# PROD-BROWSERLESS-VEX-REVIEW-001 / PROD-BROWSERLESS-VEX-DIGEST-REISSUE-001

## Decision

The twelve residual CVEs in the exact local browserless `a635692a899ee02c6905cd694611c14e0da4594a` API, Admin and XHS HTTP candidates are formally assessed as `not_affected`. This is an exact-product VEX decision, not a production exception, a scanner deletion, an ACR push authorization or a deployment authorization.

The canonical raw Trivy reports remain unchanged at 23 rows per role: 4 Critical and 19 High, with no ignore file, VEX, suppression or reported fixed version applied to those source reports. The separate CycloneDX VEX document exists so a reviewer can see both the scanner result and the exact-product impact decision.

## Exact scope

| Role | Corrected immutable ACR digest | Local image ID | SBOM serial | Raw report |
|---|---|---|---|---|
| API | `sha256:17706e1802afc136ac8f9a621d4199a7f9749da733290e923e42268eff42e0d1` | `sha256:b1983bab928ef93495d8be020030917d4ae54364234390047c3163af5414fedb` | `urn:uuid:9b5dc0cf-276b-42a8-8cde-aae5d0676dc5/1` | 23 rows, 4 Critical / 19 High |
| Admin | `sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733` | `sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f` | `urn:uuid:ae2ab874-1774-4af7-ad42-ce7cad5c876b/1` | 23 rows, 4 Critical / 19 High |
| XHS HTTP | `sha256:452c2faf7853ce58d93e43c05fb6217a9a6cc1e4c81345d8cef2f50acabd79af` | `sha256:5b44114d4bd9c28a8e93c39140466c542e8babeead038fb0d1cfe45c3cd75966` | `urn:uuid:4073a9eb-1d9b-49b3-8dc1-7bfbfec21514/1` | 23 rows, 4 Critical / 19 High |

The local Docker image IDs remain distinct from the ACR registry digests. CycloneDX VEX version 3 binds only the three corrected digests that passed direct `repository@sha256` pull and OCI provenance read-back. The prior version 2 bindings were invalidated by direct-pull evidence and must never be used. The VEX becomes stale if the registry digest, image, SBOM, base image, architecture, package set, role entrypoint/command graph, deployment constraints or official CVE scope changes.

## Twelve dispositions

| CVE | Formal state | CycloneDX justification | Exact-product evidence |
|---|---|---|---|
| `CVE-2026-13221` | `not_affected` | `code_not_reachable` | Perl core exists, but no accepted role command invokes Perl or accepts an attacker-controlled Perl regex. |
| `CVE-2026-42496` | `not_affected` | `code_not_present` | Trivy maps the source package to `perl-base`; the affected `Archive::Tar` module is absent. |
| `CVE-2026-57433` | `not_affected` | `code_not_present` | The affected `Storable` module is absent. |
| `CVE-2026-8376` | `not_affected` | `requires_environment` | The affected condition requires a 32-bit Perl build; every exact candidate is `linux/amd64`. |
| `CVE-2025-69720` | `not_affected` | `code_not_reachable` | The affected `infocmp` CLI/terminfo path is outside every accepted role command graph. |
| `CVE-2026-41992` | `not_affected` | `code_not_reachable` | No accepted role invokes the affected multi-file gzip decompression path. |
| `CVE-2026-42497` | `not_affected` | `code_not_present` | The affected `Archive::Tar` module is absent. |
| `CVE-2026-48962` | `not_affected` | `code_not_present` | The affected `IO::Compress` module is absent. |
| `CVE-2026-53615` | `not_affected` | `code_not_reachable` | Offline accepted-root ELF closure does not reach `libblkid.so.1`; enforced runtime has no devices, privilege, dangerous capabilities or host namespace. |
| `CVE-2026-54369` | `not_affected` | `code_not_reachable` | Offline accepted-root ELF closure does not reach `libacl.so.1`; runtime is UID/GID 999, capability-free and read-only. |
| `CVE-2026-57432` | `not_affected` | `code_not_reachable` | No accepted role invokes Perl or accepts an attacker-controlled Perl pack/unpack template. |
| `CVE-2026-9538` | `not_affected` | `code_not_present` | The affected `Archive::Tar` module is absent. |

The VEX `affects` fields use exact independent-BOM links. The ncurses decision covers all four Trivy package rows per role, and the util-linux decision covers all nine rows per role. It does not use a top-level image reference as a substitute for the scanned package component.

## Evidence and safety

- Machine evidence manifest: `security/vex/a635692-browserless-evidence.json`.
- Formal CycloneDX VEX: `security/vex/a635692-browserless.vex.cdx.json`.
- Independent review record: `security/vex/a635692-browserless-review.json`.
- Offline verifier: `python tools/verify_browserless_vex.py`.
- Retained raw Trivy SHA256 values remain API `92d8bab2f8b58f4ed2a9469aaca8a73ee9985d8a97999ab7ff81efba68c20eda`, Admin `e38d2a754a74133b93538545473cc3a1758403a1389fc34a028a3d81bc1e44b8`, and XHS HTTP `f91e706a8e058fa60952b74246fb9a156b68cb698e6379ccc9a6aed79f744932`.
- Retained SBOM SHA256 values remain API `59a4cabaa7debfb81684ac3a77c7467454d1c98ef04d64aeade4850b07d918be`, Admin `136ace76eaaaed1d7ded40d54bb5162cbd28bb79069a310694913e847d1f6cd7`, and XHS HTTP `a27663349c7af6ebdfdfbd16bf6ef2c189b420115405304ac26565249aa6a92e`.
- The retained constraint proof covers 1,203 ELF records, 354 accepted roots and 377 reachable objects per role.
- Cloud Assistant reads targeted only isolated builder `i-wz99180s9ig5ecq10uaj`. No production instance, image, file, environment or cloud resource was modified.
- One supplemental `jq` read stopped with exit code 5 because of expression grouping. It read the first SBOM and made no change; the corrected read completed with exit code 0.
- No exploit, PoC, malformed input, symbol/memory probe or network provider call was used.

The disposition format follows the CISA minimum VEX fields and status-justification model, CycloneDX vulnerability analysis enumerations, and Trivy's independent CycloneDX BOM-Link matching behavior. Debian Security Tracker links are included per CVE in the VEX.

## Release boundary

Successful digest reissue closes only the corrected immutable-product VEX binding gate. It does not authorize another ACR login/push, image build, deployment, service start, production access, ALB, TLS, DNS or real supplier call. Any deployment still requires a separate plan and explicit approval, and must enforce the reviewed runtime constraints.
