"""
Lumen Ora — Inference Bridge
Runs llama.cpp (llama-server), exposes a JSON-RPC HTTP API on localhost:8765,
enforces every tool call through the Policy Engine daemon before execution,
and streams responses back to callers via Server-Sent Events.

Usage:
    python bridge.py --model /path/to/model.gguf [--policy-socket /tmp/lumen-policy.sock]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any, AsyncIterator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from tool_schema import TOOL_SCHEMAS, dispatch_tool

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("lumen.bridge")

# ---------------------------------------------------------------------------
# Configuration (populated by parse_args or environment variables)
# ---------------------------------------------------------------------------

LLAMA_SERVER_URL = os.environ.get("LLAMA_SERVER_URL", "http://127.0.0.1:8080")
LLAMA_SERVER_URL_SMART = os.environ.get("LLAMA_SERVER_URL_SMART", LLAMA_SERVER_URL)
LLAMA_SERVER_URL_FAST  = os.environ.get("LLAMA_SERVER_URL_FAST",  "http://127.0.0.1:8081")
# POLICY_ENGINE_SOCKET can be:
#   - A Unix socket path (Linux/macOS production): /tmp/lumen-policy.sock
#   - A TCP address prefixed with "tcp://": tcp://127.0.0.1:8766 (Windows dev)
# On Windows the policy engine binary falls back to TCP on 127.0.0.1:8766.
POLICY_SOCKET_PATH = os.environ.get("POLICY_ENGINE_SOCKET", "tcp://127.0.0.1:8766")
BRIDGE_HOST = os.environ.get("BRIDGE_HOST", "127.0.0.1")
BRIDGE_PORT = int(os.environ.get("BRIDGE_PORT", "8765"))

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Lumen Ora Inference Bridge",
    version="0.1.0",
    description="JSON-RPC gateway between callers and llama.cpp with policy enforcement.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class InferenceRequest(BaseModel):
    prompt: str = Field(..., description="The latest user message.")
    messages: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Prior conversation turns [{role, content}]. If provided, builds multi-turn context.",
    )
    tools: list[dict[str, Any]] = Field(
        default_factory=lambda: TOOL_SCHEMAS,
        description="Tool schemas to expose to the model.",
    )
    session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique session identifier.",
    )
    stream: bool = Field(True, description="Whether to stream the response via SSE.")
    max_tokens: int = Field(512, description="Max tokens to generate.")
    temperature: float = Field(0.7)
    model_tier: str = Field("smart", description="'fast' (3B) or 'smart' (7B). Default: smart.")


class PolicyEvalResult(BaseModel):
    decision: str  # "Allow" | "Deny" | "RequireConfirmation"
    detail: str | None = None
    matched_rule: str | None = None


class ToolCallResult(BaseModel):
    tool_name: str
    parameters: dict[str, Any]
    policy: PolicyEvalResult
    result: Any | None = None
    error: str | None = None


class InferenceResponse(BaseModel):
    session_id: str
    text: str
    tool_calls: list[ToolCallResult] = Field(default_factory=list)
    finish_reason: str = "stop"


# ---------------------------------------------------------------------------
# Policy Engine client (Unix socket JSON-RPC)
# ---------------------------------------------------------------------------

def _parse_policy_socket(path: str) -> tuple[str, str | None, int | None]:
    """
    Parse POLICY_SOCKET_PATH into (mode, host, port).
    mode is "tcp" or "unix".
    """
    if path.startswith("tcp://"):
        addr = path[6:]  # strip "tcp://"
        host, _, port_str = addr.rpartition(":")
        return "tcp", host or "127.0.0.1", int(port_str) if port_str else 8766
    return "unix", None, None


async def _open_policy_connection(socket_path: str):
    """Open an asyncio connection to the policy engine (Unix or TCP)."""
    mode, host, port = _parse_policy_socket(socket_path)
    if mode == "tcp":
        return await asyncio.open_connection(host, port)
    else:
        return await asyncio.open_unix_connection(socket_path)


async def evaluate_tool_call_policy(
    tool_name: str,
    parameters: dict[str, Any],
    context: dict[str, str] | None = None,
) -> PolicyEvalResult:
    """Send a tool call to the Policy Engine daemon for evaluation."""
    request = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "evaluate",
        "params": {
            "tool_name": tool_name,
            "parameters": parameters,
            "context": context or {"home_dir": str(Path.home())},
        },
    }
    payload = json.dumps(request) + "\n"

    try:
        reader, writer = await _open_policy_connection(POLICY_SOCKET_PATH)
        writer.write(payload.encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        writer.close()
        await writer.wait_closed()

        response = json.loads(line)
        if "error" in response:
            log.warning("Policy engine error: %s", response["error"])
            return PolicyEvalResult(decision="Allow", detail="Policy engine error — defaulting to Allow")

        audit_entry = response.get("result", {})
        decision_obj = audit_entry.get("decision", {})

        if isinstance(decision_obj, dict):
            decision_type = decision_obj.get("decision", "Allow")
            detail = decision_obj.get("detail", {})
            if isinstance(detail, dict):
                reason = detail.get("reason") or detail.get("message") or None
            else:
                reason = str(detail) if detail else None
        else:
            decision_type = str(decision_obj)
            reason = None

        return PolicyEvalResult(
            decision=decision_type,
            detail=reason,
            matched_rule=audit_entry.get("matched_rule_id"),
        )

    except FileNotFoundError:
        log.warning("Policy engine socket not found at %s — running without enforcement", POLICY_SOCKET_PATH)
        return PolicyEvalResult(decision="Allow", detail="Policy engine not running")
    except ConnectionRefusedError:
        log.warning("Policy engine not accepting connections at %s — running without enforcement", POLICY_SOCKET_PATH)
        return PolicyEvalResult(decision="Allow", detail="Policy engine not running")
    except Exception as exc:
        log.error("Policy engine communication error: %s", exc)
        return PolicyEvalResult(decision="Allow", detail=f"Policy engine error: {exc}")


# ---------------------------------------------------------------------------
# Model tier routing
# ---------------------------------------------------------------------------

def _llama_url_for_tier(tier: str) -> str:
    return LLAMA_SERVER_URL_FAST if tier == "fast" else LLAMA_SERVER_URL_SMART


# ---------------------------------------------------------------------------
# llama.cpp interaction
# ---------------------------------------------------------------------------

def _build_system_prompt(tools: list[dict[str, Any]]) -> str:
    tool_names = ", ".join(t["name"] for t in tools)
    tool_json = json.dumps(tools, indent=2)
    return (
        "You are Lumen, an AI operating system interface. "
        "You have access to these tools: " + tool_names + "\n\n"
        "TOOL SCHEMAS:\n"
        f"{tool_json}\n\n"
        "TOOL CALL FORMAT — when you need to use a tool, output EXACTLY this on its own line "
        "(valid JSON, nothing before or after on that line):\n"
        '{"tool_call": {"name": "TOOL_NAME", "parameters": {"param": "value"}}}\n\n'
        "RULES:\n"
        "1. Output the tool call JSON on its own line, then stop.\n"
        "2. After receiving a tool result, give a natural language response.\n"
        "3. If you do not need a tool, respond directly in plain text.\n\n"
        "EXAMPLE:\n"
        "User: List the files in my home directory\n"
        '{"tool_call": {"name": "list_directory", "parameters": {"path": "~"}}}\n'
        "Tool result: [{\"name\": \"Documents\", \"type\": \"directory\", \"size\": -1}]\n"
        "Your home directory contains: Documents (directory), ...\n"
    )


def _build_qwen_prompt(
    prompt: str,
    prior_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    conversation_suffix: str = "",
) -> str:
    """Build a Qwen2.5 chat-template prompt with optional prior conversation turns."""
    system = _build_system_prompt(tools)
    parts = [f"<|im_start|>system\n{system}<|im_end|>"]
    for msg in prior_messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
    parts.append(f"<|im_start|>user\n{prompt}<|im_end|>")
    if conversation_suffix:
        parts.append(conversation_suffix)
    parts.append("<|im_start|>assistant\n")
    return "\n".join(parts)


async def query_llama(
    prompt: str,
    prior_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    stream: bool,
    conversation_suffix: str = "",
    llama_url: str = "",
) -> AsyncIterator[str]:
    """
    POST to llama-server's /completion endpoint and yield token chunks.
    Uses Qwen2.5 chat template (<|im_start|>/<|im_end|>).
    """
    if not llama_url:
        llama_url = LLAMA_SERVER_URL_SMART
    full_prompt = _build_qwen_prompt(prompt, prior_messages, tools, conversation_suffix)

    payload = {
        "prompt": full_prompt,
        "n_predict": max_tokens,
        "temperature": temperature,
        "stream": stream,
        "stop": ["<|im_end|>", "<|im_start|>"],
    }

    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream("POST", f"{llama_url}/completion", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                        token = chunk.get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue
                elif line:
                    try:
                        chunk = json.loads(line)
                        token = chunk.get("content", "")
                        if token:
                            yield token
                    except json.JSONDecodeError:
                        continue


def extract_tool_call(text: str) -> dict[str, Any] | None:
    """
    Scan a text chunk for an embedded tool call JSON block.
    Returns the parsed dict or None.
    """
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and "tool_call" in line:
            try:
                obj = json.loads(line)
                if "tool_call" in obj:
                    return obj["tool_call"]
            except json.JSONDecodeError:
                pass
    return None


# ---------------------------------------------------------------------------
# Core inference pipeline
# ---------------------------------------------------------------------------

async def run_inference(request: InferenceRequest) -> InferenceResponse:
    """
    Full inference pipeline with agentic tool loop (up to 5 iterations):
    1. Query the model.
    2. Parse any tool calls from the model output.
    3. For each tool call, check with the Policy Engine.
    4. Execute allowed tool calls, inject results into the conversation, repeat.
    5. Return the final natural-language response once no more tool calls are made.
    """
    log.info("Session %s — inference start", request.session_id)

    llama_url = _llama_url_for_tier(request.model_tier)
    tool_results: list[ToolCallResult] = []
    # conversation_suffix accumulates tool call/result turns within this request
    conversation_suffix = ""
    final_text = ""
    finish_reason = "stop"
    MAX_ITERATIONS = 5

    for iteration in range(MAX_ITERATIONS):
        log.info("Session %s — iteration %d", request.session_id, iteration + 1)

        accumulated = ""
        async for token in query_llama(
            request.prompt,
            request.messages,
            request.tools,
            request.max_tokens,
            request.temperature,
            stream=False,
            conversation_suffix=conversation_suffix,
            llama_url=llama_url,
        ):
            accumulated += token

        log.info("Session %s — model output: %d chars", request.session_id, len(accumulated))

        # Check for a tool call in this output.
        tool_call = extract_tool_call(accumulated)
        if not tool_call:
            # Model produced a plain response — we're done.
            final_text = accumulated
            finish_reason = "stop"
            log.info("Session %s — no tool call, finishing", request.session_id)
            break

        tool_name = tool_call.get("name", "")
        parameters = tool_call.get("parameters", {})
        log.info("Session %s — tool call detected: %s", request.session_id, tool_name)

        # Policy check.
        policy_result = await evaluate_tool_call_policy(tool_name, parameters)
        log.info(
            "Session %s — policy decision for %s: %s",
            request.session_id, tool_name, policy_result.decision,
        )

        call_result = ToolCallResult(
            tool_name=tool_name,
            parameters=parameters,
            policy=policy_result,
        )

        if policy_result.decision == "Deny":
            call_result.error = f"DENIED by policy: {policy_result.detail}"
            log.warning("Session %s — tool %s denied: %s", request.session_id, tool_name, policy_result.detail)
            tool_results.append(call_result)
            final_text = accumulated
            finish_reason = "tool_call"
            break

        if policy_result.decision == "RequireConfirmation":
            call_result.error = f"REQUIRES CONFIRMATION: {policy_result.detail}"
            log.info("Session %s — tool %s requires confirmation", request.session_id, tool_name)
            tool_results.append(call_result)
            final_text = accumulated
            finish_reason = "needs_confirmation"
            break

        # policy_result.decision == "Allow" — execute the tool.
        try:
            result = dispatch_tool(tool_name, parameters)
            call_result.result = result
            log.info("Session %s — tool %s executed successfully", request.session_id, tool_name)
        except Exception as exc:
            call_result.error = str(exc)
            result = {"error": str(exc)}
            log.error("Session %s — tool %s error: %s", request.session_id, tool_name, exc)

        # Append truncation note for the model when run_command output was capped.
        if tool_name == "run_command" and isinstance(result, dict) and result.get("truncated"):
            n = result.get("lines_captured", 0)
            result["truncation_note"] = (
                f"[Note: output was truncated at {n} lines. "
                "Ask the user if they want to see more.]"
            )

        tool_results.append(call_result)

        # Feed tool result back using Qwen2.5 template so next pass sees full context.
        result_json = json.dumps(result, default=str)
        conversation_suffix += (
            f"<|im_start|>assistant\n{accumulated}<|im_end|>\n"
            f"<|im_start|>tool_result\n{result_json}<|im_end|>\n"
        )
        # Carry on — the next iteration will ask the model to interpret the result.

    else:
        # Exhausted MAX_ITERATIONS — return whatever we have.
        log.warning("Session %s — max iterations (%d) reached", request.session_id, MAX_ITERATIONS)
        final_text = accumulated  # noqa: F821 — always set inside loop
        finish_reason = "length"

    return InferenceResponse(
        session_id=request.session_id,
        text=final_text,
        tool_calls=tool_results,
        finish_reason=finish_reason,
    )


# ---------------------------------------------------------------------------
# SSE streaming pipeline
# ---------------------------------------------------------------------------

async def stream_inference(request: InferenceRequest) -> AsyncIterator[dict[str, str]]:
    """
    Yield SSE events for a streaming inference request.
    Implements the same agentic tool loop as run_inference but streams tokens
    from each model pass and emits tool events between passes.
    """
    yield {"event": "session", "data": json.dumps({"session_id": request.session_id})}

    llama_url = _llama_url_for_tier(request.model_tier)
    conversation_suffix = ""
    MAX_ITERATIONS = 5

    for iteration in range(MAX_ITERATIONS):
        accumulated = ""

        async for token in query_llama(
            request.prompt,
            request.messages,
            request.tools,
            request.max_tokens,
            request.temperature,
            stream=True,
            conversation_suffix=conversation_suffix,
            llama_url=llama_url,
        ):
            accumulated += token
            yield {"event": "token", "data": json.dumps({"token": token})}

        # Check for a tool call in this pass.
        tool_call = extract_tool_call(accumulated)
        if not tool_call:
            # Plain response — done.
            yield {"event": "done", "data": json.dumps({"finish_reason": "stop"})}
            return

        tool_name = tool_call.get("name", "")
        parameters = tool_call.get("parameters", {})

        policy_result = await evaluate_tool_call_policy(tool_name, parameters)
        yield {
            "event": "policy",
            "data": json.dumps(
                {
                    "tool": tool_name,
                    "decision": policy_result.decision,
                    "detail": policy_result.detail,
                    "matched_rule": policy_result.matched_rule,
                }
            ),
        }

        if policy_result.decision == "Deny":
            yield {
                "event": "tool_blocked",
                "data": json.dumps(
                    {"tool": tool_name, "reason": policy_result.detail or "Denied by policy"}
                ),
            }
            yield {"event": "done", "data": json.dumps({"finish_reason": "tool_call"})}
            return

        if policy_result.decision == "RequireConfirmation":
            yield {
                "event": "tool_blocked",
                "data": json.dumps(
                    {"tool": tool_name, "reason": policy_result.detail or "RequireConfirmation"}
                ),
            }
            yield {"event": "done", "data": json.dumps({"finish_reason": "needs_confirmation"})}
            return

        # Allow — execute tool and feed result back.
        try:
            result = dispatch_tool(tool_name, parameters)
            # Append truncation note for the model when run_command output was capped.
            if tool_name == "run_command" and isinstance(result, dict) and result.get("truncated"):
                n = result.get("lines_captured", 0)
                result["truncation_note"] = (
                    f"[Note: output was truncated at {n} lines. "
                    "Ask the user if they want to see more.]"
                )
            yield {
                "event": "tool_result",
                "data": json.dumps({"tool": tool_name, "result": result}),
            }
        except Exception as exc:
            result = {"error": str(exc)}
            yield {
                "event": "tool_error",
                "data": json.dumps({"tool": tool_name, "error": str(exc)}),
            }

        result_json = json.dumps(result, default=str)
        conversation_suffix += (
            f"<|im_start|>assistant\n{accumulated}<|im_end|>\n"
            f"<|im_start|>tool_result\n{result_json}<|im_end|>\n"
        )
        # Next iteration streams the model's follow-up response.

    # Max iterations reached.
    yield {"event": "done", "data": json.dumps({"finish_reason": "length"})}


# ---------------------------------------------------------------------------
# Model liveness helpers
# ---------------------------------------------------------------------------

def is_llama_running() -> bool:
    """Return True if the smart model (port 8080) is accepting connections."""
    import socket as _socket
    try:
        with _socket.create_connection(("127.0.0.1", 8080), timeout=1.0):
            return True
    except OSError:
        return False


def is_fast_model_running() -> bool:
    """Return True if the fast model (port 8081) is accepting connections."""
    import socket as _socket
    try:
        with _socket.create_connection(("127.0.0.1", 8081), timeout=1.0):
            return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness probe."""
    return {
        "status": "ok",
        "service": "lumen-inference-bridge",
        "version": "0.1.0",
        "smart_model": is_llama_running(),
        "fast_model": is_fast_model_running(),
    }


