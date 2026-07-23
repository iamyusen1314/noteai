# NoteAI Production Rollout Handoff

> Updated: 2026-07-23 (Asia/Shanghai)
>
> Scope: completed `PROD-IMG-002` for the exact `a635692a899ee02c6905cd694611c14e0da4594a` native AMD64 `api-runtime`, `admin-runtime` and `xhs-http-runtime` candidates. The three role-specific immutable tags were pushed once to private ACR repository `noteai/app`, read back as `linux/amd64` with the exact OCI revision/source/version/created labels, and rebound in CycloneDX 1.6 VEX version 2 to their actual registry manifest digests. The prior independent twelve-CVE disposition review and all 69 package BOM-Link assertions remain unchanged; canonical raw Trivy reports remain unsuppressed at `4 Critical / 19 High` per role. ACR logout succeeded, builder CIDR `47.107.35.208/32` was removed, the ACR public endpoint and ECS Session Manager were disabled, and no security-group ingress, deployment, service, database, ALB, TLS, DNS, production data or supplier call occurred.
>
> Evidence precedence: current Git/CI and public health checks > current cloud control-plane reads > previously captured control-plane evidence > conversation recollection. Anything not re-observed after the interruption is explicitly marked `INVESTIGATING` or uncertain.

## 1. Current project phase

NoteAI is in **production infrastructure preparation and controlled release**, not general availability. Render Staging remains the validated staging environment. The production Claude Gateway is live on Render Singapore, while the Alibaba Cloud production application path has not been released: the exact three AMD64 candidates now exist in private ACR under immutable role-specific tags and digests, but API-C/API-F application services are not accepted, no ALB is configured, TLS certificates are not attached to a production listener, and production DNS has not been switched.

`PROD-PREBUILD-001` through read-only `PROD-WORKER-FIXED-RUNTIME-DESIGN-001`, `PROD-XHS-HTTP-ADAPTER-001`, `PROD-XHS-RAP-FIX-001`, `PROD-IMG-XHS-BROWSERLESS-REBUILD-001`, `PROD-PILLOW-12.3.0-FIX-001`, the local execution scope of `PROD-IMG-XHS-PILLOW-REBUILD-001`, read-only `PROD-BROWSERLESS-OS-VULN-DISPOSITION-001`, read-only `PROD-BROWSERLESS-RESIDUAL-DECISION-001`, `PROD-BROWSERLESS-CONSTRAINT-PROOF-001`, `PROD-BROWSERLESS-VEX-REVIEW-001`, and `PROD-IMG-002` are `VERIFIED`. Exact Pillow-fixed application revision `a635692a899ee02c6905cd694611c14e0da4594a` remains the OCI revision of all three registry artifacts; deployment-control release `253fde55fa609676a9fca5c14fdf6aeceef74000` and later Handoff/VEX commits are not image revisions. Image contents and canonical raw reports remain unchanged and unsuppressed at `4 Critical / 19 High`. The only next release task is separately approved read-only `PROD-IMG-003`; no deployment or service start is implied.

## 2. Git and repository truth

| Field | Verified value |
|---|---|
| Branch | `codex/quality-stabilization-real-chain` |
| Historical retained-image application release | `93b03d5c40fb64fa264c0ada1c055f8e7696b161` |
| RAP-fix task-start HEAD / parent | `33d04d4560f9b7dda43a53527f8ae1026dc335d3` / `f3a1a3bb28acd4a2b7e33221d0d8d0100a79c9a9` |
| Rejected browserless image source | `33d04d4560f9b7dda43a53527f8ae1026dc335d3` (`feat(prod): add bounded XHS HTTP runtime [skip render]`) |
| RAP-fix application revision | `ca02335513a752ece2dabe71d08105ae86db6c5a` (`fix(prod): isolate XHS RAP signer runtime [skip render]`), pushed and independently verified |
| Pillow-fixed application revision | `a635692a899ee02c6905cd694611c14e0da4594a` (`fix(prod): upgrade Pillow to 12.3.0 [skip render]`), independently verified, pushed and now the exact source of the current local three-role images |
| Browserless constraint release | `253fde55fa609676a9fca5c14fdf6aeceef74000` (`fix(prod): enforce browserless runtime constraints [skip render]`); deployment configuration/readiness provenance only, never the OCI application revision |
| Task-start HEAD | `5b3249995522a22dc600ee7501f9328121f4497c`; formal VEX/Handoff descendant, never an OCI application revision |
| Verified local image source | exact application revision `a635692a899ee02c6905cd694611c14e0da4594a`; never reuse `ca023355`, substitute `4704c16`, or relabel an old image |
| Upstream | `origin/codex/quality-stabilization-real-chain` |
| Ahead / behind at task start | `0 / 0`; HEAD and upstream both equaled `5b3249995522a22dc600ee7501f9328121f4497c` |
| Worktree at task start | clean |
| Push state | VEX/review/Handoff changes are repository evidence only and must use `[skip render]`; they never replace `a635692a899ee02c6905cd694611c14e0da4594a` as the OCI revision |
| ACR artifact state | three immutable role tags and manifest digests recorded under private repository `noteai/app`; no deployment or service start |
| Render auto-deploy impact | commit message contains `[skip render]`; no Render production deployment or service start is authorized |

Recent relevant commits, newest first:

- `253fde5` — enforce browserless production runtime constraints and readiness rejection tests; deployment-config provenance only, never an image revision.
- `4704c16` — Handoff-only checkpoint for Pillow repository verification; never an application/image revision.
- `a635692` — upgrade Pillow to `12.3.0`; exact application revision of the current local browserless images.
- `344897c` — prior CI fixture-isolation/Handoff checkpoint only; never an application/image revision.
- `ca02335` — isolate and verify the XHS RAP signer runtime; exact application revision of the superseded pre-Pillow-fix browserless images.
- `33d04d4` — add the bounded browserless XHS HTTP runtime; exact source of the three rejected pre-fix local role images and parent of the RAP-fix release.
- `f3a1a3b` — Handoff-only checkpoint for Worker sandbox verification; documentation provenance, never an application revision.
- `93b03d5` — harden all Worker Chromium launches with fail-closed sandboxing and the pinned Playwright seccomp profile; exact source of the retained local images and baseline for the planned adapter change; normally pushed without force.
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

