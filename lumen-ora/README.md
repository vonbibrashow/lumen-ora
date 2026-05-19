# Lumen Ora

> A locally-run AI operating system interface — voice, gestures, tools, and a safety policy engine, all on your own hardware.

## What it is

Lumen Ora is a working prototype of an AI-native OS interface that runs a quantized language model (Qwen2.5) entirely on your machine via llama.cpp. Every action the AI takes — reading files, running commands, searching the web — passes through a Rust-based policy engine that enforces safety rules and keeps an audit log. The shell persists memory across sessions, accepts text, voice, and camera-gesture input, and exposes a web dashboard at `http://localhost:8765`.

No API key. No cloud. No data leaving your machine.

## Demo

```
lumen ▶  summarize the README in my project folder

  Thinking…

  ┌ Tool: read_file ──────────────────────────────────────┐
  │ /home/alice/projects/myapp/README.md                  │
  │ (1 of 312 lines shown — truncated)                    │
  └───────────────────────────────────────────────────────┘

  Your README covers installation, configuration, and a
  quick-start guide for a Python web app. The project uses
  FastAPI and PostgreSQL. There are three open TODOs in the
  Contributing section.

lumen ▶  /remember I prefer concise bullet-point summaries

  Remembered: I prefer concise bullet-point summaries

lumen ▶  search for llama.cpp quantization benchmarks

  Thinking…

  ┌ Tool: search_web ─────────────────────────────────────┐
  │ query: "llama.cpp quantization benchmarks"            │
  │ 5 results returned                                    │
  └───────────────────────────────────────────────────────┘

  • ggml.ai/blog — Q4_K_M vs Q5_K_M: 7B model fits in 4 GB
    at Q4_K_M, with ~3% quality loss vs F16
  • Reddit/LocalLLaMA — user benchmarks: Qwen2.5-7B at
    Q4_K_M achieves 18-22 tok/s on Snapdragon X Elite
  • llama.cpp GitHub wiki — recommended quants by VRAM tier
  • ...

lumen ▶  /model fast

  Switched to fast model (3B)
```

Policy engine running throughout — every tool call is checked before execution. The `read_file` call above was granted in < 2 ms. A request for `/etc/shadow` would be denied with a logged reason.

## Quick start

**Prerequisites:** Windows 10/11 with WSL2, Python 3.11+, ~8 GB free disk.

```powershell
# 1. Clone
git clone https://github.com/vonbibrashow/lumen-ora.git
cd lumen-ora

# 2. Run the installer (downloads llama.cpp, model, and Python deps)
.\prototype\setup.ps1

# 3. Launch everything (bridge + policy engine + shell)
.\prototype\start.ps1

# 4. Or run the shell directly (after the bridge is already up)
cd prototype\context-shell
python shell.py

# 5. Open the web dashboard
Start http://localhost:8765
```

The installer handles llama.cpp, Qwen2.5-7B model download (~4 GB), and all Python dependencies. First run takes 5–10 minutes depending on your connection.

## Architecture

```
User (text / voice / camera gestures)
         │
         ▼
  Context Shell (Python, :interactive)
         │  httpx POST /infer
         ▼
  Inference Bridge (FastAPI :8765)
    │                    │
    │ llama.cpp API      │ TCP :8766
    ▼                    ▼
 llama-server       Policy Engine
 (llama.cpp :8080)  (Rust / WSL2)
                         │
                         ▼
                   Tool Execution
                   (10 tools)
                         │
                         ▼
                   Audit Log (JSONL)
```

The policy engine sits between the inference bridge and tool execution. Every tool call — before it touches your file system, clipboard, or a subprocess — is evaluated against the rule set. Denied calls are logged and the model is told why.

## Features

- **Local inference** — Qwen2.5-7B (or 3B for fast mode) via llama.cpp; no API key, no cloud
- **Policy engine** — Rust daemon enforces 10 safety rules on every tool call; append-only audit log
- **10 tools** — file read/write/edit, directory listing, command runner, web search, clipboard, app launcher, screenshot
- **Voice I/O** — push-to-talk STT via faster-whisper; TTS via pyttsx3
- **Camera gestures** — thumbs-up confirm, open-palm cancel, peace voice-toggle, wave new-session
- **Lip-VAD** — auto-records when your lips move (`LUMEN_LIP_VAD=1`)
- **Long-term memory** — `/remember`, `/memory`, `/forget` persist facts across sessions in `~/.lumen/memory.jsonl`
- **Web dashboard** — FastAPI UI at `http://localhost:8765`
- **Fast/smart model switching** — `/model fast` (3B, ~18 tok/s) or `/model smart` (7B, ~12 tok/s)
- **Session restore** — conversation history persisted in `~/.lumen/history.jsonl`
- **Plugin system** — add tools by extending `tool_schema.py`

## Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read a file and return its text content |
| `write_file` | Write text to a file; creates parent directories |
| `edit_file` | Replace the first occurrence of a string in a file |
| `list_directory` | List directory contents with name, type, and size |
| `run_command` | Run a subprocess; streams output with timeout and line cap |
| `search_web` | DuckDuckGo search; returns title, URL, snippet for each result |
| `clipboard_read` | Read the current system clipboard contents |
| `clipboard_write` | Write text to the system clipboard |
| `open_app` | Launch an application by name without waiting |
| `take_screenshot` | Screenshot to `~/.lumen/screenshots/YYYY-MM-DD_HH-MM-SS.png` |

## Input modes

| Mode | How to activate | How it works |
|------|-----------------|--------------|
| Text | Default | Type and press Enter; backslash continues to next line |
| Voice (push-to-talk) | `--voice` or `/voice on` | Hold Space to record; release to transcribe via Whisper |
| Camera gestures | `--camera` or `/camera on` | Webcam detects hand gestures (see below) |
| Lip-VAD | `LUMEN_LIP_VAD=1` env var | Records automatically when face mesh detects open lips |

**Gesture map:**

| Gesture | Action |
|---------|--------|
| Thumbs up | Confirm pending action |
| Open palm | Cancel / clear context |
| Peace sign | Toggle voice mode |
| Wave | Start new session |

## Shell commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/exit` / `/quit` | Exit the shell |
| `/clear` | Clear the screen |
| `/new` | Clear conversation context, start fresh |
| `/history` | Show last 10 exchanges |
| `/session` | Show session ID and history stats |
| `/model fast\|smart` | Switch model tier (3B fast / 7B smart) |
| `/model` | Show current model tier and bridge status |
| `/remember <fact>` | Save a fact to long-term memory |
| `/memory` | List all remembered facts with indices |
| `/forget <n>` | Remove fact at index n from memory |
| `/voice on\|off\|check` | Enable, disable, or health-check voice mode |
| `/camera on\|off` | Enable or disable camera gesture input |

## Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| OS | Windows 10 with WSL2 | Windows 11 with WSL2 |
| Python | 3.11 | 3.11 or 3.12 |
| RAM | 8 GB | 16 GB |
| Disk | ~8 GB (model + deps) | ~12 GB |
| CPU | Any x86-64 | AVX2 / modern Ryzen or Intel |
| GPU | Not required | CUDA or Vulkan for faster inference |

The 3B fast model runs comfortably at 8 GB RAM. The 7B smart model needs 8–10 GB for the model alone; 16 GB total is recommended.

## Project layout

```
lumen-ora/
├── prototype/
│   ├── context-shell/
│   │   └── shell.py           # Main AI shell (1700+ lines): REPL, voice, camera, memory
│   ├── inference-bridge/
│   │   ├── bridge.py          # FastAPI server: routes prompts to llama.cpp, executes tools
│   │   └── tool_schema.py     # 10 tool definitions + implementations
│   ├── policy-engine/         # Rust TCP daemon: enforces safety rules on every tool call
│   ├── start.bat              # One-click launcher (Command Prompt)
│   ├── start.ps1              # One-click launcher (PowerShell)
│   ├── setup.ps1              # Installer: llama.cpp, model, Python deps
│   └── test_e2e.py            # 47-test end-to-end suite
├── docs/
│   ├── architecture/          # seL4/Genode design docs, policy model spec
│   ├── inference/             # Runtime design, tool schema spec
│   └── dev-setup/             # Development environment guides
├── CHANGELOG.md
└── README.md                  # This file
```

## Roadmap

| Phase | Status | Scope |
|-------|--------|-------|
| Foundation (Milestone 0) | Done | Policy engine + inference bridge + context shell; 47-test suite passing |
| Alpha (Milestone 1) | Done | Voice I/O, camera gestures, long-term memory, fast/smart model switching, 10 tools |
| Beta (Milestone 2) | In progress | Setup.ps1 installer, NPU acceleration, reproducible builds, hardware test matrix |
| OS-level (Phase 2+) | Future | seL4/Genode kernel integration, formally verified policy layer, native Lumen Ora apps |

The long-term vision is an OS where the AI layer is not bolted on top — it is the shell, with direct access to hardware, memory, and the file system through a formally verified policy layer. The prototype proves the concept on Windows/WSL2 today; the seL4/Genode architecture is the production target.

See `docs/architecture/` for the full design and `prototype/README.md` for the 90-day spec.

## License

MIT — see [LICENSE](LICENSE).

Model weights are not included in this repository. Qwen2.5 weights are released under the [Qwen License](https://huggingface.co/Qwen/Qwen2.5-7B-Instruct/blob/main/LICENSE). The setup script downloads them from Hugging Face on first run.
