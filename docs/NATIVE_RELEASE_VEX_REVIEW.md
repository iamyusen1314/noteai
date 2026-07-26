# Native five-role release VEX review

Task: `PROD-FIRST-LAUNCH-IMAGE-VULN-DISPOSITION-001`

Application revision:
`2fa3a5543876a6c8040ec17ca05a5461b101bbd7`

Status: `VERIFIED FOR EXACT LOCAL PRODUCT / NOT DEPLOYMENT AUTHORIZATION`

## Decision

GitHub native workflow run `30216295810` built the API, Admin, Payment,
AI Worker and XHS HTTP targets on an `x86_64` runner from the exact application
revision. Both ordinary CI runs passed. Native build, inspection, SBOM,
Secret scan and evidence upload passed; the final raw zero-Critical/High gate
failed closed, as designed.

The production `cryptography` wheel is now `48.0.1`, the first release fixed
for `GHSA-537c-gmf6-5ccf`. Every role contains exactly one such component.
Production dependencies deliberately exclude MLflow because the local
training-tool environment currently requires `cryptography<47`.

Canonical Trivy reports remain unchanged and unsuppressed at `4 Critical /
19 High` per role. The twelve unique Debian CVEs are formally assessed
`not_affected` only for these exact local images, SBOMs, entrypoint/command
graph and production runtime constraints. This is not a scanner deletion,
waiver, registry digest, production exception or deployment authorization.

## Exact identities

| Role | Local image ID | SBOM SHA256 | Raw vulnerability report SHA256 |
|---|---|---|---|
| API | `sha256:d5b0066cca40c70b1fa9f84afb136bf1a933b89ca7d98a36b73382a1585118c1` | `58b485d920b103d2cf1cb8ecd951752dec3153cd6c183de9858d1bdadb17c04c` | `5a70699ceb5d3b8a519a8f65b710d6e48879dcf585b5e6ae5d21dc14343a062e` |
| Admin | `sha256:a87133a69cc460f17fd2ade6f36fe09401083c0b93ca087ea1c74aa757a80c60` | `2829bc88f5e4dabfae7c2bc0c953b5d3071b8bd04c6db8eb2a00b0cec06230ee` | `504aabc50a703685bf735e4e0b5c086c7d361cf562d9630441438bf06fe0b17b` |
| Payment | `sha256:b499cc6600a49a4ae4dc95302b20b99d8aa859f8d2c6eb44f51c7d63094a5ca5` | `3e66a120720bc8905d11602541779823e21e5b9cd6a4682ea8a87e790c27ccde` | `10becf8454e857726729b0eda6518802f2d4878359bdaf5c7deefa2a84553863` |
| AI Worker | `sha256:19d7ac22d33e12584037bed9abefd2dc5d84264a6df598071e7ca48ed89f27c4` | `4656c6ad49f901dba3ca876eaf7aba39f90d2536cfa08955c586198b0e8bfff6` | `318a8fb6f805577f6853793996bc33eeb71b2e407037e76ab7550dfaab947569` |
| XHS HTTP | `sha256:b5907d57feca619b6668f91ba278740799d4768f2816a7d48f0551f9b060c9ba` | `2cabdeb2608dc3802a7fd6bba31ca98e933be4610a40557c2593813a3ec7761a` | `4bab1def66febf338a80138a1cf161eb41a2e1b2553d80aafc66855923a5cc80` |

Local image IDs are not registry digests. No ACR login, pull or push occurred.

## Residual disposition

| CVE family | Exact-product conclusion |
|---|---|
| Perl core `13221`, `57432` | Perl is present but outside every accepted role command and production subprocess path. |
| Archive::Tar `42496`, `42497`, `9538` | Affected module is absent from the exact pinned base; no stage installs Perl modules. |
| Storable `57433` / IO::Compress `48962` | Affected modules are absent from the exact pinned base; no stage installs Perl modules. |
| Perl `8376` | Requires a 32-bit build; all five candidates are `linux/amd64`. |
| ncurses `69720` | Affected `infocmp` CLI is outside every accepted command path. |
| gzip `41992` | No role invokes the affected multi-file decompression path. |
| util-linux `53615` | No device/partition parser path; runtime has no devices, privileges, capabilities or host namespaces. |
| libacl `54369` | No ACL tool/API path; runtime is UID/GID 999, capability-free and read-only. |

## Evidence and verification

- Reduced machine evidence:
  `security/vex/2fa3a55-native-release-evidence.json`.
- CycloneDX 1.6 VEX:
  `security/vex/2fa3a55-native-release.vex.cdx.json`.
- Review record:
  `security/vex/2fa3a55-native-release-review.json`.
- Offline verifier:
  `python tools/verify_native_release_vex.py`.
- VEX contains twelve vulnerability objects and 115 exact SBOM BOM-Links.
- The CycloneDX 1.6 schema at specification commit
  `55343ba19dee1785acf1ce9191540d5fd7b590db` has SHA256
  `3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93`;
  validation returned zero errors.
- Focused native/VEX/readiness tests, the full unit suite, Compose parsing,
  production-readiness gate and Git diff checks must remain green.

Any application/image ID, base image, SBOM, architecture, package version,
entrypoint, subprocess graph, runtime capability/device/mount/namespace or
official CVE-scope change invalidates this review. Publishing to ACR and
deploying the current release remain separate authenticated tasks.
