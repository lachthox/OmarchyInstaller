# OmarchyInstaller Rebuild Specification (Definitive Architecture)
## GitHub Actions + Ventoy CLI + Windows Python TUI + Arch Live Python TUI + Safe Omarchy Handoff

> **Purpose of this document**  
> This is the **authoritative rebuild specification** for the `OmarchyInstaller` repo.  
> It is intended to be used in **VSCode with Copilot** to rebuild the repo under a new architecture with as little ambiguity as possible.  
> Treat this document as the source of truth for:
>
> - architecture
> - ownership boundaries
> - release/build flow
> - installer responsibilities
> - boot policy
> - Windows protection policy
> - Ventoy handling
> - Omarchy handoff timing
> - supply-chain safety checks
> - implementation order
>
> If this document assigns a responsibility to a layer, that responsibility must remain in that layer unless a clearly documented technical reason requires otherwise.  
> If this document says a workflow must abort in an unsafe state, it must abort.  
> Do not improvise around safety-critical decisions.

---

# 0. Executive Summary

This project is being rebuilt into a **four-layer system**.

## Layer 0 — Repository Build and Release Layer
GitHub Actions in this repo are the **base level of the entire workflow**.

They are responsible for:
- building the customized Arch ISO
- building the packaged Windows EXE
- producing version manifests
- publishing release artifacts
- automatically rebuilding when relevant source or packaging changes occur

This is the first layer and must be explicitly represented in the architecture.

## Layer 1 — Windows Preparation Layer
A **Windows Python TUI**, packaged as a standalone `.exe`, prepares the machine for dual boot safely.

It owns:
- Windows safety checks
- Secure Boot / BitLocker / Fast Startup handling
- Windows safety backup creation
- partition shrink
- Ventoy USB preparation using **Ventoy CLI**, like the original repo
- copying the customized Arch ISO onto the Ventoy USB
- writing `plan.json`
- writing optional Wi-Fi handoff data
- determining where backups are stored
- validating versions and upstream assumptions before reboot

## Layer 2 — Arch Live Installation Layer
A **customized Arch ISO** boots via **Ventoy** and launches a **Python TUI** in the live environment.

It owns:
- locating the Ventoy handoff files
- validating the real machine against the Windows-generated install plan
- network connection
- partition creation in prepared free space
- `archinstall`
- Limine and boot policy enforcement
- Windows preservation validation
- staging the Omarchy handoff

## Layer 3 — Omarchy Handoff and Ongoing Protection Layer
After Arch is installed and booted successfully:
- Omarchy runs once through a wrapper
- boot state is revalidated and normalized afterward
- ongoing lightweight boot checks keep the system healthy
- upstream Omarchy bootstrap location drift is detected and surfaced to reduce supply-chain surprises

---

# 1. What Exists Today and What Must Be Preserved

The rebuild must stay aligned with the current repo’s proven concepts.

## 1.1 Existing repo concepts to preserve

### A. GitHub Actions already rebuild the custom Arch ISO
The current repo already has a GitHub Actions workflow that downloads the stock Arch ISO, customizes it, and publishes a release artifact.

**Preserve that build model.**

### B. The Windows helper already uses a Ventoy CLI and ISO copy workflow
The current Windows-side flow is built around Ventoy, not raw one-shot USB writing.

**Preserve that user model.**

### C. The customized live environment currently auto-prompts the Arch-side installer
Today that Arch-side installer is `setup.sh`.

**Preserve the live auto-start idea, but replace the Bash-heavy control flow with Python.**

### D. The current repo expects Omarchy to be run after reboot
The existing repo tells the user to run Omarchy after Arch installation.

**Preserve the timing concept, but automate and guard it.**

---

# 2. Absolute Design Principles

These are non-negotiable.

## 2.1 Python is the orchestration language
Python is the primary language for:
- UI
- state
- validation
- config generation
- release and update checks
- supply-chain checks
- flow control
- logging
- compatibility checks
- boot health logic

Do not reintroduce giant Bash orchestration flows.

## 2.2 Native OS tools perform system actions
Python must orchestrate native tools rather than replace them.

Use native tools for:
- partitioning
- formatting
- mounting
- boot entry changes
- EFI operations
- network configuration
- bootloader work

### Rule
Python decides **what** to do.  
Native system tools do **the actual operation**.

## 2.3 Omarchy is not the system owner
Omarchy must be treated as:

> **a post-install customization layer**

Omarchy must not own:
- partitioning
- target-disk selection
- EFI ownership
- dual-boot logic
- Windows preservation
- default boot policy

Those responsibilities belong to **our installer**.

## 2.4 Windows safety is the highest priority
Assume the most realistic severe failure is:

> **Windows becomes difficult or impossible to boot because of EFI or boot drift**

—not necessarily data loss.

Protect:
- EFI partition contents
- Windows Boot Manager
- BCD
- WinRE
- fallback firmware bootability