Independent repository verification for exact application revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161` completed. Native AMD64 build, runtime sandbox acceptance, CycloneDX SBOM, Secret scan and unsuppressed High/Critical scans have all been run for this hardened revision. The corresponding evidence at `89e3505` remains a superseded baseline only. `93b03d5` must remain the recorded revision of those retained images; after the adapter implementation, the new full application commit—not a Handoff-only HEAD or a relabelled old image—must be the revision of every newly built role image.

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

### 4.1 Retained recovery point and next-source rule

- Exact source revision for the current three browserless ACR role images: `a635692a899ee02c6905cd694611c14e0da4594a` (`a635692`). Historical `93b03d5c40fb64fa264c0ada1c055f8e7696b161` remains only the hardened browser-worker baseline and is not the current image revision.
- Two superseded local-only candidates exist: `noteai-local:git-89e3505-amd64-api-r1` and `noteai-local:git-89e3505-amd64-worker-r1`. Both are `linux/amd64` and carry full revision `89e3505225c9d596d6ddb26040f08b777e77823c`, but they predate the sandbox correction and must not be pushed or deployed. Neither has an ACR registry digest.
- API size is `1,042,774,445` bytes and Worker size is `2,494,249,539` bytes. Local Docker image IDs are recorded in the ECS acceptance evidence and are explicitly **not** ACR registry digests.
- No current role image may be deployed yet. The exact `a635692a899ee02c6905cd694611c14e0da4594a` Pillow-fixed browserless roles have been pushed to private ACR and their registry-digest VEX reissue is complete, but separate read-only `PROD-IMG-003` supply-chain acceptance and later explicit deployment approvals remain mandatory. Their raw reports remain canonical and unsuppressed at `4 Critical / 19 High`; the exact-product VEX remains a separate impact statement rather than a production exception.
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
| `noteai-local:git-ca02335-amd64-api-r1` | Local image ID `sha256:5fa36abe1c603aa0abc1295912fe6ee16a0b468d8be216475be06a4daa9a6454`; no ACR digest | `linux/amd64` | **Superseded local build:** exact RAP-fixed revision; contains Pillow `12.2.0`; Secret `0`, `4 Critical / 29 High`. |
| `noteai-local:git-ca02335-amd64-admin-r1` | Local image ID `sha256:6d3b5ee2dd4619a60394ad4e026287fe4b5a9a39dd722c37954fe58627369865`; no ACR digest | `linux/amd64` | **Superseded local build:** exact RAP-fixed revision; contains Pillow `12.2.0`; Secret `0`, `4 Critical / 29 High`. |
| `noteai-local:git-ca02335-amd64-xhs-http-r1` | Local image ID `sha256:755e337c2932ef53187b5af333b1daa47be578a81af9a57d6c1af7a9368b3b60`; no ACR digest | `linux/amd64` | **Superseded local build:** exact RAP-fixed revision; contains Pillow `12.2.0`; Secret `0`, `4 Critical / 29 High`; basic/RAP `network=none` smoke passed. |
| `git-a635692-amd64-api-r1` | ACR manifest `sha256:17706e1802afc136ac8f9a621d4199a719749da73329ee923e42268eff42e0d1`; local image ID remains `sha256:b1983bab928ef93495d8be020030917d4ae54364234390047c3163af5414fedb` | `linux/amd64` | **Current private ACR candidate, deployment-blocked:** exact Pillow-fixed revision; Secret `0`, raw `4 Critical / 19 High`, registry-digest VEX complete. |
| `git-a635692-amd64-admin-r1` | ACR manifest `sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d676c733`; local image ID remains `sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f` | `linux/amd64` | **Current private ACR candidate, deployment-blocked:** exact Pillow-fixed revision; Secret `0`, raw `4 Critical / 19 High`, registry-digest VEX complete. |
| `git-a635692-amd64-xhs-http-r1` | ACR manifest `sha256:452c2faf7853ce58d93e43c5bf6217a99a6cce14c81345d8cef2f5accabd79af`; local image ID remains `sha256:5b44114d4bd9c28a8e93c39140466c542e8babeead038fb0d1cfe45c3cd75966` | `linux/amd64` | **Current private ACR candidate, deployment-blocked:** exact Pillow-fixed revision; Secret `0`, raw `4 Critical / 19 High`, basic/RAP smoke and registry-digest VEX complete. |

No mutable tag such as `latest` is an acceptable production reference. The three current ACR manifests may only be considered after `PROD-IMG-003` and later explicit deployment approval; all historical entries remain forbidden.

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
- `PROD-IMG-XHS-BROWSERLESS-REBUILD-001` completed on retained isolated builder `i-wz99180s9ig5ecq10uaj`: clean exact source `ca02335513a752ece2dabe71d08105ae86db6c5a`, Git LFS/model integrity, three local native AMD64 builds, provenance/content, CycloneDX/Secret/unsuppressed scans and `network=none` basic/RAP signer smoke all completed. The execution task is verified; the images remain release-blocked by `4 Critical / 29 High`.
- `PROD-PILLOW-12.3.0-FIX-001` completed at exact application revision `a635692a899ee02c6905cd694611c14e0da4594a`: shared production pin `12.2.0` → `12.3.0`, direct compatibility/readiness regression coverage, Python 3.11 wheel validation, full tests and independent verification passed. No image was built or rescanned.
- `PROD-IMG-XHS-PILLOW-REBUILD-001` completed on retained isolated builder `i-wz99180s9ig5ecq10uaj`: clean exact source `a635692a899ee02c6905cd694611c14e0da4594a`, Git LFS/model integrity, three local native AMD64 builds, provenance/content, CycloneDX/Secret/unsuppressed scans and `network=none` basic/RAP signer smoke all completed. Pillow rows are `0`; every role remains release-blocked by residual `4 Critical / 19 High`.

Not started or not completed:

- Read-only disposition of all residual Debian `4 Critical / 19 High` rows in the exact Pillow-fixed images. No production exception or VEX has been registered.
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
- The retained API/Worker images correctly identify `93b03d5c40fb64fa264c0ada1c055f8e7696b161`. The future browserless role images must identify the new verified adapter release commit; neither a Handoff-only HEAD nor a relabelled old image may replace its true revision.
- Runtime build evidence for the predecessor `89e3505225c9d596d6ddb26040f08b777e77823c` exists under `/opt/noteai-build/evidence-89e3505-split/` as a superseded baseline. Current exact `93b03d5` evidence exists under `/opt/noteai-build/evidence-93b03d5-hardened/`: API `3 Critical / 19 High`, Worker `5 Critical / 32 High`, Secret `0` for both, plus successful bounded Worker sandbox runtime acceptance. These results do not authorize a push or deployment because the residual vulnerabilities lack an approved disposition.

### PROD-IMG-001 — Build corrected AMD64 image

- Status: `BLOCKED`. The retained isolated ECS `noteai-build-amd64-b6abaa7-r1` (`i-wz99180s9ig5ecq10uaj`) in Alibaba Cloud Shenzhen F was rechecked and used only for the approved split and browserless local build/scan tasks. The user extended its release time; exact future lifecycle state must still be rechecked before any later task.
- Historical source/build evidence (2026-07-20): exact detached HEAD `8f7d9c23dd4c4bc951f23d2412156f121da868e7`, tree `483544cdbf5c2d7c11827ca296874f097d2969c2`, clean status, and three production V0.4 Git LFS binary SHA values equal their commit pointer OIDs. This evidence does not cover the hardened targets at `93b03d5c40fb64fa264c0ada1c055f8e7696b161`.
- Superseded historical local candidate: `noteai-local:git-8f7d9c2-amd64-r1`, `linux/amd64`, size `3,454,259,927` bytes, local image ID `sha256:47174b226ef11b704fcf92474e3f9d9bf266ef77a75e23ae4fdab99e1cfdd0f9`. This is a local Docker image ID, **not** an ACR registry digest. It must not be pushed or deployed.
- Historical acceptance: exact OCI revision/source/version/created (`2026-07-20T14:54:53Z`), non-root UID `999`, expected entrypoint/CMD, Python-stdlib live probe, `mttravel 1.0.16` and bundle SHA, four machine-manifest artifacts, no curl/Xvfb/setuptools/wheel, non-root offline headless Chromium `about:blank`, restored apt sources, no `.env`/`.git`, no sensitive ENV/history assignment, Trivy Secret `0`, CycloneDX SBOM `298` components.
- Historical remediation delta: package records fell from `75` to `39`; High fell from `68` to `32`; Critical remained `7`; unique CVE IDs became `29`; removed records `36`, added records `0`. This result belongs only to the superseded combined image.
- Historical blocking acceptance: Trivy `0.70.0` reported `32 High` and `7 Critical` for the superseded combined image; the later split/hardened results were API `3 Critical / 19 High` and Worker `5 Critical / 32 High`. The current Pillow-fixed browserless API, Admin and XHS images each report `4 Critical / 19 High`; no ignore, VEX or production exception was used or registered.
- Historical evidence was retained at `/opt/noteai-build/evidence-8f7d9c2` and `/opt/noteai-build/PROD-VULN-FIX-001-evidence.tgz` (`215,209` bytes, SHA256 `e4dd0fe886c12af3a3f9e10fe50af0254829d122954fc9b9e6b383284d0984cf`). The last recorded automatic release was `2026-07-21 21:22 +08:00`; current builder/image existence must be verified and is not inferred here.
- The current retained browserless evidence uses exact Pillow-fixed application revision `a635692a899ee02c6905cd694611c14e0da4594a`. Never substitute superseded `ca023355`, `344897c`, any other Handoff-only commit, or historical `f3a1a3b`, `93b03d5`, `89e3505`, `8f7d9c2`, `b6abaa7` or `ff030f5` as that application revision.
- ACR inventory was not read or modified during this execution phase. No ACR login or push occurred, and the remote existence of the local candidate tag was not assumed.
- Executed scope was limited to the approved temporary isolated Alibaba Cloud Shenzhen `x86_64` builder, never API-C or API-F: clean exact checkout, local `linux/amd64` build, and local acceptance only. PROD-IMG-002, service start, database/cache access, and production cloud-service changes were excluded.
- Acceptance evidence completed locally for browserless `api-runtime`, `admin-runtime` and `xhs-http-runtime`: AMD64 architecture, full OCI revision/source/version/created labels, expected role marker and owner, entrypoint/user/model and role-appropriate contents, absence of installed Playwright/Chromium/browser graphics capability and of any production-reachable browser command, SBOM, vulnerability scan and Secret scan. Before any push decision, every residual Critical or High finding still requires explicit disposition.
- Cost/impact: temporary ECS compute, system disk, and dependency downloads; no paid AI/provider calls. Rollback remains deletion of the unpushed local image/build cache and release of the temporary builder, but neither deletion nor manual release was performed because both require a separate lifecycle decision.
- `PROD-IMG-XHS-BROWSERLESS-BUILD-001` failed RAP runtime acceptance as recorded below. Its RAP-fix and clean successor rebuild are now complete. Continue to prohibit ACR, exception/VEX registration, deployment and real Xiaohongshu calls; do **not** approve `PROD-IMG-002` for any current local image.

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
- **Release commit:** `93b03d5c40fb64fa264c0ada1c055f8e7696b161`, parent `5ba202febaff364328057a7f8a1ca41f72816a47`, message `fix(prod): harden worker chromium sandbox [skip render]`. It was normally pushed to `origin/codex/quality-stabilization-real-chain`; local/remote divergence was `0/0` before this Handoff checkpoint. This exact application SHA remains the source identity of the retained hardened images and the baseline for the adapter change; the next rebuild must instead use the new full verified adapter commit, never a later Handoff-only HEAD.
- **Launch enforcement:** all five Python Chromium launch points (`crawler.py` two, `scheduler_a.py` one, `download_covers.py` two) use `model/chromium_security.py`. The helper forces `chromium_sandbox=True`, rejects `--no-sandbox`, `--disable-setuid-sandbox` and `--no-zygote` before Playwright is called, and never retries a failed sandbox launch with weaker settings. The obsolete Render low-memory/no-zygote switch was removed.
- **Runtime boundary:** Worker remains `USER noteai`. Docker image creation no longer launches Chromium as root and checks only that Playwright resolves an installed executable. Compose applies `no-new-privileges:true` and the same seccomp profile to Admin, trends-worker and tracking-worker; API is excluded. No `privileged`, `SYS_ADMIN`, `seccomp=unconfined` or capability addition was introduced.
- **Seccomp provenance:** complete upstream Playwright v1.56.0 profile at `deploy/security/playwright-chromium-seccomp-v1.56.0.json`, `12,997` bytes, SHA256 `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`, `defaultAction=SCMP_ACT_ERRNO`, includes `SCMP_ARCH_X86_64` and the reviewed `clone`/`setns`/`unshare` allow rule. Render Blueprint has no reviewed custom-seccomp field; no unsupported field or sandbox bypass was invented.
- **Offline existing-image evidence:** Cloud Assistant invocations `t-sz06rkcdpibjyf4` and `t-sz06rkck2fakagw` completed with exit `0` on isolated builder `i-wz99180s9ig5ecq10uaj`. Stopped containers created with `--network none` were used only for file extraction; no image process was run. Package ownership and direct ELF `NEEDED` evidence for the existing API image ID `sha256:c44730a50e4ae873ba9b77f56bbb79c8bc573c1e8177da79c9b727c6c17707f1` and Worker image ID `sha256:b299d5f3ef5dc639a2b1611b0e7f46731f0eb9b0451ea540e0e4600423bf6fd8` was retained under the builder's timestamped `/opt/noteai-build/worker-hardening-evidence.*` directory. Worker browser paths include Playwright Chromium `1194`; direct ELF evidence starts with `libdl.so.2` and `libpthread.so.0`. This evidence does not prove complete transitive exploitability or non-exploitability.
- **Boundary evidence:** running containers before/after remained `0`; `/root/.docker/config.json` remained absent. No Secret was read or printed, no ACR login/read/push occurred, and no production database/cache/cloud resource or external provider was accessed.
- **Independent verification:** `87/87` targeted tests; full suite `601` passed with `5` skipped; production readiness `78/78`; seccomp hash/JSON semantics, all launch paths, fail-closed behavior, non-root Dockerfile, Compose role coverage, Render boundary, `py_compile`, Compose quiet parse, diff check and changed-file Secret scan passed. The independent verifier found no Critical/High/Medium/Low implementation defect. The full-suite `moonshot network error` text was a mocked failure path, not a real supplier call.
- **Remaining release gates:** the approved hardened build and the later bounded user-namespace runtime proof completed. Worker Chromium now has a successful non-root + pinned seccomp + `no-new-privileges` acceptance result on the isolated ECS. Residual unsuppressed Critical/High findings and deployment-platform support remain separate release decisions.
- **Completion transition:** the recommended `PROD-ROLE-VULN-DISPOSITION-001` is now independently `VERIFIED` below. Its conservative result leaves `14` Worker browser-library rows indeterminate; the next recommended approval is the bounded offline evidence task recorded there. Continue to prohibit ACR login/push, production exception/VEX registration, deployment, production data/cloud access and real supplier calls unless separately and explicitly approved.

### PROD-IMG-HARDENED-BUILD-001 — Build, scan and runtime-accept hardened split images

- **Status:** `VERIFIED` on 2026-07-22. Both native AMD64 images, all required scans and the bounded Worker Chromium sandbox runtime proof completed. This does not accept the residual vulnerabilities or authorize ACR/deployment.
- **Priority:** Critical release gate.
- **Boundary evidence:** isolated native `x86_64` builder `i-wz99180s9ig5ecq10uaj` remained in Shenzhen F with security-group inbound rules `0`, no RAM role, no Docker registry config, no running containers and no route to production `10.42.*`. Cloud Assistant boundary invocation `t-sz06rke7glu33sw` exited `0` with `BOUNDARY_AUDIT=PASS`.
- **Source evidence:** because GitHub HTTPS was also unreachable, an exact locally generated Git pack for delta `89e3505..93b03d5` was split and transferred through Cloud Assistant, each chunk and the reassembled pack was SHA256-verified, and the exact commit was imported without Secret material. Clean detached source is `/opt/noteai-build/repo-93b03d5-exact-r1`. Invocation `t-sz06rki4jfyu0hs` exited `0`: revision exact, clean worktree, `git lfs fsck`, all required V0.4 models/manifests, Dockerignore gate, tracked sensitive names `0`, seccomp SHA `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`, and OCI created `2026-07-21T06:30:11Z` all passed. The superseded API image was used only as a `--network none`, read-only Python 3.11 checker for the source tree; no service started.
- **Base retrieval resolution:** provenance-reviewed public ECR copies of the exact Dockerfile-pinned base indexes were supplied as named BuildKit contexts; the immutable index digests remained Python `sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93` and Node `sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0`. No Dockerfile registry rewrite, floating tag or unreviewed base substitution occurred.
- **Build evidence:** Cloud Assistant invocation `t-sz06rl3f65uy2o0` completed the native builds. API `noteai-local:git-93b03d5-amd64-api-r1` is local image ID `sha256:e637ff8af8f63c83e1370066111765f6594297806ec9b3e153d03b1dcb1762bc`, size `1,042,778,777` bytes. Worker `noteai-local:git-93b03d5-amd64-worker-r1` is local image ID `sha256:17a80aa53c41909abf4dace7c0bec4cfc90e6fd4387bb1c80e8bc5ca7616836e`, size `2,494,844,195` bytes. Both are `linux/amd64`, `USER noteai`, exact revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161`, source `https://github.com/iamyusen1314/noteai`, and carry the expected role/version labels, entrypoint and role CMD. Both have empty `RepoDigests`; these local image IDs are not ACR registry digests. The earlier Handoff value beginning `17a88aa...90e6f043...` was a transcription error: it matched zero retained evidence files, while the corrected ID above matched 11 build/SBOM/Secret/vulnerability/smoke evidence files.
- **Content/SBOM/Secret/vulnerability evidence:** evidence is under `/opt/noteai-build/evidence-93b03d5-hardened/`, with final API and Worker sets in `api-final-r4/` and `worker-final-r4/`. API is browser-free, SBOM components `174`, Secret findings `0`, `19 High / 3 Critical`, fixed-version findings `0`. Worker contains Playwright `1.56.0`, Chromium bundle `1194`, no Xvfb, SBOM components `288`, Secret findings `0`, `32 High / 5 Critical`, fixed-version findings `0`. Both passed mttravel `1.0.16` bundle SHA `8a0527bb6e8b9074cf0221756f35bca989945e8436e4841596a7b7bf79ae06d8`, all V0.4 model/manifest hashes, role/content/history/provenance checks, and absence of `.git` and `model/.env`. Trivy `0.70.0` ran offline with no ignore/VEX and database update timestamp `2026-07-20T13:19:47.192055519Z`.
- **Final audit:** invocation `t-sz06rm8im4wf6rk` reconfirmed exact clean source, LFS, model and seccomp hashes, provenance, scan counts, no production route, running containers `0` and Docker auth absent. Invocation `t-sz06rm8mmlhj01s` independently emitted the full image IDs in bounded chunks.
- **Worker smoke result:** historical invocation `t-sz06rm802szh24g` failed closed when the host quota was `user.max_user_namespaces=0`. Approved bounded invocation `t-sz06rmyrixwxzwg` then temporarily set that value to `128` and passed with `--network none`, UID/GID `999`, `PAGE_URL=about:blank`, `CHROMIUM_PROCESS_COUNT=7`, `FORBIDDEN_FLAG_COUNT=0`, `ALL_NNP_ONE=1`, `ALL_SECCOMP_FILTERED=1`, `NON_ROOT_PROCESS_COUNT=7` and `NESTED_UID_MAP_VARIANTS=1`. It emitted both `WORKER_USERNS_SMOKE=PASS` and `PROD_WORKER_USERNS_SMOKE=PASS`, restored `user.max_user_namespaces=0`, left `RUNNING_CONTAINERS_AFTER=0`, and emitted `USERNS_RESTORE=PASS`. No sandbox bypass, capability addition, unconfined seccomp or privileged container was used.
- **Boundary deviation disclosed:** a read-only Cloud Assistant selector accidentally included API-C and API-F together with the builder for invocation `t-sz06rm266jzmx34`. The command only ran process inspection and tailed a nonexistent builder log; all targets returned exit `0`. It performed no write, container action, network call, Secret access, service/data operation or state change. All later commands targeted only the isolated builder.
- **Execution:** native `linux/amd64` local builds of `api-runtime` and `worker-runtime`; exact OCI provenance; role/content/model/mttravel checks; CycloneDX SBOM; filesystem/history Secret scan; unsuppressed High/Critical scan; Worker non-root `about:blank` smoke with `no-new-privileges` and the vendored seccomp profile whose SHA is recorded above.
- **Prohibited:** ACR login/read/push, production exception/VEX registration, deployment/service start, API-C/API-F changes, production database/Tair access, ALB/TLS/DNS/cloud-resource mutation and real AI/map/Meituan/crawler/payment calls.
- **Risk/cost:** existing temporary ECS compute only; the smoke used `--network none` and made no provider call. Residual High/Critical findings remain unsuppressed. The approved host-level sysctl change was bounded, automatically restored and independently evidenced.
- **Rollback:** remove only new unpushed local image/build-cache objects if separately approved; retain the builder and evidence until the next release decision or its configured automatic release. Accidental builder release requires rebuilding from exact commit; local image IDs are never ACR digests.
- **Acceptance:** met for build/scan/runtime evidence. Both exact native AMD64 images and all provenance/content/SBOM/Secret/vulnerability evidence exist locally; API acceptance passed; Worker sandboxed Chromium started under the required boundary and cleanup passed. Stop before ACR.
- **Required decision to unblock release:** approve a separate independent role-specific residual-vulnerability disposition. Runtime acceptance does not itself justify VEX, exception registration, ACR push or deployment.

### PROD-ROLE-VULN-DISPOSITION-001 — Final role-specific vulnerability/VEX evidence review

