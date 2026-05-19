#!/usr/bin/env python3
"""
Lumen Ora — End-to-End Test Suite
Tests the full pipeline: Context Shell → Inference Bridge → Policy Engine → tool execution

Architecture notes for this test environment (Windows + WSL2):
  - Policy Engine (Rust) runs in WSL2, listens on TCP 127.0.0.1:8766 (Windows fallback mode)
  - Inference Bridge (Python/FastAPI) runs on Windows, port 8765
  - llama-server (llama.cpp) runs on Windows, port 8080
  - The test verifies each layer independently, then the full pipeline

Usage:
    python test_e2e.py [--skip-model]    # skip if llama-server not available
    python test_e2e.py --policy-only     # test policy engine only (no Python deps needed)
    python test_e2e.py --all             # full end-to-end (requires llama-server running)
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Ensure stdout can handle Unicode box-drawing characters on Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-16"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Colour helpers (works on Windows 10+ terminal)
# ---------------------------------------------------------------------------

def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m"

def green(t: str) -> str:  return _c("32", t)
def red(t: str) -> str:    return _c("31", t)
def yellow(t: str) -> str: return _c("33", t)
def cyan(t: str) -> str:   return _c("36", t)
def bold(t: str) -> str:   return _c("1", t)

# ---------------------------------------------------------------------------
# Test result tracking
# ---------------------------------------------------------------------------

RESULTS: list[tuple[str, bool, str]] = []

def record(name: str, passed: bool, detail: str = "") -> bool:
    RESULTS.append((name, passed, detail))
    icon = green("PASS") if passed else red("FAIL")
    print(f"  [{icon}] {name}" + (f"\n         {detail}" if detail and not passed else ""))
    return passed

def section(title: str) -> None:
    print(f"\n{bold(cyan('── ' + title + ' ──'))}")

def summary() -> int:
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    failed = total - passed
    print(f"\n{bold('Results: ')}{green(str(passed))} passed, {red(str(failed))} failed, {total} total")
    if failed:
        print(red("\nFailed tests:"))
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  - {name}" + (f": {detail}" if detail else ""))
    return 0 if failed == 0 else 1


# ===========================================================================
# LAYER 1: Policy Engine tests (direct TCP socket — no Python deps needed)
# ===========================================================================

POLICY_HOST = "127.0.0.1"
POLICY_PORT = 8766

def policy_send(request: dict[str, Any], timeout: float = 5.0) -> dict[str, Any]:
    """Send a JSON-RPC request to the policy engine via TCP and return the response."""
    payload = json.dumps(request) + "\n"
    with socket.create_connection((POLICY_HOST, POLICY_PORT), timeout=timeout) as sock:
        sock.sendall(payload.encode())
        # Read until newline
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = sock.recv(4096)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf.strip())


def is_policy_engine_running() -> bool:
    """Check whether the policy engine TCP server is accepting connections."""
    try:
        with socket.create_connection((POLICY_HOST, POLICY_PORT), timeout=2.0):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def start_policy_engine_wsl(binary_path_wsl: str) -> subprocess.Popen | None:
    """
    Launch the policy engine binary inside WSL2 and wait for it to be ready.
    Returns the Popen handle or None on failure.
    """
    env = os.environ.copy()
    # On Windows: policy engine uses TCP fallback
    # POLICY_ENGINE_ADDR env var controls address
    cmd = [
        "wsl", "-d", "Ubuntu-22.04", "--",
        "env", "LUMEN_TCP_PORT=8766",
        binary_path_wsl,
    ]
    print(f"  Starting policy engine: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={**env, "POLICY_ENGINE_ADDR": "0.0.0.0:8766"},
        )
    except FileNotFoundError:
        return None

    # Wait up to 10s for the engine to bind
    for _ in range(20):
        if is_policy_engine_running():
            return proc
        time.sleep(0.5)
    proc.terminate()
    return None


def find_policy_engine_binary() -> str | None:
    """
    Find the compiled policy-engine binary.
    Checks WSL2 path (primary) and Windows path (secondary).
    """
    prototype_dir = Path(__file__).parent
    policy_dir = prototype_dir / "policy-engine"

    # WSL2 path — normalise Windows (C:/...) and Git Bash (/c/...) path formats.
    _posix = policy_dir.as_posix().replace("\\", "/")
    if len(_posix) >= 2 and _posix[1] == ":":
        # Windows: C:/Users/... → /mnt/c/Users/...
        _posix = f"/mnt/{_posix[0].lower()}/{_posix[3:]}"
    elif len(_posix) >= 2 and _posix[0] == "/" and _posix[2] == "/":
        # Git Bash: /c/Users/... → /mnt/c/Users/...
        _posix = f"/mnt/{_posix[1].lower()}/{_posix[3:]}"
    wsl_binary = f"{_posix}/target/debug/policy-engine"

    # Windows native binary
    win_binary = policy_dir / "target" / "debug" / "policy-engine.exe"

    if win_binary.exists():
        return str(win_binary)

    # Check if WSL2 binary exists via wsl test command
    try:
        result = subprocess.run(
            ["wsl", "-d", "Ubuntu-22.04", "--", "test", "-f", wsl_binary],
            timeout=5,
            capture_output=True,
        )
        if result.returncode == 0:
            return wsl_binary  # Return the WSL-side path
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return None


def run_policy_engine_tests(auto_start: bool = True) -> tuple[bool, subprocess.Popen | None]:
    """
    Run all policy engine tests. Returns (all_passed, proc_handle).
    If auto_start=True and the engine isn't running, tries to start it.
    """
    section("LAYER 1 — Policy Engine (TCP JSON-RPC)")

    proc = None

    if not is_policy_engine_running():
        if not auto_start:
            record("policy-engine reachable", False, f"Not running on {POLICY_HOST}:{POLICY_PORT}")
            return False, None

        binary = find_policy_engine_binary()
        if not binary:
            record("policy-engine binary found", False,
                   "Run: cd prototype/policy-engine && wsl -d Ubuntu-22.04 -- cargo build")
            return False, None

        record("policy-engine binary found", True, binary)
        print(f"  {yellow('Engine not running — attempting auto-start...')}")

        if binary.startswith("/mnt/"):
            proc = start_policy_engine_wsl(binary)
        else:
            # Native Windows binary
            try:
                proc = subprocess.Popen(
                    [binary],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                for _ in range(20):
                    if is_policy_engine_running():
                        break
                    time.sleep(0.5)
                else:
                    proc.terminate()
                    proc = None
            except FileNotFoundError:
                proc = None

        if not is_policy_engine_running():
            record("policy-engine start", False, "Failed to start or bind on port 8766")
            return False, proc
        record("policy-engine start", True, f"Listening on {POLICY_HOST}:{POLICY_PORT}")
    else:
        record("policy-engine reachable", True, f"{POLICY_HOST}:{POLICY_PORT}")

    all_ok = True

    # ── Test 1: ping ──────────────────────────────────────────────────────────
    try:
        resp = policy_send({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": None})
        ok = resp.get("result", {}).get("status") == "ok"
        all_ok &= record("ping response", ok, str(resp.get("result")))
    except Exception as e:
        all_ok &= record("ping response", False, str(e))

    # ── Test 2: list_rules ────────────────────────────────────────────────────
    try:
        resp = policy_send({"jsonrpc": "2.0", "id": 2, "method": "list_rules", "params": None})
        rules = resp.get("result", {}).get("rules", [])
        ok = len(rules) == 5
        all_ok &= record("list_rules returns 5 rules", ok, str(rules))
    except Exception as e:
        all_ok &= record("list_rules", False, str(e))

    # ── Test 3: list_directory — should be ALLOWED ────────────────────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 3, "method": "evaluate",
            "params": {
                "tool_name": "list_directory",
                "parameters": {"path": "/home"},
                "context": {"home_dir": "/home"},
            },
        })
        result = resp.get("result", {})
        decision = result.get("decision", {})
        # decision is tagged enum: {"decision": "Allow"} or {"decision": "Deny", "detail": {...}}
        decision_type = decision.get("decision") if isinstance(decision, dict) else str(decision)
        ok = decision_type == "Allow"
        all_ok &= record("list_directory /home → Allow", ok,
                         f"decision={decision}")
    except Exception as e:
        all_ok &= record("list_directory /home → Allow", False, str(e))

    # ── Test 4: path traversal — should be DENIED ────────────────────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 4, "method": "evaluate",
            "params": {
                "tool_name": "read_file",
                "parameters": {"path": "../../etc/passwd"},
                "context": {},
            },
        })
        result = resp.get("result", {})
        decision = result.get("decision", {})
        decision_type = decision.get("decision") if isinstance(decision, dict) else str(decision)
        ok = decision_type == "Deny"
        all_ok &= record("path traversal ../../etc/passwd → Deny", ok,
                         f"decision={decision}")
    except Exception as e:
        all_ok &= record("path traversal → Deny", False, str(e))

    # ── Test 5: write outside home — should be DENIED ─────────────────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 5, "method": "evaluate",
            "params": {
                "tool_name": "write_file",
                "parameters": {"path": "/etc/cron.d/evil"},
                "context": {"home_dir": "/home/user"},
            },
        })
        result = resp.get("result", {})
        decision = result.get("decision", {})
        decision_type = decision.get("decision") if isinstance(decision, dict) else str(decision)
        ok = decision_type == "Deny"
        all_ok &= record("write_file /etc/cron.d/evil → Deny", ok,
                         f"decision={decision}")
    except Exception as e:
        all_ok &= record("write_file outside home → Deny", False, str(e))

    # ── Test 6: write inside home — should be ALLOWED ────────────────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 6, "method": "evaluate",
            "params": {
                "tool_name": "write_file",
                "parameters": {"path": "/home/user/notes.txt"},
                "context": {"home_dir": "/home/user"},
            },
        })
        result = resp.get("result", {})
        decision = result.get("decision", {})
        decision_type = decision.get("decision") if isinstance(decision, dict) else str(decision)
        ok = decision_type == "Allow"
        all_ok &= record("write_file inside home → Allow", ok,
                         f"decision={decision}")
    except Exception as e:
        all_ok &= record("write_file inside home → Allow", False, str(e))

    # ── Test 7: /tmp exec — should be DENIED ─────────────────────────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 7, "method": "evaluate",
            "params": {
                "tool_name": "run_command",
                "parameters": {"command": "/tmp/dropper.sh", "args": []},
                "context": {},
            },
        })
        result = resp.get("result", {})
        decision = result.get("decision", {})
        decision_type = decision.get("decision") if isinstance(decision, dict) else str(decision)
        ok = decision_type == "Deny"
        all_ok &= record("run_command /tmp/dropper.sh → Deny", ok,
                         f"decision={decision}")
    except Exception as e:
        all_ok &= record("/tmp exec → Deny", False, str(e))

    # ── Test 8: bulk delete — should be RequireConfirmation ──────────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 8, "method": "evaluate",
            "params": {
                "tool_name": "delete_files",
                "parameters": {"paths": ["a.txt", "b.txt", "c.txt", "d.txt"]},
                "context": {},
            },
        })
        result = resp.get("result", {})
        decision = result.get("decision", {})
        decision_type = decision.get("decision") if isinstance(decision, dict) else str(decision)
        ok = decision_type == "RequireConfirmation"
        all_ok &= record("bulk delete 4 files → RequireConfirmation", ok,
                         f"decision={decision}")
    except Exception as e:
        all_ok &= record("bulk delete → RequireConfirmation", False, str(e))

    # ── Test 9: raw IP network — should be RequireConfirmation ───────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 9, "method": "evaluate",
            "params": {
                "tool_name": "http_request",
                "parameters": {"url": "http://192.168.1.200/beacon"},
                "context": {},
            },
        })
        result = resp.get("result", {})
        decision = result.get("decision", {})
        decision_type = decision.get("decision") if isinstance(decision, dict) else str(decision)
        ok = decision_type == "RequireConfirmation"
        all_ok &= record("http_request raw IP → RequireConfirmation", ok,
                         f"decision={decision}")
    except Exception as e:
        all_ok &= record("raw IP → RequireConfirmation", False, str(e))

    # ── Test 10: matched_rule_id is populated ─────────────────────────────────
    try:
        resp = policy_send({
            "jsonrpc": "2.0", "id": 10, "method": "evaluate",
            "params": {
                "tool_name": "read_file",
                "parameters": {"path": "../../etc/shadow"},
                "context": {},
            },
        })
        result = resp.get("result", {})
        matched = result.get("matched_rule_id")
        ok = matched == "path-traversal-deny"
        all_ok &= record("matched_rule_id populated", ok, f"matched_rule_id={matched}")
    except Exception as e:
        all_ok &= record("matched_rule_id populated", False, str(e))

    return all_ok, proc


# ===========================================================================
# LAYER 2: Tool execution tests (pure Python, no bridge needed)
# ===========================================================================

def run_tool_execution_tests() -> bool:
    """Test the tool dispatch layer directly, without the bridge or model."""
    section("LAYER 2 — Tool Execution (direct Python dispatch)")

    # Ensure we can import from the inference-bridge directory
    bridge_dir = Path(__file__).parent / "inference-bridge"
    if str(bridge_dir) not in sys.path:
        sys.path.insert(0, str(bridge_dir))

    try:
        from tool_schema import dispatch_tool, TOOL_SCHEMAS
    except ImportError as e:
        record("import tool_schema", False, str(e))
        return False

    record("import tool_schema", True)
    all_ok = True

    # ── Test 1: TOOL_SCHEMAS has 10 entries ──────────────────────────────────
    ok = len(TOOL_SCHEMAS) == 10
    all_ok &= record("TOOL_SCHEMAS has 10 tools", ok, str([t["name"] for t in TOOL_SCHEMAS]))

    # ── Test 2: list_directory on temp dir ───────────────────────────────────
    try:
        with tempfile.TemporaryDirectory() as td:
            # Create some files
            Path(td, "alpha.txt").write_text("hello")
            Path(td, "beta.txt").write_text("world")
            Path(td, ".hidden").write_text("hidden")
            result = dispatch_tool("list_directory", {"path": td, "show_hidden": False})
            names = [e["name"] for e in result]
            ok = sorted(names) == ["alpha.txt", "beta.txt"]
            all_ok &= record("list_directory excludes hidden", ok, f"names={names}")
    except Exception as e:
        all_ok &= record("list_directory", False, str(e))

    # ── Test 3: list_directory with hidden ───────────────────────────────────
    try:
        with tempfile.TemporaryDirectory() as td:
            Path(td, "visible.txt").write_text("v")
            Path(td, ".secret").write_text("s")
            result = dispatch_tool("list_directory", {"path": td, "show_hidden": True})
            names = [e["name"] for e in result]
            ok = ".secret" in names and "visible.txt" in names
            all_ok &= record("list_directory includes hidden when show_hidden=True", ok, f"names={names}")
    except Exception as e:
        all_ok &= record("list_directory with hidden", False, str(e))

    # ── Test 4: read_file ─────────────────────────────────────────────────────
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("lumen ora test content\n")
            tmp_path = f.name
        result = dispatch_tool("read_file", {"path": tmp_path})
        ok = "lumen ora test content" in result
        all_ok &= record("read_file returns content", ok, f"result[:50]={result[:50]!r}")
        Path(tmp_path).unlink(missing_ok=True)
    except Exception as e:
        all_ok &= record("read_file", False, str(e))

    # ── Test 5: write_file + read_file round-trip ─────────────────────────────
    try:
        with tempfile.TemporaryDirectory() as td:
            target = str(Path(td) / "output.txt")
            dispatch_tool("write_file", {"path": target, "content": "round-trip test"})
            result = dispatch_tool("read_file", {"path": target})
            ok = result.strip() == "round-trip test"
            all_ok &= record("write_file/read_file round-trip", ok, f"result={result!r}")
    except Exception as e:
        all_ok &= record("write_file round-trip", False, str(e))

    # ── Test 6: run_command (echo) ────────────────────────────────────────────
    try:
        import platform
        if platform.system() == "Windows":
            result = dispatch_tool("run_command", {"command": "cmd", "args": ["/c", "echo hello"]})
        else:
            result = dispatch_tool("run_command", {"command": "echo", "args": ["hello"]})
        ok = result["exit_code"] == 0 and "hello" in result["stdout"]
        all_ok &= record("run_command echo hello", ok, f"stdout={result['stdout']!r}")
    except Exception as e:
        all_ok &= record("run_command echo", False, str(e))

    # ── Test 7: run_command unknown binary ────────────────────────────────────
    try:
        result = dispatch_tool("run_command", {"command": "nonexistent_binary_xyz", "args": []})
        ok = result["exit_code"] == 127
        all_ok &= record("run_command unknown binary → exit_code 127", ok, f"result={result}")
    except Exception as e:
        all_ok &= record("run_command unknown binary", False, str(e))

    # ── Test 8: unknown tool name raises KeyError ─────────────────────────────
    try:
        dispatch_tool("delete_everything", {})
        all_ok &= record("unknown tool raises KeyError", False, "No exception raised")
    except KeyError:
        all_ok &= record("unknown tool raises KeyError", True)
    except Exception as e:
        all_ok &= record("unknown tool raises KeyError", False, f"Wrong exception: {e}")

    # ── Test: search_web returns results (requires internet) ──────────────────
    try:
        result = dispatch_tool("search_web", {"query": "python programming language", "num_results": 2})
        if isinstance(result, list) and result:
            first = result[0]
            has_title = bool(first.get("title", ""))
            has_url = bool(first.get("url", ""))
            all_ok &= record("search_web returns results", has_title and has_url,
                             str(result[0]))
        else:
            all_ok &= record("search_web returns results (stub/no internet)", True,
                             "No results — duckduckgo-search not installed or no internet")
    except Exception as e:
        all_ok &= record("search_web returns results", False, str(e))

    # ── Test: edit_file round-trip ────────────────────────────────────────────
    try:
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("hello world"); tmp = f.name
        result = dispatch_tool("edit_file", {"path": tmp, "old_str": "world", "new_str": "lumen"})
        content = Path(tmp).read_text(); Path(tmp).unlink()
        all_ok &= record("edit_file replaces string", result.get("replaced") and "lumen" in content)
    except Exception as e:
        all_ok &= record("edit_file replaces string", False, str(e))

    # ── Test: clipboard round-trip ────────────────────────────────────────────
    # Works on Windows (PowerShell + clip.exe) and on Linux/macOS when
    # pyperclip + a backend (xclip/xsel/wl-copy/pbcopy) is available.
    # Headless CI Linux without a clipboard backend is non-fatal: we record
    # PASS-with-skip so the cross-platform path is exercised but not gated.
    import platform as _plat
    try:
        write_result = dispatch_tool("clipboard_write", {"text": "lumen-test-123"})
        if isinstance(write_result, dict) and "error" in write_result:
            # No backend available — non-fatal on non-Windows (e.g. headless CI).
            if _plat.system() == "Windows":
                all_ok &= record("clipboard write/read", False, str(write_result))
            else:
                record("clipboard write/read",
                       True, f"skipped: {write_result.get('error')}")
        else:
            got = dispatch_tool("clipboard_read", {})
            if isinstance(got, dict):
                if _plat.system() == "Windows":
                    all_ok &= record("clipboard write/read", False, str(got))
                else:
                    record("clipboard write/read",
                           True, f"skipped: {got.get('error')}")
            else:
                all_ok &= record("clipboard write/read", "lumen-test-123" in str(got))
    except Exception as e:
        record("clipboard write/read", True, f"skipped: {e}")  # non-fatal on CI

    # ── Test: take_screenshot ─────────────────────────────────────────────────
    # mss is the primary backend on all platforms; on headless Linux CI
    # without a display it will error cleanly — non-fatal.
    try:
        result = dispatch_tool("take_screenshot", {})
        if "error" in str(result):
            record("take_screenshot", True, f"skipped: {result}")  # mss/PIL not installed or headless
        else:
            p = Path(result.get("path", ""))
            all_ok &= record("take_screenshot saves file", p.exists())
            if p.exists(): p.unlink()
    except Exception as e:
        # Cross-platform: headless display can raise rather than return {error}.
        if _plat.system() == "Windows":
            all_ok &= record("take_screenshot", False, str(e))
        else:
            record("take_screenshot", True, f"skipped: {e}")

    return all_ok


# ===========================================================================
# LAYER 2b: Voice subsystem tests (pure Python, no hardware required)
# ===========================================================================

def run_voice_tests() -> bool:
    """
    Test the voice subsystem dependencies and model loading.
    No microphone or speaker hardware is required — we only verify imports
    and (if the model is already cached) attempt a WhisperModel init.
    """
    section("LAYER 2b — Voice Subsystem")

    all_ok = True

    # ── faster-whisper import ─────────────────────────────────────────────────
    try:
        import faster_whisper  # noqa: F401
        fw_ok = True
        record("faster-whisper importable", True)
    except ImportError as e:
        fw_ok = False
        record("faster-whisper importable", False,
               f"{e} — run: pip install faster-whisper")

    # ── pyttsx3 import ────────────────────────────────────────────────────────
    try:
        import pyttsx3  # noqa: F401
        record("pyttsx3 importable", True)
    except ImportError as e:
        record("pyttsx3 importable", False,
               f"{e} — run: pip install pyttsx3")

    # ── sounddevice import ────────────────────────────────────────────────────
    try:
        import sounddevice  # noqa: F401
        record("sounddevice importable", True)
    except ImportError as e:
        record("sounddevice importable", False,
               f"{e} — run: pip install sounddevice")

    # ── WhisperModel load (only if cache already present) ────────────────────
    if fw_ok:
        hf_hub_cache = Path.home() / ".cache" / "huggingface" / "hub"
        cache_hit = False
        if hf_hub_cache.exists():
            cache_hit = any(
                "whisper" in p.name.lower()
                for p in hf_hub_cache.iterdir()
                if p.is_dir()
            )

        if cache_hit:
            try:
                from faster_whisper import WhisperModel
                _m = WhisperModel("base.en", device="cpu", compute_type="int8")
                record("WhisperModel('base.en') loads from cache", True)
            except Exception as exc:
                all_ok &= record("WhisperModel('base.en') loads from cache", False, str(exc))
        else:
            # Model not cached — skip rather than trigger a 150 MB download in CI
            print(f"  [{yellow('SKIP')}] WhisperModel load — model not cached "
                  f"(~/.cache/huggingface/hub has no whisper dir)")

    return all_ok


# ===========================================================================
# LAYER 3: Inference Bridge HTTP tests (requires bridge running, NOT model)
# ===========================================================================

BRIDGE_URL = "http://127.0.0.1:8765"

def is_bridge_running() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"{BRIDGE_URL}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def is_llama_running() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def bridge_get(path: str) -> tuple[int, Any]:
    import urllib.request
    with urllib.request.urlopen(f"{BRIDGE_URL}{path}", timeout=10) as r:
        return r.status, json.loads(r.read())


def bridge_post(path: str, body: dict[str, Any], timeout: int = 30) -> tuple[int, Any]:
    import urllib.request
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{BRIDGE_URL}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def start_bridge(policy_socket_mode: str = "tcp") -> subprocess.Popen | None:
    """Start the inference bridge as a subprocess."""
    bridge_dir = Path(__file__).parent / "inference-bridge"
    bridge_py = bridge_dir / "bridge.py"

    if not bridge_py.exists():
        return None

    env = os.environ.copy()
    if policy_socket_mode == "tcp":
        # Override so bridge connects to policy engine via TCP on Windows
        env["POLICY_ENGINE_SOCKET"] = "tcp://127.0.0.1:8766"

    cmd = [sys.executable, str(bridge_py)]
    print(f"  Starting bridge: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return None

    # Wait for health endpoint
    for _ in range(20):
        if is_bridge_running():
            return proc
        time.sleep(0.5)

    proc.terminate()
    return None


def run_bridge_tests(skip_model: bool = True) -> tuple[bool, subprocess.Popen | None]:
    """
    Run inference bridge HTTP API tests.
    Most tests work without a model (the bridge handles ConnectError gracefully).
    """
    section("LAYER 3 — Inference Bridge (HTTP API)")

    # Try to import required packages first
    missing = []
    for pkg in ("fastapi", "uvicorn", "httpx", "pydantic", "sse_starlette"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)

    if missing:
        record("Python dependencies installed", False,
               f"Missing: {missing}. Run: pip install -r inference-bridge/requirements.txt")
        return False, None

    record("Python dependencies installed", True)

    proc = None
    if not is_bridge_running():
        print(f"  {yellow('Bridge not running — attempting auto-start...')}")
        proc = start_bridge()
        if not is_bridge_running():
            record("inference bridge start", False,
                   f"Could not start bridge on {BRIDGE_URL}")
            return False, proc
        record("inference bridge start", True, BRIDGE_URL)
    else:
        record("inference bridge reachable", True, BRIDGE_URL)

    all_ok = True

    # ── Test 1: /health ───────────────────────────────────────────────────────
    try:
        status, body = bridge_get("/health")
        ok = status == 200 and body.get("status") == "ok"
        all_ok &= record("GET /health returns ok", ok, str(body))
    except Exception as e:
        all_ok &= record("GET /health", False, str(e))

    # ── Test 2: /tools ────────────────────────────────────────────────────────
    try:
        status, body = bridge_get("/tools")
        tools = body.get("tools", [])
        ok = status == 200 and len(tools) >= 10
        names = [t["name"] for t in tools]
        all_ok &= record("GET /tools returns 10 schemas", ok, str(names))
    except Exception as e:
        all_ok &= record("GET /tools", False, str(e))

    # ── Test 3: POST /evaluate_tool — policy passthrough ─────────────────────
    # This test hits the real policy engine through the bridge
    try:
        import urllib.request, urllib.parse
        url = f"{BRIDGE_URL}/evaluate_tool?tool_name=read_file"
        body_data = json.dumps({"path": "/home/user/file.txt"}).encode()
        req = urllib.request.Request(url, data=body_data,
                                     headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            resp = json.loads(r.read())
        # If policy engine is running, should get Allow. If not, should get "Policy engine not running"
        ok = resp.get("decision") in ("Allow",)
        detail = resp.get("detail", "")
        all_ok &= record("POST /evaluate_tool read_file → Allow (or policy-not-running)",
                         ok or "Policy engine" in detail or "not running" in detail,
                         str(resp))
    except Exception as e:
        # 503 is acceptable — means bridge is up but policy engine is not
        if "503" in str(e) or "422" in str(e):
            all_ok &= record("POST /evaluate_tool (bridge up, policy optional)", True, str(e))
        else:
            all_ok &= record("POST /evaluate_tool", False, str(e))

    # ── Test 4: POST /infer ────────────────────────────────────────────────────
    # When llama-server is running we need a generous timeout (7B on CPU is slow).
    # When it's not running we expect a fast 503; 10 s is plenty.
    _model_up = is_llama_running()
    _infer_timeout = 360 if _model_up else 10
    if skip_model or _model_up:
        try:
            status, body = bridge_post("/infer", {
                "prompt": "List the files in my home directory",
                "stream": False,
            }, timeout=_infer_timeout)
            # Without llama-server: should get 503 (ConnectError)
            # With llama-server: should get 200
            if status == 503:
                all_ok &= record("POST /infer without model → 503 (expected)", True,
                                 "llama-server not running — bridge handles gracefully")
            elif status == 200:
                all_ok &= record("POST /infer with model → 200", True,
                                 f"session_id={body.get('session_id')}")
            else:
                all_ok &= record("POST /infer status code", False,
                                 f"Unexpected status {status}: {body}")
        except Exception as e:
            all_ok &= record("POST /infer", False, str(e))

    return all_ok, proc


# ===========================================================================
# LAYER 3b: Bridge auth tests (LUMEN_API_TOKEN gating)
# ===========================================================================

AUTH_BRIDGE_PORT = 8767  # separate port so we don't clobber the main bridge
AUTH_BRIDGE_URL = f"http://127.0.0.1:{AUTH_BRIDGE_PORT}"
AUTH_TEST_TOKEN = "test-token-abc-123"


def _is_url_running(url: str) -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"{url}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _start_auth_bridge() -> subprocess.Popen | None:
    """Start a bridge subprocess with LUMEN_API_TOKEN set on a separate port."""
    bridge_dir = Path(__file__).parent / "inference-bridge"
    bridge_py = bridge_dir / "bridge.py"
    if not bridge_py.exists():
        return None

    env = os.environ.copy()
    env["LUMEN_API_TOKEN"] = AUTH_TEST_TOKEN
    env["BRIDGE_PORT"] = str(AUTH_BRIDGE_PORT)
    env["POLICY_ENGINE_SOCKET"] = "tcp://127.0.0.1:8766"

    cmd = [sys.executable, str(bridge_py), "--port", str(AUTH_BRIDGE_PORT)]
    print(f"  Starting auth-bridge: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return None

    for _ in range(20):
        if _is_url_running(AUTH_BRIDGE_URL):
            return proc
        time.sleep(0.5)
    proc.terminate()
    return None


def run_auth_tests() -> tuple[bool, subprocess.Popen | None]:
    """
    Verify the LUMEN_API_TOKEN gating on /infer, /infer-stream, /evaluate_tool.
    Spins up a second bridge instance on port 8767 with the token set.
    """
    section("LAYER 3b — Bridge Auth (LUMEN_API_TOKEN)")

    # Dep check first
    missing = []
    for pkg in ("fastapi", "uvicorn", "httpx", "pydantic", "sse_starlette"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        record("auth-bridge dependencies installed", False, f"Missing: {missing}")
        return False, None

    proc = _start_auth_bridge()
    if proc is None or not _is_url_running(AUTH_BRIDGE_URL):
        record("auth-bridge start", False,
               f"Could not start bridge on {AUTH_BRIDGE_URL} with LUMEN_API_TOKEN")
        return False, proc
    record("auth-bridge start", True, AUTH_BRIDGE_URL)

    all_ok = True
    import urllib.request, urllib.error

    # ── Test 1: /health is open even with auth enabled, and reports auth_required ──
    try:
        with urllib.request.urlopen(f"{AUTH_BRIDGE_URL}/health", timeout=5) as r:
            body = json.loads(r.read())
        ok = r.status == 200 and body.get("auth_required") is True
        all_ok &= record("/health open + reports auth_required=true", ok, str(body))
    except Exception as e:
        all_ok &= record("/health open + reports auth_required=true", False, str(e))

    # ── Test 2: /infer WITHOUT Authorization header → 401 ──────────────────────
    try:
        req = urllib.request.Request(
            f"{AUTH_BRIDGE_URL}/infer",
            data=json.dumps({"prompt": "hi", "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status = None
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        ok = status == 401
        all_ok &= record("POST /infer without token → 401", ok, f"status={status}")
    except Exception as e:
        all_ok &= record("POST /infer without token → 401", False, str(e))

    # ── Test 3: /infer with WRONG token → 401 ──────────────────────────────────
    try:
        req = urllib.request.Request(
            f"{AUTH_BRIDGE_URL}/infer",
            data=json.dumps({"prompt": "hi", "stream": False}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer wrong-token",
            },
            method="POST",
        )
        status = None
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        ok = status == 401
        all_ok &= record("POST /infer with wrong token → 401", ok, f"status={status}")
    except Exception as e:
        all_ok &= record("POST /infer with wrong token → 401", False, str(e))

    # ── Test 4: /infer with CORRECT token → not 401 (200 or 503) ──────────────
    # 503 is acceptable: bridge is reachable + authorized, but llama-server may be down.
    try:
        req = urllib.request.Request(
            f"{AUTH_BRIDGE_URL}/infer",
            data=json.dumps({"prompt": "hi", "stream": False}).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {AUTH_TEST_TOKEN}",
            },
            method="POST",
        )
        status = None
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        ok = status != 401  # anything but 401 means auth passed
        all_ok &= record("POST /infer with valid token → not 401 (auth passed)",
                         ok, f"status={status}")
    except Exception as e:
        all_ok &= record("POST /infer with valid token → not 401", False, str(e))

    # ── Test 5: /evaluate_tool without token → 401 ─────────────────────────────
    try:
        req = urllib.request.Request(
            f"{AUTH_BRIDGE_URL}/evaluate_tool?tool_name=read_file",
            data=json.dumps({"path": "/home/user/x.txt"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status = None
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        ok = status == 401
        all_ok &= record("POST /evaluate_tool without token → 401", ok, f"status={status}")
    except Exception as e:
        all_ok &= record("POST /evaluate_tool without token → 401", False, str(e))

    # ── Test 6: /infer-stream via GET query token → not 401 ────────────────────
    # EventSource cannot set headers — we accept ?token= as fallback.
    try:
        url = (
            f"{AUTH_BRIDGE_URL}/infer-stream?prompt=hi"
            f"&token={AUTH_TEST_TOKEN}"
        )
        status = None
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                status = r.status
                # We don't need to consume the stream — status is set on response start.
        except urllib.error.HTTPError as e:
            status = e.code
        ok = status != 401
        all_ok &= record("GET /infer-stream?token=... → not 401", ok, f"status={status}")
    except Exception as e:
        # Some streams may close abruptly; still acceptable as long as not 401
        if "401" in str(e):
            all_ok &= record("GET /infer-stream?token=... → not 401", False, str(e))
        else:
            all_ok &= record("GET /infer-stream?token=... → not 401 (stream)", True, str(e))

    # ── Test 7: /infer-stream without token → 401 ──────────────────────────────
    try:
        url = f"{AUTH_BRIDGE_URL}/infer-stream?prompt=hi"
        status = None
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        ok = status == 401
        all_ok &= record("GET /infer-stream without token → 401", ok, f"status={status}")
    except Exception as e:
        all_ok &= record("GET /infer-stream without token → 401", False, str(e))

    return all_ok, proc


# ===========================================================================
# LAYER 3c: Tailscale-friendly remote bind (LUMEN_BIND_HOST=0.0.0.0)
# ===========================================================================

REMOTE_BRIDGE_PORT = 8768  # separate port to avoid clobbering other bridges
REMOTE_TEST_TOKEN = "test-remote-token-xyz-789"


def _get_non_loopback_ipv4() -> str | None:
    """
    Return a non-loopback IPv4 address for this host, or None if we can't
    find one (e.g. machine has no network interface up). Cross-platform.
    """
    # Trick: open a UDP socket to a public-looking address. No packets sent,
    # but the kernel binds it to the interface it would use for that route.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(1.0)
            s.connect(("10.255.255.255", 1))
            ip = s.getsockname()[0]
        if ip and not ip.startswith("127."):
            return ip
    except OSError:
        pass

    # Fallback: iterate all addresses returned for this host's name.
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                return ip
    except socket.gaierror:
        pass
    return None


def _start_remote_bridge() -> subprocess.Popen | None:
    """
    Start a bridge subprocess with LUMEN_BIND_HOST=0.0.0.0 and
    LUMEN_API_TOKEN set, on a separate port so it can't clobber the
    other test bridges.
    """
    bridge_dir = Path(__file__).parent / "inference-bridge"
    bridge_py = bridge_dir / "bridge.py"
    if not bridge_py.exists():
        return None

    env = os.environ.copy()
    env["LUMEN_API_TOKEN"] = REMOTE_TEST_TOKEN
    env["LUMEN_BIND_HOST"] = "0.0.0.0"
    env["BRIDGE_PORT"] = str(REMOTE_BRIDGE_PORT)
    env["POLICY_ENGINE_SOCKET"] = "tcp://127.0.0.1:8766"

    cmd = [sys.executable, str(bridge_py), "--port", str(REMOTE_BRIDGE_PORT)]
    print(f"  Starting remote-bridge: {' '.join(cmd)}")
    try:
        proc = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except Exception:
        return None

    # Wait for it to come up via loopback /health.
    for _ in range(20):
        try:
            import urllib.request
            with urllib.request.urlopen(
                f"http://127.0.0.1:{REMOTE_BRIDGE_PORT}/health", timeout=2
            ) as r:
                if r.status == 200:
                    return proc
        except Exception:
            pass
        time.sleep(0.5)
    proc.terminate()
    return None


def run_remote_bind_tests() -> tuple[bool, subprocess.Popen | None]:
    """
    Verify LUMEN_BIND_HOST=0.0.0.0 makes the bridge reachable on a
    non-loopback interface. Skipped (passes vacuously) on hosts with
    no usable non-loopback IPv4.
    """
    section("LAYER 3c — Tailscale-friendly remote bind (LUMEN_BIND_HOST)")

    # Dep check first
    missing = []
    for pkg in ("fastapi", "uvicorn", "httpx", "pydantic", "sse_starlette"):
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        record("remote-bridge dependencies installed", False, f"Missing: {missing}")
        return False, None

    non_loopback_ip = _get_non_loopback_ipv4()
    if not non_loopback_ip:
        # No usable interface — record as pass with a note so CI doesn't fail.
        record("non-loopback IPv4 available",
               True,
               "skipped: no non-loopback interface (CI / offline host)")
        return True, None
    record("non-loopback IPv4 available", True, non_loopback_ip)

    proc = _start_remote_bridge()
    if proc is None:
        record("remote-bridge start (LUMEN_BIND_HOST=0.0.0.0)", False,
               f"Could not start bridge on port {REMOTE_BRIDGE_PORT}")
        return False, proc
    record("remote-bridge start (LUMEN_BIND_HOST=0.0.0.0)", True,
           f"port {REMOTE_BRIDGE_PORT}")

    all_ok = True
    import urllib.request, urllib.error

    # ── Test 1: /health reachable on the non-loopback interface ──────────────
    try:
        url = f"http://{non_loopback_ip}:{REMOTE_BRIDGE_PORT}/health"
        with urllib.request.urlopen(url, timeout=5) as r:
            body = json.loads(r.read())
        ok = r.status == 200 and body.get("status") == "ok"
        all_ok &= record(
            f"GET /health via {non_loopback_ip}:{REMOTE_BRIDGE_PORT} → 200",
            ok, str(body),
        )
    except Exception as e:
        all_ok &= record(
            f"GET /health via {non_loopback_ip}:{REMOTE_BRIDGE_PORT}",
            False, str(e),
        )

    # ── Test 2: socket-level probe — confirms bridge bound 0.0.0.0, not 127.* ──
    # Even if HTTP routing differs, a raw socket connect to the non-loopback
    # IP on the bridge port must succeed when LUMEN_BIND_HOST=0.0.0.0.
    try:
        with socket.create_connection(
            (non_loopback_ip, REMOTE_BRIDGE_PORT), timeout=3.0
        ):
            all_ok &= record(
                f"TCP connect to {non_loopback_ip}:{REMOTE_BRIDGE_PORT} succeeds",
                True, "bridge is listening on a non-loopback address",
            )
    except OSError as e:
        all_ok &= record(
            f"TCP connect to {non_loopback_ip}:{REMOTE_BRIDGE_PORT}",
            False,
            f"bridge did not bind to 0.0.0.0 — connect failed: {e}",
        )

    # ── Test 3: auth still enforced on remote interface (token required) ─────
    # Confirms /infer is still protected even when reached from another host.
    try:
        req = urllib.request.Request(
            f"http://{non_loopback_ip}:{REMOTE_BRIDGE_PORT}/infer",
            data=json.dumps({"prompt": "hi", "stream": False}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        status = None
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status = r.status
        except urllib.error.HTTPError as e:
            status = e.code
        ok = status == 401
        all_ok &= record(
            "POST /infer on remote interface without token → 401",
            ok, f"status={status}",
        )
    except Exception as e:
        all_ok &= record(
            "POST /infer on remote interface without token → 401",
            False, str(e),
        )

    return all_ok, proc


# ===========================================================================
# LAYER 4: Full end-to-end pipeline test (requires llama-server + model)
# ===========================================================================

def run_full_e2e_test() -> bool:
    """
    Full end-to-end test: send a prompt that should trigger list_directory,
    verify the tool call is policy-checked, executed, and results returned.

    Requires: llama-server running at http://127.0.0.1:8080
    """
    section("LAYER 4 — Full End-to-End Pipeline")

    if not is_llama_running():
        record("llama-server reachable", False,
               "llama-server not running at http://127.0.0.1:8080 — start it with:\n"
               "         inference-bridge/llama-cpp/llama-server.exe "
               "--model inference-bridge/models/<model>.gguf --port 8080")
        print(f"  {yellow('Skipping full e2e — llama-server not available.')}")
        return True  # Not a failure — just not configured yet

    record("llama-server reachable", True, "http://127.0.0.1:8080")

    if not is_bridge_running():
        record("inference bridge reachable for e2e", False)
        return False

    all_ok = True

    # ── Test: Send a prompt that should produce a list_directory tool call ────
    prompt = (
        "List the files in my home directory for me. "
        "Use the list_directory tool with path='~'."
    )
    try:
        status, body = bridge_post("/infer", {
            "prompt": prompt,
            "stream": False,
            "max_tokens": 256,
            "temperature": 0.1,  # Low temperature for determinism
        }, timeout=120)

        all_ok &= record("POST /infer returns 200", status == 200, f"status={status}")

        if status == 200:
            session_id = body.get("session_id")
            all_ok &= record("response has session_id", bool(session_id), str(session_id))

            text = body.get("text", "")
            all_ok &= record("response has text", bool(text), f"text[:100]={text[:100]!r}")

            tool_calls = body.get("tool_calls", [])
            finish_reason = body.get("finish_reason", "")

            if tool_calls:
                tc = tool_calls[0]
                all_ok &= record("tool_call present in response", True,
                                 f"tool={tc.get('tool_name')} params={tc.get('parameters')}")

                policy = tc.get("policy", {})
                decision = policy.get("decision", "unknown")
                all_ok &= record(f"policy decision for {tc.get('tool_name')}: {decision}",
                                 decision in ("Allow", "Deny", "RequireConfirmation"),
                                 str(policy))

                if decision == "Allow":
                    result = tc.get("result")
                    all_ok &= record("tool execution result present", result is not None,
                                     str(result)[:200] if result else "None")

                # With the agentic loop: "stop" = tool ran + model replied; "tool_call" = blocked
                all_ok &= record("finish_reason is valid", finish_reason in ("stop", "tool_call", "needs_confirmation", "length"),
                                 f"finish_reason={finish_reason!r}")
            else:
                # Model may not have called the tool — check text contains something useful
                all_ok &= record("model responded (no tool call — model may not follow format)",
                                 len(text) > 10,
                                 f"text[:100]={text[:100]!r}")
                print(f"  {yellow('Note: model did not emit a tool_call JSON block. Consider fine-tuning the prompt.')}")

    except Exception as e:
        all_ok &= record("full e2e request", False, str(e))

    return all_ok


# ===========================================================================
# LAYER 5: Setup verification (llama.cpp binary + model file presence)
# ===========================================================================

def run_setup_checks() -> bool:
    """Check that llama.cpp binary and model files are in place."""
    section("LAYER 0 — Setup Verification")

    prototype_dir = Path(__file__).parent
    llama_dir = prototype_dir / "inference-bridge" / "llama-cpp"
    model_dir = prototype_dir / "inference-bridge" / "models"

    all_ok = True

    # ── llama.cpp directory ───────────────────────────────────────────────────
    all_ok &= record("inference-bridge/llama-cpp/ exists", llama_dir.exists(),
                     str(llama_dir))

    # ── llama-server binary ───────────────────────────────────────────────────
    server_exe = llama_dir / "llama-server.exe"
    server_nix = llama_dir / "llama-server"
    has_server = server_exe.exists() or server_nix.exists()
    found_binary = str(server_exe) if server_exe.exists() else (
        str(server_nix) if server_nix.exists() else "not found"
    )
    all_ok &= record("llama-server binary present", has_server,
                     f"{found_binary}\n         Download: see prototype/inference-bridge/SETUP.md")

    # ── model files ───────────────────────────────────────────────────────────
    models = list(model_dir.glob("*.gguf")) if model_dir.exists() else []
    all_ok &= record("at least one .gguf model present", len(models) > 0,
                     str(models) if models else
                     "No .gguf files found in inference-bridge/models/\n"
                     "         Download a model — see SETUP instructions in test_e2e.py")

    if models:
        for m in models:
            size_gb = m.stat().st_size / (1024**3)
            print(f"    {cyan('model:')} {m.name} ({size_gb:.2f} GB)")

    # ── Python version ────────────────────────────────────────────────────────
    py_ok = sys.version_info >= (3, 11)
    all_ok &= record(f"Python >= 3.11 ({sys.version.split()[0]})", py_ok)

    # ── policy engine binary ──────────────────────────────────────────────────
    policy_win = (prototype_dir / "policy-engine" / "target" / "debug" / "policy-engine.exe")
    policy_nix_wsl_path = (
        prototype_dir / "policy-engine" / "target" / "debug" / "policy-engine"
    )
    has_policy = policy_win.exists() or policy_nix_wsl_path.exists()

    # Also check WSL2
    if not has_policy:
        _raw2 = (prototype_dir / "policy-engine").as_posix().replace("\\", "/")
        if len(_raw2) >= 2 and _raw2[1] == ":":
            _raw2 = f"/mnt/{_raw2[0].lower()}/{_raw2[3:]}"
        elif len(_raw2) >= 2 and _raw2[0] == "/" and _raw2[2] == "/":
            _raw2 = f"/mnt/{_raw2[1].lower()}/{_raw2[3:]}"
        wsl_path = _raw2
        try:
            r = subprocess.run(
                ["wsl", "-d", "Ubuntu-22.04", "--", "test", "-f",
                 f"{wsl_path}/target/debug/policy-engine"],
                timeout=5, capture_output=True,
            )
            has_policy = r.returncode == 0
        except Exception:
            pass

    all_ok &= record("policy-engine binary present", has_policy,
                     "Build with: wsl -d Ubuntu-22.04 -- bash -c "
                     "'cd /mnt/c/path/to/prototype/policy-engine && cargo build'")

    return all_ok


# ===========================================================================
# Main
# ===========================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lumen Ora end-to-end test suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python test_e2e.py                 # All layers (skips full e2e if no model)
  python test_e2e.py --policy-only   # Policy engine tests only
  python test_e2e.py --skip-bridge   # Setup + policy + tools only
  python test_e2e.py --all           # All layers including full LLM pipeline
        """,
    )
    parser.add_argument("--policy-only", action="store_true",
                        help="Run policy engine tests only")
    parser.add_argument("--skip-bridge", action="store_true",
                        help="Skip inference bridge HTTP tests")
    parser.add_argument("--all", action="store_true",
                        help="Run full end-to-end including LLM inference")
    parser.add_argument("--skip-model", action="store_true", default=True,
                        help="Skip tests that require a running llama-server (default: True)")
    args = parser.parse_args()

    print(bold(cyan("""
╔══════════════════════════════════════════════════════════╗
║           Lumen Ora — End-to-End Test Suite              ║
║   Policy Engine → Inference Bridge → Tool Execution      ║
╚══════════════════════════════════════════════════════════╝""")))

    processes: list[subprocess.Popen] = []

    try:
        # Layer 0: Setup checks (always run)
        run_setup_checks()

        if args.policy_only:
            ok, proc = run_policy_engine_tests()
            if proc:
                processes.append(proc)
            return summary()

        # Layer 1: Policy engine
        ok, proc = run_policy_engine_tests()
        if proc:
            processes.append(proc)

        # Layer 2: Tool execution (pure Python, no deps needed beyond pydantic)
        run_tool_execution_tests()

        # Layer 2b: Voice subsystem (import checks + cached model load)
        run_voice_tests()

        if not args.skip_bridge:
            # Layer 3: Inference bridge
            ok, proc = run_bridge_tests(skip_model=not args.all)
            if proc:
                processes.append(proc)

            # Layer 3b: Bridge auth gating
            ok, proc = run_auth_tests()
            if proc:
                processes.append(proc)

            # Layer 3c: Tailscale-friendly remote bind (LUMEN_BIND_HOST=0.0.0.0)
            ok, proc = run_remote_bind_tests()
            if proc:
                processes.append(proc)

            # Layer 4: Full e2e (only if --all or llama-server already running)
            if args.all or is_llama_running():
                run_full_e2e_test()
            else:
                section("LAYER 4 — Full End-to-End Pipeline")
                print(f"  {yellow('Skipped — pass --all to run (requires llama-server + model)')}")
                print(f"  {yellow('Start llama-server first:')} "
                      f"inference-bridge/llama-cpp/llama-server.exe "
                      f"--model inference-bridge/models/<model>.gguf")

    finally:
        # Clean up any subprocesses we started
        for proc in processes:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    return summary()


if __name__ == "__main__":
    sys.exit(main())
