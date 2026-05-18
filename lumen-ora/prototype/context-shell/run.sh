#!/bin/bash
# Start the full Lumen Ora stack and open the Context Shell.
set -e

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

echo "Starting Lumen Ora..."

# Start policy engine in WSL2
wsl -d Ubuntu-22.04 -- bash -c \
  "LUMEN_TCP_PORT=8766 $REPO_ROOT/prototype/policy-engine/target/debug/policy-engine \
   &> /tmp/policy-engine.log &"
sleep 1

# Start inference bridge (background)
python "$REPO_ROOT/prototype/inference-bridge/bridge.py" &
BRIDGE_PID=$!
sleep 2

# Note: llama-server must be started separately (Windows native process).
# Example:
#   prototype/inference-bridge/llama-cpp/llama-server.exe \
#     --model models/qwen*.gguf --port 8080
#
# Or set LLAMA_SERVER_URL to point to an already-running instance.

echo "Inference bridge PID: $BRIDGE_PID"
echo ""

# Open the Context Shell
python "$REPO_ROOT/prototype/context-shell/shell.py"

# Cleanup on exit
kill "$BRIDGE_PID" 2>/dev/null || true
echo "Lumen Ora stopped."
