#!/bin/bash
# Lumen Ora — ISO builder
#
# Builds a bootable USB/ISO installer from Ubuntu Server 24.04 LTS.
# Run this in WSL2 (Ubuntu) or on any Linux machine with xorriso.
#
# Prerequisites (installed automatically if missing):
#   sudo apt install xorriso curl wget mtools p7zip-full
#
# Usage:
#   cd /mnt/c/Users/SETUP/Documents/claude/lumen-ora/build
#   bash build-iso.sh
#   # Output: lumen-ora-v0.4.0-beta-installer.iso
#
# Ubuntu 24.04 boot structure notes:
#   - Boot files live in boot/grub/i386-pc/ and boot/grub/x86_64-efi/
#   - EFI image is boot/grub/efi.img  (not a separate .efi.img)
#   - MBR hybrid image: boot/grub/i386-pc/boot_hybrid.img
#   - xorriso -append_partition 2 0xef <efi.img> is needed for UEFI
#   - osirrox (part of xorriso) must be used for extraction to preserve
#     the hidden boot sectors that 7z misses

set -euo pipefail

VERSION="v0.4.0-beta"
OUTPUT_ISO="lumen-ora-${VERSION}-installer.iso"
# UBUNTU_VERSION is auto-detected at runtime from the releases page —
# point releases come out every ~6 months (24.04.1, .2, .3, .4 ...) so
# hard-coding the version causes 404s on stale scripts.
UBUNTU_ISO="ubuntu-24.04-live-server-amd64.iso"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORK_DIR="/tmp/lumen-iso-build"
EXTRACT_DIR="$WORK_DIR/iso-extract"

BOLD="\033[1m"; CYAN="\033[36m"; GREEN="\033[32m"; RED="\033[31m"; YELLOW="\033[33m"; RESET="\033[0m"
banner() { echo -e "\n${BOLD}${CYAN}── $* ──${RESET}"; }
ok()     { echo -e "  ${GREEN}✓${RESET}  $*"; }
warn()   { echo -e "  ${YELLOW}!${RESET}  $*"; }
fail()   { echo -e "  ${RED}✗${RESET}  $*"; exit 1; }

echo -e "${BOLD}${CYAN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║        Lumen Ora — ISO Builder                          ║"
echo "║        Building: $OUTPUT_ISO          ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"

# ─────────────────────────────────────────────────────────────────────────────
# Prereq checks + auto-install
# ─────────────────────────────────────────────────────────────────────────────

banner "Checking prerequisites"

MISSING_PKGS=()
command -v xorriso &>/dev/null || MISSING_PKGS+=(xorriso)
command -v 7z      &>/dev/null || MISSING_PKGS+=(p7zip-full)
command -v mtools  &>/dev/null || MISSING_PKGS+=(mtools)
command -v wget    &>/dev/null || MISSING_PKGS+=(wget)

