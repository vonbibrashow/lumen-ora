#!/usr/bin/env python3
"""
Lumen Ora — Context Shell
The user-facing AI interface. Everything you type goes to the AI.

Usage:
    python shell.py           # interactive mode
    python shell.py --check   # connectivity check, exit 0/1
    python shell.py --voice   # enable voice mode (STT + TTS)
    python shell.py --camera  # enable camera gesture + lip-VAD input
"""

from __future__ import annotations

import argparse
import json
import os
import platform as _platform
import queue
import socket
import subprocess
import sys
import textwrap
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Platform detection — used throughout to guard OS-specific code paths
# ---------------------------------------------------------------------------

PLATFORM = _platform.system()   # "Windows", "Linux", or "Darwin"

# ---------------------------------------------------------------------------
# Optional readline (not available on Windows by default; graceful fallback)
# ---------------------------------------------------------------------------
try:
    import readline  # noqa: F401  — side-effect: enables arrow keys / history
    _READLINE = True
except ImportError:
    _READLINE = False

# ---------------------------------------------------------------------------
# Third-party deps (rich + httpx — must be installed)
# ---------------------------------------------------------------------------
try:
    import httpx
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich.spinner import Spinner
    from rich.live import Live
    from rich import box
except ImportError:
    print(
        "Missing dependencies. Run:\n"
        "    pip install httpx rich\n",
        file=sys.stderr,
    )
    sys.exit(1)

# ---------------------------------------------------------------------------
# Optional voice deps — all guarded; shell works without them
# ---------------------------------------------------------------------------

_VOICE_DEPS_OK = False
_VOICE_MISSING: list[str] = []

try:
    import sounddevice as _sd  # noqa: F401
    _SD_OK = True
except ImportError:
    _SD_OK = False
    _VOICE_MISSING.append("sounddevice")

try:
    import soundfile as _sf  # noqa: F401
    _SF_OK = True
except ImportError:
    _SF_OK = False
    _VOICE_MISSING.append("soundfile")

try:
    import keyboard as _keyboard_mod  # noqa: F401
    _KB_OK = True
except ImportError:
    _KB_OK = False
    _VOICE_MISSING.append("keyboard")

try:
    from faster_whisper import WhisperModel as _WhisperModel  # noqa: F401
    _WHISPER_OK = True
except ImportError:
    _WHISPER_OK = False
    _VOICE_MISSING.append("faster-whisper")

try:
    import pyttsx3 as _pyttsx3_mod  # noqa: F401
    _PYTTSX3_OK = True
except ImportError:
    _PYTTSX3_OK = False
    _VOICE_MISSING.append("pyttsx3")

_VOICE_DEPS_OK = not _VOICE_MISSING

# ---------------------------------------------------------------------------
# Optional camera deps — cv2 + mediapipe; shell works without them
# ---------------------------------------------------------------------------

_CAMERA_DEPS_OK = False

try:
    import cv2 as _cv2  # noqa: F401
    import mediapipe as _mp  # noqa: F401
    _CAMERA_DEPS_OK = True
except ImportError:
    _CAMERA_DEPS_OK = False

# Thread-safe queue for camera events (always created; empty when camera is off)
_camera_event_queue: queue.Queue = queue.Queue()

# Lip-VAD state (shared between camera thread and REPL)
_lip_speaking = False
_camera_thread_running = threading.Event()  # set when the camera daemon is active

# Lip-VAD thresholds
LIP_OPEN_THRESHOLD = 0.015   # normalized distance between landmarks 13 and 14
_LIP_OPEN_FRAMES_TO_START = 3   # consecutive open frames before recording starts
_LIP_CLOSE_FRAMES_TO_STOP = 8   # consecutive closed frames before recording stops

# Gesture wave detection
_WAVE_VELOCITY_THRESHOLD = 0.15  # normalized units/frame

# Env var for lip-VAD
LUMEN_LIP_VAD = os.environ.get("LUMEN_LIP_VAD", "0").strip() not in ("0", "false", "no")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BRIDGE_URL = os.environ.get("LUMEN_BRIDGE_URL", "http://127.0.0.1:8765")
POLICY_HOST = os.environ.get("LUMEN_POLICY_HOST", "127.0.0.1")
POLICY_PORT = int(os.environ.get("LUMEN_POLICY_PORT", "8766"))

# Optional API token for remote/multi-user deployments. When set, the bridge
# enforces Authorization: Bearer <token> on protected endpoints. Local-only
# users can leave this unset.
LUMEN_API_TOKEN = os.environ.get("LUMEN_API_TOKEN", "").strip()


def _auth_headers() -> dict[str, str]:
    """Return Authorization header dict if a token is configured, else {}."""
    if LUMEN_API_TOKEN:
        return {"Authorization": f"Bearer {LUMEN_API_TOKEN}"}
    return {}

LUMEN_DIR = Path.home() / ".lumen"
SESSION_FILE = LUMEN_DIR / "session_id"
HISTORY_FILE = LUMEN_DIR / "history.jsonl"
MEMORY_FILE = Path.home() / ".lumen" / "memory.jsonl"

TIMEOUT_SECONDS = 120
MAX_HISTORY_TURNS = 20
MAX_CONTEXT_TURNS = 10   # how many prior turns to send as context to the model
MAX_TOOL_RESULT_CHARS = 800

PROMPT = "lumen ▶  "   # lumen ▶
VOICE_PROMPT = "🎤 lumen ▶  "
CONTINUATION = "   ... "    # multiline continuation marker

MODEL_NAME = "Qwen2.5-7B"

# Voice config
LUMEN_WHISPER_MODEL = os.environ.get("LUMEN_WHISPER_MODEL", "base.en")
LUMEN_TTS_ENABLED = os.environ.get("LUMEN_TTS", "1").strip() not in ("0", "false", "no")

# Audio recording settings
_AUDIO_SAMPLE_RATE = 16000   # Hz — Whisper expects 16 kHz
_AUDIO_CHANNELS = 1           # mono

# ---------------------------------------------------------------------------
# Console (stderr=False so we can redirect stdout cleanly if needed)
# ---------------------------------------------------------------------------

console = Console(highlight=False)

# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def _red(s: str) -> str:
    return f"[bold red]{s}[/bold red]"

def _green(s: str) -> str:
    return f"[bold green]{s}[/bold green]"

def _dim(s: str) -> str:
    return f"[dim]{s}[/dim]"

def _yellow(s: str) -> str:
    return f"[bold yellow]{s}[/bold yellow]"

# ---------------------------------------------------------------------------
# Policy engine auto-start
# ---------------------------------------------------------------------------

# Holds the Popen handle if we started the policy engine ourselves; None otherwise.
_policy_proc: subprocess.Popen | None = None


def _win_path_to_wsl(win_path: Path) -> str:
    """
    Convert a Windows absolute path to its /mnt/... WSL2 equivalent.
    Handles both 'C:/...' and '/c/...' (Git Bash) formats.
    """
    posix = win_path.as_posix().replace("\\", "/")
    if len(posix) >= 2 and posix[1] == ":":
        # Windows: C:/Users/... → /mnt/c/Users/...
        return f"/mnt/{posix[0].lower()}/{posix[3:]}"
    if len(posix) >= 3 and posix[0] == "/" and posix[2] == "/":
        # Git Bash: /c/Users/... → /mnt/c/Users/...
        return f"/mnt/{posix[1].lower()}/{posix[3:]}"
    return posix


