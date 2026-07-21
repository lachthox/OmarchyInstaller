"""Authenticode-sign the packaged Windows EXE and record verifiable evidence.

Signing credential resolution, in order:
  1. `WINDOWS_CODESIGN_PFX_BASE64` + `WINDOWS_CODESIGN_PASSWORD` (+ optional
     `WINDOWS_CODESIGN_TIMESTAMP_URL`) environment variables -- the real,
     managed Authenticode certificate a production release requires. Never
     committed to the repo; configured as GitHub Actions secrets.
  2. `--ephemeral-test-cert` -- generates a throwaway self-signed certificate
     on the runner purely to exercise and prove the sign/verify mechanics in
     CI. Output is marked `production_signing: false` and must never gate a
     real publish.

If neither is available, the EXE is left unsigned and this tool writes
`windows-exe-signing.json` recording exactly that, so `publish_release.py`
can fail closed rather than silently ship an unsigned production artifact.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path


DEFAULT_TIMESTAMP_URL = "http://timestamp.digicert.com"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _find_signtool() -> str:
    completed = subprocess.run(
        ["where", "signtool"], capture_output=True, text=True, check=False
    )
    if completed.returncode == 0 and completed.stdout.strip():
        return completed.stdout.strip().splitlines()[0]
    for root in Path("C:/Program Files (x86)/Windows Kits/10/bin").glob("*/x64/signtool.exe"):
        return str(root)
    raise RuntimeError("signtool.exe was not found on this runner.")


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=True)


def sign_with_pfx(exe_path: Path, pfx_path: Path, password: str, timestamp_url: str, signtool: str) -> None:
    _run([
        signtool, "sign",
        "/f", str(pfx_path),
        "/p", password,
        "/fd", "sha256",
        "/tr", timestamp_url,
        "/td", "sha256",
        str(exe_path),
    ])


def verify_signature(exe_path: Path, signtool: str) -> str:
    completed = _run([signtool, "verify", "/pa", "/v", str(exe_path)])
    return completed.stdout


def make_ephemeral_test_cert(work_dir: Path) -> tuple[Path, str, str]:
    """Generate a throwaway self-signed codesign cert via PowerShell, export to PFX.

    Also temporarily trusts it (CurrentUser\\Root) so `signtool verify /pa`
    can succeed against it -- a self-signed cert is otherwise never part of
    any trust chain, and `/pa` (the default Authenticode policy) always
    rejects an untrusted signer regardless of how the file was signed. The
    caller is responsible for removing the returned thumbprint from Root
    once verification is done; this is CI-only and never installed on a
    machine that would treat it as a real trust anchor.
    """
    pfx_path = work_dir / "ephemeral-test-cert.pfx"
    password = "ephemeral-test-only"
    script = f"""
$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=Omarchy VM Test (ephemeral, not for production)" -KeyUsage DigitalSignature -FriendlyName "Omarchy VM Test" -CertStoreLocation Cert:\\CurrentUser\\My -NotAfter (Get-Date).AddDays(1)
$securePw = ConvertTo-SecureString -String "{password}" -Force -AsPlainText
Export-PfxCertificate -Cert $cert -FilePath "{pfx_path.as_posix()}" -Password $securePw | Out-Null
$rootStore = Get-Item Cert:\\CurrentUser\\Root
$rootStore.Open("ReadWrite")
$rootStore.Add($cert)
$rootStore.Close()
Remove-Item "Cert:\\CurrentUser\\My\\$($cert.Thumbprint)"
Write-Output $cert.Thumbprint
"""
    completed = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", script], check=True, capture_output=True, text=True
    )
    thumbprint = completed.stdout.strip().splitlines()[-1]
    return pfx_path, password, thumbprint


def untrust_ephemeral_test_cert(thumbprint: str) -> None:
    subprocess.run(
        [
            "pwsh", "-NoProfile", "-Command",
            f'Remove-Item "Cert:\\CurrentUser\\Root\\{thumbprint}" -ErrorAction SilentlyContinue',
        ],
        check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="Path for windows-exe-signing.json evidence.")
    parser.add_argument(
        "--ephemeral-test-cert",
        action="store_true",
        help="Sign with a throwaway self-signed cert to prove the mechanics only; never a production signature.",
    )
    args = parser.parse_args()

    if os.name != "nt":
        print("Windows EXE signing requires a Windows runner (signtool.exe).", file=sys.stderr)
        return 1

    pfx_b64 = os.environ.get("WINDOWS_CODESIGN_PFX_BASE64", "")
    password = os.environ.get("WINDOWS_CODESIGN_PASSWORD", "")
    # A GitHub Actions `env:` mapping from an unset secret sets the variable
    # to an empty string rather than leaving it absent, so `os.environ.get`'s
    # default never triggers on its own -- fall back explicitly.
    timestamp_url = os.environ.get("WINDOWS_CODESIGN_TIMESTAMP_URL", "").strip() or DEFAULT_TIMESTAMP_URL

    evidence = {
        "schema_version": "1.0.0",
        "generated_at_utc": utc_now(),
        "exe_path": str(args.exe),
        "production_signing": False,
        "signed": False,
        "certificate_source": "none",
        "verification_output": "",
        "required_secrets": [
            "WINDOWS_CODESIGN_PFX_BASE64 (base64-encoded .pfx Authenticode certificate)",
            "WINDOWS_CODESIGN_PASSWORD (PFX private key password)",
            "WINDOWS_CODESIGN_TIMESTAMP_URL (optional; defaults to a public RFC3161 responder)",
        ],
    }

    with tempfile.TemporaryDirectory(prefix="omarchy-signing-") as tmp:
        tmp_path = Path(tmp)
        try:
            signtool = _find_signtool()
        except RuntimeError as exc:
            evidence["error"] = str(exc)
            args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            print(str(exc), file=sys.stderr)
            return 1

        if pfx_b64 and password:
            pfx_path = tmp_path / "production-cert.pfx"
            pfx_path.write_bytes(base64.b64decode(pfx_b64))
            try:
                sign_with_pfx(args.exe, pfx_path, password, timestamp_url, signtool)
                verification = verify_signature(args.exe, signtool)
                evidence.update(
                    production_signing=True,
                    signed=True,
                    certificate_source="managed-secret",
                    verification_output=verification,
                )
            finally:
                pfx_path.unlink(missing_ok=True)
        elif args.ephemeral_test_cert:
            pfx_path, ephemeral_password, thumbprint = make_ephemeral_test_cert(tmp_path)
            try:
                sign_with_pfx(args.exe, pfx_path, ephemeral_password, timestamp_url, signtool)
                verification = verify_signature(args.exe, signtool)
                evidence.update(
                    production_signing=False,
                    signed=True,
                    certificate_source="ephemeral-ci-test-cert",
                    verification_output=verification,
                )
            finally:
                pfx_path.unlink(missing_ok=True)
                untrust_ephemeral_test_cert(thumbprint)
        else:
            evidence["note"] = (
                "No managed Authenticode credential configured; EXE left unsigned. "
                "Production release remains blocked until the required secrets are set."
            )

    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
