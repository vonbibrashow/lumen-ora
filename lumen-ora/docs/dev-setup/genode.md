# Genode Development Environment Setup

This guide covers setting up a development environment for Lumen Ora's Genode/seL4 layer. If you are contributing to the inference layer, context shell, or policy engine prototype and don't need to work with Genode itself, see `inference.md` instead — it is much simpler to set up.

**Platform requirement:** A Linux host is required for Genode development. Ubuntu 22.04/24.04 or Debian 12 are best-supported. Fedora and Arch work but may require extra steps. macOS and Windows (even with WSL2) are not supported for Genode cross-compilation at this time.

---

## Prerequisites

### System Requirements (Host Machine)

- Linux x86-64
- 16 GB RAM minimum (32 GB recommended — Genode builds are parallel and memory-hungry)
- 100 GB free disk space (the Genode depot plus all ports is large)
- Internet connection for downloading ports

### Required Packages (Ubuntu 24.04)

```bash
sudo apt update
sudo apt install -y \
  git \
  build-essential \
  libncurses-dev \
  wget \
  libsdl2-dev \
  expect \
  python3 \
  python3-pip \
  qemu-system-x86 \
  qemu-system-arm \
  gdb \
  libgmp-dev \
  flex \
  bison \
  libexpat-dev \
  libssl-dev \
  device-tree-compiler \
  u-boot-tools \
  dosfstools \
  mtools
```

For cross-compilation to ARM64 (required for Snapdragon X Elite and other ARM targets):
```bash
sudo apt install -y \
  gcc-aarch64-linux-gnu \
  g++-aarch64-linux-gnu \
  binutils-aarch64-linux-gnu
```

---

## Setting Up the Genode Toolchain

Genode requires its own cross-compilation toolchain. Do not use the system GCC — version mismatches cause subtle build failures.

### Download and Build the Genode Toolchain

```bash
# Create a workspace directory
mkdir -p ~/genode-workspace && cd ~/genode-workspace

# Clone the Genode toolchain repository
git clone https://github.com/genodelabs/genode-toolchain.git
cd genode-toolchain

# Build the toolchain for x86_64 targets (takes 30-60 minutes)
./build.sh x86_64

# Build the toolchain for ARM64 targets (another 30-60 minutes)
./build.sh aarch64
```

Alternatively, download pre-built toolchain binaries from the Genode project:
```bash
# Pre-built toolchain (faster, but ensure it matches Genode version)
wget https://depot.genode.org/genodelabs/api/tool/x86_64/2024-09-01.tar.gz
tar -xf 2024-09-01.tar.gz -C ~/genode-toolchain/
```

Add the toolchain to your PATH:
```bash
echo 'export PATH="$HOME/genode-toolchain/usr/local/genode/tool/current/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc

# Verify
genode-x86_64-g++ --version  # should print the toolchain GCC version
```

---

## Cloning the Lumen Ora Repository

```bash
cd ~/genode-workspace

# Clone Lumen Ora
git clone https://github.com/ericvonbibra/lumen-ora.git
cd lumen-ora

# The Genode and seL4 components are git submodules
git submodule update --init --recursive
```

After this, the repository structure includes:
```
lumen-ora/
  genode/              # Genode framework (submodule)
    repos/
      base/            # Genode base system
      base-sel4/       # seL4 base platform
      os/              # OS components
      libports/        # Ported libraries
  seL4/                # seL4 kernel (submodule)
  src/                 # Lumen Ora-specific components
    policy-engine/     # Policy Layer Genode component
    inference-bridge/  # Inference bridge Genode component
    context-shell/     # Context shell Genode component
```

---

## Setting Up the Genode Build System

Genode uses its own build system (not CMake or Make in the conventional sense). The build system creates a build directory separate from the source tree.

### Create a Build Directory

```bash
cd ~/genode-workspace/lumen-ora/genode

# Create a build directory for x86_64 seL4
./tool/create_builddir x86_64_sel4

# Create a build directory for ARM64 seL4 (for Snapdragon)
./tool/create_builddir arm_v8a_sel4
```

### Configure the Build

Edit the build configuration:
```bash
cd ~/genode-workspace/lumen-ora/genode/build/x86_64_sel4
```

Edit `etc/build.conf`:
```makefile
# Genode build configuration for Lumen Ora x86_64

# Parallel jobs (set to number of CPU cores)
MAKE += -j$(nproc)

# Repositories to include
REPOSITORIES += $(GENODE_DIR)/repos/base
REPOSITORIES += $(GENODE_DIR)/repos/base-sel4
REPOSITORIES += $(GENODE_DIR)/repos/os
REPOSITORIES += $(GENODE_DIR)/repos/libports
REPOSITORIES += $(GENODE_DIR)/repos/dde_linux
REPOSITORIES += $(LUMEN_ORA_DIR)/src
```

### Download Ports

Some Genode components depend on external libraries fetched at build time:
```bash
cd ~/genode-workspace/lumen-ora/genode

# Download required ports (internet access needed)
./tool/ports/prepare_port \
  libc \
  stdcxx \
  openssl \
  curl \
  sqlite3
```

---

## Building for QEMU (Local Testing)

The fastest development cycle uses QEMU for x86_64 testing. You do not need real hardware for most development work.

