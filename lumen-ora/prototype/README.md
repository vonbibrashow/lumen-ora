# Lumen Ora — 90-Day Prototype Specification (Milestone 0)

This document is the team's single source of truth for Milestone 0. It describes exactly what we are building, what we are not building, the week-by-week build plan, the hardware test matrix, the acceptance criteria, and how to contribute.

If something about the prototype scope is unclear or wrong, open an issue or PR to fix this document before writing code. Clarity here prevents wasted effort.

**Last updated:** 2026-05-19
**Target completion:** 2026-08-17 (13 weeks from start)

---

## Executive Summary

The 90-day prototype proves that the Lumen Ora architecture is viable on real hardware. By the end of week 13, a contributor with no prior Lumen Ora experience should be able to:

1. Clone the repository, run the setup script, and have the prototype running in under two hours
2. Type a natural language request and have it answered by a local language model
3. Watch the model successfully execute at least one tool call (file read, file write, or process spawn)
4. Watch the Policy Engine correctly deny an unauthorized action
5. Inspect the audit log and find a complete record of every action taken

This is proof of concept. It is not a product. It is not secure enough to use for sensitive work. It is not the seL4/Genode architecture. It is the minimum thing that demonstrates the core thesis: **local AI inference, routed through a policy enforcement layer, can work as the primary OS interface on real consumer hardware.**

---

## Scope: What We Are Building

### In Scope for Milestone 0

**Platform:** NixOS 24.11 running on bare metal (not in a VM). x86-64 primary, ARM64 (Snapdragon X Elite) secondary.

**The three components:**
1. **Policy Engine Daemon** — a Rust userspace daemon that enforces the 10 starter rules and writes an append-only audit log
2. **Context Shell** — a PTY-intercepting terminal wrapper that is the user-facing interface
3. **Inference Bridge** — the glue between Context Shell, Policy Engine, and a local llama.cpp instance

**Demonstrable behaviors:**
- Accept text input from the user
- Route the request to a local LLM (Qwen2.5-7B or Qwen2.5-14B in Q4_K_M, depending on hardware)
- Execute at least these tool call types: `fs_read`, `fs_write`, `fs_list`, `proc_spawn`
- Correctly deny `fs_read` on a path outside the granted scope (demonstrates Rule 1/Rule 2)
- Correctly deny `proc_spawn` when no spawn capability is granted (demonstrates Rule 4)
- Require user confirmation before any file deletion (demonstrates Rule 7)
- Produce a complete, parseable audit log for a full session

**Non-functional requirements:**
- Minimum 12 tok/s generation with Qwen2.5-7B Q4_K_M on minimum hardware target (x86-64, AVX2, 16 GB RAM)
- Minimum 18 tok/s generation on the Snapdragon X Elite ARM64 target
- Policy Engine evaluation latency < 5 ms (p99) for simple rule checks
- Policy Engine must not be a throughput bottleneck at interactive token generation rates

### Explicitly Not In Scope for Milestone 0

These are deferred to later milestones. Do not implement them in the prototype.

| Feature | Why deferred |
|---------|-------------|
| seL4/Genode kernel | The architecture is validated, but bring-up is a multi-month parallel effort |
| Voice input | Adds complexity and hardware dependencies; text-first validates the AI interface |
| Persistent session memory | Session memory across restarts is Phase 2 |
| Multi-model routing (fast + reasoning) | Load one model per prototype instance; routing adds complexity |
| Network tool calls (`net_request`) | Adds network capability scope complexity; file and process tools are sufficient to prove the concept |
| Semantic session search | Requires embedding model; deferred |
| NPU-specific optimization | QNN backend is in active development in llama.cpp; use Vulkan/CUDA for now |
| User-configurable capability profiles | Hardcoded default profile for the prototype; configurability is Phase 2 |
| GUI/compositor | Text-only for the prototype |
| Model fine-tuning or RLHF | We use base Qwen2.5-Instruct weights |
| Reproducible build system for full stack | NixOS flake for the prototype is sufficient |
| Security audit | Planned for Phase 2 |

---

## The Three Components

### Component 1: Policy Engine Daemon

