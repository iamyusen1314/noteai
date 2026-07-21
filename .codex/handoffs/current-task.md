# NoteAI Production Rollout Handoff

> Updated: 2026-07-21 (Asia/Shanghai)
>
> Scope: verified repository checkpoint for `PROD-WORKER-HARDEN-001`. All five Python Chromium launch paths now use a fail-closed sandbox wrapper; the three Compose Worker roles use the pinned Playwright v1.56.0 seccomp profile plus `no-new-privileges`; the final Worker remains non-root. Offline package-ownership and direct ELF-link evidence was retained from the two existing stopped local images. No image build, container/application start, ACR login/read/push, production exception/VEX registration, deployment, production database/cache access, cloud-resource mutation, external-provider call, crawl or end-user payment was authorized or performed.
>
> Evidence precedence: current Git/CI and public health checks > current cloud control-plane reads > previously captured control-plane evidence > conversation recollection. Anything not re-observed after the interruption is explicitly marked `INVESTIGATING` or uncertain.

## 1. Current project phase

NoteAI is in **production infrastructure preparation and controlled release**, not general availability. Render Staging remains the validated staging environment. The production Claude Gateway is live on Render Singapore, while the Alibaba Cloud production application path has not been released: the corrected immutable AMD64 application image is not yet verified, API-C/API-F application services are not accepted, no ALB is configured, TLS certificates are not attached to a production listener, and production DNS has not been switched.

`PROD-PREBUILD-001`, read-only `PROD-VULN-001`, remediation `PROD-VULN-FIX-001`, `PROD-RUNTIME-SPLIT-001`, bounded build/scan `PROD-IMG-SPLIT-BUILD-001`, read-only `PROD-SPLIT-VULN-DECISION-001` and repository hardening `PROD-WORKER-HARDEN-001` are `VERIFIED`. Exact application commit `93b03d5c40fb64fa264c0ada1c055f8e7696b161` is now the unique source for the next API/Worker rebuild. The existing local candidates remain exact revision `89e3505225c9d596d6ddb26040f08b777e77823c`; they predate sandbox hardening, are superseded, and must not be pushed or deployed. Their last scans remain API `3 Critical / 19 High` and Worker `5 Critical / 32 High`, all without a Trixie fixed version and without any registered exception. No new image was built, no ACR login/read/push or registry digest exists for the hardened revision, and no application start, production dependency access or cloud-resource mutation occurred.

## 2. Git and repository truth

| Field | Verified value |
|---|---|
| Branch | `codex/quality-stabilization-real-chain` |
| Application release commit | `93b03d5c40fb64fa264c0ada1c055f8e7696b161` |
| Release parent | `5ba202febaff364328057a7f8a1ca41f72816a47` |
| Release message | `fix(prod): harden worker chromium sandbox [skip render]` |
| Production build source | exact full application commit above; never a later handoff-only HEAD |
| Upstream | `origin/codex/quality-stabilization-real-chain` |
| Ahead / behind before Handoff commit | `0 / 0`; local and remote application SHA both equal `93b03d5c40fb64fa264c0ada1c055f8e7696b161` |
| Staged before checkpoint | none |
| Unstaged before checkpoint | only `.codex/handoffs/current-task.md` |
| Untracked before checkpoint | none |
| Push state | application release commit was normally pushed without force; the next push will be a pure-documentation `[skip render]` Handoff checkpoint whose unknown SHA is not recorded in advance |
| Render auto-deploy impact | application message contains `[skip render]`; the later Handoff-only checkpoint message must also contain `[skip render]`; no deployment is authorized |

Recent relevant commits, newest first:

- `93b03d5` — harden all Worker Chromium launches with fail-closed sandboxing and the pinned Playwright seccomp profile; exact source for the next rebuild; normally pushed without force.
- `5ba202f` — Handoff-only checkpoint for the verified runtime split; documentation provenance, never an application revision.
- `89e3505` — split API and browser-worker runtimes; exact source of the now-superseded local AMD64 candidates; normally pushed to the tracking branch without force.
- `8f7d9c2` — minimize audited combined runtime-image attack surface; historical source of the superseded blocked local AMD64 image.
- `b6abaa7` — close independently verified production prebuild release gates; historical source superseded by later application revisions.
- `ff030f5` — package Meituan travel CLI for production.
- `84f8a2f` — define isolated production Claude Gateway service.
- `ecc4702` — record independent production release verification.
- `0a05a98` — reconcile Alibaba deployment ledger.
- `0ccf3f6` — stop XHS collection after server-side logout.
- `199bf5f` — add durable operation admission ledger.
- `8b6a0b3` — authorize Gateway transaction condition checks.
- `353ee22` — add redacted Gateway control diagnostics.
- `710065f` — reject existing Gateway operation claims.
- `22da06a` — add zero-Claude Gateway scale rehearsal.
- `c0afbbe` — install Blueprint test dependencies in CI.
- `0e050f8` — harden the Claude Gateway trust boundary.

