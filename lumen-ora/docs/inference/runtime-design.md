# Inference Runtime Design

This document covers the technical design of the inference layer: how llama.cpp is integrated, how the model routing system works, and the JSON-RPC interface between the Context Shell / Tool Call Router and the inference runtime.

For the tool call schema (what the model can call), see `tool-schema.md`.
For the higher-level orchestration design, see `../architecture/ai-orchestration.md`.

---

## Component Overview

The inference layer consists of:

1. **llama-server** — llama.cpp's built-in HTTP server, used for inference. We run it as a managed subprocess (in the prototype) or as a Genode component (in the target architecture). It exposes an OpenAI-compatible API plus llama.cpp-specific extensions.

2. **Inference Bridge** — a Rust daemon that wraps llama-server, manages model loading/unloading, implements the model routing logic, and exposes a JSON-RPC interface to the Tool Call Router.

3. **Tool Call Router** — parses the model's structured output for tool calls and routes them through the Policy Layer. (Described in `../architecture/ai-orchestration.md`; the interface to llama-server is described here.)

---

## llama.cpp Integration

### Why llama.cpp

llama.cpp is the primary inference backend because:
- Supports GGUF quantization formats (Q4_K_M, Q5_K_M, Q8_0, IQ2_XXS, etc.)
- Has production-quality backends for every relevant hardware target: CUDA (NVIDIA), Metal (Apple), Vulkan (cross-platform GPU), SYCL (Intel), and BLAS (CPU-only)
- Actively maintained with frequent hardware-specific optimizations
- Small dependency footprint (C++17, few external dependencies)
- Supports flash attention, continuous batching, speculative decoding, and other performance-critical features
- Grammar-constrained generation for reliable structured output

### Build Configuration

The inference bridge builds llama.cpp from source as a submodule. Build flags are set based on detected hardware:

```cmake
# CMakeLists.txt excerpt for the inference bridge
if (LUMEN_BACKEND STREQUAL "auto")
  # Detection order: CUDA > Vulkan > Metal > BLAS
  find_package(CUDAToolkit)
  if (CUDAToolkit_FOUND)
    set(LUMEN_BACKEND "cuda")
  elseif (APPLE)
    set(LUMEN_BACKEND "metal")
  else()
    # Check for Vulkan (covers AMD, Intel, Qualcomm via Turnip)
    find_package(Vulkan)
    if (Vulkan_FOUND)
      set(LUMEN_BACKEND "vulkan")
    else()
      set(LUMEN_BACKEND "blas")
    endif()
  endif()
endif()

# NPU backend: llama.cpp's QNN backend for Snapdragon
# Enabled separately because it requires the Qualcomm AI SDK
if (LUMEN_ENABLE_QNN_NPU)
  add_definitions(-DGGML_USE_QNN)
endif()
```

### llama-server Configuration

The Inference Bridge launches llama-server with the following flags:

```bash
llama-server \
  --model "${MODEL_PATH}" \
  --ctx-size "${CONTEXT_SIZE}" \
  --n-gpu-layers 999 \          # offload all layers to GPU if possible
  --flash-attn \                 # enable flash attention
  --cache-type-k q8_0 \         # KV cache quantization (reduces memory 2x vs f16)
  --cache-type-v q8_0 \
  --parallel 1 \                 # single concurrent session (OS use case)
  --host 127.0.0.1 \
  --port 8080 \
  --no-webui \
  --log-disable                  # Inference Bridge handles logging
```

For the dual-model configuration (fast + reasoning):
- Fast model runs on port 8080, reasoning model on port 8081
- Each model gets a separate KV cache
- GPU layers are divided based on available VRAM: small model gets 100% offload, large model gets as many layers as fit in remaining VRAM

### Grammar-Constrained Generation

Tool calls are generated using llama.cpp's JSON schema grammar mode. The inference bridge provides the JSON schema for the tool call format to llama-server at request time:

```json
{
  "prompt": "...",
  "grammar": null,
  "json_schema": {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "properties": {
      "reasoning": { "type": "string" },
      "tool_call": { "$ref": "#/definitions/ToolCall" },
      "response": { "type": "string" }
    },
    "oneOf": [
      { "required": ["tool_call"] },
      { "required": ["response"] }
    ],
    "definitions": {
      "ToolCall": { ... }
    }
  }
}
```

When `json_schema` is set, llama-server uses its GBNF grammar engine to constrain token sampling to only produce valid JSON matching the schema. This makes schema validation of model output trivial: if llama-server returns a result, it is guaranteed to match the schema.

---

## Inference Bridge JSON-RPC API

The Inference Bridge exposes a JSON-RPC 2.0 API over a Unix domain socket at `/run/lumen-ora/inference.sock`. The Tool Call Router and Context Shell connect to this socket.

### API Endpoints

#### `inference.chat`

Submit a chat turn and receive a streamed response.

Request:
```json
{
  "jsonrpc": "2.0",
  "id": "turn-42",
  "method": "inference.chat",
  "params": {
    "session_id": "sess-a1b2c3",
    "message": {
      "role": "user",
      "content": "Read my resume and tell me what skills are listed."
    },
    "options": {
      "model": "auto",           // "fast", "reasoning", or "auto"
      "temperature": 0.7,
      "max_tokens": 2048,
      "stream": true
    }
  }
}
```

