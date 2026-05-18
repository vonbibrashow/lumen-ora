# Inference Development Environment Setup

This guide covers setting up the development environment for the inference layer: the Inference Bridge, Context Shell, and Policy Engine prototype (the Rust daemon). This environment works on Linux, macOS, and Windows (via WSL2).

You do not need Genode, seL4, or any specialized toolchain for this. If you have a machine with 16 GB RAM and a reasonably modern CPU, you can get started in under an hour.

---

## System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| OS | Linux (any distro), macOS 13+, Windows 11 + WSL2 | NixOS or Ubuntu 24.04 |
| CPU | x86-64 with AVX2, or ARM64 | Snapdragon X Elite, AMD Ryzen AI 300, or Apple Silicon |
| RAM | 16 GB | 32 GB |
| Storage | 50 GB free | 100 GB free (space for multiple GGUF models) |
| GPU (optional) | NVIDIA with 8+ GB VRAM | RTX 4070 or better |

For GPU-accelerated inference on Linux, you'll need CUDA 12.x (NVIDIA), ROCm 6.x (AMD), or the Vulkan SDK (cross-platform).

---

## Step 1: Install Rust

The Inference Bridge and Policy Engine prototype are written in Rust. Install via rustup:

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
source "$HOME/.cargo/env"

# Verify
rustc --version  # should be 1.78 or later
cargo --version
```

For NixOS users, add `rustup` to your configuration or use a flake (see the `flake.nix` in the repo root).

---

## Step 2: Clone the Repository

```bash
git clone https://github.com/ericvonbibra/lumen-ora.git
cd lumen-ora
git submodule update --init prototype/
```

The `prototype/` directory is where all the 90-day prototype code lives. The rest of the repository (Genode components, seL4 integration) requires the full Genode toolchain and a Linux host.

---

## Step 3: Build llama.cpp

llama.cpp is fetched as a submodule and built as part of the inference bridge build process. However, you can also build and test it independently.

### Linux (CPU-only, minimum viable)

```bash
cd prototype/inference-bridge/llama.cpp
cmake -B build -DLLAMA_BUILD_SERVER=ON -DLLAMA_BUILD_TESTS=OFF
cmake --build build --config Release -j$(nproc)
```

### Linux (NVIDIA GPU)

```bash
cmake -B build \
  -DLLAMA_BUILD_SERVER=ON \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES="75;80;86;89"  # adjust for your GPU
cmake --build build --config Release -j$(nproc)
```

### Linux (AMD GPU — Vulkan)

```bash
cmake -B build \
  -DLLAMA_BUILD_SERVER=ON \
  -DGGML_VULKAN=ON
cmake --build build --config Release -j$(nproc)
```

### Linux (Qualcomm NPU via QNN — Snapdragon only)

The QNN backend requires the Qualcomm AI Engine Direct SDK, which requires registration at developer.qualcomm.com. Once downloaded:

```bash
export QNN_SDK_ROOT=/path/to/qairt/2.xx.x.xxxxxxxx
cmake -B build \
  -DLLAMA_BUILD_SERVER=ON \
  -DGGML_QNN=ON \
  -DQNN_SDK_ROOT=$QNN_SDK_ROOT
cmake --build build --config Release -j$(nproc)
```

### macOS (Apple Silicon — Metal)

```bash
cmake -B build \
  -DLLAMA_BUILD_SERVER=ON \
  -DGGML_METAL=ON
cmake --build build --config Release -j$(nproc)
```

### Verify

```bash
# Quick sanity check (no model required)
./build/bin/llama-server --help
```

---

## Step 4: Download a Model

Models are not included in the repository. Download a GGUF model from HuggingFace.

**For development and testing (fits in 8 GB RAM, fast to load):**
```bash
mkdir -p ~/lumen-ora-models
cd ~/lumen-ora-models

# Qwen2.5-7B-Instruct Q4_K_M (recommended for development)
# ~5 GB download
wget https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/qwen2.5-7b-instruct-q4_k_m.gguf

# Or use huggingface-cli (pip install huggingface_hub)
huggingface-cli download Qwen/Qwen2.5-7B-Instruct-GGUF \
  qwen2.5-7b-instruct-q4_k_m.gguf \
  --local-dir ~/lumen-ora-models
```

**For testing the 14B model (target hardware spec):**
```bash
# Qwen2.5-14B-Instruct Q4_K_M — ~9.5 GB download
huggingface-cli download Qwen/Qwen2.5-14B-Instruct-GGUF \
  qwen2.5-14b-instruct-q4_k_m.gguf \
  --local-dir ~/lumen-ora-models
```

### Configure the Model Path

Edit `prototype/inference-bridge/config.toml`:
```toml
[fast]
path = "/home/yourname/lumen-ora-models/qwen2.5-7b-instruct-q4_k_m.gguf"
context_size = 8192

[reasoning]
path = "/home/yourname/lumen-ora-models/qwen2.5-14b-instruct-q4_k_m.gguf"
context_size = 16384

# If you only have one model, set both to the same path
# or comment out the one you don't have
```

---

## Step 5: Build the Prototype

```bash
cd lumen-ora/prototype

# Build all three components
cargo build --release --workspace

# Binaries:
# target/release/policy-engine    — Policy Engine daemon
# target/release/inference-bridge — Inference Bridge daemon
# target/release/context-shell    — Context Shell
```

---

## Step 6: Run the Prototype

The prototype has a launcher script that starts all three daemons in the right order:

```bash
cd lumen-ora/prototype
./run.sh