## 2.5 Ventoy is the official USB transport model
The USB model is:

> **Ventoy USB + customized Arch ISO file stored on it + machine-specific handoff files stored alongside it on the same writable filesystem**

Do not design around:
- raw `dd`
- raw Rufus single-image assumptions
- a dedicated config partition as a requirement
- a second helper USB

## 2.6 The final installed system must remain clean
The final Omarchy install must not be polluted with:
- installer runtime junk
- temp configs
- temp Wi-Fi secrets
- temp logs not intended to persist
- random helper assets

Every artifact must explicitly belong to one of:
- CI/build only
- Windows prep only
- Ventoy USB only
- live ISO only
- temporary target staging
- final installed system required

## 2.7 Safety-first beats convenience
If there is a choice between:
- convenience
- speed
- cleverness
- lower friction

and

- deterministic behavior
- recoverability
- explicit validation
- safe abort behavior

choose deterministic recoverable behavior every time.

---

# 3. Complete End-to-End Workflow

This is the definitive intended workflow.

```text
Repository change
  ↓
GitHub Actions rebuild custom Arch ISO + Windows EXE + manifests
  ↓
User runs latest OmarchyInstaller.exe
  ↓
Windows Python TUI validates machine
  ↓
Windows Python TUI creates safety backups
  ↓
Windows Python TUI prepares Ventoy USB using Ventoy CLI
  ↓
Windows Python TUI copies latest custom Arch ISO onto Ventoy USB
  ↓
Windows Python TUI writes plan.json + optional wifi.json + backup metadata
  ↓
User reboots and selects the custom Arch ISO from Ventoy
  ↓
Customized Arch live environment boots
  ↓
Python live installer auto-starts
  ↓
Live installer locates handoff files on Ventoy USB
  ↓
Live installer validates the real machine against plan.json
  ↓
Live installer configures networking
  ↓
Live installer creates Linux partition only in prepared free space
  ↓
Live installer runs archinstall with controlled options
  ↓
Live installer installs and normalizes Limine and verifies Windows preservation
  ↓
Live installer plants first-boot Omarchy wrapper into target system
  ↓
User reboots into installed Arch
  ↓
User logs in
  ↓
Omarchy wrapper performs upstream-location integrity and health check
  ↓
Omarchy wrapper runs Omarchy installer
  ↓
Post-Omarchy normalization runs
  ↓
Boot guardian keeps setup healthy over time
```

---

# 4. Rebuild Execution Strategy

This rebuild is large enough that it must begin in a controlled containment area inside the repo.

## 4.1 Mandatory starting approach
The best way to begin this rebuild is to create a:

```text
rebuild/
```

folder within the repository root.

This folder is the staging area for the new architecture.

### Purpose of `rebuild/`
It exists to:
- keep the new architecture contained while the old repo still exists
- prevent destructive cross-contamination between legacy files and the rebuild
- let Copilot work against an organized target structure instead of mixed old/new code
- make incremental migration easier
- allow the project to be built in clear, isolated steps

### Hard rule
Do not begin the rebuild by immediately rewriting the entire legacy repo in place.

Start inside `rebuild/` first.

## 4.2 What lives in `rebuild/`
At the beginning of the rebuild, place the new architecture under something like:

```text
rebuild/
  docs/
  installer/
  tools/
  assets/
  requirements.txt
  pyproject.toml
```

The exact structure can mirror the final intended structure, but it must remain clearly isolated from legacy code until the new system is coherent enough to replace it.

## 4.3 Step-by-step guidance rule
Each stage of the rebuild must contain enough current, explicit detail that Copilot can build that stage without guessing.

That means:
- every stage should define what files are being created
- every stage should define which layer owns the behavior
- every stage should define success and failure conditions
- every stage should define inputs and outputs
- every stage should define whether the code is temporary, final, or transitional

### Hard rule
Do not leave major implementation gaps as “figure this out later” if Copilot is expected to act on that stage.

If a step is intended for Copilot implementation, it must be described with enough detail that it can be built deterministically.

---

# 5. Layer 0 — Repository Build and Release Layer

This is the first layer of the architecture and must be modeled explicitly.

## 5.1 Role of GitHub Actions
GitHub Actions remain responsible for:
- customized Arch ISO build
- Windows EXE build
- publishing release artifacts
- publishing update manifests
- automated rebuilds on relevant changes

This is required.

## 5.2 Required pipelines
The repo must contain CI/CD for:

### 5.2.1 Arch ISO build pipeline
Build the customized Arch ISO with:
- injected Python runtime
- injected live installer app
- injected live auto-start
- required packages
- manifests and version metadata

### 5.2.2 Windows EXE build pipeline
Build the Windows Python TUI as a standalone EXE with:
- PyInstaller
- stable packaging inputs
- version stamping

