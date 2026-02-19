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
ORIG_ROOTFS="$WORK_DIR/original_rootfs.img"

# ── Locate and extract live rootfs image from the ISO ───────────────────────
# Modern Arch ISOs (2022+) use EROFS; older ones use SquashFS.
# We try direct extraction from known paths rather than xorriso -find,
# which has unreliable output behaviour across versions.

echo "[1/6] Locating and extracting live rootfs from source ISO..."

ROOTFS_FORMAT=""
ISO_ROOTFS_PATH=""

# Known Arch Linux rootfs paths in order of preference
CANDIDATES=(
  "/arch/x86_64/airootfs.erofs:erofs"
  "/arch/x86_64/airootfs.sfs:squashfs"
  "/arch/x86_64/airootfs.sqfs:squashfs"
)

for entry in "${CANDIDATES[@]}"; do
  cpath="${entry%%:*}"
  cfmt="${entry##*:}"
  echo "  Trying $cpath ..."
  if xorriso -osirrox on -indev "$SRC_ISO" -extract "$cpath" "$ORIG_ROOTFS" 2>/dev/null; then
    if [[ -f "$ORIG_ROOTFS" && -s "$ORIG_ROOTFS" ]]; then
      ISO_ROOTFS_PATH="$cpath"
      ROOTFS_FORMAT="$cfmt"
      echo "  Found: $ISO_ROOTFS_PATH (format: $ROOTFS_FORMAT)"
      break
    fi
    rm -f "$ORIG_ROOTFS"
  fi
done

# If known paths failed, do a full listing and search
if [[ -z "$ISO_ROOTFS_PATH" ]]; then
  echo "  Known paths not found — scanning full ISO listing..."
  FULL_LISTING="$(xorriso -indev "$SRC_ISO" -find / -type f 2>&1 || true)"
  echo "  Files in ISO (filtered):"
  echo "$FULL_LISTING" | grep -i 'airootfs\|rootfs\|\.erofs\|\.sfs\|\.sqfs' || echo "    (none matching)"

  for pattern in 'airootfs\.erofs' 'airootfs\.sfs' 'airootfs\.sqfs'; do
    MATCH="$(echo "$FULL_LISTING" | grep -E "/$pattern\$" | head -n1)" || true
    if [[ -n "$MATCH" ]]; then
      # Clean up any xorriso prefix noise (e.g. "'/path'" -> /path)
      MATCH="$(echo "$MATCH" | sed "s/^[^/]*//" | tr -d "'")"
      if xorriso -osirrox on -indev "$SRC_ISO" -extract "$MATCH" "$ORIG_ROOTFS" 2>/dev/null; then
        if [[ -f "$ORIG_ROOTFS" && -s "$ORIG_ROOTFS" ]]; then
          ISO_ROOTFS_PATH="$MATCH"
          case "$pattern" in
            *erofs*) ROOTFS_FORMAT="erofs" ;;
            *)       ROOTFS_FORMAT="squashfs" ;;
          esac
          echo "  Found via scan: $ISO_ROOTFS_PATH (format: $ROOTFS_FORMAT)"
          break
        fi
        rm -f "$ORIG_ROOTFS"
      fi
    fi
  done
fi

if [[ -z "$ISO_ROOTFS_PATH" ]]; then
  echo "Error: Could not find live rootfs image in ISO." >&2
  echo "  Searched known paths and scanned ISO listing." >&2
  echo "  Full ISO listing for debugging:" >&2
  xorriso -indev "$SRC_ISO" -find / -type f 2>&1 | head -50 >&2 || true
  exit 1
fi

# ── Verify format-specific tools are available ──────────────────────────────

echo "[2/6] Checking $ROOTFS_FORMAT toolchain..."

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

# ── Extract rootfs image contents ────────────────────────────────────────────

echo "[3/6] Unpacking rootfs image ($ROOTFS_FORMAT)..."
mkdir -p "$ROOTFS_DIR"

if [[ "$ROOTFS_FORMAT" == "erofs" ]]; then
  fsck.erofs --extract="$ROOTFS_DIR" "$ORIG_ROOTFS" 2>&1 || {
    echo "Error: fsck.erofs extraction failed. Trying dump.erofs fallback..." >&2
    if command -v dump.erofs >/dev/null 2>&1; then
      dump.erofs --extract="$ROOTFS_DIR" "$ORIG_ROOTFS" 2>&1
    else
      echo "Error: Could not extract EROFS image." >&2
      exit 1
    fi
  }
elif [[ "$ROOTFS_FORMAT" == "squashfs" ]]; then
  unsquashfs -f -d "$ROOTFS_DIR" "$ORIG_ROOTFS" >/dev/null
fi

# ── Inject Omarchy payload into the rootfs ──────────────────────────────────

echo "[4/6] Injecting Omarchy payload into rootfs..."
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

echo "[5/6] Repacking rootfs image ($ROOTFS_FORMAT)..."

if [[ "$ROOTFS_FORMAT" == "erofs" ]]; then
  mkfs.erofs -zlz4hc "$NEW_ROOTFS" "$ROOTFS_DIR" >/dev/null 2>&1
elif [[ "$ROOTFS_FORMAT" == "squashfs" ]]; then
  mksquashfs "$ROOTFS_DIR" "$NEW_ROOTFS" -comp xz -b 1M -all-root -noappend >/dev/null
fi

# ── Rebuild the ISO ─────────────────────────────────────────────────────────

echo "[6/6] Rebuilding customized ISO image..."
rm -f "$OUT_ISO"
xorriso -indev "$SRC_ISO" -outdev "$OUT_ISO" \
  -boot_image any replay \
  -map "$NEW_ROOTFS" "$ISO_ROOTFS_PATH" >/dev/null

echo ""
echo "Customized ISO created: $OUT_ISO"
echo "SHA256: $(sha256sum "$OUT_ISO" | cut -d' ' -f1)"