# What this does:
# 1. Starts the Policy Engine daemon (opens Unix socket at /tmp/lumen-policy.sock)
# 2. Starts llama-server (loads the configured model)
# 3. Starts the Inference Bridge (connects to llama-server and Policy Engine)
# 4. Starts the Context Shell (opens an interactive session)
```

You should see:
```
[policy-engine] starting with 10 default rules loaded
[policy-engine] audit log: /tmp/lumen-audit.log
[policy-engine] listening on /tmp/lumen-policy.sock
[llama-server] loading model: qwen2.5-7b-instruct-q4_k_m.gguf
[llama-server] model loaded in 4.2s (42 tok/s estimated)
[inference-bridge] connected to llama-server
[inference-bridge] connected to policy-engine
[context-shell] ready
[Lumen Ora — Qwen2.5-7B / 16GB / CPU+Vulkan]
>
```

Type a request:
```
> List the files in /tmp
```

---

## Step 7: Run Tests

```bash
cd lumen-ora/prototype

# Run all tests
cargo test --workspace

# Run only policy engine tests
cargo test -p policy-engine

# Run only inference bridge tests  
cargo test -p inference-bridge

# Run integration tests (requires the model to be running)
cargo test --test integration -- --test-threads=1
```

### Integration Test Prerequisites

Integration tests require a running model. Start the services first, then run:
```bash
# In one terminal:
./run.sh --no-shell  # starts daemons without the interactive shell

# In another terminal:
cargo test --test integration
```

---

## Development Workflow

### Editing the Policy Engine

The Policy Engine is the component where most of the safety-critical work happens. It is located at `prototype/policy-engine/src/`.

The key files:
- `src/main.rs` — startup, socket handling, IPC dispatch
- `src/rules/mod.rs` — rule trait definition and rule registry
- `src/rules/*.rs` — individual rule implementations (one file per rule)
- `src/audit.rs` — audit log writing
- `src/capability_store.rs` — capability grant/revoke/check

To add a new policy rule:
1. Create `src/rules/my_rule.rs`
2. Implement the `PolicyRule` trait
3. Register the rule in `src/rules/mod.rs`
4. Add tests in `src/rules/my_rule.rs` (inline test module)
5. Add an integration test in `tests/policy_rules.rs`

See `CONTRIBUTING.md` for Policy Layer contribution requirements (including the TLA+ specification requirement).

### Hot Reloading

The Policy Engine supports hot-reloading of rules without restarting the daemon. While running:
```bash
# In another terminal:
kill -SIGHUP $(pgrep policy-engine)
# The daemon reloads rule configuration from disk
```

Note: only rule configuration can be hot-reloaded. Code changes require a full rebuild and restart.

### Editing the Context Shell

The Context Shell is at `prototype/context-shell/src/`. It is a PTY-wrapping terminal application.

Key files:
- `src/main.rs` — PTY setup, input loop, output rendering
- `src/session.rs` — session management, JSON-RPC to inference bridge
- `src/high_stakes.rs` — high-stakes command detection and confirmation UI
- `src/streaming.rs` — streaming token output rendering

### Linting and Formatting

```bash
# Format all code
cargo fmt --all

# Lint
cargo clippy --all -- -D warnings

# Both are checked in CI — fix before submitting a PR
```

---

## Hardware-Specific Setup Notes

### Snapdragon X Elite (Windows + WSL2)

See `windows.md` for WSL2-specific setup. Key additional step: the Vulkan driver from WSLg (WSL GPU support) works for inference via `ggml-vulkan`. You do not need a native Linux install for development on Snapdragon X Elite hardware running Windows 11.

### Apple Silicon

Metal backend is the most efficient option. No additional drivers needed beyond macOS with Xcode Command Line Tools. The `cmake -DGGML_METAL=ON` flag enables it.

Note: Apple Silicon Macs use unified memory. The Metal backend can access the full system RAM as VRAM, making a 32 GB M3 Pro/Max an excellent development machine for 14B models.

### x86-64 CPU Only (No GPU)

Inference works without a GPU but is slower. For a 7B model with Q4_K_M:
- Modern AMD or Intel CPU with AVX2: 8–15 tok/s
- Older hardware without AVX2: 3–6 tok/s

Use a smaller model (3B or 1.5B) if throughput is insufficient for iterative development.

---

## Troubleshooting

### "model file not found"
Check that `config.toml` points to the correct absolute path for your model file. Relative paths are not supported.

### "llama-server failed to start: out of memory"
Your model doesn't fit in available RAM/VRAM. Options:
- Use a smaller model or more aggressive quantization (IQ2_XXS, Q2_K)
- Reduce context_size in config.toml (try 4096 instead of 8192/16384)
- Close other applications to free RAM

### "policy-engine: audit log write failed"
The audit log directory must be writable. Check `/tmp/` permissions, or set a custom path in `policy-engine/config.toml`.

### "inference-bridge: connection refused"
The Policy Engine or llama-server hasn't started yet, or started on a different port. Check the terminal output from `./run.sh`. The startup order matters: policy-engine → llama-server → inference-bridge → context-shell.

### GPU not being used
Run `./build/bin/llama-server --list-backends` to see available backends. If CUDA/Metal/Vulkan isn't listed, the build didn't include that backend. Rebuild with the appropriate `-DGGML_*` flag.

---

## Next Steps After Setup

Once your environment is working:

1. Read `prototype/README.md` for the full 90-day build plan and week-by-week goals.
2. Run the test suite and check that all tests pass on your hardware.
3. Look at issues tagged `good-first-issue` and `inference` on GitHub.
4. Check the performance acceptance criteria in `prototype/README.md` and run the benchmark script against your hardware: `./prototype/bench.sh --hardware your-hardware-name`