**Language:** Rust (stable, 1.78 or later)
**IPC mechanism:** Unix domain socket at `/run/lumen-ora/policy.sock`, speaking newline-delimited JSON-RPC 2.0
**Rule format:** Each rule is a Rust struct implementing the `PolicyRule` trait (see `policy-engine/README.md`)
**Formal specification:** Each rule has a TLA+ specification. The specifications are in `policy-engine/spec/`. In Milestone 0, they are written but not machine-checked.
**Audit log:** Append-only JSONL file at `/var/log/lumen-ora/audit.log` (see `docs/inference/tool-schema.md` for schema)
**Configuration:** `/etc/lumen-ora/policy.toml`

#### The 10 Starter Rules

| Rule ID | Name | Hardcoded? | Default |
|---------|------|-----------|---------|
| RULE_01 | FS scope enforcement | No (user can expand scope) | ON |
| RULE_02 | Path traversal prevention | YES | ON |
| RULE_03 | Network egress requires grant | No | ON (deny by default) |
| RULE_04 | Process spawn requires grant | No | ON (deny by default) |
| RULE_05 | No capability self-escalation | YES | ON |
| RULE_06 | Audit log is append-only | YES | ON |
| RULE_07 | High-stakes confirmation | No (types can be configured) | ON |
| RULE_08 | Symlink scope validation | YES | ON |
| RULE_09 | Spawn inherits no AI capabilities | YES | ON |
| RULE_10 | Session boundary enforcement | No | ON |

Full rule definitions and TLA+ specs: `../docs/architecture/seL4-policy-model.md`

#### Policy Engine IPC Protocol

The Policy Engine receives requests from the Inference Bridge and sends responses. The message framing is newline-delimited JSON (NDJSON). One request per line, one response per line, matched by `call_id`.

Request:
```json
{"schema_version":"0.1","session_id":"sess-a1b2c3","turn_id":"turn-01","call_id":"tc-001","tool":"fs_read","arguments":{"path":"/home/user/Documents/resume.pdf","encoding":"text"}}
```

Response:
```json
{"call_id":"tc-001","status":"granted","result":{"path":"/home/user/Documents/resume.pdf","content":"...","size_bytes":4096,"truncated":false},"policy_rule_applied":null,"latency_ms":2}
```

The full schema is in `../docs/inference/tool-schema.md`.

#### Audit Log Format

Each line of the audit log is a JSON object matching the schema in `../docs/inference/tool-schema.md`. Example:
```json
{"schema_version":"0.1","timestamp_monotonic":1716134400000,"timestamp_wall":"2026-05-19T12:00:00.000Z","session_id":"sess-a1b2c3","turn_id":"turn-01","call_id":"tc-001","tool":"fs_read","decision":"granted","policy_rule_applied":null,"latency_policy_ms":2,"latency_total_ms":15,"redacted_args":{"path":"/home/user/Documents/resume.pdf","encoding":"text"},"redacted_result":{"size_bytes":4096,"truncated":false}}
```

In Milestone 0: no HMAC integrity protection. This is noted as a known gap.

#### Done Definition (Policy Engine)

- All 10 rules implemented and passing their unit tests
- IPC socket accepting connections from the Inference Bridge
- Audit log written correctly for every tool call (granted, denied, high-stakes)
- Performance: p99 evaluation latency < 5 ms on the x86-64 reference hardware for a simple fs_read check
- `cargo test -p policy-engine` passes with no failures

---

### Component 2: Context Shell

**Language:** Rust (stable)
**Mechanism:** PTY pair via `portable-pty` crate. Master PTY held by the Context Shell. Slave PTY presented to the user's terminal.
**Model communication:** JSON-RPC 2.0 to the Inference Bridge via Unix socket at `/run/lumen-ora/inference.sock`

#### What the Context Shell Manages

1. **Input collection:** Reads from the user's terminal via the master PTY. Sends each completed input (Enter key) to the Inference Bridge as a JSON-RPC `inference.chat` call.

2. **Output streaming:** Receives streaming tokens from the Inference Bridge. Renders tokens immediately as they arrive. For tool calls in progress, shows `[executing: <tool_name>...]` until the result is ready.

