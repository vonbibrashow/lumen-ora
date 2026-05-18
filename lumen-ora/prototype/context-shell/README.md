# Context Shell — Prototype Component

The Context Shell is the user-facing component of the Lumen Ora prototype. It is a PTY-intercepting terminal wrapper that sits between the user and the AI, managing the session lifecycle, rendering model output, detecting high-stakes operations, and providing the confirmation UI.

In the final Lumen Ora architecture, this component is replaced by a voice/text input subsystem integrated into the minimal compositor. In the 90-day prototype, it is a terminal application that provides the full interactive experience.

---

## Status

Weeks 5–7 of the build plan (see `../README.md`). Currently: not started.

---

## What This Component Does

1. Opens a PTY (pseudoterminal) pair
2. Presents a session prompt to the user on the slave PTY
3. Receives user input, sends it to the Inference Bridge via JSON-RPC
4. Receives streaming token output from the Inference Bridge, renders it to the terminal
5. Detects when the Inference Bridge returns a `high_stakes_pending` decision:
   - Pauses streaming output
   - Renders the confirmation UI
   - Waits for user to type "confirm" / "deny" / ask a clarifying question
   - Forwards the user's decision to the Policy Engine
6. Displays session status line: model name, token count, active capability count
7. Handles session lifecycle: start, save, resume, end

---

## Source Layout

```
context-shell/
  src/
    main.rs               -- PTY setup, main input/output loop
    session.rs            -- session state, JSON-RPC connection to Inference Bridge
    renderer.rs           -- streaming token rendering, ANSI formatting
    high_stakes.rs        -- high-stakes detection and confirmation UI
    status_line.rs        -- bottom status bar rendering
    history.rs            -- session history and resume logic
  tests/
    renderer.rs           -- rendering output correctness tests
    session.rs            -- session lifecycle tests (mocked Inference Bridge)
    high_stakes.rs        -- confirmation UI flow tests
  Cargo.toml
```

---

## PTY Architecture

The Context Shell uses the `portable-pty` crate to create a PTY pair. The master PTY is held by the Context Shell; the slave PTY is the "terminal" that the user sees (displayed in their actual terminal via the master).

```
User's terminal (xterm, Windows Terminal, etc.)
        │
        ▼
Context Shell (master PTY)
        │ JSON-RPC
        ▼
Inference Bridge
        │ JSON-RPC
        ▼
Policy Engine + llama-server
```

The PTY setup allows the Context Shell to intercept all input before it reaches the model and all output before it reaches the user's terminal. This is what enables the high-stakes confirmation UI: the Context Shell can pause the stream, render the confirmation prompt, wait for a response, and then resume the stream — all transparently within the user's terminal session.

---

## Prompt Format

The user-facing prompt is:
```
[Lumen Ora — <model_name> / <ram_gb>GB / <backend>]
>
```

Example:
```
[Lumen Ora — Qwen2.5-14B / 16GB / Vulkan]
>
```

During inference:
```
[Lumen Ora — Qwen2.5-14B / 16GB / Vulkan] [generating...]
```

During a tool call:
```
[Lumen Ora — Qwen2.5-14B / 16GB / Vulkan] [executing: fs_read...]
```

---

## High-Stakes Confirmation UI

When the Inference Bridge returns a `high_stakes_pending` decision, the Context Shell clears the current line and renders:

```
╔═ ACTION REQUIRES CONFIRMATION ═══════════════════════════════════════╗
║                                                                        ║
║  The AI wants to:                                                      ║
║    DELETE /home/user/Videos/old_footage/ (47.2 GB, recursive)        ║
║                                                                        ║
║  Type "confirm" to proceed, "deny" to cancel,                         ║
║  or ask a question about this action.                                  ║
║                                                                        ║
╚════════════════════════════════════════════════════════════════════════╝
confirm/deny/question>
```

The box is rendered in yellow on a dark background (via ANSI color codes). If the terminal doesn't support color, it is rendered as plain ASCII art.

---

## Session Resume

Sessions are stored in `~/.lumen-ora/sessions/` (managed by the Session Memory Manager in the Inference Bridge). The Context Shell can list and resume past sessions:

```
> /sessions list
Recent sessions:
  2026-05-18 14:32  sess-a1b2c3  "cover letter for Acme Corp SRE role" (42 min)
  2026-05-17 09:14  sess-d4e5f6  "Docker cleanup and storage audit" (18 min)

> /sessions resume sess-a1b2c3
Resuming session from 2026-05-18...
[session summary injected into context]
>
```

---

## Building

```bash
cd prototype/context-shell
cargo build --release
```

Dependencies: `portable-pty`, `crossterm` (terminal control), `tokio` (async), `serde_json` (JSON-RPC).

---

## Testing

```bash
cargo test -p context-shell
```

The integration tests use a mock Inference Bridge that produces scripted responses. This allows testing the full UI flow (including high-stakes confirmation) without a running model.

---

## Contributing

The Context Shell is the most visible part of the prototype — it's what contributors and users interact with. Contributions to the rendering, UX, and session management are welcome without the extra review requirements that apply to the Policy Engine.

However: any change to how high-stakes confirmation works (the confirmation UI flow, what counts as high-stakes, the timing of when confirmation is requested) requires a Model RFC, because it affects the safety properties of the system.

See `../../CONTRIBUTING.md` for general guidelines.