def ensure_policy_engine() -> bool:
    """
    Ensure the policy engine is listening on TCP 127.0.0.1:8766.

    1. If already running, return True immediately.
    2. If not, locate the binary (env var LUMEN_POLICY_BIN or default build path).
    3. On Windows: start the binary via WSL2 (wsl -d Ubuntu-22.04).
       On Linux/macOS: run the native binary directly (no WSL wrapper needed).
    4. Wait up to 5 s for port 8766 to open.
    5. Returns True if up, False if unavailable (prints a dim warning, does NOT crash).
    """
    global _policy_proc

    # --- Check if already up ---
    if socket.connect_ex(("127.0.0.1", 8766)) == 0:
        return True

    env_bin = os.environ.get("LUMEN_POLICY_BIN", "").strip()

    if PLATFORM != "Windows":
        # -----------------------------------------------------------------
        # Linux / macOS: run the native Rust binary directly (no WSL needed)
        # -----------------------------------------------------------------
        if env_bin:
            native_binary = Path(env_bin)
        else:
            native_binary = (
                Path(__file__).parent.parent
                / "policy-engine"
                / "target"
                / "debug"
                / "policy-engine"
            )

        if not native_binary.exists():
            console.print(
                _dim(
                    f"  [policy] Binary not found at {native_binary} — "
                    "run: cd prototype/policy-engine && cargo build"
                )
            )
            return False

        try:
            _policy_proc = subprocess.Popen(
                [str(native_binary)],
                env={**os.environ, "LUMEN_TCP_PORT": "8766"},
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as exc:
            console.print(_dim(f"  [policy] Failed to start policy engine: {exc}"))
            return False

    else:
        # -----------------------------------------------------------------
        # Windows: wrap the binary in WSL2
        # -----------------------------------------------------------------
        if env_bin:
            wsl_binary = env_bin
        else:
            default_win = (
                Path(__file__).parent.parent
                / "policy-engine"
                / "target"
                / "debug"
                / "policy-engine"
            )
            wsl_binary = _win_path_to_wsl(default_win)

        try:
            _policy_proc = subprocess.Popen(
                [
                    "wsl", "-d", "Ubuntu-22.04", "--",
                    "env", "LUMEN_TCP_PORT=8766",
                    wsl_binary,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            # wsl not found on this machine
            console.print(_dim("  [policy] wsl not found — policy engine unavailable."))
            return False
        except Exception as exc:
            console.print(_dim(f"  [policy] Failed to start policy engine: {exc}"))
            return False

    # --- Wait up to 5 s for the port to open ---
    for _ in range(10):
        time.sleep(0.5)
        if socket.connect_ex(("127.0.0.1", 8766)) == 0:
            return True

    # Did not come up in time
    console.print(_dim("  [policy] Policy engine did not bind within 5 s — running without enforcement."))
    return False


# ---------------------------------------------------------------------------
# Lumen directory setup
# ---------------------------------------------------------------------------

def ensure_lumen_dir() -> None:
    LUMEN_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Whisper model pre-download / cache warm-up
# ---------------------------------------------------------------------------

def ensure_whisper_model() -> None:
    """
    Pre-download the Whisper model so it is cached before the REPL starts.
    Call this at startup when --voice is passed.
    faster-whisper caches models in ~/.cache/huggingface/hub.
    """
    if not _WHISPER_OK:
        return

    # Check whether the model directory already exists in the HF cache
    hf_hub_cache = Path.home() / ".cache" / "huggingface" / "hub"
    cache_exists = hf_hub_cache.exists() and any(
        p.name.lower().startswith("whisper") or "whisper" in p.name.lower()
        for p in hf_hub_cache.iterdir()
        if p.is_dir()
    ) if hf_hub_cache.exists() else False

    if not cache_exists:
        console.print(_dim("  Whisper model: downloading..."))

    try:
        from faster_whisper import WhisperModel
        _model = WhisperModel(LUMEN_WHISPER_MODEL, device="cpu", compute_type="int8")
        # Store on the global voice engine singleton so it is reused
        engine = _get_voice_engine()
        engine._whisper = _model
        console.print(_dim("  Whisper model: ready"))
    except Exception as exc:
        console.print(_red(f"  Whisper model: failed to load ({exc})"))

# ---------------------------------------------------------------------------
# Session ID — persisted across restarts
# ---------------------------------------------------------------------------

def load_or_create_session_id() -> str:
    ensure_lumen_dir()
    if SESSION_FILE.exists():
        sid = SESSION_FILE.read_text().strip()
        if sid:
            return sid
    sid = str(uuid.uuid4())
    SESSION_FILE.write_text(sid)
    return sid

# ---------------------------------------------------------------------------
# History — last N turns in JSONL
# ---------------------------------------------------------------------------

def append_history(user_text: str, ai_text: str) -> None:
    ensure_lumen_dir()
    entry = {
        "ts": datetime.utcnow().isoformat(),
        "user": user_text,
        "ai": ai_text,
    }
    with HISTORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def load_history(n: int = MAX_HISTORY_TURNS) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    lines = HISTORY_FILE.read_text(encoding="utf-8").splitlines()
    entries = []
    for line in lines:
        line = line.strip()
        if line:
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return entries[-n:]

def trim_history() -> None:
    """Keep only the last MAX_HISTORY_TURNS entries."""
    entries = load_history(MAX_HISTORY_TURNS)
    ensure_lumen_dir()
    with HISTORY_FILE.open("w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e) + "\n")

# ---------------------------------------------------------------------------
# Long-term memory — ~/.lumen/memory.jsonl
# ---------------------------------------------------------------------------

# Module-level memory state and model tier
_memory: list[dict] = []
_model_tier: str = "smart"


def load_memory(max_facts: int = 20) -> list[dict]:
    """Load the most recent max_facts entries from ~/.lumen/memory.jsonl."""
    if not MEMORY_FILE.exists():
        return []
    lines = MEMORY_FILE.read_text(encoding="utf-8").splitlines()
    facts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            facts.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return facts[-max_facts:]


def save_memory_fact(fact: str, tag: str = "general") -> None:
    """Append a single fact to ~/.lumen/memory.jsonl."""
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {"fact": fact, "tag": tag, "created": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with MEMORY_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def build_memory_context(facts: list[dict]) -> str:
    """Build a memory context string to prepend to the system prompt."""
    if not facts:
        return ""
    lines = [f"- {f['fact']}" for f in facts]
    return "Known facts about the user:\n" + "\n".join(lines)

# ---------------------------------------------------------------------------
# Connectivity checks
# ---------------------------------------------------------------------------

def check_bridge() -> tuple[bool, str]:
    """Return (ok, detail)."""
    try:
        r = httpx.get(f"{BRIDGE_URL}/health", timeout=4.0, headers=_auth_headers())
        if r.status_code == 200:
            data = r.json()
            if data.get("auth_required") and not LUMEN_API_TOKEN:
                return False, "auth required — set LUMEN_API_TOKEN"
            return True, data.get("version", "ok")
        if r.status_code == 401:
            return False, "auth required — set LUMEN_API_TOKEN"
        return False, f"HTTP {r.status_code}"
    except httpx.ConnectError:
        return False, "connection refused"
    except httpx.TimeoutException:
        return False, "timeout"
    except Exception as exc:
        return False, str(exc)


def check_policy() -> tuple[bool, str]:
    """Return (ok, detail) — TCP connect to policy engine."""
    import socket
    try:
        sock = socket.create_connection((POLICY_HOST, POLICY_PORT), timeout=3.0)
        sock.close()
        return True, "connected"
    except (ConnectionRefusedError, OSError):
        return False, "connection refused"
    except Exception as exc:
        return False, str(exc)

# ---------------------------------------------------------------------------
# Startup banner
# ---------------------------------------------------------------------------

def print_banner(
    bridge_ok: bool,
    policy_ok: bool,
    voice_mode: bool = False,
    camera_mode: bool = False,
) -> None:
    bridge_status = (
        _green("Bridge: connected") if bridge_ok else _red("Bridge: not running")
    )
    policy_status = (
        _green("Policy Engine: connected") if policy_ok else _red("Policy Engine: not running")
    )
    model_status = _green("Model: ready") if bridge_ok else _dim("Model: unknown")

    width = console.width or 60
    divider = "─" * width  # ──────

    console.print()
    console.print(
        f"[bold cyan]Lumen Ora[/bold cyan]  [dim]·[/dim]  [cyan]AI Shell[/cyan]"
        f"  [dim]·[/dim]  [cyan]{MODEL_NAME}[/cyan]"
    )
    console.print(
        f"{policy_status}  [dim]|[/dim]  {bridge_status}  [dim]|[/dim]  {model_status}"
    )

    hints: list[str] = []
    if voice_mode:
        hints.append("Hold Space to speak / press Enter to type.")
    if camera_mode:
        hints.append("Camera: gesture+lip-vad active")
    hints.append("/help for commands.")
    console.print(f"[dim]{' '.join(hints)}[/dim]")
    console.print(f"[dim]{divider}[/dim]")
    console.print()

# ---------------------------------------------------------------------------
# Inference call
# ---------------------------------------------------------------------------

def call_bridge(prompt: str, session_id: str, messages: list[dict] | None = None) -> dict:
    """
    POST /infer to the bridge.
    messages is the prior conversation context [{role, content}, ...].
    Prepends long-term memory context and passes model_tier.
    """
    conversation = messages or []
    memory_ctx = build_memory_context(_memory)
    if memory_ctx:
        messages_to_send = [
            {"role": "user", "content": f"[Context]\n{memory_ctx}"},
            {"role": "assistant", "content": "Understood."},
        ] + conversation
    else:
        messages_to_send = conversation

    payload = {
        "prompt": prompt,
        "session_id": session_id,
        "stream": False,
        "messages": messages_to_send,
        "model_tier": _model_tier,
    }
    try:
        r = httpx.post(
            f"{BRIDGE_URL}/infer",
            json=payload,
            timeout=TIMEOUT_SECONDS,
            headers=_auth_headers(),
        )
        if r.status_code == 401:
            raise PermissionError(
                "Bridge requires authentication. Set LUMEN_API_TOKEN to the bridge's token."
            )
        r.raise_for_status()
        return r.json()
    except httpx.TimeoutException as exc:
        raise TimeoutError("Model taking too long — try a simpler request") from exc

# ---------------------------------------------------------------------------
# Response rendering
# ---------------------------------------------------------------------------

def _truncate(s: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(s) <= max_chars:
        return s
    return s[:max_chars] + f"\n[dim]… ({len(s) - max_chars} more chars)[/dim]"


def render_response(data: dict) -> tuple[bool, str]:
    """
    Render the bridge response.
    Returns (require_confirmation, prose_text).
    prose_text is the AI's prose text only (suitable for TTS); tool panels excluded.
    """
    text: str = data.get("text", "")
    tool_calls: list = data.get("tool_calls", [])
    # policy_decisions may be a top-level list (future) or embedded per-tool-call
    policy_decisions: list = data.get("policy_decisions", [])
    finish_reason: str = data.get("finish_reason", "stop")

    # --- Prose text ---
    prose_text = ""
    if text.strip():
        width = (console.width or 80) - 4
        wrapped = textwrap.fill(text.strip(), width=width)
        console.print()
        console.print(wrapped)
        prose_text = text.strip()

    # --- Tool call results ---
    for tc in tool_calls:
        tool_name = tc.get("tool_name", "unknown")
        result = tc.get("result")
        error = tc.get("error")
        policy_obj = tc.get("policy", {}) or {}
        decision = policy_obj.get("decision", "Allow")
        detail = policy_obj.get("detail", "")

        # Policy blocked?
        if decision == "Deny":
            console.print(
                Panel(
                    _red(f"Policy blocked: {detail or 'no reason given'}"),
                    title=f"[red]Denied — {tool_name}[/red]",
                    border_style="red",
                    box=box.ROUNDED,
                )
            )
            continue

        # Policy requires confirmation?
        if decision == "RequireConfirmation":
            console.print()
            console.print(
                Panel(
                    f"[yellow]The AI wants to run:[/yellow] [bold]{tool_name}[/bold]\n"
                    f"[dim]{detail or 'No additional detail.'}[/dim]",
                    title="[yellow]Action Requires Confirmation[/yellow]",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )
            try:
                answer = input("Proceed? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                answer = "n"
            if answer not in ("y", "yes"):
                console.print(_dim("  Action cancelled."))
                continue
            # User confirmed — if there's a result it will already be in the payload,
            # otherwise we surface the error.

        # Show tool result in a dim box
        if result is not None:
            result_str = (
                json.dumps(result, indent=2) if not isinstance(result, str) else result
            )
            console.print(
                Panel(
                    _dim(_truncate(result_str)),
                    title=f"[dim]Tool: {tool_name}[/dim]",
                    border_style="bright_black",
                    box=box.SIMPLE,
                )
            )
        elif error:
            console.print(
                Panel(
                    _red(_truncate(str(error))),
                    title=f"[dim]Tool error: {tool_name}[/dim]",
                    border_style="red",
                    box=box.SIMPLE,
                )
            )

    # --- Top-level policy decisions (if bridge ever adds them) ---
    for pd in policy_decisions:
        if isinstance(pd, dict) and pd.get("decision") == "Deny":
            reason = pd.get("detail") or pd.get("reason") or "no reason given"
            console.print(_red(f"\nPolicy blocked: {reason}"))

    console.print()
    return False, prose_text


# ---------------------------------------------------------------------------
# Voice subsystem
# ---------------------------------------------------------------------------

class VoiceEngine:
    """
    Manages STT (faster-whisper) and TTS (pyttsx3).
    All methods are no-ops when voice deps are unavailable.
    """

    def __init__(self) -> None:
        self._whisper: object = None          # WhisperModel instance (reused across PTT calls)
        self._tts_engine: object = None
        self._tts_lock = threading.Lock()
        self._recording = False
        self._audio_frames: list = []

    # ------------------------------------------------------------------
    # Lazy init
    # ------------------------------------------------------------------

    def _ensure_whisper(self) -> bool:
        if not _WHISPER_OK:
            return False
        if self._whisper is None:
            from faster_whisper import WhisperModel
            console.print(_dim(f"[voice] Loading Whisper model '{LUMEN_WHISPER_MODEL}'…"))
            self._whisper = WhisperModel(
                LUMEN_WHISPER_MODEL,
                device="cpu",
                compute_type="int8",
            )
            console.print(_dim("[voice] Whisper ready."))
        return True

    def _ensure_tts(self) -> bool:
        if not _PYTTSX3_OK:
            return False
        if self._tts_engine is None:
            import pyttsx3
            self._tts_engine = pyttsx3.init()
            # Sensible defaults for Windows SAPI
            self._tts_engine.setProperty("rate", 175)
        return True

    # ------------------------------------------------------------------
    # Audio device helpers
    # ------------------------------------------------------------------

    @staticmethod
    def list_audio_devices() -> str:
        """Return a compact summary string of available audio input devices."""
        if not _SD_OK:
            return "(sounddevice not installed)"
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            inputs = [
                f"{i}: {d['name']}"
                for i, d in enumerate(devices)
                if d.get("max_input_channels", 0) > 0
            ]
            return ", ".join(inputs) if inputs else "(none found)"
        except Exception as exc:
            return f"(error querying devices: {exc})"

    # ------------------------------------------------------------------
    # Push-to-talk recording
    # ------------------------------------------------------------------

    def start_recording(self) -> bool:
        """Begin capturing audio from the default mic. Returns False if unavailable."""
        if not (_SD_OK and _SF_OK):
            return False
        import sounddevice as sd

        self._audio_frames = []
        self._recording = True

        def _callback(indata, frames, time, status):
            if self._recording:
                self._audio_frames.append(indata.copy())

        try:
            self._stream = sd.InputStream(
                samplerate=_AUDIO_SAMPLE_RATE,
                channels=_AUDIO_CHANNELS,
                dtype="float32",
                callback=_callback,
            )
            self._stream.start()
        except Exception:
            self._recording = False
            available = self.list_audio_devices()
            console.print(
                _red(f"No mic found. Available inputs: {available}")
            )
            return False
        return True

    def stop_recording(self) -> "np.ndarray | None":
        """Stop recording and return the audio array (float32, 16 kHz mono)."""
        self._recording = False
        if not hasattr(self, "_stream"):
            return None
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            pass
        if not self._audio_frames:
            return None
        import numpy as np
        audio = np.concatenate(self._audio_frames, axis=0)
        return audio.flatten()

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def transcribe(self, audio_array: "np.ndarray") -> str:
        """Transcribe audio array to text. Returns '' on failure."""
        if not self._ensure_whisper():
            return ""
        try:
            segments, _info = self._whisper.transcribe(
                audio_array,
                beam_size=5,
                language="en",
                condition_on_previous_text=False,
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            return text
        except Exception as exc:
            console.print(_red(f"[voice] Transcription error: {exc}"))
            return ""

    # ------------------------------------------------------------------
    # Text-to-speech
    # ------------------------------------------------------------------

    def speak(self, text: str) -> None:
        """Speak text using pyttsx3. No-op if TTS disabled or unavailable."""
        if not LUMEN_TTS_ENABLED:
            return
        if not self._ensure_tts():
            return

        # Run TTS in a background thread so it doesn't block the REPL
        def _speak():
            with self._tts_lock:
                try:
                    self._tts_engine.say(text)
                    self._tts_engine.runAndWait()
                except Exception as exc:
                    console.print(_red(f"[voice] TTS error: {exc}"))

        t = threading.Thread(target=_speak, daemon=True)
        t.start()

    # ------------------------------------------------------------------
    # Push-to-talk: blocking record-until-Space-released
    # ------------------------------------------------------------------

    def push_to_talk(self) -> str:
        """
        Record audio while Space is held; transcribe on release.
        Returns transcribed text, or '' if nothing usable.
        Requires keyboard + sounddevice + soundfile + faster-whisper.

        Safety: recording is capped at 30 seconds to prevent accidental
        indefinite holds.
        """
        if not (_KB_OK and _SD_OK and _SF_OK and _WHISPER_OK):
            return ""

        import keyboard

        console.print(_dim("  [recording…] Release Space when done (max 30 s)."), end="\r")

        ok = self.start_recording()
        if not ok:
            # start_recording already printed the error message
            return ""

        # Block until Space key is released, with a 30-second safety cap.
        # keyboard.wait() has no built-in timeout; we use a daemon thread to
        # enforce the cap by programmatically releasing the wait.
        _MAX_RECORD_SECONDS = 30
        _timed_out = [False]

        def _timeout_guard():
            import time
            time.sleep(_MAX_RECORD_SECONDS)
            if self._recording:
                _timed_out[0] = True
                # Trigger the release event so keyboard.wait() unblocks
                try:
                    keyboard.release("space")
                except Exception:
                    pass

        _guard = threading.Thread(target=_timeout_guard, daemon=True)
        _guard.start()

        try:
            keyboard.wait("space", suppress=True, trigger_on_release=True)
        except Exception:
            pass

        audio = self.stop_recording()
        console.print(" " * 60, end="\r")  # clear the recording line

        if _timed_out[0]:
            console.print(_dim("  (recording capped at 30 s)"))

        if audio is None or len(audio) < _AUDIO_SAMPLE_RATE * 0.3:
            # Less than 300 ms of audio — ignore (likely accidental tap)
            console.print(_dim("  (recording too short, ignored)"))
            return ""

        console.print(_dim("  [transcribing…]"), end="\r")
        text = self.transcribe(audio)
        console.print(" " * 60, end="\r")  # clear the transcribing line

        if text:
            console.print(f"  [dim]You said:[/dim] {text}")
        return text


# Module-level singleton — created lazily on first voice use
_voice_engine: VoiceEngine | None = None


def _get_voice_engine() -> VoiceEngine:
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = VoiceEngine()
    return _voice_engine


# ---------------------------------------------------------------------------
# Camera subsystem — gesture recognition + lip-VAD
# ---------------------------------------------------------------------------

def _classify_gesture(hand_landmarks, handedness_label: str) -> str | None:
    """
    Classify a hand gesture from MediaPipe hand landmarks.
    Returns one of: 'thumbs_up', 'open_palm', 'peace', 'wave', or None.

    Landmark indices used:
        4  = thumb tip
        3  = thumb IP
        8  = index tip
        6  = index PIP
        12 = middle tip
        10 = middle PIP
        16 = ring tip
        14 = ring PIP
        20 = pinky tip
        18 = pinky PIP
        0  = wrist
        9  = middle MCP (base)
    """
    lm = hand_landmarks.landmark

    # Helper: is a finger extended? (tip above PIP in y-axis; y increases downward)
    def _extended(tip_idx: int, pip_idx: int) -> bool:
        return lm[tip_idx].y < lm[pip_idx].y

    index_ext = _extended(8, 6)
    middle_ext = _extended(12, 10)
    ring_ext = _extended(16, 14)
    pinky_ext = _extended(20, 18)

    # Thumb: compare x-position relative to IP joint (handedness-aware)
    if handedness_label == "Right":
        thumb_ext = lm[4].x < lm[3].x
    else:
        thumb_ext = lm[4].x > lm[3].x

    fingers_up = sum([index_ext, middle_ext, ring_ext, pinky_ext])

    # Open palm: all 4 fingers + thumb extended
    if thumb_ext and fingers_up == 4:
        return "open_palm"

    # Peace/V sign: index + middle extended, ring + pinky folded
    if index_ext and middle_ext and not ring_ext and not pinky_ext:
        return "peace"

    # Thumbs up: only thumb extended, all fingers folded
    if thumb_ext and fingers_up == 0:
        return "thumbs_up"

    return None


def _camera_worker(stop_event: threading.Event, voice_state_ref: list) -> None:
    """
    Background daemon thread: runs MediaPipe hand + face mesh detection.
    Posts events to _camera_event_queue.
    voice_state_ref is a one-element list holding the voice_state dict so
    we can toggle voice from this thread.
    """
    global _lip_speaking

    try:
        import cv2
        import mediapipe as mp
    except ImportError:
        return

    mp_hands = mp.solutions.hands
    mp_face_mesh = mp.solutions.face_mesh

    hands_detector = mp_hands.Hands(
        max_num_hands=1,
        min_detection_confidence=0.7,
        min_tracking_confidence=0.5,
    )
    face_detector = mp_face_mesh.FaceMesh(
        max_num_faces=1,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5,
        refine_landmarks=True,
    )

    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        console.print(_red("[camera] Could not open camera device."))
        return

    # --- State for gesture debounce ---
    _last_gesture: str | None = None
    _gesture_cooldown = 0          # frames to suppress repeated gesture firing
    _GESTURE_COOLDOWN_FRAMES = 20  # ~0.67 s at 30 fps

    # --- State for wave detection ---
    _prev_wrist_x: float | None = None
    _wrist_dx_history: list[float] = []
    _WAVE_HISTORY = 6  # frames

    # --- State for lip-VAD ---
    _lip_open_count = 0
    _lip_close_count = 0

    _camera_thread_running.set()

    try:
        while not stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                continue

            # Convert BGR → RGB once for both detectors
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False

            # ----------------------------------------------------------------
            # Hand / gesture detection
            # ----------------------------------------------------------------
            hand_results = hands_detector.process(rgb)

            gesture: str | None = None
            if hand_results.multi_hand_landmarks:
                hand_lm = hand_results.multi_hand_landmarks[0]
                handedness = (
                    hand_results.multi_handedness[0].classification[0].label
                    if hand_results.multi_handedness
                    else "Right"
                )

                # Wave: track wrist x-velocity
                wrist_x = hand_lm.landmark[0].x
                if _prev_wrist_x is not None:
                    dx = abs(wrist_x - _prev_wrist_x)
                    _wrist_dx_history.append(dx)
                    if len(_wrist_dx_history) > _WAVE_HISTORY:
                        _wrist_dx_history.pop(0)
                    avg_velocity = sum(_wrist_dx_history) / len(_wrist_dx_history)
                    if avg_velocity > _WAVE_VELOCITY_THRESHOLD:
                        gesture = "wave"
                _prev_wrist_x = wrist_x

                if gesture is None:
                    gesture = _classify_gesture(hand_lm, handedness)
            else:
                _prev_wrist_x = None
                _wrist_dx_history.clear()

            # Fire gesture event (with cooldown to avoid repeated triggers)
            if gesture is not None and _gesture_cooldown == 0:
                event: str | None = None
                if gesture == "thumbs_up":
                    event = "confirm"
                elif gesture == "open_palm":
                    event = "cancel"
                elif gesture == "peace":
                    event = "voice_toggle"
                elif gesture == "wave":
                    event = "new_session"

                if event is not None and event != _last_gesture:
                    _camera_event_queue.put(event)
                    _last_gesture = event
                    _gesture_cooldown = _GESTURE_COOLDOWN_FRAMES
            elif _gesture_cooldown > 0:
                _gesture_cooldown -= 1
                if gesture is None:
                    _last_gesture = None

            # ----------------------------------------------------------------
            # Lip-VAD (only when LUMEN_LIP_VAD env var is set)
            # ----------------------------------------------------------------
            if LUMEN_LIP_VAD:
                face_results = face_detector.process(rgb)
                if face_results.multi_face_landmarks:
                    face_lm = face_results.multi_face_landmarks[0].landmark
                    # Landmarks 13 = upper lip inner, 14 = lower lip inner
                    upper_lip_y = face_lm[13].y
                    lower_lip_y = face_lm[14].y
                    lip_distance = abs(lower_lip_y - upper_lip_y)

                    if lip_distance > LIP_OPEN_THRESHOLD:
                        _lip_open_count += 1
                        _lip_close_count = 0
                    else:
                        _lip_close_count += 1
                        _lip_open_count = 0

                    # Transition: closed → speaking
                    if (
                        not _lip_speaking
                        and _lip_open_count >= _LIP_OPEN_FRAMES_TO_START
                    ):
                        _lip_speaking = True
                        _camera_event_queue.put("lip_start")

                    # Transition: speaking → stopped
                    elif (
                        _lip_speaking
                        and _lip_close_count >= _LIP_CLOSE_FRAMES_TO_STOP
                    ):
                        _lip_speaking = False
                        _camera_event_queue.put("lip_stop")
                else:
                    # No face detected — reset lip state silently (fall back to PTT)
                    _lip_open_count = 0
                    _lip_close_count = 0
                    if _lip_speaking:
                        _lip_speaking = False
                        _camera_event_queue.put("lip_stop")

    finally:
        _camera_thread_running.clear()
        hands_detector.close()
        face_detector.close()
        cap.release()


# Module-level camera state
_camera_stop_event: threading.Event | None = None
_camera_bg_thread: threading.Thread | None = None


def start_camera(voice_state: dict) -> bool:
    """
    Start the camera background thread.
    Returns True if started successfully, False otherwise.
    Guarded: silently no-ops if cv2/mediapipe are unavailable.
    """
    global _camera_stop_event, _camera_bg_thread

    if not _CAMERA_DEPS_OK:
        return False

    if _camera_bg_thread is not None and _camera_bg_thread.is_alive():
        return True  # already running

    _camera_stop_event = threading.Event()
    voice_state_ref = [voice_state]  # mutable container for cross-thread access

    _camera_bg_thread = threading.Thread(
        target=_camera_worker,
        args=(_camera_stop_event, voice_state_ref),
        daemon=True,
        name="lumen-camera",
    )
    _camera_bg_thread.start()
    return True


def stop_camera() -> None:
    """Signal the camera thread to stop."""
    global _camera_stop_event
    if _camera_stop_event is not None:
        _camera_stop_event.set()
    _camera_thread_running.clear()


def camera_is_running() -> bool:
    """Return True if the camera daemon thread is active."""
    return _camera_thread_running.is_set()


# ---------------------------------------------------------------------------
# Special / commands
# ---------------------------------------------------------------------------

def cmd_help(voice_mode: bool = False) -> None:
    lines = [
        "[bold]/help[/bold]              — show this help",
        "[bold]/exit[/bold]              — exit the shell (also Ctrl+D)",
        "[bold]/quit[/bold]              — exit the shell",
        "[bold]/clear[/bold]             — clear screen and reset display",
        "[bold]/new[/bold]               — start a fresh conversation (clears context)",
        "[bold]/history[/bold]           — show last 10 exchanges",
        "[bold]/session[/bold]           — show session ID and history stats",
        "[bold]/model fast|smart[/bold]  — switch model tier: fast (3B) or smart (7B)",
        "[bold]/model[/bold]             — show current model tier",
        "[bold]/remember <fact>[/bold]   — save a fact to long-term memory",
        "[bold]/memory[/bold]            — list all remembered facts",
        "[bold]/forget <n>[/bold]        — remove fact at index n from memory",
        "[bold]/voice on[/bold]          — enable voice mode (STT + TTS)",
        "[bold]/voice off[/bold]         — disable voice mode",
        "[bold]/voice check[/bold]       — check voice subsystem (mic, STT, TTS)",
        "[bold]/camera on[/bold]         — enable camera gesture + lip-VAD input",
        "[bold]/camera off[/bold]        — disable camera gesture + lip-VAD input",
    ]
    console.print(
        Panel(
            "\n".join(lines),
            title="[cyan]Lumen Ora — Commands[/cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


def cmd_voice_check() -> None:
    """
    Run a voice subsystem health check and print a formatted report.
    Checks faster-whisper, pyttsx3, sounddevice, audio inputs, and TTS.
    """
    console.print()
    console.print("[bold]Voice subsystem check:[/bold]")

    # ── faster-whisper ────────────────────────────────────────────────────────
    try:
        import faster_whisper  # noqa: F401
        fw_status = "[green]OK[/green]    installed"
    except ImportError:
        fw_status = "[red]MISSING[/red]  run: pip install faster-whisper"
    console.print(f"  faster-whisper : {fw_status}")

    # ── pyttsx3 ───────────────────────────────────────────────────────────────
    try:
        import pyttsx3 as _p3  # noqa: F401
        p3_status = "[green]OK[/green]    installed"
    except ImportError:
        p3_status = "[red]MISSING[/red]  run: pip install pyttsx3"
    console.print(f"  pyttsx3        : {p3_status}")

    # ── sounddevice ───────────────────────────────────────────────────────────
    try:
        import sounddevice as _sd_chk  # noqa: F401
        sd_status = "[green]OK[/green]    installed"
    except ImportError:
        sd_status = "[red]MISSING[/red]  run: pip install sounddevice"
    console.print(f"  sounddevice    : {sd_status}")

    # ── microphone ────────────────────────────────────────────────────────────
    mic_label = "(sounddevice not installed)"
    if _SD_OK:
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            inputs = [
                d for d in devices
                if d.get("max_input_channels", 0) > 0
            ]
            if inputs:
                # Try to find the default input
                try:
                    default_idx = sd.default.device[0]
                    default_dev = devices[default_idx]
                    mic_label = f"{default_dev['name']} (default)"
                except Exception:
                    mic_label = inputs[0]["name"]
            else:
                mic_label = "[red]MISSING[/red]  no input devices found"
        except Exception as exc:
            mic_label = f"[red]ERROR[/red]   {exc}"
    console.print(f"  microphone     : {mic_label}")

    # ── TTS ───────────────────────────────────────────────────────────────────
    tts_status = "(pyttsx3 not installed)"
    if _PYTTSX3_OK:
        try:
            import pyttsx3
            _engine = pyttsx3.init()
            _engine.setProperty("rate", 175)
            _engine.say("Voice check OK")
            _engine.runAndWait()
            tts_status = "[green]OK[/green]    speaking test"
        except Exception as exc:
            tts_status = f"[red]ERROR[/red]   {exc}"
    console.print(f"  TTS            : {tts_status}")
    console.print()


def cmd_history() -> None:
    entries = load_history(10)
    if not entries:
        console.print(_dim("No history yet."))
        return
    for i, e in enumerate(entries, 1):
        ts = e.get("ts", "")[:19].replace("T", " ")
        user_text = e.get("user", "")[:80]
        ai_text = e.get("ai", "")[:120]
        console.print(f"[dim]{i:2}. [{ts}][/dim]")
        console.print(f"    [bold]You:[/bold] {user_text}")
        console.print(f"    [cyan]AI:[/cyan]  {ai_text}")
        console.print()


def cmd_model(tier: str | None = None) -> None:
    global _model_tier
    if tier == "fast":
        _model_tier = "fast"
        console.print(_green("Switched to fast model (3B)"))
        return
    if tier == "smart":
        _model_tier = "smart"
        console.print(_green("Switched to smart model (7B)"))
        return
    # Show current state
    bridge_ok, detail = check_bridge()
    tier_label = "fast (3B)" if _model_tier == "fast" else "smart (7B)"
    if bridge_ok:
        console.print(
            f"Model tier: [cyan]{tier_label}[/cyan]  "
            f"[dim]base: {MODEL_NAME}  bridge: {detail}[/dim]"
        )
    else:
        console.print(
            f"Model tier: [cyan]{tier_label}[/cyan]  "
            + _red(f"(bridge not reachable: {detail})")
        )


def cmd_session(session_id: str, conversation: list[dict]) -> None:
    entries = load_history()
    console.print(f"Session ID:  [dim]{session_id}[/dim]")
    console.print(f"Context:     [cyan]{len(conversation) // 2}[/cyan] turns in memory")
    console.print(f"History:     [cyan]{len(entries)}[/cyan] turns on disk  ({HISTORY_FILE})")


def handle_special(
    cmd: str,
    session_id: str = "",
    conversation: list[dict] | None = None,
    voice_state: dict | None = None,
    camera_state: dict | None = None,
) -> bool:
    """
    Handle /commands. Return True if handled (caller should not send to AI).
    Return False if not a special command.
    voice_state is a mutable dict with key 'enabled' (bool).
    camera_state is a mutable dict with key 'enabled' (bool).
    """
    global _memory
    stripped = cmd.strip()
    if not stripped.startswith("/"):
        return False

    parts = stripped.split(None, 1)
    verb = parts[0].lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if verb in ("/exit", "/quit"):
        console.print("[dim]Goodbye.[/dim]")
        sys.exit(0)

    if verb == "/clear":
        console.clear()
        return True

    if verb == "/new":
        if conversation is not None:
            conversation.clear()
        console.print(_dim("Conversation context cleared. Starting fresh."))
        return True

    if verb == "/history":
        cmd_history()
        return True

    if verb == "/session":
        cmd_session(session_id, conversation or [])
        return True

    if verb == "/model":
        cmd_model(rest if rest in ("fast", "smart") else None)
        return True

    if verb == "/remember":
        if not rest:
            console.print(_dim("Usage: /remember <fact>"))
            return True
        save_memory_fact(rest)
        _memory = load_memory()
        console.print(_green(f"Remembered: {rest}"))
        return True

    if verb == "/memory":
        if not _memory:
            console.print(_dim("No facts in memory yet. Use /remember <fact> to add one."))
        else:
            for i, f in enumerate(_memory):
                tag = f.get("tag", "general")
                created = f.get("created", "")[:10]
                console.print(f"  [dim]{i}.[/dim] {f['fact']}  [dim][{tag}  {created}][/dim]")
        return True

    if verb == "/forget":
        if not rest.strip().isdigit():
            console.print(_dim("Usage: /forget <n>  (use /memory to list indices)"))
            return True
        idx = int(rest.strip())
        all_facts = load_memory(max_facts=9999)
        if idx < 0 or idx >= len(all_facts):
            console.print(_red(f"Index {idx} out of range (0–{len(all_facts) - 1})."))
            return True
        removed = all_facts.pop(idx)
        # Rewrite the file without that line
        MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        with MEMORY_FILE.open("w", encoding="utf-8") as _f:
            for _entry in all_facts:
                _f.write(json.dumps(_entry) + "\n")
        _memory = load_memory()
        console.print(_dim(f"Forgotten: {removed['fact']}"))
        return True

    if verb == "/help":
        cmd_help(voice_state.get("enabled", False) if voice_state else False)
        return True

    if verb == "/voice":
        if rest == "check":
            cmd_voice_check()
            return True
        if voice_state is None:
            console.print(_dim("/voice requires an active shell session."))
            return True
        if rest == "on":
            if not _VOICE_DEPS_OK:
                console.print(
                    _red(
                        "Voice mode unavailable — missing packages: "
                        + ", ".join(_VOICE_MISSING)
                        + "\nRun: pip install faster-whisper sounddevice soundfile keyboard pyttsx3"
                    )
                )
            else:
                voice_state["enabled"] = True
                console.print(_green("Voice mode enabled. Hold Space to speak."))
        elif rest == "off":
            voice_state["enabled"] = False
            console.print(_dim("Voice mode disabled."))
        else:
            status = "on" if voice_state.get("enabled") else "off"
            console.print(
                f"Voice mode is currently [bold]{status}[/bold]. "
                "Use [bold]/voice on[/bold], [bold]/voice off[/bold], "
                "or [bold]/voice check[/bold]."
            )
        return True

    if verb == "/camera":
        if camera_state is None:
            console.print(_dim("/camera requires an active shell session."))
            return True
        if rest == "on":
            if not _CAMERA_DEPS_OK:
                console.print(
                    "Camera deps not installed: pip install opencv-python mediapipe"
                )
            else:
                if not camera_state.get("enabled"):
                    camera_state["enabled"] = True
                    vs = voice_state or {}
                    ok = start_camera(vs)
                    if ok:
                        console.print(_green("Camera mode enabled. Gesture + lip-VAD active."))
                    else:
                        camera_state["enabled"] = False
                        console.print(_red("Camera failed to start. Is a camera device connected?"))
                else:
                    console.print(_dim("Camera is already running."))
        elif rest == "off":
            camera_state["enabled"] = False
            stop_camera()
            console.print(_dim("Camera mode disabled."))
        else:
            status = "on" if camera_state.get("enabled") else "off"
            console.print(
                f"Camera mode is currently [bold]{status}[/bold]. "
                "Use [bold]/camera on[/bold] or [bold]/camera off[/bold]."
            )
        return True

    # Unknown slash command — let the AI handle it (return False)
    return False

# ---------------------------------------------------------------------------
# Spinner helper
# ---------------------------------------------------------------------------

def infer_with_spinner(prompt: str, session_id: str, messages: list[dict]) -> dict:
    """Run inference with a spinner while waiting."""
    result: dict = {}
    error_info: list[Exception] = []

    spinner_done = threading.Event()

    def _infer():
        try:
            result.update(call_bridge(prompt, session_id, messages))
        except Exception as exc:
            error_info.append(exc)
        finally:
            spinner_done.set()

    t = threading.Thread(target=_infer, daemon=True)
    t.start()

    with Live(
        Spinner("dots", text=Text("Thinking…", style="dim")),
        console=console,
        refresh_per_second=10,
        transient=True,
    ):
        spinner_done.wait()

    if error_info:
        raise error_info[0]

    return result

# ---------------------------------------------------------------------------
# Voice-aware input
# ---------------------------------------------------------------------------

def _read_voice_or_text(voice_state: dict, prompt_str: str) -> str | None:
    """
    Read user input.
    - In voice mode: waits for either a Space keydown (→ push-to-talk) or any
      other key (→ falls through to normal text input).
    - In text mode (or when voice deps unavailable): plain input().
    Returns the input string, or None to re-prompt (e.g. after Ctrl+C).
    Raises EOFError when the user signals end-of-file (Ctrl+D).
    """
    if not voice_state.get("enabled") or not _VOICE_DEPS_OK:
        try:
            return input(prompt_str)
        except EOFError:
            raise
        except KeyboardInterrupt:
            console.print()
            return None

    # --- Voice mode ---
    import keyboard

    # Print the prompt without a newline so it appears inline.
    sys.stdout.write(prompt_str)
    sys.stdout.flush()

    try:
        event = keyboard.read_event(suppress=False)
        if event.event_type == "down" and event.name == "space":
            # Clear the prompt line
            sys.stdout.write("\r" + " " * (len(prompt_str) + 2) + "\r")
            sys.stdout.flush()
            ve = _get_voice_engine()
            text = ve.push_to_talk()
            return text if text else ""
        else:
            # A non-Space key was pressed; clear and fall back to normal input
            sys.stdout.write("\r" + " " * (len(prompt_str) + 2) + "\r")
            sys.stdout.flush()
            return input(prompt_str)
    except EOFError:
        raise
    except KeyboardInterrupt:
        console.print()
        return None
    except Exception:
        # keyboard module failed or unavailable at runtime — fall back
        try:
            return input(prompt_str)
        except EOFError:
            raise
        except KeyboardInterrupt:
            console.print()
            return None


# ---------------------------------------------------------------------------
# Camera event handler (called inside REPL loop)
# ---------------------------------------------------------------------------

def _drain_camera_events(
    voice_state: dict,
    conversation: list[dict],
    camera_state: dict,
    pending_confirm: list[bool],
) -> str | None:
    """
    Drain all pending camera events and handle them.
    Returns a synthesised user-input string if the event maps to a text command,
    or None if nothing actionable was queued.

    pending_confirm is a one-element mutable list [bool] set to True when a
    thumbs-up "confirm" event fires while a RequiresConfirmation prompt is active.
    """
    try:
        while True:
            event = _camera_event_queue.get_nowait()

            if event == "confirm":
                # Auto-answer any pending RequiresConfirmation prompt with "y"
                pending_confirm[0] = True
                console.print(_dim("[camera] Thumbs up detected — confirming action."))

            elif event == "cancel":
                # Send /new to clear conversation context
                console.print(_dim("[camera] Open palm detected — clearing context."))
                if conversation is not None:
                    conversation.clear()
                console.print(_dim("Conversation context cleared. Starting fresh."))

            elif event == "voice_toggle":
                # Toggle voice mode
                if voice_state.get("enabled"):
                    voice_state["enabled"] = False
                    console.print(_dim("[camera] Peace sign — voice mode disabled."))
                else:
                    if _VOICE_DEPS_OK:
                        voice_state["enabled"] = True
                        console.print(_green("[camera] Peace sign — voice mode enabled."))
                    else:
                        console.print(
                            _red(
                                "[camera] Voice deps not installed: "
                                + ", ".join(_VOICE_MISSING)
                            )
                        )

            elif event == "new_session":
                # Wave → new session (same as /new)
                console.print(_dim("[camera] Wave detected — starting new session."))
                if conversation is not None:
                    conversation.clear()
                console.print(_dim("Conversation context cleared. Starting fresh."))

            elif event == "lip_start":
                # Lip-VAD: lips opened — start voice recording if voice mode active
                if voice_state.get("enabled") and _VOICE_DEPS_OK:
                    ve = _get_voice_engine()
                    console.print(_dim("[lip-vad] Speaking detected — recording…"))
                    ve.start_recording()

            elif event == "lip_stop":
                # Lip-VAD: lips closed — stop recording and transcribe
                if voice_state.get("enabled") and _VOICE_DEPS_OK:
                    ve = _get_voice_engine()
                    audio = ve.stop_recording()
                    if audio is not None and len(audio) >= _AUDIO_SAMPLE_RATE * 0.3:
                        console.print(_dim("[lip-vad] Transcribing…"))
                        text = ve.transcribe(audio)
                        if text:
                            console.print(f"  [dim]You said:[/dim] {text}")
                            return text  # inject as user input
    except queue.Empty:
        pass

    return None


# ---------------------------------------------------------------------------
# REPL
# ---------------------------------------------------------------------------

def repl(session_id: str, start_voice: bool = False, start_cam_input: bool = False) -> None:
    """Main read-eval-print loop."""
    global _memory

    # In-memory conversation for multi-turn context (trimmed to MAX_CONTEXT_TURNS)
    conversation: list[dict] = []

    # Load long-term memory
    _memory = load_memory()
    if _memory:
        console.print(f"  [dim]Memory: {len(_memory)} fact(s) loaded[/dim]")

    # Mutable voice state — passed to handle_special so /voice on/off works
    voice_state: dict = {"enabled": start_voice and _VOICE_DEPS_OK}

    # Mutable camera state
    camera_state: dict = {"enabled": False}

    # Start camera thread if requested at launch
    if start_cam_input and _CAMERA_DEPS_OK:
        ok = start_camera(voice_state)
        if ok:
            camera_state["enabled"] = True
        else:
            console.print(_red("[camera] Failed to start camera. Is a device connected?"))
    elif start_cam_input and not _CAMERA_DEPS_OK:
        console.print(
            "Camera deps not installed: pip install opencv-python mediapipe"
        )

    # Pending confirm from gesture (thumbs up)
    _pending_confirm: list[bool] = [False]

    while True:
        # ----------------------------------------------------------------
        # Drain camera events at the top of each iteration
        # ----------------------------------------------------------------
        injected_text: str | None = None
        if camera_state.get("enabled") or camera_is_running():
            injected_text = _drain_camera_events(
                voice_state, conversation, camera_state, _pending_confirm
            )

        active_voice = voice_state.get("enabled", False)
        prompt_str = VOICE_PROMPT if active_voice else PROMPT

        # If lip-VAD injected a transcribed utterance, use it directly
        if injected_text:
            line = injected_text
        else:
            # --- Read ---
            try:
                line = _read_voice_or_text(voice_state, prompt_str)
            except EOFError:
                console.print()
                console.print("[dim]Goodbye.[/dim]")
                break

            if line is None:
                # KeyboardInterrupt — re-prompt
                continue

        # Empty input — re-prompt
        if not line.strip():
            continue

        # Multiline: lines ending with backslash continue (text-only convenience)
        accumulated = line
        while accumulated.rstrip().endswith("\\") and not voice_state.get("enabled"):
            accumulated = accumulated.rstrip()[:-1] + "\n"
            try:
                more = input(CONTINUATION)
            except EOFError:
                break
            except KeyboardInterrupt:
                accumulated = ""
                break
            accumulated += more

        user_input = accumulated.strip()
        if not user_input:
            continue

        # --- Special commands ---
        if handle_special(
            user_input,
            session_id,
            conversation,
            voice_state,
            camera_state,
        ):
            continue

        # --- Send to AI (with rolling conversation context) ---
        prior = conversation[-MAX_CONTEXT_TURNS * 2:]  # each turn = 2 messages
        try:
            data = infer_with_spinner(user_input, session_id, prior)
        except httpx.ConnectError:
            console.print(
                _red(
                    "\nInference bridge not running.\n"
                    "Start it with:  python prototype/inference-bridge/bridge.py\n"
                )
            )
            continue
        except TimeoutError as exc:
            console.print(_red(f"\n{exc}\n"))
            continue
        except PermissionError as exc:
            console.print(_red(f"\n{exc}\n"))
            continue
        except httpx.HTTPStatusError as exc:
            console.print(_red(f"\nBridge error: {exc.response.status_code} — {exc.response.text[:200]}\n"))
            continue
        except Exception as exc:
            console.print(_red(f"\nUnexpected error: {exc}\n"))
            continue

        # --- Render ---
        _require_confirm, prose_text = render_response(data)

        # --- TTS (voice mode only; prose only, never tool JSON) ---
        if voice_state.get("enabled") and prose_text:
            ve = _get_voice_engine()
            ve.speak(prose_text)

        # --- Update in-memory conversation context ---
        ai_text = data.get("text", "")
        conversation.append({"role": "user", "content": user_input})
        conversation.append({"role": "assistant", "content": ai_text})

        # --- Persist history ---
        append_history(user_input, ai_text)
        trim_history()

# ---------------------------------------------------------------------------
# --check mode
# ---------------------------------------------------------------------------

def run_check() -> int:
    """Verify connectivity to bridge and policy engine. Return exit code."""
    console.print("[bold]Lumen Ora — connectivity check[/bold]")
    console.print()

    bridge_ok, bridge_detail = check_bridge()
    policy_ok, policy_detail = check_policy()

    if bridge_ok:
        console.print(f"  {_green('[OK]')}  Inference Bridge  ({bridge_detail})")
    else:
        console.print(f"  {_red('[FAIL]')}  Inference Bridge  ({bridge_detail})")

    if policy_ok:
        console.print(f"  {_green('[OK]')}  Policy Engine     ({policy_detail})")
    else:
        console.print(f"  {_red('[FAIL]')}  Policy Engine     ({policy_detail})")

    console.print()
    if bridge_ok and policy_ok:
        console.print(_green("All systems ready."))
        return 0
    else:
        issues = []
        if not bridge_ok:
            issues.append(
                "  • Start the inference bridge:  python prototype/inference-bridge/bridge.py"
            )
        if not policy_ok:
            issues.append(
                "  • Start the policy engine:     "
                "wsl -- LUMEN_TCP_PORT=8766 ./prototype/policy-engine/target/debug/policy-engine"
            )
        console.print(_red("Some services are not reachable."))
        for issue in issues:
            console.print(f"[dim]{issue}[/dim]")
        return 1

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Lumen Ora Context Shell")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Verify connectivity to bridge and policy engine, then exit.",
    )
    parser.add_argument(
        "--voice",
        action="store_true",
        help="Enable voice mode at startup (push-to-talk STT + TTS).",
    )
    parser.add_argument(
        "--camera",
        action="store_true",
        help="Enable camera gesture + lip-VAD input at startup.",
    )
    parser.add_argument(
        "--model",
        choices=["fast", "smart"],
        default="smart",
        help="Model tier: fast (3B, ~18s) or smart (7B, ~70s). Default: smart.",
    )
    args = parser.parse_args()

    if args.check:
        sys.exit(run_check())

    # --- Model tier ---
    global _model_tier
    _model_tier = args.model

    # --- Voice mode startup validation ---
    start_voice = args.voice
    if start_voice and not _VOICE_DEPS_OK:
        console.print(
            _red(
                "Voice mode unavailable — missing packages: "
                + ", ".join(_VOICE_MISSING)
            )
        )
        console.print(
            "[dim]Run: pip install faster-whisper sounddevice soundfile keyboard pyttsx3[/dim]"
        )
        console.print("[dim]Continuing in text-only mode.[/dim]")
        console.print()
        start_voice = False

    # --- Camera mode startup validation ---
    start_cam = args.camera
    if start_cam and not _CAMERA_DEPS_OK:
        console.print(
            "Camera deps not installed: pip install opencv-python mediapipe"
        )
        console.print("[dim]Continuing without camera input.[/dim]")
        console.print()
        start_cam = False

    # --- Normal interactive mode ---
    session_id = load_or_create_session_id()

    bridge_ok, _ = check_bridge()
    policy_ok, _ = check_policy()

    print_banner(bridge_ok, policy_ok, voice_mode=start_voice, camera_mode=start_cam)

    # --- Policy engine auto-start (only if not already running) ---
    if policy_ok:
        console.print("  Policy engine: already running")
    else:
        engine_up = ensure_policy_engine()
        if engine_up:
            console.print("  Policy engine: started")
        else:
            console.print(_dim("  Policy engine: unavailable (running without enforcement)"))
    console.print()

    if start_voice:
        # Pre-download / warm-up the Whisper model BEFORE entering the REPL
        # so the first push-to-talk isn't blocked by a 150 MB download.
        ensure_whisper_model()
        console.print(
            "[dim]Voice mode active. Hold Space to speak, or just type and press Enter.[/dim]"
        )
        console.print()

    if not bridge_ok:
        console.print(
            _red(
                "Warning: Inference bridge is not running.\n"
                "Start it with:  python prototype/inference-bridge/bridge.py\n"
                "Continuing — your input won't reach the AI until the bridge is up.\n"
            )
        )

    try:
        repl(session_id, start_voice=start_voice, start_cam_input=start_cam)
    except KeyboardInterrupt:
        console.print()
        console.print("[dim]Goodbye.[/dim]")
    finally:
        stop_camera()
        if _policy_proc is not None:
            try:
                _policy_proc.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    main()
