#!/usr/bin/env bash
# build-custom-iso.sh — Build a customized Arch ISO with omarchy-setup baked in.
#
# This script runs natively on Linux (e.g. in CI or on any workstation).
# It injects the omarchy-setup directory into the Arch live rootfs image and
# installs a login hook that auto-prompts to run setup.sh on first boot.
#
# Supports both modern EROFS-based ISOs (Arch 2022+) and legacy SquashFS ISOs.
#
# Usage:
#   ./build-custom-iso.sh <source-iso> <setup-dir> <output-iso>
#
# Requirements: xorriso, rsync, and either erofs-utils (mkfs.erofs/fsck.erofs)
#               or squashfs-tools (mksquashfs/unsquashfs) depending on ISO format.
#
# Example:
#   ./build-custom-iso.sh \
#       archlinux-2026.02.01-x86_64.iso \
#       ./omarchy-setup \
#       archlinux-2026.02.01-x86_64-omarchy-auto.iso

set -Eeuo pipefail

# ── Argument parsing ────────────────────────────────────────────────────────

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <source-iso> <setup-dir> <output-iso>" >&2
  exit 1
fi

SRC_ISO="$1"
SETUP_DIR="$2"
OUT_ISO="$3"

if [[ ! -f "$SRC_ISO" ]]; then
  echo "Error: Source ISO not found: $SRC_ISO" >&2
  exit 1
fi

if [[ ! -d "$SETUP_DIR" ]]; then
  echo "Error: Setup directory not found: $SETUP_DIR" >&2
  exit 1
fi

# ── Base dependency check ───────────────────────────────────────────────────

for cmd in xorriso rsync; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: Required tool '$cmd' is not installed." >&2
    exit 1
  fi
done

# ── Work directory ──────────────────────────────────────────────────────────

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

ROOTFS_DIR="$WORK_DIR/rootfs"
STAGING_DIR="$WORK_DIR/staging"

# ── Locate live rootfs image inside the ISO ─────────────────────────────────
# Modern Arch ISOs (2022+) use EROFS; older ones use SquashFS.

echo "[1/7] Locating live rootfs in source ISO..."

ROOTFS_FORMAT=""
ISO_ROOTFS_PATH=""

# Try EROFS first (modern default)
ISO_ROOTFS_PATH="$(xorriso -indev "$SRC_ISO" -find / -type f -name 'airootfs.erofs' -- 2>/dev/null \
  | grep -E '/airootfs\.erofs$' | head -n1)" || true

if [[ -n "$ISO_ROOTFS_PATH" ]]; then
  ROOTFS_FORMAT="erofs"
fi

# Fall back to SquashFS (.sfs)
if [[ -z "$ISO_ROOTFS_PATH" ]]; then
  ISO_ROOTFS_PATH="$(xorriso -indev "$SRC_ISO" -find / -type f -name 'airootfs.sfs' -- 2>/dev/null \
    | grep -E '/airootfs\.sfs$' | head -n1)" || true
  if [[ -n "$ISO_ROOTFS_PATH" ]]; then
    ROOTFS_FORMAT="squashfs"
  fi
fi

# Fall back to SquashFS (.sqfs)
if [[ -z "$ISO_ROOTFS_PATH" ]]; then
  ISO_ROOTFS_PATH="$(xorriso -indev "$SRC_ISO" -find / -type f -name 'airootfs.sqfs' -- 2>/dev/null \
    | grep -E '/airootfs\.sqfs$' | head -n1)" || true
  if [[ -n "$ISO_ROOTFS_PATH" ]]; then
    ROOTFS_FORMAT="squashfs"
  fi
fi

if [[ -z "$ISO_ROOTFS_PATH" ]]; then
  echo "Error: Could not find live rootfs image in ISO." >&2
  echo "  Searched for: airootfs.erofs, airootfs.sfs, airootfs.sqfs" >&2
  exit 1
fi

echo "  Found: $ISO_ROOTFS_PATH (format: $ROOTFS_FORMAT)"

# ── Verify format-specific tools are available ──────────────────────────────

echo "[2/7] Checking $ROOTFS_FORMAT toolchain..."

if [[ "$ROOTFS_FORMAT" == "erofs" ]]; then
  for cmd in mkfs.erofs fsck.erofs; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "Error: EROFS rootfs detected but '$cmd' is not installed." >&2
      echo "  Install erofs-utils: sudo apt-get install erofs-utils" >&2
      exit 1
    fi
  done
