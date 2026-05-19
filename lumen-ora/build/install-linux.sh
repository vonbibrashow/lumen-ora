#!/bin/bash
# Lumen Ora — Linux installer (existing system)
#
# Run this on any Ubuntu 22.04+, Debian 12+, or Fedora 38+ system
# to install Lumen Ora without needing to reinstall your OS.
#
# Usage:
#   curl -sSL https://raw.githubusercontent.com/vonbibrashow/lumen-ora/master/build/install-linux.sh | bash
#   # or clone and run locally:
#   git clone https://github.com/vonbibrashow/lumen-ora.git && bash lumen-ora/build/install-linux.sh

set -euo pipefail

REPO_URL="https://github.com/vonbibrashow/lumen-ora.git"
INSTALL_DIR="$HOME/lumen-ora"
BUILD_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_NAME="qwen2.5-7b-instruct-q4_k_m.gguf"
MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-7B-Instruct-GGUF/resolve/main/${MODEL_NAME}"

BOLD="\033[1m"; CYAN="\033[36m"; GREEN="\033[32m"; RED="\033[31m"; RESET="\033[0m"

banner() { echo -e "\n${BOLD}${CYAN}── $* ──${RESET}"; }
ok()     { echo -e "  ${GREEN}✓${RESET}  $*"; }
fail()   { echo -e "  ${RED}✗${RESET}  $*"; exit 1; }

echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           Lumen Ora — Linux Installer                   ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ─────────────────────────────────────────────────────────────────────────────
# Detect distro
# ─────────────────────────────────────────────────────────────────────────────

banner "Detecting OS"
if command -v apt-get &>/dev/null; then
    PKG_MGR="apt"
    ok "Debian/Ubuntu detected"
elif command -v dnf &>/dev/null; then
    PKG_MGR="dnf"
    ok "Fedora/RHEL detected"
elif command -v pacman &>/dev/null; then
    PKG_MGR="pacman"
    ok "Arch Linux detected"
else
    fail "Unsupported distro. Supported: Ubuntu/Debian, Fedora/RHEL, Arch."
fi

# ─────────────────────────────────────────────────────────────────────────────
# System dependencies
# ─────────────────────────────────────────────────────────────────────────────

banner "Installing system packages"
case "$PKG_MGR" in
    apt)
        sudo apt-get update -qq
        sudo apt-get install -y \
            python3.11 python3.11-venv python3-pip \
            git curl wget unzip build-essential \
            pkg-config libssl-dev libffi-dev \
            libsndfile1 portaudio19-dev xclip
        ;;
    dnf)
        sudo dnf install -y \
            python3.11 python3-pip \
            git curl wget unzip gcc gcc-c++ make \
            openssl-devel libffi-devel \
            libsndfile portaudio-devel xclip
        ;;
    pacman)
        sudo pacman -Sy --noconfirm \
            python python-pip \
            git curl wget unzip base-devel \
            openssl libffi \
            libsndfile portaudio xclip
        ;;
esac
ok "System packages installed"

# ─────────────────────────────────────────────────────────────────────────────
# Rust
# ─────────────────────────────────────────────────────────────────────────────

banner "Rust toolchain"
if ! command -v cargo &>/dev/null; then
    echo "Installing rustup..."
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
    source "$HOME/.cargo/env"
fi
ok "Rust $(rustc --version)"

# ─────────────────────────────────────────────────────────────────────────────
# Clone / update repo
# ─────────────────────────────────────────────────────────────────────────────

banner "Lumen Ora repository"
if [ -d "$INSTALL_DIR/.git" ]; then
    git -C "$INSTALL_DIR" pull --ff-only
    ok "Updated existing repo at $INSTALL_DIR"
else
    git clone --depth 1 "$REPO_URL" "$INSTALL_DIR"
    ok "Cloned to $INSTALL_DIR"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Build policy engine
# ─────────────────────────────────────────────────────────────────────────────

banner "Building policy engine (Rust, ~2 min)"
cd "$INSTALL_DIR/prototype/policy-engine"
cargo build --release
ok "Policy engine built"

# ─────────────────────────────────────────────────────────────────────────────
# Python deps
# ─────────────────────────────────────────────────────────────────────────────

