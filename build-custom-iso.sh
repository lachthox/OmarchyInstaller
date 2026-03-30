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

# ── Build the overlay staging directory ─────────────────────────────────────
# Contains only our injected files — not the full rootfs.

echo "[3/6] Preparing Omarchy payload..."

STAGING_DIR="$WORK_DIR/staging"
mkdir -p "$STAGING_DIR/opt/omarchy-setup"
rsync -rlt --delete "$SETUP_DIR/" "$STAGING_DIR/opt/omarchy-setup/"

# Strip Windows CRLF line endings from all shell scripts to avoid
# invisible \r bytes leaking into generated config files at runtime.
find "$STAGING_DIR/opt/omarchy-setup" -type f -name '*.sh' -exec sed -i 's/\r$//' {} +

# ── Create the live-shell autostart hook ────────────────────────────────────

mkdir -p "$STAGING_DIR/usr/local/bin"
PAYLOAD_AUTOSTART="$STAGING_DIR/opt/omarchy-setup/hooks/live-autostart.sh"

if [[ -f "$PAYLOAD_AUTOSTART" ]]; then
  cp "$PAYLOAD_AUTOSTART" "$STAGING_DIR/usr/local/bin/omarchy-live-autostart"
  chmod 0755 "$STAGING_DIR/usr/local/bin/omarchy-live-autostart"
else
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
  chmod 0755 "$STAGING_DIR/usr/local/bin/omarchy-live-autostart"
fi

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

cat > "$STAGING_DIR/root/.zprofile" <<'PROFILE'
# OMARCHY_AUTORUN_HOOK
if [[ -z "${OMARCHY_AUTORUN_DONE:-}" && -x /usr/local/bin/omarchy-live-autostart ]]; then
  if [[ -t 0 && "$(tty 2>/dev/null || true)" == "/dev/tty1" ]]; then
    export OMARCHY_AUTORUN_DONE=1
    /usr/local/bin/omarchy-live-autostart
  fi
fi
PROFILE

# ── Set correct permissions on staging files ────────────────────────────────

chmod 0755 "$STAGING_DIR/usr/local/bin/omarchy-live-autostart"
chmod 0755 "$STAGING_DIR/opt/omarchy-setup/setup.sh" 2>/dev/null || true

ensure_nmtui_in_rootfs() {
  local rootfs="$1"

  if [[ -x "$rootfs/usr/bin/nmtui" ]]; then
    echo "  nmtui already present in live rootfs."
    return 0
  fi

  if [[ ! -x "$rootfs/usr/bin/pacman" ]]; then
    echo "Warning: pacman not found in extracted rootfs; cannot install NetworkManager. Continuing with iwctl fallback." >&2
    return 0
  fi

  echo "  Installing NetworkManager (includes nmtui) into live rootfs..."

  mkdir -p "$rootfs/proc" "$rootfs/sys" "$rootfs/dev" "$rootfs/run" "$rootfs/etc"
  cp -fL /etc/resolv.conf "$rootfs/etc/resolv.conf" 2>/dev/null || true

  mount --bind /dev "$rootfs/dev"
  mount --bind /run "$rootfs/run"
  mount -t proc proc "$rootfs/proc"
  mount -t sysfs sys "$rootfs/sys"

  local install_rc=0
  local cache_mounted=0
  mkdir -p "$rootfs/var/cache/pacman/pkg"
  if mount -t tmpfs -o size=512m tmpfs "$rootfs/var/cache/pacman/pkg"; then
    cache_mounted=1
  else
    echo "Warning: could not mount tmpfs for pacman cache; continuing with directory cache." >&2
  fi

  chroot "$rootfs" /usr/bin/bash -lc '
    set -f
    mkdir -p /var/cache/pacman/pkg
    if grep -Eq "^[#[:space:]]*DownloadUser[[:space:]]*=" /etc/pacman.conf; then
      sed -Ei "s|^[#[:space:]]*DownloadUser[[:space:]]*=.*|DownloadUser = root|" /etc/pacman.conf
    else
      printf "\nDownloadUser = root\n" >> /etc/pacman.conf
    fi

    if grep -Eq "^[[:space:]]*CheckSpace" /etc/pacman.conf; then
      sed -Ei "s|^[[:space:]]*CheckSpace|# CheckSpace|" /etc/pacman.conf
    fi

    if [[ ! -d /etc/pacman.d/gnupg || ! -w /etc/pacman.d/gnupg ]]; then
      rm -rf /etc/pacman.d/gnupg || true
      mkdir -p -m 700 /etc/pacman.d/gnupg
    fi

    pacman-key --init >/dev/null 2>&1 || true
    pacman-key --populate archlinux >/dev/null 2>&1 || true

    rm -f /usr/share/licenses/gcc-libs/RUNTIME.LIBRARY.EXCEPTION || true
    find /usr/share/locale -type f -path "*/LC_MESSAGES/libstdc++.mo" -delete 2>/dev/null || true

    pacman -Sy --noconfirm --needed \
      --overwrite "/usr/lib/libgcc*" \
      --overwrite "/usr/lib/libstdc++*" \
      --overwrite "/usr/share/licenses/gcc-libs/*" \
      --overwrite "/usr/share/locale/*/LC_MESSAGES/libstdc++.mo" \
      --cachedir /var/cache/pacman/pkg \
      archlinux-keyring networkmanager || {
      cp /etc/pacman.conf /tmp/pacman.nosig.conf
      if grep -Eq "^[[:space:]]*SigLevel[[:space:]]*=" /tmp/pacman.nosig.conf; then
        sed -Ei "s|^[[:space:]]*SigLevel[[:space:]]*=.*|SigLevel = Never|" /tmp/pacman.nosig.conf
      else
        printf "\nSigLevel = Never\n" >> /tmp/pacman.nosig.conf
      fi

      if grep -Eq "^[[:space:]]*CheckSpace" /tmp/pacman.nosig.conf; then
        sed -Ei "s|^[[:space:]]*CheckSpace|# CheckSpace|" /tmp/pacman.nosig.conf
      fi

      pacman -Sy --config /tmp/pacman.nosig.conf --noconfirm --needed \
        --overwrite "/usr/lib/libgcc*" \
        --overwrite "/usr/lib/libstdc++*" \
        --overwrite "/usr/share/licenses/gcc-libs/*" \
        --overwrite "/usr/share/locale/*/LC_MESSAGES/libstdc++.mo" \
        --cachedir /var/cache/pacman/pkg \
        archlinux-keyring networkmanager
    }
  ' || install_rc=$?

  if [[ "$install_rc" -eq 0 ]]; then
    chroot "$rootfs" /usr/bin/bash -lc 'systemctl enable NetworkManager.service >/dev/null 2>&1 || true' || true
  fi

  if [[ "$cache_mounted" -eq 1 ]]; then
    umount -R "$rootfs/var/cache/pacman/pkg" 2>/dev/null || umount -l "$rootfs/var/cache/pacman/pkg" 2>/dev/null || true
  fi
  umount -R "$rootfs/sys" 2>/dev/null || umount -l "$rootfs/sys" 2>/dev/null || true
  umount -R "$rootfs/proc" 2>/dev/null || umount -l "$rootfs/proc" 2>/dev/null || true
  umount -R "$rootfs/run" 2>/dev/null || umount -l "$rootfs/run" 2>/dev/null || true
  umount -R "$rootfs/dev" 2>/dev/null || umount -l "$rootfs/dev" 2>/dev/null || true

  if [[ "$install_rc" -ne 0 ]]; then
    echo "Warning: Failed to install NetworkManager in live rootfs. Continuing with iwctl fallback." >&2
    return 0
  fi

  if [[ ! -x "$rootfs/usr/bin/nmtui" ]]; then
    echo "Warning: NetworkManager install completed but nmtui binary is missing. Continuing with iwctl fallback." >&2
    return 0
  fi

  echo "  NetworkManager/nmtui installed successfully."
}