3. **High-stakes confirmation UI:** When the Inference Bridge returns `high_stakes_pending`:
   - Pause output streaming
   - Render the confirmation box (see `context-shell/README.md` for the exact format)
   - Read user input: `confirm`, `deny`, or a follow-up question
   - Forward the decision to the Policy Engine (via the Inference Bridge)
   - Resume streaming

4. **Session management:** On startup, shows session info. On exit (Ctrl+D or `/exit`), triggers session save.

#### Prompt Format

```
[Lumen Ora — <model_name> / <ram_gb>GB / <backend>]
>
```

When computing/waiting:
```
[Lumen Ora — <model_name> / <ram_gb>GB / <backend>] [generating...]
```

#### High-Stakes Command Detection

The Inference Bridge (via the Policy Engine) handles high-stakes classification. The Context Shell renders the confirmation UI when it receives `high_stakes_pending` status. It does not do its own high-stakes detection.

However, the Context Shell does implement one additional check: if the user's raw input contains specific strings before it is sent to the model (`rm -rf`, `DROP TABLE`, `mkfs`, `dd if=/dev`), the Context Shell displays a warning:
```
! Your input looks like a dangerous shell command. If you meant to run this
  directly (not through the AI), use a regular terminal. Type "confirmed"
  to send this to the AI anyway, or press Enter to cancel.
```

This is not a security control — it is a UX safeguard against accidentally pasting shell commands into the AI interface.

#### Latency Handling

Target: the user should see the first token within 2 seconds of pressing Enter (time to first token, or TTFT).

Breakdown of TTFT:
- Input encoding: ~50 ms (prompt tokenization for short inputs)
- Policy Layer session setup: ~10 ms
- LLM prefill of prompt: ~500–1000 ms (depends on prompt length and hardware)
- First generated token: variable

At 2 seconds TTFT, the user experience is acceptable for interactive use. If TTFT exceeds 3 seconds consistently on the target hardware, it is a performance regression and should be investigated.

During the wait for the first token, the Context Shell shows the `[generating...]` indicator. There is no spinner or progress bar in Milestone 0 (deferred to UX polish in later milestones).

#### Done Definition (Context Shell)

- PTY setup working correctly: user input is collected, output is rendered, no character loss
- High-stakes confirmation UI triggers correctly when the Policy Engine returns `high_stakes_pending`
- Session start/end works correctly: the Inference Bridge is connected, the session ID is assigned and displayed
- Streaming output renders correctly without buffering delays
- `cargo test -p context-shell` passes with no failures

---

### Component 3: Inference Bridge

**Language:** Rust (stable)
**Upstream:** llama.cpp (git submodule, pinned to a specific commit for reproducibility)
**Interfaces:**
- Exposes JSON-RPC 2.0 on `/run/lumen-ora/inference.sock` (to Context Shell)
- Connects to llama-server HTTP API on `http://127.0.0.1:8080` (to llama.cpp)
- Connects to Policy Engine on `/run/lumen-ora/policy.sock` (to Policy Engine)

#### Tool Call Parsing

The model produces output in one of two forms:
1. A plain text response (no tool call)
2. A JSON object with a `tool_call` field

Grammar-constrained generation via llama-server ensures the output is always valid JSON. The Inference Bridge parses each response and:
- If it contains `tool_call`: validates against the JSON Schema, forwards to Policy Engine
- If it contains `response`: streams to the Context Shell as text

For Milestone 0, the model's output format uses a simplified JSON wrapper:
```json
{
  "thinking": "...",
  "tool_call": { "tool": "fs_read", "arguments": { "path": "..." } }
}
```
or:
```json
{
  "response": "Here is the content of your resume: ..."
}
```

The `thinking` field (like a chain-of-thought scratchpad) is parsed but not shown to the user. It is included in the audit log.

#### Tool Call Loop

A single user turn may require multiple sequential tool calls (e.g., list a directory, then read a file, then write a modified version). The Inference Bridge handles this loop:

```
1. Receive user message from Context Shell
2. Send to llama-server (inference.chat)
3. Receive model response
4. If response contains tool_call:
   a. Validate
   b. Forward to Policy Engine
   c. Receive result (or denial)
   d. Inject result into model context
   e. Continue inference (send next request to llama-server with updated context)
   f. GOTO 3
5. If response contains response:
   a. Stream to Context Shell
   b. Done
6. If 10 tool calls reached without a response: inject "max tool calls reached" message, done
```

The max-10-tool-calls limit prevents runaway loops. In practice, most tasks use 1–4 tool calls.

#### Session Context (Milestone 0 Scope)

For Milestone 0, session memory is **within-session only**. The context window is not summarized or compressed. When the context window approaches full (>80% used), the Inference Bridge injects a system message: `[Context is getting long. Please wrap up the current task or start a new session.]`

Cross-session memory (persistent summaries, semantic search, session resume) is deferred to Phase 2.

#### Done Definition (Inference Bridge)

- llama-server starts successfully, model loads, llama-server accepts API calls
- Tool calls are correctly extracted from model output, validated, and forwarded to the Policy Engine
- Tool call results are correctly injected into model context
- The full tool call loop works: list directory → read file → write modified file → confirm with user
- The denial path works: model asks for a capability it doesn't have → Policy Engine denies → model explains to user
- `cargo test -p inference-bridge` passes with no failures

---

## Week-by-Week Build Plan

### Overview

```
Weeks 1–4:   Policy Engine (the safety-critical core; build first)
Weeks 3–5:   Inference Bridge scaffolding (overlaps with Policy Engine)
Weeks 5–7:   Context Shell (build after Inference Bridge interface is stable)
Week 8:      First integration: all three components working together
Weeks 9–10:  Tool calls and the full loop (list → read → write → confirm)
Week 11:     Hardware testing and performance validation
Week 12:     Bug fixes, documentation, and hardening
Week 13:     Acceptance testing against all hardware targets, final polish
```

---

### Week 1: Policy Engine Foundation

**Goal:** Policy Engine builds, starts, and handles a mock tool call via the Unix socket.

**Deliverables:**
- Cargo workspace created at `prototype/`
- `policy-engine` crate: `main.rs`, `ipc.rs`, `audit.rs`
- Unix socket listener accepting JSON-RPC connections
- Audit log writing working (correct JSONL format)
- `PolicyRule` trait defined in `rules/mod.rs`
- `RULE_01` (FS scope) implemented as the first rule

**Done when:**
- A tool can connect to `/run/lumen-ora/policy.sock` and send a mock `fs_read` request
- The response is `granted` when the path is in scope, `denied` when it's not
- The audit log contains a correct entry for both cases
- `cargo test -p policy-engine --lib` passes

**Who can contribute:** Anyone comfortable with Rust and async I/O (tokio). Familiarity with Unix sockets helpful but not required.

---

### Week 2: Policy Engine Rules 2–10

**Goal:** All 10 rules implemented with tests.

**Deliverables:**
- Rules 2–10 implemented (one file per rule)
- Unit tests for each rule: at least one grant test and one denial test per rule
- High-stakes (`RULE_07`) returns `high_stakes_pending` correctly
- Capability store: in-memory structure for session-scoped capabilities
- Capability grant/revoke IPC messages working

**Done when:**
- `cargo test -p policy-engine` passes all tests
- The following demo scenario works:
  1. Connect to policy socket, start session
  2. Send `fs_read` for `/home/user/Documents/test.txt` → `granted` (scope is pre-granted)
  3. Send `fs_read` for `/etc/passwd` → `denied` (out of scope)
  4. Send `fs_delete` for any path → `high_stakes_pending`
  5. Send `proc_spawn` for `/usr/bin/git` → `denied` (no spawn capability)
  6. Audit log contains correct entry for all 5 requests

**TLA+ requirement:** First drafts of all 10 TLA+ specs committed to `policy-engine/spec/`. They do not need to be machine-checked, but they must be written.

---

### Week 3: Inference Bridge — llama.cpp Integration

**Goal:** llama-server starts, model loads, and the Inference Bridge can get a completion from it.