### 5.2.3 Release pipeline
Publish:
- latest ISO
- latest EXE
- checksums
- release manifest
- compatibility metadata

## 5.3 Auto rebuild triggers
The repo must automatically rebuild relevant artifacts when code or packaging changes.

### 5.3.1 ISO rebuild triggers
Any change to these areas must trigger a new ISO build:
- live installer Python source
- ISO payload files
- ISO build scripts
- Linux-side assets
- startup and entrypoint logic
- Linux runtime dependencies
- shared schema and compatibility code used by live installer
- GitHub workflow files for ISO build

### 5.3.2 Windows EXE rebuild triggers
Any change to these areas must trigger a new EXE build:
- Windows TUI Python source
- Windows platform modules
- shared schema and version code
- requirements and packaging config
- PyInstaller config or spec
- GitHub workflow files for EXE build

### 5.3.3 Full rebuild triggers
Any change to shared compatibility, versioning, or schema logic should rebuild:
- ISO
- EXE

because both sides consume the same contract.

## 5.4 Build orchestration philosophy
GitHub Actions are the runner.

Python scripts should own most build logic.

### Correct model
- GitHub Actions invokes Python build scripts
- Python build scripts decide:
  - payload preparation
  - manifest creation
  - compatibility stamping
  - artifact naming
  - release metadata generation

Do not bury important build logic in giant YAML blobs.

## 5.5 Required build outputs
Each successful releasable build must produce:

### ISO outputs
- customized Arch ISO
- checksum file
- ISO version manifest

### Windows outputs
- `OmarchyInstaller.exe`
- checksum file
- EXE version manifest

### Shared outputs
- build version
- commit SHA
- schema version
- compatibility metadata
- Omarchy upstream bootstrap expectation metadata

## 5.6 Required compatibility manifest
The repo must publish a machine-readable manifest containing at least:
- build version
- commit SHA
- schema version
- ISO version
- EXE version
- compatibility rules
- expected Omarchy bootstrap location or locations

This should be JSON.

## 5.7 Windows EXE packaging tool
Use **PyInstaller**. This is mandatory.

The user must not need Python installed.

## 5.8 Release freshness rule
When repo code changes in relevant areas, CI must rebuild and publish fresh artifacts so that the latest Windows binary release is always up to date.

This is required.

---

# 6. Layer 1 — Windows Python TUI

## 6.1 Delivery format
The Windows-side app must be distributed as:

**OmarchyInstaller.exe**

No user Python dependency is allowed.

## 6.2 Purpose
The Windows app is the Windows-safe preparation layer.

It must own:
- machine validation
- safety backup
- partition shrink
- Ventoy USB creation/preparation using Ventoy CLI
- ISO placement onto Ventoy USB
- plan generation
- optional Wi-Fi handoff generation
- upstream and version validation
- user-facing abort and warning logic

It must not attempt to perform the real Linux installation from Windows.

## 6.3 Mandatory Windows-side checks
The Windows app must do all of the following.

### 6.3.1 Administrative privilege validation
Verify the app is running elevated.

If not:
- show clear error
- offer relaunch as admin if feasible
- block further progress

### 6.3.2 Platform sanity validation
Verify:
- supported Windows version
- UEFI boot mode
- GPT system disk
- no obviously unsupported or ambiguous baseline layout

If unsupported:
- abort
- explain why

### 6.3.3 Secure Boot handling
This must follow the requested policy exactly.

#### Default
If our install path supports Secure Boot:
- leave Secure Boot enabled

#### If Secure Boot is incompatible with the chosen path
The Windows TUI must present a clear user choice:
1. Disable Secure Boot if required
2. Continue with Secure Boot as experimental or unsupported if feasible
3. Cancel

#### Additional requirement
The app must be capable of:
- detecting Secure Boot state
- guiding the user to disable it if needed

#### Hard rule
Never silently disable Secure Boot.

### 6.3.4 BitLocker handling
Detect BitLocker protection state.

If it is unsafe to proceed:
- explain the risk
- strongly recommend or require suspension
- abort if unresolved

### 6.3.5 Fast Startup handling
If Fast Startup is enabled:
- explain why it is unsafe
- offer to disable it
- block progress until resolved

### 6.3.6 WinRE validation
Verify Windows Recovery Environment status.

If unavailable or disabled in a risky context:
- warn strongly or abort

### 6.3.7 Disk and partition discovery
Identify:
- physical target disk
- EFI partition
- Windows partition
- recovery partition if present
- eventual free-space region

Capture stable metadata:
- disk serial
- disk model
- disk size
- GPT partition GUIDs
- partition sizes
- start and end sectors
- partition style

## 6.4 Windows safety backup system
This is required and must be deterministic.

### 6.4.1 Required backup set
Before risky operations, create:
- EFI backup
- BCD backup
- structured disk metadata backup

### 6.4.2 Backup storage priority logic
The user explicitly requested this behavior, so implement it exactly.