Independent repository verification for exact application revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161` completed. Native AMD64 build, runtime sandbox acceptance, CycloneDX SBOM, Secret scan and unsuppressed High/Critical scans have **not** been run for this hardened revision. The corresponding evidence at `89e3505` remains a superseded baseline only. A later Handoff-only commit may become Git HEAD, but must never replace `93b03d5c40fb64fa264c0ada1c055f8e7696b161` in image metadata.

## 3. Current environment and cloud state

### 3.1 Render

| Component | Current evidence | State and limitation |
|---|---|---|
| Render Staging API | Public `/health/live` and `/health/ready` returned HTTP 200 on 2026-07-20 | Staging only; does not prove Alibaba production readiness. |
| Render Staging Admin | Public readiness returned HTTP 200 on 2026-07-20 after cold wake | Staging only. |
| Render Staging Web | Public root returned HTTP 200 on 2026-07-20 | Staging only. |
| Render Staging Claude Gateway | Public live/readiness returned HTTP 200 on 2026-07-20 | No paid Claude call was made in this checkpoint. |
| Render production Claude Gateway | Public live/readiness returned HTTP 200 on 2026-07-20 | Last exact control-plane evidence: Singapore Starter, minimum 2 / maximum 4 instances, autoscaling CPU 60% and memory 70%, auto-deploy off, deployed revision `84f8a2f`. Eight signed zero-Claude readiness passes and two instance markers were previously verified. Alibaba API is not yet switched to it. |

### 3.2 Alibaba Cloud

The following table separates last confirmed control-plane evidence from current uncertainty. No Alibaba resource was mutated during this checkpoint.

| Component | Last confirmed evidence | Current release conclusion |
|---|---|---|
| ACR | Repository and private access existed; public endpoint was closed; PrivateZone/private endpoint was effective. Existing tag/platform evidence is listed in section 4. | Current complete tag list could not be independently re-read after the interruption because the console session timed out and the public endpoint is disabled. Exact current target-tag existence is `INVESTIGATING`. |
| API-C ECS | Host `noteai-prod-api-c` was running in the last control-plane check. The old AMD64 image had been pulled and runtime secret entry was performed. | Application service was not accepted or started with the target image. Current process/service state must be rechecked read-only; do not infer readiness from ECS host state. |
| API-F ECS | Host `noteai-prod-api-f` was running in the last control-plane check. | Application was not deployed. Current process/service state must be rechecked read-only. |
| RDS | `noteai-prod-postgres`, PostgreSQL 16 high availability, running in the last check; one-month purchase without auto-renew. Authorized migrations `0001` through `0008` were applied: 30 public tables and 8 migration rows; key business tables were empty. | No Staging data was imported. Availability, backup/PITR settings, account connectivity and renewal date require a fresh read-only audit before release. |
| Tair | `noteai-prod-tair`, Redis 7 high availability, 2 GiB, running in the last check; one-month purchase without auto-renew. | Not wired into the application. Availability, endpoint policy and renewal date require a fresh read-only audit. |
| VPC / vSwitches | Production VPC and C/F application/data subnets were created. | Last confirmed available; route and security-group effective state require read-only recheck. |
| SNAT | VPC-level public egress capability was purchased and configured. | Last confirmed enabled; active route, EIP and fee state require read-only recheck. |
| PrivateZone | Private ACR name resolution was configured and previously effective. | Must be rechecked from both API-C and API-F without printing resolved credentials or controlled values. |
| ALB | No completed ALB creation/configuration evidence. | Treat as not created and `BLOCKED` until a fresh inventory proves otherwise. |
| TLS | Three independently purchased certificates for `noteaipro.cn`, `api.noteaipro.cn`, and `admin.noteaipro.cn` were issued. | Not bound to an ALB listener; certificate validity and deployment state require read-only recheck. |
| DNS | Enterprise DNS was paid and the primary domain was bound. | Production business records were not cut over. Local DNS tests are unreliable while proxy fake-IP DNS is active; use authoritative/control-plane evidence. |

### 3.3 Traffic, payments and unrecorded changes

- **Production traffic:** no intended production user path exists because the application services are not accepted, no ALB is configured and business DNS has not been cut over. Exact zero traffic is not independently proven because ALB/application access logs do not exist or were not audited.
- **Cloud payments:** real cloud-resource payments occurred, including domains/DNS, certificates, ECS, RDS, Tair, ACR-related service, and VPC public egress/SNAT resources. RDS and Tair are monthly purchases without confirmed auto-renew.
- **End-user payments:** no real NoteAI payment callback, settlement or reconciliation flow was executed or verified.
- **Production data writes:** only the explicitly authorized clean-production RDS schema migrations are confirmed. No Staging data import and no destructive database action are confirmed.
- **Unrecorded cloud changes:** no specific additional mutation is evidenced, but a complete post-interruption Alibaba inventory and billing audit has not been completed. Therefore absence of unrecorded changes remains uncertain and must be audited read-only.

## 4. Exact recovery point and image supply chain

### 4.1 Required recovery point

- Exact source revision for both next role-specific candidates: `93b03d5c40fb64fa264c0ada1c055f8e7696b161` (`93b03d5`).
- Two superseded local-only candidates exist: `noteai-local:git-89e3505-amd64-api-r1` and `noteai-local:git-89e3505-amd64-worker-r1`. Both are `linux/amd64` and carry full revision `89e3505225c9d596d6ddb26040f08b777e77823c`, but they predate the sandbox correction and must not be pushed or deployed. Neither has an ACR registry digest.
- API size is `1,042,774,445` bytes and Worker size is `2,494,249,539` bytes. Local Docker image IDs are recorded in the ECS acceptance evidence and are explicitly **not** ACR registry digests.
- Each role-specific target may be deployed only after a new build from exact `93b03d5c40fb64fa264c0ada1c055f8e7696b161`, non-root sandbox runtime acceptance under the pinned seccomp profile, complete role-specific scans, a later approved ACR push/read-back recording its own immutable registry digest, and closure of the residual vulnerability gate.
- `89e3505`, `8f7d9c2`, `b6abaa7` and `ff030f5` are no longer acceptable build sources. Any later Handoff-only HEAD is documentation provenance only, not application provenance.

### 4.2 Last verified ACR image inventory

| Tag | Digest | Platform | Release decision |
|---|---|---|---|
| `git-ecc4702e` | `sha256:b7a7d47dba6a314fae2fde6d1d35cafe9f209da41f385c266f463a31f66f6916` | `linux/amd64` | **Forbidden for production release:** older source revision and missing the `ff030f5` Meituan CLI packaging change. |
| `git-ff030f5` | `sha256:751b7ecc9e6f883b923f52754c5290d07e06610014ae43ee5d7fa303c168afe1` | `linux/arm64` | **Forbidden on x86 ECS:** architecture mismatch. |
| `git-ff030f5-amd64-r2` | Not verified | Required `linux/amd64` | Superseded target; do not build or deploy. |
| `git-b6abaa7-amd64-r1` | Never pushed by these tasks; current ACR existence not re-read | `linux/amd64` locally | Superseded local candidate; do not push or deploy. |
| `git-8f7d9c2-amd64-r1` | Local-only at last verification; no ACR registry digest exists | `linux/amd64` | **Superseded historical combined image:** predates the runtime split and Trixie base; do not push or deploy. |
| `noteai-local:git-89e3505-amd64-api-r1` | Local image ID recorded in ECS evidence; no ACR digest | `linux/amd64` | **Superseded:** predates release `93b03d5`; baseline scan `3 Critical / 19 High`. |
| `noteai-local:git-89e3505-amd64-worker-r1` | Local image ID recorded in ECS evidence; no ACR digest | `linux/amd64` | **Superseded and forbidden:** predates fail-closed Chromium sandboxing; baseline scan `5 Critical / 32 High`. |

No mutable tag such as `latest` is an acceptable production reference. No existing image above may be used for production deployment.

### 4.3 Interruption point

The 2026-07-19 interruption occurred **before a successful native AMD64 build and ACR push of the corrected `ff030f5` image**. The ARM64 image had been pushed under `git-ff030f5`. A corrected AMD64 target tag had not appeared in the last verified ACR inventory. API-C had pulled the older `git-ecc4702e` AMD64 image, and runtime secret entry had been performed, but the NoteAI API application had not completed start/readiness acceptance.

### 4.4 Completed, not started and uncertain

Completed with evidence:

- `PROD-PREBUILD-001` and all four child gates are independently verified at application revision `b6abaa781c11950c4d261e8d9f17c3194aecd0cf`.
- Release candidate `b6abaa781c11950c4d261e8d9f17c3194aecd0cf` contains the required `ff030f5` Meituan CLI packaging fix and all independently verified prebuild closures.
- Production Claude Gateway exists on Render Singapore and public live/readiness is healthy.
- Clean production RDS schema migrations `0001` through `0008` were applied without Staging data import.
- Three TLS certificates were issued.
- VPC/subnets, RDS, Tair, ECS hosts, ACR repository/private connectivity and SNAT were provisioned in prior authorized steps.
- `PROD-RUNTIME-SPLIT-001` is independently verified at exact application revision `89e3505225c9d596d6ddb26040f08b777e77823c`; repository-only API/Worker target separation and fail-closed role startup controls passed all final gates.
- `PROD-IMG-SPLIT-BUILD-001` completed on retained isolated builder `i-wz99180s9ig5ecq10uaj`: exact clean detached source and the production Git LFS release set were verified; both local native AMD64 targets were built; provenance, role marker, entrypoint/CMD, non-root user, `mttravel`, model, sensitive-path/history, SBOM, Secret and vulnerability evidence was recorded.
- `PROD-WORKER-HARDEN-001` completed at exact application revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161`: repository sandbox enforcement, pinned seccomp configuration, tests and offline evidence collection were independently verified and normally pushed with `[skip render]`.

Not started or not completed:

- Native AMD64 rebuild and full role-specific acceptance at exact hardened revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161`, including real non-root Chromium sandbox smoke under the pinned seccomp profile and renewed SBOM/Secret/vulnerability scans.
- Release-risk disposition for whatever Critical/High findings remain after that rebuild. No production exception or VEX has been registered.
- ACR push/read-back of any accepted successor candidate and immutable registry digest verification.
- API-C start on the corrected immutable digest and zero-AI readiness.
- Real bounded provider verification for Kimi, Claude Gateway, Amap and Meituan from production.
- API-F deployment.
- ALB creation/configuration, certificate binding and DNS cutover.
- Production smoke test and payment callback/reconciliation validation.

State uncertain and requiring fresh read-only verification:

- Current ACR tag list and whether the target tag was created after the last visible check.
- Current API-C/API-F host and service/process state.
- Current RDS/Tair health, backup/PITR, renewal and network policies.
- Current VPC routes, SNAT, security groups and PrivateZone resolution from both nodes.
- Complete Alibaba resource/billing inventory after the interruption.
- Exact absence of production traffic.

## 5. Unique task ledger

Only these task statuses are permitted: `TODO`, `INVESTIGATING`, `READY_TO_EXECUTE`, `EXECUTING`, `READY_TO_VERIFY`, `VERIFIED`, `BLOCKED`, `DEFERRED`. A task may become `VERIFIED` only after independent verification evidence is recorded here.

### PROD-PREBUILD-001 — Production image prebuild closure

- Status: `VERIFIED`
- Application release candidate: `b6abaa781c11950c4d261e8d9f17c3194aecd0cf` (`fix(prod): close prebuild release gates [skip render]`).
- All four prebuild gates are independently verified: model manifest integrity, explicit/concurrency-safe migrations, core-only zero-outbound health semantics, and pinned/provenance-aware build configuration.
- Independent verification: `586 OK (skipped=5)` full tests; `278 OK` targeted tests; production readiness gate `63/63`; `network_attempts=0`; `py_compile`, Compose/static configuration, diff, secret, and build-context checks passed.
- No production image build/push, service start, database write, cloud mutation, or external-provider call was performed.

### PROD-MODEL-001 — Model release manifest SHA drift

- Status: `VERIFIED`
- Human-readable release checks: `8/8`; machine-readable checks: `4/4`; Git LFS artifact checks: `3/3`.
- The drift was confined to stale human documentation; the machine manifest and LFS artifacts were consistent. The documentation was minimally corrected and the complete SHA validation passed again.
- No production exception was registered and no model binary was replaced.

### PROD-BOOT-001 — Production startup and migration isolation

- Status: `VERIFIED`
- A normal PostgreSQL production API import/start path performs `0` migration runs and opens `0` migration connections.
- The explicit one-time migration path applies migrations `0001`–`0008` once, applies `0` on the second run, and is protected by a PostgreSQL advisory lock against concurrent execution.
- Local and Render Staging behavior remains supported; ordinary production API restarts do not change database structure.
- Verification did not connect to or write any real production database.

### PROD-HEALTH-001 — Production health-check semantics

- Status: `VERIFIED`
- `/health/live` is process-only. `/health/ready` checks only core readiness (database plus required local model artifacts), and returns non-200 when a core dependency is unavailable.
- Optional external providers do not participate in readiness, are not called by health checks, and do not cause all API nodes to be removed. Verification recorded `network_attempts=0`.
- Health responses do not disclose secrets or internal provider configuration; unavailable admin dependencies fail safely.

### PROD-PROV-001 — Image provenance and reproducible-build controls

- Status: `VERIFIED`
- Runtime base images are pinned by index digest; OCI `revision`, `source`, `version`, and `created` metadata are explicit build inputs; build-context and secret-exclusion controls passed static verification.
- The only valid application revision for the next API/Worker images is `93b03d5c40fb64fa264c0ada1c055f8e7696b161`. A later Handoff-only HEAD must not replace this revision.
- Runtime build evidence for the predecessor `89e3505225c9d596d6ddb26040f08b777e77823c` exists under `/opt/noteai-build/evidence-89e3505-split/`. It is a superseded baseline only: API `3 Critical / 19 High`, Worker `5 Critical / 32 High`, Secret `0` for both. No runtime build evidence yet exists for `93b03d5`; these results do not authorize a push or deployment.

### PROD-IMG-001 — Build corrected AMD64 image

- Status: `BLOCKED`. The retained isolated ECS `noteai-build-amd64-b6abaa7-r1` (`i-wz99180s9ig5ecq10uaj`) in Alibaba Cloud Shenzhen F was rechecked and used only for the approved split local build/scan. The user extended its release time; exact future lifecycle state must still be rechecked before any later task.
- Historical source/build evidence (2026-07-20): exact detached HEAD `8f7d9c23dd4c4bc951f23d2412156f121da868e7`, tree `483544cdbf5c2d7c11827ca296874f097d2969c2`, clean status, and three production V0.4 Git LFS binary SHA values equal their commit pointer OIDs. This evidence does not cover the hardened targets at `93b03d5c40fb64fa264c0ada1c055f8e7696b161`.
- Superseded historical local candidate: `noteai-local:git-8f7d9c2-amd64-r1`, `linux/amd64`, size `3,454,259,927` bytes, local image ID `sha256:47174b226ef11b704fcf92474e3f9d9bf266ef77a75e23ae4fdab99e1cfdd0f9`. This is a local Docker image ID, **not** an ACR registry digest. It must not be pushed or deployed.
- Historical acceptance: exact OCI revision/source/version/created (`2026-07-20T14:54:53Z`), non-root UID `999`, expected entrypoint/CMD, Python-stdlib live probe, `mttravel 1.0.16` and bundle SHA, four machine-manifest artifacts, no curl/Xvfb/setuptools/wheel, non-root offline headless Chromium `about:blank`, restored apt sources, no `.env`/`.git`, no sensitive ENV/history assignment, Trivy Secret `0`, CycloneDX SBOM `298` components.
- Historical remediation delta: package records fell from `75` to `39`; High fell from `68` to `32`; Critical remained `7`; unique CVE IDs became `29`; removed records `36`, added records `0`. This result belongs only to the superseded combined image.
- Historical blocking acceptance: Trivy `0.70.0` reported `32 High` and `7 Critical` for the superseded combined image. Current separate results are API `3 Critical / 19 High` and Worker `5 Critical / 32 High`; no ignore, VEX or production exception was used or registered.
- Historical evidence was retained at `/opt/noteai-build/evidence-8f7d9c2` and `/opt/noteai-build/PROD-VULN-FIX-001-evidence.tgz` (`215,209` bytes, SHA256 `e4dd0fe886c12af3a3f9e10fe50af0254829d122954fc9b9e6b383284d0984cf`). The last recorded automatic release was `2026-07-21 21:22 +08:00`; current builder/image existence must be verified and is not inferred here.
- The next build must use exact source `93b03d5c40fb64fa264c0ada1c055f8e7696b161`; do not use `89e3505`, `8f7d9c2`, `b6abaa7`, `ff030f5` or a later Handoff-only HEAD as the application revision.
- ACR inventory was not read or modified during this execution phase. No ACR login or push occurred, and the remote existence of the local candidate tag was not assumed.
- Executed scope was limited to the approved temporary isolated Alibaba Cloud Shenzhen `x86_64` builder, never API-C or API-F: clean exact checkout, local `linux/amd64` build, and local acceptance only. PROD-IMG-002, service start, database/cache access, and production cloud-service changes were excluded.
- Acceptance evidence required before any push decision, separately for `api-runtime` and `worker-runtime`: AMD64 child manifest/architecture, full OCI revision/source/version/created labels, expected role marker and owner, entrypoint/user/layers/model and role-appropriate `mttravel`/browser contents, SBOM, vulnerability scan, secret scan and an explicit release decision for every Critical or High finding.
- Cost/impact: temporary ECS compute, system disk, and dependency downloads; no paid AI/provider calls. Rollback remains deletion of the unpushed local image/build cache and release of the temporary builder, but neither deletion nor manual release was performed because both require a separate lifecycle decision.
- Only recommended next approval: `PROD-IMG-HARDENED-BUILD-001`, limited to a clean detached native AMD64 rebuild of both targets from exact `93b03d5`, complete local scans, and a non-root sandboxed Worker `about:blank` acceptance under the pinned seccomp profile. Continue to prohibit ACR, exception/VEX registration and deployment. Do **not** approve `PROD-IMG-002` while the hardened runtime evidence and formal residual decisions remain open.

### PROD-VULN-001 — Read-only vulnerability triage

- Status: `VERIFIED`
- Approved scope (2026-07-20): read-only verification of the `68 High` and `7 Critical` Trivy findings, including report integrity, duplicate findings, Debian/Python vendor fix status, candidate-image reachability, and the minimum remediation path.
- Prohibited in this task: production exception registration, image rebuild or mutation, ACR login/push, service start/redeployment, production database/cache access, cloud-resource changes, and real external-provider calls.
- Evidence integrity: report `/opt/noteai-build/evidence/trivy-vuln-high-critical.json` is `958,146` bytes with SHA256 `c71e872df48ee6de5183abbefe45735f66e2ed3423453dc7aaa9731d7783f51d`; its image ID exactly equals the live local candidate ID above. Trivy is `0.70.0`; DB metadata is version 2, updated `2026-07-20T13:19:47.192055519Z`, downloaded `2026-07-20T13:45:37.4832612Z`; the SBOM and sensitive-content scans exited `0`, while the vulnerability gate exited `1`. The scan used `HIGH,CRITICAL` plus exit code 1 and no ignore/VEX option.
- De-duplication: all `75` package findings are unique by CVE/package/version/target, but they represent `50` unique CVE IDs: `43 High` and `7 Critical`. Seventeen CVE IDs repeat across related binary packages, creating `25` extra package-level counts; examples are one util-linux CVE counted across eight binary packages, X.Org CVEs counted against both `xserver-common` and `xvfb`, and curl CVEs counted against both `curl` and `libcurl4`.
- Debian/Python fix state: the `66` Debian High records have no fixed version in the current Bookworm feed (`45 affected`, `20 fix_deferred`, `1 will_not_fix`); current installed versions for the leading families match Debian's current Bookworm package versions. The two Python High records have upstream fixes, but Trivy correctly located vulnerable vendored code inside `setuptools 79.0.1`: `jaraco.context 5.3.0` (fixed upstream in `6.1.0`) and vendored `wheel 0.45.1` (fixed upstream in `0.46.2`); the separately installed `wheel 0.46.3` does not remove the vendored copies.
- Critical reachability: no Critical was demonstrated as reachable from a normal NoteAI API request. `CVE-2023-45853` is Debian's zlib/MiniZip source-package false positive for this image: no MiniZip binary/file is installed. `CVE-2026-8376` applies to 32-bit Perl while the image is `x86_64`. `CVE-2026-42496` requires `Archive::Tar`, but that module and `perl-modules-5.36` are absent. NoteAI does not invoke Perl. `CVE-2026-13221` is additionally inconsistent in Debian's own record (Bookworm marked vulnerable while the note says introduced in Perl `5.37.10`; image is `5.36.0`) and is not treated as proven exploitable. SQLite is linked, but `CVE-2025-7458` requires attacker-controlled arbitrary SQL and the repository exposes only fixed/parameterized statements. GLib is linked by Playwright Chromium, while `CVE-2026-58016` requires malformed D-Bus introspection XML and no NoteAI D-Bus/XML input path was found. libxml2 is present through `libLLVM-15`/graphics dependencies, while `CVE-2026-6653` requires malicious XML parsing and no NoteAI XML parser/input path was found. These reachability conclusions are evidence, not a registered production exception.
- High attack-surface grouping: `20` High package findings are the uninvoked Xvfb/X.Org path; `13` are curl/libcurl/libssh2 while curl is used only for the loopback Docker health check and the application uses Python clients; `2` are setuptools vendored build-tool paths not imported by NoteAI. These `35` records are the first deterministic removal target. Remaining findings cluster in current Bookworm base utilities, XML/GLib/graphics dependencies and SQLite/Perl metadata, and require a new image plus re-scan before any acceptance decision.
- Minimum remediation path (not executed): create an API-specific runtime stage without Playwright/Xvfb/graphics packages, keep browser dependencies only in the crawler/worker image, replace the curl health check with a zero-outbound Python probe, remove runtime pip build tooling/setuptools vendored code, and re-evaluate the pinned supported base digest. Then rebuild a new local AMD64 candidate and re-run the same SBOM/secret/vulnerability/reachability gates. Any remaining vendor-unfixed finding must be resolved by a separately reviewed VEX/production-risk decision; no exception was created here.
- Stop evidence: only `--network none --read-only` disposable inspection containers were used; after audit, running containers `0`, `RepoDigests=[]`, Docker auth entries `0`. No API, provider, ACR, database/cache or cloud-resource write occurred.
- Historical release decision was superseded by PROD-VULN-FIX-001. Current `PROD-IMG-001` and `PROD-IMG-002` remain `BLOCKED`; neither local `r1` candidate may be pushed or deployed.

### PROD-VULN-FIX-001 — Minimize runtime attack surface and rebuild locally

- **Status:** `VERIFIED` on 2026-07-20.
- **Priority:** Critical while the temporary builder is retained.
- **Approved scope:** minimum Docker/runtime dependency closure, corresponding tests, one new `[skip render]` release commit and normal push of the current branch, followed by one native AMD64 local rebuild/re-scan on the existing isolated builder.
- **Proposed scope:** make only the minimum Docker/runtime dependency and related test/documentation changes described by PROD-VULN-001; independently verify them; create a new `[skip render]` release commit; then rebuild and re-scan one new native AMD64 local candidate on the existing isolated builder.
- **Repository implementation:** remove the curl-only health-probe dependency and use Python standard-library loopback probes in Docker/Compose; purge only `xvfb` and `xserver-common` after an offline Playwright Chromium `about:blank` smoke; uninstall runtime `setuptools`/`wheel` only after dependency installation; require `pip check`; retain Chromium, Playwright, OpenCV/graphics libraries, Meituan CLI and all application paths.
- **Pre-commit verification:** full unit suite `587 OK (skipped=5)`; targeted deployment/readiness tests `25 OK`; production readiness `66/66`; required model-artifact check `4/4`; quality gate passed its expected good/bad fixtures; `py_compile`, Compose parse, diff check, upstream divergence `0/0`, tracked-file sensitive-value scan and worktree scope checks passed. No service or provider was started/called.
- **Release commit:** `8f7d9c23dd4c4bc951f23d2412156f121da868e7` (`fix(prod): minimize runtime image attack surface [skip render]`) was pushed normally to `origin/codex/quality-stabilization-real-chain`; no force-push and no Render deployment occurred.
- **Independent execution evidence:** one new local native AMD64 candidate was built; offline runtime/content/provenance gates passed; the exact Trivy delta is `68→32 High`, `7→7 Critical`, `36` records removed, `0` added, Secret `0`, SBOM `327→298`. Deterministic avoidable findings are absent. Residual findings were returned without exception or suppression, satisfying this remediation task while leaving the image release task blocked.
- **Excluded:** ACR login/push, production exception/VEX acceptance, API-C/API-F start or redeployment, production database/cache access, ALB/TLS/DNS, and real provider calls.
- **Cost/limit:** existing temporary ECS is about `¥0.98748/hour` plus metered public traffic and remains scheduled for automatic release at `2026-07-21 21:22 +08:00`; no extension is authorized.
- **Acceptance:** independent tests and readiness gates pass, re-scan evidence is bound to the new exact image/release commit, deterministic avoidable findings are removed, and any residual finding is returned for a separate evidence-based decision rather than silently ignored.

### PROD-RUNTIME-SPLIT-001 — Split API and browser-worker runtimes

- **Status:** `VERIFIED` on 2026-07-21; repository implementation, independent verification and the local application release commit are complete.
- **Approved scope:** minimum Dockerfile/Python dependency split, Compose/Render role selection, startup protection, corresponding tests and necessary build specification; independent verification followed by a `[skip render]` release commit and normal branch push. Image build/pull, ACR, deployment, cloud resources, production data, real providers and VEX/exception registration remain prohibited.
- **Implementation:** added `api-runtime` and `worker-runtime` Docker targets on the pinned `python:3.11.15-slim-trixie` index; browser dependencies remain Worker-only; Compose and Render select explicit roles; the root-owned image role marker must match the runtime declaration. Missing/unreadable/empty/invalid markers, read failure, role mismatch and non-allowlisted command shapes fail closed with exit 78 before artifact loading, migration, import or execution. API and Worker use explicit command-shape allowlists, Worker defaults to `/bin/false`, and API rejects its embedded scheduler flag.
- **Independent review round 1:** a High fail-open startup-guard gap was found; the same implementation agent corrected it before re-review.
- **Independent review round 2:** the High finding was closed; a Medium false-positive risk in the readiness gate's string-only validation was found, and the same implementation agent replaced it with an offline semantic harness and mutation checks.
- **Independent review round 3:** `VERIFIED`; no Critical, High or Medium finding remained.
- **Final verification evidence:** full socket-blocked unit suite `594 OK (skipped=5)` with `network_attempts=0`; targeted readiness/deployment tests `38 OK`; production readiness `73/73`; semantic entrypoint matrix `14` allowed and `32` rejected cases; all three independently injected mutation classes failed the gate as required; shell syntax, modified Python compilation, YAML parsing, Compose quiet parse, build/readiness static checks, diff check and tracked-file/build-context secret checks passed. No Docker build/pull, container/service start, database/provider/network call or secret output occurred.
- **Release commit:** `89e3505225c9d596d6ddb26040f08b777e77823c`, parent `9bf6fcb7e9620c3ed0a831a889c0d5f34ceb6894`, message `fix(prod): split api and worker runtimes [skip render]`. It was normally pushed to `origin/codex/quality-stabilization-real-chain` without force; local and remote application SHA matched before the Handoff commit. The later Handoff-only checkpoint SHA is intentionally not invented.
- **Release rule:** exact `89e3505225c9d596d6ddb26040f08b777e77823c` is the unique application source for both role-specific images. Historical `8f7d9c2` and the old local combined image are superseded and forbidden for push/deploy. A later Handoff-only commit remains documentation provenance only.
- **Completion:** this repository task is complete. `PROD-IMG-001` remains blocked; the built local role-specific candidates require the separate residual-vulnerability decision below before any ACR task can be considered.

### PROD-IMG-SPLIT-BUILD-001 — Build and scan split native AMD64 images

- **Status:** `VERIFIED` on 2026-07-21. The authorized local build/scan scope is complete; the image release decision remains blocked by residual vulnerabilities.
- **Builder and boundary:** retained isolated native AMD64 ECS `noteai-build-amd64-b6abaa7-r1` / `i-wz99180s9ig5ecq10uaj`, Shenzhen F, `x86_64`, 4 vCPU / 16 GiB. Security-group inbound rules remained `0`; no RAM role or Docker registry config existed; the task never targeted API-C/API-F and never accessed production RDS/Tair.
- **Source and LFS:** clean detached worktree `/opt/noteai-build/repo-89e3505-exact-r3` at exact `89e3505225c9d596d6ddb26040f08b777e77823c`; production V0.4 LFS artifacts matched their pointer/manifest SHA values and human/machine manifests agreed.
- **Local candidates:** `noteai-local:git-89e3505-amd64-api-r1` (`1,042,774,445` bytes) and `noteai-local:git-89e3505-amd64-worker-r1` (`2,494,249,539` bytes). Both are `linux/amd64`, full OCI revision/source/version/created values match the authorized build inputs, and `RepoDigests` is empty. Local image IDs are preserved in evidence and are not registry digests.
- **Acceptance:** both images use non-root `noteai`, `/app/scripts/docker_entrypoint.sh`, role-correct CMD and root-owned mode `0444` `/etc/noteai-runtime-role`; live health metadata uses `/health/live`; `mttravel 1.0.16` and bundle SHA `8a0527bb6e8b9074cf0221756f35bca989945e8436e4841596a7b7bf79ae06d8` passed; three V0.4 models and human/machine release manifests passed. API contains `0` Playwright and Chromium paths; Worker contains `518` Playwright and `51` Chromium paths. Sensitive filesystem paths and history Secret-name hits are `0` for both; the allowlisted non-secret `.env.example` exists once in each image.
- **Scan execution:** Trivy `0.70.0`, DB version 2 updated `2026-07-20T13:19:47.192055519Z`; scanner containers used `--network none`, no ignore, no VEX and `--ignore-unfixed=false`. API SBOM has `174` components, Secret findings `0`, vulnerabilities `3 Critical / 19 High`. Worker SBOM has `288` components, Secret findings `0`, vulnerabilities `5 Critical / 32 High`. Raw and unique counts are equal (`22` API, `37` Worker), so duplicates are `0`; all `59` findings have no reported fixed version.
- **Critical detail:** API Criticals are `CVE-2026-13221`, `CVE-2026-42496` and `CVE-2026-8376`, all on `perl-base 5.40.1-6`. Worker has the same three plus `CVE-2026-58016` on `libglib2.0-0t64 2.84.4-3~deb13u3` and `CVE-2026-6653` on `libxml2 2.12.7+dfsg+really2.9.14-2.1+deb13u3`. This is scan evidence, not an exploitability conclusion or exception.
- **Evidence:** `/opt/noteai-build/evidence-89e3505-split/` contains build logs plus `acceptance/`, `content/` and `scans-final/`; JSON/SBOM/TSV reports and SHA256 evidence files were retained on the builder. Scanner/tool containers were removed; final running-container count is `0`; Docker registry login remains absent.
- **Prohibited:** ACR login/read/push, production exception/VEX registration, deployment, API-C/API-F or other service start, production database/Tair access, ALB/TLS/DNS or any cloud-resource mutation, production data access, and real AI/map/Meituan/crawler/payment/provider calls.
- **Stop point reached:** Critical/High findings were returned without suppression. The follow-on read-only decision is complete, but neither image is accepted. Do not push or deploy either image; do not rebuild the same Trixie candidates because the vendor feed has no fixed version for any of the `59` rows.

### PROD-SPLIT-VULN-DECISION-001 — Review residual split-image findings

- **Status:** `VERIFIED` on 2026-07-21; the authorized read-only decision audit is complete. This verifies the analysis, not release acceptance.
- **Priority:** Critical release gate.
- **Evidence integrity:** Cloud Assistant invocations `t-sz06rk69xqngjy8` and `t-sz06rk6e96yzh8g` succeeded with exit `0` on builder `i-wz99180s9ig5ecq10uaj`. The retained TSV still contains `59` rows and `59` unique CVE/package/version/role records: API `22` (`3 Critical / 19 High`) and Worker `37` (`5 Critical / 32 High`), duplicate rows `0`. Final running-container count remained `0`; the read-only gate printed `PASS_READ_ONLY`.
- **Unique-CVE map:** API has `11` unique CVEs across ncurses (`CVE-2025-69720`), Perl/Archive::Tar/IO::Compress (`CVE-2026-13221`, `42496`, `42497`, `48962`, `57432`, `8376`, `9538`), gzip (`41992`), util-linux (`53615`) and libacl (`54369`). Worker contains those same base rows plus `15` browser-dependency rows: six Expat CVEs (`CVE-2025-59375`, `CVE-2026-25210`, `45186`, `56131`, `56407`, `56408`), CUPS `CVE-2026-34980`, seven GLib CVEs (`CVE-2026-58010` through `58016`) and libxml2 `CVE-2026-6653`. Across both roles this is `26` unique CVE IDs.
- **Vendor state:** all `59` rows have an empty scanner fixed version for installed Trixie packages, consistent with the current Debian tracker. Same-base `apt upgrade` or a same-digest rebuild therefore cannot clear the gate. Bookworm is also vulnerable for the audited families. Forky/Sid fixes some ncurses, Perl, Expat, CUPS, GLib, libxml2 and acl issues, but is not a stable production base and still leaves `CVE-2026-13221`, `CVE-2026-42496/42497`, `CVE-2026-41992`, `CVE-2026-53615`, `CVE-2026-58016` and `CVE-2026-9538` unfixed; it is not an evidence-backed drop-in solution.
- **API reachability:** repository inspection at exact `89e3505225c9d596d6ddb26040f08b777e77823c` found no application invocation of Perl, Archive::Tar, IO::Compress, `infocmp`, gzip decompression, blkid/partition parsing or libacl pathname APIs. The API image is `linux/amd64`, so 32-bit-only `CVE-2026-8376` is architecture-not-applicable. The remaining API rows are package-present with no demonstrated application input path, but static grep alone is insufficient to register `not_affected`; no VEX or exception was created.
- **Historical Worker reachability at `89e3505`:** CUPS `CVE-2026-34980` requires a network-exposed `cupsd` with a shared queue, while the image contains only the Chromium dependency library and configures no print server. The Perl/base CLI paths are likewise not invoked by NoteAI. The Expat/GLib/libxml2 rows cannot receive a blanket `not_affected`: Chromium may load these libraries and the Worker intentionally visits untrusted web pages. At that revision Playwright defaulted `chromium_sandbox` to false; `scheduler_a.py` explicitly passed `--no-sandbox` and could add `--no-zygote`; no Compose seccomp existed. This blocker was corrected in repository release `93b03d5`, but runtime proof still requires a new approved build and sandbox smoke.
- **Alternative-base decision:** retaining Trixie or reverting to Bookworm does not fix the findings; Forky/Sid is unstable and incomplete; Alpine is unsupported by Playwright's glibc browser builds and conflicts with the Python native-wheel stack; a distroless API would require replacing the shell entrypoint and packaged Node CLI; the matching Microsoft Playwright image is an evaluation candidate only, not an automatic production fix, because its own official guidance warns against untrusted-site use without sandbox controls and its vulnerability posture has not been scanned for this application.
- **Formal VEX path:** API is a candidate for a separate independent VEX evidence review using immutable image identity, SBOM component/version, package ownership, ELF/linkage and command/input-path proof for each CVE. Any eventual `not_affected` statement must use an evidence-backed justification, have expiry/re-review conditions and be bound to the final immutable image digest. Worker is not eligible for a blanket VEX while untrusted browsing runs without the Chromium sandbox; browser-library rows require stronger binary/call-path evidence even after hardening. No VEX document, suppression or production exception was produced or registered in this task.
- **Minimum safe path:** first correct Worker sandboxing without changing business behavior: remove explicit `--no-sandbox`, set `chromium_sandbox=True` for every launch, keep the non-root user, add a reviewed seccomp/runtime profile and fail-closed tests, while preserving Render Staging behavior. In the same bounded task, collect offline package-ownership and ELF/linkage evidence from both existing local images without starting an application or making network calls. Then create a new release commit and, only after separate approval, rebuild/re-scan both targets. Residual API and Worker CVEs may proceed to independent formal VEX review only after that evidence exists.
- **Prohibited and observed stop point:** no image rebuild, ACR login/read/push, production exception/VEX registration, deployment/service start, production data/dependency access, cloud-resource mutation or real provider call occurred. Both current local images and `PROD-IMG-002` remain `BLOCKED`.
- **Completion transition:** the recommended `PROD-WORKER-HARDEN-001` was separately approved and is now independently `VERIFIED` below. The next task is the bounded hardened rebuild/runtime gate; ACR, production exception/VEX registration, deployment, production access, cloud mutation and real provider calls remain prohibited.

### PROD-WORKER-HARDEN-001 — Enforce Worker Chromium sandbox

- **Status:** `VERIFIED` on 2026-07-21. Repository implementation, independent verification, offline evidence collection and the `[skip render]` application release commit are complete.
- **Release commit:** `93b03d5c40fb64fa264c0ada1c055f8e7696b161`, parent `5ba202febaff364328057a7f8a1ca41f72816a47`, message `fix(prod): harden worker chromium sandbox [skip render]`. It was normally pushed to `origin/codex/quality-stabilization-real-chain`; local/remote divergence was `0/0` before this Handoff checkpoint. This exact application SHA, not a later Handoff-only HEAD, is the unique source for the next rebuild.
- **Launch enforcement:** all five Python Chromium launch points (`crawler.py` two, `scheduler_a.py` one, `download_covers.py` two) use `model/chromium_security.py`. The helper forces `chromium_sandbox=True`, rejects `--no-sandbox`, `--disable-setuid-sandbox` and `--no-zygote` before Playwright is called, and never retries a failed sandbox launch with weaker settings. The obsolete Render low-memory/no-zygote switch was removed.
- **Runtime boundary:** Worker remains `USER noteai`. Docker image creation no longer launches Chromium as root and checks only that Playwright resolves an installed executable. Compose applies `no-new-privileges:true` and the same seccomp profile to Admin, trends-worker and tracking-worker; API is excluded. No `privileged`, `SYS_ADMIN`, `seccomp=unconfined` or capability addition was introduced.
- **Seccomp provenance:** complete upstream Playwright v1.56.0 profile at `deploy/security/playwright-chromium-seccomp-v1.56.0.json`, `12,997` bytes, SHA256 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`, `defaultAction=SCMP_ACT_ERRNO`, includes `SCMP_ARCH_X86_64` and the reviewed `clone`/`setns`/`unshare` allow rule. Render Blueprint has no reviewed custom-seccomp field; no unsupported field or sandbox bypass was invented.
- **Offline existing-image evidence:** Cloud Assistant invocations `t-sz06rkcdpibjyf4` and `t-sz06rkck2fakagw` completed with exit `0` on isolated builder `i-wz99180s9ig5ecq10uaj`. Stopped containers created with `--network none` were used only for file extraction; no image process was run. Package ownership and direct ELF `NEEDED` evidence for the existing API image ID `sha256:c44730a50e4ae873ba9b77f56bbb79c8bc573c1e8177da79c9b727c6c17707f1` and Worker image ID `sha256:b299d5f3ef5dc639a2b1611b0e7f46731f0eb9b0451ea540e0e4600423bf6fd8` was retained under the builder's timestamped `/opt/noteai-build/worker-hardening-evidence.*` directory. Worker browser paths include Playwright Chromium `1194`; direct ELF evidence starts with `libdl.so.2` and `libpthread.so.0`. This evidence does not prove complete transitive exploitability or non-exploitability.
- **Boundary evidence:** running containers before/after remained `0`; `/root/.docker/config.json` remained absent. No Secret was read or printed, no ACR login/read/push occurred, and no production database/cache/cloud resource or external provider was accessed.
- **Independent verification:** `87/87` targeted tests; full suite `601` passed with `5` skipped; production readiness `78/78`; seccomp hash/JSON semantics, all launch paths, fail-closed behavior, non-root Dockerfile, Compose role coverage, Render boundary, `py_compile`, Compose quiet parse, diff check and changed-file Secret scan passed. The independent verifier found no Critical/High/Medium/Low implementation defect. The full-suite `moonshot network error` text was a mocked failure path, not a real supplier call.
- **Remaining release gates:** no image build or browser process start was permitted here. A later approved native AMD64 build must prove a non-root Chromium `about:blank` launch under the exact seccomp and `no-new-privileges`, then repeat SBOM, Secret, content and High/Critical scans for both targets. Render requires separate sandbox compatibility and memory observation after removal of `--no-zygote`. These gates block ACR and deployment but do not invalidate this repository release.
- **Only recommended next approval:** `PROD-IMG-HARDENED-BUILD-001`: read-only recheck the existing isolated builder, then from a clean detached exact `93b03d5c40fb64fa264c0ada1c055f8e7696b161` perform one native AMD64 local rebuild of `api-runtime` and `worker-runtime`, complete provenance/content/SBOM/Secret/vulnerability scans, and a non-root sandboxed Worker smoke under the pinned seccomp. Continue to prohibit ACR login/push, production exception/VEX registration, deployment, production data/cloud access and real supplier calls.

