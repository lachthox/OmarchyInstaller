# Arch + Omarchy Completion Remediation Plan

This document describes how to fix each currently known blocker that prevents a full end-to-end completion of:

1. Windows prep
2. Arch live install
3. Post-install Omarchy handoff

It is implementation-focused and maps each blocker to concrete code changes, acceptance criteria, and test coverage.

## Scope

This plan targets the rebuild Python path under `rebuild/`.
It does not require changing legacy production behavior in place unless explicitly called out as a fallback decision.

## Blocker Summary

| ID | Blocker | Severity | Primary Owners |
| --- | --- | --- | --- |
| B1 | Windows Python TUI does not write Ventoy handoff bundle (`ISO + plan.json`) | Critical | Layer 1 (`platforms/windows`) |
| B2 | Launcher defaults can end in Python-only completion without complete handoff behavior | High | Layer 0/1 (`tools/windows`, `platforms/windows`) |
| B3 | Live install path does not stage first-boot prerequisites (`install-success.json`, runtime assets) | Critical | Layer 2/3 (`platforms/linux_live`, `platforms/installed_system`) |
| B4 | Firstboot/boot-guardian service assets are not installed/enabled in target system | Critical | Layer 2/3 (`platforms/linux_live`, `assets/services`, `assets/scripts`) |
| B5 | Wi-Fi handoff exists in contract but is not wired into live network flow | Medium | Layer 2 (`platforms/linux_live`, `ui`) |

## Recommended Implementation Order

1. B1 first (no handoff means no valid config-mode path).
2. B3 and B4 second (without these, Omarchy handoff cannot start).
3. B2 third (make launcher behavior deterministic for rollout).
4. B5 fourth (quality and resilience improvement, not a hard blocker if ethernet exists).

## B1 Fix: Write Ventoy Handoff Bundle from Windows Python Flow

### Current State

- `WindowsPrepApp` validates backup/partition/Ventoy but does not stage payload files.
- `stage_ventoy_handoff_bundle(...)` already exists and can write:
  - ISO
  - `omarchy/plan.json`
  - optional `wifi.json`
  - optional log/backup metadata

### Root Cause

- Flow orchestration stops at "validated" status and exits before creating handoff artifacts.

### Required Changes

1. Add plan assembly in Windows flow.
File targets:
- `rebuild/installer/platforms/windows/flow.py`
- `rebuild/installer/platforms/windows/app.py`
- `rebuild/installer/platforms/windows/partition_prep.py` (reuse existing `apply_partition_metadata_to_plan` helper)

Implementation details:
- Create a helper that builds a valid `PlanContract` payload after successful:
  - compatibility checks
  - backup step
  - partition prep step
- Use live probe output (disk/EFI/windows/free-space identities) as source of truth.
- Include required compatibility fields:
  - schema version
  - producer/live minimum versions
  - `ventoy_handoff_path=omarchy/plan.json`

2. Persist bundle only after readiness checks pass.
File target:
- `rebuild/installer/platforms/windows/app.py`

Implementation details:
- In `action_continue_flow`, after readiness is true:
  - resolve validated Ventoy data root
  - call `stage_ventoy_handoff_bundle(...)`
  - include ISO path from `source_iso_path`
  - include backup metadata from backup result payload
  - include optional Wi-Fi payload if available
- Surface clear status and fail closed if write/verification fails.

3. Track payload result in UI state for summary and supportability.
File target:
- `rebuild/installer/platforms/windows/app.py`

Implementation details:
- Add field to keep `VentoyPayloadResult` summary.
- Display written files in summary/details stage.

### Acceptance Criteria

1. On successful Python Windows flow with configured Ventoy disk and ISO path, USB contains:
  - `/<iso-name>.iso` (or deterministic name)
  - `omarchy/plan.json`
  - optional sidecar files if provided
2. If payload write fails, flow exits blocked with actionable error.
3. Flow never reports "completed" without creating handoff artifacts.

### Tests

Unit tests (new):
- `rebuild/tests/test_windows_handoff_flow.py`:
  - success path writes bundle
  - missing ISO path blocks
  - invalid plan payload blocks
  - unreadable write verification blocks

Update existing tests:
- `rebuild/tests/test_windows_flow.py`:
  - include "continue_flow writes bundle" expectation.

## B2 Fix: Make Launcher Path Deterministic for Production

### Current State