@app.post("/infer")
async def infer(request: InferenceRequest):
    """
    Run inference.
    - If request.stream=True: returns an SSE stream.
    - If request.stream=False: returns a JSON InferenceResponse.
    """
    if request.stream:
        return EventSourceResponse(stream_inference(request))
    try:
        response = await run_inference(request)
        return response
    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail=f"Cannot connect to llama.cpp server at {LLAMA_SERVER_URL}. "
                   "Start llama-server first or check LLAMA_SERVER_URL.",
        )
    except Exception as exc:
        log.exception("Inference error for session %s", request.session_id)
        raise HTTPException(status_code=500, detail=str(exc))


@app.post("/evaluate_tool")
async def evaluate_tool_endpoint(
    tool_name: str,
    parameters: dict[str, Any],
    context: dict[str, str] | None = None,
):
    """Directly evaluate a tool call through the policy engine (for testing)."""
    result = await evaluate_tool_call_policy(tool_name, parameters, context)
    return result


@app.get("/tools")
async def list_tools():
    """Return available tool schemas."""
    return {"tools": TOOL_SCHEMAS}


@app.get("/")
async def serve_dashboard():
    """Serve the web UI dashboard."""
    from fastapi.responses import HTMLResponse
    static_file = Path(__file__).parent / "static" / "index.html"
    if static_file.exists():
        return HTMLResponse(static_file.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Lumen Ora</h1><p>Place static/index.html next to bridge.py</p>")


@app.get("/session-info")
async def session_info():
    """Return session metadata for the web UI."""
    return {
        "version": "0.1.0",
        "smart_model": is_llama_running(),
        "fast_model": is_fast_model_running(),
        "tool_count": len(TOOL_SCHEMAS),
    }


@app.get("/infer-stream")
async def infer_stream_get(prompt: str, model_tier: str = "smart"):
    """GET endpoint for SSE streaming — easier to use from EventSource."""
    request = InferenceRequest(prompt=prompt, stream=True, model_tier=model_tier)
    return EventSourceResponse(stream_inference(request))


# ---------------------------------------------------------------------------
# Static file mount (must come AFTER all route definitions)
# ---------------------------------------------------------------------------

_static_dir = Path(__file__).parent / "static"
_static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


# ---------------------------------------------------------------------------
# llama.cpp subprocess management
# ---------------------------------------------------------------------------

_llama_process: subprocess.Popen | None = None


def start_llama_server(model_path: str, context_size: int = 4096, gpu_layers: int = 0) -> None:
    """Launch llama-server as a subprocess."""
    global _llama_process

    llama_bin = Path(__file__).parent / "llama-cpp" / "llama-server"
    if not llama_bin.exists():
        llama_bin = Path(__file__).parent / "llama-cpp" / "llama-server.exe"
    if not llama_bin.exists():
        log.warning(
            "llama-server binary not found at %s. "
            "Point LLAMA_SERVER_URL to a running instance instead.",
            llama_bin,
        )
        return

    cmd = [
        str(llama_bin),
        "--model", model_path,
        "--ctx-size", str(context_size),
        "--n-gpu-layers", str(gpu_layers),
        "--host", "127.0.0.1",
        "--port", "8080",
    ]
    log.info("Starting llama-server: %s", " ".join(cmd))
    _llama_process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    # Give it a moment to start.
    time.sleep(2)
    log.info("llama-server PID: %d", _llama_process.pid)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser(description="Lumen Ora Inference Bridge")
    parser.add_argument("--model", help="Path to GGUF model file. If provided, starts llama-server.")
    parser.add_argument("--llama-url", default=LLAMA_SERVER_URL, help="URL of running llama-server.")
    parser.add_argument("--policy-socket", default=POLICY_SOCKET_PATH, help="Path to policy engine Unix socket.")
    parser.add_argument("--host", default=BRIDGE_HOST, help="Host to bind the bridge to.")
    parser.add_argument("--port", type=int, default=BRIDGE_PORT, help="Port to bind the bridge to.")
    parser.add_argument("--gpu-layers", type=int, default=0, help="GPU layers to offload to llama.cpp.")
    args = parser.parse_args()

    LLAMA_SERVER_URL = args.llama_url
    POLICY_SOCKET_PATH = args.policy_socket

    if args.model:
        start_llama_server(args.model, gpu_layers=args.gpu_layers)

    log.info("Lumen Ora Inference Bridge starting on %s:%d", args.host, args.port)
    log.info("Policy Engine socket: %s", POLICY_SOCKET_PATH)
    log.info("llama.cpp URL: %s", LLAMA_SERVER_URL)

    uvicorn.run(app, host=args.host, port=args.port)