### PROD-IMG-HARDENED-BUILD-001 — Build and scan hardened split images

- **Status:** `READY_TO_EXECUTE`, but no execution is authorized until the user explicitly approves this exact task.
- **Priority:** Critical release gate.
- **Prerequisites:** read-only confirmation that isolated builder `i-wz99180s9ig5ecq10uaj` still exists and retains inbound rules `0`, no RAM role, no registry auth and no production-data network path; clean detached checkout at exact `93b03d5c40fb64fa264c0ada1c055f8e7696b161`; complete production Git LFS SHA validation.
- **Execution:** native `linux/amd64` local builds of `api-runtime` and `worker-runtime`; exact OCI provenance; role/content/model/mttravel checks; CycloneDX SBOM; filesystem/history Secret scan; unsuppressed High/Critical scan; Worker non-root `about:blank` smoke with `no-new-privileges` and the vendored seccomp profile whose SHA is recorded above.
- **Prohibited:** ACR login/read/push, production exception/VEX registration, deployment/service start, API-C/API-F changes, production database/Tair access, ALB/TLS/DNS/cloud-resource mutation and real AI/map/Meituan/crawler/payment calls.
- **Risk/cost:** existing temporary ECS compute and metered dependency traffic; a sandbox incompatibility or changed vulnerability set must fail the task closed. No provider charge is expected.
- **Rollback:** remove only new unpushed local image/build-cache objects if separately approved; retain the builder and evidence until the next release decision or its configured automatic release. Accidental builder release requires rebuilding from exact commit; local image IDs are never ACR digests.
- **Acceptance:** both images are exact native AMD64 revision `93b03d5`; API remains browser-free; Worker remains non-root and proves sandboxed Chromium start under the exact profile; SBOM/Secret/content/provenance evidence is complete; every Critical/High is returned unsuppressed for the next independent decision. Stop before ACR.
- **User approval:** required before any build command.