if [ ${#MISSING_PKGS[@]} -gt 0 ]; then
    echo "Installing missing packages: ${MISSING_PKGS[*]}"
    sudo apt-get update -qq
    sudo apt-get install -y "${MISSING_PKGS[@]}"
fi

for cmd in xorriso 7z mtools wget; do
    command -v "$cmd" &>/dev/null && ok "$cmd found" || fail "Still missing: $cmd"
done

# osirrox ships with xorriso
command -v osirrox &>/dev/null && ok "osirrox found" || warn "osirrox not found — will fall back to 7z extraction"

# ─────────────────────────────────────────────────────────────────────────────
# Download Ubuntu Server ISO
# ─────────────────────────────────────────────────────────────────────────────

banner "Ubuntu Server 24.04 ISO"
cd "$SCRIPT_DIR"

if [ -f "$UBUNTU_ISO" ]; then
    SIZE_BYTES=$(stat -c%s "$UBUNTU_ISO" 2>/dev/null || stat -f%z "$UBUNTU_ISO")
    if [ "$SIZE_BYTES" -lt 600000000 ]; then
        warn "Existing ISO looks incomplete ($(du -h "$UBUNTU_ISO" | cut -f1)) — re-downloading"
        rm -f "$UBUNTU_ISO"
    else
        ok "Ubuntu ISO already present ($(du -h "$UBUNTU_ISO" | cut -f1))"
    fi
fi

if [ ! -f "$UBUNTU_ISO" ]; then
    # Auto-detect latest 24.04.x point release.
    # Ubuntu publishes point releases at https://releases.ubuntu.com/24.04/
    # and removes older ones, so we scrape the directory listing.
    echo "Detecting latest Ubuntu Server 24.04 point release..."
    LATEST_FILENAME=$(curl -s https://releases.ubuntu.com/24.04/ \
        | grep -oE 'ubuntu-24\.04\.[0-9]+-live-server-amd64\.iso' \
        | sort -V | tail -1)

    if [ -z "$LATEST_FILENAME" ]; then
        # Fallback: try known versions in reverse order
        for v in 24.04.4 24.04.3 24.04.2 24.04.1 24.04; do
            candidate_url="https://releases.ubuntu.com/24.04/ubuntu-${v}-live-server-amd64.iso"
            if curl -fIs "$candidate_url" >/dev/null 2>&1; then
                LATEST_FILENAME="ubuntu-${v}-live-server-amd64.iso"
                ok "Fallback to $LATEST_FILENAME"
                break
            fi
        done
    fi

    [ -z "$LATEST_FILENAME" ] && fail "Could not find any Ubuntu 24.04 server ISO on releases.ubuntu.com"

    UBUNTU_ISO_URL="https://releases.ubuntu.com/24.04/$LATEST_FILENAME"
    ok "Latest: $LATEST_FILENAME"

    echo "Downloading $LATEST_FILENAME (~700 MB)..."
    wget --progress=bar:force:noscroll \
         --retry-connrefused \
         --tries=3 \
         -O "$UBUNTU_ISO" \
         "$UBUNTU_ISO_URL"
    ok "Downloaded $UBUNTU_ISO ($(du -h "$UBUNTU_ISO" | cut -f1))"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Inspect ISO structure (once, for build log clarity)
# ─────────────────────────────────────────────────────────────────────────────

banner "Inspecting ISO structure"
echo "Boot-related files:"
7z l "$UBUNTU_ISO" 2>/dev/null | grep -iE 'grub|efi|casper|boot|\.img' | head -40 || true

# Detect EFI image path — Ubuntu 24.04 uses boot/grub/efi.img
EFI_IMG_CANDIDATES=(
    "boot/grub/efi.img"
    "boot/grub/efi/efi.img"
    "EFI/boot/bootx64.efi"
)
EFI_IMG=""
for candidate in "${EFI_IMG_CANDIDATES[@]}"; do
    if 7z l "$UBUNTU_ISO" 2>/dev/null | grep -qi "$(basename "$candidate")"; then
        EFI_IMG="$candidate"
        ok "EFI image: $EFI_IMG"
        break
    fi
done

[ -z "$EFI_IMG" ] && warn "Could not auto-detect EFI image path — will probe after extraction"

# ─────────────────────────────────────────────────────────────────────────────
# Extract ISO contents
# ─────────────────────────────────────────────────────────────────────────────

banner "Extracting ISO"
rm -rf "$WORK_DIR"
mkdir -p "$EXTRACT_DIR"

# Prefer osirrox (part of xorriso) — it preserves all sectors including boot
# 7z misses hidden/system areas needed for proper boot sector reconstruction
if command -v osirrox &>/dev/null; then
    echo "Using osirrox for full ISO extraction..."
    osirrox -indev "$SCRIPT_DIR/$UBUNTU_ISO" -extract / "$EXTRACT_DIR/" 2>&1 | tail -5
    ok "Extracted with osirrox"
else
    warn "osirrox not available — using 7z (boot sectors may need separate handling)"
    7z x "$SCRIPT_DIR/$UBUNTU_ISO" -o"$EXTRACT_DIR" -y 2>&1 | tail -5
    ok "Extracted with 7z"
fi

# osirrox preserves the original ISO's read-only permissions; we need to
# patch grub.cfg and inject files, so make the whole tree writable for owner.
chmod -R u+w "$EXTRACT_DIR" 2>/dev/null
ok "Extract tree made writable"

# Show what we got
echo "Extracted boot layout:"
find "$EXTRACT_DIR/boot" -maxdepth 4 -name "*.img" -o -name "*.efi" 2>/dev/null | head -20 || true

# ─────────────────────────────────────────────────────────────────────────────
# Resolve boot file paths from actual extraction
# ─────────────────────────────────────────────────────────────────────────────

banner "Resolving boot file paths"

# MBR hybrid image
BOOT_HYBRID=""
for path in \
    "$EXTRACT_DIR/boot/grub/i386-pc/boot_hybrid.img" \
    "$EXTRACT_DIR/boot/grub/boot_hybrid.img"; do
    if [ -f "$path" ]; then
        BOOT_HYBRID="$path"
        ok "MBR hybrid: $path"
        break
    fi
done

# Ubuntu 24.04.4 no longer ships boot_hybrid.img as a file — the hybrid MBR
# code is baked into the first 432 bytes of the ISO image itself. Extract it.
if [ -z "$BOOT_HYBRID" ]; then
    BOOT_HYBRID="$WORK_DIR/boot_hybrid.img"
    dd if="$SCRIPT_DIR/$UBUNTU_ISO" of="$BOOT_HYBRID" bs=1 count=432 \
       status=none 2>/dev/null
    if [ -s "$BOOT_HYBRID" ]; then
        ok "MBR hybrid: extracted from source ISO (first 432 bytes)"
    else
        warn "Could not extract MBR — BIOS boot may not work"
        BOOT_HYBRID=""
    fi
fi

# BIOS eltorito boot image
ELTORITO=""
for path in \
    "$EXTRACT_DIR/boot/grub/i386-pc/eltorito.img" \
    "$EXTRACT_DIR/boot/grub/i386-pc/cdboot.img" \
    "$EXTRACT_DIR/boot/grub/bios.img"; do
    if [ -f "$path" ]; then
        ELTORITO="$path"
        ELTORITO_REL="${path#$EXTRACT_DIR/}"
        ok "El Torito image: $ELTORITO_REL"
        break
    fi
done
[ -z "$ELTORITO" ] && fail "No BIOS El Torito boot image found"

# Boot catalog
BOOT_CAT_REL="boot/grub/i386-pc/boot.cat"
[ -f "$EXTRACT_DIR/$BOOT_CAT_REL" ] || BOOT_CAT_REL="boot/grub/boot.cat"
ok "Boot catalog: $BOOT_CAT_REL"

# EFI partition image. Older Ubuntu versions shipped a separate efi.img;
# 24.04.4 embeds the EFI System Partition (ESP) as an appended partition
# at the end of the ISO. Try to find efi.img first, then fall back to
# extracting partition #2 from the source ISO.
EFI_IMG_PATH=""
if [ -f "$EXTRACT_DIR/boot/grub/efi.img" ]; then
    EFI_IMG_PATH="$EXTRACT_DIR/boot/grub/efi.img"
    ok "EFI image: boot/grub/efi.img"
fi

if [ -z "$EFI_IMG_PATH" ]; then
    # Parse the source ISO's GPT to find the EFI partition (type 0xef)
    # and dd it out as a standalone image.
    echo "  Extracting EFI partition from source ISO..."

    # Use fdisk -l (preferred) or sfdisk to read the partition table
    PART_INFO=$(fdisk -l "$SCRIPT_DIR/$UBUNTU_ISO" 2>/dev/null \
        | grep -E "EFI|esp|0xef|EF00" | head -1)

    if [ -z "$PART_INFO" ]; then
        # Try sfdisk dump as a backup
        PART_INFO=$(sfdisk -d "$SCRIPT_DIR/$UBUNTU_ISO" 2>/dev/null \
            | grep -i "type=.*ef" | head -1)
    fi

    if [ -n "$PART_INFO" ]; then
        # fdisk output format: "device start end sectors size type"
        # extract start sector and sector count
        PART_START=$(echo "$PART_INFO" | awk '{print $2}' | grep -oE '[0-9]+' | head -1)
        PART_SECTORS=$(echo "$PART_INFO" | awk '{print $4}' | grep -oE '[0-9]+' | head -1)

        if [ -n "$PART_START" ] && [ -n "$PART_SECTORS" ]; then
            EFI_IMG_PATH="$WORK_DIR/efi.img"
            dd if="$SCRIPT_DIR/$UBUNTU_ISO" of="$EFI_IMG_PATH" \
                bs=512 skip="$PART_START" count="$PART_SECTORS" \
                status=none 2>/dev/null
            if [ -s "$EFI_IMG_PATH" ]; then
                ok "EFI partition extracted: $(du -h "$EFI_IMG_PATH" | cut -f1) (start=$PART_START sectors=$PART_SECTORS)"
            else
                warn "EFI extraction produced empty file"
                EFI_IMG_PATH=""
            fi
        fi
    fi
fi

[ -z "$EFI_IMG_PATH" ] && warn "No EFI image found — UEFI boot may not work"

# Detect casper kernel + initrd
if [ -d "$EXTRACT_DIR/casper" ]; then
    ok "casper/ directory present"
    ls "$EXTRACT_DIR/casper/" | head -6
else
    warn "casper/ not found — check ISO extraction"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Inject Lumen Ora files
# ─────────────────────────────────────────────────────────────────────────────

banner "Injecting Lumen Ora installer files"

# nocloud directory for autoinstall
NOCLOUD_DIR="$EXTRACT_DIR/nocloud"
mkdir -p "$NOCLOUD_DIR"
echo "instance-id: lumen-ora-install" > "$NOCLOUD_DIR/meta-data"
cp "$SCRIPT_DIR/autoinstall.yaml" "$NOCLOUD_DIR/user-data"
ok "autoinstall.yaml → nocloud/user-data"

# systemd service files
mkdir -p "$EXTRACT_DIR/lumen-services"
cp "$SCRIPT_DIR/services/"*.service "$EXTRACT_DIR/lumen-services/"
ok "systemd service files ($(ls "$SCRIPT_DIR/services/"*.service | wc -l) files)"

# firstboot script
cp "$SCRIPT_DIR/firstboot.sh" "$EXTRACT_DIR/firstboot.sh"
chmod +x "$EXTRACT_DIR/firstboot.sh"
ok "firstboot.sh"

# ─────────────────────────────────────────────────────────────────────────────
# Patch GRUB config
# ─────────────────────────────────────────────────────────────────────────────

banner "Patching GRUB"

# Find ALL grub.cfg files inside the extracted ISO
mapfile -t GRUB_CFGS < <(find "$EXTRACT_DIR" -name "grub.cfg" 2>/dev/null)

if [ ${#GRUB_CFGS[@]} -eq 0 ]; then
    warn "No grub.cfg found in ISO — creating at boot/grub/grub.cfg"
    mkdir -p "$EXTRACT_DIR/boot/grub"
    GRUB_CFGS=("$EXTRACT_DIR/boot/grub/grub.cfg")
fi

for cfg in "${GRUB_CFGS[@]}"; do
    echo "  Patching: $cfg"
    # Back up original
    cp "$cfg" "${cfg}.orig" 2>/dev/null || true
    # Replace with our custom grub.cfg (which already has Lumen Ora entries)
    cp "$SCRIPT_DIR/grub.cfg" "$cfg"
done
ok "Patched ${#GRUB_CFGS[@]} grub.cfg file(s): ${GRUB_CFGS[*]}"

# ─────────────────────────────────────────────────────────────────────────────
# Repack ISO with xorriso
# ─────────────────────────────────────────────────────────────────────────────

banner "Repacking ISO (preserving UEFI + BIOS boot)"
cd "$SCRIPT_DIR"
OUTPUT_PATH="$SCRIPT_DIR/$OUTPUT_ISO"

# Build xorriso command dynamically based on what we found
XORRISO_CMD=(
    xorriso -as mkisofs
    -r
    -V "LUMEN_ORA_INSTALL"
    -o "$OUTPUT_PATH"
    -J -joliet-long
    -cache-inodes
)

# BIOS El Torito boot
XORRISO_CMD+=(
    -b "$ELTORITO_REL"
    -c "$BOOT_CAT_REL"
    -no-emul-boot
    -boot-load-size 4
    -boot-info-table
    --grub2-boot-info
)

# MBR hybrid (isohybrid) — needed for USB booting
if [ -n "$BOOT_HYBRID" ]; then
    XORRISO_CMD+=(--grub2-mbr "$BOOT_HYBRID")
fi

# UEFI EFI system partition
if [ -n "$EFI_IMG_PATH" ]; then
    XORRISO_CMD+=(
        -append_partition 2 0xef "$EFI_IMG_PATH"
        -eltorito-alt-boot
        -e "--interval:appended_partition_2:::"
        -no-emul-boot
        -partition_offset 16
    )
fi

XORRISO_CMD+=("$EXTRACT_DIR")

echo "Running: ${XORRISO_CMD[*]}"
echo ""
"${XORRISO_CMD[@]}" 2>&1 | tail -25

# ─────────────────────────────────────────────────────────────────────────────
# Verify output
# ─────────────────────────────────────────────────────────────────────────────

banner "Verifying output ISO"

if [ ! -f "$OUTPUT_PATH" ]; then
    fail "Output ISO not found at $OUTPUT_PATH"
fi

SIZE_BYTES=$(stat -c%s "$OUTPUT_PATH")
SIZE_MB=$((SIZE_BYTES / 1048576))
SIZE_HUMAN=$(du -h "$OUTPUT_PATH" | cut -f1)

if [ "$SIZE_BYTES" -lt 600000000 ]; then
    fail "Output ISO too small (${SIZE_HUMAN}) — something went wrong"
fi
ok "ISO size: $SIZE_HUMAN"

# Verify nocloud injection
if 7z l "$OUTPUT_PATH" 2>/dev/null | grep -q "nocloud"; then
    ok "nocloud/ directory present in ISO"
else
    warn "nocloud/ not detected in ISO listing (may still be present)"
fi

if 7z l "$OUTPUT_PATH" 2>/dev/null | grep -q "lumen-services"; then
    ok "lumen-services/ directory present in ISO"
else
    warn "lumen-services/ not detected in ISO listing"
fi

# ─────────────────────────────────────────────────────────────────────────────
# Cleanup
# ─────────────────────────────────────────────────────────────────────────────

rm -rf "$WORK_DIR"
ok "Work directory cleaned up"

# ─────────────────────────────────────────────────────────────────────────────
# Done
# ─────────────────────────────────────────────────────────────────────────────

echo ""
echo -e "${BOLD}${GREEN}"
echo "╔══════════════════════════════════════════════════════════╗"
echo "║   ISO ready!                                            ║"
echo "║                                                         ║"
printf "║   File: %-48s║\n" "$OUTPUT_ISO"
printf "║   Size: %-48s║\n" "$SIZE_HUMAN"
echo "║                                                         ║"
echo "║   Flash to USB with Balena Etcher (recommended):        ║"
echo "║     https://etcher.balena.io                            ║"
echo "║                                                         ║"
echo "║   Or dd (Linux/Mac):                                    ║"
echo "║     sudo dd if=$OUTPUT_ISO of=/dev/sdX bs=4M status=progress"
echo "║                                                         ║"
echo "║   Windows path:                                         ║"
WIN_PATH="C:\\Users\\SETUP\\Documents\\claude\\lumen-ora\\build\\$OUTPUT_ISO"
printf "║     %-52s║\n" "$WIN_PATH"
echo "╚══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
