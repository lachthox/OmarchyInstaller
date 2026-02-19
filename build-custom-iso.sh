#!/usr/bin/env bash
# build-custom-iso.sh — Build a customized Arch ISO with omarchy-setup baked in.
#
# This script runs natively on Linux (e.g. in CI or on any workstation).
# It injects the omarchy-setup directory into the Arch live squashfs and
# installs a login hook that auto-prompts to run setup.sh on first boot.
#
# Usage:
#   ./build-custom-iso.sh <source-iso> <setup-dir> <output-iso>
#
# Requirements: xorriso, squashfs-tools (mksquashfs), rsync
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

# ── Dependency check ────────────────────────────────────────────────────────

for cmd in xorriso mksquashfs rsync; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Error: Required tool '$cmd' is not installed." >&2
    exit 1
  fi
done

# ── Work directory ──────────────────────────────────────────────────────────

WORK_DIR="$(mktemp -d)"
trap 'rm -rf "$WORK_DIR"' EXIT

ORIG_SFS="$WORK_DIR/original_airootfs.sfs"
NEW_SFS="$WORK_DIR/new_airootfs.sfs"
STAGING_DIR="$WORK_DIR/staging"

# ── Locate live rootfs squashfs inside the ISO ──────────────────────────────

echo "[1/6] Locating live rootfs in source ISO..."

ISO_SFS_PATH="$(xorriso -indev "$SRC_ISO" -find / -type f -name 'airootfs.sfs' -- 2>/dev/null \
  | grep -E '/airootfs\.sfs$' | head -n1)" || true

if [[ -z "$ISO_SFS_PATH" ]]; then
  ISO_SFS_PATH="$(xorriso -indev "$SRC_ISO" -find / -type f -name 'airootfs.sqfs' -- 2>/dev/null \
    | grep -E '/airootfs\.sqfs$' | head -n1)" || true
fi

if [[ -z "$ISO_SFS_PATH" ]]; then
  echo "Error: Could not find live rootfs squashfs (airootfs.sfs or .sqfs) in ISO." >&2
  exit 1
fi

echo "  Found: $ISO_SFS_PATH"

# ── Extract the squashfs from the ISO ───────────────────────────────────────

echo "[2/6] Extracting compressed live rootfs..."
xorriso -osirrox on -indev "$SRC_ISO" -extract "$ISO_SFS_PATH" "$ORIG_SFS" >/dev/null

# ── Build the overlay staging directory ─────────────────────────────────────

echo "[3/6] Preparing Omarchy payload (append-only overlay)..."
rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR/opt/omarchy-setup"
rsync -rlt --delete "$SETUP_DIR/" "$STAGING_DIR/opt/omarchy-setup/"

# ── Create the live-shell autostart hook ────────────────────────────────────

echo "[4/6] Installing live-shell autostart hook..."
mkdir -p "$STAGING_DIR/usr/local/bin"
cat > "$STAGING_DIR/usr/local/bin/omarchy-live-autostart" <<'AUTOSTART'
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
chmod +x "$STAGING_DIR/usr/local/bin/omarchy-live-autostart"

mkdir -p "$STAGING_DIR/root"
cat > "$STAGING_DIR/root/.bash_profile" <<'PROFILE'
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

# ── Repack squashfs (append-only — fast, no full rootfs extraction) ────────

echo "[5/6] Repacking squashfs with payload..."

PSEUDO_FILE="$WORK_DIR/pseudo-defs.txt"
cat > "$PSEUDO_FILE" <<'PSEUDO'
/usr/local/bin/omarchy-live-autostart m 0755
/opt/omarchy-setup/setup.sh m 0755
PSEUDO

cp "$ORIG_SFS" "$NEW_SFS"
mksquashfs "$STAGING_DIR" "$NEW_SFS" -comp xz -b 1M -all-root -pf "$PSEUDO_FILE" >/dev/null

# ── Rebuild the ISO ────────────────────────────────────────────────────────

echo "[6/6] Rebuilding customized ISO image..."
rm -f "$OUT_ISO"
xorriso -indev "$SRC_ISO" -outdev "$OUT_ISO" \
  -boot_image any replay \
  -map "$NEW_SFS" "$ISO_SFS_PATH" >/dev/null

echo ""
echo "Customized ISO created: $OUT_ISO"
echo "SHA256: $(sha256sum "$OUT_ISO" | cut -d' ' -f1)"