- **Status:** `VERIFIED` on 2026-07-22. The authorized read-only review is complete; this validates the evidence classification, not a production exception, formal VEX statement or release acceptance.
- **Exact evidence identity:** the retained reports are API SHA256 `6e8e2078bb6ee9003b29fd67a2b8d68721aeab29b5167794339ade42c10f8c1d` and Worker SHA256 `30a677c518d78b44f1add6ab648cd3428c2ac51ea91d534abee74f3b40460e0a`. Cloud Assistant invocations `t-sz06rn0111qa5fk` and `t-sz06rn0e8b0sj5s` read and independently compressed the existing JSON on builder `i-wz99180s9ig5ecq10uaj`; both exited `0`. Counts remain API `22` (`3 Critical / 19 High`, `11` unique CVEs) and Worker `37` (`5 Critical / 32 High`, `26` unique CVEs), total `59`, duplicate rows `0`, and fixed-version rows `0`.
- **Debian state at review time:** every installed Trixie version in the reports remains marked vulnerable by Debian. Debian labels several as `no-dsa`, `postponed` or minor, but those labels are not fixes. Forky/Sid fixes `19` of the `26` unique CVEs, while `CVE-2026-13221`, `CVE-2026-41992`, `CVE-2026-42496`, `CVE-2026-42497`, `CVE-2026-53615`, `CVE-2026-58016` and `CVE-2026-9538` remain unfixed there too. A same-Trixie `apt upgrade` or unchanged-base rebuild cannot clear the gate today.
- **API reachability disposition:** no repository API/entrypoint invocation of Perl, Archive::Tar, IO::Compress, `infocmp`, gzip decompression, blkid/partition parsing or libacl pathname APIs was found. `CVE-2026-8376` is 32-bit-only while the exact image is `linux/amd64`. Debian's `perl-base` amd64 file list contains the Perl binary but not Archive::Tar or IO::Compress; the source-package mapping for `CVE-2026-53615` expands one libblkid flaw across nine util-linux binary packages, while NoteAI neither invokes mount/blkid nor has the privileges needed for the cited paths. No API finding was demonstrated reachable. All `22` API rows have sufficient evidence to enter a separate formal VEX authoring/reviewer workflow, but none was accepted or registered here.
- **Worker base/CUPS disposition:** the same `22` base rows have the same non-invocation/architecture evidence. `CVE-2026-34980` additionally requires a network-exposed `cupsd` with a shared queue; the image contains `libcups2t64` for Chromium compatibility, and Debian's package file list confirms that binary package contains `libcups.so.2` and documentation, not the CUPS daemon. These `23` Worker rows have strong evidence for later formal review, but remain unsuppressed.
- **Worker browser-library blocker:** six Expat rows (`CVE-2025-59375`, `CVE-2026-25210`, `CVE-2026-45186`, `CVE-2026-56131`, `CVE-2026-56407`, `CVE-2026-56408`), seven GLib rows (`CVE-2026-58010` through `CVE-2026-58016`) and libxml2 `CVE-2026-6653` are installed only in the Worker/browser role. The sandbox, non-root UID, pinned seccomp and `no-new-privileges` materially reduce exploit impact, but do not prove those parsing/library paths unreachable. Because the Worker intentionally visits untrusted pages and existing package/ELF evidence is not a complete transitive call-path proof, these `14` rows (`2 Critical / 12 High`) remain `INDETERMINATE` and are not ready for a `not_affected` VEX statement.
- **Formal VEX evidence decision:** API `22` plus Worker base/CUPS `23` rows are candidates for a separate signed, independently reviewed draft bound first to the exact local image IDs/revision and later to an immutable registry digest. The `14` Worker browser-library rows are excluded from that candidate set pending stronger offline binary/load/input-path evidence or a vendor-fixed runtime. No VEX file, suppression, waiver or production exception was created.
- **Observed boundary:** commands only opened existing report files; no container/image/service was started, no build occurred and builder files were not changed. Only builder `i-wz99180s9ig5ecq10uaj` was selected; API-C/API-F were not selected. The Alibaba Cloud console session expired after evidence extraction, and no reauthentication or credential handling was attempted. No ACR, production data/dependency, cloud-resource mutation or supplier call occurred.
- **Release decision transition:** the recommended `PROD-WORKER-BROWSER-LIB-EVIDENCE-001` completed below under a user-narrowed non-invasive boundary. It confirmed package installation and normal Chromium loading but intentionally left CVE-specific reachability `UNKNOWN`; therefore `PROD-IMG-002` remains `BLOCKED`.

### PROD-WORKER-BROWSER-LIB-EVIDENCE-001 — Restricted non-invasive browser-library review

- **Status:** `VERIFIED` on 2026-07-22 for the user-restricted non-invasive scope. This status confirms evidence collection and conservative classification only; it does not accept risk, register VEX, authorize ACR or release either image.
- **Exact evidence identity:** retained Worker image `noteai-local:git-93b03d5-amd64-worker-r1`, local image ID `sha256:17a80aa53c41909abf4dace7c0bec4cfc90e6fd4387bb1c80e8bc5ca7616836e`, `linux/amd64`, application revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161`. This remains a local image ID, not an ACR digest. Existing Worker evidence remains SBOM `288`, Secret `0`, Trivy `5 Critical / 32 High`, report SHA256 `30a677c518d78b44f1add6ab648cd3428c2ac51ea91d534abee74f3b40460e0a`, no ignore/VEX and no fixed-version rows in the retained report.
- **Command boundary and correction:** only isolated builder `i-wz99180s9ig5ecq10uaj` was selected; API-C/API-F were not selected. Invocation `t-sz06rn4pc1x5nnk` exited `127` because Cloud Assistant truncated a nested heredoc; it was a transport/script error, not vulnerability evidence. Corrected invocation `t-sz06rn5k9owhbeo` used the exact retained image with `--pull never`, `--rm`, `--network none`, read-only rootfs, UID/GID `999`, all capabilities dropped, pinned seccomp and `no-new-privileges`; it exited `0` in four seconds.
- **Boundary results:** exact image ID and `amd64` matched; `RepoDigests=[]`; Docker auth config was absent; seccomp SHA256 was `cc3e61cabda6bbc1e53e54d27ba4d55a9d3be829b6dd1a596f4a7b31b1cc7849`; container status showed `NoNewPrivs=1`, `Seccomp=2`, one seccomp filter and only loopback. Running containers were `0` before/after and `user.max_user_namespaces` was `0` before/after. No persistent file, sysctl, image, service or cloud-resource state was changed. Cloud Assistant retained only its normal execution/audit records.
- **Installed package ownership:** `libexpat1:amd64 2.7.1-2` owns `/usr/lib/x86_64-linux-gnu/libexpat.so.1*`; `libglib2.0-0t64:amd64 2.84.4-3~deb13u3` owns `libglib-2.0.so.0*` and `libgio-2.0.so.0*`; `libxml2:amd64 2.12.7+dfsg+really2.9.14-2.1+deb13u3` owns `libxml2.so.2*`. Repository search found no NoteAI call of the listed Expat/libxml2/GLib vulnerable APIs.
- **Normal runtime-load evidence:** direct `ldd` on Playwright Chromium `141.0.7390.37` and a normal `LD_DEBUG=libs chrome --version` run loaded system `libexpat.so.1`, `libglib-2.0.so.0` and `libgio-2.0.so.0`; the observed path did not load system `libxml2.so.2`. This proves library presence/load only, not CVE-specific reachability from an untrusted page. A binary symbol-string scan was also emitted by the corrected command, but the user subsequently prohibited symbol probing; it is excluded from the release disposition and must not be repeated.
- **Safety stop:** after a security warning, the user prohibited exploit/PoC/payload/malformed-input, symbol probing, memory-corruption testing and sandbox-escape validation. A planned local parser-API probe was stopped before submission and never executed. No parser fixture, malformed input, exploitability test or real page was run. Anything not determinable from existing SBOM/Trivy, package metadata, normal loader evidence and official vulnerability metadata is recorded as `UNKNOWN`.
- **Official Debian status:** current Trixie versions above remain vulnerable. Debian Forky/Sid `expat 2.8.2-1` fixes all six retained Expat CVEs; `glib2.0 2.88.2-1` fixes `CVE-2026-58010` through `CVE-2026-58015` but not `CVE-2026-58016`; `libxml2 2.15.3+dfsg-1` fixes `CVE-2026-6653`. A same-Trixie package upgrade or unchanged-base rebuild cannot clear these rows.
- **Conservative disposition:** Expat six rows are `INSTALLED + LOADED + CVE_REACHABILITY_UNKNOWN`; GLib seven rows are `INSTALLED + LOADED + CVE_REACHABILITY_UNKNOWN`; libxml2 one row is `INSTALLED + NOT_LOADED_IN_OBSERVED_VERSION_PATH + OTHER_RUNTIME_PATHS_UNKNOWN`. All `14` rows (`2 Critical / 12 High`) remain release blockers. No `not_affected` statement, VEX, suppression, waiver or production exception was created.
- **Minimum safe closure:** use a digest-pinned Worker runtime whose Expat and libxml2 packages are vendor-fixed, then rebuild/re-scan; do not mix Debian suites in place. For GLib, wait for or select a supported vendor runtime containing an official fix for all seven, including `CVE-2026-58016`; Forky/Sid alone is currently insufficient. Removal is acceptable only if a future static dependency review proves Chromium can run without the package and a normal non-invasive loader check plus full Worker acceptance/re-scan passes. Until then, Worker/ACR release remains blocked.
- **No-repeat rule:** do not rerun the nested-heredoc command, binary symbol search, parser/API probe, exploitability test or sandbox-escape validation. Future evidence work is limited to reading existing SBOM/Trivy artifacts and official vendor metadata unless the user explicitly changes the boundary.

### PROD-WORKER-FIXED-RUNTIME-DESIGN-001 — Supported fixed-runtime candidate design

- **Status:** `VERIFIED` on 2026-07-22 for the approved read-only design scope. This confirms the candidate comparison and migration gate only; it does not authorize a Dockerfile/dependency change, image build, VEX/exception, ACR access or release.
- **Input identity:** current Worker is exact application revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161`, Python `3.11.15`, Playwright `1.56.0`, Chromium bundle `1194` / Chromium `141.0.7390.37`, Debian Trixie base pinned by digest, non-root UID/GID `999`, pinned seccomp plus `no-new-privileges`. Existing scan evidence remains Worker SBOM `288`, Secret `0`, Trivy `5 Critical / 32 High`; the `14` browser-library rows remain `2 Critical / 12 High` with no approved disposition.
- **Official Python image candidates:** the Docker Official Images manifest currently publishes Python `3.11.15` on Trixie, Bookworm and Alpine only. Trixie is the current vulnerable baseline; Bookworm is also marked vulnerable for the retained Debian issues and is a regression rather than a fix; Alpine/musl is explicitly unsupported by Playwright. No supported Docker Official Python `3.11` Forky/Sid tag exists.
- **Debian newer-suite candidate:** Forky/Sid `expat 2.8.2-1` fixes the six retained Expat rows and `libxml2 2.15.3+dfsg-1` fixes `CVE-2026-6653`; `glib2.0 2.88.2-1` fixes `CVE-2026-58010` through `CVE-2026-58015` but Debian still marks `CVE-2026-58016` vulnerable. Mixing suites is prohibited, and Forky/Sid is neither a complete fix nor a supported Docker Python 3.11 production base.
- **Microsoft Playwright Noble candidate:** exact tag `mcr.microsoft.com/playwright/python:v1.56.0-noble` exists with manifest-list digest `sha256:a7f6cf3ae520c9d670ad956572c13747ed5abdbba5123a01526f873ed1662528`, so its Playwright/browser version can match the project. It is not accepted as a production replacement: Microsoft states the image is for testing/development and is not recommended for untrusted websites; its source base is Ubuntu Noble rather than Python 3.11; Ubuntu has fixed `CVE-2026-6653` for Noble libxml2 but still marks the retained Expat and GLib findings, including `CVE-2026-58016`, as `Needs evaluation`. A tag/digest existing is not evidence that the blockers are fixed.
- **Custom Ubuntu Noble candidate:** rejected for the current release. It would require a separately maintained Python 3.11 toolchain or an application upgrade to a different Python version, while official Ubuntu metadata still lacks fixed status for the retained Expat/GLib rows. This increases runtime and supply-chain scope without clearing the gate.
- **Playwright upgrade candidate:** current upstream documentation uses Playwright `1.60.0`. Upgrading from `1.56.0` is a possible future Plan B, not a drop-in base replacement: it changes the Python dependency and browser bundle, requires the matching image/browser version, a newly reviewed matching seccomp profile, repository regression tests, fresh native AMD64 build/SBOM/Secret/vulnerability scans and sandbox smoke. It must not be combined silently with a base migration.
- **Remote browser/sidecar candidate:** Playwright documents remote server operation, but this would add a network trust boundary and deployment component, does not itself prove the browser system libraries fixed, and is not a minimal closure for the current release. It is not selected.
- **Decision:** there is **no release-ready Worker runtime candidate today**. Do not rebuild merely by moving to Bookworm, Alpine, Forky/Sid, Ubuntu Noble or the MCR Playwright image; each either remains officially unresolved, is unsupported, or broadens the runtime without clearing all `14` blockers. `PROD-IMG-002` remains `BLOCKED`.
- **Minimum future migration:** wait for a maintained vendor runtime whose official package metadata clears all `14`; resolve and record both its immutable index digest and `linux/amd64` child digest; give the Worker a separately pinned base so the browser migration does not force an API base change; preserve Python/Playwright compatibility, non-root UID/GID `999`, sandbox-helper ownership, pinned matching seccomp and `no-new-privileges`; create a new release commit for the Docker/dependency change; then perform a separately approved Worker-only native AMD64 rebuild and complete provenance/content/SBOM/Secret/unsuppressed vulnerability scans plus the bounded sandbox smoke. Acceptance requires all `14` rows absent, no new unreviewed Critical/High row, and independent verification before any ACR decision.
- **Revision rule:** `93b03d5c40fb64fa264c0ada1c055f8e7696b161` remains the behavioral/application baseline for this design. Any future Dockerfile or dependency change creates a new full release commit, and that successor—not `93b03d5`, any Handoff-only HEAD or a mutable tag—must be the OCI revision/build source.
- **Observed boundary:** only repository/Handoff files, retained evidence facts and official public vendor metadata were read. No ECS/Cloud Assistant command, image/container operation, registry access, source/package mutation, VEX/exception write, production/cloud access, parser/symbol/exploit probe or provider call occurred; incremental cloud cost was zero.
- **Next gate:** this browser-runtime path is retained as historical evidence but is no longer the selected production architecture. Do not repeat its build, probes or vendor-fix review unless the product decision changes. The bounded direct-HTTP implementation, RAP fix, Pillow fix, exact `a635692` three-role rebuild/rescan and residual Debian disposition are complete; the current next gate is the separately approved read-only residual release decision.

### PROD-XHS-HTTP-ADAPTER-001 — Replace production browser collection with a bounded direct-HTTP adapter

