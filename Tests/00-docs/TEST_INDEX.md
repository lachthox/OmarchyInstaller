# TEST_INDEX — OmarchyInstaller Bats Test Inventory

> Auto-maintained: add a row for every new `.bats` file.  
> Columns: **ID** · **Phase** · **Area** · **Priority** · **Status** · **Description** · **Script**

## Legend

- Phase: `01`=unit, `02`=component
- Priority: `P1` critical · `P2` high · `P3` normal
- Status: `active` · `wip` · `skip`

---

## Unit tests — Phase 01

| ID | Phase | Area | Priority | Status | Description | Script |
|---|---|---|---|---|---|---|
| T01-CFG-001 | 01 | config | P1 | active | generate_archinstall_config writes a file | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-002 | 01 | config | P1 | active | generated JSON contains correct disk path | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-003 | 01 | config | P1 | active | generated JSON contains correct EFI partition | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-004 | 01 | config | P1 | active | generated JSON contains correct root partition | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-005 | 01 | config | P1 | active | EFI partition mountpoint is /boot | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-006 | 01 | config | P1 | active | root partition fs_type is btrfs | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-007 | 01 | config | P1 | active | all five btrfs subvolumes present | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-008 | 01 | config | P1 | active | root partition has encrypted=true, encryption_type=luks2 | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-009 | 01 | config | P1 | active | base package list is complete | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-010 | 01 | config | P1 | active | ucode package included when ucode_pkg arg is non-empty | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-011 | 01 | config | P2 | active | no ucode package when ucode_pkg arg is empty | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-012 | 01 | config | P1 | active | hostname written correctly | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-013 | 01 | config | P1 | active | username in users array with is_superuser=true | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-014 | 01 | config | P1 | active | timezone written correctly | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-015 | 01 | config | P1 | active | bootloader written correctly | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-016 | 01 | config | P1 | active | output passes JSON parse (python3 json.load) | `01-unit/T01-config-001-json-generation.bats` |
| T01-CFG-017 | 01 | config | P2 | active | special chars in values produce valid JSON | `01-unit/T01-config-001-json-generation.bats` |
| T01-STR-001 | 01 | string | P1 | active | normalize_hostname: uppercase lowercased | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-002 | 01 | string | P1 | active | normalize_hostname: spaces become hyphens | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-003 | 01 | string | P1 | active | normalize_hostname: dots replaced with hyphens | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-004 | 01 | string | P1 | active | normalize_hostname: consecutive specials collapsed | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-005 | 01 | string | P1 | active | normalize_hostname: leading/trailing hyphens stripped | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-006 | 01 | string | P1 | active | normalize_hostname: empty string returns omarchy-host | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-007 | 01 | string | P2 | active | normalize_hostname: valid hostname passes through unchanged | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-008 | 01 | string | P2 | active | normalize_hostname: all-hyphens input returns omarchy-host | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-009 | 01 | string | P1 | active | validate_username: valid lowercase name accepted | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-010 | 01 | string | P1 | active | validate_username: name with numbers accepted | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-011 | 01 | string | P2 | active | validate_username: name starting with underscore accepted | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-012 | 01 | string | P2 | active | validate_username: name with hyphen accepted | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-013 | 01 | string | P1 | active | validate_username: empty string rejected | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-014 | 01 | string | P1 | active | validate_username: uppercase rejected | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-015 | 01 | string | P1 | active | validate_username: starts with digit rejected | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-016 | 01 | string | P1 | active | validate_username: space in name rejected | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-017 | 01 | string | P1 | active | validate_username: @ symbol rejected | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-018 | 01 | string | P1 | active | validate_username: leading hyphen rejected | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-019 | 01 | string | P1 | active | json_escape: plain string unchanged | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-020 | 01 | string | P1 | active | json_escape: backslash doubled | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-021 | 01 | string | P1 | active | json_escape: double-quote escaped | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-022 | 01 | string | P1 | active | json_escape: newline replaced with \n | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-023 | 01 | string | P1 | active | json_escape: carriage return replaced with \r | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-024 | 01 | string | P1 | active | json_escape: tab replaced with \t | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-025 | 01 | string | P2 | active | json_escape: multiple special chars in one pass | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-026 | 01 | string | P2 | active | cpu_ucode_pkg: GenuineIntel → intel-ucode (fixture) | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-027 | 01 | string | P2 | active | cpu_ucode_pkg: AuthenticAMD → amd-ucode (fixture) | `01-unit/T01-string-001-pure-functions.bats` |
| T01-STR-028 | 01 | string | P3 | active | cpu_ucode_pkg: unknown vendor → empty string (fixture) | `01-unit/T01-string-001-pure-functions.bats` |

## Component tests — Phase 02

| ID | Phase | Area | Priority | Status | Description | Script |
|---|---|---|---|---|---|---|
| T02-DSK-001 | 02 | disk | P1 | active | collect_disks: single disk parsed to name\|size\|model | `02-component/T02-disk-001-collect-disks.bats` |
| T02-DSK-002 | 02 | disk | P1 | active | collect_disks: NAME field extracted | `02-component/T02-disk-001-collect-disks.bats` |
| T02-DSK-003 | 02 | disk | P1 | active | collect_disks: SIZE field extracted | `02-component/T02-disk-001-collect-disks.bats` |
| T02-DSK-004 | 02 | disk | P1 | active | collect_disks: MODEL field extracted | `02-component/T02-disk-001-collect-disks.bats` |
| T02-DSK-005 | 02 | disk | P1 | active | collect_disks: partition entries (type=part) are filtered | `02-component/T02-disk-001-collect-disks.bats` |
| T02-DSK-006 | 02 | disk | P2 | active | collect_disks: multiple disks produce multiple output lines | `02-component/T02-disk-001-collect-disks.bats` |
| T02-DSK-007 | 02 | disk | P2 | active | collect_disks: empty lsblk output produces no output | `02-component/T02-disk-001-collect-disks.bats` |
| T02-DSK-008 | 02 | disk | P2 | active | collect_disks: empty model field produces trailing pipe | `02-component/T02-disk-001-collect-disks.bats` |
| T02-EFI-001 | 02 | disk | P1 | active | find_efi_partition: detects EFI by PARTTYPE UUID (mixed case) | `02-component/T02-disk-002-efi-detection.bats` |
| T02-EFI-002 | 02 | disk | P1 | active | find_efi_partition: detects EFI by PARTTYPE UUID (uppercase) | `02-component/T02-disk-002-efi-detection.bats` |
| T02-EFI-003 | 02 | disk | P1 | active | find_efi_partition: fallback — vfat + /boot mountpoint | `02-component/T02-disk-002-efi-detection.bats` |
| T02-EFI-004 | 02 | disk | P1 | active | find_efi_partition: fallback — vfat + /boot/efi mountpoint | `02-component/T02-disk-002-efi-detection.bats` |
| T02-EFI-005 | 02 | disk | P2 | active | find_efi_partition: no EFI partition → empty output | `02-component/T02-disk-002-efi-detection.bats` |
| T02-EFI-006 | 02 | disk | P2 | active | find_efi_partition: non-EFI partitions are ignored | `02-component/T02-disk-002-efi-detection.bats` |