#### Preferred destination
If the Ventoy USB has enough space:
- store Windows backups on the Ventoy USB

#### Required behavior
The Windows TUI must:
1. estimate backup size
2. measure Ventoy USB free space
3. decide whether Ventoy storage is sufficient
4. if sufficient, store backups there
5. if insufficient, inform the user and require alternate backup destination selection

#### Alternate destinations
Allowed examples:
- local disk folder
- external drive
- alternate removable drive
- user-selected path

#### Verification
After backup:
- verify files exist
- verify expected structure exists
- abort on failure

### 6.4.3 Required backup contents
At minimum:

```text
windows-backup/
  efi-backup/
  bcd-backup
  disk-layout.json
  partition-map.json
  recovery-info.txt
```

## 6.5 Ventoy USB preparation (Windows side)
This must align with the current repo’s Ventoy CLI workflow.

### 6.5.1 Ventoy creation and preparation requirement
The Windows Python TUI must be responsible for creating and preparing the Ventoy USB using **Ventoy CLI**, the same way the original repo conceptually does.

This is mandatory.

The Windows app must own:
- locating Ventoy CLI
- installing or downloading it if that is part of policy
- executing it
- validating resulting Ventoy media is usable

### 6.5.2 Ventoy USB detection
The app must identify the intended Ventoy USB safely.

Do not trust:
- the last removable drive
- whatever appeared recently

Detection must be verified using:
- expected Ventoy structure
- writable filesystem
- expected target volume behavior

### 6.5.3 Ventoy USB validation
Before using it, verify:
- Ventoy medium exists
- filesystem is writable
- there is enough space for:
  - custom ISO
  - `plan.json`
  - optional `wifi.json`
  - optional backups and logs

If not valid:
- abort or ask the user to fix/select a valid device

### 6.5.4 ISO placement onto Ventoy USB
The Windows app must place the customized Arch ISO onto the Ventoy USB as a normal file.

Example location:

```text
<VENTOY_USB>\ISO\Omarchy-Arch-Installer.iso
```

The exact path may be configurable, but must be deterministic.

### 6.5.5 Handoff file placement onto Ventoy USB
The Windows app must write machine-specific handoff data to:

```text
<VENTOY_USB>\omarchy\
```

At minimum:
```text
plan.json
```

Optional:
```text
wifi.json
install.log
windows-backup-info.json
```

### 6.5.6 Required verification before reboot
Before telling the user to reboot, the Windows app must verify:
- ISO file exists on Ventoy USB
- `plan.json` exists
- required optional files exist if chosen
- files are readable

Abort if verification fails.

## 6.6 Partition preparation (Windows side)
This is safety-critical.

### 6.6.1 Required behavior
The Windows app must:
- shrink the Windows partition
- leave **unallocated space**
- record the exact resulting free-space range

The Windows app must not:
- create ext4
- create Linux filesystem structures
- create a LUKS container
- finish Linux layout from Windows

The Windows phase only reserves safe unallocated space.

### 6.6.2 Required recorded metadata
After shrink, record:
- disk serial
- disk size
- EFI partition GUID
- Windows partition GUID
- free-space start sector
- free-space end sector
- free-space size

This becomes part of `plan.json`.

## 6.7 Version and update behavior
The Windows app must check GitHub and release metadata for:
- latest EXE version
- latest ISO version
- manifest compatibility

The app must be able to detect:
- local EXE outdated
- Ventoy ISO outdated
- schema mismatch
- incompatible build pairings

It must warn or block as appropriate.

## 6.8 Omarchy bootstrap location and supply-chain health check (Windows side)
This is a required protective feature.

### 6.8.1 Goal
Detect if the expected Omarchy bootstrap or install script location changes unexpectedly.

This is to reduce the risk of:
- unnoticed upstream location change
- supply-chain confusion
- stale hardcoded bootstrap assumptions
- a bad actor taking advantage of location drift before it is noticed

### 6.8.2 Required health check model
The project must define an expected Omarchy bootstrap source contract in release metadata.

At minimum the health check should validate:
- expected bootstrap URL or entry path
- expected repository source
- expected bootstrap file location or locations
- whether those assumptions still match upstream expectations

### 6.8.3 Behavior if location or assumption changes
If the expected bootstrap location or upstream handoff pattern changes:
- notify the user
- flag it in release and manifest
- block or warn depending on severity
- surface clearly in logs and UI

This should be treated as a supply-chain health event, not a cosmetic difference.

---

# 7. `plan.json` — Definitive Handoff Contract

This is the machine-specific install contract between:
- Windows prep layer
- Arch live layer

It must be treated as a validated install plan, not arbitrary script instructions.

## 7.1 Core principle
Windows says:
> This is the exact machine state I prepared.

Arch says:
> I will verify this exact state before touching anything.

Only if the states match may Arch proceed.