- **Status:** `VERIFIED` on 2026-07-22 at exact adapter application commit `33d04d4560f9b7dda43a53527f8ae1026dc335d3`. RAP-fixed successor `ca02335513a752ece2dabe71d08105ae86db6c5a` is the exact application/OCI revision of the current local images; CI/Handoff-only `344897c36f7cb69a9dc4d8fe1794b6170722e6fd` is not an application revision.
- **Product decision:** the user explicitly accepts the non-official/private-interface, account-restriction and platform-rule risks of the Spider_XHS approach and states that commercial use authorization for Spider_XHS is resolved. This records a product-risk decision; it does **not** assert or manufacture Xiaohongshu platform authorization.
- **Exact source lock:** repository HEAD at task start is Handoff-only commit `f3a1a3bb28acd4a2b7e33221d0d8d0100a79c9a9`; the unchanged application-code baseline is `93b03d5c40fb64fa264c0ada1c055f8e7696b161`. Spider_XHS is locked to commit `9504b5249103f34a0a4e7062939258061559e2fd`, tree `7db08187cb5332a5a3c89a5923987e098ffddf14`, authored 2026-07-19. At that exact upstream commit, `apis/xhs_pc_apis.py` SHA256 is `218507d59b8bd7c73c0fd3fe28b7fc7ecf387e3c50b5249e9d14ac787c4757d2`, `static/xhs_main_260411.js` SHA256 is `723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d`, and `static/xhs_rap.js` SHA256 is `e79fe1c79c97a73fbf5fdb6420af114ff591902aa60b436ac4b803a99b806d2e`. Mutable-branch and runtime code downloads are prohibited.
- **Authorization record:** the upstream public tree contains no public `LICENSE` file at the locked commit. The user states that separate Spider_XHS commercial authorization is resolved; this Handoff records that assertion without storing contract material and without representing it as Xiaohongshu platform authorization.
- **Minimum implementation scope:** read-only homefeed, search recommendation, note search, note detail, bounded pagination and session-health handling; browserless `admin-runtime` and `xhs-http-runtime` production targets; remove the Playwright/Chromium Worker from production Compose/Render role configuration and readiness gates. Preserve existing business, billing, quota, user-data and model behavior.
- **Explicit exclusions:** creator/publish/upload, comments/messages/likes/favorites or other platform writes; Pugongying/Qianfan write flows; anti-detection, challenge bypass, proxy rotation, account pools or automated account recovery; real Xiaohongshu calls in the first implementation task; production credentials/data, cloud mutation, image build, ACR access and deployment.
- **Implemented boundary:** only homefeed, search recommendation, note search and note detail use four fixed read-only endpoints; pagination is capped at three pages/sixty items. Local session health is secret-free and makes no platform call. Cookies are restricted to the fixed request host, expired cookies are discarded, duplicate names resolve to the last valid value, and Cookie/`a1`/signatures never enter argv, environment, health output or fixed errors. API/Admin roles cannot collect; `xhs-http` requires the exact adapter; missing/wrong adapters fail closed; direct collection is suspended unless explicitly unlocked; explicit suspension also stops legacy local tooling. Challenge/login/cooldown failures never fall back to browser, proxy or account rotation.
- **Production roles:** Docker/Compose/Render select only `api-runtime`, `admin-runtime` and `xhs-http-runtime`. No production target installs Python Playwright, Chromium or its graphics stack; the XHS runtime disables the inherited web healthcheck and exposes only allowlisted worker commands. Historical browser source/package declarations remain explicit local/legacy tooling and are not reachable through a production role entrypoint.
- **Verification:** independent socket-blocked full suite `625` passed with `5` skipped and `network_attempts=0`; targeted suite `130` passed with `network_attempts=0`; production readiness `83/83`; Python compilation, Shell syntax, Compose rendering, diff check, state-transition regression, high-confidence sensitive scan and exact upstream asset comparison passed. The verifier found no unresolved Critical or High implementation issue.
- **Source/provenance:** Spider_XHS commit `9504b5249103f34a0a4e7062939258061559e2fd`, tree `7db08187cb5332a5a3c89a5923987e098ffddf14`; upstream API SHA256 `218507d59c...787c4757d2`; vendored asset SHA256 values `723dc6ef...589292d` and `e79fe1c7...b806d2e` matched the clean detached source. The public upstream tree has no public license file at that commit; the user states separate commercial authorization exists outside Git. This is not Xiaohongshu platform authorization.
- **Image impact:** the retained `93b03d5` API and Worker images are immutable local evidence and are not changed by this decision. The API image remains a useful browser-free baseline but cannot be relabelled as the successor revision or used as the final post-adapter candidate. The Worker image becomes architecturally superseded and must not be pushed or deployed; it need not be rebuilt merely to wait for browser-library vendor fixes. Do not delete either retained image without separate lifecycle approval.
- **Image set:** the separately approved Pillow-fixed native AMD64 build/scan has completed for browserless `api-runtime`, `admin-runtime` and `xhs-http-runtime`; no production browser Worker image exists. The local image IDs remain distinct from future ACR immutable digests. The successor formal VEX review is complete, but ACR and deployment remain separately gated.
- **Rollback:** disable the adapter/collection scheduler with its feature gate, return the product to manual/screenshot evidence input, and leave the retired Worker undeployed. Do not silently reactivate Playwright.
- **Cost/impact now:** zero incremental cloud/provider cost and no production impact. No image, registry, service, database, provider or cloud resource was touched.
- **Successor sequence:** the first browserless build failed RAP acceptance; `PROD-XHS-RAP-FIX-001`, its successor rebuild, `PROD-PILLOW-12.3.0-FIX-001`, the clean exact `a635692` three-role rebuild/rescan, read-only residual Debian disposition, residual-path decision, constraint proof and independent VEX review are now complete. ACR remains unapproved and deployment remains prohibited.

### PROD-IMG-XHS-BROWSERLESS-BUILD-001 — Build and scan the three browser-free AMD64 roles

- **Status:** `BLOCKED` on 2026-07-23. The authorized build/scan ran to its required stop point, but runtime acceptance failed; it is not release-accepted and must not transition to ACR.
- **Exact source:** clean detached worktree `/opt/noteai-build/repo-33d04d4-exact-r1` at full application commit `33d04d4560f9b7dda43a53527f8ae1026dc335d3`. Git LFS/model artifacts, the machine manifest and expected SHA values were revalidated before build.
- **Builder/boundary:** retained isolated native AMD64 ECS `i-wz99180s9ig5ecq10uaj` / `noteai-build-amd64-b6abaa7-r1`, never API-C/API-F. Commands confirmed Docker registry auth entries `0` and running containers `0` after execution. No production RDS/Tair route or Secret was used; no ACR login/push, deployment, production access, real provider/Xiaohongshu call or cloud-resource mutation occurred.
- **Local candidates:** `noteai-local:git-33d04d4-amd64-api-r1`, `noteai-local:git-33d04d4-amd64-admin-r1`, and `noteai-local:git-33d04d4-amd64-xhs-http-r1`. All are native `linux/amd64`, run as non-root `noteai`, identify full OCI revision `33d04d4560f9b7dda43a53527f8ae1026dc335d3`, source `https://github.com/iamyusen1314/noteai`, created `2026-07-22T09:49:58Z`, have role-correct entrypoint/CMD/markers and empty `RepoDigests`. API local image ID is `sha256:3ee746458aec82866dc691209f31fa8a85d5a043452070c201ac2f906495da20`; XHS local image ID is `sha256:1fb0460928b852270b80a512cd78fb69ec46d47ab77784c9f96f6a85b48beddc`; the Admin ID is retained in the evidence summary. These are local image IDs, never ACR registry digests.
- **Content/provenance acceptance:** the three roles passed architecture, non-root, OCI labels, entrypoint/CMD, root-owned mode-`0444` role marker, model/manifest SHA, `mttravel 1.0.16` bundle SHA, sensitive history/path, and role-appropriate health metadata. `xhs-http-runtime` correctly records disabled health as Docker `Healthcheck.Test=["NONE"]`. Installed Playwright, Chromium/browser binaries and the checked browser graphics packages are absent from all three production roles.
- **Scans:** CycloneDX SBOM, Trivy Secret and unsuppressed `HIGH,CRITICAL` scans completed with no ignore/VEX/exception. API: `174` components, Secret `0`, `4 Critical / 29 High`. Admin: `174` components, Secret `0`, `4 Critical / 29 High`. XHS: `175` components, Secret `0`, `4 Critical / 29 High`, `41` raw / `33` unique / `8` duplicate package rows, `5` rows with a reported fixed version. Browser-component matches are `0`. These findings remain evidence for later disposition; none was waived here.
- **Signer acceptance:** pinned XHS asset SHA values and `crypto-js 4.2.0` passed. A synthetic GET search-recommend wrapper smoke passed in `network=none` with three non-empty response fields and no real Cookie/session. A production-shaped synthetic POST search-notes smoke with `needs_rap=true` consistently returned wrapper exit code `1` and no `x_rap_param`; this affects the committed note-search and note-detail paths. The failure is a release blocker. A later shell-only phase diagnostic was itself malformed and is not used as product evidence; the bounded wrapper result remains authoritative.
- **Evidence:** `/opt/noteai-build/evidence-33d04d4-xhs-browserless/acceptance-v6/` contains completed API/Admin evidence; `/opt/noteai-build/evidence-33d04d4-xhs-browserless/acceptance-final/` contains XHS evidence, scan summaries, signer pass/fail records, combined `FAILED_ACCEPTANCE` summary and a verified `SHA256SUMS`. Final evidence recorded `RUNNING_CONTAINERS_AFTER=0`, `ACR_AUTH_ENTRIES=0`, and `EVIDENCE_CHECKSUMS=PASS`.
- **Rollback/retention:** images and evidence remain local and unpushed. Do not delete images/cache or release the builder without a separate lifecycle approval. Because no production/registry state changed, release rollback is simply to leave these candidates unused.
- **Successor:** `PROD-XHS-RAP-FIX-001` and its clean successor rebuild are recorded below. These old images remain blocked and must not be reused.

### PROD-XHS-RAP-FIX-001 — Isolate and verify the offline RAP signer wrapper

- **Status:** `VERIFIED` on 2026-07-23. Independent verification found no unresolved Critical or High application defect.
- **Root cause:** `xhs_main_260411.js` installs process-global shims, including a proxied `globalThis`. The old wrapper then evaluated `xhs_rap.js` with `vm.runInThisContext`, so the RAP asset inherited the polluted global state and failed with an internal `TypeError`. The pinned RAP asset itself passed when evaluated independently.
- **Minimum correction:** only the application-owned `model/vendor/spider_xhs/signer.js` changed. RAP now executes in a fresh `vm.createContext` that exposes only `Buffer`, URL/TextEncoder primitives, timers, a quiet console, and a restricted `require` that accepts only `crypto` and maps it to `node:crypto`. It does not expose `process`, filesystem/network modules, host `globalThis`, or full `require`. The RAP asset is loaded relative to `__dirname`, making the wrapper independent of process CWD. Upstream signer output is silenced so stdout remains one JSON object.
- **Pinned assets:** `xhs_main_260411.js` SHA256 `723dc6ef64836b0998aa4ba85796e2ffd99bfb20f222d69adcbcf66ea589292d` and `xhs_rap.js` SHA256 `e79fe1c79c97a73fbf5fdb6420af114ff591902aa60b436ac4b803a99b806d2e` remain byte-identical to HEAD and the clean locked upstream source.
- **Regression coverage:** `crypto-js` is fixed to dev-only version `4.2.0` with lockfile integrity matching the Docker build. CI now installs Node 20 dependencies using `npm ci --ignore-scripts`. The wrapper-level test starts real Node processes from repo root, blocks bare and `node:` forms of `dgram`, `dns`, `http`, `http2`, `https`, `net`, and `tls`, and blocks `fetch`. Basic search-recommend and RAP search-notes return exact non-empty field sets, empty stderr and JSON-only stdout without echoing the synthetic `a1` or body. Disallowed endpoints fail closed with no stdout/stderr.
- **Independent evidence:** basic PASS (`rc=0`), RAP search PASS (`rc=0`), and additional RAP feed PASS (`rc=0`) using real `crypto-js 4.2.0`; all outputs stayed below `64 KiB`, contained only expected non-empty signature fields, and disclosed no synthetic input. Missing `a1`, bad method and bad endpoint all returned `rc=1` with empty output. All 15 tested network entry points were denied.
- **Verification:** XHS suite `24/24`; full unit suite `626` passed with `5` existing skips; Python network-attempt counter `0`; production readiness `83/83`; Node/Python syntax, `docker compose config --quiet`, `npm ci --ignore-scripts`, npm audit, diff check and high-confidence Secret scan passed. The apparent provider URLs/errors in test logs came from mocks and failure-contract assertions, not real calls.
- **GitHub CI closure:** the first pushed RAP-fix commit `ca02335513a752ece2dabe71d08105ae86db6c5a` passed the new Node 20 wrapper test but reproduced the same six pre-existing XHS acquisition failures as parent `33d04d4`. Root cause was test setup copying `.env.example` (adapter selected and collection suspended) without a runtime role, causing local/legacy fixture tests to fail closed before their mocks. The CI job now explicitly uses the `local` role and empty adapter/suspension values; individual direct-runtime tests continue to set their own fail-closed environment. This is test-environment isolation only and does not change `.env.example`, production defaults or runtime behavior.
- **Changed scope:** `model/vendor/spider_xhs/signer.js`, `tests/test_spider_xhs_http.py`, `tests/fixtures/xhs_signer_no_network.cjs`, `package.json`, `package-lock.json`, `.github/workflows/ci.yml`, and this Handoff. No business, billing, quota, database, Docker runtime target, Compose/Render role, production data or cloud resource changed.
- **Rollback:** revert application commit `ca02335` and the separate CI/Handoff closure commit, and keep every old local image unused. No registry, deployment or production rollback is required because none was touched.
- **Next gate:** the separately approved `PROD-IMG-XHS-BROWSERLESS-REBUILD-001` completed as recorded below. Do not repeat it or approve ACR/deployment for its current local images.

### PROD-IMG-XHS-BROWSERLESS-REBUILD-001 — Rebuild and scan the RAP-fixed browserless AMD64 roles

