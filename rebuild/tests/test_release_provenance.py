from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

import rebuild.tools.publish_release as publisher
from rebuild.installer.shared.models import ReleaseManifestContract
from rebuild.tools.build_iso_pipeline import validate_release_version
from rebuild.tools.build_windows_exe import normalize_version


COMMIT = "a" * 40
TAG = "v1.2.3"
RUN_ID = "12345"
REF = f"refs/tags/{TAG}"


def write_artifacts(root: Path, *, dry_run: bool = False, commit: str = COMMIT) -> None:
    iso = root / "iso" / "fixture-omarchy-auto.iso"
    exe = root / "windows" / "OmarchyInstaller.exe"
    iso.parent.mkdir(parents=True)
    exe.parent.mkdir(parents=True)
    iso.write_bytes(b"iso")
    exe.write_bytes(b"exe")
    common = {
        "schema_version": "1.0.0",
        "dry_run": dry_run,
        "git_commit": commit,
        "release_version": "1.2.3",
        "release_tag": TAG,
        "github_run_id": RUN_ID,
        "github_ref": REF,
    }
    (iso.parent / "iso-build-manifest.json").write_text(
        json.dumps(
            {
                **common,
                "output_iso": {
                    "name": iso.name,
                    "sha256": publisher.compute_sha256(iso),
                },
            }
        ),
        encoding="utf-8",
    )
    (exe.parent / "windows-exe-build-manifest.json").write_text(
        json.dumps(
            {
                **common,
                "version_stamp": {"dotted_quad": "1.2.3.0"},
                "output": {
                    "exe_name": exe.name,
                    "sha256": publisher.compute_sha256(exe),
                },
            }
        ),
        encoding="utf-8",
    )


def test_windows_version_requires_explicit_semver() -> None:
    assert normalize_version("1.2.3").dotted_quad == "1.2.3.0"
    for invalid in ("abc123", "1.2", "1.2.3-rc1", "70000.1.1"):
        with pytest.raises(ValueError):
            normalize_version(invalid)
    assert validate_release_version("1.2.3") == "1.2.3"


def test_release_bundle_accepts_exact_non_dry_run_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = tmp_path / "inputs"
    write_artifacts(inputs)
    monkeypatch.setattr(publisher, "detect_git_commit", lambda _workspace: COMMIT)

    bundle = publisher.build_release_payload(tmp_path, inputs, tmp_path / "output", TAG)

    manifest = ReleaseManifestContract.model_validate(
        json.loads(Path(bundle["release_manifest"]).read_text(encoding="utf-8"))
    )
    assert manifest.build.git_commit == COMMIT
    assert manifest.build.github_run_id == RUN_ID
    assert manifest.contracts.plan_schema_version == "1.0.0"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("dry", "dry-run"),
        ("commit", "provenance mismatch"),
        ("hash", "hash does not match"),
    ],
)
def test_release_bundle_rejects_untrusted_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    message: str,
) -> None:
    inputs = tmp_path / "inputs"
    write_artifacts(inputs, dry_run=mutation == "dry")
    if mutation == "commit":
        exe_manifest = inputs / "windows" / "windows-exe-build-manifest.json"
        payload = json.loads(exe_manifest.read_text(encoding="utf-8"))
        payload["git_commit"] = "b" * 40
        exe_manifest.write_text(json.dumps(payload), encoding="utf-8")
    if mutation == "hash":
        (inputs / "iso" / "fixture-omarchy-auto.iso").write_bytes(b"tampered")
    monkeypatch.setattr(publisher, "detect_git_commit", lambda _workspace: COMMIT)

    with pytest.raises(RuntimeError, match=message):
        publisher.build_release_payload(tmp_path, inputs, tmp_path / "output", TAG)


def test_recursive_artifact_match_must_be_unique(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    (tmp_path / "a" / "OmarchyInstaller.exe").write_bytes(b"one")
    (tmp_path / "b" / "OmarchyInstaller.exe").write_bytes(b"two")

    with pytest.raises(RuntimeError, match="Ambiguous"):
        publisher.find_single_file(tmp_path, "OmarchyInstaller.exe")


def test_existing_release_tag_is_immutable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(publisher, "run_command", lambda command, cwd=None: calls.append(command))

    with pytest.raises(RuntimeError, match="immutable"):
        publisher.publish_release_assets("owner/repo", TAG, [tmp_path / "asset"], dry_run=False)
    assert len(calls) == 1


def _write_signing_evidence(path: Path, *, production: bool, signed: bool) -> None:
    path.write_text(
        json.dumps(
            {
                "production_signing": production,
                "signed": signed,
                "certificate_source": "managed-secret" if production else "none",
            }
        ),
        encoding="utf-8",
    )


def test_signing_gate_requires_production_by_default(tmp_path: Path) -> None:
    evidence = tmp_path / "windows-exe-signing.json"
    _write_signing_evidence(evidence, production=False, signed=False)
    with pytest.raises(RuntimeError, match="production Authenticode"):
        publisher.enforce_signing_gate(evidence, allow_unsigned=False)


def test_signing_gate_requires_evidence_file(tmp_path: Path) -> None:
    missing = tmp_path / "windows-exe-signing.json"
    with pytest.raises(RuntimeError, match="signing evidence is missing"):
        publisher.enforce_signing_gate(missing, allow_unsigned=True)


def test_signing_gate_allows_unsigned_when_opted_in(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    evidence = tmp_path / "windows-exe-signing.json"
    _write_signing_evidence(evidence, production=False, signed=False)
    result = publisher.enforce_signing_gate(evidence, allow_unsigned=True)
    assert result["production_signing"] is False
    assert "not signed with a production" in capsys.readouterr().err.lower()


def test_signing_gate_accepts_production_signature(tmp_path: Path) -> None:
    evidence = tmp_path / "windows-exe-signing.json"
    _write_signing_evidence(evidence, production=True, signed=True)
    result = publisher.enforce_signing_gate(evidence, allow_unsigned=False)
    assert result["production_signing"] is True


def test_new_release_upload_never_uses_clobber(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def run(command: list[str], cwd=None) -> None:
        calls.append(command)
        if command[:3] == ["gh", "release", "view"]:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(publisher, "run_command", run)
    publisher.publish_release_assets("owner/repo", TAG, [tmp_path / "asset"], dry_run=False)

    assert len(calls) == 3
    assert "--clobber" not in calls[-1]
