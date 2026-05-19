"""
Lumen Ora — Tool Schema Definitions
Defines the 10 core tools available to the AI model.
All tools must pass through the Policy Engine before execution.
"""

from __future__ import annotations

import datetime
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Cached platform check — used by clipboard, screenshot, and other
# OS-conditional code paths. platform.system() returns 'Windows',
# 'Linux', or 'Darwin'.
_IS_WINDOWS = platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Parameter models
# ---------------------------------------------------------------------------

class ReadFileParams(BaseModel):
    path: str = Field(..., description="Absolute or home-relative path to the file to read.")


class WriteFileParams(BaseModel):
    path: str = Field(..., description="Absolute or home-relative path to write.")
    content: str = Field(..., description="Text content to write to the file.")


class RunCommandParams(BaseModel):
    command: str = Field(..., description="The executable to run (e.g. 'git', 'ls').")
    args: list[str] = Field(default_factory=list, description="Arguments to pass to the command.")
    cwd: str | None = Field(None, description="Working directory; defaults to home dir.")
    timeout_seconds: int = Field(30, description="Max seconds to wait for completion.")
    max_output_lines: int = Field(200, description="Cap output at this many lines. Default: 200.")


class SearchWebParams(BaseModel):
    query: str = Field(..., description="The search query string.")
    num_results: int = Field(5, description="Maximum number of results to return.")


class ListDirectoryParams(BaseModel):
    path: str = Field(..., description="Directory path to list.")
    show_hidden: bool = Field(False, description="Whether to include hidden files/dirs.")


class EditFileParams(BaseModel):
    path: str = Field(..., description="Absolute or home-relative path to the file to edit.")
    old_str: str = Field(..., description="The string to find and replace (first occurrence).")
    new_str: str = Field(..., description="The replacement string.")


class ClipboardWriteParams(BaseModel):
    text: str = Field(..., description="Text to write to the clipboard.")


class OpenAppParams(BaseModel):
    name: str = Field(..., description="Application name or path to launch (e.g. 'notepad', 'calc').")


class TakeScreenshotParams(BaseModel):
    filename: str | None = Field(
        None,
        description="Output filename. Defaults to ~/.lumen/screenshots/YYYY-MM-DD_HH-MM-SS.png.",
    )


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

class CommandResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    truncated: bool = False
    lines_captured: int = 0


class DirectoryEntry(BaseModel):
    name: str
    type: str  # "file" | "directory" | "symlink" | "other"
    size: int  # bytes; -1 for directories


class WebResult(BaseModel):
    title: str
    url: str
    snippet: str


# ---------------------------------------------------------------------------
# Tool registry — JSON Schema descriptors for the model
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read the contents of a file at the given path. Returns the file's text content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or home-relative path to the file.",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write text content to a file. Creates the file if it does not exist; overwrites if it does.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or home-relative path to write.",
                },
                "content": {
                    "type": "string",
                    "description": "Text content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "run_command",
        "description": "Run a shell command and return stdout, stderr, and exit code.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The executable to run.",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments to pass to the command.",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (optional).",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Max seconds to wait. Default: 30.",
                },
                "max_output_lines": {
                    "type": "integer",
                    "description": "Cap output at this many lines. Default: 200.",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "search_web",
        "description": "Search the web for a query via DuckDuckGo. Returns a list of {title, url, snippet} results.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query.",
                },
                "num_results": {
                    "type": "integer",
                    "description": "Max results to return. Default: 5.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "list_directory",
        "description": "List the contents of a directory. Returns [{name, type, size}] for each entry.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list.",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files. Default: false.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "edit_file",
        "description": (
            "Edit a file by replacing the FIRST occurrence of old_str with new_str. "
            "Returns {replaced: true, path: ...} on success or {replaced: false, error: ...} if not found."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or home-relative path to the file to edit.",
                },
                "old_str": {
                    "type": "string",
                    "description": "The string to find (first occurrence will be replaced).",
                },
                "new_str": {
                    "type": "string",
                    "description": "The replacement string.",
                },
            },
            "required": ["path", "old_str", "new_str"],
        },
    },
    {
        "name": "clipboard_read",
        "description": "Read the current contents of the system clipboard. Returns the clipboard text.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
    {
        "name": "clipboard_write",
        "description": "Write text to the system clipboard. Returns {written: true} on success.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Text to place on the clipboard.",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "open_app",
        "description": (
            "Launch an application by name (e.g. 'notepad', 'calc', 'chrome'). "
            "Returns {launched: name} immediately without waiting for the process."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Application name or path to launch.",
                },
            },
            "required": ["name"],
        },
    },
    {
        "name": "take_screenshot",
        "description": (
            "Take a screenshot and save it to disk. "
            "Returns {path, width, height} on success. "
            "Requires pillow or mss to be installed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "filename": {
                    "type": "string",
                    "description": (
                        "Output file path. Defaults to "
                        "~/.lumen/screenshots/YYYY-MM-DD_HH-MM-SS.png."
                    ),
                },
            },
            "required": [],
        },
    },
]


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def execute_read_file(params: ReadFileParams) -> str:
    """Read and return file contents."""
    p = Path(params.path).expanduser()
    return p.read_text(encoding="utf-8", errors="replace")