- Launcher can run Python TUI and exit without forcing legacy handoff.
- This is valid for experimentation but ambiguous for production users when Python path is not fully complete.

### Root Cause

- Launch defaults prioritize flexibility over deterministic completion policy.

### Required Changes

1. Define policy mode in launcher.
File target:
- `rebuild/tools/windows/omarchy_installer_launcher.py`

Implementation details:
- Add explicit policy switch:
  - `python-only` (full rebuild path)
  - `python-then-legacy`
  - `legacy-only`
- Default should be environment-driven:
  - production/release: `python-then-legacy` until B1-B4 are fully shipped
  - dev: `python-only` allowed

2. Enforce policy at runtime.
File targets:
- `rebuild/tools/windows/omarchy_installer_launcher.py`
- `rebuild/tools/build_windows_exe.py`

Implementation details:
- Stamp selected default mode in build metadata manifest.
- Print mode in startup log for support diagnostics.

### Acceptance Criteria

1. Release EXE behavior is deterministic and documented.
2. Users cannot silently land in incomplete path due to default ambiguity.
3. CLI flags can still override in development/testing builds.

### Tests

Unit tests (new):
- `rebuild/tests/test_windows_launcher_modes.py`:
  - default mode resolution
  - per-flag override behavior
  - legacy handoff code path triggers correctly

## B3 Fix: Stage First-Boot Prerequisites from Live Install

### Current State

- Live installer performs partitioning and `archinstall`.
- It does not currently write the installed-system firstboot marker contract or stage required runtime root.

### Root Cause

- Post-install handoff wiring is not yet integrated into Layer 2 execution pipeline.

### Required Changes

1. Add post-install staging step after successful `archinstall`.
File target:
- `rebuild/installer/platforms/linux_live/install.py`

Implementation details:
- Introduce helper like `_stage_installed_system_runtime(mount_root, stage_root, ...)`.
- Required output on target system:
  - `/var/lib/omarchy/install/install-success.json`
  - `/opt/omarchy-setup/` runtime directory with:
    - `setup.sh`
    - `main.py`
    - `installer/` package
    - `requirements.txt`
    - `runtime-packages.txt`
    - `hooks/live-autostart.sh`
    - `hooks/firstboot-wrapper.sh`
    - `build-metadata.json`

2. Make marker payload explicit and versioned.
File target:
- `rebuild/installer/platforms/linux_live/install.py`

Implementation details:
- Include fields:
  - `schema_version`
  - `completed_at_utc`
  - disk identifiers
  - install mode (`ventoy-plan` or `standalone`)
  - archinstall config path/hash

3. Fail closed if post-install staging cannot complete.
File target:
- `rebuild/installer/platforms/linux_live/install.py`

Implementation details:
- If staging fails after successful archinstall:
  - return failure status
  - record detailed error in install log
  - do not report install completed

### Acceptance Criteria

1. After successful live install, firstboot prerequisites exist in target filesystem.
2. `run_firstboot_handoff` no longer blocks due to missing install marker or missing bootstrap root files.
3. Install log includes post-install staging actions.

### Tests

Unit tests (new):
- `rebuild/tests/test_linux_live_postinstall_staging.py`:
  - marker file written
  - runtime tree staged
  - failure behavior when write path unavailable

Integration test (new or scripted):
- Dry-run capable simulation that verifies staged tree layout contract.

## B4 Fix: Install and Enable Firstboot + Boot Guardian Services

### Current State

- Service templates and scripts exist in `rebuild/assets`.
- They are not yet installed/enabled inside target Arch system by the install pipeline.

### Root Cause

- Assets are packaged for ISO/build use but missing installed-system deployment hook.

### Required Changes

1. Copy service units and wrappers into target root.
File targets:
- `rebuild/installer/platforms/linux_live/install.py`
- `rebuild/assets/services/omarchy-firstboot.service`
- `rebuild/assets/services/boot-guardian.service`
- `rebuild/assets/scripts/firstboot-wrapper.sh`
- `rebuild/assets/scripts/omarchy-boot-check.sh`
- `rebuild/assets/scripts/omarchy-boot-repair.sh`
- `rebuild/assets/scripts/boot-guardian.sh`

