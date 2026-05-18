# AI Orchestration Layer Design

This document describes the design of the AI Orchestration Layer: the inference runtime integration, the tool call routing system, the model routing logic, and the session memory architecture.

For the Policy Layer (which sits below this layer), see `seL4-policy-model.md`.
For the tool call JSON Schema, see `docs/inference/tool-schema.md`.
For the llama.cpp integration specifics, see `docs/inference/runtime-design.md`.

---

## Overview

The AI Orchestration Layer is the software that turns "a language model running locally" into "the interface to the operating system." It has four responsibilities:

1. **Inference management:** Load, manage, and route between language models.
2. **Tool call orchestration:** Parse structured tool calls from model output, validate them, submit them to the Policy Layer, and route results back.
3. **Session memory:** Maintain continuity of context across multiple turns and across sessions.
4. **Output formatting:** Convert model output into user-visible form.

These four responsibilities are handled by three components: the Inference Runtime, the Tool Call Router, and the Session Memory Manager. They communicate through internal message queues.

---

## System Prompt Architecture

The system prompt is the fixed-at-session-start instruction set that shapes the model's behavior. It is not user-visible but is included in every inference call.

### Prompt Sections

The system prompt has four sections, loaded in order:

```
[SECTION 1: Identity and Role]
You are the interface layer of Lumen Ora, an AI-native operating system.
You are not a chatbot. You are an OS shell with the ability to act on the
user's computer through a structured tool call interface.

[SECTION 2: Capabilities — Injected at session start from Policy Layer]
Your current session has the following active capabilities:
{capability_list}

You may ONLY call tools that correspond to capabilities in this list.
If you need a capability not in this list, ask the user to grant it.
Do not attempt to invent workarounds or proxy requests through other tools.

[SECTION 3: Tool Definitions — JSON Schema]
You have access to the following tools:
{tool_schema_json}

All tool calls must be valid JSON conforming to the schema above.
Invalid tool calls will be rejected by the Policy Layer.

[SECTION 4: Behavioral Rules]
- Think before acting. For complex requests, reason step by step before
  issuing tool calls.
- Ask for clarification when the user's intent is ambiguous, rather than
  guessing. A wrong guess that deletes a file is worse than asking.
- High-stakes tool calls (file deletion, process termination, network
  requests that send user data) will be held for user confirmation. This
  is enforced by the Policy Layer and cannot be bypassed.
- When you complete a task, summarize what you did concisely. Do not
  congratulate yourself.
- Your session memory is limited. When context is long, prefer to
  summarize completed tasks rather than holding the full history in context.
```

### Capability Injection

The capability list in Section 2 is regenerated at session start and whenever capabilities change (grant or revoke). The Policy Layer provides the current capability list; the orchestration layer formats it for injection into the system prompt.

Example capability list:
```
Active capabilities this session:
- File read: /home/user/ (all subdirectories)
- File write/create: /home/user/Documents/, /tmp/lumen-scratch/
- File delete: /tmp/lumen-scratch/ only
- Process spawn: /usr/bin/git, /usr/bin/python3
- Network: DNS resolution only (no outbound connections)
- User interaction: notifications, confirmations
```

---

## Inference Runtime

The inference runtime is llama.cpp. Rationale: it is the most actively maintained, best-optimized, and most hardware-portable local inference library available. It supports CUDA, Metal, Vulkan, ROCm, BLAS, and NPU backends, making it viable across the hardware target matrix.

### Model Loading

Models are stored in GGUF format. On system boot (or session start), the inference runtime loads the configured model and performs:

1. **Model validation:** Check the GGUF file's SHA-256 against the stored hash. Reject if mismatched.
2. **Backend selection:** Detect available compute backends in priority order: NPU > dedicated GPU > integrated GPU > CPU with SIMD.
3. **Memory allocation:** Allocate KV cache. The KV cache size is configured based on available RAM minus the OS baseline overhead.
4. **Context window initialization:** Initialize the context window with the system prompt.

### Model Loading Sequence

```
boot
  │
  ├─ read /etc/lumen-ora/model.conf
  │     model: /models/qwen2.5-14b-q4_k_m.gguf
  │     context-window: 16384
  │     kv-cache-type: q8_0
  │     backend: auto
  │
  ├─ validate GGUF SHA-256
  │
  ├─ detect backends [npu, cuda, vulkan, blas]
  │
  ├─ initialize llama.cpp context
  │     n_ctx = 16384
  │     n_gpu_layers = auto (fill GPU memory)
  │     flash_attn = true (if supported)
  │
  ├─ load system prompt into context
  │
  └─ ready (accept tool calls from Context Shell)
```