- **Status:** `VERIFIED` on 2026-07-23 for the authorized local build/scan scope. The three image candidates are **release-blocked** and are not approved for ACR or deployment.
- **Exact source:** clean detached worktree `/opt/noteai-build/repo-ca02335-exact-r1` at full application commit `ca02335513a752ece2dabe71d08105ae86db6c5a`. Final `git status --porcelain` was empty, `git lfs fsck` passed, and the V0.4 machine manifest verified all three `.lgb` artifacts plus the declared training report in each image. Branch tip at rebuild time `344897c36f7cb69a9dc4d8fe1794b6170722e6fd` differed only in CI/Handoff files and was not an OCI application revision.
- **Builder/boundary:** retained isolated native AMD64 ECS `i-wz99180s9ig5ecq10uaj` / `noteai-build-amd64-b6abaa7-r1`, Shenzhen F, `x86_64`, 4 vCPU / 16 GiB. It remained in the build VPC with zero inbound security-group rules, no RAM role, no load balancer and no production data-network membership. The task never targeted API-C/API-F, RDS or Tair. Docker registry auth entries remained `0`; no ACR login/read/push occurred.
- **Build mechanics:** the source Dockerfile and both pinned multi-arch base digests were unchanged. The configured Alibaba Docker mirror could not serve the pinned base digest; the daemon mirror was temporarily and reversibly switched to DaoCloud only for the native build, then restored byte-for-byte to `https://0fjuh2bu.mirror.aliyuncs.com/`. No running container remained.
- **Local candidates:** `noteai-local:git-ca02335-amd64-api-r1` / local image ID `sha256:5fa36abe1c603aa0abc1295912fe6ee16a0b468d8be216475be06a4daa9a6454` / size `1,044,230,106` bytes; `noteai-local:git-ca02335-amd64-admin-r1` / `sha256:6d3b5ee2dd4619a60394ad4e026287fe4b5a9a39dd722c37954fe58627369865` / `1,044,230,108` bytes; `noteai-local:git-ca02335-amd64-xhs-http-r1` / `sha256:755e337c2932ef53187b5af333b1daa47be578a81af9a57d6c1af7a9368b3b60` / `1,044,718,005` bytes. These are local Docker image IDs, **not** ACR registry digests; all three have `RepoDigests=[]`.
- **Provenance/content acceptance:** all three are `linux/amd64`, use non-root `noteai` UID `999`, carry exact OCI revision `ca02335513a752ece2dabe71d08105ae86db6c5a`, source, version `git-ca02335-amd64-r1`, created and role labels, use `/app/scripts/docker_entrypoint.sh`, and have role-correct CMD/marker/health metadata. API/Admin use `/health/live`; XHS correctly records `Healthcheck.Test=["NONE"]`. `mttravel 1.0.16` and bundle SHA `8a0527bb6e8b9074cf0221756f35bca989945e8436e4841596a7b7bf79ae06d8`, `crypto-js 4.2.0`, signer asset SHA values `723dc6ef...589292d` and `e79fe1c7...b806d2e`, and all model SHA checks passed. Installed Playwright, Chromium/browser binaries and browser caches are absent. The only sensitive-like filename is the public template `/app/model/.env.example`; raw Trivy Secret findings are `0`.
- **SBOM and unsuppressed scans:** Trivy `0.70.0` refreshed its vulnerability DB on 2026-07-23 before scanning. Scanner workdir was empty; no ignore file, `--ignore-unfixed=false`, no VEX and no exception were used. API: CycloneDX `174`, Secret `0`, `33` raw / `33` unique, `4 Critical / 29 High`, `10` with a reported fix. Admin: `174`, Secret `0`, same `33` unique and severity/fix counts. XHS: `175`, Secret `0`, same `33` unique and severity/fix counts. The three vulnerability sets are identical.
- **Finding disposition:** the four Critical rows are on Debian `perl-base 5.40.1-6`. Ten High rows are on installed and used `pillow 12.2.0`, with scanner-recorded fixed version `12.3.0`. The remaining High rows are Debian base packages with no `FixedVersion` in this scan. No finding is suppressed or waived. Independent repository review confirmed PIL is imported by `model/extract_cover_features.py`; the Pillow rows must be removed before any later risk disposition.
- **Signer acceptance:** production-equivalent `NODE_PATH=/opt/noteai/xhs-node/node_modules` was supplied only to the disposable command, matching `SpiderXHSSigner`. Synthetic basic search-recommend and RAP search-notes both passed in `network=none` as non-root `noteai`, with read-only root filesystem, `cap-drop ALL`, `no-new-privileges`, bounded PID/CPU/memory and no real Cookie/session/provider call. The initial direct-node attempt omitted the production `NODE_PATH` and failed before execution; it is a harness error and is not product evidence. Final basic/RAP responses contained exactly the required non-empty fields and did not echo synthetic input.
- **Evidence:** `/opt/noteai-build/evidence-ca02335-xhs-browserless-rebuild-r1/` contains build logs, inspect/history, content/model checks, CycloneDX/Secret/vulnerability JSON, package TSVs, signer summaries and final integrity evidence. It contains `62` files; `SHA256SUMS` SHA256 is `333697df3ad085325b5f6a7e3ffadbf5bddd5ad7d7fd11e885b92752cfc6c737`. Final state recorded clean exact source, LFS fsck PASS, running containers `0`, Docker auth entries `0` and restored original mirror.
- **Independent review:** source/config review found the three-role image design, lack of browser dependencies, role startup protection, model/signing pins and identical role vulnerability sets structurally consistent with exact revision `ca023355`. It separately confirmed `344897c` is CI/Handoff-only and that Pillow is a live dependency. The review did not reproduce the ECS raw bytes locally, so the retained raw ECS evidence and checksum manifest remain mandatory release provenance.
- **Release decision:** execution scope complete; images **BLOCKED**. `PROD-IMG-002` remains blocked by unsuppressed `4 Critical / 29 High` and the absence of an approved VEX/exception. Do not relabel, push or deploy these local IDs.
- **Successor status:** `PROD-PILLOW-12.3.0-FIX-001`, the clean three-role rebuild/rescan from exact application revision `a635692a899ee02c6905cd694611c14e0da4594a`, residual Debian disposition, residual decision, constraint proof and independent formal VEX review all completed as recorded below. Existing images remain immutable and unchanged; ACR still requires explicit approval.

### PROD-PILLOW-12.3.0-FIX-001 — Upgrade the shared browserless Pillow runtime pin

- **Status:** `VERIFIED` on 2026-07-23 at exact application revision `a635692a899ee02c6905cd694611c14e0da4594a`; independent review found no unresolved Critical or High repository issue.
- **Change:** `model/requirements-api.txt` changes only `pillow==12.2.0` to `pillow==12.3.0`. API, Admin and XHS inherit the same `runtime-common` install, while compatibility and legacy Worker requirement files recursively reference this production list. Dockerfile, Compose, Render roles, business behavior and other dependencies are unchanged.
- **Regression coverage:** production readiness now requires the exact `pillow==12.3.0` pin. A new unit test creates a deterministic PNG, verifies Pillow open/save and `ImageStat`, then runs the actual `image_to_b64` and `extract_deterministic` paths and checks stable media type and image features.
- **Compatibility:** an isolated Python `3.11.14` environment installed the public Pillow `12.3.0` CPython 3.11 wheel; PNG/JPEG/WebP round-trips, `ImageStat` and WebP support passed. The project test environment also ran with Pillow `12.3.0`; `pip check` reported no broken requirements.
- **Verification:** targeted `16/16`; full unit suite `627` passed with `5` skipped; production readiness `83/83`; model-artifact check, quality gate, Python compilation, Compose parse, diff and changed-file sensitive scan passed. GitHub CI runs `29982041413` and `29982043526` completed successfully for exact SHA `a635692a899ee02c6905cd694611c14e0da4594a`, including the repository's Python `3.11` dependency install and full test workflow. Apparent provider failure text in the local unit log is produced by a test-owned fake client and does not represent an external call.
- **Independent review:** confirmed the single-pin scope, three-role dependency inheritance, test correctness and absence of Docker/ACR/deployment/production/provider/VEX/cloud changes. It found no Critical or High issue and allowed the commit gate.
- **Image impact:** the successor image task below now proves Pillow `12.3.0` in all three exact `a635692` roles and proves all ten prior Pillow High rows absent. Historical `ca023355` images remain immutable and superseded.
- **Rollback:** revert application commit `a635692a899ee02c6905cd694611c14e0da4594a`; no registry, deployment, production or cloud rollback is required.
- **Next gate:** completed by `PROD-IMG-XHS-PILLOW-REBUILD-001` below. Stop before ACR or deployment; next perform read-only residual Debian disposition.

### PROD-IMG-XHS-PILLOW-REBUILD-001 — Rebuild and scan the Pillow-fixed browserless AMD64 roles

- **Status:** `VERIFIED` on 2026-07-23 for the authorized local build/scan scope. The three candidates remain **release-blocked** and are not approved for ACR or deployment.
- **Exact source:** clean detached `/opt/noteai-build/repo-a635692-pillow-r2` at full application commit `a635692a899ee02c6905cd694611c14e0da4594a`. Final `git status --porcelain` was empty, `git lfs fsck` passed and the exact release artifacts/manifests matched their recorded hashes. Branch/Handoff tip `4704c1617a169f6d925a1b16e90aba0f8b88d02b` was not used as an OCI revision.
- **Builder/boundary:** retained isolated native AMD64 ECS `i-wz99180s9ig5ecq10uaj` / `noteai-build-amd64-b6abaa7-r1`, Shenzhen F, `x86_64`, 4 vCPU / 16 GiB. It remained in the separate build VPC with zero inbound security-group rules and no production data-network membership. The task never targeted API-C/API-F, RDS or Tair. Docker registry auth entries remained `0`; no ACR login/read/push occurred.
- **Build execution:** immutable Python and Node base digests, source Dockerfile and OCI values were unchanged. The first default-network attempt was stopped after validated target PIDs made no progress; the first host-network retry failed on a public PyPI CDN timeout and produced no candidate. The second host-network retry completed all three targets and cached the shared browserless runtime. These failures are retained as audit evidence and are not acceptance results.
- **Local candidates:** API `noteai-local:git-a635692-amd64-api-r1`, local image ID `sha256:b1983bab928ef93495d8be020030917d4ae54364234390047c3163af5414fedb`, size `1,044,383,616` bytes; Admin `noteai-local:git-a635692-amd64-admin-r1`, `sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f`, `1,044,383,618` bytes; XHS HTTP `noteai-local:git-a635692-amd64-xhs-http-r1`, `sha256:5b44114d4bd9c28a8e93c39140466c542e8babeead038fb0d1cfe45c3cd75966`, `1,044,871,515` bytes. These are local Docker image IDs, **not** ACR registry digests; all have `RepoDigests=[]`.
- **Provenance/content acceptance:** all three are `linux/amd64`, non-root `noteai` UID/GID `999`, carry exact OCI revision/source/version `git-a635692-amd64-r1`/created labels and role labels, use `/app/scripts/docker_entrypoint.sh`, and have role-correct CMD/marker/health metadata. API/Admin use `/health/live`; XHS records `Healthcheck.Test=["NONE"]`. Pillow is exactly `12.3.0`; setuptools/wheel, installed Playwright, Chromium/browser binaries, actual `.env` and `.git` paths are absent. `mttravel 1.0.16`, its bundle SHA, `crypto-js 4.2.0`, both signer asset SHAs, three V0.4 models, train report, audit/readiness/training-health, human/machine release manifests and model registry all passed exact SHA checks.
- **SBOM/Secret/vulnerability evidence:** Trivy `0.70.0` used the retained 2026-07-23 database offline in `network=none` containers. There was no ignore file, no suppression/VEX/exception, `--ignore-unfixed=false` was explicit and High/Critical reports exited `1` as expected. API: SBOM `174`, Secret `0`, `23` raw/unique, `4 Critical / 19 High`, fixed-version rows `0`, Pillow rows `0`. Admin is identical with SBOM `174`. XHS HTTP is identical with SBOM `175`. Compared with exact `ca023355`, ten Pillow High rows were removed and no residual row gained a reported fix.
- **Signer acceptance:** basic search-recommend and RAP search-notes synthetic inputs passed inside the XHS image as UID/GID `999`, `network=none`, read-only root filesystem, drop all capabilities, `no-new-privileges` and bounded PID/CPU/memory. The network-blocking fixture was read-only mounted; only output length/SHA summaries were recorded. No a1/signature value, Cookie/session or real provider call was output or used.
- **Evidence/cleanup:** `/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/` contains build logs, inspect/history/runtime checks, CycloneDX/Secret/vulnerability JSON and signer summaries. Final manifest covers `46` files and about `3.7 MiB`. All stage checksum manifests passed; exact source remained clean; temporary scan/smoke directories were removed; running containers `0`, build processes `0`, Docker auth entries `0`.
- **Harness notes:** intermediate acceptance/scan/smoke harness attempts stopped on quoting, stale abbreviated-hash, undersized tmpfs, shell-continuation or read-permission errors before producing valid acceptance. Each disposable container was removed, no NoteAI image/environment/cloud resource was modified and only the final successful runs are acceptance evidence.
- **Release decision:** local execution scope complete; images **BLOCKED**. `PROD-IMG-002` remains blocked by unsuppressed `4 Critical / 19 High` and the absence of a reviewed residual disposition. Do not relabel, push or deploy these local IDs.
- **Next task:** request approval for read-only `PROD-BROWSERLESS-OS-VULN-DISPOSITION-001`; no ACR task is next.

### PROD-BROWSERLESS-OS-VULN-DISPOSITION-001 — Review residual Debian image findings

- **Status:** `VERIFIED` on 2026-07-23 for the authorized read-only review; no image or release acceptance was granted.
- **Priority:** Critical before registry release
- **Evidence identity:** every exact `a635692` role has the same unsuppressed `23` raw/unique package rows: `4 Critical / 19 High`, fixed-version rows `0`, Pillow rows `0`. They collapse to 12 unique CVEs because `CVE-2025-69720` maps to four ncurses packages and `CVE-2026-53615` maps to nine util-linux binary packages. Raw JSON and CycloneDX SBOMs remain under `/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/`.
- **Read-only execution:** Cloud Assistant targeted only isolated builder `i-wz99180s9ig5ecq10uaj`. Execution `t-sz06rs3xcs8n400` normalized the three reports and proved identical CVE/package/version sets. Execution `t-sz06rs4kvi02ha8` read the existing API SBOM and confirmed the installed affected package families. Commands only used `jq`, `sha256sum`, `find`, `sort` and shell built-ins; they did not write files, start containers/services, access registries, read secrets or target API-C/API-F. Local repository static search at exact `a635692` returned no production-role invocation of Perl, Archive::Tar, IO::Compress, Storable, infocmp, gzip, blkid, ACL tools or mount.
- **Base-image state:** the image remains pinned to official `python:3.11.15-slim-trixie` multi-arch index `sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`, with AMD64 child `sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045`. The current official Docker Hub tag still resolves to the same AMD64 child, so rebuilding the same source today would not change these rows.
- **Package/module proof:** `perl-base 5.40.1-6`, `ncurses-bin 6.5+20250216-2`, `gzip 1.13-1`, `util-linux/libblkid 2.41-5` and `libacl1 2.3.2-2+b1` are installed. Neither the SBOM nor Debian's official `perl-base` AMD64 file list contains `Archive::Tar`, `IO::Compress` or `Storable`; the file list does contain `/usr/bin/perl`. Debian marks `perl-base`, `ncurses-bin`, `gzip` and `util-linux` Essential, so removing them in-place from this Debian runtime is not a minimum safe change.
- **Disposition table:**