**Deliverables:**
- `inference-bridge` crate scaffolded
- llama-server started as a managed subprocess by the Inference Bridge
- `llama_client.rs`: HTTP client for the llama-server `/completion` and `/chat/completions` endpoints
- Configuration loading from `config.toml`
- Model hash verification on startup

**Done when:**
- Running `./target/release/inference-bridge` starts llama-server and loads the model
- A raw HTTP request to the Inference Bridge's internal llama-server returns a completion
- Model hash verification correctly rejects a model file with a modified byte

**Note:** The Inference Bridge's JSON-RPC socket (for the Context Shell) is NOT implemented yet in week 3. This week is purely about the llama.cpp connection.

---

### Week 4: Inference Bridge — Tool Call Parsing + Policy Engine Connection

**Goal:** The Inference Bridge can parse tool calls from model output and route them through the Policy Engine.

**Deliverables:**
- `tool_parser.rs`: streaming parser that detects JSON tool call objects in model output
- `tool_validator.rs`: JSON Schema validation against `schemas/tool_call.schema.json`
- `policy_client.rs`: JSON-RPC client connecting to the Policy Engine socket
- End-to-end path: model output → tool call detected → validated → sent to Policy Engine → result injected into context

**Done when:**
- With the Policy Engine running, the Inference Bridge can:
  1. Send a prompt to the model that causes it to produce a `fs_read` tool call
  2. Detect the tool call in the model output
  3. Validate it against the schema
  4. Forward it to the Policy Engine
  5. Receive the result (granted + file content, or denied + reason)
  6. Inject the result into model context
  7. Continue inference and receive a natural language response

**Note:** At this point, the actual file read is not yet implemented — the Policy Engine sends back a mock result. Real file I/O is implemented in Week 9.

---

### Week 5: Inference Bridge — JSON-RPC API for Context Shell

**Goal:** The Inference Bridge exposes its full JSON-RPC API and can handle chat turns end-to-end.

**Deliverables:**
- JSON-RPC 2.0 server on `/run/lumen-ora/inference.sock`
- `inference.chat` method: handles a user message, runs the full tool call loop, returns streaming response
- `inference.status` method: returns model status
- Streaming response: tokens are sent as they arrive (not buffered to full completion)

**Done when:**
- A CLI test tool (no Context Shell yet) can connect to the Inference Bridge socket and have a conversation
- The conversation includes at least one tool call that is correctly detected and forwarded
- Streaming works: tokens arrive one-by-one, not in a single batch

---

### Week 6: Context Shell — Foundation

**Goal:** Context Shell starts, connects to the Inference Bridge, and handles basic input/output.

**Deliverables:**
- `context-shell` crate scaffolded
- PTY setup: master/slave pair, raw mode for input
- Input collection: reads user input, sends to Inference Bridge on Enter
- Output rendering: receives streaming tokens, displays immediately
- Session prompt displayed correctly

**Done when:**
- The user can type a request, press Enter, and see the model's response stream in
- There is no garbling, character loss, or display corruption
- The prompt format matches the spec

---

### Week 7: Context Shell — High-Stakes Confirmation and Session Management

**Goal:** The full user-visible safety feature (high-stakes confirmation) is working.

**Deliverables:**
- `high_stakes.rs`: confirmation UI rendered correctly
- High-stakes flow: when Inference Bridge returns `high_stakes_pending`, show the confirmation box, wait for user response, forward to Inference Bridge
- Session start/end working: session ID displayed, `/exit` terminates cleanly
- Raw command warning: warning shown when user pastes dangerous-looking shell commands

**Done when:**
- Demo scenario: user asks the AI to delete a file → AI issues `fs_delete` → confirmation box appears → user types "deny" → AI receives the denial → AI explains to user that it was blocked

---

### Week 8: First Full Integration

**Goal:** All three components running together. The full end-to-end flow works for a simple demonstration scenario.