Response (streamed, one JSON object per line):
```json
{"type": "token", "content": "I'll", "model": "fast"}
{"type": "token", "content": " read", "model": "fast"}
...
{"type": "tool_call", "tool": "fs_read", "arguments": {"path": "/home/user/Documents/resume-2025.pdf"}}
{"type": "tool_result_requested", "tool": "fs_read", "request_id": "tc-001"}
// Tool Call Router handles this — submits to Policy Layer, returns result:
{"type": "tool_result", "request_id": "tc-001", "result": {...}}
...
{"type": "done", "usage": {"prompt_tokens": 512, "completion_tokens": 234}}
```

#### `inference.load_model`

Load a model (or switch the active model).

Request:
```json
{
  "jsonrpc": "2.0",
  "id": "load-1",
  "method": "inference.load_model",
  "params": {
    "slot": "fast",              // "fast" or "reasoning"
    "model_path": "/models/qwen2.5-7b-q4_k_m.gguf",
    "context_size": 8192,
    "verify_hash": true
  }
}
```

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "load-1",
  "result": {
    "status": "loaded",
    "model": "Qwen2.5-7B-Instruct",
    "quantization": "Q4_K_M",
    "context_size": 8192,
    "backend": "vulkan",
    "layers_on_gpu": 28,
    "layers_on_cpu": 0,
    "estimated_tok_per_sec": 42
  }
}
```

#### `inference.status`

Get current status of the inference runtime.

Response:
```json
{
  "jsonrpc": "2.0",
  "id": "status-1",
  "result": {
    "models": {
      "fast": {
        "name": "Qwen2.5-7B-Instruct",
        "quantization": "Q4_K_M",
        "backend": "vulkan",
        "status": "idle",
        "context_used": 1024,
        "context_max": 8192
      },
      "reasoning": {
        "name": "Qwen2.5-14B-Instruct",
        "quantization": "Q4_K_M",
        "backend": "vulkan",
        "status": "idle",
        "context_used": 0,
        "context_max": 16384
      }
    },
    "hardware": {
      "backend": "vulkan",
      "device": "Adreno 740",
      "vram_used_mb": 9800,
      "vram_total_mb": 14000
    }
  }
}
```

#### `inference.session_context`

Inject or retrieve session context (for the Session Memory Manager).

```json
{
  "jsonrpc": "2.0",
  "id": "ctx-1",
  "method": "inference.session_context",
  "params": {
    "session_id": "sess-a1b2c3",
    "action": "inject_summary",
    "summary": "Earlier this session: user archived Docker images (11.8 GB recovered). User is working on a cover letter for Acme Corp SRE role. Resume at /home/user/Documents/resume-2025.pdf."
  }
}
```

---

## Model Management

### Model Storage

Models are stored in `/models/` by default (configurable). Each model directory contains:
```
/models/
  qwen2.5-14b-q4_k_m/
    model.gguf           # The weights
    model.sha256         # Hash for integrity verification
    model.json           # Metadata: name, quantization, license, parameters
  qwen2.5-7b-q4_k_m/
    model.gguf
    model.sha256
    model.json
```

### Model Integrity Verification

Before loading any model, the Inference Bridge verifies the SHA-256 hash:

```rust
fn verify_model(path: &Path, expected_hash: &str) -> Result<(), ModelError> {
    let mut hasher = Sha256::new();
    let mut file = File::open(path)?;
    let mut buffer = [0u8; 65536];
    loop {
        let n = file.read(&mut buffer)?;
        if n == 0 { break; }
        hasher.update(&buffer[..n]);
    }
    let hash = format!("{:x}", hasher.finalize());
    if hash != expected_hash {
        return Err(ModelError::HashMismatch { expected: expected_hash.to_string(), actual: hash });
    }
    Ok(())
}
```

A model that fails hash verification is not loaded. The event is logged to the audit log with severity `WARN`.

### Model Configuration File

The active model configuration is at `/etc/lumen-ora/models.toml`:

```toml
[fast]
path = "/models/qwen2.5-7b-q4_k_m/model.gguf"
context_size = 8192
kv_cache_type = "q8_0"
gpu_layers = 999  # auto-fill

[reasoning]
path = "/models/qwen2.5-14b-q4_k_m/model.gguf"
context_size = 16384
kv_cache_type = "q8_0"
gpu_layers = 999  # auto-fill

[routing]
auto_route = true
reasoning_threshold_tokens = 50  # requests longer than this get reasoning model
reasoning_keywords = ["plan", "design", "debug", "explain", "compare", "why", "how does"]
```

---

## Performance Monitoring

The Inference Bridge tracks and exposes performance metrics:

- Tokens per second (decode, prefill separately)
- Time to first token
- KV cache utilization
- GPU memory utilization
- Model load time

Metrics are exposed via a Prometheus-compatible endpoint at `http://127.0.0.1:9090/metrics` (disabled by default, enabled by configuration).

Benchmark acceptance criteria for the prototype are defined in `prototype/README.md`.
