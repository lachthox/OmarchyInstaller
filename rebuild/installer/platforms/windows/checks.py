"""Windows safety and preflight checks with deterministic gating."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
import os
import re
import subprocess
from typing import Protocol


class CheckStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    message: str
    value: str


@dataclass(frozen=True, slots=True)
class WindowsPreflightReport:
    checks: tuple[CheckResult, ...]
    can_proceed: bool

    @property
    def failures(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if check.status == CheckStatus.FAIL)

    @property
    def warnings(self) -> tuple[CheckResult, ...]:
        return tuple(check for check in self.checks if check.status == CheckStatus.WARN)

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["failures"] = [asdict(check) for check in self.failures]
        payload["warnings"] = [asdict(check) for check in self.warnings]
        return payload


class WindowsProbe(Protocol):
    """Probe interface to enable deterministic checks and test stubs."""

    def is_admin(self) -> bool: ...
    def windows_version(self) -> str: ...
    def boot_mode(self) -> str: ...
    def partition_style(self) -> str: ...
    def secure_boot_enabled(self) -> bool | None: ...
    def bitlocker_state(self) -> str: ...
    def fast_startup_enabled(self) -> bool | None: ...
    def winre_enabled(self) -> bool | None: ...


class PowerShellProbe:
    """Default probe implementation using native Windows commands."""

    def _run_ps(self, command: str) -> str:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    def _run_cmd(self, command: list[str]) -> str:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return ""
        return completed.stdout.strip()

    def _normalize_bitlocker_output(self, output: str) -> str:
        if not output:
            return "Unknown"
        normalized = output.strip()
        lowered = normalized.lower()

        if lowered in {"decrypting", "decryptioninprogress", "decryption in progress"}:
            return "Decrypting"
        if lowered in {"1", "on", "protectionon", "protection on"}:
            return "On"
        if lowered in {"0", "off", "protectionoff", "protection off"}:
            return "Off"

        decryption_match = re.search(r"Conversion\s+Status:\s*Decryption\s+In\s+Progress", output, re.IGNORECASE)
        if decryption_match:
            return "Decrypting"

        protection_match = re.search(r"Protection\s+Status:\s*(Protection\s+On|Protection\s+Off)", output, re.IGNORECASE)
        if protection_match and "off" in protection_match.group(1).lower():
            percentage_match = re.search(r"Percentage\s+Encrypted:\s*(\d+(\.\d+)?)%", output, re.IGNORECASE)
            if percentage_match:
                try:
                    percentage = float(percentage_match.group(1))
                    if percentage > 0:
                        return "Decrypting"
                except ValueError:
                    pass
        if protection_match:
            state = protection_match.group(1).lower()
            return "On" if "on" in state else "Off"

        decrypted_match = re.search(r"Conversion\s+Status:\s*Fully\s+Decrypted", output, re.IGNORECASE)
        if decrypted_match:
            return "Off"

        encrypted_match = re.search(r"Conversion\s+Status:\s*(Fully|Used Space Only)\s+Encrypted", output, re.IGNORECASE)
        if encrypted_match:
            return "On"

        return "Unknown"

    def is_admin(self) -> bool:
        output = self._run_ps(
            "[bool]([Security.Principal.WindowsPrincipal]"
            "[Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole("
            "[Security.Principal.WindowsBuiltInRole]::Administrator)"
        )
        return output.lower() == "true"

    def windows_version(self) -> str:
        return self._run_ps("(Get-CimInstance Win32_OperatingSystem).Version")

    def boot_mode(self) -> str:
        output = self._run_ps(
            "if (Test-Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\SecureBoot\\State') {'UEFI'} else {'Legacy'}"
        )
        return output or "Unknown"

    def partition_style(self) -> str:
        output = self._run_ps("(Get-Disk | Where-Object IsBoot -eq $true | Select-Object -First 1).PartitionStyle")
        return output or "Unknown"

    def secure_boot_enabled(self) -> bool | None:
        output = self._run_ps("try { Confirm-SecureBootUEFI } catch { '' }")
        if not output:
            return None
        lowered = output.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        return None

    def bitlocker_state(self) -> str:
        command = (
            "if (Get-Command Get-BitLockerVolume -ErrorAction SilentlyContinue) { "
            "$v = Get-BitLockerVolume -MountPoint $env:SystemDrive | Select-Object -First 1; "
            "if ($null -ne $v) { "
            "[PSCustomObject]@{ "
            "protection_status = [string]$v.ProtectionStatus; "
            "volume_status = [string]$v.VolumeStatus; "
            "encryption_percentage = [int]$v.EncryptionPercentage "
            "} | ConvertTo-Json -Compress "
            "} "
            "} else { '' }"
        )
        output = self._run_ps(command)
        if output:
            try:
                import json

                payload = json.loads(output)
                protection_status = str(payload.get("protection_status", "")).strip().lower()
                volume_status = str(payload.get("volume_status", "")).strip().lower()
                try:
                    encryption_percentage = int(payload.get("encryption_percentage", 0))
                except (TypeError, ValueError):
                    encryption_percentage = 0

                if "decryption" in volume_status:
                    return "Decrypting"
                if "fullydecrypted" in volume_status or "fully decrypted" in volume_status:
                    return "Off"
                if protection_status in {"0", "off", "protectionoff", "protection off"}:
                    if encryption_percentage > 0:
                        return "Decrypting"
                    return "Off"
                if protection_status in {"1", "on", "protectionon", "protection on"}:
                    return "On"
                if "encrypted" in volume_status or "encryption" in volume_status:
                    return "On"
            except Exception:
                normalized = self._normalize_bitlocker_output(output)
                if normalized != "Unknown":
                    return normalized

        system_drive = os.environ.get("SystemDrive", "C:")
        fallback_output = self._run_cmd(["manage-bde.exe", "-status", system_drive])
        return self._normalize_bitlocker_output(fallback_output)

    def fast_startup_enabled(self) -> bool | None:
        output = self._run_ps(
            "(Get-ItemProperty -Path 'HKLM:\\SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Power' "
            "-Name HiberbootEnabled -ErrorAction SilentlyContinue).HiberbootEnabled"
        )
        if output == "":
            return None
        if output.strip() == "1":
            return True
        if output.strip() == "0":
            return False
        return None

    def winre_enabled(self) -> bool | None:
        completed = subprocess.run(
            ["reagentc.exe", "/info"],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            return None
        match = re.search(r"Windows RE status:\s*(Enabled|Disabled)", completed.stdout, re.IGNORECASE)
        if not match:
            return None
        return match.group(1).lower() == "enabled"


def _check_admin(probe: WindowsProbe) -> CheckResult:
    value = "true" if probe.is_admin() else "false"
    if value == "true":
        return CheckResult("admin", CheckStatus.PASS, "Process has administrator privileges.", value)
    return CheckResult("admin", CheckStatus.FAIL, "Administrator privileges are required.", value)


def _check_windows_version(probe: WindowsProbe) -> CheckResult:
    version = probe.windows_version() or "unknown"
    major = 0
    try:
        major = int(version.split(".")[0])
    except (ValueError, IndexError):
        pass
    if major >= 10:
        return CheckResult("windows_version", CheckStatus.PASS, "Supported Windows version detected.", version)
    return CheckResult("windows_version", CheckStatus.FAIL, "Unsupported Windows version; Windows 10+ required.", version)


def _check_boot_mode(probe: WindowsProbe) -> CheckResult:
    mode = probe.boot_mode()
    if mode.upper() == "UEFI":
        return CheckResult("boot_mode", CheckStatus.PASS, "UEFI boot mode detected.", mode)
    return CheckResult("boot_mode", CheckStatus.FAIL, "UEFI boot mode is required.", mode)


def _check_partition_style(probe: WindowsProbe) -> CheckResult:
    style = probe.partition_style()
    if style.upper() == "GPT":
        return CheckResult("partition_style", CheckStatus.PASS, "GPT partition style detected.", style)
    return CheckResult("partition_style", CheckStatus.FAIL, "GPT partition style is required.", style)


def _check_secure_boot(probe: WindowsProbe) -> CheckResult:
    enabled = probe.secure_boot_enabled()
    if enabled is True:
        return CheckResult(
            "secure_boot",
            CheckStatus.FAIL,
            "Secure Boot is enabled; current Limine boot path requires Secure Boot to be disabled.",
            "true",
        )
    if enabled is False:
        return CheckResult("secure_boot", CheckStatus.PASS, "Secure Boot is disabled.", "false")
    return CheckResult("secure_boot", CheckStatus.WARN, "Secure Boot state could not be determined.", "unknown")


def _check_bitlocker(probe: WindowsProbe) -> CheckResult:
    state = probe.bitlocker_state()
    normalized = state.lower()
    if normalized in {"decrypting", "decryptioninprogress", "decryption in progress"}:
        return CheckResult(
            "bitlocker",
            CheckStatus.FAIL,
            "BitLocker decryption is in progress. Wait until fully decrypted before proceeding.",
            state,
        )
    if normalized in {"off", "0"}:
        return CheckResult("bitlocker", CheckStatus.PASS, "BitLocker protection is not active on system drive.", state)
    if normalized in {"on", "1", "protectionon"}:
        return CheckResult("bitlocker", CheckStatus.FAIL, "BitLocker is active; backup and handling flow required.", state)
    return CheckResult("bitlocker", CheckStatus.WARN, "BitLocker state could not be reliably determined.", state)


def _check_fast_startup(probe: WindowsProbe) -> CheckResult:
    enabled = probe.fast_startup_enabled()
    if enabled is False:
        return CheckResult("fast_startup", CheckStatus.PASS, "Fast Startup is disabled.", "false")
    if enabled is True:
        return CheckResult("fast_startup", CheckStatus.FAIL, "Fast Startup must be disabled before proceeding.", "true")
    return CheckResult("fast_startup", CheckStatus.WARN, "Fast Startup state could not be determined.", "unknown")


def _check_winre(probe: WindowsProbe) -> CheckResult:
    enabled = probe.winre_enabled()
    if enabled is True:
        return CheckResult("winre", CheckStatus.PASS, "Windows RE is enabled.", "true")
    if enabled is False:
        return CheckResult("winre", CheckStatus.FAIL, "Windows RE is disabled; recovery contract not met.", "false")
    return CheckResult("winre", CheckStatus.WARN, "Windows RE status could not be determined.", "unknown")


def evaluate_windows_preflight(probe: WindowsProbe) -> WindowsPreflightReport:
    checks = (
        _check_admin(probe),
        _check_windows_version(probe),
        _check_boot_mode(probe),
        _check_partition_style(probe),
        _check_secure_boot(probe),
        _check_bitlocker(probe),
        _check_fast_startup(probe),
        _check_winre(probe),
    )
    can_proceed = all(check.status != CheckStatus.FAIL for check in checks)
    return WindowsPreflightReport(checks=checks, can_proceed=can_proceed)


def run_windows_preflight(probe: WindowsProbe | None = None) -> dict:
    """Run deterministic safety checks and return structured gating output."""
    report = evaluate_windows_preflight(probe or PowerShellProbe())
    return report.to_dict()
