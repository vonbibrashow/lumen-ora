#!/bin/bash
# Lumen Ora — First-boot setup script
# Runs ONCE after the OS installer completes.
# Triggered by lumen-firstboot.service (systemd, runs as lumen user).
#
# What it does:
#   1. Clones the lumen-ora repo
#   2. Builds the Rust policy engine (cargo build)
#   3. pip install all Python dependencies
#   4. Downloads llama-server Linux binary from llama.cpp releases
#   5. Downloads Qwen2.5-7B GGUF model from Hugging Face
#   6. Enables and starts all three runtime services
#   7. Writes ~/.lumen-firstboot-done so this only runs once

set -euo pipefail

# ─────────────────────────────────────────────────────────────────────────────
# Configuration — edit these before building the ISO if needed
# ─────────────────────────────────────────────────────────────────────────────

REPO_URL="https://github.com/vonbibrashow/lumen-ora.git"
INSTALL_DIR="/opt/lumen-ora"
LUMEN_DIR="$HOME/.lumen"
DONE_MARKER="$HOME/.lumen-firstboot-done"

# Model — change to 3B for machines with 8 GB RAM
MODEL_NAME="qwen2.5-7b-instruct-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/${MODEL_NAME}"

# llama.cpp Linux release — script fetches latest automatically
LLAMA_RELEASE_API="https://api.github.com/repos/ggerganov/llama.cpp/releases/latest"

LOG_FILE="/var/log/lumen-firstboot.log"

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
die() { log "ERROR: $*"; exit 1; }

step() {
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "  $*"
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
}

# ─────────────────────────────────────────────────────────────────────────────
# Guard: only run once
# ─────────────────────────────────────────────────────────────────────────────

if [ -f "$DONE_MARKER" ]; then
    log "First-boot already completed. Remove $DONE_MARKER to re-run."
    exit 0
fi

log "Lumen Ora first-boot setup starting..."
sudo touch "$LOG_FILE" && sudo chmod 644 "$LOG_FILE"

# ─────────────────────────────────────────────────────────────────────────────
# Step 1: Wait for network
# ─────────────────────────────────────────────────────────────────────────────

step "1/7 — Waiting for network..."
for i in $(seq 1 30); do
    if ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; then
        log "Network ready."
        break
    fi
    [ "$i" -eq 30 ] && die "No network after 60 s. Check your Ethernet connection."
    sleep 2
done

# ─────────────────────────────────────────────────────────────────────────────
# Step 2: Clone the repo
# ─────────────────────────────────────────────────────────────────────────────

step "2/7 — Cloning lumen-ora repo..."
if [ -d "$INSTALL_DIR/.git" ]; then
    log "Repo already cloned at $INSTALL_DIR, pulling latest..."
    git -C "$INSTALL_DIR" pull --ff-only
else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR" 2>&1 | tee -a "$LOG_FILE"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 3: Build the policy engine (Rust)
# ─────────────────────────────────────────────────────────────────────────────

step "3/7 — Building Rust policy engine (~2 min)..."
# Source cargo env (rustup installs to ~/.cargo by default)
source "$HOME/.cargo/env" 2>/dev/null || true
export PATH="$HOME/.cargo/bin:$PATH"

if ! command -v cargo &>/dev/null; then
    log "Rust not found — installing rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path 2>&1 | tee -a "$LOG_FILE"
    source "$HOME/.cargo/env"
fi

cd "$INSTALL_DIR/prototype/policy-engine"
cargo build --release 2>&1 | tee -a "$LOG_FILE"
log "Policy engine built at target/release/policy-engine"

# ─────────────────────────────────────────────────────────────────────────────
# Step 4: Python dependencies
# ─────────────────────────────────────────────────────────────────────────────

step "4/7 — Installing Python dependencies..."
python3.11 -m pip install --upgrade pip --quiet
python3.11 -m pip install \
    httpx \
    fastapi \
    uvicorn[standard] \
    sse-starlette \
    pydantic \
    rich \
    ddgs \
    faster-whisper \
    pyttsx3 \
    sounddevice \
    soundfile \
    pynput \
    pyperclip \
    mss \
    pillow \
    keyboard \
    2>&1 | tee -a "$LOG_FILE"
log "Python dependencies installed."

# ─────────────────────────────────────────────────────────────────────────────
# Step 5: Download llama-server Linux binary
# ─────────────────────────────────────────────────────────────────────────────

