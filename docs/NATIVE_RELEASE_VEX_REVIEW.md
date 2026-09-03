# Native five-role release VEX review

Tasks:

- `PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-B06671F-001`
- `PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-B06671F-PUBLISH-001`

Application revision:
`b06671fbcca51f884b04c86edcf116e373c6cfa8`

Status: `EXACT GITHUB SOURCE CANDIDATE + FIVE ACR PRODUCTS VERIFIED / NOT DEPLOYED`

## Decision

GitHub native workflow run `30233565859` built the API, Admin, Payment,
AI Worker and XHS HTTP targets on an `x86_64` runner from the exact application
revision. Ordinary push and pull-request CI runs `30233541815` and
`30233543255` passed. Native build, inspection, SBOM, Secret scan and evidence
upload passed; the final raw zero-Critical/High gate failed closed, as
designed.

The production `cryptography` wheel is now `48.0.1`, the first release fixed
for `GHSA-537c-gmf6-5ccf`. Every role contains exactly one such component.
Production dependencies deliberately exclude MLflow because the local
training-tool environment currently requires `cryptography<47`.

Canonical Trivy reports remain unchanged and unsuppressed at `4 Critical /
19 High` per role. The twelve unique Debian CVEs are formally assessed
`not_affected` only for the exact image/SBOM identities, entrypoint/command
graph and production runtime constraints. This is not a scanner deletion,
waiver, production exception or deployment authorization.

The isolated retained AMD64 builder separately rebuilt exact revision
`b06671f`, generated canonical raw evidence, and published five role-specific
immutable tags. Authenticated ACR control-plane read-back matched five unique
manifest digests. These ACR-built images intentionally have different local
image IDs and SBOM serials from the GitHub-built source candidates; neither
identity set is inherited by assumption.

The production ACR VPC/PrivateZone binding was restored after publication.
The one-time publisher role and policy, builder ACR VPC link, Docker
authentication and temporary authentication directories were removed.
API-C/API-F were not redeployed or restarted and both retained their exact
pre-publication loopback health fingerprints. No database write, provider
call, ALB/TLS/DNS change or user traffic occurred.

## GitHub source-candidate identities

| Role | Local image ID | SBOM SHA256 | Raw vulnerability report SHA256 |
|---|---|---|---|
| API | `sha256:b394922e1164a3b9e7a613bb521164ef0e7ec1ad4dd439d4adce22f6f911f97b` | `806daa0996215f0507900a87ac67ef694125814719a72672296a264a49a869f1` | `cadce0863ab991107be0fcdbb8a02849c498842af02591dacb0e41d494de6cca` |
| Admin | `sha256:2035afcfd8f6b7172a29fdd30590c6c46e2b8ea228618152e9775895d6f17856` | `b71d40e14eae64b60d8c4282d63ed1dcdbad4d1ac1c63a957ff4d9b2b9c3868e` | `153a043172b1698b5c543558f8f1731fab4c0b0008df184f96f702ee1b2c2112` |
| Payment | `sha256:998fc4078c19b8056ac7a33668071e55513b72f5fb975f7d2f33c81ff5cf5a9b` | `c9ec4dd48e6a7cde7f2406ec57ea1460d70a2caffd16b6fad6e83e2e55ded52d` | `47615d348274ba4064778c92f29189354e55c3a3d5fd972a3251f116c69e7f05` |
| AI Worker | `sha256:e60fb4e42e675b07931a405ee4aaa1c8bb57f1089936c130587a57435588c6bd` | `516a290cc731c5f3f40d3ce722506a6e9a36f3736895259a7162f750f0391962` | `571a4d4a7a698108fd9f73d22734f195a15f9411456596cf162ed053eb587a1a` |
| XHS HTTP | `sha256:6b71735dd53902d69c081305e333d3e93463f664eb135d6b2f903834fbd23dc0` | `32d69e6c97afd670982336fbd852f8cfbf0de77177c94be5567631ae9e93c8d1` | `292d0201e3e643bbdffa82bdb585d0b947b850f8bc8d88bd7fee613edaffca01` |

These GitHub local image IDs are not registry digests. They remain source-
candidate evidence and are not presented as the identities of the ACR build.

## Registry publication evidence

- Five exact `linux/amd64` roles have five unique immutable ACR manifest
  digests and distinct local image IDs.
- Every registry role retains the same 23 canonical package rows, exact
  `4 Critical / 19 High`, zero Secret/browser/forbidden-OS findings and one
  `cryptography 48.0.1`.
- The compact attestation binds all raw SBOM, vulnerability, Secret, OCI
  inspect, history, package and build-metadata hashes. Canonical raw evidence
  remains retained on the isolated builder for fourteen days.
- The registry VEX binds all twelve dispositions to 115 exact ACR-build SBOM
  BOM-Links. The official CycloneDX 1.6 schema validation returned zero
  errors.
- Publication is complete, but deployment authorization remains false.

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

- GitHub source-candidate evidence, VEX and review:
  `security/vex/b06671f-github-native-release-evidence.json`,
  `security/vex/b06671f-github-native-release.vex.cdx.json` and
  `security/vex/b06671f-github-native-release-review.json`.
- ACR publication evidence, VEX and review:
  `security/vex/b06671f-registry-release-evidence.json`,
  `security/vex/b06671f-registry-release.vex.cdx.json` and
  `security/vex/b06671f-registry-release-review.json`.
- Offline verifiers:
  `python tools/verify_native_release_vex.py` and
  `python tools/verify_registry_release_vex.py`.
- Each VEX contains twelve vulnerability objects and 115 exact SBOM
  BOM-Links for its own five-image identity set.
- The CycloneDX 1.6 schema at specification commit
  `55343ba19dee1785acf1ce9191540d5fd7b590db` has SHA256
  `3e92dddbc30cf7f6a02b80f0942b1a4cfd4fb1c26f1dfc4310afa9d613cafb93`;
  validation returned zero errors.
- Focused GitHub/registry VEX/readiness tests pass `41/41`; the full unit
  suite passes `953` with `24` explicit-environment skips; production
  readiness passes `103/103`; quality, Python compilation, CycloneDX 1.6
  schema, JSON and Git diff checks pass.

Any application/image ID, base image, SBOM, architecture, package version,
entrypoint, subprocess graph, runtime capability/device/mount/namespace or
official CVE-scope change invalidates this review. Deploying the current
release remains a separate authenticated task.

The earlier `2fa3a55` bundle remains historical evidence for that exact
revision only. It is not inherited by `b06671f`.
