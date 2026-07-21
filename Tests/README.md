# OmarchyInstaller Test Suite

Bats-based tests retained only for useful shell helper behavior. The obsolete
`generate_archinstall_config` Bats suite was removed: the Python engine's strict
contract tests plus `rebuild/tools/validate_archinstall_upstream.py` now feed the
generated config and credentials through the pinned archinstall 4.4 parser.

## Quick-start

```bash
# From omarchy-setup/
bats Tests/01-unit/
bats Tests/02-component/
# Or run everything:
bats Tests/01-unit/ Tests/02-component/
```

## Layout

```
Tests/
├── 00-docs/           Test inventory and documentation
│   └── TEST_INDEX.md
├── 01-unit/           Fast, isolated unit tests (no disk, no root)
├── 02-component/      Component tests with mocked system commands
├── 07-fixtures/       Shared helpers, stubs, cpuinfo fixtures
│   ├── assert.bash         Minimal assert helpers (no deps)
│   ├── load-mocks.bash     Prepends mock-commands/ to PATH
│   ├── source-setup.bash   Sources setup.sh without running main
│   ├── intel-cpuinfo.txt   /proc/cpuinfo fixture — GenuineIntel
│   ├── amd-cpuinfo.txt     /proc/cpuinfo fixture — AuthenticAMD
│   └── mock-commands/      Stub executables for lsblk, sgdisk, etc.
└── 09-reports/        Captured run artifacts (git-ignored content)
```

## File naming

`T{phase}-{area}-{seq}-{slug}.bats`

- **phase**: two-digit folder number (`01`, `02`)
- **area**: short label (`config`, `string`, `disk`)
- **seq**: three-digit sequence per area (`001`, `002`)
- **slug**: concise behaviour description

## Mock command stubs

Stubs read environment variables to control output and exit code:

| Variable | Used by | Default |
|---|---|---|
| `MOCK_LSBLK_OUTPUT` | `lsblk` (generic) | *(empty)* |
| `MOCK_LSBLK_PARTTYPE_OUTPUT` | `lsblk` when args contain `PARTTYPE` | *(empty)* |
| `MOCK_LSBLK_FSTYPE_OUTPUT` | `lsblk` when args contain `MOUNTPOINT` | *(empty)* |
| `MOCK_SGDISK_OUTPUT` | `sgdisk` | *(empty)* |
| `MOCK_EXIT_CODE` | all stubs | `0` |

## Dependencies

- `bats` ≥ 1.2
- `python3` (for JSON structural assertions in unit tests)
- `awk`, `sed`, `tr` (standard POSIX utils — present on Arch live ISO)
