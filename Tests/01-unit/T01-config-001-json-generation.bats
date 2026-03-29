#!/usr/bin/env bats
# T01-config-001-json-generation.bats
# Unit tests for generate_archinstall_config.
#
# Strategy: source setup.sh (minus the main invocation), call
# generate_archinstall_config with known arguments, then inspect the resulting
# JSON file with grep (structure) and python3 (deep structural assertions).
# No disk access, no root, no network.

setup() {
  load '../07-fixtures/assert'
  load '../07-fixtures/source-setup'
  CONFIG_PATH=""  # ensure prepare_config_path always creates a fresh file
}

teardown() {
  # Remove the temp config file created during the test
  if [[ -n "${CONFIG_PATH:-}" && -f "${CONFIG_PATH:-}" ]]; then
    rm -f "$CONFIG_PATH"
  fi
}

# ---------------------------------------------------------------------------
# Helper: call generate_archinstall_config with standard test arguments.
# ---------------------------------------------------------------------------
_call_generate() {
  generate_archinstall_config \
    "/dev/sda" \
    "/dev/sda1" \
    "/dev/sda2" \
    "test-host" \
    "alice" \
    "s3cr3t" \
    "enc-s3cr3t" \
    "America/New_York" \
    "systemd-boot" \
    "us" \
    "intel-ucode"
}

# ---------------------------------------------------------------------------
# Helper: run a python3 verification script against CONFIG_PATH.
# Pass the python3 source as stdin (heredoc at call site).
# ---------------------------------------------------------------------------
_py_check() {
  python3 - "$CONFIG_PATH"
}

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@test "generate_archinstall_config: creates a config file" {
  _call_generate
  [ -f "$CONFIG_PATH" ]
}

@test "generate_archinstall_config: disk device path present in JSON" {
  _call_generate
  run grep -q '"device": "/dev/sda"' "$CONFIG_PATH"
  assert_success
}

@test "generate_archinstall_config: EFI partition dev_name present" {
  _call_generate
  run grep -q '"dev_name": "/dev/sda1"' "$CONFIG_PATH"
  assert_success
}

@test "generate_archinstall_config: root partition dev_name present" {
  _call_generate
  run grep -q '"dev_name": "/dev/sda2"' "$CONFIG_PATH"
  assert_success
}

@test "generate_archinstall_config: EFI mountpoint is /boot" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
parts = d['disk_config']['device_modifications'][0]['partitions']
efi = next(p for p in parts if p['dev_name'] == '/dev/sda1')
assert efi['mountpoint'] == '/boot', f"EFI mountpoint: expected /boot, got {efi['mountpoint']}"
PYEOF
}

@test "generate_archinstall_config: root partition fs_type is btrfs" {
  _call_generate
  run grep -q '"fs_type": "btrfs"' "$CONFIG_PATH"
  assert_success
}

@test "generate_archinstall_config: all five btrfs subvolumes present" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
parts = d['disk_config']['device_modifications'][0]['partitions']
root = next(p for p in parts if p['dev_name'] == '/dev/sda2')
sv_names = [s['name'] for s in root['btrfs']['subvolumes']]
for expected in ['@', '@home', '@log', '@pkg', '@snapshots']:
    assert expected in sv_names, f"subvolume '{expected}' missing; got {sv_names}"
PYEOF
}

@test "generate_archinstall_config: btrfs subvolume mountpoints are correct" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
parts = d['disk_config']['device_modifications'][0]['partitions']
root = next(p for p in parts if p['dev_name'] == '/dev/sda2')
sv_map = {s['name']: s['mountpoint'] for s in root['btrfs']['subvolumes']}
assert sv_map['@'] == '/', f"@ mountpoint wrong: {sv_map['@']}"
assert sv_map['@home'] == '/home', f"@home mountpoint wrong: {sv_map['@home']}"
assert sv_map['@log'] == '/var/log', f"@log mountpoint wrong: {sv_map['@log']}"
assert sv_map['@pkg'] == '/var/cache/pacman/pkg', f"@pkg wrong: {sv_map['@pkg']}"
assert sv_map['@snapshots'] == '/.snapshots', f"@snapshots wrong: {sv_map['@snapshots']}"
PYEOF
}