| Severity / CVE | Scanner package rows | Installed affected artifact | Static reachability disposition | Official Trixie fix state | Minimum safe path |
|---|---|---|---|---|---|
| Critical `CVE-2026-13221` | `perl-base` | Yes, Perl core | `NO_CONFIGURED_PATH`: no role/entrypoint invokes Perl or compiles untrusted Perl regex; not a formal VEX conclusion | Trixie/unstable unfixed; upstream fixed in 5.43.10 | Formal evidence review, or a separately designed minimal final rootfs without Perl; do not mix unstable packages |
| Critical `CVE-2026-42496` | `perl-base` | **No** `Archive::Tar` module in SBOM or `perl-base` file list | `NOT_INSTALLED` | Trixie postponed; upstream Archive::Tar 3.08 | No image change required for the absent module; formal release disposition still required |
| Critical `CVE-2026-57433` | `perl-base` | **No** `Storable` module in SBOM or `perl-base` file list | `NOT_INSTALLED` | Trixie vulnerable; forky/sid Perl 5.40.1-8 fixed | No image change required for the absent module; do not import forky/sid Perl into Trixie |
| Critical `CVE-2026-8376` | `perl-base` | Perl exists, but finding requires a 32-bit build | `NOT_APPLICABLE_ARCH`: exact images are `linux/amd64` | Trixie vulnerable; forky/sid 5.40.1-8 fixed | No image change for AMD64; formal architecture disposition still required |
| High `CVE-2025-69720` | `libncursesw6`, `libtinfo6`, `ncurses-base`, `ncurses-bin` | Yes; affected code is the `infocmp` CLI | `NO_CONFIGURED_PATH`: no role invokes `infocmp` or accepts terminfo input | Trixie no-DSA; forky/sid fixed in ncurses 6.6 | Formal evidence review, or minimal-rootfs removal of the CLI; do not remove Essential ncurses in-place |
| High `CVE-2026-41992` | `gzip` | Yes, `/usr/bin/gzip` | `NO_CONFIGURED_PATH`: no role invokes a multi-file `gzip -d` workflow | Trixie/unstable unfixed; Debian rates minor/no-DSA | Formal evidence review, or minimal-rootfs removal of the CLI; do not remove Essential gzip in-place |
| High `CVE-2026-42497` | `perl-base` | **No** `Archive::Tar` module | `NOT_INSTALLED` | Trixie postponed; upstream Archive::Tar 3.08 | Same as `CVE-2026-42496` |
| High `CVE-2026-48962` | `perl-base` | **No** `IO::Compress` module | `NOT_INSTALLED` | Trixie vulnerable; forky/sid fixed | No image change required for absent module; do not mix unstable packages |
| High `CVE-2026-53615` | nine `util-linux` binary-package rows; vulnerable code is in `libblkid` | Yes, `libblkid.so.1` | `UNKNOWN`: no configured role call or device mapping was found, but existing SBOM/config evidence alone cannot prove absence of all transitive dynamic use | Trixie, forky and sid unfixed | Keep blocked; either independently prove/enforce no device/partition-parser path and make a formal decision, or move to a reviewed minimal final rootfs that omits libblkid |
| High `CVE-2026-54369` | `libacl1` | Yes, `libacl.so.1` | `UNKNOWN`: images run as UID/GID 999 and no ACL call was found, but existing evidence cannot prove no transitive pathname API use | Trixie point update planned; forky/sid 2.4.0-1 fixed | Keep blocked; either independently prove/enforce non-root/no-privilege/no-ACL path and make a formal decision, or use a reviewed runtime without libacl / later fixed Trixie base |
| High `CVE-2026-57432` | `perl-base` | Yes, Perl core | `NO_CONFIGURED_PATH`: no production role invokes Perl or accepts a Perl pack/unpack template | Trixie vulnerable; forky/sid 5.40.1-8 fixed | Formal evidence review, or a separately designed minimal final rootfs without Perl |
| High `CVE-2026-9538` | `perl-base` | **No** `Archive::Tar` module | `NOT_INSTALLED` | Trixie/unstable unfixed and postponed | No image change required for absent module; formal release disposition still required |

- **Release interpretation at completion of this read-only task:** six unique CVEs had decisive non-affected evidence (`5 NOT_INSTALLED`, `1 NOT_APPLICABLE_ARCH`), four had high-confidence static `NO_CONFIGURED_PATH` evidence, and two High CVEs remained `UNKNOWN`. The successor constraint proof and independent formal VEX review now close those evidence/decision gaps; raw reports still remain canonical and unsuppressed.
- **Minimum remediation decision:** a same-digest rebuild or ordinary Trixie `apt upgrade` cannot remove the rows, and importing individual forky/sid packages into Trixie is rejected. The selected non-waiting Path A—formal exact-product disposition plus enforced deployment constraints—is now independently verified. The minimal/distroless path remains a contingency if any reviewed identity or constraint changes.
- **Safety:** no exploit/PoC/payload/malformed input, symbol/memory/sandbox probe or runtime exploitability test was created or run. No VEX/exception, suppression, image build, ACR access, deployment, production/provider call or cloud-resource mutation occurred. The two Cloud Assistant executions created normal audit-history records only.
- **Next gate:** request read-only `PROD-BROWSERLESS-RESIDUAL-DECISION-001` to prepare an independently reviewable decision package comparing constrained formal disposition versus a minimal/distroless final runtime; it must not write formal VEX/exception, build, access ACR or deploy. `PROD-IMG-002` stays blocked.

### PROD-BROWSERLESS-RESIDUAL-DECISION-001 — Independently reviewable final disposition paths

- **Status:** `VERIFIED` on 2026-07-23 for the authorized read-only decision scope; no release acceptance, formal VEX, exception or suppression was granted.
- **Exact evidence identity:** the decision applies only to the three local `linux/amd64` role images built from application/OCI revision `a635692a899ee02c6905cd694611c14e0da4594a`: API local ID `sha256:b1983bab928ef93495d8be020030917d4ae54364234390047c3163af5414fedb`, Admin `sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f`, and XHS HTTP `sha256:5b44114d4bd9c28a8e93c39140466c542e8babeead038fb0d1cfe45c3cd75966`. These are local IDs, not registry digests. Every role retains the same unsuppressed `23` package rows (`4 Critical / 19 High`) and retained CycloneDX SBOM/Trivy evidence under `/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/`.
- **Decision outcome:** choose **Path A — exact-product formal disposition for ten CVEs plus a separately implemented constrained-deployment proof for `libblkid` and `libacl`**. It preserves the already tested Python `3.11.15` application runtime and can avoid an image rebuild if the proof closes using deployment configuration plus the immutable current images. **Path B — a minimal/distroless runtime** remains the contingency if either library cannot be closed non-invasively or the deployment platform cannot enforce/read back the required controls.

#### Path A1 — formal disposition design for the ten high-confidence CVEs

The future VEX authoring task should use a separate CycloneDX VEX BOM rather than mutating the retained SBOM. Each assertion must be scoped to the exact role product, exact local image ID and SBOM serial/hash; if a later ACR push is separately approved, the final signed/attested statement must be reissued against the immutable registry digest before deployment. Keep four distinct artifacts: raw unsuppressed Trivy JSON, the VEX document, VEX-applied Trivy JSON with suppressed rows visible, and the independent review record. Trivy's VEX support is experimental, so the raw report remains canonical audit evidence and no raw row may be deleted.

| CVE set | Future state | Machine justification | Required impact evidence |
|---|---|---|---|
| `CVE-2026-42496`, `CVE-2026-42497`, `CVE-2026-9538` | `not_affected` | CycloneDX `code_not_present`; CISA/CSAF mapping `vulnerable_code_not_present` | Exact SBOM and official `perl-base` file list show no `Archive::Tar`; scanner source-package mapping alone does not install the vulnerable module |
| `CVE-2026-57433` | `not_affected` | `code_not_present` / `vulnerable_code_not_present` | Exact SBOM and package file list show no `Storable` |
| `CVE-2026-48962` | `not_affected` | `code_not_present` / `vulnerable_code_not_present` | Exact SBOM and package file list show no `IO::Compress` |
| `CVE-2026-8376` | `not_affected` | CycloneDX `requires_environment`; interoperable CSAF mapping `vulnerable_code_not_present` | Exact artifact is AMD64 and contains no affected 32-bit build; record architecture and scanner metadata explicitly |
| `CVE-2026-13221`, `CVE-2026-57432` | `not_affected` | `code_not_reachable` / `vulnerable_code_not_in_execute_path` | Role marker, entrypoint allowlist and exact-source search show no production Perl execution or attacker-controlled Perl regex/pack template |
| `CVE-2025-69720` | `not_affected` | `code_not_reachable` / `vulnerable_code_not_in_execute_path` | No role invokes `infocmp` or accepts terminfo input |
| `CVE-2026-41992` | `not_affected` | `code_not_reachable` / `vulnerable_code_not_in_execute_path` | No role invokes the affected multi-file gzip decompression workflow |

An independent reviewer who did not implement the runtime/configuration must confirm the package PURLs, application revision, image identity, OS/architecture, SBOM and Trivy hashes, entrypoint/command graph, assessment date and evidence hashes. Each assertion requires a review trigger for any base digest, package version, role command, entrypoint, architecture, deployment capability/device policy or upstream CVE-metadata change. The five absent-module assertions, the architecture assertion and four no-execute-path assertions are ready to enter that review workflow; this task did not author or register them.

#### Path A2 — required proof for `libblkid` and `libacl`

- **Current result:** the successor `PROD-BROWSERLESS-CONSTRAINT-PROOF-001` is independently `VERIFIED`. All production roles now have an enforceable repository deployment contract and effective local runtime read-back for UID/GID `999`, `cap_drop: ALL`, `no-new-privileges`, read-only root, bounded tmpfs/data writes, no devices, no privileged mode and no host namespace. Offline ELF dependency closure found neither `libblkid.so.1` nor `libacl.so.1` in the accepted executable/native-extension graph for any exact retained role image.
- **Safe evidence required:** use only package ownership, SBOM and offline ELF `DT_NEEDED` dependency closure for the allowlisted Python/Node/mttravel/native-wheel runtime; do not use exploit, PoC, malformed input, symbol hunting or vulnerability trigger probes. Record whether `libblkid.so.1` or `libacl.so.1` is loaded by any accepted executable/native extension.
- **Deployment constraints required for every role:** explicit `user: "999:999"`; `cap_drop: [ALL]`; `security_opt: [no-new-privileges:true]`; read-only root filesystem; bounded `tmpfs` only where proven necessary; explicit UID-owned writable data/artifact/cache mounts; `privileged: false`; no `devices`, host block-device or broad host-path mounts; no `CAP_SYS_ADMIN`, `CAP_SYS_RAWIO` or `CAP_MKNOD`; and no setuid/setgid helper in the accepted executable surface.
- **Acceptance for `CVE-2026-53615`:** the allowlisted execution/dependency graph does not load or call the affected libblkid path, and the runtime has no block-device/image input or privilege needed to create one. If the library is absent from the graph, use `vulnerable_code_not_in_execute_path`; if it is necessarily loaded, only an independently accepted proof that no adversary can control the affected path may use `vulnerable_code_cannot_be_controlled_by_adversary`.
- **Acceptance for `CVE-2026-54369`:** the allowlisted execution/dependency graph does not call the affected libacl pathname path, and non-root/capability/mount constraints prevent a privileged adversary-controlled path. The same justification choice rule applies. Failure to prove either condition leaves the CVE `under_investigation` and blocks release.
- **Proof artifacts:** normalized deployment configuration, local `network=none` constrained smoke using the retained images, container-inspect/read-back showing the effective user/capabilities/security options/mounts/devices/read-only state, evidence hashes, and independent review. No production start or cloud mutation is needed for this proof phase.

#### Path B — minimal/distroless final runtime contingency

| Candidate | Benefit | Blocking migration facts | Decision |
|---|---|---|---|
| Google `gcr.io/distroless/python3-debian12:nonroot` | Open, signed, small, no package manager or shell; most plausible public candidate | Debian 12 Python is `3.11.2`, not exact `3.11.15`; current shell entrypoint/start scripts cannot run; official-Python `/usr/local` virtualenv/site paths do not directly match distroless `/usr/bin`; all native wheels and `libgomp` need a new dependency closure; XHS also requires separately copied Node/crypto-js | Best **contingency**, not a drop-in or current minimum |
| Google `python3-debian13:nonroot` | Current Debian generation and minimal surface | Debian 13 default is Python `3.13`, requiring a Python-version migration plus full compatibility test | Reject for this release |
| Chainguard Python `3.11` | Minimal non-root runtime with vendor patch stream | Free tier exposes primarily `latest`; maintained version streams/SLAs and immutable unique-tag workflow generally require production subscription; Wolfi/native-wheel/Node compatibility must be evaluated | Consider only after commercial/vendor approval |
| Custom Python `3.11.15` rootfs on distroless `base`/`cc` | Could retain exact CPython | Must manually carry CPython, CA/tzdata, all shared libraries, native-wheel closure, `libgomp` and Node signer; highest omission, provenance and maintenance burden | Not recommended as minimum |
| Alpine or in-place removal from Trixie slim | Smaller apparent package set | musl/native-wheel migration risk; Perl/gzip/ncurses/util-linux are Debian Essential and unsafe to strip in-place | Reject |

Any Path B choice requires a new application/Docker revision, digest-pinned base, shell-free Python launcher/role guard, native AMD64 rebuild of all three roles, full unit/readiness/integration checks, model and signer acceptance, SBOM/Secret/content/provenance scans and a new residual vulnerability decision. The exact residual count cannot be promised before that rebuild.

#### Independent route comparison and recommendation

| Criterion | Path A: constrained disposition | Path B: minimal/distroless |
|---|---|---|
| Preserves exact tested app/Python | Yes, `a635692` / Python `3.11.15` | No, unless using the highest-risk custom rootfs |
| New image build required | Not if deployment-only proof passes | Yes, all three roles |
| Ten high-confidence CVEs | Formal exact-product dispositions | Likely removed, but only a new SBOM/scan can prove it |
| Two `UNKNOWN` CVEs | Must close with dependency plus least-privilege proof | Must prove libraries absent in new SBOM/runtime closure |
| XHS Node signer | Unchanged | New Node/runtime packaging and regression |
| Deployment portability | Strongest on controlled Alibaba ECS Docker host; current Render file cannot prove all controls | Strong if migration succeeds |
| Change/regression risk | Low to medium | High |
| Relative effort/cost | One hardening/evidence cycle, then independent VEX review | Multiple implementation/build/scan cycles; possible Chainguard subscription |