### PROD-IMG-002 — Push to ACR and verify digest

- **Status:** `BLOCKED`
- **Priority:** Critical
- **Current evidence:** two superseded split AMD64 candidates exist at predecessor revision `89e3505`; no image exists for hardened revision `93b03d5`. No production exception/VEX or ACR registry digest exists.
- **Prerequisites:** a separately approved native AMD64 rebuild/re-scan from exact `93b03d5`, successful non-root sandbox runtime acceptance under the pinned seccomp, an independent role-specific residual/VEX decision, explicit release acceptance of both images, and an approved ACR access window; public access remains closed except an explicitly approved, time-bounded exception.
- **Execution steps:** push once; close any temporary public route; read back manifest/index; record immutable digest and platform; compare remote/local metadata.
- **Risk:** wrong repository/tag, mutable overwrite, public exposure, partial multi-arch manifest.
- **Rollback:** close temporary access and leave the untrusted tag unused; do not delete remote content without separate approval.
- **Acceptance:** ACR read-back proves a single allowed `linux/amd64` manifest for exact revision and records its immutable digest; independent auditor concurs.
- **Real call:** yes, ACR push/read.
- **Possible cost:** storage and network egress.
- **User approval:** required.

### PROD-IMG-003 — Verify revision, architecture, artifacts, mttravel and Secret handling