### Batch Size and Latency

Token generation latency is determined primarily by memory bandwidth (for attention) and compute (for feed-forward layers). At the target hardware specifications:

| Hardware | Model | Quantization | Expected tok/s |
|----------|-------|-------------|---------------|
| Snapdragon X Elite | Qwen2.5-14B | Q4_K_M | 15–25 tok/s |
| Snapdragon X Elite | Qwen2.5-7B | Q4_K_M | 35–55 tok/s |
| AMD Ryzen AI 300 | Qwen2.5-14B | Q4_K_M | 12–20 tok/s |
| Intel Lunar Lake | Qwen2.5-14B | Q4_K_M | 10–18 tok/s |
| NVIDIA RTX 4070 (12GB) | Qwen2.5-14B | Q4_K_M | 45–70 tok/s |
| x86-64 CPU only (AVX2) | Qwen2.5-7B | Q4_K_M | 8–15 tok/s |

These are estimates based on llama.cpp benchmarks. Actual numbers depend on memory bandwidth configuration, thermal conditions, and concurrent system load.

---

## Tool Call Routing

### Structured Output Format

The model produces tool calls in a structured JSON format embedded in its output. The format follows the pattern established by llama.cpp's `--grammar` mode and `--json-schema` mode for structured generation:

```json
{
  "reasoning": "The user wants to read their resume file. I have fs:read:/home/user/ capability. I will use the fs_read tool.",
  "tool_call": {
    "tool": "fs_read",
    "arguments": {
      "path": "/home/user/Documents/resume-2025.pdf",
      "encoding": "binary",
      "return_format": "base64"
    }
  }
}
```

The `reasoning` field is required for any tool call that involves file write, process spawn, network egress, or device access. For read-only operations, it is optional but encouraged.

The model is constrained to produce valid JSON by llama.cpp's grammar-constrained generation. Invalid JSON cannot be produced when grammar mode is active.

### Tool Call Router Pipeline

```
model output (streaming tokens)
      │
      ├─ detect tool_call block (JSON start marker)
      │
      ├─ accumulate JSON until closing brace
      │
      ├─ parse JSON
      │     └─ if parse failure: log error, return error to model context
      │
      ├─ validate against tool JSON Schema
      │     └─ if validation failure: log error, return error to model context
      │
      ├─ forward to Policy Layer daemon (Unix socket / seL4 IPC)
      │     └─ request: {session_id, tool_call_json}
      │
      ├─ Policy Layer response: {decision, result_or_error}
      │     ├─ "granted": forward result to model context
      │     ├─ "denied": return denial reason to model context
      │     ├─ "high-stakes-pending": display to user, await confirmation
      │     │     ├─ "confirmed": re-submit to Policy Layer
      │     │     └─ "rejected": return rejection to model context
      │     └─ "error": return error to model context
      │
      └─ inject result into model context, continue inference
```

### Error Handling

When a tool call is denied or errors:
- The denial reason is injected into the model context in a standardized format
- The model is expected to acknowledge the denial, explain it to the user if relevant, and either try an alternative or ask the user to grant the needed capability
- The model should not repeatedly retry a denied tool call. After two denials for the same action, the model is prompted to stop trying and explain the situation to the user.

The second-denial prompt is injected by the Tool Call Router automatically:
```
[SYSTEM: Policy Layer has denied this tool call twice. Stop retrying.
Explain to the user what you were trying to do and what capability
would be needed to do it. Let the user decide whether to grant it.]
```

---

## Model Routing

Lumen Ora supports two models loaded simultaneously: a "fast" model for low-latency responses and a "reasoning" model for complex tasks.

### Routing Heuristics

The model router applies heuristics to decide which model handles each request:

**Fast model (7B, Q4_K_M) handles:**
- Simple file reads and writes where the task is clearly specified
- Short factual questions
- Single-step tool calls
- Formatting and reformatting of content where no reasoning is needed
- Follow-up turns in an established task context (user says "add a paragraph about X" when a document is already being edited)

**Reasoning model (14B or larger, Q4_K_M) handles:**
- Multi-step plans requiring more than two tool calls
- Ambiguous requests requiring interpretation
- Code generation or debugging
- Long document processing
- Any task involving the user's security posture or capability grants (since mistakes here are costly)

**Routing decision inputs:**
1. Token count of the request (longer requests → reasoning model more likely)
2. Tool call count in the request's likely execution (estimated by a lightweight classifier)
3. Keyword signals: "plan," "design," "compare," "debug," "why," "explain" → reasoning model
4. User history: if the user has repeatedly corrected the fast model on similar tasks, route those task types to the reasoning model

### Model Handoff