- **Recommendation:** proceed with Path A. It is a standards-based release decision, not a production exception and not a claim that scanner findings disappeared. If the constrained proof fails for either library or the chosen production platform cannot enforce/read back the controls, stop and authorize Path B using Google Distroless Debian 12 as the first prototype candidate.
- **Official decision references:** CISA Minimum Requirements for VEX (`https://www.cisa.gov/sites/default/files/2023-04/minimum-requirements-for-vex-508c.pdf`) and Status Justifications (`https://www.cisa.gov/sites/default/files/publications/VEX_Status_Justification_Jun22.pdf`); CycloneDX vulnerability exploitability and 1.7 analysis fields (`https://cyclonedx.org/use-cases/vulnerability-exploitability/`, `https://cyclonedx.org/docs/1.7/proto/`); OASIS CSAF 2.1 VEX (`https://docs.oasis-open.org/csaf/csaf/v2.1/csaf-v2.1.html`); Trivy local VEX/show-suppressed behavior (`https://trivy.dev/docs/dev/supply-chain/vex/file/`); Docker Compose service security controls (`https://docs.docker.com/reference/compose-file/services/`); Google Distroless supported images/entrypoint constraints (`https://github.com/GoogleContainerTools/distroless`); Debian Bookworm/Trixie Python package versions (`https://packages.debian.org/bookworm/python/python3.11`, `https://packages.debian.org/trixie/python/python3`); and Chainguard version/support policy (`https://edu.chainguard.dev/chainguard/chainguard-images/about/versions/`). Public-source reads were non-mutating.
- **Safety and stop point:** local repository and public official documentation were read only. No ECS/Cloud Assistant action, production/control-plane access, code or deployment-config change, formal VEX/exception, scanner suppression, image build, ACR access, service start or provider call occurred. Existing images and raw reports are unchanged.
- **Next gate:** `PROD-BROWSERLESS-CONSTRAINT-PROOF-001` and the successor independent formal VEX review completed as recorded below. ACR and deployment remain separately gated.

### PROD-BROWSERLESS-CONSTRAINT-PROOF-001 — Enforce and verify constrained browserless deployment

- **Status:** `VERIFIED` on 2026-07-23. Independent read-only review initially rejected two readiness-parser bypasses, then confirmed the minimal fixes and returned final `PASS` with no new Critical, High or Medium issue.
- **Repository release:** deployment-control commit `253fde55fa609676a9fca5c14fdf6aeceef74000`, message `fix(prod): enforce browserless runtime constraints [skip render]`. It changes deployment configuration, readiness checks, tests and documentation only. It is not an application/image revision; the three retained images still identify exact OCI application revision `a635692a899ee02c6905cd694611c14e0da4594a`.
- **Production contract:** new `deploy/production/docker-compose.yml` references each role only as `repository@sha256:<64-lowercase-hex>`, uses an external root-managed env file, and grants only `/app/model/data` as a writable bind plus bounded `/tmp`. API, Admin, XHS Trends and XHS Tracking all enforce `user: "999:999"`, `read_only: true`, `privileged: false`, `cap_drop: [ALL]` and `security_opt: [no-new-privileges:true]`; they have no `cap_add`, `devices`, host namespace or dangerous capability. Local `docker-compose.yml` carries the same runtime controls but remains explicitly a development topology.
- **Readiness protection:** `tools/production_readiness_gate.py` now validates every role and rejects missing/comment-spoofed UID, privileged mode, devices, dangerous capabilities and quoted or unquoted host network/PID/IPC namespaces. Regression tests include the independently found `user: "0:0" # user: "999:999"` and `network_mode: "host"` bypass forms.
- **Exact retained images:** API `sha256:b1983bab928ef93495d8be020030917d4ae54364234390047c3163af5414fedb`; Admin `sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f`; XHS HTTP `sha256:5b44114d4bd9c28a8e93c39140466c542e8babeead038fb0d1cfe45c3cd75966`. These are local image IDs, not ACR digests.
- **Isolated ECS evidence:** only retained builder `i-wz99180s9ig5ecq10uaj` in Shenzhen F was targeted. Final evidence is under `/opt/noteai-build/evidence-a635692-constraint-proof-r1`; final evidence-script SHA256 is `75b7d8393de4e259fcc6303ecffa51a063b59266fc10dfe357fedaf7524221e6`. Final Cloud Assistant execution `t-sz06rs944x76m0w` returned `FINAL status=PASS`, evidence checksums `PASS`, running containers before/after `0/0`, and Docker auth entries `0`.
- **Package/ELF result:** all roles contain Debian `util-linux`/`libblkid` `2.41-5` and `libacl1` `2.3.2-2+b1`, but the offline ELF closure examined `1,203` ELF records, `354` accepted roots and `377` reachable objects per role and found `libblkid=False`, `libacl=False` for API, Admin and XHS HTTP. This is high-confidence `vulnerable_code_not_in_execute_path` evidence under the recorded deployment constraints; no formal VEX state was written.
- **Runtime read-back:** each smoke was `linux/amd64`, UID/GID `999`, `network=none`, read-only root, non-privileged, `cap_drop=["ALL"]`, `no-new-privileges`, zero devices, bounded `/tmp` and bounded UID-owned `/app/model/data`. API `/health/live` and `/health/ready` returned `200/200`; Admin returned `200/503` because no `ADMIN_PASSWORD` production secret was injected, matching the source's intended fail-closed readiness; XHS remained suspended and exited `1` fail-closed. No supplier or production endpoint was called.
- **Audit history:** execution `t-sz06rs8gucfu874` failed before evidence collection because its shell used an unsupported substitution; execution `t-sz06rs8ltw1lb0g` was manually stopped after host `readelf` encountered non-ELF files. No conclusion relies on either attempt. The final command added ELF-magic/file-pattern prefiltering and disabled core dumps; cleanup left zero containers.
- **Repository verification:** full unit suite `630` passed with `5` skipped; targeted deployment/readiness/security suite `25/25`; production readiness `85/85`; development and production Compose config-only checks, Python compilation and `git diff --check` passed. Unit logs containing provider failures are test-owned synthetic/fail-closed paths, not real calls.
- **Release interpretation:** the technical evidence gap for `libblkid` and `libacl` is closed for these exact images under this exact production contract. Raw Trivy evidence remains canonical and unchanged at `4 Critical / 19 High` per role. The successor formal VEX review is complete; `PROD-IMG-002` remains blocked only for explicit ACR authorization and registry-digest reissue controls.
- **Safety/rollback:** no image build, registry login/push, service deployment, production data/secret access, provider call or cloud-resource modification occurred. Rollback is a normal revert of deployment-control commit `253fde55fa609676a9fca5c14fdf6aeceef74000`; no production or registry rollback is required.

### PROD-BROWSERLESS-VEX-REVIEW-001 — Formal exact-product VEX and independent review

- **Status:** `VERIFIED` on 2026-07-23. The first independent review correctly returned `FAIL` because evidence hashes/IDs were only format-checked and the readiness Secret heuristic falsely flagged Python test container constants. The minimum fixes hard-code every reviewed image/SBOM/Trivy/constraint identity, add coordinated-tampering regression coverage and only exempt Python multiline literal opening tokens; the same independent verifier then returned final `PASS`.
- **Exact scope:** application/OCI revision `a635692a899ee02c6905cd694611c14e0da4594a`; API local image ID `sha256:b1983bab928ef93495d8be020030917d4ae54364234390047c3163af5414fedb`; Admin `sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f`; XHS HTTP `sha256:5b44114d4bd9c28a8e93c39140466c542e8babeead038fb0d1cfe45c3cd75966`; all `linux/amd64`. These remain local image IDs and are not ACR registry digests.
- **Formal decision:** one independent CycloneDX 1.6 VEX contains exactly twelve `not_affected` vulnerability objects: five `code_not_present`, one `requires_environment`, and six `code_not_reachable`. Its 69 `affects` entries resolve to exactly 23 scanner rows per role; the ncurses CVE includes four package BOM-Links per role and the util-linux CVE includes nine per role. `analysis.response` is absent, so the document does not encode `will_not_fix`, a waiver or a production exception.
- **Original artifact identity:** at independent-review commit `5b3249995522a22dc600ee7501f9328121f4497c`, VEX SHA256 was `cf30b880f95c5b0b889bce79478b2b26aa71b66aee884c7380c9dbf9adde2746`, machine evidence SHA256 was `7deb56837f833075e4579d4aaa0dd26c6ea5d4cbfcf9505ce109324f8af6d1db`, and independent review record SHA256 was `9fd0e25950a7970248e36aeed823858731b8500a08cea448e8bce945820137f9`. `PROD-IMG-002` preserves these prior-review identities inside the registry reissue record while updating the current VEX/evidence hashes.
- **Retained evidence:** SBOM serials/versions and SHA256, raw Trivy SHA256, Trivy DB metadata SHA256, exact package PURLs/BOM refs, and constraint/runtime proof SHA256 are immutable literals in the offline verifier. Only isolated builder `i-wz99180s9ig5ecq10uaj` was read through Cloud Assistant. Read execution `t-sz06rsblbtnwphc` and corrected BOM-ref execution `t-sz06rsbupffva4g` returned exit `0`. Intermediate read `t-sz06rsbrezx6g3k` stopped at exit `5` on a `jq` grouping error after the first SBOM; it wrote no file and changed no environment.
- **Validation:** official CycloneDX 1.6 schema SHA256 `1ebcb88a2c845ecb6ff7bee7aeabdff9422cb0347f3d6875b241bd444b7e098f` returned `0` validation errors. Offline bundle verifier passed; targeted VEX/readiness tests passed `21/21`; production readiness passed `86/86`; full unit suite passed `636` with `5` skipped; development and production Compose config-only checks, Python compilation and `git diff --check` passed. Test logs used synthetic/fail-closed provider paths and made no real supplier call.
- **Canonical scanner rule:** the retained raw reports remain unchanged and unsuppressed at `23` rows (`4 Critical / 19 High`) per role. The VEX is a separate impact statement; it does not delete, rewrite or silently suppress raw evidence.
- **Validity/review triggers:** any application/image ID, base digest, SBOM, package version, architecture, role/CMD/entrypoint graph, deployment capability/device/mount/namespace policy or upstream CVE scope change invalidates the current decision. `PROD-IMG-002` completed the required reissue against the three immutable ACR registry digests; any future digest or image change requires another reissue.
- **Safety/stop point:** no exploit/probe, image build, ACR login/push, service start/deployment, production access, cloud-resource mutation or real supplier call occurred. No production exception was created.
- **Successor:** `PROD-IMG-002` completed the one-time push, read-back and registry-digest VEX reissue recorded below.

### PROD-IMG-002 — Push to ACR and verify digest