- **Status:** `BLOCKED`
- **Priority:** Critical
- **Current evidence:** old AMD64 image lacks the latest packaging; same-revision image is ARM64; runtime secret entry occurred but values must not be read or copied.
- **Prerequisites:** PROD-IMG-002 digest; read-only image and node inspection plan.
- **Execution steps:** inspect digest/platform/labels; verify revision; verify required model artifacts by name/hash; verify `mttravel` executable and runtime dependency; verify only required secret key names and file permissions, never values; scan image history for secret leakage.
- **Risk:** supply-chain mismatch, missing artifacts, secrets in layers/logs, nonfunctional provider CLI.
- **Rollback:** reject the digest and return to PROD-IMG-001; do not deploy.
- **Acceptance:** independent supply-chain report confirms exact revision, AMD64, model artifacts, executable `mttravel`, required runtime configuration interface and no secret exposure.
- **Real call:** image/registry reads only; no provider call.
- **Possible cost:** negligible registry/network reads.
- **User approval:** required if cloud access or temporary network change is needed.

### PROD-API-001 — Start API-C

- **Status:** `BLOCKED`
- **Priority:** Critical
- **Current evidence:** API-C ECS was running; application was not accepted on the corrected digest.
- **Prerequisites:** PROD-IMG-003; immutable approved digest; read-only node/service audit; approved deployment plan with rollback.
- **Execution steps:** pull by digest; preserve prior service definition; start one API-C service serially; collect redacted service status and bounded logs; do not call paid providers.
- **Risk:** startup failure, database/schema mismatch, secret exposure, unintended external calls.
- **Rollback:** stop the new service and restore the previous inactive configuration; do not deploy a forbidden image.
- **Acceptance:** service remains active, uses the approved digest, restarts cleanly, and exposes no secrets in logs.
- **Real call:** production host/container/DB connection; no paid AI.
- **Possible cost:** existing compute plus registry traffic.
- **User approval:** required for production write/start.

### PROD-API-002 — Complete API-C zero-AI readiness

- **Status:** `BLOCKED`
- **Priority:** Critical
- **Current evidence:** no accepted production API-C readiness result exists.
- **Prerequisites:** PROD-API-001; health-check plan that suppresses paid provider calls and business writes.
- **Execution steps:** verify live/readiness, database schema/connectivity, cache behavior if enabled, file/model loading, Gateway configuration consistency and redacted logs; exercise only zero-AI probes.
- **Risk:** readiness falsely succeeding while dependencies fail; accidental provider charge; sensitive log output.
- **Rollback:** mark API-C unavailable and stop service if unsafe; no DNS/ALB exposure.
- **Acceptance:** repeated live/readiness HTTP 200, dependencies required for zero-AI startup healthy, no paid AI call and no secret/log leakage; independent Test & Readiness Auditor signs off.
- **Real call:** production health/DB/cache reads; no AI call.
- **Possible cost:** existing cloud compute/database usage.
- **User approval:** required before production probes that touch controlled services.

### PROD-EXT-001 — Verify Kimi

- **Status:** `BLOCKED`
- **Priority:** High
- **Current evidence:** production key name was entered, but value correctness and end-to-end invocation are unverified.
- **Prerequisites:** PROD-API-002; Live Run Plan with one bounded synthetic request, token/cost cap and data impact.
- **Execution steps:** invoke one minimal non-sensitive synthetic request; verify response, timeout, usage record and cost accounting; redact identifiers.
- **Risk:** charge, wrong credential, data leakage, duplicate billing.
- **Rollback:** disable provider path and leave API-C internal; no retry storm.
- **Acceptance:** one successful bounded call with reconciled provider usage and internal cost record, or a documented safe failure with no repeated charge.
- **Real call:** yes, paid Kimi/Moonshot.
- **Possible cost:** capped AI usage.
- **User approval:** explicit approval required immediately before the call.

### PROD-EXT-002 — Verify Claude Gateway

- **Status:** `BLOCKED`
- **Priority:** High
- **Current evidence:** Render production Gateway live/readiness is healthy and zero-Claude signed checks passed; Alibaba API end-to-end call is unverified.
- **Prerequisites:** PROD-API-002; signed configuration consistency check; Live Run Plan with one capped Claude request.
- **Execution steps:** send one non-sensitive synthetic request through API-C to the production Gateway; verify HMAC/authentication, request admission/idempotency, response, timeout and usage/cost records.
- **Risk:** charge, signature/epoch mismatch, replay, duplicate provider request, sensitive logs.
- **Rollback:** disable Gateway transport on API-C and keep production unexposed.
- **Acceptance:** one bounded end-to-end request succeeds through the intended Gateway instances with reconciled usage and no secret/log exposure.
- **Real call:** yes, paid Claude.
- **Possible cost:** capped Claude usage.
- **User approval:** explicit approval required immediately before the call.

### PROD-EXT-003 — Verify Amap

- **Status:** `BLOCKED`
- **Priority:** High
- **Current evidence:** production key name was entered, but end-to-end invocation is unverified.
- **Prerequisites:** PROD-API-002; Live Run Plan with one bounded synthetic query and quota impact.
- **Execution steps:** execute one allowed non-sensitive query; verify structured evidence, timeout/error handling and quota accounting.
- **Risk:** quota consumption, wrong environment, sensitive query logs.
- **Rollback:** disable provider path; do not retry automatically.
- **Acceptance:** one valid response is parsed into the expected fixed schema with no secret exposure and bounded quota use.
- **Real call:** yes, Amap.
- **Possible cost:** quota/usage charge depending on account plan.
- **User approval:** explicit approval required immediately before the call.

