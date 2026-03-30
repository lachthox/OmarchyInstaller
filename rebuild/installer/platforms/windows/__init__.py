"""Windows preparation platform modules."""

from .checks import run_windows_preflight
from .disk_probe import DiskProbeError, DiskProbeSnapshot, collect_disk_probe_snapshot
from .backup import BackupError, BackupResult, backup_boot_state, run_windows_backup_subsystem
from .partition_prep import (
    PartitionPrepError,
    PartitionPrepPolicy,
    PartitionPrepResult,
    PowerShellPartitionResizer,
    apply_partition_metadata_to_plan,
    prepare_unallocated_space,
)

__all__ = [
    "BackupError",
    "BackupResult",
    "DiskProbeError",
    "DiskProbeSnapshot",
    "PartitionPrepError",
    "PartitionPrepPolicy",
    "PartitionPrepResult",
    "PowerShellPartitionResizer",
    "apply_partition_metadata_to_plan",
    "backup_boot_state",
    "collect_disk_probe_snapshot",
    "prepare_unallocated_space",
    "run_windows_backup_subsystem",
    "run_windows_preflight",
]
