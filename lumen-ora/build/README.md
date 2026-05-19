# Lumen Ora — Bootable Installer

This directory contains everything needed to build a self-booting USB installer
that installs Lumen Ora on bare metal — **no Windows required**.

After installation the machine boots directly into a headless Linux appliance.
The primary UI is the web dashboard at `http://<machine-ip>:8765`, reachable from
any browser on the same network (or via Tailscale from anywhere).

## Quick start

```bash
# On WSL2 (Ubuntu) or any Linux machine:
cd build/
./build-iso.sh
# Output: lumen-ora-v0.4.0-beta-installer.iso  (~900 MB)
```

Flash to USB:

```bash
# Find your USB drive (e.g. /dev/sdb) — double-check before running!
sudo dd if=lumen-ora-v0.4.0-beta-installer.iso of=/dev/sdX bs=4M status=progress
sync
```

Or use [Balena Etcher](https://etcher.balena.io/) (GUI, Windows/Mac/Linux).

Boot the target machine from the USB. The installer runs **hands-off** —
it will erase the selected drive and install automatically.

---

## What the installer does

1. **Boots** Ubuntu Server 24.04 LTS minimal (no desktop)
2. **Partitions** the target drive: 1 GB EFI + 4 GB swap + rest ext4 root
3. **Installs** Ubuntu base system + Python 3.11 + Rust toolchain + build tools
4. **Enables** four systemd services (see `services/`)
5. **Reboots** → on first boot, `lumen-firstboot.service` runs once:
   - Clones the lumen-ora repo
   - `cargo build` for the policy engine (~2 min)
   - `pip install` for the bridge + shell
   - Downloads `llama-server` Linux binary from llama.cpp releases
   - Downloads `qwen2.5-7b-instruct-q4_k_m.gguf` from Hugging Face (~4.4 GB)
6. **Serves** the web dashboard permanently at `:8765`

First-boot download takes 5–15 minutes depending on connection speed.
Progress is visible via: `journalctl -fu lumen-firstboot`

---

## Requirements for the build machine

| Tool | Install |
|------|---------|
| `xorriso` | `apt install xorriso` |
| `curl` | `apt install curl` |
| `mtools` | `apt install mtools` |
| ~2 GB free disk | for Ubuntu ISO + scratch space |

## Requirements for the target machine

| Item | Minimum | Recommended |
|------|---------|-------------|
| Architecture | x86-64 | x86-64 with AVX2 |
| RAM | 8 GB | 16 GB |
| Disk | 20 GB | 60 GB |
| Boot | UEFI or BIOS | UEFI |
| Network | Required (first boot) | Wired Ethernet |

The 7B model alone occupies ~4.4 GB RAM. 8 GB is the hard floor.
16 GB is recommended so the OS + model + bridge all fit comfortably.

---

## Files in this directory

```
build/
├── README.md             # This file
├── build-iso.sh          # Builds the bootable ISO from scratch
├── install-linux.sh      # Installs Lumen Ora on an existing Linux system
├── autoinstall.yaml      # Ubuntu autoinstall (cloud-init/curtin) config
├── grub.cfg              # GRUB boot menu for the installer ISO
├── firstboot.sh          # One-time first-boot setup script
└── services/
    ├── lumen-llama.service    # llama-server (model inference)
    ├── lumen-policy.service   # Rust policy engine
    ├── lumen-bridge.service   # FastAPI bridge + web dashboard
    └── lumen-firstboot.service# First-boot download + setup (runs once)
```

---

## Accessing Lumen Ora after install

Find the machine's IP address:

```bash
# On the Lumen Ora machine:
ip addr show | grep "inet " | grep -v 127

# Or from another machine:
nmap -sn 192.168.1.0/24 | grep -A2 lumen
```

Then open: `http://<ip>:8765`

For remote access from outside your LAN, see the Tailscale recipe in
the top-level [INSTALL.md](../INSTALL.md).

SSH is enabled: `ssh lumen@<ip>` (password set during autoinstall, or
add your public key to `autoinstall.yaml` before building).

---

## Customising before build

| Want to change | Edit |
|----------------|------|
| Username / password | `autoinstall.yaml` → `identity` section |
| SSH public key | `autoinstall.yaml` → `ssh` → `authorized-keys` |
| Drive to install to | `autoinstall.yaml` → `storage` → `disk` (default: first disk) |
| Timezone | `autoinstall.yaml` → `locale` / `timezone` |
| Model size (3B vs 7B) | `firstboot.sh` → `MODEL_URL` and `MODEL_NAME` variables |
| Repo to clone | `firstboot.sh` → `REPO_URL` |