Install destinations:
- `/etc/systemd/system/omarchy-firstboot.service`
- `/etc/systemd/system/boot-guardian.service`
- `/usr/local/bin/omarchy-firstboot-wrapper.sh`
- `/usr/local/bin/omarchy-boot-check`
- `/usr/local/bin/omarchy-boot-repair`
- `/usr/local/bin/omarchy-boot-guardian` (or current wrapper naming)

2. Enable services in target.
File target:
- `rebuild/installer/platforms/linux_live/install.py`

Implementation details:
- Use `arch-chroot /mnt systemctl enable omarchy-firstboot.service`
- Use `arch-chroot /mnt systemctl enable boot-guardian.service`
- Ensure executable permissions are set before enabling.

3. Seed boot guardian expected-state file.
File targets:
- `rebuild/installer/platforms/linux_live/install.py`
- `rebuild/installer/platforms/installed_system/boot_guardian_state.py`

Implementation details:
- Write `/var/lib/omarchy/boot/expected-state.json` from known install outputs.
- Include schema version and fallback boot labels.

### Acceptance Criteria

1. Installed system has service units and scripts at expected paths.
2. Both services are enabled in target systemd.
3. Boot guardian check command runs cleanly on first boot baseline.

### Tests

Unit tests:
- extend `rebuild/tests/test_installed_system_firstboot.py` for expected paths.
- add `rebuild/tests/test_linux_live_service_staging.py` for deployment behavior.

Integration checks:
- `arch-chroot` command execution stubs validate enable calls are made.

## B5 Fix: Wire Wi-Fi Handoff into Live Discovery and Network Resolution

### Current State

- Windows side can write `omarchy/wifi.json`.
- Linux network resolver accepts `wifi_handoff_profile`.
- Live UI snapshot currently calls resolver without supplying handoff profile.

### Root Cause

- Discovery currently validates and loads only `plan.json` for runtime state.

### Required Changes

1. Extend handoff discovery result to include optional Wi-Fi payload.
File target:
- `rebuild/installer/platforms/linux_live/discovery.py`

Implementation details:
- Add fields to `HandoffDiscoveryResult`:
  - `wifi_path: str | None`
  - `wifi_profile: dict[str, Any] | None`
- Load `omarchy/wifi.json` only when adjacent to validated `plan.json`.
- Treat invalid Wi-Fi payload as warning, not hard blocker for install.

2. Pass Wi-Fi profile into network resolution.
File target:
- `rebuild/installer/ui/screens.py`

Implementation details:
- In `collect_live_runtime_snapshot`, if handoff result has Wi-Fi profile:
  - call `resolve_network_connectivity(wifi_handoff_profile=...)`
- Keep current fallback order unchanged.

3. Mask sensitive values in UI/logging.
File targets:
- `rebuild/installer/ui/screens.py`
- `rebuild/installer/platforms/linux_live/network.py`

Implementation details:
- Never print passphrase in stage content or logs.
- Log only profile metadata (`ssid`, security type, interface name).

### Acceptance Criteria

1. Valid `wifi.json` is automatically consumed for live network bootstrap.
2. Invalid `wifi.json` does not crash install flow; falls back to current strategy.
3. No secret material is rendered in UI/log output.

### Tests

Unit tests (new):
- `rebuild/tests/test_linux_live_discovery_wifi.py`
- `rebuild/tests/test_linux_live_network_handoff.py`

## Cross-Cutting Guardrails

1. Keep fail-closed behavior for destructive operations.
2. Do not weaken identity matching or schema validation.
3. Preserve separate behavior for:
  - config-mode (`ventoy-plan`)
  - no-config standalone mode
4. Ensure status text in UI matches actual completion semantics.

## PR Split Recommendation

1. PR-A: B1 handoff bundle generation.
2. PR-B: B3 + B4 installed-system staging/services.
3. PR-C: B2 launcher policy and build defaults.
4. PR-D: B5 Wi-Fi handoff wiring.
5. PR-E: final integration tests and docs refresh.

## Final Verification Checklist

1. Windows Python flow writes and verifies `plan.json` + ISO on Ventoy.
2. Live ISO discovers validated plan and optional Wi-Fi profile.
3. Arch install succeeds in:
  - config-mode
  - no-config mode
4. Installed system contains:
  - install success marker
  - firstboot wrapper runtime
  - firstboot service enabled
  - boot guardian service enabled
  - boot guardian expected-state seeded
5. First boot runs Omarchy wrapper and creates completion marker.
6. Regression suite passes (`pytest` under `rebuild/tests`).