@test "generate_archinstall_config: root partition has encrypted=true" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
parts = d['disk_config']['device_modifications'][0]['partitions']
root = next(p for p in parts if p['dev_name'] == '/dev/sda2')
assert root.get('encrypted') is True, f"encrypted flag wrong: {root.get('encrypted')}"
PYEOF
}

@test "generate_archinstall_config: root partition encryption_type is luks2" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
parts = d['disk_config']['device_modifications'][0]['partitions']
root = next(p for p in parts if p['dev_name'] == '/dev/sda2')
assert root.get('encryption_type') == 'luks2', f"encryption_type: {root.get('encryption_type')}"
PYEOF
}

@test "generate_archinstall_config: base package list is complete" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
pkgs = d['packages']
required = [
    'base', 'base-devel', 'linux-firmware', 'git', 'vim',
    'btrfs-progs', 'sudo', 'networkmanager', 'wpa_supplicant',
]
missing = [p for p in required if p not in pkgs]
assert not missing, f"Missing packages: {missing}"
PYEOF
}

@test "generate_archinstall_config: ucode package included when provided" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert 'intel-ucode' in d['packages'], f"intel-ucode missing; packages={d['packages']}"
PYEOF
}

@test "generate_archinstall_config: no ucode package when arg is empty" {
  generate_archinstall_config \
    "/dev/sda" "/dev/sda1" "/dev/sda2" \
    "test-host" "alice" "s3cr3t" "enc" \
    "UTC" "grub" "us" ""
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
ucode = [p for p in d['packages'] if 'ucode' in p]
assert not ucode, f"Unexpected ucode packages: {ucode}"
PYEOF
}

@test "generate_archinstall_config: hostname written correctly" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['hostname'] == 'test-host', f"hostname: expected 'test-host', got '{d['hostname']}'"
PYEOF
}

@test "generate_archinstall_config: username in users array" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
usernames = [u['username'] for u in d['users']]
assert 'alice' in usernames, f"alice not found; users={usernames}"
PYEOF
}

@test "generate_archinstall_config: user has is_superuser=true" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
u = next(u for u in d['users'] if u['username'] == 'alice')
assert u['is_superuser'] is True, f"is_superuser wrong: {u['is_superuser']}"
PYEOF
}

@test "generate_archinstall_config: timezone written correctly" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['timezone'] == 'America/New_York', f"timezone: {d['timezone']}"
PYEOF
}

@test "generate_archinstall_config: bootloader written correctly" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
bl = d['bootloader_config']['bootloader']
assert bl == 'systemd-boot', f"bootloader: expected 'systemd-boot', got '{bl}'"
PYEOF
}

@test "generate_archinstall_config: output is valid JSON" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
json.load(open(sys.argv[1]))  # raises ValueError on malformed JSON
PYEOF
}

@test "generate_archinstall_config: backslash in values produces valid JSON" {
  CONFIG_PATH=""
  generate_archinstall_config \
    "/dev/sda" "/dev/sda1" "/dev/sda2" \
    'host\nwith\backslash' "alice" 's3\cr3t' 'enc\pass' \
    "UTC" "grub" "us" ""
  _py_check <<'PYEOF'
import json, sys
json.load(open(sys.argv[1]))  # must not raise
PYEOF
}

@test "generate_archinstall_config: double-quote in values produces valid JSON" {
  CONFIG_PATH=""
  generate_archinstall_config \
    "/dev/sda" "/dev/sda1" "/dev/sda2" \
    'host"name"' "alice" 'pass"word' 'enc"pass' \
    "UTC" "grub" "us" ""
  _py_check <<'PYEOF'
import json, sys
json.load(open(sys.argv[1]))  # must not raise
PYEOF
}

@test "generate_archinstall_config: network_config type is nm" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert d['network_config']['type'] == 'nm', f"network type: {d['network_config']['type']}"
PYEOF
}

@test "generate_archinstall_config: kernels list contains linux" {
  _call_generate
  _py_check <<'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
assert 'linux' in d['kernels'], f"kernels: {d['kernels']}"
PYEOF
}