## 7.2 Required schema contents
At minimum include:

### Meta
- schema version
- EXE version
- ISO version
- generation timestamp
- build and commit identifiers if desired

### Disk identity
- serial
- model
- size
- partition style

### EFI partition identity
- GUID or PARTUUID
- size
- filesystem
- start and end sector if useful

### Windows partition identity
- GUID or PARTUUID
- filesystem
- size
- label if useful

### Prepared free-space region
- start sector
- end sector
- size

### User choices
- username
- hostname
- timezone
- locale
- install preferences if exposed

### Network block
- optional SSID
- optional passphrase
- hidden flag
- auth type if needed

### Omarchy block
- expected repo
- expected branch or ref
- expected bootstrap assumption metadata if needed

## 7.3 Schema validation tool
Use **Pydantic** on both:
- Windows generation side
- Arch consumption side

## 7.4 Version compatibility rule
The live installer must validate:
- schema version
- EXE and plan producer version
- ISO version

If incompatible:
- abort
- explain why

---

# 8. Layer 2 — Custom Arch ISO

## 8.1 Purpose
The customized Arch ISO is the known-good live runtime.

It must contain:
- Python runtime
- live installer app
- UI framework
- required dependencies
- startup hooks

It must be bootable via Ventoy.

## 8.2 Keep the existing repack concept
The repo already rebuilds a custom Arch ISO.

Keep that model.

Do not replace it with a fundamentally different media creation strategy.

## 8.3 Required ISO contents
At minimum include:
- `python`
- live installer package and app files
- `textual`
- `rich`
- `pydantic`
- `networkmanager`
- `nmcli`
- `nmtui`
- `linux-firmware` if needed
- startup entrypoint

## 8.4 Live entrypoint
The existing repo auto-prompts `setup.sh`.

The new architecture must preserve auto-start but switch to Python.

Required live entrypoint:

```bash
python3 /opt/omarchy-installer/main.py
```

## 8.5 Runtime boundary
### The ISO contains
- installer runtime
- Python
- UI
- live tools

### The Ventoy USB contains
- machine-specific config
- logs
- backup metadata

### The final system contains
- only intentionally persisted assets

---

# 9. Layer 2 — Arch Live Installer

## 9.1 Purpose
The Arch live Python TUI owns:
- locating handoff files
- validating `plan.json`
- validating machine identity
- networking
- Arch install
- boot policy enforcement
- Omarchy handoff staging

## 9.2 Handoff discovery on Ventoy
At startup the live installer must:
1. locate the Ventoy USB or mounted storage
2. search for:

```text
omarchy/plan.json
```

3. validate that the file belongs to this installer and build context
4. load it only if safe

## 9.3 Anti-stale-plan rule
The live installer must not blindly consume the first `plan.json` it finds.

It must validate compatibility using:
- schema version
- build or ISO version
- optional timestamp sanity
- optional manifest linkage

This prevents stale handoff data from being used accidentally.

## 9.4 Disk validation rules
The live installer must validate:
- disk serial
- disk model and size
- EFI partition GUID or PARTUUID
- Windows partition GUID or PARTUUID
- free-space start and end sector range

### Hard rule
Do not trust:
- `/dev/sda`
- `/dev/nvme0n1`
- disk index
- partition number alone

Use stable identifiers.

### Failure behavior
Any mismatch or ambiguity:
- abort
- explain why
- do not guess

## 9.5 Required preflight summary
Before destructive actions, show a summary confirming:
- target disk
- EFI partition
- Windows partition
- prepared free-space region
- network state
- intended Linux layout
- intended bootloader policy
- intended Omarchy handoff mode

Only then allow continuation.

---

# 10. Network Strategy (Live Side)

Use the following order exactly:
1. Ethernet
2. Auto Wi-Fi from Windows handoff
3. Retry and rescan
4. Manual network selection in our UI
5. `nmtui`
6. USB tethering suggestion or fallback
7. Offline or abort path

Use:
- NetworkManager as primary
- `nmcli` for automation
- `nmtui` for fallback

---

# 11. Arch Installation Rules

## 11.1 Purpose
The live installer acts as an Arch install orchestrator. It is not Omarchy yet.

## 11.2 Required install behavior
The live installer must:
- create Linux partition only in exact prepared region
- format target filesystems
- mount under `/mnt`
- run `archinstall`
- produce a bootable Arch system
- preserve Windows bootability

## 11.3 Encryption policy
Follow Omarchy’s intended encrypted install posture.

Assume:
- encrypted Linux install is required or desirable
- a LUKS and Btrfs path should be used if that is Omarchy-compatible
- the user-visible flow must be deterministic and explicit

Do not improvise incompatible encryption layouts.

## 11.4 Bootloader policy
Use **Limine** as the default Linux boot path.

Windows Boot Manager must remain:
- intact
- chainloadable
- firmware-visible
- independently recoverable

