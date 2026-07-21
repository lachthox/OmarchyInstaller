"""Installed-system boot guardian, health evaluation, and repair support."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Literal, Protocol

from ..linux_live.boot_policy import (
    BootEntry,
    BootPolicyError,
    discover_boot_entries,
    discover_boot_order,
    verify_limine_efi_assets,
    verify_windows_efi_assets,
)
from .boot_guardian_state import (
    BOOT_GUARDIAN_STATE_SCHEMA_VERSION,
    DEFAULT_BOOT_GUARDIAN_STATE_PATH,
    BootGuardianExpectedState,
    BootGuardianFinding,
    BootGuardianObservedState,
    BootGuardianResult,
    BootGuardianStateError,
)


class CommandRunner(Protocol):
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]: ...


class SubprocessCommandRunner:
    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(command, capture_output=True, text=True, check=False)


@dataclass(frozen=True, slots=True)
class BootGuardianRuntime:
    expected_state: BootGuardianExpectedState
    state_source: str
    observed_state: BootGuardianObservedState


def _resolve_state_path(state_path: str | Path | None) -> Path:
    return Path(state_path).expanduser().resolve() if state_path is not None else DEFAULT_BOOT_GUARDIAN_STATE_PATH


def load_expected_state(state_path: str | Path | None = None) -> tuple[BootGuardianExpectedState, str]:
    resolved = _resolve_state_path(state_path)
    if resolved.exists():
        try:
            payload = resolved.read_text(encoding="utf-8")
            state = BootGuardianExpectedState.from_dict(json.loads(payload))
        except Exception as exc:  # pragma: no cover - defensive wrapping
            raise BootGuardianStateError(f"Failed to load boot guardian expected-state from {resolved}: {exc}") from exc
        return state, f"file:{resolved}"
    return BootGuardianExpectedState(), "built-in-default"


def _normalize_label(value: str) -> str:
    return value.strip().lower()


def _resolve_entry_by_labels(entries: tuple[BootEntry, ...], labels: tuple[str, ...]) -> tuple[BootEntry | None, str]:
    matches: list[BootEntry] = []
    for alias in labels:
        alias_norm = _normalize_label(alias)
        for entry in entries:
            label_norm = _normalize_label(entry.label)
            if alias_norm and alias_norm in label_norm and entry not in matches:
                matches.append(entry)
    if not matches:
        return None, "missing"
    if len({entry.boot_id for entry in matches}) > 1:
        return None, "ambiguous"
    return matches[0], "resolved"


def _resolve_expected_role_entries(
    expected: BootGuardianExpectedState,
    entries: tuple[BootEntry, ...],
) -> tuple[dict[str, str], dict[str, str], list[str]]:
    resolved_ids: dict[str, str] = {}
    resolved_labels: dict[str, str] = {}
    blockers: list[str] = []

    for role in expected.preferred_boot_order:
        aliases = expected.expected_boot_labels.get(role, ())
        entry, resolution = _resolve_entry_by_labels(entries, aliases)
        if resolution == "missing":
            blockers.append(f"boot entry for role '{role}' is missing")
            continue
        if resolution == "ambiguous" or entry is None:
            blockers.append(f"boot entry for role '{role}' is ambiguous")
            continue
        resolved_ids[role] = entry.boot_id
        resolved_labels[role] = entry.label

    return resolved_ids, resolved_labels, blockers


def _build_observed_state(
    expected: BootGuardianExpectedState,
    *,
    efi_mount: str | Path | None = None,
    runner: CommandRunner | None = None,
) -> BootGuardianObservedState:
    active_runner = runner or SubprocessCommandRunner()
    mount_path = Path(efi_mount or expected.efi_mount)
    mount_str = str(mount_path)
    mount_exists = mount_path.exists()

    windows_efi_exists = mount_exists and verify_windows_efi_assets(mount_path)
    limine_efi_exists = mount_exists and verify_limine_efi_assets(mount_path)

    measurement_error = ""
    try:
        boot_entries = discover_boot_entries(runner=active_runner)
        boot_order = discover_boot_order(runner=active_runner)
    except BootPolicyError as exc:
        boot_entries = tuple()
        boot_order = tuple()
        measurement_error = str(exc)

    resolved_ids, resolved_labels, _ = _resolve_expected_role_entries(expected, boot_entries)

    return BootGuardianObservedState(
        efi_mount=mount_str,
        efi_mount_exists=mount_exists,
        windows_efi_exists=windows_efi_exists,
        limine_efi_exists=limine_efi_exists,
        boot_entries=boot_entries,
        boot_order=boot_order,
        resolved_boot_ids=resolved_ids,
        resolved_boot_labels=resolved_labels,
        measurement_error=measurement_error,
    )


def _boot_order_labels(observed: BootGuardianObservedState) -> dict[str, str]:
    entry_map = {entry.boot_id: entry.label for entry in observed.boot_entries}
    return {boot_id: entry_map.get(boot_id, boot_id) for boot_id in observed.boot_order}


def _build_repair_order(expected: BootGuardianExpectedState, observed: BootGuardianObservedState) -> tuple[str, ...]:
    desired_ids = [observed.resolved_boot_ids[role] for role in expected.preferred_boot_order if role in observed.resolved_boot_ids]
    if len(desired_ids) != len(expected.preferred_boot_order):
        raise BootGuardianStateError("Cannot repair boot order because not all expected boot entries were resolved.")

    reordered = list(desired_ids)
    for boot_id in observed.boot_order:
        if boot_id not in reordered:
            reordered.append(boot_id)
    return tuple(reordered)


def _run_checked(runner: CommandRunner, command: list[str]) -> str:
    completed = runner.run(command)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "command failed"
        raise BootGuardianStateError(f"{' '.join(command)}: {detail}")
    return completed.stdout.strip()


def _build_findings(
    expected: BootGuardianExpectedState,
    observed: BootGuardianObservedState,
) -> tuple[BootGuardianFinding, ...]:
    findings: list[BootGuardianFinding] = []

    if observed.measurement_error:
        findings.append(
            BootGuardianFinding(
                code="measurement-error",
                severity="critical",
                message=f"Could not read boot policy state: {observed.measurement_error}",
            )
        )
        return tuple(findings)

    if not observed.efi_mount_exists:
        findings.append(
            BootGuardianFinding(
                code="efi-mount-missing",
                severity="critical",
                message=f"EFI mount is missing: {observed.efi_mount}",
            )
        )
    if not observed.windows_efi_exists:
        findings.append(
            BootGuardianFinding(
                code="windows-efi-missing",
                severity="critical",
                message="Windows EFI asset is missing from the EFI partition.",
            )
        )
    if not observed.limine_efi_exists:
        findings.append(
            BootGuardianFinding(
                code="limine-efi-missing",
                severity="critical",
                message="Limine EFI asset is missing from the EFI partition.",
            )
        )
    if not observed.boot_entries:
        findings.append(
            BootGuardianFinding(
                code="boot-entries-missing",
                severity="critical",
                message="No EFI boot entries were discovered.",
            )
        )
        return tuple(findings)

    role_blockers: list[str] = []
    for role in expected.preferred_boot_order:
        if role not in observed.resolved_boot_ids:
            role_blockers.append(role)
    if role_blockers:
        findings.append(
            BootGuardianFinding(
                code="boot-entry-resolution-failed",
                severity="critical",
                message="Boot entries could not be resolved for roles: " + ", ".join(role_blockers),
            )
        )
        return tuple(findings)

    if not observed.boot_order:
        findings.append(
            BootGuardianFinding(
                code="boot-order-unavailable",
                severity="critical",
                message="BootOrder could not be measured from efibootmgr.",
            )
        )
        return tuple(findings)

    desired_order = tuple(observed.resolved_boot_ids[role] for role in expected.preferred_boot_order)
    filtered_actual_order = tuple(boot_id for boot_id in observed.boot_order if boot_id in desired_order)
    if filtered_actual_order != desired_order:
        repair_command = "efibootmgr -o " + ",".join(_build_repair_order(expected, observed))
        findings.append(
            BootGuardianFinding(
                code="boot-order-drift",
                severity="warning",
                message="BootOrder does not prioritize Limine with Windows fallback.",
                repairable=True,
                repair_command=repair_command,
            )
        )

    return tuple(findings)


def evaluate_boot_guardian(
    expected: BootGuardianExpectedState,
    observed: BootGuardianObservedState,
    *,
    state_source: str,
    mode: Literal["check", "repair"] = "check",
    repair_attempted: bool = False,
    repaired: bool = False,
    repair_actions: tuple[str, ...] = (),
) -> BootGuardianResult:
    findings = _build_findings(expected, observed)
    severity: Literal["healthy", "warning", "critical"] = "healthy"
    if any(finding.severity == "critical" for finding in findings):
        severity = "critical"
    elif any(finding.severity == "warning" for finding in findings):
        severity = "warning"

    repairable = any(finding.repairable for finding in findings)
    notify = severity == "warning" and expected.warning_notify

    if severity == "critical":
        status: Literal["healthy", "warning", "critical", "repaired"] = "critical"
        exit_code = 1
    elif repaired:
        status = "repaired"
        exit_code = 0
    elif severity == "warning":
        status = "warning"
        exit_code = 0
    else:
        status = "healthy"
        exit_code = 0

    repair_command = next((finding.repair_command for finding in findings if finding.repair_command), "")
    summary_bits = [
        f"EFI mount: {observed.efi_mount}",
        f"Windows EFI: {'present' if observed.windows_efi_exists else 'missing'}",
        f"Limine EFI: {'present' if observed.limine_efi_exists else 'missing'}",
    ]
    if severity == "warning":
        summary_bits.append("boot order drift detected")
    elif severity == "critical":
        summary_bits.append("critical boot guardian blockers detected")
    elif repaired:
        summary_bits.append("boot order repaired")

    return BootGuardianResult(
        schema_version=BOOT_GUARDIAN_STATE_SCHEMA_VERSION,
        mode=mode,
        status=status,
        severity=severity,
        notify=notify,
        can_repair=repairable,
        repair_attempted=repair_attempted,
        repaired=repaired,
        exit_code=exit_code,
        state_source=state_source,
        expected_state=expected,
        observed_state=observed,
        findings=findings,
        repair_actions=repair_actions,
        repair_command=repair_command,
        summary="; ".join(summary_bits),
    )


def run_boot_guardian_check(
    *,
    state_path: str | Path | None = None,
    efi_mount: str | Path | None = None,
    runner: CommandRunner | None = None,
) -> BootGuardianResult:
    expected, state_source = load_expected_state(state_path)
    observed = _build_observed_state(expected, efi_mount=efi_mount, runner=runner)
    return evaluate_boot_guardian(expected, observed, state_source=state_source, mode="check")


def _apply_boot_order_repair(
    expected: BootGuardianExpectedState,
    observed: BootGuardianObservedState,
    *,
    runner: CommandRunner,
) -> tuple[str, ...]:
    desired_order = _build_repair_order(expected, observed)
    _run_checked(runner, ["efibootmgr", "-o", ",".join(desired_order)])
    return (f"efibootmgr -o {','.join(desired_order)}",)


def run_boot_guardian_repair(
    *,
    state_path: str | Path | None = None,
    efi_mount: str | Path | None = None,
    runner: CommandRunner | None = None,
) -> BootGuardianResult:
    active_runner = runner or SubprocessCommandRunner()
    expected, state_source = load_expected_state(state_path)
    observed = _build_observed_state(expected, efi_mount=efi_mount, runner=active_runner)
    initial = evaluate_boot_guardian(expected, observed, state_source=state_source, mode="repair")

    if initial.status == "healthy":
        return initial
    if initial.status == "critical":
        return initial
    if not initial.can_repair:
        return initial
    if not initial.repair_command:
        return initial

    if initial.repair_command.startswith("efibootmgr -o "):
        try:
            repair_actions = _apply_boot_order_repair(expected, observed, runner=active_runner)
        except BootGuardianStateError as exc:
            return BootGuardianResult(
                schema_version=BOOT_GUARDIAN_STATE_SCHEMA_VERSION,
                mode="repair",
                status="critical",
                severity="critical",
                notify=False,
                can_repair=False,
                repair_attempted=True,
                repaired=False,
                exit_code=1,
                state_source=state_source,
                expected_state=expected,
                observed_state=observed,
                findings=(
                    BootGuardianFinding(
                        code="repair-failed",
                        severity="critical",
                        message=str(exc),
                    ),
                ),
                repair_actions=(),
                repair_command=initial.repair_command,
                summary="Boot order repair failed.",
            )
    else:
        return initial

    repaired_observed = _build_observed_state(expected, efi_mount=efi_mount, runner=active_runner)
    repaired_result = evaluate_boot_guardian(
        expected,
        repaired_observed,
        state_source=state_source,
        mode="repair",
        repair_attempted=True,
        repaired=False,
        repair_actions=repair_actions,
    )
    if repaired_result.status == "healthy":
        return BootGuardianResult(
            schema_version=repaired_result.schema_version,
            mode=repaired_result.mode,
            status="repaired",
            severity="healthy",
            notify=False,
            can_repair=repaired_result.can_repair,
            repair_attempted=True,
            repaired=True,
            exit_code=0,
            state_source=repaired_result.state_source,
            expected_state=repaired_result.expected_state,
            observed_state=repaired_result.observed_state,
            findings=repaired_result.findings,
            repair_actions=repair_actions,
            repair_command=repair_actions[0],
            summary="Boot order repair completed.",
        )
    return BootGuardianResult(
        schema_version=repaired_result.schema_version,
        mode=repaired_result.mode,
        status=repaired_result.status,
        severity=repaired_result.severity,
        notify=repaired_result.notify,
        can_repair=repaired_result.can_repair,
        repair_attempted=True,
        repaired=False,
        exit_code=repaired_result.exit_code,
        state_source=repaired_result.state_source,
        expected_state=repaired_result.expected_state,
        observed_state=repaired_result.observed_state,
        findings=repaired_result.findings,
        repair_actions=repair_actions,
        repair_command=repair_actions[0],
        summary="Boot order repair attempted; remaining drift still present.",
    )


def _emit_result(result: BootGuardianResult, *, json_output: bool = False, quiet: bool = False) -> None:
    if json_output:
        print(result.to_json())
        return

    if quiet and result.status == "healthy":
        return

    print(result.summary)
    for finding in result.findings:
        print(f"{finding.severity.upper()}: {finding.code}: {finding.message}")
        if finding.repair_command:
            print(f"REPAIR: {finding.repair_command}")
    if result.repair_attempted:
        print("REPAIR ACTIONS: " + ", ".join(result.repair_actions or ("none",)))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Omarchy installed-system boot guardian.")
    parser.add_argument("action", nargs="?", choices=("check", "repair"), default="check")
    parser.add_argument(
        "--state-path",
        default=str(DEFAULT_BOOT_GUARDIAN_STATE_PATH),
        help="Path to the expected-state JSON contract.",
    )
    parser.add_argument(
        "--efi-mount",
        default="",
        help="Override EFI mount path for boot checks.",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument("--quiet", action="store_true", help="Suppress healthy output.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.action == "repair":
            result = run_boot_guardian_repair(
                state_path=args.state_path,
                efi_mount=args.efi_mount or None,
            )
        else:
            result = run_boot_guardian_check(
                state_path=args.state_path,
                efi_mount=args.efi_mount or None,
            )
    except BootGuardianStateError as exc:
        if args.json:
            print(json.dumps({"status": "critical", "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"CRITICAL: {exc}", file=sys.stderr)
        return 1

    _emit_result(result, json_output=args.json, quiet=args.quiet)
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