- **Status:** `VERIFIED` on 2026-07-23. The three exact role images were pushed once, read back, rebound in VEX version 2 and stopped before deployment.
- **Priority:** Critical
- **Exact source and repository:** application/OCI revision `a635692a899ee02c6905cd694611c14e0da4594a`; ACR Enterprise `noteai-prod-shenzhen` / `cri-xpuhaclqkxlwy47t`, private immutable repository `noteai/app`, public host used only during the approved window `noteai-prod-shenzhen-registry.cn-shenzhen.cr.aliyuncs.com`. The production-VPC private binding was not changed and ACR was not upgraded.
- **2026-07-23 preflight:** ACR Enterprise instance `noteai-prod-shenzhen` (`cri-xpuhaclqkxlwy47t`), private namespace/repository `noteai/app`, and private registry host `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com` were re-read. Only immutable historical tags `git-ff030f5` (`linux/arm64`) and `git-ecc4702e` (`linux/amd64`) exist; the three planned `git-a635692-amd64-{api,admin,xhs-http}-r1` tags do not exist, so no overwrite collision was found.
- **Exact pre-push evidence:** Cloud Assistant observation `t-sz06rsfdd0xgfls` exited `0` on only isolated builder `i-wz99180s9ig5ecq10uaj`: builder `x86_64`, running containers `0`, all three local IDs/`linux/amd64`/OCI revision/source/version/created/role/entrypoint/CMD values unchanged, every retained SBOM/Trivy/constraint SHA unchanged, and `RepoDigests=[]`. Earlier assertion `t-sz06rsf7tpz3ugw` exited `2` only because it incorrectly required Docker `Config.User=999:999`; the accepted image uses named user `noteai` whose verified runtime UID/GID is `999:999`. Neither command wrote a file or changed the image.
- **Registry results:** API tag `git-a635692-amd64-api-r1` → `sha256:17706e1802afc136ac8f9a621d4199a719749da73329ee923e42268eff42e0d1`; Admin tag `git-a635692-amd64-admin-r1` → `sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d676c733`; XHS HTTP tag `git-a635692-amd64-xhs-http-r1` → `sha256:452c2faf7853ce58d93e43c5bf6217a99a6cce14c81345d8cef2f5accabd79af`. Authenticated tag pulls returned the same three digests; local image IDs remain distinct and must never be substituted for these registry manifest digests.
- **Direct-digest consumption follow-up:** an immediate post-push `repository@sha256` pull returned `manifest unknown` for each role before the succeeding authenticated tag pulls returned the exact expected digests. This may have been registry consistency delay, but it was not re-tested after the tag read-back because the approved access window was closed immediately. Treat direct digest-form pull as `UNKNOWN`, never deploy by tag, and require `PROD-IMG-003` to prove each exact `@sha256` reference is directly retrievable before any deployment approval.
- **Remote read-back:** all three returned `linux/amd64` and retained exact OCI revision `a635692a899ee02c6905cd694611c14e0da4594a`, source `https://github.com/iamyusen1314/noteai`, version `git-a635692-amd64-r1`, and created `2026-07-23T05:23:45Z`. No service/container was started.
- **VEX reissue:** CycloneDX 1.6 VEX document version `2` preserves all twelve prior `not_affected` dispositions and 69 SBOM BOM-Link assertions while binding each role to its ACR tag, local image ID and immutable registry digest. VEX SHA256 `57c9f8c0656382d773b0d3b0b5797d6674a931fb967f97c98c37b0febf6197cb`; evidence SHA256 `22eb9bc88680cc0c98ffcadc396d3ea18b1ab324a9d97d415ca8a86e8ea8600f`; registry reissue review SHA256 `2c821fc04c2740a882f7d4437aee2bded36f5a240e23e717fd70a76708f6d565`. The reissue inherits and records the independent disposition review at commit `5b3249995522a22dc600ee7501f9328121f4497c`; it does not claim a new independent disposition review.
- **Access cleanup:** Docker logout returned `0`; exact temporary builder CIDR `47.107.35.208/32` was deleted; the ACR public endpoint was disabled and its public whitelist became empty; ECS Session Manager was disabled and displayed `会话管理已关闭`. Security-group ingress was never modified. The one-time password was not written to a repository file, command line or output.
- **Validation:** authenticated tag pull, local OCI inspect, offline VEX verifier, seven VEX tamper tests, production readiness `86/86`, full unit suite `637` with `5` skipped, Python compilation, `git diff --check`, and official CycloneDX 1.6 schema validation all passed; schema errors were `0`. Canonical SBOMs and unsuppressed raw Trivy reports remain unchanged.
- **Rollback:** do not deploy the three digests. Registry deletion is destructive and requires separate approval; no deletion is authorized or needed. Temporary network/session access has already been fully rolled back.
- **Acceptance:** one `linux/amd64` manifest digest is recorded for each exact role/revision, authenticated tag pull and provenance read-backs match, VEX version 2 is digest-bound, and all temporary access is closed. Direct `@sha256` consumption remains an explicit `PROD-IMG-003` gate.
- **Real call:** yes, ACR push/read.
- **Possible cost:** ongoing private ACR storage plus the already-consumed bounded upload traffic; no new ECS purchase or deployment cost.
- **Next approval:** only read-only `PROD-IMG-003` may be proposed next. It must first re-read and directly pull each exact `@sha256` reference, then inspect the digests; it may not deploy or start services.

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
| LEGACY-XHS-001 — XHS acquisition/account-policy recovery | `VERIFIED` through `PROD-BROWSERLESS-CONSTRAINT-PROOF-001`; real-session validation remains separately gated | High | Browser-free bounded direct adapter, RAP fix, Pillow fix, exact Pillow-fixed local browserless image execution and least-privilege constraint proof passed offline verification; commercial authorization is stated resolved, but Xiaohongshu platform authorization is not asserted and no real session call has been made. | Formal residual disposition review, then a separately approved bounded real-session task. | After release-risk closure, validate approved read operations with strict count/time/stop gates and default suspension. | Interface/signature churn, account restriction, platform enforcement, incomplete/bad evidence. | Re-enable suspension and retain manual/screenshot evidence input; never silently restore Playwright. | Current images pass content/SBOM/Secret/vulnerability gates with an independently reviewed formal disposition; any later real smoke yields bounded evidence without write/challenge bypass. | None now; later smoke is a real platform call. | Engineering/build-host cost first; later egress/account impact must be bounded. | Required before real platform call and deployment. |
| LEGACY-CAP-001 — 100 concurrent AI users capacity | `DEFERRED` | High before scale | Gateway scale rehearsal exists; end-to-end application/provider limits are not proven. | Production functional acceptance, provider quota and budget. | Design/load-test plan using synthetic traffic, queue/backpressure and no uncontrolled provider calls. | Cost spike, outage, rate limits. | Stop load generator and scale back within approved bounds. | Measured SLO/capacity and provider limits support the target with alerts. | Possibly provider/load calls. | Potentially high. | Required. |
| LEGACY-SEC-004 — Historical reasoning retention cleanup | `DEFERRED` | High before broad release | Explainable-agent experience is retained; historical raw-reasoning persistence risk remains a separate task. | Data inventory, retention policy and legal/security decision. | Read-only inventory, then separately approved non-destructive migration/cleanup plan. | Privacy/data loss. | Backup and reversible migration only. | No raw private reasoning is unnecessarily persisted; user-facing explanations remain. | No external call expected. | Storage/engineering. | Required before data mutation. |
| LEGACY-BILL-002 — SSE interruption recovery | `DEFERRED` | High | Recovery design/testing is incomplete. | Stable production API and idempotency design. | Reproduce disconnects, define terminal state/resume semantics, implement separately. | duplicate work/cost. | Feature flag or revert single package. | Disconnect/reconnect recovers without duplicate AI charge or lost terminal result. | Test AI may be needed. | Capped AI cost. | Required before paid test. |
| LEGACY-QA-003 — Remaining manual UI acceptance | `DEFERRED` | Medium | Partial UI acceptance exists; remaining checklist is not fully closed. | Stable production/staging candidate. | Complete synthetic manual checklist and record screenshots/results without secrets. | missed UX regression. | Revert isolated UI package if needed. | All listed UI flows pass on supported viewport/browser. | No paid call by default. | None/minimal. | Only if a paid flow is included. |

## 6. Test and evidence baseline

- Historical prebuild revision `b6abaa781c11950c4d261e8d9f17c3194aecd0cf` passed `586 OK (skipped=5)` full tests and `278 OK` targeted tests.
- Historical combined-image revision `8f7d9c23dd4c4bc951f23d2412156f121da868e7` passed `587 OK (skipped=5)` full tests, `25 OK` targeted deployment/readiness tests, production readiness `66/66`, quality gate, `py_compile`, Compose parse and tracked-file sensitive-value checks; it is superseded and must not be pushed or deployed.
- Historical split-runtime revision `89e3505225c9d596d6ddb26040f08b777e77823c` passed the independent repository gates: socket-blocked full suite `594 OK (skipped=5)`, `network_attempts=0`, targeted tests `38 OK`, readiness `73/73`, semantic entrypoint matrix `14` allowed / `32` rejected, and three mutation classes rejected; shell, Python compilation, YAML, Compose, diff and secret/build-context checks passed.
- Historical hardened application revision `93b03d5c40fb64fa264c0ada1c055f8e7696b161` passed independent repository gates: full suite `601 OK (skipped=5)`, targeted `87/87`, production readiness `78/78`, seccomp SHA/semantics, launch fail-closed tests, Python compilation, Compose quiet parse, diff and changed-file Secret scan.
- `PROD-XHS-HTTP-ADAPTER-001` application commit `33d04d4560f9b7dda43a53527f8ae1026dc335d3` passed independent socket-blocked full suite `625 OK (skipped=5)` with `network_attempts=0`, targeted `130/130` with `network_attempts=0`, readiness `83/83`, Python/Shell/Compose/diff checks, exact source/assets, tracking state transitions and high-confidence sensitive scan. RAP-fixed successor `ca02335513a752ece2dabe71d08105ae86db6c5a` is the superseded pre-Pillow-fix image revision; `344897c` remains CI/Handoff-only.
- The approved hardened-image execution revalidated exact source/LFS/model/seccomp/build-context gates and built both exact native AMD64 local candidates. API image ID is `sha256:e637ff8af8f63c83e1370066111765f6594297806ec9b3e153d03b1dcb1762bc`; corrected Worker image ID is `sha256:17a80aa53c41909abf4dace7c0bec4cfc90e6fd4387bb1c80e8bc5ca7616836e`. These are local IDs, not ACR digests. API scan is `174` SBOM / Secret `0` / `19 High / 3 Critical`; Worker is `288` SBOM / Secret `0` / `32 High / 5 Critical`, with no suppression or VEX. The bounded Worker smoke passed under non-root + pinned seccomp + `no-new-privileges` after temporarily setting the isolated builder's user-namespace quota to `128`; the quota was restored to `0` and no container remained.
- The RAP-fixed browserless rebuild at exact application revision `ca02335513a752ece2dabe71d08105ae86db6c5a` produced three local `linux/amd64` candidates with exact OCI labels and no `RepoDigests`. API/Admin/XHS SBOM counts are `174/174/175`; Secret findings are `0/0/0`; each unsuppressed report has `33` raw and unique rows, `4 Critical / 29 High`, including ten Pillow High rows with fixed version `12.3.0`. Basic/RAP synthetic wrapper smokes passed in `network=none` as non-root with read-only filesystem, `cap-drop ALL` and `no-new-privileges`. Evidence manifest path and SHA256 are recorded in the task ledger above.
- Pillow-fixed application revision `a635692a899ee02c6905cd694611c14e0da4594a` passed isolated Python `3.11.14` Pillow `12.3.0` PNG/JPEG/WebP compatibility, targeted `16/16`, full unit suite `627` with `5` skipped, readiness `83/83`, `pip check`, model-artifact check, quality gate, Python/Compose/diff/sensitive checks and independent review. GitHub CI runs `29982041413` and `29982043526` also passed for the exact SHA using the repository's Python `3.11` workflow; its subsequent native AMD64 rebuild/rescan evidence is recorded immediately below.
- The exact Pillow-fixed native AMD64 rebuild at `a635692a899ee02c6905cd694611c14e0da4594a` produced current local API/Admin/XHS HTTP candidates. Provenance/content/model acceptance and basic/RAP `network=none` signer smoke passed. API/Admin/XHS SBOM counts are `174/174/175`; Secret findings are `0/0/0`; every unsuppressed report has `23` raw/unique rows, `4 Critical / 19 High`, fixed-version rows `0` and Pillow rows `0`. The local IDs and evidence path are recorded in the task ledger.
- Browserless constraint release `253fde55fa609676a9fca5c14fdf6aeceef74000` passed full unit suite `630` with `5` skipped, targeted runtime/readiness/security tests `25/25`, readiness `85/85`, development and production Compose config-only checks, Python compilation and diff checks. Independent review specifically confirmed rejection of line-comment UID spoofing and quoted/unquoted host network/PID/IPC forms.
- The retained-image constrained `network=none` proof found `libblkid=False` and `libacl=False` in the accepted ELF closure for every exact role while read-back confirmed UID/GID `999`, read-only root, `cap_drop: ALL`, `no-new-privileges`, zero devices and bounded writes. API accepted `200/200`; Admin intentionally failed ready at `503` without a production password; XHS remained suspended. Evidence path and command identity are recorded in the task ledger.
- Model integrity passed human manifest `8/8`, machine manifest `4/4`, and Git LFS artifact `3/3` checks.
- `py_compile`, Docker Compose/static configuration, diff, secret, and build-context checks passed.
- The superseded combined local native AMD64 candidate remains blocked at SBOM `298`, Secret `0`, `32 High / 7 Critical`. Historical split candidates at `89e3505` and retained hardened candidates at `93b03d5` show the same role-specific counts: API SBOM `174`, Secret `0`, `3 Critical / 19 High`; Worker SBOM `288`, Secret `0`, `5 Critical / 32 High`. Those historical images remain local-only and superseded.
- No image was pushed, no ACR registry digest exists, and no production NoteAI service, database/cache, cloud resource, or external provider was invoked by this checkpoint. The only containers started were bounded `network=none` local smokes on the isolated build host, and all were removed.
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
- Do not use `git-ff030f5`, `git-ff030f5-amd64-r2`, `git-ecc4702e`, `git-b6abaa7-amd64-r1`, `git-8f7d9c2-amd64-r1`, either `git-89e3505` local candidate, either retained `git-93b03d5` local image, any `git-33d04d4` image, any `git-ca02335` local image, `latest`, or any unverified tag for production release. `a635692a899ee02c6905cd694611c14e0da4594a` is the immutable source identity of the current local evidence images; deployment-control commit `253fde55fa609676a9fca5c14fdf6aeceef74000` and later Handoff/VEX descendants are not image revisions. Local image IDs are not ACR digests; ACR remains explicitly unapproved and a pushed artifact requires registry-digest VEX reissue. The Worker browser findings are not waived—they are avoided only by the browserless production role graph. Do not repeat symbol searches, parser/API fixtures or exploitability probes for those rows.
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

1. Verify current branch/upstream and worktree explicitly: `a635692a899ee02c6905cd694611c14e0da4594a` is the immutable application/OCI revision of the current local and ACR candidates; `253fde55fa609676a9fca5c14fdf6aeceef74000` is deployment-control provenance and any later Handoff/VEX descendant is evidence provenance only.
2. Verify that the release commit uses `[skip render]` and did not trigger Render deployment; do not confuse a later Handoff-only commit with the application revision.
3. Dispatch the four mandatory read-only auditors above; use the Security Reviewer if any credential, auth, billing, public exposure or image-layer concern appears.
4. Treat historical combined/API/Worker and `ca023355` reports only as superseded baselines. Current browserless reports are under `/opt/noteai-build/evidence-a635692-pillow-rebuild-r2/scans/`: API/Admin/XHS are each `4 Critical / 19 High`, with SBOM counts `174/174/175`, Secret `0`, fixed-version rows `0` and Pillow rows `0`. Do not silently suppress, merge, waive or replace these raw results.
5. Do not repeat **PROD-IMG-002** or reopen ACR public access. Keep **PROD-IMG-003** blocked until the product owner approves read-only inspection of the exact three registry digests. Do not repeat the completed Pillow fix, three-role rebuild, residual Debian audit, residual decision, constraint proof, VEX review or digest reissue. The VEX is a separate impact statement and raw Trivy evidence remains canonical and unsuppressed.
6. Permit an execution agent only after root cause/state is confirmed, modification scope is minimal, task is `READY_TO_EXECUTE`, acceptance/rollback are documented, and the user has approved cost/production impact.
7. Stop immediately on secret exposure, architecture mismatch, untracked cloud mutation, unverifiable digest, unexpected production traffic, failed zero-AI readiness, or any need to broaden scope.

The next session must not repeat the completed production Gateway creation, domain/DNS purchase, certificate purchase/issuance, clean RDS schema migration, prior ARM64 push, historical builds/scans, browser hardening/runtime probes, fixed-runtime design, `PROD-XHS-HTTP-ADAPTER-001`, `PROD-XHS-RAP-FIX-001`, `PROD-IMG-XHS-BROWSERLESS-REBUILD-001`, `PROD-PILLOW-12.3.0-FIX-001`, `PROD-IMG-XHS-PILLOW-REBUILD-001`, `PROD-BROWSERLESS-OS-VULN-DISPOSITION-001`, `PROD-BROWSERLESS-RESIDUAL-DECISION-001`, `PROD-BROWSERLESS-CONSTRAINT-PROOF-001`, `PROD-BROWSERLESS-VEX-REVIEW-001`, `PROD-IMG-002`, or the completed `33d04d4` browserless build/scans. The only recommended next approval is read-only `PROD-IMG-003` scoped to the exact three ACR manifest digests; it must stop before deployment or service start.

## 10. Checkpoint condition

Application release `a635692a899ee02c6905cd694611c14e0da4594a` is the exact OCI revision of the three current local and ACR images and remains their only application provenance. Deployment-control release `253fde55fa609676a9fca5c14fdf6aeceef74000`, the VEX/review release and any later Handoff descendant are not OCI revisions. Current local image IDs are not ACR manifest digests. Canonical raw reports remain unchanged and unsuppressed at `4 Critical / 19 High` per role, while CycloneDX VEX version 2 preserves the independently reviewed twelve exact-product `not_affected` decisions and binds them to the three immutable ACR digests without granting an exception or deployment authorization. The next task requiring explicit approval is read-only `PROD-IMG-003`.
