# Contributing

The only supported implementation is Python. Do not add compatibility launchers,
shell/PowerShell installer paths, independent publishing workflows, or runtime
logic in workflow YAML.

Before submitting a change:

```powershell
.\.venv\Scripts\python.exe -m pytest rebuild\tests -q
.\.venv\Scripts\python.exe -m ruff check rebuild
.\.venv\Scripts\python.exe -m mypy rebuild
.\.venv\Scripts\python.exe rebuild\tools\check_no_legacy_production_refs.py
```

On Linux, also run ShellCheck and `bats rebuild/tests-shell`. Safety-critical
disk, ESP, boot, backup, release, and state-machine changes require human review
and disposable VM evidence. Never test against real disks or firmware.

Keep changes within the ownership boundary in `rebuild/docs/ownership-map.md`.
Update finding status and evidence with the same change; do not mark a finding
verified from mocked or simulated results.