Final intended model:

```text
UEFI → Limine → Omarchy / Windows
```

Emergency fallback:

```text
UEFI → Windows Boot Manager directly
```

Do not let Limine and Windows fight for ownership.

---

# 12. Windows Preservation (Live Side)

Before bootloader finalization, verify Windows boot assets still exist.

If Windows EFI assets are unexpectedly missing:
- abort
- do not continue

The installer must never invalidate the Windows boot path before Linux is known-good.

---

# 13. Layer 3 — Omarchy Handoff

## 13.1 Correct handoff timing
Omarchy must be launched only:
- after `archinstall`
- after reboot into installed Arch
- after user login

Do not run Omarchy:
- from Windows
- from WSL
- from the live ISO
- from a half-installed target

## 13.2 Omarchy wrapper model
Omarchy must be run through a wrapper that performs:

```text
pre_omarchy_checks
→ omarchy_install_location_health_check
→ run_omarchy
→ post_omarchy_boot_normalize
→ cleanup
```

## 13.3 Required Omarchy install-location health check
This is mandatory.

Before running Omarchy, the wrapper must validate the expected upstream install bootstrap assumptions.

At minimum it must check:
- expected bootstrap location or URL contract
- expected repository location assumption
- expected `boot.sh` and `install.sh` handoff model if applicable

If the location or structure has changed unexpectedly:
- notify clearly
- log it
- block or require confirmation depending on policy severity

## 13.4 Pre-Omarchy checks
Before Omarchy runs, verify:
- network availability
- boot assets still exist
- Limine still exists
- boot state is sane
- required first-boot conditions are met

## 13.5 Post-Omarchy normalization
After Omarchy runs, verify:
- Windows boot assets still exist
- Limine still exists
- boot order is still sane
- Windows is still chainloadable

If Omarchy changed something undesirable:
- restore intended boot policy

---

# 14. Layer 3 — Boot Guardian

## 14.1 Purpose
Prevent “worked at install time, broke later” boot drift.

Examples:
- Windows boot disappearing from menu
- Limine entry disappearing
- boot order silently changing
- EFI path drift

## 14.2 Required design
Implement a lightweight once-per-boot health check.

It should be:
- tiny
- deterministic
- low overhead
- not noisy when healthy

## 14.3 Implementation model
Use:
- Python script
- systemd oneshot service
- expected-state JSON

## 14.4 Required checks each boot
The guardian should verify at minimum:
1. EFI mount is valid
2. Limine files still exist
3. Windows boot files still exist
4. expected boot entries still exist
5. optional: Limine config still includes Windows entry

## 14.5 Required behavior model
### Healthy
- exit silently
- maybe log one status line

### Warning
- write warning flag
- optionally notify after login

### Critical
- write clear error
- offer repair path
- do not aggressively perform dangerous repairs automatically

## 14.6 Required commands
Provide at minimum:

```bash
omarchy-boot-check
omarchy-boot-repair
```

These should be stable, documented support tools.

---

# 15. Cleanup Strategy

This must be explicit and disciplined.

## 15.1 The final installed system must remain clean
Installer scaffolding must not linger unnecessarily in the final system.

## 15.2 Categorize all artifacts into one of these buckets

### A. Live ISO only
These exist only in the live environment.

Examples:
- Python installer app
- Textual runtime
- installer UI
- live helper scripts
- live diagnostics

These should not be copied into the final system unless intentionally required.

### B. Ventoy USB only
These stay on the Ventoy USB.

Examples:
- `plan.json`
- install logs
- backup metadata
- optional Wi-Fi handoff data

### C. Temporary target staging
These may temporarily exist under the target install during setup.

Examples:
- first-boot handoff files
- temp Omarchy wrapper state
- temp marker files

These must be tracked and removed when no longer needed.

### D. Final system required
These are the only things that should persist permanently.

Examples:
- Omarchy itself
- intended bootloader config
- intended network config if chosen
- stable guardian and repair tooling if intentionally installed

## 15.3 Required temp staging directory
If temporary target staging is needed, keep it all under one explicit directory, e.g.:

```text
/mnt/.installer-runtime/
```

This makes cleanup deterministic.

## 15.4 Cleanup must remove at minimum
- temporary `plan.json` copies on target
- temporary Wi-Fi handoff files on target
- temporary installer runtime directories
- temp logs not intended to persist
- first-boot helper files after successful completion

---

# 16. Python Stack

Use this stack unless there is a clearly justified reason to change it.

## 16.1 Runtime dependencies (required)
- `textual`
- `rich`
- `pydantic`

## 16.2 Optional runtime helpers
Possible additions:
- `typer`
- `psutil`

Do not add them unless they materially simplify implementation.

## 16.3 Dev-only dependencies
These should not necessarily be included in the live runtime.

Examples:
- `pytest`
- TUI testing tools
- snapshot helpers

