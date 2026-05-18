# Windows Development Setup (WSL2)

This guide covers setting up a Lumen Ora inference layer development environment on Windows 11 using WSL2. This is the recommended path for Windows contributors, including those on Snapdragon X Elite hardware running Windows 11 for ARM.

**What you can develop with this setup:**
- The Inference Bridge (Rust)
- The Context Shell (Rust)
- The Policy Engine prototype (Rust)
- llama.cpp with GPU acceleration (via WSLg GPU passthrough)

**What you cannot develop with this setup:**
- The Genode/seL4 layer (requires a native Linux host — see `genode.md`)
- NPU-specific code for Snapdragon (the QNN backend requires native Windows or a Linux boot; WSL2 does not expose the NPU to WSL2 processes)

---

## Prerequisites

- Windows 11 22H2 or later (required for WSLg GPU support)
- At least 16 GB RAM
- 50 GB free disk space for the WSL2 partition

### On Snapdragon X Elite Hardware

Snapdragon X Elite machines (Surface Pro 11, Dell XPS 13 9345, Asus Vivobook S 15, etc.) run Windows 11 for ARM. WSL2 on these machines runs an ARM64 Linux environment, which is exactly what we want for developing and testing ARM64 inference code.

GPU acceleration in WSL2 on Snapdragon X Elite uses the Qualcomm Adreno GPU via a WDDM bridge driver. This works for Vulkan-based inference but not for NPU (Hexagon) inference.

---

## Step 1: Install WSL2

Open PowerShell as Administrator and run:
```powershell
wsl --install
```

This installs WSL2 with Ubuntu as the default distribution. Restart when prompted.

After restart, open the Ubuntu app from the Start menu and complete the initial setup (create a username and password).

Verify WSL2 is configured correctly:
```powershell
wsl --status
# Should show: Default Version: 2
```

### Configure WSL2 Memory

By default, WSL2 uses up to 50% of system RAM. For 16B model development, you want more:

Create or edit `%USERPROFILE%\.wslconfig`:
```ini
[wsl2]
memory=12GB       # adjust based on your total RAM
swap=0            # disable swap for inference (latency)
processors=8      # match your CPU core count
```

Restart WSL2 after changing this:
```powershell
wsl --shutdown
```

---

## Step 2: Enable GPU Acceleration in WSL2

GPU acceleration for WSL2 is provided through the WSLg (Windows Subsystem for Linux GUI) graphics stack. It requires up-to-date GPU drivers.

### For NVIDIA GPUs
Install the NVIDIA CUDA on WSL driver from: https://developer.nvidia.com/cuda/wsl
This installs a special WSL-compatible CUDA driver. Do NOT install CUDA inside WSL2 directly — use the Windows driver only, then install the CUDA toolkit inside WSL2.

Inside WSL2:
```bash
wget https://developer.download.nvidia.com/compute/cuda/repos/ubuntu2404/x86_64/cuda-keyring_1.1-1_all.deb
sudo dpkg -i cuda-keyring_1.1-1_all.deb
sudo apt update
sudo apt install cuda-toolkit-12-6
```

Verify:
```bash
nvidia-smi  # should show your GPU and driver version
nvcc --version
```

### For AMD GPUs
AMD GPU support in WSL2 requires ROCm via DirectX 12 backend. Install AMD's GPU drivers for Windows normally, then inside WSL2:
```bash
# WSL2 uses AMD's DX12 → Vulkan bridge
# Verify Vulkan works:
sudo apt install vulkan-tools
vulkaninfo | grep deviceName
```

### For Qualcomm Adreno (Snapdragon X Elite)
The Adreno GPU is accessible via Vulkan through the WDDM bridge. No additional driver installation is needed inside WSL2 — it works out of the box once the Windows GPU drivers are up to date (via Windows Update).

Inside WSL2:
```bash
sudo apt install vulkan-tools libvulkan1
vulkaninfo | grep deviceName
# Should show: deviceName = Qualcomm Adreno (TM) 740 (or similar)
```

If `vulkaninfo` fails, update your Windows drivers from the manufacturer's support site.

---

## Step 3: Set Up the Development Environment in WSL2

Open your Ubuntu WSL2 terminal and follow the standard `inference.md` setup guide from this point. All the commands work identically inside WSL2. The key difference is:

**When building llama.cpp in WSL2 on Snapdragon X Elite:**
```bash
# Use Vulkan backend (Adreno GPU via WDDM bridge)
cmake -B build \
  -DLLAMA_BUILD_SERVER=ON \
  -DGGML_VULKAN=ON
cmake --build build --config Release -j$(nproc)
```

**When building on WSL2 with an NVIDIA GPU:**
```bash
cmake -B build \
  -DLLAMA_BUILD_SERVER=ON \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=native
cmake --build build --config Release -j$(nproc)
```

---

## Step 4: Configure VS Code (Optional but Recommended)

VS Code has excellent WSL2 integration via the "WSL" extension, which runs the VS Code server inside WSL2 while the UI stays on Windows.

1. Install VS Code for Windows: https://code.visualstudio.com
2. Install the "WSL" extension (ID: `ms-vscode-remote.remote-wsl`)
3. Open your project in WSL2: from the Ubuntu terminal:
   ```bash
   code ~/lumen-ora
   ```
   This opens VS Code in Windows but connected to your WSL2 environment.

4. Install the Rust Analyzer extension inside the WSL2 environment (VS Code will prompt you to do this).

---

## Accessing Files Between Windows and WSL2

Your WSL2 home directory is accessible from Windows at:
```
\\wsl.localhost\Ubuntu\home\<username>\
```

You can browse this in File Explorer. For model files (which are large), store them inside the WSL2 filesystem (not on the Windows NTFS partition) for best performance. NTFS I/O through WSL2 is significantly slower than the WSL2 ext4 filesystem.

**Slow model loading?** Make sure your model files are inside WSL2:
- Good: `/home/username/lumen-ora-models/model.gguf`
- Slow: `/mnt/c/Users/username/lumen-ora-models/model.gguf`

---

## Running the Context Shell

The Context Shell is a terminal application. It works fine in the WSL2 terminal (Windows Terminal is recommended for the best experience).

Install Windows Terminal from the Microsoft Store if you haven't already. It supports true color, ligatures, and the tab-based multi-pane workflow useful for running the daemons alongside the shell.

Suggested Windows Terminal setup for development:
- Tab 1: `./run.sh --no-shell` (starts Policy Engine + llama-server + Inference Bridge)
- Tab 2: `./context-shell` (the interactive AI interface)
- Tab 3: `tail -f /tmp/lumen-audit.log` (watching the audit log)

---

## Performance Expectations on Snapdragon X Elite + WSL2

Running under WSL2 adds a small overhead versus native Linux. Expected throughput for Qwen2.5-14B Q4_K_M on Snapdragon X Elite via WSL2 + Vulkan:

| Condition | Expected tok/s |
|-----------|---------------|
| Native Linux (dual-boot) | 20–25 |
| WSL2 + Vulkan (development) | 16–21 |
| WSL2 + CPU only (fallback) | 4–8 |

The WSL2 overhead is acceptable for development work. For hardware acceptance testing against the prototype's performance criteria, run on native Linux (NixOS) via dual-boot or a USB boot.

---

## Known Limitations on Windows / WSL2

1. **No NPU (Hexagon) access.** The Qualcomm Hexagon NPU is not exposed to WSL2 processes. NPU-accelerated inference on Snapdragon requires either:
   - A native Linux boot (NixOS on Snapdragon X Elite is supported on some models)
   - The native Windows build of llama.cpp (which works with QNN but is not the Lumen Ora prototype's target environment)

2. **No seL4/Genode development.** The Genode build system requires a native Linux host. WSL2 is not supported.

3. **Memory overhead.** WSL2 itself uses ~200–400 MB of RAM. On a 16 GB machine, factor this into your memory budget when deciding which model to load.

4. **Vulkan performance variance.** The WDDM Vulkan bridge on Snapdragon can have higher latency variance than native Vulkan. You may see occasional slow inference turns. This is not a Lumen Ora bug.

---

## Getting Help

If you run into issues with WSL2 setup:
- Check the WSL2 GitHub repo for known issues: https://github.com/microsoft/WSL
- For Vulkan issues on Snapdragon, check the Mesa3D and Turnip tracker: https://gitlab.freedesktop.org/mesa/mesa/-/issues
- For Lumen Ora-specific issues, open a GitHub issue with the `dev-environment` and `windows` labels

For general WSL2 setup help, Microsoft's documentation at https://learn.microsoft.com/windows/wsl/ is thorough and kept up to date.