**The demonstration scenario that must pass:**
1. Start the prototype with `./run.sh`
2. User types: `List the files in /tmp`
3. AI issues `fs_list` tool call for `/tmp` → Policy Engine grants (if `/tmp` is in default scope) → result returned → AI summarizes the listing
4. User types: `Create a file called hello.txt in /tmp with the content "Hello from Lumen Ora"`
5. AI issues `fs_write` tool call → Policy Engine grants → file created → AI confirms
6. User types: `Read back hello.txt`
7. AI issues `fs_read` → Policy Engine grants → content returned → AI displays it
8. User types: `Read /etc/passwd`
9. AI issues `fs_read` for `/etc/passwd` → Policy Engine denies (RULE_01) → AI explains it doesn't have access
10. Check audit log: all 5 tool calls recorded correctly

**Done when:** A fresh contributor can run this scenario on their machine and reproduce the result.

---

### Week 9: Real Tool Execution — File I/O and Process Spawn

**Goal:** Tool calls execute real OS operations, not mock responses.

**Deliverables:**
- `fs_read`: reads real files via the OS (after Policy Engine grants)
- `fs_write`: writes real files (after Policy Engine grants)
- `fs_list`: lists real directories
- `fs_delete`: deletes files (requires user confirmation via high-stakes flow)
- `proc_spawn`: spawns a real subprocess, captures stdout/stderr
  - Test case: `git --version` → AI reports the git version
  - Test case: `proc_spawn /bin/ls /tmp` → AI reports directory contents via the process output

**Security notes for Week 9:**
- Path validation must be thorough: test path traversal, symlinks, Unicode normalization
- `proc_spawn` must strip the AI's environment from the child process
- All actual I/O must go through the Policy Engine gate — no shortcuts

---

### Week 10: Multi-Turn Tool Use and Error Recovery

**Goal:** The AI can execute multi-step tasks involving sequential tool calls, and handles errors gracefully.

**The multi-step scenario that must pass:**
1. User: "I need to move all the .log files from /tmp to /tmp/archive and then tell me how many there were"
2. AI: issues `fs_list /tmp` → gets listing → issues `fs_write` to create `/tmp/archive/` (or `proc_spawn mkdir`) → issues multiple `fs_read` + `fs_write` calls to copy files → issues `fs_delete` on originals (with confirmation) → summarizes count

This requires:
- The tool call loop correctly handles 5+ sequential calls
- The AI maintains correct context across the calls
- High-stakes confirmation works for `fs_delete` within a multi-step flow
- If one step fails (file not found, permission denied), the AI handles it gracefully rather than crashing

---

### Week 11: Hardware Testing and Performance Validation

**Goal:** Run the full acceptance test matrix on target hardware. Document results.

See the Hardware Test Matrix section below for the full criteria.

**Deliverables:**
- Benchmark script: `prototype/bench.sh --hardware <target>`
  - Measures: time to first token, tokens per second, Policy Engine p99 latency, total session time for the standard scenario
- Results recorded in `prototype/hardware-results/` (one Markdown file per hardware target)
- Any hardware-specific performance issues documented as GitHub issues

**Note:** If acceptance criteria are not met on a hardware target during Week 11, Week 12 budget should be used to investigate. Week 13 is not for fixing performance issues — it is for final validation and polish.

---

### Week 12: Bug Fixes, Documentation, and Hardening

**Goal:** The prototype is stable enough for a wider audience to use.

**Deliverables:**
- All bugs from Week 11 hardware testing addressed (or documented as known issues)
- `docs/dev-setup/inference.md` updated to reflect the actual setup steps (not aspirational)
- `run.sh` works reliably across NixOS 24.11 and Ubuntu 24.04
- Audit log integrity gap documented in a GitHub issue (HMAC protection deferred to Phase 2)
- Known limitations clearly documented in this file under "Known Limitations"

---

### Week 13: Acceptance Testing and Release

**Goal:** Run the full acceptance test matrix one final time and cut the Milestone 0 release.

**Deliverables:**
- All acceptance criteria verified (see Hardware Test Matrix)
- Git tag `milestone-0` created
- GitHub Release published with:
  - `lumen-ora-prototype-m0.tar.gz` (source + build instructions)
  - `CHANGELOG.md` entry for Milestone 0
  - Hardware test results attached