### Build the Lumen Ora Scenario

```bash
cd ~/genode-workspace/lumen-ora/genode/build/x86_64_sel4

# Build the minimal boot scenario (proves the stack loads and runs)
make run/lumen_ora_minimal

# This will:
# 1. Build all required components
# 2. Generate a bootable disk image
# 3. Launch QEMU with the image
```

QEMU output appears in your terminal. The system should:
1. Boot the seL4 kernel
2. Start the Genode core component
3. Start the Policy Engine daemon
4. Print: `[lumen-ora] policy engine ready`
5. Start a minimal serial console

### Run Tests

```bash
# Run the policy engine unit tests in QEMU
make run/policy_engine_tests

# Expected output:
# [policy-engine] test: fs_path_traversal_prevention ... PASS
# [policy-engine] test: capability_grant_lifecycle ... PASS
# [policy-engine] test: audit_log_append_only ... PASS
# All 12 tests passed.
```

---

## Building for Real Hardware

### x86-64 Target

```bash
cd ~/genode-workspace/lumen-ora/genode/build/x86_64_sel4

# Build a bootable image for x86_64 hardware
make run/lumen_ora_hardware_x86

# The bootable image is at:
# ~/genode-workspace/lumen-ora/genode/build/x86_64_sel4/var/run/lumen_ora_hardware_x86/image.iso
```

Write to USB:
```bash
sudo dd if=var/run/lumen_ora_hardware_x86/image.iso of=/dev/sdX bs=4M status=progress && sync
```

### ARM64 Target (Snapdragon X Elite)

The Snapdragon X Elite uses a Qualcomm-specific UEFI environment. Lumen Ora targets the Snapdragon X Elite Developer Kit (also known as CRD — Compute Reference Device) for initial ARM64 development.

```bash
cd ~/genode-workspace/lumen-ora/genode/build/arm_v8a_sel4

make run/lumen_ora_hardware_arm64

# The image is at:
# var/run/lumen_ora_hardware_arm64/image.img
```

Follow the Qualcomm CRD flashing documentation for your specific board. The Lumen Ora build system does not yet include a one-command flash script; this is a known gap.

---

## Component Development

### Creating a New Genode Component

Components live in `lumen-ora/src/`. Each component is a directory containing:
```
my-component/
  my-component.cc     # Source files
  target.mk           # Genode makefile (specifies libs and target name)
```

A minimal `target.mk`:
```makefile
TARGET  := my_component
SRC_CC  := my-component.cc
LIBS    := base
```

A minimal component `main()`:
```cpp
#include <base/component.h>
#include <base/log.h>

void Component::construct(Genode::Env &env)
{
    Genode::log("my-component: started");
}
```

### Connecting to the Policy Engine

The Policy Engine daemon exposes a Genode RPC interface. To use it from another component:

```cpp
#include <policy_engine_session/client.h>

// In your component:
Genode::Env &env = /* ... */;
Policy_engine::Connection policy(env);

// Request a capability
Policy_engine::Tool_call_result result = policy.request_capability(
    Policy_engine::Capability_class::FS,
    "/home/user/Documents",
    Policy_engine::Permission::READ
);

if (result.granted) {
    // proceed
} else {
    Genode::warning("capability denied: ", result.reason);
}
```

The full RPC interface is defined in `src/policy-engine/include/policy_engine_session/`.

---

## Debugging

### QEMU Debugging

QEMU can be launched with GDB support:
```bash
# In the run script, add:
QEMU_ARGS += -s -S  # start paused, wait for GDB

# In another terminal:
genode-x86_64-gdb build/x86_64_sel4/var/run/lumen_ora_minimal/debug/policy_engine
(gdb) target remote localhost:1234
(gdb) continue
```

### Log Output

Genode components log via `Genode::log()`, `Genode::warning()`, `Genode::error()`. Log output goes to the core log facility, which routes to the serial console (or QEMU's console output).

Filter log output for a specific component:
```bash
# In QEMU, log is interleaved from all components
# Use the LOG service in your run script to filter:
# (See Genode run scripts in genode/repos/os/run/ for examples)
```

---

## Useful Resources

- Genode Foundations book: https://genode.org/documentation/genode-foundations-24-05.pdf
- seL4 Reference Manual: https://sel4.systems/Info/Docs/seL4-manual-latest.pdf
- seL4 Tutorials: https://sel4.systems/Info/tutorials.html
- Genode genodians blog: https://genodians.org
- Genode mailing list: https://genode.org/community/mailing-lists
- Lumen Ora architecture documentation: `../architecture/overview.md`

---

## Known Issues

- The ARM64 build for Snapdragon X Elite requires the Qualcomm Board Support Package, which has a registration requirement. We are working on an open-source alternative path.
- llama.cpp as a Genode component is not yet ported. The inference bridge in the current Genode build is a stub that forwards to a Linux host process via the network. This will change as the Genode port matures.
- The Genode driver for the Qualcomm NPU (Hexagon) does not exist yet. NPU inference on Snapdragon targets currently falls back to GPU (Adreno via Vulkan/Turnip).

Open issues for these items are tracked in GitHub with the `genode-layer` and `hardware-bringup` labels.