## 16.4 Dependency discipline rule
Do not add random Python libraries for:
- partitioning
- Wi-Fi abstraction
- bootloader control
- system magic

Use Python for:
- UI
- validation
- structure
- orchestration

Use native tools for:
- system operations

---

# 17. Repo Structure (Target State)

Recommended rebuilt repo structure:

```text
OmarchyInstaller/
├─ rebuild/
│  ├─ README.md
│  ├─ docs/
│  ├─ installer/
│  ├─ tools/
│  ├─ assets/
│  ├─ requirements.txt
│  └─ pyproject.toml
├─ README.md
├─ pyproject.toml
├─ requirements.txt
├─ requirements-dev.txt
├─ tools/
│  ├─ build_iso.py
│  ├─ inject_payload.py
│  ├─ patch_iso.py
│  ├─ write_arch_payload.py
│  ├─ ventoy_media.py
│  └─ build_windows_exe.py
├─ installer/
│  ├─ app.py
│  ├─ main.py
│  ├─ constants.py
│  ├─ logging_setup.py
│  ├─ shared/
│  │  ├─ models.py
│  │  ├─ plan_schema.py
│  │  ├─ validation.py
│  │  ├─ disk_identity.py
│  │  ├─ network_models.py
│  │  ├─ versioning.py
│  │  └─ compatibility.py
│  ├─ ui/
│  │  ├─ screens/
│  │  │  ├─ welcome.py
│  │  │  ├─ compatibility.py
│  │  │  ├─ backup_windows.py
│  │  │  ├─ partition_prep.py
│  │  │  ├─ ventoy_usb.py
│  │  │  ├─ secure_boot.py
│  │  │  ├─ network.py
│  │  │  ├─ summary.py
│  │  │  ├─ confirm.py
│  │  │  ├─ live_preflight.py
│  │  │  ├─ live_network.py
│  │  │  ├─ live_install.py
│  │  │  ├─ live_finalize.py
│  │  │  └─ error_screen.py
│  │  └─ widgets/
│  ├─ platforms/
│  │  ├─ windows/
│  │  │  ├─ checks.py
│  │  │  ├─ backup.py
│  │  │  ├─ partitioning.py
│  │  │  ├─ wifi.py
│  │  │  ├─ usb.py
│  │  │  ├─ ventoy.py
│  │  │  ├─ secure_boot.py
│  │  │  ├─ disk_probe.py
│  │  │  ├─ bcd.py
│  │  │  ├─ updates.py
│  │  │  └─ bitlocker.py
│  │  ├─ linux_live/
│  │  │  ├─ disk_probe.py
│  │  │  ├─ matcher.py
│  │  │  ├─ ventoy_mount.py
│  │  │  ├─ network.py
│  │  │  ├─ partitioning.py
│  │  │  ├─ archinstall_runner.py
│  │  │  ├─ bootloader.py
│  │  │  ├─ omarchy_handoff.py
│  │  │  ├─ cleanup.py
│  │  │  └─ preflight.py
│  │  └─ installed_system/
│  │     ├─ boot_guardian.py
│  │     ├─ boot_repair.py
│  │     ├─ omarchy_wrapper.py
│  │     ├─ expected_state.py
│  │     └─ notifications.py
├─ assets/
│  ├─ systemd/
│  │  ├─ omarchy-firstboot.service
│  │  ├─ omarchy-boot-guardian.service
│  │  └─ omarchy-post-omarchy.service
│  ├─ scripts/
│  │  ├─ setup.sh
│  │  ├─ omarchy-firstboot.sh
│  │  ├─ omarchy-post-boot-normalize.sh
│  │  └─ omarchy-boot-repair.sh
│  └─ templates/
│     ├─ plan.template.json
│     ├─ expected_boot_state.json
│     └─ release_manifest.json
├─ iso/
│  ├─ payload/
│  │  └─ opt/
│  │     └─ omarchy-installer/
│  └─ startup/
├─ .github/
│  └─ workflows/
│     ├─ build-iso.yml
│     ├─ build-windows-exe.yml
│     └─ release.yml
└─ docs/
   ├─ architecture.md
   ├─ boot-protection.md
   ├─ plan-schema.md
   ├─ release-process.md
   └─ development-notes.md
```

---

# 18. Development Order (Mandatory Implementation Order)

Do not build this in a random order.

## Stage 0 — Create `rebuild/` containment area
Before beginning the massive migration, create the `rebuild/` directory and start the new implementation there.

This is the mandatory starting point.

## Stage 1 — Repo scaffold inside `rebuild/`
Create the new file and folder structure.

## Stage 2 — Shared schema and models
Implement:
- `plan_schema.py`
- shared models
- versioning logic
- compatibility logic

Each of these must be documented and explicit enough for Copilot to implement without guessing.

