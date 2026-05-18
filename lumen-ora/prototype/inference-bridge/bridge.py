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
    prompt: str = Field(..., description="The user prompt / conversation history.")
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
# llama.cpp interaction
# ---------------------------------------------------------------------------

async def query_llama(
    prompt: str,
    tools: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    stream: bool,
) -> AsyncIterator[str]:
    """
    POST to llama-server's /completion endpoint and yield token chunks.
    Handles both streaming and non-streaming modes.
    """
    # Build a tool-aware system prompt when tools are available.
    tool_json = json.dumps(tools, indent=2)
    system = (
        "You are a helpful AI assistant with access to the following tools:\n"
        f"{tool_json}\n\n"
        "To call a tool, output a JSON block on its own line in this format:\n"
        '{"tool_call": {"name": "<tool_name>", "parameters": {<params>}}}\n'
        "Wait for the tool result before continuing your response.\n"
    )
    full_prompt = f"<|system|>\n{system}\n<|user|>\n{prompt}\n<|assistant|>\n"

    payload = {
        "prompt": full_prompt,
        "n_predict": max_tokens,
        "temperature": temperature,
        "stream": stream,
        "stop": ["<|user|>", "<|system|>"],
    }

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", f"{LLAMA_SERVER_URL}/completion", json=payload) as resp:
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
    Full inference pipeline:
    1. Query the model.
    2. Parse any tool calls from the model output.
    3. For each tool call, check with the Policy Engine.
    4. Execute allowed tool calls and inject results.
    5. Return the complete response.
    """
    log.info("Session %s — inference start", request.session_id)

    accumulated = ""
    tool_results: list[ToolCallResult] = []

    # Collect the full model output first (we'll handle streaming separately).
    async for token in query_llama(
        request.prompt, request.tools, request.max_tokens, request.temperature, stream=False
    ):
        accumulated += token

    log.info("Session %s — model output: %d chars", request.session_id, len(accumulated))

    # Check for tool calls in the output.
    tool_call = extract_tool_call(accumulated)
    if tool_call:
        tool_name = tool_call.get("name", "")
        parameters = tool_call.get("parameters", {})

        log.info("Session %s — tool call detected: %s", request.session_id, tool_name)

        # Policy check.
        policy_result = await evaluate_tool_call_policy(tool_name, parameters)
        log.info(
            "Session %s — policy decision for %s: %s",
            request.session_id, tool_name, policy_result.decision
        )

        call_result = ToolCallResult(
            tool_name=tool_name,
            parameters=parameters,
            policy=policy_result,
        )

        if policy_result.decision == "Allow":
            try:
                result = dispatch_tool(tool_name, parameters)
                call_result.result = result
                log.info("Session %s — tool %s executed successfully", request.session_id, tool_name)
            except Exception as exc:
                call_result.error = str(exc)
                log.error("Session %s — tool %s error: %s", request.session_id, tool_name, exc)
        elif policy_result.decision == "Deny":
            call_result.error = f"DENIED by policy: {policy_result.detail}"
            log.warning("Session %s — tool %s denied: %s", request.session_id, tool_name, policy_result.detail)
        else:  # RequireConfirmation
            call_result.error = f"REQUIRES CONFIRMATION: {policy_result.detail}"
            log.info("Session %s — tool %s requires confirmation", request.session_id, tool_name)

        tool_results.append(call_result)

    return InferenceResponse(
        session_id=request.session_id,
        text=accumulated,
        tool_calls=tool_results,
        finish_reason="tool_call" if tool_call else "stop",
    )


# ---------------------------------------------------------------------------
# SSE streaming pipeline
# ---------------------------------------------------------------------------

async def stream_inference(request: InferenceRequest) -> AsyncIterator[dict[str, str]]:
    """Yield SSE events for a streaming inference request."""
    yield {"event": "session", "data": json.dumps({"session_id": request.session_id})}

    accumulated = ""
    async for token in query_llama(
        request.prompt, request.tools, request.max_tokens, request.temperature, stream=True
    ):
        accumulated += token
        yield {"event": "token", "data": json.dumps({"token": token})}

    # After streaming completes, check for tool calls.
    tool_call = extract_tool_call(accumulated)
    if tool_call:
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

        if policy_result.decision == "Allow":
            try:
                result = dispatch_tool(tool_name, parameters)
                yield {
                    "event": "tool_result",
                    "data": json.dumps({"tool": tool_name, "result": result}),
                }
            except Exception as exc:
                yield {
                    "event": "tool_error",
                    "data": json.dumps({"tool": tool_name, "error": str(exc)}),
                }
        else:
            yield {
                "event": "tool_blocked",
                "data": json.dumps(
                    {"tool": tool_name, "reason": policy_result.detail or policy_result.decision}
                ),
            }

    yield {"event": "done", "data": json.dumps({"finish_reason": "stop"})}


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness probe."""
    return {"status": "ok", "service": "lumen-inference-bridge", "version": "0.1.0"}


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