elif [[ "$ROOTFS_FORMAT" == "squashfs" ]]; then
  for cmd in mksquashfs unsquashfs; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      echo "Error: SquashFS rootfs detected but '$cmd' is not installed." >&2
      echo "  Install squashfs-tools: sudo apt-get install squashfs-tools" >&2
      exit 1
    fi
  done
fi

# ── Extract the rootfs image from the ISO ───────────────────────────────────

ORIG_ROOTFS="$WORK_DIR/original_rootfs.img"

echo "[3/7] Extracting compressed live rootfs..."
xorriso -osirrox on -indev "$SRC_ISO" -extract "$ISO_ROOTFS_PATH" "$ORIG_ROOTFS" >/dev/null

# ── Extract rootfs image contents ───────────────────────────────────────────

echo "[4/7] Unpacking rootfs image ($ROOTFS_FORMAT)..."
mkdir -p "$ROOTFS_DIR"

if [[ "$ROOTFS_FORMAT" == "erofs" ]]; then
  fsck.erofs --extract="$ROOTFS_DIR" "$ORIG_ROOTFS" >/dev/null 2>&1
elif [[ "$ROOTFS_FORMAT" == "squashfs" ]]; then
  unsquashfs -f -d "$ROOTFS_DIR" "$ORIG_ROOTFS" >/dev/null
fi

# ── Inject Omarchy payload into the rootfs ──────────────────────────────────

echo "[5/7] Injecting Omarchy payload into rootfs..."
mkdir -p "$ROOTFS_DIR/opt/omarchy-setup"
rsync -rlt --delete "$SETUP_DIR/" "$ROOTFS_DIR/opt/omarchy-setup/"

# ── Create the live-shell autostart hook ────────────────────────────────────

mkdir -p "$ROOTFS_DIR/usr/local/bin"
cat > "$ROOTFS_DIR/usr/local/bin/omarchy-live-autostart" <<'AUTOSTART'
#!/usr/bin/env bash
set -Eeuo pipefail

OMARCHY_DIR="/opt/omarchy-setup"
if [[ ! -x "$OMARCHY_DIR/setup.sh" ]]; then
  exit 0
fi

echo
echo "Omarchy setup assistant is available."
read -r -n1 -p "Start Omarchy setup now? [Y/n] " ans
echo

if [[ -z "${ans:-}" || "$ans" =~ [Yy] ]]; then
  cd "$OMARCHY_DIR"
  chmod +x setup.sh
  exec ./setup.sh
fi
AUTOSTART
chmod +x "$ROOTFS_DIR/usr/local/bin/omarchy-live-autostart"

mkdir -p "$ROOTFS_DIR/root"
cat > "$ROOTFS_DIR/root/.bash_profile" <<'PROFILE'
# Arch Linux default
[[ -f ~/.bashrc ]] && . ~/.bashrc

# OMARCHY_AUTORUN_HOOK
if [[ -z "${OMARCHY_AUTORUN_DONE:-}" && -x /usr/local/bin/omarchy-live-autostart ]]; then
  if [[ -t 0 && "$(tty 2>/dev/null || true)" == "/dev/tty1" ]]; then
    export OMARCHY_AUTORUN_DONE=1
    /usr/local/bin/omarchy-live-autostart
  fi
fi
PROFILE

# ── Set correct permissions ─────────────────────────────────────────────────

chmod 0755 "$ROOTFS_DIR/usr/local/bin/omarchy-live-autostart"
chmod 0755 "$ROOTFS_DIR/opt/omarchy-setup/setup.sh" 2>/dev/null || true

# ── Repack the rootfs image in its original format ──────────────────────────

NEW_ROOTFS="$WORK_DIR/new_rootfs.img"

echo "[6/7] Repacking rootfs image ($ROOTFS_FORMAT)..."

if [[ "$ROOTFS_FORMAT" == "erofs" ]]; then
  mkfs.erofs -zlz4hc "$NEW_ROOTFS" "$ROOTFS_DIR" >/dev/null 2>&1
elif [[ "$ROOTFS_FORMAT" == "squashfs" ]]; then
  mksquashfs "$ROOTFS_DIR" "$NEW_ROOTFS" -comp xz -b 1M -all-root -noappend >/dev/null
fi

# ── Rebuild the ISO ─────────────────────────────────────────────────────────

echo "[7/7] Rebuilding customized ISO image..."
rm -f "$OUT_ISO"
xorriso -indev "$SRC_ISO" -outdev "$OUT_ISO" \
  -boot_image any replay \
  -map "$NEW_ROOTFS" "$ISO_ROOTFS_PATH" >/dev/null

echo ""
echo "Customized ISO created: $OUT_ISO"
echo "SHA256: $(sha256sum "$OUT_ISO" | cut -d' ' -f1)"