banner "Python dependencies"
python3.11 -m pip install --upgrade pip --quiet
python3.11 -m pip install \
    httpx fastapi "uvicorn[standard]" sse-starlette pydantic rich \
    ddgs faster-whisper pyttsx3 sounddevice soundfile \
    pynput pyperclip mss pillow
ok "Python deps installed"

# ─────────────────────────────────────────────────────────────────────────────
# llama-server binary
# ─────────────────────────────────────────────────────────────────────────────

banner "llama-server Linux binary"
LLAMA_DIR="$INSTALL_DIR/prototype/inference-bridge/llama-cpp"
mkdir -p "$LLAMA_DIR"

if [ ! -f "$LLAMA_DIR/llama-server" ]; then
    echo "Fetching latest llama.cpp release..."
    ASSET_URL=$(curl -s "https://api.github.com/repos/ggerganov/llama.cpp/releases/latest" | \
        python3 -c "
import sys,json
d=json.load(sys.stdin)
for a in d.get('assets',[]):
    n=a['name'].lower()
    if ('ubuntu' in n or 'linux' in n) and 'x64' in n and n.endswith('.zip'):
        print(a['browser_download_url']); break
" 2>/dev/null)

    if [ -n "$ASSET_URL" ]; then
        echo "Downloading: $ASSET_URL"
        curl -L "$ASSET_URL" -o /tmp/llama.zip
        unzip -o /tmp/llama.zip llama-server -d "$LLAMA_DIR" 2>/dev/null || true
        find /tmp/ -name "llama-server" -exec cp {} "$LLAMA_DIR/" \; 2>/dev/null || true
        rm -f /tmp/llama.zip
        chmod +x "$LLAMA_DIR/llama-server"
    else
        echo "No prebuilt binary found — building from source (~5 min)..."
        git clone --depth 1 https://github.com/ggerganov/llama.cpp.git /tmp/llama-cpp-src
        cd /tmp/llama-cpp-src
        cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLAMA_CURL=ON
        cmake --build build -j"$(nproc)"
        cp build/bin/llama-server "$LLAMA_DIR/"
        rm -rf /tmp/llama-cpp-src
    fi
    ok "llama-server ready"
else
    ok "llama-server already present"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Model download
# ─────────────────────────────────────────────────────────────────────────────

banner "Qwen2.5-7B model (~4.4 GB)"
MODEL_PATH="$LLAMA_DIR/$MODEL_NAME"
if [ ! -f "$MODEL_PATH" ]; then
    echo "Downloading model. This may take 10-20 minutes..."
    wget --progress=bar:force:noscroll --retry-connrefused --tries=5 \
         -O "$MODEL_PATH" "$MODEL_URL"
    ok "Model downloaded"
else
    ok "Model already present"
fi

# ─────────────────────────────────────────────────────────────────────────────
# systemd services
# ─────────────────────────────────────────────────────────────────────────────

banner "Installing systemd services"
SERVICES_DIR="$INSTALL_DIR/build/services"

for svc in lumen-llama lumen-policy lumen-bridge; do
    SVC_SRC="$SERVICES_DIR/${svc}.service"
    if [ -f "$SVC_SRC" ]; then
        sudo cp "$SVC_SRC" /etc/systemd/system/
        sudo sed -i "s|/opt/lumen-ora|${INSTALL_DIR}|g" "/etc/systemd/system/${svc}.service"
        sudo sed -i "s|User=lumen|User=$(whoami)|g" "/etc/systemd/system/${svc}.service"
        ok "Installed ${svc}.service"
    fi
done

sudo systemctl daemon-reload
sudo systemctl enable --now lumen-llama.service
sudo systemctl enable --now lumen-policy.service
sleep 5
sudo systemctl enable --now lumen-bridge.service

# ─────────────────────────────────────────────────────────────────────────────
# Firewall
# ─────────────────────────────────────────────────────────────────────────────

if command -v ufw &>/dev/null; then
    sudo ufw allow 8765/tcp >/dev/null
    ok "UFW: port 8765 open"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────────

MY_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")
echo ""
echo -e "${BOLD}${GREEN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║           Lumen Ora installed!                          ║"
echo "║                                                         ║"
echo "║   Open in any browser:                                  ║"
printf "║   http://%-42s║\n" "${MY_IP}:8765     "
echo "║                                                         ║"
echo "║   Manage services:                                      ║"
echo "║     systemctl status lumen-bridge                       ║"
echo "║     journalctl -fu lumen-bridge                         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