def execute_write_file(params: WriteFileParams) -> bool:
    """Write content to file; return True on success."""
    p = Path(params.path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(params.content, encoding="utf-8")
    return True


def execute_run_command(params: RunCommandParams) -> CommandResult:
    """
    Run a subprocess line-by-line via Popen (merged stdout+stderr).
    Caps output at max_output_lines lines and respects timeout_seconds.
    Returns a CommandResult with truncated/lines_captured fields.
    """
    cwd = params.cwd or str(Path.home())
    max_lines = params.max_output_lines
    deadline = time.monotonic() + params.timeout_seconds

    try:
        proc = subprocess.Popen(
            [params.command, *params.args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        return CommandResult(
            stdout="",
            stderr=f"Command not found: {params.command}",
            exit_code=127,
            truncated=False,
            lines_captured=0,
        )

    captured_lines: list[str] = []
    truncated = False

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            if time.monotonic() >= deadline:
                # Timeout — kill and mark
                proc.kill()
                captured_lines.append("\n[timed out]")
                proc.wait()
                return CommandResult(
                    stdout="".join(captured_lines),
                    stderr="",
                    exit_code=-1,
                    truncated=truncated,
                    lines_captured=len(captured_lines),
                )

            if len(captured_lines) < max_lines:
                captured_lines.append(line)
            else:
                # Count remaining lines for the truncation note
                remaining = sum(1 for _ in proc.stdout)  # type: ignore[union-attr]
                truncated = True
                extra = remaining + 1  # +1 for the current line we didn't store
                captured_lines.append(f"... {extra} more lines\n")
                break

        # Wait for process to exit (it may still be running if we broke early)
        try:
            remaining_timeout = max(0.0, deadline - time.monotonic())
            proc.wait(timeout=remaining_timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
            captured_lines.append("\n[timed out]")
            return CommandResult(
                stdout="".join(captured_lines),
                stderr="",
                exit_code=-1,
                truncated=truncated,
                lines_captured=len(captured_lines),
            )

    except Exception:
        proc.kill()
        proc.wait()
        raise

    return CommandResult(
        stdout="".join(captured_lines),
        stderr="",
        exit_code=proc.returncode,
        truncated=truncated,
        lines_captured=len(captured_lines),
    )


def execute_search_web(params: SearchWebParams) -> list[WebResult]:
    """Search the web via DuckDuckGo (no API key required)."""
    try:
        from ddgs import DDGS  # current package name
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # legacy name fallback
        except ImportError:
            return [WebResult(
                title="search_web unavailable",
                url="",
                snippet="Install with: pip install ddgs"
            )]

    results = []
    try:
        with DDGS() as ddgs:
            for r in ddgs.text(params.query, max_results=params.num_results):
                results.append(WebResult(
                    title=r.get("title", ""),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                ))
    except Exception as exc:
        results.append(WebResult(
            title="Search error",
            url="",
            snippet=str(exc),
        ))
    return results


def execute_list_directory(params: ListDirectoryParams) -> list[DirectoryEntry]:
    """List a directory and return metadata for each entry."""
    p = Path(params.path).expanduser()
    entries: list[DirectoryEntry] = []
    for item in sorted(p.iterdir()):
        if not params.show_hidden and item.name.startswith("."):
            continue
        try:
            stat = item.stat()
            size = stat.st_size if item.is_file() else -1
            if item.is_symlink():
                kind = "symlink"
            elif item.is_dir():
                kind = "directory"
            elif item.is_file():
                kind = "file"
            else:
                kind = "other"
            entries.append(DirectoryEntry(name=item.name, type=kind, size=size))
        except OSError:
            entries.append(DirectoryEntry(name=item.name, type="other", size=-1))
    return entries


def execute_edit_file(params: EditFileParams) -> dict[str, Any]:
    """Replace the first occurrence of old_str with new_str in a file."""
    p = Path(params.path).expanduser()
    try:
        original = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {"replaced": False, "error": str(exc)}
    if params.old_str not in original:
        return {"replaced": False, "error": "string not found"}
    updated = original.replace(params.old_str, params.new_str, 1)
    p.write_text(updated, encoding="utf-8")
    return {"replaced": True, "path": str(p)}


def execute_clipboard_read(_params: Any) -> Any:
    """
    Read text from the system clipboard.
    Windows: uses PowerShell Get-Clipboard (no extra deps).
    Linux/macOS: uses pyperclip (which auto-detects xclip/xsel/pbcopy).
    """
    if _IS_WINDOWS:
        try:
            result = subprocess.run(
                ["powershell", "-command", "Get-Clipboard"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return {"error": f"clipboard unavailable: {result.stderr.strip()}"}
            return result.stdout.strip()
        except Exception as exc:
            return {"error": f"clipboard unavailable: {exc}"}

    # Linux / macOS path — pyperclip handles pbcopy/xclip/xsel detection.
    try:
        import pyperclip  # type: ignore
    except ImportError:
        return {"error": "clipboard unavailable: install with 'pip install pyperclip'"}
    try:
        return pyperclip.paste()
    except Exception as exc:
        # pyperclip raises PyperclipException when no backend is installed
        # (Linux without xclip/xsel/wl-copy). Return a clean error string.
        return {"error": f"clipboard unavailable: {exc}"}


def execute_clipboard_write(params: ClipboardWriteParams) -> dict[str, Any]:
    """
    Write text to the system clipboard.
    Windows: uses clip.exe with UTF-16-LE encoding (no extra deps).
    Linux/macOS: uses pyperclip.
    """
    if _IS_WINDOWS:
        try:
            subprocess.run(
                ["clip"],
                input=params.text.encode("utf-16-le"),
                check=True,
                timeout=10,
            )
            return {"written": True}
        except Exception as exc:
            return {"error": str(exc)}

    try:
        import pyperclip  # type: ignore
    except ImportError:
        return {"error": "clipboard unavailable: install with 'pip install pyperclip'"}
    try:
        pyperclip.copy(params.text)
        return {"written": True}
    except Exception as exc:
        return {"error": f"clipboard unavailable: {exc}"}


def execute_open_app(params: OpenAppParams) -> dict[str, Any]:
    """Launch an application by name without waiting for it to exit."""
    try:
        subprocess.Popen(["start", params.name], shell=True)
        return {"launched": params.name}
    except Exception as exc:
        return {"error": str(exc)}


def execute_take_screenshot(params: TakeScreenshotParams) -> dict[str, Any]:
    """
    Take a screenshot and save it.
    Uses mss as the primary cross-platform backend (Windows/Linux/macOS).
    Falls back to PIL.ImageGrab on Windows if mss is unavailable.
    """
    # Determine output filepath
    if params.filename:
        filepath = Path(params.filename).expanduser()
    else:
        screenshots_dir = Path.home() / ".lumen" / "screenshots"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filepath = screenshots_dir / f"{ts}.png"

    filepath.parent.mkdir(parents=True, exist_ok=True)

    # Primary: mss (cross-platform — works on Windows, Linux, macOS).
    try:
        import mss  # type: ignore
        import mss.tools  # type: ignore
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # full virtual screen
            shot = sct.grab(monitor)
            mss.tools.to_png(shot.rgb, shot.size, output=str(filepath))
            return {"path": str(filepath), "width": shot.width, "height": shot.height}
    except ImportError:
        pass
    except Exception as exc:
        # mss can fail on Linux without a display (headless CI). Fall through
        # to PIL on Windows, otherwise return a clean error below.
        if not _IS_WINDOWS:
            return {"error": f"screenshot failed: {exc}"}

    # Windows-only fallback: PIL.ImageGrab (kept for back-compat — no new dep).
    if _IS_WINDOWS:
        try:
            from PIL import ImageGrab  # type: ignore
            img = ImageGrab.grab()
            img.save(str(filepath))
            w, h = img.size
            return {"path": str(filepath), "width": w, "height": h}
        except ImportError:
            pass
        except Exception as exc:
            return {"error": f"screenshot failed: {exc}"}

    return {"error": "Install mss: pip install mss"}


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TOOL_EXECUTORS = {
    "read_file": lambda p: execute_read_file(ReadFileParams(**p)),
    "write_file": lambda p: execute_write_file(WriteFileParams(**p)),
    "run_command": lambda p: execute_run_command(RunCommandParams(**p)),
    "search_web": lambda p: execute_search_web(SearchWebParams(**p)),
    "list_directory": lambda p: execute_list_directory(ListDirectoryParams(**p)),
    "edit_file": lambda p: execute_edit_file(EditFileParams(**p)),
    "clipboard_read": lambda p: execute_clipboard_read(p),
    "clipboard_write": lambda p: execute_clipboard_write(ClipboardWriteParams(**p)),
    "open_app": lambda p: execute_open_app(OpenAppParams(**p)),
    "take_screenshot": lambda p: execute_take_screenshot(TakeScreenshotParams(**p)),
}


# ---------------------------------------------------------------------------
# Plugin loader — auto-loads tools from ~/.lumen/tools/*.py
# ---------------------------------------------------------------------------

def _load_plugins() -> None:
    """
    Scan ~/.lumen/tools/ for *.py plugin files.
    Each must export PLUGIN_TOOLS: list of {name, description, parameters, execute}.
    Registered tools become available via dispatch_tool and appear in TOOL_SCHEMAS.
    """
    plugin_dir = Path.home() / ".lumen" / "tools"
    if not plugin_dir.exists():
        return

    import importlib.util

    for plugin_file in sorted(plugin_dir.glob("*.py")):
        try:
            spec = importlib.util.spec_from_file_location(plugin_file.stem, plugin_file)
            module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(module)  # type: ignore[union-attr]

            tools: list[dict[str, Any]] = getattr(module, "PLUGIN_TOOLS", [])
            for tool in tools:
                name = tool.get("name", "")
                execute_fn = tool.get("execute")
                if not name or not callable(execute_fn):
                    continue
                # Register in schema list and executor map
                schema = {k: v for k, v in tool.items() if k != "execute"}
                TOOL_SCHEMAS.append(schema)
                TOOL_EXECUTORS[name] = lambda p, fn=execute_fn: fn(p)
        except Exception as exc:
            # Bad plugin — warn but don't crash
            import logging as _log
            _log.getLogger("lumen.plugins").warning("Failed to load plugin %s: %s", plugin_file, exc)


_load_plugins()


def dispatch_tool(tool_name: str, parameters: dict[str, Any]) -> Any:
    """Execute a tool by name. Raises KeyError for unknown tools."""
    executor = TOOL_EXECUTORS[tool_name]
    result = executor(parameters)
    # Convert Pydantic models to dicts for JSON serialization
    if hasattr(result, "model_dump"):
        return result.model_dump()
    if isinstance(result, list) and result and hasattr(result[0], "model_dump"):
        return [r.model_dump() for r in result]
    return result
