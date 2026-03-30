from __future__ import annotations

from pathlib import Path

try:
    from rebuild.tools import build_iso_pipeline as pipeline
except ModuleNotFoundError:  # pragma: no cover - fallback for package-local test runs
    from tools import build_iso_pipeline as pipeline


def _write(path: Path, content: str = "x\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_prepare_payload_includes_boot_assets(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _write(workspace / "rebuild" / "installer" / "__init__.py", "# installer\n")
    _write(workspace / "rebuild" / "requirements.txt", "pydantic\n")
    _write(workspace / "rebuild" / "requirements-dev.txt", "pytest\n")

    for rel in [
        "rebuild/assets/scripts/live-autostart.sh",
        "rebuild/assets/scripts/firstboot-wrapper.sh",
        "rebuild/assets/scripts/boot-guardian.sh",
        "rebuild/assets/scripts/omarchy-boot-check.sh",
        "rebuild/assets/scripts/omarchy-boot-repair.sh",
        "rebuild/assets/services/omarchy-firstboot.service",
        "rebuild/assets/services/boot-guardian.service",
    ]:
        _write(workspace / rel, "#!/usr/bin/env bash\n")

    payload_dir = tmp_path / "payload"
    iso = pipeline.IsoDescriptor(
        name="arch.iso",
        date="2026.03.30",
        iso_url="https://example.invalid/arch.iso",
        sha_url="https://example.invalid/sha256sums.txt",
        expected_sha256="deadbeef",
    )

    pipeline.prepare_payload(workspace, payload_dir, iso, "commit123")

    assert (payload_dir / "assets" / "services" / "omarchy-firstboot.service").exists()
    assert (payload_dir / "assets" / "services" / "boot-guardian.service").exists()
    assert (payload_dir / "assets" / "scripts" / "boot-guardian.sh").exists()
    assert (payload_dir / "assets" / "scripts" / "omarchy-boot-check.sh").exists()
    assert (payload_dir / "assets" / "scripts" / "omarchy-boot-repair.sh").exists()