If the fast model produces a response that the Tool Call Router determines requires more than 3 tool calls, the router pauses the fast model's output, packages the conversation context, and re-routes the request to the reasoning model. The user sees: `[Routing to deeper reasoning — this will take a few seconds longer]`.

---

## Session Memory Architecture

### Problem

Language models have a fixed context window. At 16,384 tokens, a detailed work session fills the context window in roughly 30–60 minutes of active use. When the context fills, the oldest tokens must be evicted — and with them, the early context of the session.

For an OS-level assistant that the user may use all day, this is unacceptable. The user expects the system to remember that it archived those Docker images an hour ago, or that they are in the middle of a cover letter project.

### Layered Memory Architecture

Lumen Ora uses a three-tier memory architecture:

**Tier 1: Active Context Window**
The model's live context. All recent turns, current tool call results, and the system prompt. Managed by llama.cpp. Limited to the configured context window size (typically 8,192–32,768 tokens depending on model and hardware).

**Tier 2: Session Summary Store**
When the active context window approaches capacity (at 80% of configured size), the Session Memory Manager:
1. Identifies the oldest 30% of the context (earliest turns)
2. Issues a summarization request to the model: "Summarize the following conversation history concisely, preserving: completed tasks, their outcomes, any open decisions, and any information I said I'd remember."
3. Stores the summary in the session's SQLite database under a `session_id` key.
4. Evicts the summarized portion from the context window.
5. Injects the summary as a compressed context block at the top of the remaining context.

The summarization model is always the fast (7B) model, even if the session is otherwise using the reasoning model.

**Tier 3: Persistent Session Archive**
At session end, the full session summary (not the conversation log) is written to the persistent key-value store. At the start of a new session, the user can optionally inject relevant past session summaries into the new session's context.

The persistent archive is searchable by semantic similarity (a local embedding model — typically a small 300M-500M parameter model — provides embeddings). When the user says "continue the cover letter I was working on," the system retrieves the relevant past session summary and injects it.

### Memory Boundaries

The session archive is stored in the filesystem scope:
```
/home/user/.lumen-ora/sessions/
  <session-id>/
    summary.json      # compressed summary
    metadata.json     # timestamp, model used, task tags
    embedding.bin     # semantic embedding for retrieval
```

The AI layer does not have direct `fs:read` access to this directory. It accesses session summaries through the Session Memory Manager's controlled API, which filters and sanitizes before injection. This prevents the model from reading raw session history in a way that could be exploited by a prompt injection attack ("read my session history and extract the password I typed").

---

## Output Formatting

Model output is rendered to the framebuffer (or terminal, in the prototype) via the minimal compositor / Context Shell. The output pipeline:

1. **Streaming token output:** Tokens are rendered as they arrive. The user sees text appearing word-by-word.
2. **Code blocks:** Wrapped in a visible delimiter, with syntax highlighting (ANSI color codes in the terminal prototype, rendered blocks in the framebuffer compositor).
3. **Tool call indicators:** When the model is executing a tool call, the user sees: `[executing: <tool_name>...]` while waiting for the result.
4. **High-stakes confirmation prompt:** Displayed before high-stakes tool calls in a clearly distinguished format:
   ```
   ╔═ CONFIRMATION REQUIRED ══════════════════════════════════════════╗
   ║ The AI wants to:                                                  ║
   ║   DELETE /home/user/Videos/old_footage/ (47.2 GB)               ║
   ║                                                                   ║
   ║ Type "confirm" to proceed, "deny" to cancel, or ask a question.  ║
   ╚══════════════════════════════════════════════════════════════════╝
   ```
5. **Session indicators:** Session ID, model in use, token count, and active capability count are displayed in a status line.

---

## Performance Budget

At the target hardware specification (Snapdragon X Elite, 16 GB LPDDR5x):

| Component | Budget |
|-----------|--------|
| OS baseline (seL4 + Genode) | 200–300 MB RAM |
| Policy Layer daemon | ~50 MB RAM |
| Session Memory Manager + SQLite | ~100 MB RAM |
| Tool Call Router | ~30 MB RAM |
| Inference runtime (model loaded, KV cache) | ~10,000–12,000 MB RAM |
| **Total** | **10,380–12,480 MB** (out of 16,000 MB) |

This leaves approximately 3.5–5.6 GB of free RAM for the OS's demand-paging and any legacy applications running in the compatibility environment.

The KV cache consumes ~2 GB of the model's allocation for a 14B model at Q8_0 KV cache type and 16K context length. Reducing the KV cache type to Q4_0 halves this (to ~1 GB) at a small quality cost. Reducing context length to 8K further halves it.
