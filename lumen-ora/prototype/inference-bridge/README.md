# Inference Bridge — Prototype Component

The Inference Bridge is the glue between the Context Shell and the local llama.cpp inference runtime, and between the AI layer and the Policy Engine. It is a Rust daemon that manages model loading, implements the model routing logic, handles tool call parsing and routing, and manages the session memory lifecycle.

---

## Status

Weeks 3–7 of the build plan (see `../README.md`). Currently: not started.

---

## What This Component Does

1. Manages llama-server as a subprocess (starts it, monitors it, restarts it if it crashes)
2. Exposes a JSON-RPC API on `/run/lumen-ora/inference.sock` to the Context Shell
3. On each chat turn:
   a. Routes the request to the appropriate model (fast or reasoning)
   b. Forwards the request to llama-server
   c. Streams tokens back to the Context Shell
   d. Detects tool call JSON in the token stream
   e. Validates tool calls against the JSON Schema
   f. Forwards valid tool calls to the Policy Engine
   g. Injects results back into the model context
   h. Continues streaming until the model produces a `response` (non-tool-call output)
4. Manages session context: tracks token count, triggers summarization when context is near-full
5. Persists session summaries to `~/.lumen-ora/sessions/`

---

## Source Layout

```
inference-bridge/
  src/
    main.rs               -- startup, socket listener, process management
    ipc.rs                -- JSON-RPC server (Context Shell interface)
    llama_client.rs       -- HTTP client for llama-server API
    model_router.rs       -- fast vs. reasoning model routing logic
    tool_parser.rs        -- streaming parser for tool call JSON
    tool_validator.rs     -- JSON Schema validation for tool calls
    policy_client.rs      -- JSON-RPC client for Policy Engine
    session_memory.rs     -- context window management, summarization
    session_store.rs      -- persistent session storage (SQLite)
  llama.cpp/              -- git submodule: llama.cpp source
  schemas/
    tool_call.schema.json -- JSON Schema for tool call validation
    tool_result.schema.json
  tests/
    model_routing.rs
    tool_parsing.rs
    policy_integration.rs  -- requires running policy-engine
    session_memory.rs
  Cargo.toml
  config.toml.example
```

---

## JSON-RPC API

The Inference Bridge JSON-RPC API is documented in full in `../../docs/inference/runtime-design.md`. Summary of endpoints:

| Method | Description |
|--------|-------------|
| `inference.chat` | Submit a chat turn, receive streaming response |
| `inference.load_model` | Load or switch a model |
| `inference.status` | Get current status (models loaded, hardware, context usage) |
| `inference.session_context` | Inject or retrieve session memory |
| `inference.end_session` | Save session summary and clean up |

---

## Tool Call Parsing

The model's output is streamed token-by-token from llama-server. The `tool_parser` watches the token stream for the start of a tool call JSON object (`{"schema_version"` followed by `"tool_call":`).

When detected:
1. Token streaming to the Context Shell is paused
2. The full JSON object is accumulated until the closing `}`
3. The JSON is parsed and validated against `schemas/tool_call.schema.json`
4. If valid: forwarded to the Policy Engine via `policy_client`
5. If invalid: an error is injected into the model context

The schema validation uses the `jsonschema` Rust crate. Because llama-server's grammar-constrained generation guarantees the output is valid JSON, most validation failures will be semantic (e.g., a path that doesn't start with `/`) rather than syntactic.

---

## Model Routing Logic

```rust
fn route_request(request: &ChatRequest, config: &RouterConfig) -> ModelSlot {
    // 1. Explicit override wins
    if let Some(model) = &request.options.model {
        if model != "auto" {
            return ModelSlot::from_str(model);
        }
    }

    // 2. Long requests → reasoning model
    let token_estimate = estimate_tokens(&request.message.content);
    if token_estimate > config.reasoning_threshold_tokens {
        return ModelSlot::Reasoning;
    }

    // 3. Keyword signals → reasoning model
    let content_lower = request.message.content.to_lowercase();
    if config.reasoning_keywords.iter().any(|kw| content_lower.contains(kw)) {
        return ModelSlot::Reasoning;
    }

    // 4. Default: fast model
    ModelSlot::Fast
}
```

The router can also escalate mid-response: if the fast model's response requires more than 3 tool calls, the Tool Call Parser signals the router, which re-routes the full request to the reasoning model. The user sees a brief `[routing to deeper reasoning...]` message.

---

## Session Memory

Session memory management is a key responsibility of the Inference Bridge. The lifecycle:

1. **Session start:** Load persistent session summaries if the user requests resume. Inject summary into model context.
2. **During session:** Track `context_used` tokens. When `context_used / context_max > 0.8`:
   - Take the oldest 30% of the context
   - Send a summarization request to the fast model
   - Store the summary in SQLite (`~/.lumen-ora/sessions/<session_id>/summary.db`)
   - Replace the summarized context with the compressed summary
3. **Session end:** Write the final session summary and metadata. Compute and store a semantic embedding for retrieval.

The session SQLite database schema:
```sql
CREATE TABLE summaries (
    id INTEGER PRIMARY KEY,
    session_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,  -- Unix timestamp
    turn_range_start INTEGER,
    turn_range_end INTEGER,
    summary_text TEXT NOT NULL,
    token_count INTEGER
);

CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- metadata: session_id, model_name, started_at, ended_at, task_tags
```

---

## Configuration

`config.toml.example` (copy to `config.toml` and edit):
```toml
[llama_server]
host = "127.0.0.1"
port = 8080
port_reasoning = 8081

[models.fast]
path = ""  # required: absolute path to fast model GGUF
context_size = 8192
kv_cache_type = "q8_0"

[models.reasoning]
path = ""  # required: absolute path to reasoning model GGUF
context_size = 16384
kv_cache_type = "q8_0"
# Comment out [models.reasoning] if you only have one model

[routing]
auto_route = true
reasoning_threshold_tokens = 50
reasoning_keywords = ["plan", "design", "debug", "explain", "compare", "why", "how does", "write"]

[session]
store_path = "~/.lumen-ora/sessions"
summarize_at_context_pct = 0.80
summary_target_tokens = 200

[policy]
socket = "/run/lumen-ora/policy.sock"

[api]
socket = "/run/lumen-ora/inference.sock"
```

---

## Building

```bash
cd prototype/inference-bridge

# Build llama.cpp submodule first
cmake -S llama.cpp -B llama.cpp/build -DLLAMA_BUILD_SERVER=ON
cmake --build llama.cpp/build --config Release -j$(nproc)

# Build the Inference Bridge
cargo build --release
```

---

## Running

The Inference Bridge is typically started by the `run.sh` launcher script in `prototype/`. It can also be run standalone for testing:

```bash
# Start the Policy Engine first (required)
./target/release/policy-engine &

# Then start the Inference Bridge
./target/release/inference-bridge --config config.toml
```

---

## Testing

```bash
# Unit tests (no running daemons required)
cargo test -p inference-bridge --lib

# Integration tests (require running policy-engine and llama-server)
# Start them first:
./target/release/policy-engine &
./llama.cpp/build/bin/llama-server --model /path/to/model.gguf --port 8080 &
# Wait for model to load, then:
cargo test -p inference-bridge --test policy_integration
```

---

## Contributing

The Inference Bridge sits at the intersection of safety (it routes tool calls through the Policy Engine) and user experience (it controls latency and the streaming UX). Contributions to model routing and session memory are welcome through normal PR process. Changes to the tool call parsing or Policy Engine interface require two maintainer reviews (because they affect safety-critical code paths).

See `../../CONTRIBUTING.md` for full guidelines.
