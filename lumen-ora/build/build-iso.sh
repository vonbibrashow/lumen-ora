#!/bin/bash
# Lumen Ora — ISO builder
#
# Builds a bootable USB/ISO installer from Ubuntu Server 24.04 LTS.
# Run this in WSL2 (Ubuntu) or on any Linux machine with xorriso.
#
# Prerequisites:
#   sudo apt install xorriso curl mtools isolinux syslinux-utils
#
# Usage:
#   cd lumen-ora/build
#   ./build-iso.sh
#   # Output: lumen-ora-v0.4.0-beta-installer.iso

set -euo pipefail

VERSION="v0.4.0-beta"
OUTPUT_ISO="lumen-ora-${VERSION}-installer.iso"
UBUNTU_VERSION="24.04"
UBUNTU_ISO_URL="https://releases.ubuntu.com/${UBUNTU_VERSION}/ubuntu-${UBUNTU_VERSION}-live-server-amd64.iso"
UBUNTU_ISO="ubuntu-${UBUNTU_VERSION}-live-server-amd64.iso"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="/tmp/lumen-iso-build"
EXTRACT_DIR="$WORK_DIR/iso-extract"

BOLD="\033[1m"; CYAN="\033[36m"; GREEN="\033[32m"; RED="\033[31m"; RESET="\033[0m"
banner() { echo -e "\n${BOLD}${CYAN}── $* ──${RESET}"; }
ok()     { echo -e "  ${GREEN}✓${RESET}  $*"; }
fail()   { echo -e "  ${RED}✗${RESET}  $*"; exit 1; }

echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        Lumen Ora — ISO Builder                          ║"
echo "║        Building: $OUTPUT_ISO          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ─────────────────────────────────────────────────────────────────────────────
# Prereq checks
# ─────────────────────────────────────────────────────────────────────────────

banner "Checking prerequisites"
for cmd in xorriso curl 7z mtools; do
    if command -v "$cmd" &>/dev/null; then
        ok "$cmd found"
    else
        echo "Missing: $cmd"
        case "$cmd" in
            xorriso) echo "  Install: sudo apt install xorriso" ;;
            7z)      echo "  Install: sudo apt install p7zip-full" ;;
            mtools)  echo "  Install: sudo apt install mtools" ;;
            curl)    echo "  Install: sudo apt install curl" ;;
        esac
        fail "Missing required tool: $cmd"
    fi
done

# ─────────────────────────────────────────────────────────────────────────────
# Download Ubuntu Server ISO
# ─────────────────────────────────────────────────────────────────────────────

banner "Ubuntu Server ${UBUNTU_VERSION} ISO"
cd "$SCRIPT_DIR"

if [ ! -f "$UBUNTU_ISO" ]; then
    echo "Downloading Ubuntu Server ${UBUNTU_VERSION} (~700 MB)..."
    curl -L --progress-bar "$UBUNTU_ISO_URL" -o "$UBUNTU_ISO"
    ok "Downloaded $UBUNTU_ISO"
else
    ok "Ubuntu ISO already present ($(du -h "$UBUNTU_ISO" | cut -f1))"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Extract ISO contents
# ─────────────────────────────────────────────────────────────────────────────

banner "Extracting ISO"
rm -rf "$WORK_DIR"
mkdir -p "$EXTRACT_DIR"

# 7z can extract ISO9660 and UDF images
7z x "$UBUNTU_ISO" -o"$EXTRACT_DIR" -y >/dev/null
ok "Extracted to $EXTRACT_DIR"

# ─────────────────────────────────────────────────────────────────────────────
# Inject Lumen Ora files
# ─────────────────────────────────────────────────────────────────────────────

banner "Injecting Lumen Ora installer files"

# Create nocloud directory for autoinstall
NOCLOUD_DIR="$EXTRACT_DIR/nocloud"
mkdir -p "$NOCLOUD_DIR"

# autoinstall.yaml → meta-data + user-data (cloud-init convention)
echo "instance-id: lumen-ora-install" > "$NOCLOUD_DIR/meta-data"
cp "$SCRIPT_DIR/autoinstall.yaml" "$NOCLOUD_DIR/user-data"
ok "autoinstall.yaml → nocloud/user-data"

# Copy service files so autoinstall late-commands can pick them up
mkdir -p "$EXTRACT_DIR/lumen-services"
cp "$SCRIPT_DIR/services/"*.service "$EXTRACT_DIR/lumen-services/"
ok "systemd service files"

# Copy firstboot script
cp "$SCRIPT_DIR/firstboot.sh" "$EXTRACT_DIR/firstboot.sh"
chmod +x "$EXTRACT_DIR/firstboot.sh"
ok "firstboot.sh"

# ─────────────────────────────────────────────────────────────────────────────
# Patch GRUB config
# ─────────────────────────────────────────────────────────────────────────────

banner "Patching GRUB"

# Ubuntu Server ISO stores grub config in boot/grub/grub.cfg
GRUB_TARGET="$EXTRACT_DIR/boot/grub/grub.cfg"
GRUB_TARGET_EFI="$EXTRACT_DIR/EFI/boot/grub.cfg"

cp "$SCRIPT_DIR/grub.cfg" "$GRUB_TARGET"
[ -f "$GRUB_TARGET_EFI" ] && cp "$SCRIPT_DIR/grub.cfg" "$GRUB_TARGET_EFI"
ok "GRUB config patched"

# ─────────────────────────────────────────────────────────────────────────────
# Repack ISO with xorriso
# ─────────────────────────────────────────────────────────────────────────────

banner "Repacking ISO (preserving UEFI + BIOS boot)"
cd "$SCRIPT_DIR"

# xorriso command mirrors the structure Ubuntu uses for its server ISO
# -append_partition 2 ensures the ESP (EFI System Partition) is preserved
xorriso -as mkisofs \
    -r \
    -V "LUMEN_ORA_INSTALL" \
    --modification-date="$(date -u +%Y%m%d%H%M%S00)" \
    -o "$OUTPUT_ISO" \
    -J -joliet-long \
    -cache-inodes \
    -b boot/grub/i386-pc/eltorito.img \
    -c boot/grub/i386-pc/boot.cat \
    -no-emul-boot \
    -boot-load-size 4 \
    -boot-info-table \
    --grub2-boot-info \
    --grub2-mbr "$EXTRACT_DIR/boot/grub/i386-pc/boot_hybrid.img" \
    -append_partition 2 0xef "$EXTRACT_DIR/boot/grub/efi.img" \
    -eltorito-alt-boot \
    -e "--interval:appended_partition_2:::" \
    -no-emul-boot \
    -partition_offset 16 \
    "$EXTRACT_DIR" \
    2>&1 | tail -20

SIZE=$(du -h "$OUTPUT_ISO" | cut -f1)
ok "ISO built: $OUTPUT_ISO ($SIZE)"

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────

rm -rf "$WORK_DIR"

echo ""
echo -e "${BOLD}${GREEN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ISO ready!                                            ║"
echo "║                                                         ║"
printf "║   File: %-43s║\n" "$OUTPUT_ISO ($SIZE)"
echo "║                                                         ║"
echo "║   Flash to USB:                                         ║"
echo "║     sudo dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress"
echo "║                                                         ║"
echo "║   Or use Balena Etcher (GUI):                          ║"
echo "║     https://etcher.balena.io                            ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
