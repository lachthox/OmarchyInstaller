# Windows code signing

## Current state: unsigned releases (the $0 path)

The release workflow (`.github/workflows/rebuild-release.yml`) publishes an
**unsigned** Windows EXE by default. This is a deliberate, supported choice for
a $0 open-source release:

- The signing step (`rebuild/tools/sign_windows_exe.py`) leaves the EXE unsigned
  when no managed certificate secret is configured, and records that fact in
  `windows-exe-signing.json` (`production_signing: false`, `signed: false`).
- The publish step runs `python -m rebuild.tools.publish_release ... --allow-unsigned`,
  which permits an unsigned EXE through the release gate instead of failing closed.

### What "unsigned" means for users

- **Windows SmartScreen** shows a full-screen *"Windows protected your PC"*
  warning. Users must click **More info -> Run anyway** to launch the installer.
- There is **no publisher identity** baked into the EXE. Anyone could produce a
  binary claiming to be this project.

### What still protects users without Authenticode

The release is not "trust nothing." Every published release includes:

- `sha256sums.txt` covering the ISO, EXE, and both manifests, so a download can
  be integrity-checked.
- **GitHub build-provenance attestation** (`actions/attest@v4`), which
  cryptographically ties the artifacts to the exact workflow run and commit that
  built them. Verify with:

  ```
  gh attestation verify OmarchyInstaller.exe --repo <owner>/<repo>
  ```

So origin and integrity are verifiable — just not automatically by Windows at
double-click time, the way an Authenticode signature would be.

## Switching to a real (signed) release later

Signing is a drop-in upgrade — **no code change is required**. The signing tool
auto-detects the managed certificate from environment/secret variables and, when
present, produces a real production signature that satisfies the strict publish
gate even without `--allow-unsigned`.

### Step 1 — obtain a code-signing certificate

Pick one:

- **SignPath Foundation (free, for open source)** — issues a free Authenticode
  certificate to qualifying OSS projects. Best "no SmartScreen, no cost" option.
  Requires an application and review. https://signpath.org/
- **Azure Trusted Signing** — low monthly cost, cloud-managed key, no PFX to
  handle. Requires an identity-validated Azure account.
- **A commercial CA** (DigiCert, Sectigo, SSL.com, etc.) — buy an OV or EV
  code-signing certificate. EV clears SmartScreen reputation fastest.

An **EV** certificate clears SmartScreen's reputation gate immediately; an **OV**
certificate clears it after the binary accrues download reputation.

### Step 2 — configure the GitHub Actions secrets

The signing tool reads these (see `rebuild/tools/sign_windows_exe.py`):

| Secret | Meaning |
| --- | --- |
| `WINDOWS_CODESIGN_PFX_BASE64` | Base64-encoded `.pfx` (cert + private key). |
| `WINDOWS_CODESIGN_PASSWORD` | The PFX private-key password. |
| `WINDOWS_CODESIGN_TIMESTAMP_URL` | Optional RFC3161 timestamp URL (defaults to a public DigiCert responder). |

To produce the base64 PFX value:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("codesign.pfx")) | Set-Content pfx.b64
```

Add each value under **Repo Settings -> Secrets and variables -> Actions**.

> A cloud key service (Azure Trusted Signing, or a CA's KMS/HSM) that does not
> hand you a PFX will need a small adapter in `sign_windows_exe.py` that calls
> its signing client instead of `signtool /f <pfx>`. The evidence contract
> (`production_signing: true`, `signed: true`) stays the same.

### Step 3 — tighten the gate back to fail-closed

Once real signing is configured and verified in a run, remove `--allow-unsigned`
from the **"Publish only ..."** step in `rebuild-release.yml`. The gate then
requires `production_signing: true` again, so a future misconfiguration can never
silently ship an unsigned production build. No other change is needed — with the
secrets present, `sign_windows_exe.py` already produces the production signature
the strict gate expects.

## Reference

- Gate logic: `rebuild/tools/publish_release.py` (`enforce_signing_gate`).
- Signing tool + credential resolution order: `rebuild/tools/sign_windows_exe.py`.
- Release policy context: `docs/release-process.md`, `docs/release-readiness.md`.