### PROD-EXT-004 — Verify Meituan

- **Status:** `BLOCKED`
- **Priority:** High
- **Current evidence:** `ff030f5` packages the Meituan travel CLI; the production image and actual node executable are not yet verified; token key name was entered but not validated.
- **Prerequisites:** PROD-IMG-003 and PROD-API-002; policy/permission confirmation; Live Run Plan with one bounded allowed query.
- **Execution steps:** verify CLI installation/version without exposing credentials; perform one non-sensitive allowed query; verify parsing, timeout and error handling.
- **Risk:** unavailable CLI, token failure, quota/contract violation, sensitive output.
- **Rollback:** disable Meituan provider and retain zero-AI readiness.
- **Acceptance:** production node can execute the packaged CLI and one bounded allowed request returns expected structured evidence without secret leakage.
- **Real call:** yes, Meituan service.
- **Possible cost:** quota/contract usage.
- **User approval:** explicit approval required immediately before the call.

### PROD-API-003 — Deploy API-F

- **Status:** `BLOCKED`
- **Priority:** High
- **Current evidence:** API-F ECS existed but application was not deployed.
- **Prerequisites:** API-C readiness and all required provider decisions; approved immutable digest from PROD-IMG-002; API-C rollback evidence.
- **Execution steps:** deploy serially by immutable digest, never mutable tag; verify service and zero-AI readiness; keep out of ALB until independently accepted.
- **Risk:** inconsistent replicas, wrong digest, database concurrency, secret/config drift.
- **Rollback:** stop API-F service and retain accepted API-C only.
- **Acceptance:** API-F matches API-C digest/config contract, passes repeated zero-AI readiness and exposes no secret in logs; independent verification complete.
- **Real call:** production host/DB/cache reads; no paid AI during readiness.
- **Possible cost:** existing compute and registry traffic.
- **User approval:** required for production deployment/start.

### PROD-ALB-001 — Create and configure ALB

- **Status:** `BLOCKED`
- **Priority:** High
- **Current evidence:** no completed ALB resource/configuration evidence.
- **Prerequisites:** PROD-API-002 and PROD-API-003; cloud inventory audit; listener/backend/health/fee/rollback plan.
- **Execution steps:** create ALB and target groups; add only accepted API-C/API-F backends; configure health checks and HTTP-to-HTTPS policy without DNS cutover.
- **Risk:** recurring fees, public exposure, bad health routing, unintended traffic.
- **Rollback:** remove backends/disable listeners while retaining resources; resource deletion requires separate approval.
- **Acceptance:** both accepted backends healthy, unhealthy-node removal works, no business DNS points to ALB and security groups allow only intended paths.
- **Real call:** yes, Alibaba control-plane writes.
- **Possible cost:** ALB hourly/LCU/public network charges.
- **User approval:** explicit cost and resource-change approval required.

### PROD-TLS-001 — Bind three TLS certificates

- **Status:** `BLOCKED`
- **Priority:** High
- **Current evidence:** certificates are issued for root, API and Admin domains but not deployed.
- **Prerequisites:** PROD-ALB-001; certificate validity/hostname read-only audit; listener mapping plan.
- **Execution steps:** bind the correct certificate to each HTTPS hostname/listener; configure modern TLS policy; verify chain/SNI without DNS cutover.
- **Risk:** wrong certificate/hostname, downtime, weak policy, renewal gap.
- **Rollback:** restore prior listener certificate mapping or disable listener; do not delete certificates.
- **Acceptance:** independent SNI/chain/expiry verification succeeds for all three hostnames against the ALB endpoint.
- **Real call:** Alibaba control-plane writes and TLS probes.
- **Possible cost:** certificates already paid; ALB usage may accrue.
- **User approval:** required for production listener mutation.

### PROD-DNS-001 — Execute DNS cutover

- **Status:** `BLOCKED`
- **Priority:** Critical
- **Current evidence:** enterprise DNS is paid/bound; production business records are not cut over.
- **Prerequisites:** all image/API/ALB/TLS acceptance complete; production smoke prechecks; authoritative DNS plan, TTL, rollback target and explicit go-live approval.
- **Execution steps:** publish only approved root/API/Admin records serially; verify authoritative answers outside proxy fake-IP DNS; monitor errors and traffic.
- **Risk:** public outage, split routing, certificate mismatch, irreversible user impact during TTL.
- **Rollback:** restore documented prior records and monitor propagation; do not delete the DNS zone.
- **Acceptance:** authoritative resolvers return intended endpoints, HTTPS works for all hostnames, monitored error rate is within release threshold and rollback remains tested.
- **Real call:** yes, public DNS control-plane write and real user-routing impact.
- **Possible cost:** DNS queries and production traffic.
- **User approval:** separate explicit cutover approval required after all prerequisites pass.

### PROD-SMOKE-001 — Execute production smoke test

- **Status:** `BLOCKED`
- **Priority:** Critical
- **Current evidence:** no complete production smoke test exists.
- **Prerequisites:** PROD-DNS-001 or an approved pre-DNS ALB test path; synthetic accounts/data; Live Run Plan with exact writes, provider-call cap, cost and cleanup policy.
- **Execution steps:** test public web/API/Admin authentication and authorization, core generation/diagnosis paths, attachments within policy, provider calls already approved, billing records in non-payment mode, failure/recovery and both API nodes.
- **Risk:** production data writes, AI charges, account lockout, duplicate billing, user exposure.
- **Rollback:** stop smoke traffic, disable affected route/provider and execute only preapproved synthetic-data cleanup; no destructive database cleanup.
- **Acceptance:** documented checklist passes with traceable request IDs, correct authorization/billing behavior, no new Critical/High defect and independent verifier evidence.
- **Real call:** yes; may include capped AI and synthetic production writes.
- **Possible cost:** AI, cloud traffic and storage.
- **User approval:** explicit approval required immediately before execution.

### PROD-PAY-001 — Validate payment callback and reconciliation

- **Status:** `DEFERRED`
- **Priority:** Critical before commercial charging
- **Current evidence:** real end-user payment callback/settlement/reconciliation is not implemented or verified; cloud-resource purchases are unrelated.
- **Prerequisites:** payment provider contract/configuration, product refund/reconciliation rules, security review, idempotency tests, sandbox/test-mode plan and legal/business approval.
- **Execution steps:** first validate signatures, idempotent callback, order state, refunds and reconciliation in sandbox/test mode; real-money validation requires a separate release package and approval.
- **Risk:** financial loss, duplicate credit, refund error, compliance and real-user impact.
- **Rollback:** disable payment entry/callback route and reconcile test orders; never delete financial records.
- **Acceptance:** sandbox/test transactions reconcile exactly, duplicate callbacks are idempotent, refund and exception ledger are auditable, Security and Finance verification complete.
- **Real call:** no real payment is authorized by this handoff.
- **Possible cost:** provider/test fees may apply; real funds prohibited until separately approved.
- **User approval:** mandatory product, finance and explicit live-payment approval.

### Deferred existing backlog

These items remain in the same unique ledger but must not interrupt the production recovery sequence unless a Critical safety issue emerges.

| ID / title | Status | Priority | Current evidence | Prerequisites | Execution steps | Risk | Rollback | Acceptance | Real call | Possible cost | User approval |
|---|---|---|---|---|---|---|---|---|---|---|---|
| LEGACY-XHS-001 — XHS acquisition/account-policy recovery | `DEFERRED` | High | Collection failures correlated with platform logout/account restriction; no compliant stable source is accepted. | Product/legal source decision and platform-compliant access. | Read-only source audit; no anti-detection, account pool, proxy rotation or challenge bypass. | Account restriction, policy breach, bad evidence. | Keep scheduler disabled/degraded and preserve diagnostics. | Compliant source produces independently verified evidence without account-policy evasion. | Potential external collection. | Provider/quota cost. | Required before any collection. |
| LEGACY-CAP-001 — 100 concurrent AI users capacity | `DEFERRED` | High before scale | Gateway scale rehearsal exists; end-to-end application/provider limits are not proven. | Production functional acceptance, provider quota and budget. | Design/load-test plan using synthetic traffic, queue/backpressure and no uncontrolled provider calls. | Cost spike, outage, rate limits. | Stop load generator and scale back within approved bounds. | Measured SLO/capacity and provider limits support the target with alerts. | Possibly provider/load calls. | Potentially high. | Required. |
| LEGACY-SEC-004 — Historical reasoning retention cleanup | `DEFERRED` | High before broad release | Explainable-agent experience is retained; historical raw-reasoning persistence risk remains a separate task. | Data inventory, retention policy and legal/security decision. | Read-only inventory, then separately approved non-destructive migration/cleanup plan. | Privacy/data loss. | Backup and reversible migration only. | No raw private reasoning is unnecessarily persisted; user-facing explanations remain. | No external call expected. | Storage/engineering. | Required before data mutation. |
| LEGACY-BILL-002 — SSE interruption recovery | `DEFERRED` | High | Recovery design/testing is incomplete. | Stable production API and idempotency design. | Reproduce disconnects, define terminal state/resume semantics, implement separately. | duplicate work/cost. | Feature flag or revert single package. | Disconnect/reconnect recovers without duplicate AI charge or lost terminal result. | Test AI may be needed. | Capped AI cost. | Required before paid test. |
| LEGACY-QA-003 — Remaining manual UI acceptance | `DEFERRED` | Medium | Partial UI acceptance exists; remaining checklist is not fully closed. | Stable production/staging candidate. | Complete synthetic manual checklist and record screenshots/results without secrets. | missed UX regression. | Revert isolated UI package if needed. | All listed UI flows pass on supported viewport/browser. | No paid call by default. | None/minimal. | Only if a paid flow is included. |

