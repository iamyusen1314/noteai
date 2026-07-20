# NoteAI Production Rollout Handoff

> Updated: 2026-07-20 (Asia/Shanghai)
>
> Scope: formal production-rollout checkpoint only. This checkpoint did not build or deploy an image, start an application, change Alibaba Cloud or Render resources, switch DNS, run migrations, call paid AI, crawl external sites, or execute an end-user payment.
>
> Evidence precedence: current Git/CI and public health checks > current cloud control-plane reads > previously captured control-plane evidence > conversation recollection. Anything not re-observed after the interruption is explicitly marked `INVESTIGATING` or uncertain.

## 1. Current project phase

NoteAI is in **production infrastructure preparation and controlled release**, not general availability. Render Staging remains the validated staging environment. The production Claude Gateway is live on Render Singapore, while the Alibaba Cloud production application path has not been released: the corrected immutable AMD64 application image is not yet verified, API-C/API-F application services are not accepted, no ALB is configured, TLS certificates are not attached to a production listener, and production DNS has not been switched.

The immediate release stop condition is to establish a verified, immutable `linux/amd64` image for revision `ff030f5`, then complete API-C zero-AI readiness before any real provider call or additional production component is started.

## 2. Git and repository truth

| Field | Verified value |
|---|---|
| Branch | `codex/quality-stabilization-real-chain` |
| HEAD before this handoff checkpoint | `ff030f51c6396214ff024a62432cbbdbf3225e96` |
| Short revision | `ff030f5` |
| Upstream | `origin/codex/quality-stabilization-real-chain` |
| Ahead / behind before checkpoint | `0 / 0` |
| Staged before checkpoint | none |
| Unstaged before checkpoint | only `.codex/handoffs/current-task.md` |
| Untracked before checkpoint | none |
| Render auto-deploy impact | checkpoint commit must contain `[skip render]`; no deployment is authorized |

Recent relevant commits, newest first:

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

Current CI evidence for exact revision `ff030f5`: both push and pull-request GitHub Actions runs completed successfully. No test suite was rerun during this documentation-only checkpoint.

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

- Exact source revision: `ff030f51c6396214ff024a62432cbbdbf3225e96` (`ff030f5`).
- Required target tag: `git-ff030f5-amd64-r2`.
- The target must be deployed by immutable digest after independent verification. If a later session changes the tag, it must record the reason, source revision, platform, digest and superseded tag in this handoff before deployment.

### 4.2 Last verified ACR image inventory

| Tag | Digest | Platform | Release decision |
|---|---|---|---|
| `git-ecc4702e` | `sha256:b7a7d47dba6a314fae2fde6d1d35cafe9f209da41f385c266f463a31f66f6916` | `linux/amd64` | **Forbidden for production release:** older source revision and missing the `ff030f5` Meituan CLI packaging change. |
| `git-ff030f5` | `sha256:751b7ecc9e6f883b923f52754c5290d07e06610014ae43ee5d7fa303c168afe1` | `linux/arm64` | **Forbidden on x86 ECS:** architecture mismatch. |
| `git-ff030f5-amd64-r2` | Not verified | Required `linux/amd64` | Last confirmed absent at the interruption. Current existence/digest is `INVESTIGATING`; do not deploy until independently verified. |

No mutable tag such as `latest` is an acceptable production reference. Neither existing image above may be used for production deployment.

### 4.3 Interruption point

The 2026-07-19 interruption occurred **before a successful native AMD64 build and ACR push of the corrected `ff030f5` image**. The ARM64 image had been pushed under `git-ff030f5`. A corrected AMD64 target tag had not appeared in the last verified ACR inventory. API-C had pulled the older `git-ecc4702e` AMD64 image, and runtime secret entry had been performed, but the NoteAI API application had not completed start/readiness acceptance.

### 4.4 Completed, not started and uncertain

Completed with evidence:

- Source revision `ff030f5` exists, is pushed and has successful GitHub CI.
- Production Claude Gateway exists on Render Singapore and public live/readiness is healthy.
- Clean production RDS schema migrations `0001` through `0008` were applied without Staging data import.
- Three TLS certificates were issued.
- VPC/subnets, RDS, Tair, ECS hosts, ACR repository/private connectivity and SNAT were provisioned in prior authorized steps.

Not started or not completed:

- Verified `git-ff030f5-amd64-r2` build and push.
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

### PROD-IMG-001 — Build corrected AMD64 image

- **Status:** `INVESTIGATING`
- **Priority:** Critical
- **Current evidence:** source revision is `ff030f5`; existing same-revision image is ARM64; target `git-ff030f5-amd64-r2` was last confirmed absent. Current ACR inventory must be re-read first.
- **Prerequisites:** read-only Git/ACR/host architecture audit; clean source tree; documented build host/platform; user approval for build and any temporary registry access.
- **Execution steps:** confirm target absence; build `linux/amd64` from exact revision with Git LFS/model inputs resolved; record build metadata without secrets; do not deploy.
- **Risk:** architecture mismatch, stale source, missing model artifacts or CLI, secret leakage into image layers.
- **Rollback:** stop/remove only the local failed build artifacts; do not delete remote tags or cloud resources.
- **Acceptance:** independent inspection proves exact revision `ff030f5`, platform `linux/amd64`, expected entrypoint and no embedded secrets; image is ready for push under the immutable target tag.
- **Real call:** registry/build dependency downloads may be real; no AI call.
- **Possible cost:** registry storage/egress and temporary build resources.
- **User approval:** required before build or registry-access mutation.

### PROD-IMG-002 — Push to ACR and verify digest

- **Status:** `BLOCKED`
- **Priority:** Critical
- **Current evidence:** no verified digest exists for `git-ff030f5-amd64-r2`.
- **Prerequisites:** PROD-IMG-001 acceptance; approved ACR access window; public access remains closed except an explicitly approved, time-bounded exception.
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

- Exact revision `ff030f5` has successful GitHub Actions push and pull-request CI runs.
- The repository's standard local baseline remains:
  - Python unit tests under `tests/`.
  - API contract and frontend static-report tests.
  - Playwright end-to-end tests.
  - production readiness gate.
  - Docker Compose configuration validation.
- No tests were rerun during this documentation-only checkpoint.
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
- Do not use `git-ff030f5`, `git-ecc4702e`, `latest`, or any unverified tag for production.
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

1. Verify the current branch, exact HEAD, upstream divergence, staged/unstaged/untracked files and recent commits.
2. Verify that the checkpoint commit contains only this handoff and did not trigger Render deployment.
3. Dispatch the four mandatory read-only auditors above; use the Security Reviewer if any credential, auth, billing, public exposure or image-layer concern appears.
4. Reconcile current ACR tag/digest/platform truth, API-C/API-F host and service state, RDS/Tair/network/PrivateZone, Alibaba billing inventory, Render Gateway state, ALB/TLS/DNS and traffic evidence.
5. Start with **PROD-IMG-001**. Do not build until the current ACR inventory and build-host architecture are proven and user approval is obtained.
6. Permit an execution agent only after root cause/state is confirmed, modification scope is minimal, task is `READY_TO_EXECUTE`, acceptance/rollback are documented, and the user has approved cost/production impact.
7. Stop immediately on secret exposure, architecture mismatch, untracked cloud mutation, unverifiable digest, unexpected production traffic, failed zero-AI readiness, or any need to broaden scope.

The next session must not repeat the completed production Gateway creation, domain/DNS purchase, certificate purchase/issuance, clean RDS schema migration or prior ARM64 push. It must verify their current state read-only and continue from PROD-IMG-001.

## 10. Checkpoint condition

Before this checkpoint commit, the worktree contained only this handoff as an unstaged modification, with no staged or untracked files. The checkpoint is eligible for a dedicated documentation commit only after a secret/path scan. The commit must use `[skip render]`, push normally to the existing tracking branch, never force-push, and must not trigger any build, deployment or cloud change.