---

## Hardware Test Matrix

The prototype must be validated on at least the following hardware targets. "Validated" means: a contributor ran the full acceptance test suite (`prototype/tests/acceptance.sh`) and it passed.

### Target 1: x86-64 Reference (Minimum Spec)

**Machine configuration:**
- CPU: Any x86-64 with AVX2 support (Intel Haswell/2013 or later, AMD Ryzen 1000 or later)
- RAM: 16 GB DDR4 (dual-channel preferred)
- GPU: None required (CPU inference only)
- OS: NixOS 24.11 or Ubuntu 24.04 LTS

**Model:** Qwen2.5-7B-Instruct-Q4_K_M

**Acceptance criteria:**

| Criterion | Required | Description |
|-----------|----------|-------------|
| Generation throughput | >= 12 tok/s | Measured with `bench.sh --tok-test` |
| Time to first token | <= 3.0 s | For a 50-token system prompt + 10-token user message |
| Policy Engine latency (p99) | <= 5 ms | Measured over 100 consecutive `fs_read` grants |
| Audit log correctness | 100% | Every tool call in the standard scenario appears in the log with correct decision |
| Denial correctness | 100% | `/etc/passwd` read must be denied; no scope-escaping path works |
| High-stakes confirmation | Works | `fs_delete` requires confirmation, is blockable with "deny" |
| Tool call loop | Works | The multi-step `.log file archive` scenario from Week 10 completes correctly |
| Crash stability | 0 crashes | 30 minutes of interactive use with no crashes |

---

### Target 2: ARM64 Snapdragon X Elite (Target Performance Spec)

**Machine configuration:**
- SoC: Qualcomm Snapdragon X Elite (any X1E variant)
- RAM: 16 GB LPDDR5x
- GPU: Adreno (used via Vulkan/Turnip)
- OS: NixOS 24.11 on Snapdragon (or Ubuntu on ARM64 if NixOS bring-up is not complete)

**Model:** Qwen2.5-14B-Instruct-Q4_K_M (or Q4_K_M of largest model that fits within 13 GB allocation)

**Acceptance criteria:**

| Criterion | Required | Description |
|-----------|----------|-------------|
| Generation throughput | >= 18 tok/s | Measured with `bench.sh --tok-test` (Vulkan backend) |
| Time to first token | <= 2.5 s | |
| Policy Engine latency (p99) | <= 5 ms | |
| Audit log correctness | 100% | |
| Denial correctness | 100% | |
| High-stakes confirmation | Works | |
| Tool call loop | Works | |
| Crash stability | 0 crashes | 30 minutes interactive |

**Note on NixOS for Snapdragon:** NixOS support for Snapdragon X Elite is in active development in the NixOS community. If a stable NixOS boot is not achievable by Week 11, Ubuntu 24.04 on ARM64 is an acceptable fallback for Milestone 0. Document the substitution in `hardware-results/snapdragon-xelite.md`.

---

### Target 3: x86-64 with Discrete NVIDIA GPU (Bonus Target)

**Machine configuration:**
- CPU: Any modern x86-64
- RAM: 32 GB (or 16 GB if the GPU has 12+ GB VRAM)
- GPU: NVIDIA RTX 4070 (12 GB VRAM) or equivalent
- OS: NixOS 24.11 or Ubuntu 24.04

**Model:** Qwen2.5-14B-Instruct-Q4_K_M (full GPU offload)

**Acceptance criteria:**

| Criterion | Required | Description |
|-----------|----------|-------------|
| Generation throughput | >= 45 tok/s | |
| All other criteria | Same as Target 1 | |

This target is "bonus" — it's not required for Milestone 0 sign-off, but it demonstrates the upper end of the hardware range.

---

### Acceptance Test Script

The acceptance test script is at `prototype/tests/acceptance.sh`. It automates the standard scenario and measures the criteria above. To run it:

```bash
# After the prototype is running (all daemons started):
./prototype/tests/acceptance.sh --hardware snapdragon-xelite --output acceptance-results.json

# Expected output:
# [PASS] generation_throughput: 22.4 tok/s (required: >= 18)
# [PASS] time_to_first_token: 1.8s (required: <= 2.5s)
# [PASS] policy_latency_p99: 2.1ms (required: <= 5ms)
# [PASS] audit_log_correctness: 100% (5/5 calls logged)
# [PASS] denial_correctness: /etc/passwd denied correctly
# [PASS] high_stakes_confirmation: fs_delete blocked with 'deny'
# [PASS] tool_call_loop: multi-step scenario completed in 8 steps
# [PASS] crash_stability: 30 min session, 0 crashes
#
# All 8 acceptance criteria PASSED.
# Results written to acceptance-results.json
```

---

## How to Contribute to the Prototype

### Step 1: Set Up Your Environment

Follow `../docs/dev-setup/inference.md`. The setup takes under two hours on most hardware.

### Step 2: Verify Your Environment

Run the test suite:
```bash
cd prototype
cargo test --workspace
```

If any tests fail, open an issue before writing new code.

### Step 3: Find Your First Task

Look at the week-by-week plan above. Find the current week and look for tasks that are not yet claimed (check GitHub issues for `in-progress` labels).

For first-time contributors: look for issues tagged `good-first-issue`. Most of them are in the Policy Engine (implementing a specific rule or its test) or in the Context Shell (implementing a specific UX detail).

### Step 4: Claim the Task

Comment on the GitHub issue: "I'd like to work on this — claiming it." This prevents duplicate work. If there's no GitHub issue for what you want to do, open one first.

### Step 5: Build and Test

```bash
# Make your changes
# Run the tests
cargo test --workspace

# Run the linter
cargo clippy --all -- -D warnings
cargo fmt --all --check

# If all pass, open a PR
```

### Step 6: Open a PR

Use the PR template. For Policy Engine changes, include the TLA+ specification for any new or modified rule. For Context Shell changes, include a description of what the UX change looks like (before/after). For Inference Bridge changes, describe what tool calls now work that didn't before.

### Step 7: Get Review

Policy Engine changes require two maintainer reviews (one from the Safety Subcommittee). Other changes require one maintainer review. See `../GOVERNANCE.md` for current maintainer and Safety Subcommittee membership.

---

## NixOS Setup

The prototype targets NixOS 24.11 as the primary development and deployment platform. The repository includes a `flake.nix` that provides a reproducible development environment:

```bash
# With Nix flakes enabled:
cd prototype
nix develop  # enters the dev shell with all dependencies

# Or use direnv (auto-activates when you enter the directory):
echo "use flake" > .envrc
direnv allow
```

The `flake.nix` provides:
- Rust 1.78 toolchain with the correct components
- llama.cpp build dependencies (cmake, libstdc++, cuda/vulkan SDK if available)
- Python 3.11 (for the evaluation harness)
- `policy-engine`, `inference-bridge`, and `context-shell` as Nix packages
- A NixOS module for the full prototype (deploy to a NixOS machine with a single `nixos-rebuild`)

If you are not using NixOS, the setup works equally well on Ubuntu 24.04 following `../docs/dev-setup/inference.md`.

---

## Known Limitations (Milestone 0)

These are documented gaps in the prototype that are NOT considered bugs — they are accepted for Milestone 0 and will be addressed in later milestones.

1. **No cross-session memory.** Session state is lost when the session ends.
2. **No audit log integrity protection.** The HMAC-SHA256 mechanism is designed but not implemented.
3. **Policy Engine is userspace, not kernel-enforced.** A privileged process could bypass it on Linux. This is expected and will be resolved by the Genode/seL4 architecture in Phase 2.
4. **Single model per session.** No fast/reasoning routing. The configured model handles all requests.
5. **No network tool calls.** `net_request` is in the schema but not implemented.
6. **No voice input.** Text-only for Milestone 0.
7. **NPU not used.** GPU (Vulkan/CUDA/Metal) or CPU only.
8. **No capability profile persistence.** User capability preferences reset on restart.
9. **No semantic session search.** You can't ask "resume my cover letter session from last week."
10. **NixOS on Snapdragon X Elite may require manual steps.** Boot support is in progress upstream.