## 6. Test and evidence baseline

- Historical prebuild revision `b6abaa781c11950c4d261e8d9f17c3194aecd0cf` passed `586 OK (skipped=5)` full tests and `278 OK` targeted tests.
- Historical combined-image revision `8f7d9c23dd4c4bc951f23d2412156f121da868e7` passed `587 OK (skipped=5)` full tests, `25 OK` targeted deployment/readiness tests, production readiness `66/66`, quality gate, `py_compile`, Compose parse and tracked-file sensitive-value checks; it is superseded and must not be pushed or deployed.
- Current split-runtime release revision `89e3505225c9d596d6ddb26040f08b777e77823c` passed the independent repository gates: socket-blocked full suite `594 OK (skipped=5)`, `network_attempts=0`, targeted tests `38 OK`, readiness `73/73`, semantic entrypoint matrix `14` allowed / `32` rejected, and three mutation classes rejected; shell, Python compilation, YAML, Compose, diff and secret/build-context checks passed.
- Current hardened application release `93b03d5c40fb64fa264c0ada1c055f8e7696b161` passed independent repository gates: full suite `601 OK (skipped=5)`, targeted `87/87`, production readiness `78/78`, seccomp SHA/semantics, launch fail-closed tests, Python compilation, Compose quiet parse, diff and changed-file Secret scan. No image was built or process started for this revision.
- Model integrity passed human manifest `8/8`, machine manifest `4/4`, and Git LFS artifact `3/3` checks.
- `py_compile`, Docker Compose/static configuration, diff, secret, and build-context checks passed.
- The superseded combined local native AMD64 candidate remains blocked at SBOM `298`, Secret `0`, `32 High / 7 Critical`. The current split candidates were separately built and accepted: API SBOM `174`, Secret `0`, `3 Critical / 19 High`; Worker SBOM `288`, Secret `0`, `5 Critical / 32 High`. Both remain local-only and blocked.
- No image was pushed, no ACR registry digest exists, and no service, database/cache, cloud resource, or external provider was invoked by this checkpoint.
- Render public live/readiness checks listed in section 3 were rerun on 2026-07-20.
- Alibaba production application readiness, provider calls, ALB/TLS/DNS and payment checks have not passed; no task may be promoted to `VERIFIED` from historical narration alone.

## 7. Mandatory safety boundaries

All future sessions and all agents must obey:

- 不输出 Secret、Token、密码、私钥、Cookie 或完整连接字符串；
- 不读取或复制受控环境文件中的真实值；
- 不把 Secret 写入镜像、日志、Handoff、Git 或命令输出；
- 不使用 ARM64 镜像部署 x86 ECS；
- 不使用可变标签替代不可变 digest 进行 API-F 部署；
- 不执行数据库破坏性操作；
- 不导入 Staging 数据到生产；
- 不删除 RDS、Tair、ECS、ACR、ALB、证书、DNS 或其他资源；
- 不 force push；
- 不直接合并 main/master；
- 不切换 DNS，除非前置验收全部通过并获得明确批准；
- 不执行真实支付；
- 不进行大规模真实爬取；
- 不进行未经批准的高费用 AI 调用；
- 所有真实外部调用前必须输出 Live Run Plan；
- 所有云资源变更前必须说明对象、影响、费用、回滚方法；
- 所有生产写操作必须串行执行；
- 不允许多个 Subagents 同时修改同一云资源或同一代码区域。

Additional release controls:

- Do not expose or copy values from production environment files. Validate only key names, permissions, redacted fingerprints or provider-side results.
- Do not use `git-ff030f5`, `git-ff030f5-amd64-r2`, `git-ecc4702e`, `git-b6abaa7-amd64-r1`, `git-8f7d9c2-amd64-r1`, either `git-89e3505` local candidate, `latest`, or any unverified tag for production. The only permitted application source for the next build is exact revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161`. No local image exists for it and no ACR registry digest exists.
- Do not let execution agents work until the read-only audit stage has reconciled Git, ACR, ECS, RDS/Tair, networking, Render, TLS and DNS truth.
- Do not repeat already completed domain/certificate purchases, clean RDS schema migration, or production Gateway creation.
- Any status discrepancy stops execution and returns the affected task to `INVESTIGATING`.

## 8. Recommended new-session orchestration

Roles:

1. **Main Codex — CTO / Production Release Orchestrator:** owns the ledger, sequencing, approvals, evidence review and final independent acceptance.
2. **Repository & Git Auditor — read-only:** verifies branch, HEAD, worktree, commits, CI, deployment descriptors and code/revision relationships.
3. **Image & Supply Chain Auditor — read-only:** verifies ACR tags/digests/platforms, Docker metadata, model artifacts, `mttravel`, Git LFS and secret-free image history.
4. **Cloud Infrastructure Auditor — read-only:** verifies ECS/API services, RDS, Tair, VPC/routes/security groups, SNAT, PrivateZone, ACR access, ALB, TLS, DNS, billing inventory and traffic evidence.
5. **Test & Readiness Auditor — read-only:** identifies the minimum zero-AI checks, provider-call acceptance tests, smoke scope and regression evidence.
6. **Security Reviewer — read-only when needed:** reviews auth/admin/billing/payment, secret handling, logs, Gateway signatures, uploads and production exposure.

Repository/Git, image supply chain, cloud infrastructure and test/readiness audits may run in parallel because they are read-only and have distinct evidence boundaries. All production writes, image push, service starts, external provider calls, ALB/TLS changes, DNS changes and payment work must run serially. No Implementation or execution agent may start until the read-only auditors return structured evidence and the Main Codex marks the exact task `READY_TO_EXECUTE` with an approved plan.

## 9. New-session startup procedure

Read these files first:

1. `AGENTS.md`
2. `.codex/handoffs/current-task.md`
3. `.codex/notes/architecture-summary.md`
4. `.codex/notes/risk-register.md`
5. `docs/RENDER_DEPLOYMENT_GUIDE.md`
6. `docs/DEPLOYMENT_SECRETS.md`
7. `render.yaml`
8. `render.gateway.production.yaml`
9. `Dockerfile`
10. `tools/production_readiness_gate.py`

Then:

1. Verify the current branch and exact application build source `93b03d5c40fb64fa264c0ada1c055f8e7696b161` independently of any later Handoff-only HEAD; also verify upstream divergence and worktree state.
2. Verify that any Handoff checkpoint commit contains only documentation, uses `[skip render]`, and did not trigger Render deployment.
3. Dispatch the four mandatory read-only auditors above; use the Security Reviewer if any credential, auth, billing, public exposure or image-layer concern appears.
4. Treat the historical `32 High / 7 Critical` evidence only as the superseded combined-image baseline. Use the separate current scan reports under `/opt/noteai-build/evidence-89e3505-split/scans-final/` for API (`3 Critical / 19 High`) and Worker (`5 Critical / 32 High`); do not silently suppress, merge or project one role's result onto the other.
5. Keep **PROD-IMG-001** and **PROD-IMG-002** blocked. The completed hardening task does not authorize a rebuild, any exception/VEX, ACR access or deployment. The only recommended next approval is `PROD-IMG-HARDENED-BUILD-001` as defined in the task ledger.
6. Permit an execution agent only after root cause/state is confirmed, modification scope is minimal, task is `READY_TO_EXECUTE`, acceptance/rollback are documented, and the user has approved cost/production impact.
7. Stop immediately on secret exposure, architecture mismatch, untracked cloud mutation, unverifiable digest, unexpected production traffic, failed zero-AI readiness, or any need to broaden scope.

The next session must not repeat the completed production Gateway creation, domain/DNS purchase, certificate purchase/issuance, clean RDS schema migration, prior ARM64 push, `b6abaa7` build, `8f7d9c2` remediation rebuild, split build/scan, residual decision audit, offline hardening evidence collection or repository sandbox correction. Its recommended next approval is `PROD-IMG-HARDENED-BUILD-001`; ACR access/push, exception/VEX registration and deployment remain prohibited.

## 10. Checkpoint condition

The application release candidate `93b03d5c40fb64fa264c0ada1c055f8e7696b161`, parent `5ba202febaff364328057a7f8a1ca41f72816a47`, message `fix(prod): harden worker chromium sandbox [skip render]`, was normally pushed to `origin/codex/quality-stabilization-real-chain` without force. Local and remote application SHA matched before the Handoff commit. This Handoff-only update is documentation provenance; its commit SHA is intentionally unknown until the next pure-documentation checkpoint commit exists, and it must never replace the application revision in image metadata. That checkpoint must use `[skip render]`, push normally to the existing tracking branch, never force-push, and must not trigger any image build, ACR access, deployment, database access, cloud change or provider call.