# ── Repack the rootfs image ────────────────────────────────────────────────
# Both SquashFS and EROFS use full extract-modify-repack to avoid
# mksquashfs append-mode issues with overlapping directory trees.

NEW_ROOTFS="$WORK_DIR/new_rootfs.img"

echo "[4/6] Repacking rootfs image ($ROOTFS_FORMAT)..."

if [[ "$ROOTFS_FORMAT" == "squashfs" ]]; then
  echo "  Extracting SquashFS rootfs (this may take a while)..."
  mkdir -p "$ROOTFS_DIR"
  unsquashfs -d "$ROOTFS_DIR" -f "$ORIG_ROOTFS" >/dev/null

  # Overlay staged files into the extracted rootfs
  rsync -rlt "$STAGING_DIR/" "$ROOTFS_DIR/"

  ensure_nmtui_in_rootfs "$ROOTFS_DIR"

  echo "  Repacking SquashFS rootfs..."
  mksquashfs "$ROOTFS_DIR" "$NEW_ROOTFS" -comp xz -b 1M -all-root -noappend >/dev/null

elif [[ "$ROOTFS_FORMAT" == "erofs" ]]; then
  # EROFS doesn't support appending — full extract, inject, repack.
  echo "  Extracting EROFS rootfs (this may take a while)..."
  mkdir -p "$ROOTFS_DIR"
  fsck.erofs --extract="$ROOTFS_DIR" "$ORIG_ROOTFS" 2>&1 || {
    echo "Error: fsck.erofs extraction failed. Trying dump.erofs fallback..." >&2
    if command -v dump.erofs >/dev/null 2>&1; then
      dump.erofs --extract="$ROOTFS_DIR" "$ORIG_ROOTFS" 2>&1
    else
      echo "Error: Could not extract EROFS image." >&2
      exit 1
    fi
  }

  # Overlay staged files into the extracted rootfs
  rsync -rlt "$STAGING_DIR/" "$ROOTFS_DIR/"

  ensure_nmtui_in_rootfs "$ROOTFS_DIR"

  echo "  Repacking EROFS rootfs..."
  mkfs.erofs -zlz4hc "$NEW_ROOTFS" "$ROOTFS_DIR" >/dev/null 2>&1
fi

echo "  Original rootfs: $(du -sh "$ORIG_ROOTFS" | cut -f1)"
echo "  New rootfs:      $(du -sh "$NEW_ROOTFS" | cut -f1)"

# ── Rebuild the ISO ─────────────────────────────────────────────────────────

echo "[5/6] Rebuilding customized ISO image..."
rm -f "$OUT_ISO"
xorriso -indev "$SRC_ISO" -outdev "$OUT_ISO" \
  -boot_image any replay \
  -map "$NEW_ROOTFS" "$ISO_ROOTFS_PATH" >/dev/null

echo ""
echo "Customized ISO created: $OUT_ISO"
ISO_SIZE=$(stat -c%s "$OUT_ISO" 2>/dev/null || stat -f%z "$OUT_ISO" 2>/dev/null || echo 0)
echo "Size: $(du -sh "$OUT_ISO" | cut -f1) ($ISO_SIZE bytes)"
echo "SHA256: $(sha256sum "$OUT_ISO" | cut -d' ' -f1)"

# Warn if over GitHub's 2 GiB release asset limit
if [[ "$ISO_SIZE" -gt 2147483648 ]]; then
  echo "WARNING: ISO exceeds GitHub Release 2 GiB asset limit ($ISO_SIZE bytes)." >&2
fi