## Stage 3 — Windows platform layer
Implement:
- system checks
- disk probe
- backup logic
- BitLocker, Fast Startup, Secure Boot checks
- partition prep
- Ventoy detection and preparation using Ventoy CLI
- ISO placement
- Omarchy bootstrap location health check metadata handling

## Stage 4 — Windows TUI
Build:
- screens
- flow
- summary and confirmation
- error handling

## Stage 5 — Ventoy handoff generation
Implement:
- ISO placement
- `plan.json`
- backup destination logic
- Wi-Fi handoff

## Stage 6 — Arch live platform layer
Implement:
- Ventoy handoff discovery
- disk matcher
- Linux preflight
- network layer

## Stage 7 — Arch live TUI
Build:
- preflight UI
- network UI
- install confirmation UI
- install progress UI

## Stage 8 — Arch install orchestration
Implement:
- partition creation
- `archinstall` runner
- encryption handling
- bootloader handling

## Stage 9 — Omarchy handoff
Implement:
- first-boot wrapper
- pre and post checks
- Omarchy launch flow
- Omarchy install-location health check enforcement

## Stage 10 — Boot guardian
Implement:
- health check
- repair command
- expected-state logic

## Stage 11 — Cleanup logic
Implement:
- temp artifact cleanup
- post-install normalization

## Stage 12 — CI/CD
Implement:
- Windows EXE build
- ISO build
- release automation
- rebuild triggers on relevant source and packaging changes

### Guidance rule for every stage
Every stage above must contain enough up-to-date detail that Copilot can implement that stage deterministically.

Do not leave major gaps as vague future work if the stage is supposed to be implemented now.

---

# 19. Non-Negotiable Safety Abort Conditions

The installer must refuse to continue if any of the following are true:
- not running as admin in Windows phase
- unsupported boot mode or partition style
- BitLocker unsafe state
- Fast Startup enabled and unresolved
- WinRE unavailable in a risky state
- EFI backup failed
- BCD export failed
- insufficient backup storage with no valid alternate location
- Ventoy USB invalid or not writable
- ISO missing from Ventoy USB
- `plan.json` missing or invalid
- version mismatch or incompatibility
- disk or partition identity mismatch
- prepared free-space mismatch
- Windows boot files unexpectedly missing
- boot state cannot be validated safely
- Omarchy bootstrap location health check fails according to policy

If unsafe:
- abort cleanly
- explain why
- do not “try anyway”

---

# 20. Final Project Philosophy

This is the final intended mental model of the system:

- our installer owns the machine
- Omarchy owns the environment
- Ventoy is the transport
- Python is the brain
- GitHub Actions are the build foundation
- Windows safety is sacred

That is the architecture.

---

# 21. Copilot Implementation Checklist

Use this as the immediate execution checklist.

- [ ] Create `rebuild/` containment area
- [ ] Create repo scaffold inside `rebuild/`
- [ ] Add `pyproject.toml`
- [ ] Add `requirements.txt`
- [ ] Implement shared schema and models
- [ ] Implement Windows admin and platform checks
- [ ] Implement BitLocker, Fast Startup, and Secure Boot checks
- [ ] Implement Windows EFI and BCD backup logic
- [ ] Implement Windows disk metadata capture
- [ ] Implement Windows partition shrink flow
- [ ] Implement Ventoy CLI integration
- [ ] Implement Ventoy USB detection and verification
- [ ] Implement ISO placement and update logic
- [ ] Implement `plan.json` generation
- [ ] Implement optional Wi-Fi handoff generation
- [ ] Implement Omarchy bootstrap location health check metadata flow
- [ ] Implement Arch Ventoy handoff discovery
- [ ] Implement Arch disk and partition matcher
- [ ] Implement Arch preflight screen
- [ ] Implement Arch network flow
- [ ] Implement Arch partition creation and `archinstall` runner
- [ ] Implement Limine and Windows preservation logic
- [ ] Implement Omarchy first-boot wrapper
- [ ] Implement post-Omarchy normalization
- [ ] Implement boot guardian and repair command
- [ ] Implement cleanup logic
- [ ] Implement Windows EXE build pipeline
- [ ] Implement ISO build pipeline
- [ ] Implement release automation and rebuild triggers

---

# 22. Final Instruction to Copilot

When implementing this project:
- prefer small, testable modules
- avoid giant all-in-one scripts
- keep shell usage minimal and purpose-specific
- use Python as the orchestration layer
- preserve Windows safety as the highest priority
- keep Ventoy assumptions explicit and correct
- do not allow Omarchy to become the authority over boot strategy
- keep the final installed system clean
- do not introduce ambiguity where deterministic behavior is possible
- start the rebuild inside `rebuild/` and keep each stage well-contained
- ensure every stage has enough explicit detail to be implemented without guessing

If there is a choice between:
- simpler but less safe
- and slightly more work but deterministic and recoverable

choose deterministic and recoverable behavior.

That is the standard for this rebuild.

