"""
Lumen Ora — Tool Schema Definitions
Defines the 5 core tools available to the AI model.
All tools must pass through the Policy Engine before execution.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


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


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

TOOL_EXECUTORS = {
    "read_file": lambda p: execute_read_file(ReadFileParams(**p)),
    "write_file": lambda p: execute_write_file(WriteFileParams(**p)),
    "run_command": lambda p: execute_run_command(RunCommandParams(**p)),
    "search_web": lambda p: execute_search_web(SearchWebParams(**p)),
    "list_directory": lambda p: execute_list_directory(ListDirectoryParams(**p)),
}


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
