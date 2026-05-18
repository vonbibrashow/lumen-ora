#!/usr/bin/env python3
"""
Lumen Ora — Context Shell
The user-facing AI interface. Everything you type goes to the AI.

Usage:
    python shell.py           # interactive mode
    python shell.py --check   # connectivity check, exit 0/1
    python shell.py --voice   # enable voice mode (STT + TTS)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
import threading
import uuid
from datetime import datetime
from pathlib import Path

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
# Configuration
# ---------------------------------------------------------------------------

BRIDGE_URL = os.environ.get("LUMEN_BRIDGE_URL", "http://127.0.0.1:8765")
POLICY_HOST = os.environ.get("LUMEN_POLICY_HOST", "127.0.0.1")
POLICY_PORT = int(os.environ.get("LUMEN_POLICY_PORT", "8766"))

LUMEN_DIR = Path.home() / ".lumen"
SESSION_FILE = LUMEN_DIR / "session_id"
HISTORY_FILE = LUMEN_DIR / "history.jsonl"

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
# Lumen directory setup
# ---------------------------------------------------------------------------

def ensure_lumen_dir() -> None:
    LUMEN_DIR.mkdir(parents=True, exist_ok=True)

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
# Connectivity checks
# ---------------------------------------------------------------------------

def check_bridge() -> tuple[bool, str]:
    """Return (ok, detail)."""
    try:
        r = httpx.get(f"{BRIDGE_URL}/health", timeout=4.0)
        if r.status_code == 200:
            data = r.json()
            return True, data.get("version", "ok")
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

def print_banner(bridge_ok: bool, policy_ok: bool, voice_mode: bool = False) -> None:
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
    if voice_mode:
        console.print("[dim]Hold Space to speak / press Enter to type. /help for commands.[/dim]")
    else:
        console.print("[dim]Type anything. /help for commands.[/dim]")
    console.print(f"[dim]{divider}[/dim]")
    console.print()

# ---------------------------------------------------------------------------
# Inference call
# ---------------------------------------------------------------------------

def call_bridge(prompt: str, session_id: str, messages: list[dict] | None = None) -> dict:
    """
    POST /infer to the bridge.
    messages is the prior conversation context [{role, content}, ...].
    """
    payload = {
        "prompt": prompt,
        "session_id": session_id,
        "stream": False,
        "messages": messages or [],
    }
    try:
        r = httpx.post(
            f"{BRIDGE_URL}/infer",
            json=payload,
            timeout=TIMEOUT_SECONDS,
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
        self._whisper: object = None
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

        self._stream = sd.InputStream(
            samplerate=_AUDIO_SAMPLE_RATE,
            channels=_AUDIO_CHANNELS,
            dtype="float32",
            callback=_callback,
        )
        self._stream.start()
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
        """
        if not (_KB_OK and _SD_OK and _SF_OK and _WHISPER_OK):
            return ""

        import keyboard

        console.print(_dim("  [recording…] Release Space when done."), end="\r")

        ok = self.start_recording()
        if not ok:
            return ""

        # Block until Space key is released
        keyboard.wait("space", suppress=True, trigger_on_release=True)

        audio = self.stop_recording()
        console.print(" " * 60, end="\r")  # clear the recording line

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
# Special / commands
# ---------------------------------------------------------------------------

def cmd_help(voice_mode: bool = False) -> None:
    lines = [
        "[bold]/help[/bold]       — show this help",
        "[bold]/exit[/bold]       — exit the shell (also Ctrl+D)",
        "[bold]/quit[/bold]       — exit the shell",
        "[bold]/clear[/bold]      — clear screen and reset display",
        "[bold]/new[/bold]        — start a fresh conversation (clears context)",
        "[bold]/history[/bold]    — show last 10 exchanges",
        "[bold]/session[/bold]    — show session ID and history stats",
        "[bold]/model[/bold]      — show which model is loaded",
        "[bold]/voice on[/bold]   — enable voice mode (STT + TTS)",
        "[bold]/voice off[/bold]  — disable voice mode",
    ]
    console.print(
        Panel(
            "\n".join(lines),
            title="[cyan]Lumen Ora — Commands[/cyan]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    )


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


def cmd_model() -> None:
    bridge_ok, detail = check_bridge()
    if bridge_ok:
        console.print(f"Model: [cyan]{MODEL_NAME}[/cyan]  [dim](bridge: {detail})[/dim]")
    else:
        console.print(_red(f"Bridge not reachable: {detail}"))


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
) -> bool:
    """
    Handle /commands. Return True if handled (caller should not send to AI).
    Return False if not a special command.
    voice_state is a mutable dict with key 'enabled' (bool).
    """
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
        cmd_model()
        return True

    if verb == "/help":
        cmd_help(voice_state.get("enabled", False) if voice_state else False)
        return True

    if verb == "/voice":
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
                "Use [bold]/voice on[/bold] or [bold]/voice off[/bold]."
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
# REPL
# ---------------------------------------------------------------------------

def repl(session_id: str, start_voice: bool = False) -> None:
    """Main read-eval-print loop."""
    # In-memory conversation for multi-turn context (trimmed to MAX_CONTEXT_TURNS)
    conversation: list[dict] = []

    # Mutable voice state — passed to handle_special so /voice on/off works
    voice_state: dict = {"enabled": start_voice and _VOICE_DEPS_OK}

    while True:
        active_voice = voice_state.get("enabled", False)
        prompt_str = VOICE_PROMPT if active_voice else PROMPT

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
        if handle_special(user_input, session_id, conversation, voice_state):
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
    args = parser.parse_args()

    if args.check:
        sys.exit(run_check())

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

    # --- Normal interactive mode ---
    session_id = load_or_create_session_id()

    bridge_ok, _ = check_bridge()
    policy_ok, _ = check_policy()

    print_banner(bridge_ok, policy_ok, voice_mode=start_voice)

    if start_voice:
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
        repl(session_id, start_voice=start_voice)
    except KeyboardInterrupt:
        console.print()
        console.print("[dim]Goodbye.[/dim]")


if __name__ == "__main__":
    main()