step "5/7 — Downloading llama-server Linux binary..."
LLAMA_DIR="$INSTALL_DIR/prototype/inference-bridge/llama-cpp"
mkdir -p "$LLAMA_DIR"

if [ ! -f "$LLAMA_DIR/llama-server" ]; then
    log "Fetching latest llama.cpp release info..."
    RELEASE_JSON=$(curl -s "$LLAMA_RELEASE_API")

    # Find the Ubuntu/Linux x64 asset URL
    ASSET_URL=$(echo "$RELEASE_JSON" | python3 -c "
import sys, json
data = json.load(sys.stdin)
assets = data.get('assets', [])
for a in assets:
    name = a['name'].lower()
    if ('ubuntu' in name or 'linux' in name) and 'x64' in name and name.endswith('.zip'):
        print(a['browser_download_url'])
        break
" 2>/dev/null)

    if [ -z "$ASSET_URL" ]; then
        # Fallback: build from source
        log "No prebuilt binary found — building llama.cpp from source..."
        LLAMA_SRC="/tmp/llama-cpp-src"
        git clone --depth 1 https://github.com/ggerganov/llama.cpp.git "$LLAMA_SRC"
        cd "$LLAMA_SRC"
        cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=ON
        cmake --build build --config Release -j$(nproc) 2>&1 | tee -a "$LOG_FILE"
        cp build/bin/llama-server "$LLAMA_DIR/llama-server"
        rm -rf "$LLAMA_SRC"
    else
        log "Downloading: $ASSET_URL"
        curl -L "$ASSET_URL" -o /tmp/llama-release.zip 2>&1 | tee -a "$LOG_FILE"
        unzip -o /tmp/llama-release.zip llama-server -d "$LLAMA_DIR" 2>/dev/null || \
        unzip -o /tmp/llama-release.zip "*/llama-server" -d /tmp/llama-extract 2>/dev/null && \
            find /tmp/llama-extract -name "llama-server" -exec cp {} "$LLAMA_DIR/" \;
        rm -f /tmp/llama-release.zip
        chmod +x "$LLAMA_DIR/llama-server"
    fi
    log "llama-server ready at $LLAMA_DIR/llama-server"
else
    log "llama-server already present, skipping download."
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 6: Download the model
# ─────────────────────────────────────────────────────────────────────────────

step "6/7 — Downloading model (${MODEL_NAME}) — this may take 10-20 min..."
MODEL_PATH="$LLAMA_DIR/$MODEL_NAME"

if [ ! -f "$MODEL_PATH" ]; then
    log "Downloading from Hugging Face (~4.4 GB)..."
    wget --progress=bar:force:noscroll \
         --retry-connrefused \
         --tries=5 \
         -O "$MODEL_PATH" \
         "$MODEL_URL" 2>&1 | tee -a "$LOG_FILE"
    log "Model downloaded to $MODEL_PATH"
else
    log "Model already present at $MODEL_PATH, skipping."
fi

# ─────────────────────────────────────────────────────────────────────────────
# Step 7: Install and start systemd services
# ─────────────────────────────────────────────────────────────────────────────

step "7/7 — Installing systemd services..."

# Update service files with actual paths
for svc in lumen-llama lumen-policy lumen-bridge; do
    SVC_FILE="/etc/systemd/system/${svc}.service"
    if [ -f "$SVC_FILE" ]; then
        sudo sed -i "s|/opt/lumen-ora|${INSTALL_DIR}|g" "$SVC_FILE"
        sudo sed -i "s|User=lumen|User=$(whoami)|g" "$SVC_FILE"
    fi
done

sudo systemctl daemon-reload
sudo systemctl enable --now lumen-llama.service
sudo systemctl enable --now lumen-policy.service

# Wait a moment for llama-server to load the model
log "Waiting 10 s for llama-server to initialise..."
sleep 10

sudo systemctl enable --now lumen-bridge.service

# ─────────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────────

touch "$DONE_MARKER"

MY_IP=$(hostname -I | awk '{print $1}')
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           Lumen Ora is ready!                           ║"
echo "║                                                         ║"
echo "║   Open in any browser:                                  ║"
printf "║   http://%-42s║\n" "${MY_IP}:8765     "
echo "║                                                         ║"
echo "║   SSH:  ssh $(whoami)@${MY_IP}                             ║"
echo "║                                                         ║"
echo "║   Logs: journalctl -fu lumen-bridge                     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
log "First-boot setup complete!"
