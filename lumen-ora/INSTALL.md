# Installing Lumen Ora

Lumen Ora is a local AI assistant. Everything — model, policy gate, tools —
runs on your own machine. The installer downloads the open-source Qwen2.5
weights from Hugging Face; no API keys, no cloud sign-up.

## TL;DR

```
git clone https://github.com/<your-org>/lumen-ora.git
cd lumen-ora
install.bat              # Windows
```

Then start it:

```
prototype\start.bat
```

## Requirements

| What | Why | Where to get it |
|---|---|---|
| Windows 10/11 (64-bit) | Host OS for the bridge + llama.cpp | — |
| WSL2 with Ubuntu-22.04 | Runs the Rust policy engine | `wsl --install -d Ubuntu-22.04` |
| Python 3.11 or 3.12 | Bridge + context shell | https://www.python.org/downloads/ |
| Git | Cloning the repo | https://git-scm.com/download/win |
| ~7 GB free disk | Model weights + dependencies | — |
| 16 GB RAM | 7B model on CPU; 8 GB works with 3B only | — |

The installer checks all of the above and tells you exactly what's missing
before it starts changing anything on your system.

## Step-by-step (Windows)

### 1. Clone

```
git clone https://github.com/<your-org>/lumen-ora.git
cd lumen-ora
```

### 2. Run the installer

Pick one of these — they do the same thing:

```
install.bat            # double-click friendly
.\install.ps1          # if you prefer PowerShell
```

Both wrap `prototype\setup.ps1`, which:

1. Checks prerequisites (Python, WSL, Git)
2. `pip install`s the bridge + shell dependencies
3. Builds the Rust policy engine inside WSL2 (`cargo build`)
4. Prompts whether to download the Qwen2.5 7B GGUF (~4.4 GB) and/or 3B GGUF (~2 GB)
5. Prints a final status report

The installer is idempotent — re-run it any time. It only redoes the steps
that aren't already done.

### 3. Start the stack

```
prototype\start.bat
```

This opens three windows: llama-server, the inference bridge, and the
context shell. The first start takes ~10 s while llama-server warms up
the model.

Open `http://localhost:8765` in a browser for the web dashboard, or chat
directly in the context shell window.

### 4. Verify (optional)

```
cd prototype
python test_e2e.py
```

You should see **47 passed, 0 failed**.

## Step-by-step (Linux / macOS)

> Coming in Phase 4 — Public Beta. The Rust policy engine and Python bridge
> are already cross-platform; only the launcher scripts and a few
> Windows-specific tools (clipboard, screenshot) need platform branches.
> Tracking issue: `#TBD`.

## Manual install (skip the wrapper)

If you'd rather drive `setup.ps1` directly:

```
cd prototype
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

Or do it by hand:

```
# 1. Python deps
pip install -r prototype\inference-bridge\requirements.txt
pip install -r prototype\context-shell\requirements.txt

# 2. Build policy engine in WSL2
wsl -d Ubuntu-22.04 -- bash -c "cd /mnt/c/.../prototype/policy-engine && cargo build"

# 3. Download a model into prototype\inference-bridge\llama-cpp\
#    qwen2.5-7b-instruct-q4_k_m.gguf  (smart)
#    qwen2.5-3b-instruct-q4_k_m.gguf  (fast)

# 4. Verify llama-server.exe exists in prototype\inference-bridge\llama-cpp\
```

## Troubleshooting

**`cargo: command not found` during WSL build.**
Install Rust inside WSL: `wsl -d Ubuntu-22.04 -- bash -c "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y"`.

**`llama-server.exe` not found.**
Download a recent llama.cpp release for Windows and extract it into
`prototype\inference-bridge\llama-cpp\`. The installer doesn't fetch
llama.cpp automatically (binary releases change too often).

**Tests fail at Layer 1 with "policy-engine binary not found".**
`wsl -d Ubuntu-22.04 -- bash -c "cd /mnt/c/.../prototype/policy-engine && source ~/.cargo/env && cargo build"`.

**The 7B model is too slow on my machine.**
Use the 3B model: launch with `python shell.py --model fast`, or toggle
in the web dashboard. ~3× faster, slightly worse reasoning.

**`UnicodeEncodeError` when running tests on a fresh terminal.**
Already fixed in the test harness — pull latest and rerun.

## Uninstall

```
# Remove the cloned repo and the runtime data:
rmdir /s /q C:\path\to\lumen-ora
rmdir /s /q %USERPROFILE%\.lumen          # history, memory, screenshots
```

Python packages installed by `pip` stay on your system; remove them with
`pip uninstall` if you want a clean slate.

## What gets installed where

| Location | Contents |
|---|---|
| `prototype\inference-bridge\llama-cpp\` | llama-server.exe + GGUF model weights |
| `prototype\policy-engine\target\debug\` | Compiled Rust policy engine |
| `%USERPROFILE%\.lumen\history.jsonl` | Conversation history (last 6 turns auto-restored) |
| `%USERPROFILE%\.lumen\memory.jsonl` | Long-term memory facts (`/remember`) |
| `%USERPROFILE%\.lumen\screenshots\` | Screenshots taken by the `take_screenshot` tool |
| `%USERPROFILE%\.lumen\tools\*.py` | User plugins (see `prototype\inference-bridge\example_plugin.py`) |

Nothing is written to the registry. Nothing phones home. The model never
leaves your machine.
