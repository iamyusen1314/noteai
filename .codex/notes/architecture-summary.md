# Architecture Summary

Last updated: 2026-08-19

## Confirmed Production Target (partially implemented)

- Alibaba Cloud South China runs the complete production system: user frontend/API, Admin, PostgreSQL, billing/payment, V0.4 artifacts, Kimi/Moonshot, fact enrichment, market timing/tracking workers, object storage/video cache, logs and monitoring.
- Recommended public naming is `noteaipro.cn` for the production root, `api` and `admin` hosts, with `noteaipro.com` held only as a defensive registration. The primary `.cn` has Alibaba Enterprise Ultimate DNS plus Basic Defense. Three independent Rapid DV certificates for the root, API and Admin names were signed on 2026-07-18 but are not yet bound to an ALB. Business A/CNAME records remain intentionally absent until a verified production ALB target exists.
- 2026-07-18 actual state: the production VPC, two private API ECS nodes across C/F, one cross-zone high-availability PostgreSQL RDS logical instance, one high-availability 2 GiB Tair instance, and VPC-level SNAT/public egress are paid and running. The empty production RDS has migrations `0001` through `0008`, 30 public tables, no missing versions, no Staging data and no Prompt baseline seed. ACR image/digest, production application deployment, ALB, certificate binding and business DNS cutover are not complete.
- Commercial V1 capacity target is 1,000 active online sessions plus reliable admission of 100 simultaneous AI jobs across Claude and Kimi; the future expansion target is 1,000 simultaneous AI jobs. "Simultaneous" means every job is durably accepted, queued, recoverable and auditable, not that every request bypasses backpressure and enters a provider at the same instant.
- Render Singapore ultimately runs only a minimal Claude Gateway. It must not connect to the business database or hold user/admin sessions, payment state, Moonshot credentials, model artifacts, S3/OSS credentials, Cron jobs or persistent user content.
- The browser never calls the Gateway. Alibaba Cloud remains the only public business API and owns authentication, request-id idempotency, credits, usage, result persistence, Kimi fallback and business SSE.
- Alibaba API admission and AI execution are separate. V1 first uses PostgreSQL `FOR UPDATE SKIP LOCKED` plus lease/fence/heartbeat as the authoritative durable queue and returns a job ID before execution. A `TaskQueue` interface keeps transport replaceable; only after a transactional outbox is proven may Alibaba SMQ/MNS/RocketMQ carry content-free job IDs as at-least-once worker wake-ups. Fenced database claims, provider-start evidence, terminal result, refund and replay state always remain authoritative. Dedicated workers consume jobs under explicit Claude/Kimi capacity budgets. Redis/Tair may accelerate cache or counters but is never the job or billing source of truth.
- Commit `199bf5f` contains `CAP-001A1` and `CAP-001A2A`; production migrations `0007` and `0008` are applied to the empty RDS structure. The application code is not deployed and post-commit independent verification remains pending, so both tasks are `READY_TO_VERIFY`, not `VERIFIED`. They are not connected to public routes or a Worker. The next release gate is a recoverable payload/result contract; no 202 route or Worker may be enabled until it is complete.
- User payloads and public terminal results target private Alibaba OSS objects encrypted with SSE-KMS and accessed through RAM Role/STS. Commercial V1 uses the free Alibaba product default service keys for RDS/OSS server-side encryption; it must not be marketed as customer-managed keys, BYOK or purpose-separated key ownership. These free service keys are not an application Secret store. Alibaba API access uses ECS RAM Role/STS; Claude/Kimi/Adapay, database, Tair, JWT and Gateway credentials use controlled deploy-time injection, root-only local access, explicit redaction and manual rotation until paid Software KMS credential management is justified. Software KMS plus its minimum credential quota is deferred until an enterprise/compliance, automated-rotation, multi-operator, BYOK, application-layer encryption, independent key-domain or contractual requirement is confirmed. PostgreSQL keeps only opaque reference metadata, ownership/purpose bindings, hashes/counts, versions, encryption-mode/key-epoch metadata, state and TTL; messages keep only operation IDs. Raw reasoning, system prompts, provider envelopes, credentials, base64, presigned URLs and original media never enter task metadata, queue messages or ordinary logs. Retention and minimized cross-border text policy still require product/compliance approval.
- Production monitoring covers each provider/model's official quota or response-header equivalents, RPM/ITPM/OTPM, token/cost/balance, 429/5xx/timeout, queue depth/oldest age, active leases and task-stage P50/P95/P99. NoteAI may automatically alert, apply approved backpressure and scale within a pre-approved cloud budget; it must never automatically raise a provider spend cap or purchase a larger paid resource. Capacity upgrade requests include current limit, utilization, growth, exhaustion forecast, requested limit, cost impact and rollback evidence for user approval.
- The Gateway accepts only authenticated internal calls, applies model/payload/token/concurrency limits, calls Anthropic, removes provider raw reasoning, and returns versioned content/error/usage envelopes.
- ARCH-001 has placed the production runtime behind an SDK-independent `ClaudeTransport` with a behavior-compatible local Anthropic implementation. ARCH-002 now runs a verified minimal single-instance Gateway on Render Singapore Starter through a separate Blueprint; its control plane uses AWS Singapore DynamoDB through Render OIDC. `ARCH-002P-C` is verified at `c0afbbe`: exact authority, DNS/TLS pinning, signed remote readiness, configuration epochs and timeout layering passed local, GitHub CI and independent Render Shell checks. The existing full-stack Staging service intentionally remains on Local transport, so no business traffic has been cut over. Production 2–4 instance use remains blocked by `ARCH-002P-D`.
- ARCH-002P is split into four serial gates. Gate A (outcome-safe retry/fallback, partial-stream termination, usage audit and cancellation/ASGI cleanup ownership) and Gate B (Singapore shared atomic nonce/rate/operation/lease control plane) are VERIFIED on the single-instance Staging Gateway. Remaining gates are exact host/remote readiness/timeout trust boundaries and the 2→4 instance Render deployment/chaos rehearsal. The Gateway makes zero new Claude calls when the control plane is unavailable. Keeping the Alibaba business system available through safe Kimi routing for proven-not-dispatched work, durable queues, status/replay and reconciliation remains a separate `BILL-002` Production prerequisite; it is not implied by Gate B. The shared control plane stores only hashes, enums, timestamps and usage summaries and never stores prompts or generated content.
- ARCH-002P-B is live on Staging at commit `d279caa`. Each Router Claude leaf call owns a signed opaque operation ID stable across safe retry/fallback. DynamoDB mode uses a stable service principal for atomic nonce, monotonic single-item rate, non-expiring live operation state and renewable fenced slots; only terminal operations receive cleanup TTL. Anthropic is called only after a durable fenced provider-start transition. Render web identity is mandatory; static AWS keys and metadata fallback are rejected. The Singapore on-demand table is Active with TTL and encryption; the exact Render workspace/default/service subject role is table-only. Two independent live clients proved single-winner nonce/rate/operation behavior with zero Claude calls. `FIN-003` is verified with a monthly US$1 all-service budget, actual 80% and forecast 100% direct-email alerts, no SNS or automatic actions. Staging remains one instance/one worker; real 2–4 instance validation is still required.
- ARCH-001 scope distinguishes production runtime from offline tooling. `model/extract_cover_features.py` (offline Claude vision batch), `tools/ai_prelabel_review_batch.py` (offline review batch), and `tools/live_ai_smoke.py` (explicit manual connectivity smoke) are not Production API request paths, must not run in Alibaba API/Admin/Worker processes, and remain tracked by `ARCH-001A` plus a fixed repository-wide static allowlist.
- Migration sequence: first introduce and verify a single `ClaudeTransport` boundary; then build/test the Gateway; then deploy Alibaba production infrastructure and data services; then canary the gateway transport; finally switch public DNS and retire the old Render business services after a rollback window.
- Do not operate two full business APIs against one production database as a transitional dual-active design.

## Payment execution contract (provider activation not yet implemented)

- Adapay is the selected V1 aggregation provider, subject to written merchant admission for NoteAI's AI SaaS and non-withdrawable/non-transferable service credits, plus confirmation of the required Alipay, WeChat and UnionPay PC/H5 flows.
- `model/payment_contract.py` and migration `0014` now implement the
  provider-isolated repository contract: fixed integer-fen catalogue,
  signed callback verification, collision-safe Event idempotency, immutable
  cash/entitlement ledgers, paid-credit source positions, one full unused
  refund, reconciliation/settlement summaries and exact role boundaries.
  Existing test top-up/upgrade endpoints and legacy `payment_ref` remain
  non-cash test paths.
- Payment success comes only from a verified server callback or authoritative order query with matching merchant/app/environment/currency/amount. Browser redirects never grant credits.
- Cash refunds remain separate from AI-operation credit reversals. T+1 reconciliation compares NoteAI ledgers, Adapay charge/refund/fee files and bank settlement batches.
- Ordering and callback switches default off and no network adapter is
  selected by environment. Merchant credentials, official adapter,
  mock/sandbox compatibility, callback reachability, production migration/
  ACL, bounded scheduler/alerts and any capped real-money proof remain open.

## Frontend

- Main file: `NoteAI_Pro_Demo_Framer.html`.
- Render static build: `scripts/build_render_frontend.sh` writes `dist/index.html` and a generated `dist/runtime-config.js`; `NOTEAI_PUBLIC_API_BASE` supplies the cloud API origin.
- Frontend shape: single static HTML document with embedded CSS and JavaScript.
- Confirmed libraries/assets:
  - ECharts loaded from CDN.
  - Lucide loaded from CDN.
  - Three.js in npm dependencies and local vendor asset.
  - Playwright e2e tests under `tests/e2e`.
- Page/route structure:
  - Frontend uses in-page sections and `showPage(name)` rather than browser routes.
  - Confirmed pages include landing/home, upload/start diagnosis, processing progress, diagnosis report, profile/growth, tech engine, chat, pricing/library-style surfaces.
- Main workflows:
  - AI diagnosis: screenshot upload, video upload, or manual input.
  - AI generation: image/video/brief input.
  - Chat optimization: starts from diagnosis/generation context.
  - Pricing/credits and profile surfaces read backend billing/profile endpoints.
- State management:
  - Global JavaScript variables in the HTML file, such as diagnosis/generation results, uploaded images, OCR state, video IDs, auth user, and chat session.
  - `localStorage` is used for auth/session-like frontend state and chat restore state.
- Form/request behavior:
  - Requests use `fetch` to `API_BASE`, derived from current host or `window.NOTEAI_API_BASE`.
  - Auth uses bearer token headers from frontend auth state.
  - Streaming endpoints parse Server-Sent Events style `data:` lines from response bodies.
- Data display:
  - Report rendering is frontend-driven from backend JSON, including V0.4 feature schema, dimensions, agent evidence, market timing, and generated plans.

## Backend

- Main directory: `model/`.
- Main API app: `model/api.py`.
- Admin API app: `model/admin_server.py`.
- Auth modules:
  - User auth: `model/auth.py`.
  - Admin auth: `model/admin_auth.py`.
- Key support modules:
  - `model/db.py`: local SQLite/cloud PostgreSQL connection dispatch, helpers, and PostgreSQL migration runner.
  - `model/runtime_settings.py`: shared JSON settings stored in the primary database.
  - `model/billing.py`: credits, subscriptions, usage, token/cost accounting.
  - `model/payment_contract.py`: provider-isolated payment/refund cash,
    entitlement and reconciliation state machine.
  - `model/model_router.py`: Claude/Kimi model routing, fallback, retry, timeout, usage recording.
  - `model/fact_enrichment.py`: Amap/Meituan/search/local fact enrichment.
  - `model/hot_keywords.py`: hot keyword DB and market timing features.
  - `model/scheduler_a.py` and `model/market_timing_worker.py`: market timing/crawler worker flow.
  - `model/spider_xhs_http.py`: bounded read-only Spider_XHS direct-HTTP adapter for homefeed, search recommendation, note search, note detail, local session health and capped pagination.
  - `model/v04_composite_features.py`, `model/train_v04_composite.py`, related files: V0.4 training/scoring.
- API structure:
  - Auth: `/auth/register`, `/auth/login`, `/auth/logout`, `/auth/me`, profile/avatar/password endpoints.
  - OCR/vision: `/extract-screenshot`, `/validate-ocr`, `/upload-video`.
  - Notes/diagnoses/tracking: `/notes`, `/diagnoses`, `/notes/track-url`, `/notes/tracking`.
  - Billing/payment: `/billing/plan`, `/billing/usage`, `/billing/credits`,
    test-only top-up/upgrade routes, payment capabilities, owner-bound orders
    and the default-disabled Adapay callback.
  - AI scoring/diagnosis/generation: `/score`, `/quick-diagnose`, `/diagnose`, `/analyze`, `/analyze/stream`, `/generate`, `/generate/stream`.
  - Chat: `/chat/start`, `/chat/message`, `/chat/ui`.
  - Health: `/health`, `/health/live`, `/health/ready`.
- Admin structure:
  - `/admin/login`, `/admin/logout`, `/admin/me`.
  - Overview/users/user detail/user adjust.
  - Tracked notes, revenue, usage stats.
  - Prompt list/get/update/rollback.
  - Model list/deploy/train/status.
  - Crawler status/update/toggle/run/logs.
  - Settings/logs/health (`/health/live`, `/health/ready`, and backward-compatible `/admin/health`).
- Middleware:
  - CORS is configured in API/admin code; exact allowed origins depend on env/config.
- Error handling:
  - FastAPI `HTTPException` is used for auth failures, provider failures, market timing unavailable, billing quota/credit failures, and input validation.
  - Model provider errors are normalized in helper functions for Moonshot/Kimi and routed/retried through `model_router.py`.
- Permission checks:
  - User endpoints use optional or required bearer auth depending on operation.
  - Paid operations should require user identity through billing checks.
  - Admin endpoints depend on `admin_auth.get_admin_user`.

### Production XHS runtime boundary

- Production uses three browser-free dependency targets: `api-runtime`, `admin-runtime`, and `xhs-http-runtime`. None installs the Python Playwright package, a Chromium binary, or the browser graphics stack.
- Only the root-marked `xhs-http` role with `NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http` may enter the direct adapter. Collection is suspended unless explicitly unlocked; API/Admin roles and an `xhs-http` role with a missing or different adapter fail closed before signing or network I/O.
- The direct adapter is fixed to `edith.xiaohongshu.com` and four read-only API paths. It has no login, write, proxy rotation, challenge bypass, arbitrary endpoint, or browser fallback. Cookies are host-filtered, expired values are discarded, and secrets never enter argv, environment, health output, or ordinary errors.
- Historical Playwright crawler source remains only for explicit `local`/`legacy` development roles and npm Playwright remains frontend E2E tooling. Those source files may still be copied with the application tree, but production dependencies, role entrypoints, and reachable commands provide no browser execution capability.

## Database

- Local database files:
  - User/product DB: `model/data/noteai.db`.
  - Hot keyword DB: `model/data/hot_keywords.db`.
  - These runtime DB files are ignored and should not be committed.
- Cloud database:
  - Render services share PostgreSQL through `DATABASE_URL`.
  - Versioned migrations now extend through
    `0014_payment_execution_contract.sql`.
  - `scripts/render_predeploy.py` applies migrations under a PostgreSQL advisory lock and records them in `schema_migrations`.
- Schema location:
  - `model/db.py` contains `CREATE TABLE IF NOT EXISTS` SQL and idempotent `ALTER TABLE` migrations.
  - `model/hot_keywords.py` contains separate hot keyword schema and idempotent migration logic.
- Confirmed tables in `model/db.py`:
  - `users`
  - `user_sessions`
  - `notes`
  - `chat_sessions`
  - `user_memories`
  - `growth_records`
  - `subscriptions`
  - `usage_records`
  - `credits`
  - `credit_transactions`
  - `saved_diagnoses`
  - `tracked_notes`
- Confirmed hot keyword tables:
  - `hot_keywords`
  - `keyword_snapshots`
- Migration status:
  - No Alembic/Prisma migration tool is used.
  - PostgreSQL uses versioned SQL; SQLite keeps idempotent runtime additions for backward compatibility.
  - `scripts/migrate_sqlite_to_postgres.py` is dry-run by default and can copy application rows only after explicit guarded `--apply` approval.
  - Production completed structure-only migrations `0001`–`0008` on
    2026-07-18. Repository candidates now extend through `0016`; `0009`–`0016`
    remain unapplied. V3B and V4 each ran once and are independently proven
    rolled back with database writes zero; neither may be retried. Disposable
    PostgreSQL evidence does not imply production migration or privilege
    readiness.
  - The corrected managed-RDS migration architecture uses a protected
    executor to activate persistent `noteai_admin` with `SET LOCAL ROLE`.
    The persistent owner must own the database and every public
    relation/function, so new migration objects never depend on a transient
    executor.
  - The first fixed-query forced-readonly owner-authority preflight consumed
    the existing root-only Admin database Secret through anonymous stdin after
    a network-none import. Production deterministically rejected that runtime
    identity at `SET LOCAL ROLE noteai_admin` with SQLSTATE `42501`; the
    read-only transaction rolled back with database writes zero and is not
    retriable.
  - The successor capability preflight is separately named and uses one
    short-term managed-RDS privileged account. Its RSA private key exists only
    on API-C. API-C strips the existing Admin URI userinfo and rejects query
    credential/redirect overrides before the audit container boundary; only
    sanitized topology and the decrypted short-term password are consumed
    through protected stdin, and no DSN or plaintext credential is persisted,
    placed in environment/argv or emitted. The contract requires one direct
    `pg_rds_superuser` membership, no other direct/owner/runtime membership
    and no object/default-ACL/shared ACL or ownership dependency. Alibaba's
    managed `pg_rds_superuser` contract permits `SET ROLE` to a standard
    account, but production must prove that capability once in read-only mode
    before V5.
  - PostgreSQL 16 implicitly grants a non-superuser CREATEROLE creator
    `ADMIN OPTION` on every role it creates. The six new runtime roles
    therefore have exactly six management rows to persistent `noteai_admin`,
    with `INHERIT FALSE` and `SET FALSE`; these are owner-management topology,
    not runtime privilege inheritance. Any additional row fails closed.
  - Runtime ACL execution is split into ten fixed sanitized sub-stages inside
    the same transaction. Production must first pass a separately named
    forced-readonly owner-authority preflight before any new V5 write incident.
- Seed / initialization:
  - No standalone seed command is confirmed.
  - Test and local startup may initialize tables.
- Do not run without approval:
  - DB reset/delete/cleanup commands.
  - Any script or endpoint that modifies production-like data.
  - Any unreviewed migration/schema change.

## Auth / Permission

- User authentication:
  - Password hashing: PBKDF2-SHA256 in `model/auth.py`.
  - Token generation: `secrets.token_urlsafe(32)`.
  - Session storage: SQLite `user_sessions`.
  - Token transport: bearer auth via FastAPI `HTTPBearer`.
  - Token expiry: 30 days.
- Admin authentication:
  - Admin username/password come from environment variables.
  - Admin sessions are stored in the primary database and prefixed with `admin_`.
  - Admin token expiry: 7 days.
- High-risk points:
  - `get_optional_user` allows backward-compatible anonymous access; paid operations must separately enforce user identity.
  - Admin adjustment endpoints can change subscription/credits/user state.
  - Top-up/upgrade endpoints must not be treated as real payment without payment provider reconciliation.

## External Services

Only service names and variable names are documented here; no secret values.

- AI text/generation:
  - Anthropic Claude via `ANTHROPIC_API_KEY`.
  - Moonshot/Kimi via `MOONSHOT_API_KEY`.
- Vision/OCR/video:
  - Kimi/Moonshot vision models via Moonshot API.
- Fact enrichment:
  - Amap via `AMAP_WEB_KEY`.
  - Meituan travel / AI Hub via `MEITUAN_AI_HUB_TOKEN`, `MEITUAN_OPEN_TOKEN`, and related Meituan variables.
  - Optional Baidu Map, Tencent Map, SerpAPI, Bing Search, Google CSE variables are present in env templates/code.
  - Local verified facts path variables are supported.
- Market timing / trends:
  - Local hot keyword DB.
  - Optional cloud snapshot, refresh, upload URLs/tokens.
  - Optional authorized trend source URL/token.
- Model artifacts:
  - Git LFS, private Amazon S3 read-only loading, and an optional object-storage base URL are supported.
- Payment:
  - The Adapay repository/offline contract exists, but no real adapter,
    merchant credential, provider transaction or production callback has been
    enabled or verified.

## Data Flow

### AI diagnosis

1. User selects mode and content intent in the frontend.
2. User uploads screenshots/video or enters manual title/body.
3. Frontend OCR/video helpers may call `/extract-screenshot`, `/validate-ocr`, or `/upload-video`.
4. Frontend calls `/analyze/stream` or `/analyze` with title/body/domain/images/video ID, user constraints, content intent, merchant visibility, merchant name, and fact source policy.
5. Backend authenticates/bills as needed, enriches facts if routing allows, computes V0.4 features, runs multi-agent diagnosis, enforces market timing if configured, and returns report/plans via JSON or streaming events.
6. Frontend renders processing progress and report, then can save diagnosis/note or start chat optimization.

### AI generation

1. User uploads image/video or writes brief.
2. Frontend sends `/generate/stream` or `/generate` with domain, materials, user constraints, content intent fields.
3. Backend reads visual descriptions, fact enrichment, V0.4 planning brief, multi-candidate generation, candidate scoring/ranking, title/body sanitizers, and delivery gates.
4. Backend returns title/body/tags/plans/scores/selection metadata.
5. Frontend renders generated output and can start chat optimization.

### Chat optimization

1. User starts chat from diagnosis/generation context.
2. Frontend calls `/chat/start`, then `/chat/message`.
3. Backend loads user memory/preferences and generation context, applies user constraints and content intent contract, records usage where applicable, and returns revised notes or feedback.

### Billing

1. Paid/credit operations call billing guards in backend.
2. `billing.py` deducts monthly credits first, then recharge credits.
3. Usage records capture operation, credits, tokens, model calls, estimated/actual cost fields.
4. Real revenue comes only from immutable payment cash rows; legacy top-ups
   are not revenue truth. Admin separately exposes unmatched cash for manual
   review and never reports non-recurring purchases as MRR.

## Fragile Areas

### Item 26 manual post-action cost-stop authority

- The historical browser cost stop is an observed, terminal/no-replay v1
  operation; it is not retroactive abort authority and adds no readiness
  credit. The unavailable v1 public-root bytes and signing-key custody are
  preserved only as historical one-way commitments and are never a fallback.
- The active design is an independent generation-v2 authority with a tracked
  Secret-free public root, three role-context RSA-3072 signatures, a signed
  runtime receipt-v3 and root-owned raw/runtime custody. Its inert A3 source
  checkpoint is exact revision
  `62f3f49fba3eb473a7a8e08f51b42f3186f7e86d`; only push `31996624538` and
  pull request `31996626682` exist for that SHA, and both completed attempt 1
  with success and zero reruns. This accepts source only: the public root is
  absent, the expected hash is empty, every production entry point fails before
  I/O, and no credential has been generated.
- The serial activation DAG has completed ledger-stop dual CI and inert-source
  dual CI. Scoped authorization for root-key generation is now recorded, but
  execution is preceded by a dedicated no-overwrite bootstrap-source
  checkpoint and its own attempt-one dual CI. The helper can run only from a
  fixed root-owned one-file staging directory after its installed bytes are
  compared with the accepted Git blob; it creates the three final private-key
  files with exclusive descriptors and exports public keys through OpenSSL
  without Python reading private bytes. A post-CI ledger binds that helper
  commit/blob/SHA before any `sudo` use. Complete public-root activation dual
  CI, signed receipt/root-only install, fresh read-only capture, M1/M2 candidate
  artifacts and final authority follow. The inert-source SHA and helper-source
  SHA are not the future root-bearing
  `control_revision`. Its control sources, CI workflow and public root freeze at
  that future control revision through M1, M2 and the successor. Receipt and
  evidence artifacts first appear at M1, the checkpoint first appears at M2,
  and each artifact is byte-frozen from its prescribed appearance stage through
  the successor.
- The first helper-source attempt, `514fbe075fe96096d641595a87423af4418ed90a`,
  is terminal/no-rerun and not accepted: its push route timed out restoring a
  model artifact, while its green PR route exposed that the synthetic Item 26
  authority fixture still created disposable private keys outside root custody.
  Its append-only successor leaves the production bootstrap helper unchanged,
  replaces the private-key test seam with pinned public-only SPKIs and non-key
  signature mocks, and adds bounded, unique-temp HTTP artifact retry. Only that
  successor's own attempt-one dual CI plus a later ledger binding may unlock the
  already-authorized root bootstrap. Neither `514fbe0` nor the correction
  revision is the future root-bearing `control_revision`.
- That correction is now exact revision
  `b2d2e89d76f311350468cc3f1e8c20988796e923`; its only push and pull-request
  runs (`32082386775` and `32082388870`) both completed attempt one with all 22
  steps successful and zero reruns. It accepts the unchanged helper source and
  the public-only test boundary, but remains distinct from the future
  root-bearing control revision. A four-ledger binding checkpoint records the
  exact source closure and must itself complete a new attempt-one dual-CI pair
  before the already-authorized root bootstrap may execute.
- The binding checkpoint is now exact revision
  `4eab99188332b156fde0f8892daa668375fff245`; its only push
  `32085627719` and pull-request `32085631106` runs completed attempt one with
  success, 22/22 steps and zero reruns. After this gate and explicit one-shot
  operator authorization, the accepted helper was exclusively staged below the
  fixed root-owned execution tree and then created exactly three RSA-3072
  private keys below fixed root custody. Python read/output of private bytes,
  retry and cleanup all remained zero; only three public PEMs were exported.
  A preceding sudo ticket-transport failure was pre-root with zero root write or
  residue and is recorded separately from the successful staging/key bootstrap.
- The resulting Secret-free activation candidate freezes contract SHA-256
  `190ed155a410b20c1b081b5bc090bbc4c4a6609789d94c51296ce1460bc5ffd1`
  and canonical public-root SHA-256
  `8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85`.
  The root contains three public keys and no private material, rebuilds
  byte-identically, and grants no action or readiness credit. Bootstrap helper
  and public-root refs are frozen in the authority, PITR and external source
  sets. Receipt ancestry is explicitly
  `653a4f3 < 2cfd03a < 514fbe0 < b2d2e89 < 4eab991 < 7882809 < control`;
  the rejected `514fbe0` and `7882809` terminal rows are both included in
  run/job uniqueness and the strict rejected-to-successor time sequence.
- That root-bearing candidate became exact revision
  `78828093048c8b2f2dccd111412703f068155543`, but its only push
  `32140388587`/job `95721382044` and pull-request `32140393870`/job
  `95721399196` runs both terminated at attempt one with failure and zero
  reruns. Artifact restore/verification passed on both routes; Unit then ran
  2,608 tests with one failure, zero errors and 34 skips. The only failure was
  a stale test expectation for the pre-finalization error text: finalized
  authority correctly failed closed earlier at external-authority validation.
  Quality, PostgreSQL, readiness and Compose were not reached. Revision
  `7882809` is frozen rejected/no-rerun and cannot be a receipt-v3
  `control_revision`.
- Its authorized append-only executable-control successor is presently
  uncheckpointed, has an empty revision and has no own CI. The bounded source
  delta updates that stale assertion, constrains root Git to an exact
  command-scoped canonical-repository `safe.directory` value rather than a
  wildcard, and adds the fixed root-owned receipt signer. The canonical public
  root and contract hashes remain `8bfb8834...ff85` and `190ed155...ffd1`, and
  root custody still holds the three already-generated role keys with only
  three public exports. Receipt build/sign, signer/authority/runtime install,
  capture, journal, cloud, database and builder counts remain zero. Only the
  successor's own new attempt-one dual-green push/PR pair can allow a later
  separately gated signing/install stage; a failed or cancelled route is again
  terminal/no-rerun.
- Local root-owned material is not portable CI evidence. A Secret-free,
  clean-clone-replayable terminal capsule or equivalent trusted distribution
  contract remains mandatory before Item 26 credit or any paid PITR successor.
- The append-only executable-control successor is now exact revision
  `68aa82ffbdd43e78e585d8956d13d3030ef6a640`, direct child of rejected
  `7882809`.  Its only ordinary push and pull-request runs
  (`32147676628` and `32147682239`) both completed attempt one with success and
  zero reruns.  Receipt-v3 was subsequently built and signed exactly once by
  the local-CI authority.  The canonical public envelope is 22,068 bytes with
  SHA-256 `61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a`
  and activation time `2026-08-19T00:15:13Z`; independent public-only
  validation proves its RSA signature, public root, two CI rows and twelve
  source-blob bindings.
- The visible-terminal launcher's displayed failure was a wrapper false
  negative.  Its root literal caught successful `SystemExit(0)` with a broad
  `BaseException`, causing the outer wrapper to report
  `launcher_single_sudo_failed` after the signed receipt was already durable.
  A separate latent post-validation defect confused the validator's normalized
  summary with the original envelope payload.  Neither defect changes the
  signed envelope.  Preservation revision
  `2cfb58b9f227a37cc86843bef7dc1014bc185391` is the direct child of `68aa82f`
  and adds only the exact executed launcher, its contemporaneous test and the
  public receipt.  This revision carries the B Secret-free launcher/test
  correction candidate as part of an expected exact six-path delta from
  `2cfb58b9`.  Candidate source presence is not checkpoint acceptance: the B
  commit and tree remain deliberately empty here until a successor ledger can
  freeze them, and B's own CI count is zero/pending.  It is never authorization
  to rerun or re-sign.
- The tracked
  `.codex/item26-manual-cost-stop-activation-receipt-v3-68aa82ffbdd43e78e585d8956d13d3030ef6a640.json`
  is a runtime activation component, not the M1 provider `RECEIPT_REF`.  The control,
  preservation and future B revisions must still omit the M1 provider receipt,
  evidence and M2 checkpoint.  M1 must be a strict descendant of B, while its
  authority bundle continues to name `68aa82f` as `control_revision`.  The
  public activation envelope improves portability but does not finalize S0:
  installed root/runtime state, provider/ActionTrail raw material, final bundle
  and M1/M2 artifacts remain absent.  Item 26 is therefore still unverified
  with no readiness credit.
- Future approval authority has been delegated by the product owner to the
  CTO.  This changes who may issue a later explicit, bounded authorization; it
  does not itself authorize installer, root/runtime mutation, capture,
  cloud/API, database, paid, replay, cleanup or any other current action.

- `NoteAI_Pro_Demo_Framer.html` is a very large static file with global state; accidental name collisions or missing payload fields are easy.
- `model/api.py` is very large and mixes API models, provider calls, scoring, generation, sanitization, streaming, billing, and report logic.
- Billing and admin adjustment logic is revenue-critical.
- SQLite and PostgreSQL must stay behaviorally compatible; schema or SQL-dialect mistakes can affect startup and cloud workers.
- Market timing freshness gates can block AI flows when data is stale or unavailable.
- Fact enrichment can cause factual pollution if placeholders/generic facts leak into delivery copy.
- Model artifacts must match their SHA256 manifest; required-mode checksum failure intentionally prevents startup.
- Live AI calls depend on external APIs, timeouts, concurrency, and provider billing.
- Crawler/Playwright market timing logic is operationally fragile in cloud environments.
- Render staging is split into Static Site, API, Admin, two Cron Jobs, PostgreSQL, and one API-only video cache disk as declared in `render.yaml`.
- Production ALB health must represent the Alibaba process, PostgreSQL and required local model artifacts. Claude Gateway unavailability may degrade Claude routing, but must not make both Alibaba API nodes unhealthy or remove the whole site.
- Commercial capacity is not yet achieved: Tair is running but not integrated, no public 202 admission path or independent Worker exists, and CAP-001A2B plus durable result/refund reconciliation remain open.
- XHS Cookie now accepts managed environment injection only and the repository log/reasoning redaction boundaries pass, but production injection, rotation and historical-log verification remain open. Owner-bound private media/payload storage, cross-process recovery, expiry/deletion/compensation and content-free restore manifests are repository/disposable-PostgreSQL verified; production OSS/RAM roles, migration `0013`, managed cross-node proof, PostgreSQL connection pooling and a real isolated PITR drill remain open.

## Item 26 future-launcher B CI rejection and append-only C boundary (2026-08-19)

- Exact future-launcher correction B is
  `9f2ac29c58f4e9ec63bb3265b1bfe41c4f11c5e8`, tree
  `70b7df3d0b35181919fadabc8c268a15ce851811`, direct parent
  `2cfb58b9f227a37cc86843bef7dc1014bc185391`, with exactly the expected six
  paths.  Its launcher implements the consumed-attempt guard, moves successful
  root exit outside the broad exception handler and separates the signed
  envelope payload from the authority summary.  Those source semantics are not
  accepted as a checkpoint because B's only attempt-one push and pull-request
  CI routes both terminated failure and may not be rerun.
- Push `32203164457`/job `95920998630` and pull request
  `32203166634`/job `95921006035` each reached Unit with 2,647 tests, zero
  failures, three errors and 34 skips; each then skipped Quality, PostgreSQL,
  readiness and Compose.  The three errors all came from test fixtures that
  embedded the production Mac UID `501` or
  `/Users/openclaw/Desktop/noteai` instead of injecting the canonical Linux
  checkout identity.  This is a test portability boundary, not evidence that
  the frozen receipt, RSA signature, authority projection or B launcher logic
  is invalid.
- Correction C is deliberately limited to the four ledgers and the launcher
  test, with expected parent `9f2ac29` and exact path count five.  The production
  launcher stays byte-identical to B.  Tests may inject the current checkout
  owner/path while production constants remain fixed, and topology assertions
  must validate exact B rather than making a HEAD-relative self-reference.  C
  may state only expected parent/path/source presence: its own commit, tree,
  test blob and CI cannot appear in C and remain empty/pending until a strict
  ledger-only descendant records them.  C receives at most one attempt-one
  push/PR pair; no rerun is permitted.
- This source-only branch does not advance the activation DAG.  `68aa82f`
  remains the receipt control; the tracked activation receipt is still not the
  M1 provider receipt; Item 26 remains unverified; S0 remains open; M1/M2 outputs
  remain absent; readiness remains `25/29` internally and `25/38` publicly.
  Installer, runtime mutation, operational capture, cloud/API, database, paid,
  replay and cleanup remain closed.  A future operational edge requires a new,
  explicit and action-scoped decision from an identifiable CTO; delegation or
  agent inference supplies no authority.

## Item 26 portability successor C terminal acceptance (2026-08-19)

- Secret-free C is exact revision
  `d73d454b76e680137fd0bc90983e5fe6e09b4ec3`, tree
  `2123a74b685cfd5bd57bd3620d3044f9605c3de1`, direct parent
  `9f2ac29c58f4e9ec63bb3265b1bfe41c4f11c5e8`, with exactly five changed
  paths: the four ledgers and the launcher test.  Its test is mode `100644`,
  blob `d530efb0b4029895c49203c2e232a597db7773e0`, 40,690 bytes and SHA-256
  `cc8692a939c0462d7f36cbe8a4c7e4fe58cad4ea48986341fd51ee0bb158421b`.
  The B production launcher, signed activation receipt and control/authority
  sources remain byte-identical; rejected B remains permanently no-rerun.
- C's sole push run `32210460306`/job `95941985568` and sole pull-request run
  `32210464258`/job `95941997491` both completed attempt one with success,
  no previous-attempt URL and zero reruns.  Their job intervals are
  `02:58:31Z–03:31:43Z` and `02:58:35Z–03:32:02Z`; run-terminal times are
  `03:31:44Z` and `03:32:03Z`.  Each has 22/22 successful steps, main Unit
  `2647` with 34 skips and zero failure/error, frozen batches
  `[10, 1, 12, 22, 21]`, Quality `7 + expected 1`, PostgreSQL `6/6`, readiness
  `138/138`, Compose success, one Node-only warning and zero error annotation.
  C therefore supplies the accepted CI-portability successor checkpoint.
- The append-only D ledger source has expected parent `d73d454...`, exact four
  ledger paths, empty self revision/tree and own CI `PENDING_NOT_STARTED`.
  It cannot self-authorize or self-accept and is not an operational-authority
  edge.  Authorization `CTO-AUTH-ITEM26-D73-TERMINAL-CHECKPOINT-001` names the
  Root Main agent as the product-owner-designated CTO managing Subagents;
  Subagents have no independent authorization authority.  Its scope is exactly
  four ledgers, one commit, one normal non-force push and observation of the
  unique attempt-one push/PR CI pair, with failure/cancellation terminal,
  rerun/automatic retry forbidden and no operational authority.  Item 26 stays
  unverified, S0 stays open, readiness remains `25/29`
  internally and `25/38` publicly, the M1 provider receipt/evidence and M2
  checkpoint remain absent, and all installer/capture/cloud/database/paid/
  replay/cleanup gates remain closed pending a separate scoped CTO decision.

## Item 26 ledger-only D terminal acceptance (2026-08-19)

- Secret-free D is exact revision
  `b055bad3528541bdcd9caec8604e2fce0e4e4276`, tree
  `61c1e6d7f41e1742d6209d0a01265a32fd51642f`, direct parent
  `d73d454b76e680137fd0bc90983e5fe6e09b4ec3`, with exactly four changed
  paths: the handoff, architecture summary, risk register and readiness
  manifest.  Launcher, launcher test, signed activation receipt,
  control/authority sources, private-key custody and M1/M2 outputs are
  unchanged.  D freezes accepted C and is itself ledger-only rather than an
  operational-authority edge.
- D's sole push run `32213959160`/job `95951864059` and sole pull-request run
  `32213962996`/job `95951883660` both completed attempt one with success,
  no previous-attempt URL and zero reruns.  Their job intervals are
  `03:57:03Z–04:28:34Z` and `03:57:10Z–04:25:44Z`; run-terminal times are
  `04:28:35Z` and `04:25:45Z`.  Each has 22/22 successful steps, main Unit
  `2647` with 34 skips and zero failure/error, frozen batches
  `[10, 1, 12, 22, 21]`, Quality `7 + expected 1`, PostgreSQL `6/6`, readiness
  `138/138`, Compose success, one Node-only warning and zero error/failure
  annotations.  D therefore supplies the accepted ledger-only terminal
  checkpoint for the portability chain.
- The append-only E ledger source has expected parent `b055bad...`, exact four
  ledger paths, empty self revision/tree and own CI `PENDING_NOT_STARTED` with
  count zero.  It cannot self-authorize or self-accept and is not an
  operational-authority edge.  Authorization
  `CTO-AUTH-ITEM26-B055-TERMINAL-CHECKPOINT-001` names the
  product-owner-designated `ROOT_MAIN_CTO`, who manages Subagents; Subagents
  have no independent authorization authority.  Its scope is exactly four
  ledgers, one commit, one normal non-force push and observation of the unique
  attempt-one push/PR CI pair, with failure/cancellation terminal,
  rerun/automatic retry forbidden and no operational authority.  Item 26 stays
  unverified, S0 stays open, readiness remains `25/29` internally and `25/38`
  publicly, the M1 provider receipt/evidence and M2 checkpoint remain absent,
  and all launcher/sudo/signing/installer/capture/cloud/database/paid/replay/
  cleanup gates remain closed pending a separate scoped CTO decision.

## Item 26 ledger-only E terminal acceptance and installer-stager source boundary (2026-08-19)

- Secret-free E is exact revision
  `a4e2a0d106e013c9b3ce730a278345c7552cdcd9`, tree
  `15ed4d17da9899ba1fd1f8d7af1227e9567a06c6`, direct parent
  `b055bad3528541bdcd9caec8604e2fce0e4e4276`, with exactly four changed
  paths: the handoff, architecture summary, risk register and readiness
  manifest.  Launcher, tests, signed activation receipt, control/authority
  sources, private-key custody, installer and M1/M2 outputs are unchanged.
  E freezes accepted D and is itself ledger-only rather than operational
  authority.
- E's sole push run `32216936458`/job `95960106742` and sole pull-request run
  `32216939467`/job `95960115556` both completed attempt one with success,
  no previous-attempt URL and zero reruns.  Their job intervals are
  `04:45:54Z–05:19:57Z` and `04:45:57Z–05:19:01Z`; run intervals are
  `04:45:51Z–05:19:58Z` and `04:45:54Z–05:19:02Z`.  Each has 22/22 successful
  steps, main Unit `2647` with 34 skips and zero failure/error, frozen batches
  `[10, 1, 12, 22, 21]`, Quality `7 + expected 1`, PostgreSQL `6/6`, readiness
  `138/138`, Compose success, one Node-only warning and zero error/failure
  annotations.  E therefore supplies the accepted terminal checkpoint for D.
- The next source candidate has expected parent `a4e2a0d...` and exactly six
  paths: the four ledgers plus
  `tools/stage_and_install_item26_manual_cost_stop_runtime_v3.py` and
  `tests/test_stage_and_install_item26_manual_cost_stop_runtime_v3.py`.
  It is Secret-free and source-only.  The two source blobs may be frozen in
  this candidate because they do not self-reference; the candidate's own
  revision/tree and CI must remain empty/pending until a strict descendant
  binds them.  Source presence is neither installer execution nor checkpoint
  acceptance.
- The frozen stager is mode `100644`, 49,981 bytes, blob
  `6ed7a666d84e10f90b747a60197254f4d7e52ca8`, SHA-256
  `a0fe8d896da08cdcb97df895116bd6cdc7b7e11e55104164b842cb69ee5199bc`;
  its embedded ASCII `ROOT_PROGRAM` is 19,045 bytes with SHA-256
  `2d774a57a53474d0cd1fb79c1f4fc92608dfd9858370097ddad698b023bcdb46`.
  The frozen test is mode `100644`, 27,596 bytes, blob
  `f1ff59215347401e3615a8df15d8b5d8ac13d8da`, SHA-256
  `7218a81d466f394bec60e7e314aae9d6d9ab9b53595fc59afac43e589d048cb8`.
  Two concurrent summaries were byte-identical; focused normal/`-O` checks
  passed `27/27` each, related existing checks passed `48/48`, compile passed
  and diff-check was clean.  Independent implementation red-team review is
  `GO / P0=0 / P1=0 / P2=0` and rechecked all three hash/byte pairs.  These
  source identities support future CLI argument audit without self-binding the
  candidate commit.
- Authorization `CTO-AUTH-ITEM26-INSTALLER-STAGER-SOURCE-001` names the
  product-owner-designated `ROOT_MAIN_CTO`, who manages Subagents; Subagents
  have no independent authorization authority.  Its scope is exactly six
  paths, one commit, one normal non-force push and observation of the unique
  attempt-one push/PR CI pair, with failure/cancellation terminal and
  rerun/automatic retry forbidden.  It authorizes source construction only:
  launcher, sudo, installer, rollback, root write, capture, cloud/API,
  database, paid, replay and cleanup actions remain closed and at zero.
- The future install contract has two additional explicit action classes.  The
  frozen `68aa82f` verifier uses a root-owned NoteAI temporary directory named
  `.item26-v2-signature-verify-*` for exactly three public-only files and then
  removes them; the installer also has a bounded synchronous rollback path.
  This source candidate authorizes neither, and current public-scratch
  create/cleanup and rollback counts are zero.  A later one-shot install CTO
  authorization must name both classes.  Failure residue is never cleaned by
  the stager and retry remains forbidden.
- Item 26 stays unverified, S0 stays open, readiness remains `25/29`
  internally and `25/38` publicly, the M1 provider receipt/evidence and M2
  checkpoint remain absent, and no readiness credit is added.  The source
  candidate cannot authorize its own execution or any later operational edge.

## Item 26 installer-stager source terminal acceptance and F boundary (2026-08-19)

- Secret-free installer-stager source checkpoint
  `c5acaf37fabe4a1f9d3333f75e157b77ca327daf` is the direct child of E
  `a4e2a0d106e013c9b3ce730a278345c7552cdcd9`, has tree
  `863ae66c7ac3e537f63bfc2af8093bbabef84465`, and changes exactly the four
  ledgers plus the stager and its test.  Launcher, receipt, control/authority
  source, private-key material and M1/M2 outputs are unchanged.
- The frozen source identities remain: stager mode `100644`, 49,981 bytes,
  blob `6ed7a666d84e10f90b747a60197254f4d7e52ca8`, SHA-256
  `a0fe8d896da08cdcb97df895116bd6cdc7b7e11e55104164b842cb69ee5199bc`;
  embedded ASCII `ROOT_PROGRAM` 19,045 bytes, SHA-256
  `2d774a57a53474d0cd1fb79c1f4fc92608dfd9858370097ddad698b023bcdb46`;
  test mode `100644`, 27,596 bytes, blob
  `f1ff59215347401e3615a8df15d8b5d8ac13d8da`, SHA-256
  `7218a81d466f394bec60e7e314aae9d6d9ab9b53595fc59afac43e589d048cb8`.
  The prior duplicate summaries, normal/optimized `27/27`, related `48/48`,
  compile/diff checks and `GO / P0=0 / P1=0 / P2=0` review stay frozen.
- Its sole push run `32221546388`/job `95972808384` and pull-request run
  `32221549932`/job `95972819006` both completed attempt one with success,
  no previous-attempt URL and zero reruns.  Push was created/run-started at
  `05:59:34Z`, with job `05:59:37Z–06:25:27Z` and terminal `06:25:28Z`;
  PR was created/run-started at `05:59:38Z`, with job
  `05:59:41Z–06:33:45Z` and terminal `06:33:45Z`.  Each passed 22/22 steps,
  main Unit `2674` with 34 skips and zero failure/error, frozen batches
  `[10, 1, 12, 22, 21]`, Quality `7 + expected 1`, PostgreSQL `6/6`, readiness
  `138/138` and Compose, with one Node-only warning and zero error/failure
  annotations.  Source acceptance is true, but is not execution authority.
- The append-only F source candidate has expected parent `c5acaf37...`, exact
  four ledger paths, empty self revision/tree and own CI
  `PENDING_NOT_STARTED` with count zero.  It changes none of the three frozen
  source identities and cannot self-authorize or self-accept.  Authorization
  `CTO-AUTH-ITEM26-INSTALLER-STAGER-ACCEPTANCE-001` names the
  product-owner-designated `ROOT_MAIN_CTO`, who manages Subagents; Subagents
  have no independent authorization authority.  Its scope is exactly four
  ledgers, one commit, one normal non-force push and observation of the unique
  attempt-one push/PR CI pair, with failure/cancellation terminal and
  rerun/automatic retry forbidden.
- Deferred F self-binding applies to the ledger's own terminal acceptance, not
  to the install ordering.  The required sequence is F commit, external
  verification of F's unique attempt-one dual-green push/PR pair, a separate
  one-shot Root Main CTO install authorization while local HEAD/upstream/remote
  remain exactly F, then execution, and only afterwards a G post-action
  append-only ledger.  The stager binds those live pointers to F and would
  reject a pre-execution G as `stager_acceptance_revision`; G is neither an
  installation prerequisite nor action authority.
- The authorization remains source-only.  Launcher, sudo, root write,
  installer, rollback, public scratch, capture, cloud/API and database actions
  remain closed and at zero.  The earlier quarantine audit deviation remains
  exact: one incorrectly scoped repository-wide `rg` returned five
  function/condition lines from
  `tools/stage_item26_manual_cost_stop_helper_v2.py`, did not open the complete
  file, execute or modify it, or emit credentials/private material; the other
  six quarantined paths had no match and the agent was stopped and replaced.
- Item 26 stays unverified, S0 stays open, readiness remains `25/29`
  internally and `25/38` publicly, the M1 provider receipt/evidence and M2
  checkpoint remain absent, and no readiness credit is added.  Any execution
  still requires that separate action-scoped CTO authorization in the
  F-before-G order above.

## Item 26 F acceptance, runtime-v3 install result and G boundary (2026-08-19)

- F `35fede04256442f7853d38980de174526cf28220` is the exact-four-ledger
  direct child of source `c5acaf37fabe4a1f9d3333f75e157b77ca327daf`, with
  tree `d46d144c4fbf09d081a4f0ba803f0f08e3aa6623`.  Its sole attempt-one push
  `32225356634`/job `95983858276` and PR
  `32225360301`/job `95983869018` both completed success, no previous attempt
  and zero reruns.  Their job intervals were `06:53:52Z–07:27:07Z` and
  `06:53:55Z–07:27:25Z`; each passed 22/22 steps, Unit `2674` with 34 skips and
  zero failure/error, frozen batches `[10, 1, 12, 22, 21]`, Quality
  `7 + expected 1`, PostgreSQL `6/6`, readiness `138/138` and Compose, with one
  Node-only warning and zero error/failure annotations.
- F terminal acceptance did not itself authorize installation.  Separate
  one-shot authorization `CTO-AUTH-ITEM26-INSTALL-35FEDE0-001` is now consumed
  and non-current after one visible-terminal stager, one sudo, one root-stager
  and one installer execution.  The outer result is
  `ROOT_V2_RUNTIME_V3_STAGED_INSTALLED_AND_VERIFIED`, retry/cleanup zero,
  private-key read/output zero, cloud/database counts zero and no readiness
  credit.  Its source/acceptance and receipt bindings are exact.
- The public result artifact is canonical 675-byte JSON at the F-bound path,
  local mode `0600`, Git blob `225a3d23e494b86f6e8a8c8594dbacfc40bdb639`,
  SHA-256 `5ac98e74d18c22ee424448284f552f70d859cfe6b1a081769116aa5bcd333a5c`
  and expected Git mode `100644`.  Inner status
  `ROOT_V2_RUNTIME_V3_INSTALLED` binds control `68aa82f`, authority epoch v2,
  public-root file/Git SHA-256
  `8bfb8834c1e241a18cde984d42524759f53423bcf809dd8657fa4b2be102ff85`
  and activation-receipt SHA-256
  `61b756abed72b2f6ab8fb3b20a260b03c0932f6e4c271c4f723a4e5942cd7f2a`.
  Direct result counts are authority/runtime/journal `1/4/0`, private-key
  read/write `0/0`, cloud `0` and database connection/write `0/0`.
- Immutable code plus terminal success derives one retained staging directory
  and two public source files, three installed target directories, one public
  verifier scratch lifecycle (`1` directory, `3` files, all synchronously
  deleted), residue zero and rollback zero.  This is point-in-time derivation,
  not a later root-filesystem inventory readback; no aggregate root-write
  syscall count is claimed.
- Post-action G is an exact-five candidate: four ledgers plus the unchanged
  public result, direct parent F.  Authorization
  `CTO-AUTH-ITEM26-INSTALL-POSTACTION-G-001` permits only one commit, one normal
  non-force push and unique attempt-one push/PR observation; failure/cancel
  stops and rerun/automatic retry are forbidden.  G's own revision/tree remain
  empty and own CI pending/count zero.  A successor only freezes G/CI and cannot
  retroactively authorize installation or any new action.
- S0 remains open because a Mac root install is not a Secret-free clean-clone
  capsule and raw/final/M1/M2 artifacts remain absent.  The result is not the
  M1 provider receipt; Item 26 remains unverified with no evidence or credit,
  readiness stays `25/29` internal and `25/38` public, and operational capture
  still needs a new action-scoped CTO authorization.

## Item 26 G acceptance and direct Aliyun legacy-RPC adapter topology (2026-08-19)

- G `9146d7a264418f59d76e4d8c7a46ac2abc80e9e8` is the exact-five direct child
  of F `35fede04256442f7853d38980de174526cf28220`, with tree
  `01babbd78832ccc745c65442e030390a25719b89`.  Its unchanged public result plus
  four-ledger delta has one push run `32258307819`/job `96085173739` and one PR
  run `32258312429`/job `96085188749`; both completed attempt one, 22/22 steps,
  no previous attempt and zero reruns.  Each passed Unit `2674` with 34 skips
  and zero failures/errors, frozen `[10, 1, 12, 22, 21]`, Quality `7+1`,
  PostgreSQL `6/6`, readiness `138/138` and Compose, with one Node-only warning
  and zero error/failure annotations.  G is terminally accepted but remains
  non-operational.
- The next topology edge is source L, a direct-child exact-six candidate:
  `tools/item26_aliyun_official_read_v2.py`, its same-name test under `tests/`,
  and four ledgers.  It is a candidate FD-only, read-only direct implementation
  of Alibaba Cloud's official legacy RPC protocol using stdlib `http.client`;
  it never executes CLI/plugins, while its signing/query vectors are parity
  frozen against CLI `3.4.11`.  Status is `SOURCE_ONLY_NOT_AUTHORIZED`; exact
  public-FD, identity and credential-handling findings are resolved at source
  red-team `P0=0/P1=0`, making these bytes a controlled-source candidate but
  not an accepted/operational transport.  It does not include the root
  bridge/materializer or configure, authenticate, install, root-stage or
  operationally execute a transport.  Authorization
  `CTO-AUTH-ITEM26-M1-BRIDGE-SOURCE-001` permits only one exact-six commit, one
  normal non-force push and unique attempt-one push/PR observation.  L's own
  revision/tree are empty and CI is pending/count zero; it is not accepted,
  runnable or action authority until later exact-four-ledger acceptance A
  freezes its static bytes and dual CI.  A separate bridge/materializer source
  checkpoint and its own acceptance must then follow before any OAuth/capture
  action may be considered.
- L source is mode `100644`, 31,410 bytes, blob
  `f53a01805ea68005ca9e56a08dfa491221c224cf`, SHA-256
  `719886d2846a7602bf3fc0529f5c191305b58465c668d171461860d4c60aadb9`;
  its test is mode `100644`, 38,393 bytes, blob
  `6cc138d5b9170cbbe7468a9b17530fe3d25533de`, SHA-256
  `8a0c5227968217132c041cae9b3e201c37e97816ab6e9f8cab353638528faacf`.
  Focused normal/`-O` each passed 25 of 26 with one expected Darwin
  `SOCK_SEQPACKET` unsupported skip; Linux CI must execute that negative test.
  Compile and actual pinned-CA readback passed; operational/network/API/
  credential/OAuth counts remain zero.
- L never reads full CLI config or OAuth tokens.  Its only future credential
  input is a bridge-projected canonical minimal temporary-STS envelope with
  fixed profile `noteai-item26-m1` and region `cn-shenzhen`; the envelope
  `source` is contractual and does not prove OAuth provenance, which the bridge
  must establish by binding the fixed CLI config inode/hash/profile.  Runtime
  is limited to exact LookupEvents, DescribeDBInstances and QueryInstanceBill
  legacy-RPC action/version/host tuples.
- OAuth is undesigned and unauthorized; default user-owned CLI config is
  disallowed.  Any persistence needs separate authority and root-owned `O_EXCL`
  `0600` custody.  Capture must bind expected account/principal from audited
  local OAuth metadata or equivalent trusted identity without a new provider
  call; envelope source/profile cannot be that proof.
- The current Mac transport trust dependency is root-owned `0644`
  `/etc/ssl/cert.pem`, 333,483 bytes, SHA-256
  `9dae8d76e55cb08991f2b672d58999ea15560d910759c16b544f843bdffbb994`.
  Future capture must preflight that identity/hash; an OS CA update fails closed
  and needs a new source successor.  The adapter's own SSL context excludes the
  implicit `SSL_CERT_FILE`, `SSL_CERT_DIR` and `SSLKEYLOGFILE` paths, but makes
  no claim over every OpenSSL variable.  The future bridge must clean-env exec
  and reject credential/SSL/OpenSSL/proxy environment variables.  Fake source
  tests perform no CA read or network operation.
- The public root entry checks effective root, `RLIMIT_CORE=(0,0)` and Python
  `-I -S -B` isolation/no-site flags before reading the credential FD, then exposes only
  fixed secret-free error codes with suppressed causes.  Clean-env execution,
  root staging and inventory belong to the future bridge; none occurred here.
- A zero-byte response-socket write-half preflight runs before any input or
  credential read and before provider-factory creation.  This fails closed
  before cloud dispatch when the output channel is unusable; current operational
  preflight and dispatch counts are zero.
- Request, credential and response descriptors reject `O_NONBLOCK`/`O_ASYNC`.
  Nonblocking or asynchronous I/O fails before credential read, provider factory
  or dispatch; current operational FD-validation count is zero.
- The adapter source does not itself establish provider connectivity.  Its
  future bridge dependency requires accepted fixed identities,
  already-authenticated official transport and non-TTY FD-only request/response.
  The installed collector remains an offline
  importer.  Official Homebrew Aliyun CLI `3.4.11` is present at fixed Cellar
  path `/opt/homebrew/Cellar/aliyun-cli/3.4.11/bin/aliyun`, mode `0555`, owner
  `openclaw:admin`, 87,064,450 bytes and SHA-256
  `7a418ea428dcbfeaab2af8760938aeda8d2f16bd77b586cbe4c75b07034df8fb`;
  its ActionTrail `0.7.1`, RDS `0.7.6` and BssOpenApi `0.7.5` plugin binaries
  are also installed with frozen sizes/hashes in the readiness ledger.  OAuth
  profile/config is absent and CLI configure/API/capture counts are zero.  The
  CLI/plugins are parity references and possible future OAuth/bootstrap or
  evidence tooling, not the adapter's runtime transport.  Raw identifiers,
  bodies, credentials and browser/authentication state are excluded from argv,
  env, user files, Git and terminal output.
- A future separately authorized capture may bind G/L/A, the separate accepted
  bridge/materializer checkpoint, frozen control, installed runtime/result and
  exact adapter/bridge identities and any CLI/plugin identities actually used
  for OAuth/bootstrap.  OAuth itself requires a prior
  separate authorization and must not call a provider API.  Capture's bounded topology
  is one serial session, five logical streams (`LookupEvents` x2,
  `DescribeDBInstances` x2 and `QueryInstanceBill` x1), at most 64 read calls
  including pagination, at most 15 minutes per begin/finish interval, zero
  cloud writes, mutations, database connections/transactions/writes,
  private-key operations and incremental cost.  Root journal/raw writes are
  `O_EXCL`, root-owned `0600` and FD-only; unknown/failure is terminal with no
  retry, replay, concurrent provider dispatch or cleanup.  One isolated adapter
  child plus one parent draining a local `AF_UNIX` socket is required only as
  IPC containment for the 8 MiB response; it produces no second cloud request
  and provider dispatch concurrency remains zero.  Current child/drain counts
  are zero.  Pagination continuation is not replay.  Public receipt/evidence `O_EXCL` materialization requires a separate
  later authorization and may not overwrite an existing path.
- L currently performs none of those actions.  S0 stays open, Item 26 stays
  unverified with empty evidence, M1/M2 remain absent, readiness remains
  `25/29` internal and `25/38` public, and credit remains false.

## Item 26 adapter L rejection and exact-five portability successor (2026-08-20)

- The controlled-source topology is append-only.  L
  `2eebd51144f62d722584ca44f721eb1627b083d2` freezes parent G
  `9146d7a264418f59d76e4d8c7a46ac2abc80e9e8`, tree
  `7014bb71829e45b22fc60eaaf94d9ec9aa9668ac`, all six changed paths and the
  adapter source identity (mode `100644`, 31,410 bytes, blob
  `f53a01805ea68005ca9e56a08dfa491221c224cf`, SHA-256
  `719886d2846a7602bf3fc0529f5c191305b58465c668d171461860d4c60aadb9`).
  The source file is outside the successor diff and remains non-operational.
- L's attempt-one push `32269736302` / `96122964791` and PR `32269742881` /
  `96122985095` both failed Unit after 2,700 tests (one failure, zero errors,
  34 skips).  Each has 22 steps: 15 success, one failed and six skipped.  The
  common readiness-scanner cause is the test-only literal
  `ACCESS_KEY_SECRET` at line 37; the later Quality, PostgreSQL,
  production-readiness and Compose gates were not reached.  Both attempts are
  terminal, have no previous attempt and have rerun count zero.
- Under `CTO-AUTH-ITEM26-ALIYUN-FD-ADAPTER-CI-FIX-001`, the only current
  candidate is L's exact-five direct child: four ledgers plus the test.  Its
  revision, tree, new test static identity and own dual-CI identities are
  deliberately pending until self-binding.  The authority is capped at one
  commit, one normal non-force push and one unique attempt-one push/PR
  observation; failure/cancellation stops, with no retry, rerun or second push.
  The adapter source change count is zero.
- The architectural sequence remains adapter source successor → adapter
  acceptance → separate bridge/materializer source → bridge/materializer
  acceptance → separately authorized OAuth and capture.  This checkpoint
  supplies none of those later authorities and performs no adapter, OAuth,
  API, root, private-key, database, capture, materialization, cleanup or replay
  action.  S0/Item 26/M1/M2/readiness/credit stay unchanged.

## Item 26 adapter CI-fix successor accepted; ledger-only A topology (2026-08-20)

- Controlled adapter source now resolves to exact-five successor
  `65b82ffd890479315c9a93769cf11e2a9d27074b`, the unique child of rejected L
  `2eebd51144f62d722584ca44f721eb1627b083d2`, tree
  `f46f9775dee8c6cdf8508b83b8e861c7bcba57bf`.  Its test freezes as
  mode/blob/bytes/SHA `100644`/
  `9211031d90b78c9a18ddb1acaa9b0a649aec10da`/38,441/
  `1e52569151d431420ff7503eda2a9ee6197eaddadbcc72335dee4da8f25c1950`.
  Adapter source blob `f53a01805ea68005ca9e56a08dfa491221c224cf` and SHA-256
  `719886d2846a7602bf3fc0529f5c191305b58465c668d171461860d4c60aadb9`
  are unchanged.
- Unique attempt-one push `32275176834` / `96140787951` and PR
  `32275182331` / `96140806251` are terminal green with no previous attempt and
  zero reruns.  Each is 22/22 steps; Unit is 2,700 tests, zero failure/error and
  34 ambient skips, with all 26 adapter tests and the Linux seqpacket negative
  case executed.  Frozen counts `[10,1,12,22,21]`, Quality 7 pass + 1 expected
  failure, PostgreSQL 6/6, readiness 138/138 and Compose are green.  Each job's
  sole annotation is a Node 20 deprecation warning; the four terminal pointers
  and exact two-run inventory agree.
- Under `CTO-AUTH-ITEM26-ALIYUN-FD-ADAPTER-CI-FIX-ACCEPTANCE-001`, the next
  node is an exact-four ledger-only direct child A.  Its self revision, tree and
  own CI remain pending/zero.  Authority is one commit, one normal non-force
  push and one unique attempt-one push/PR observation; failure/cancel stops,
  without retry, rerun or second push.
- This is controlled-source acceptance, not runtime authority.  The remaining
  sequence is A acceptance → separate bridge/materializer source → separate
  bridge/materializer acceptance → separately authorized OAuth/capture.  No
  operational count or readiness state changes here.

## Item 26 M1 capture/materializer source architecture candidate (2026-08-20)

- Accepted ledger A `a30b879d06c388a4a0e230b5a23b2eaedc93649d`, parent
  `65b82ffd890479315c9a93769cf11e2a9d27074b`, tree
  `cfc060262cea88c2658295da8b871d815a2d426a`, is the sole parent of the
  authorized exact-six source candidate.  A's attempt-one push
  `32279571023`/`96154867794` and PR `32279575953`/`96154882780` are terminal
  green with 22/22 steps, Unit 2,700/zero failure-error/34 skips, frozen
  `[10,1,12,22,21]`, Quality 7+1, PostgreSQL 6, readiness 138 and Compose.
- Candidate source/test static identities are respectively
  `100644`/448,346B/blob `56c837b03fbae41017e8d2e8c86b453b44c5d316`/
  SHA-256 `28910869ab5043a50b029cabbfe4d1502b79f20e0d2dd145ed5c31bca81c9c2e`
  and `100644`/273,690B/blob `2de6a41d08c1d787d82bbc7024845622f4704b2b`/
  SHA-256 `29e84bbdffebc4795cbfc350f623df5242e3f2257cc14851825c89cbeabf49af`.
  Embedded payloads freeze as `CAPTURE_BOOTSTRAP` 11,240B/
  `15f05e57bcc5fc6ddbd4ae8cdd732e531834719c8d11d92b3c6099bf9353dc74`,
  `MATERIALIZE_BOOTSTRAP` 12,425B/
  `308a68bda0f91199e59653b426775ff3c657953e1faea57ffee1da3b81d2984e`,
  capture root 111,666B/
  `7d71e514a4fa30635df26dd52377d8ff172db2c2f0647416fbdd38a7bcab33c5`,
  materialize root 71,653B/
  `5d6ae172422b805fa2b358c605285a8056e37e492ce31fb2fdf724bc3047ec16`
  and stage root 53,723B/
  `62a469141b1e03a62018a9fec89001c95445126f0a4948c6c6331a9de778ca4c`;
  their exact Git-blob OIDs are frozen in the readiness ledger.
- The source implements gate-off outer/bootstrap/root contracts with READY,
  gate, liveness, bounded status-loss containment and concrete default
  capture/orchestrator/adapter-child wiring.  Static red-team is P0/P1/P2 zero;
  normal/`-O` are 90/90 and outer plus five payloads compile in both modes.
  Earlier 3C/4A identities are historical scoped evidence intentionally
  superseded by signal/process-group containment and production-reachability
  wiring, not current zero-drift identities.
- `implementation_complete=true` describes source completeness only.  Status
  remains `SOURCE_ONLY_IMPLEMENTATION_COMPLETE_NOT_AUTHORIZED`; all four
  execution gates are false, credential/capture capsules are `NOT_PROVISIONED`
  and every operational/cost count is zero.  The architecture sequence remains
  this exact-six source → exact-four source acceptance → separate credential /
  OAuth source and acceptance → separately authorized capture and later
  materialization.  None of those later authorities is implied here.

## Item 26 M1 source CI-portability successor architecture (2026-08-20)

- Failed source checkpoint `2b690ffe7f484e07075e776f52fdb436d297dc4d`
  freezes parent A `a30b879d06c388a4a0e230b5a23b2eaedc93649d`, tree
  `91f314cd954f434a4649214b54d5bb085b8fdee9`, its exact-six path set,
  four ledger identities, source/test identities and the five embedded
  payload identities.  It remains an immutable rejected checkpoint; its source
  and payload bytes are the controlled non-operational implementation.
- Push run `32314078284` / job `96262703265` terminated attempt one after Unit
  ran 2,790 tests with zero failures, three errors and 36 skips.  Its three
  errors are Linux test-fixture portability defects: a missing injected Git
  reader fell through to the macOS repository-root binding; a capture aggregate
  used live macOS system-identity probing instead of a binding-derived stable
  leaf; and a materialize negative test omitted its accepted tool probe, so the
  Linux OpenSSL identity failed before the intended pipe preflight.  Later
  Quality, PostgreSQL, readiness and Compose stages were skipped.  The push is
  the hard-stop trigger.  PR `32314083397` was still in progress at that stop;
  its later matching terminal failure is read-only history, not an authority
  premise.  Both attempts retain previous-attempt null and rerun zero.
- `CTO-AUTH-ITEM26-M1-SOURCE-CI-PORTABILITY-001` allows exactly one append-only
  direct-child exact-five candidate: four ledgers plus the existing test.  The
  source and all five payloads are zero-touch.  The only permitted fixture
  changes inject the already defined Git-reader seam, patch only the capture
  identity leaf with binding-derived mode/owner/size/hash rows, and inject an
  accepted-binding materialize tool probe.  Fixed revision/blob/hash/size
  loading, root parent-chain validation, anti-I/O/process guards, module
  cleanup, directional blocking pipe rejection and `Popen=0` remain asserted.
  Reverse application must reconstruct the exact failed test.
- The repaired test is frozen at mode `100644`, 276,592 bytes, blob
  `395183cda18a6021a923764ea0f584abacdbebf4`, SHA-256
  `00e04d37b58ef746766a59b7ee57d58cf5adf146f9cb20ea27db29734d96b121`
  and `+90/-3`.  Its reverse patch verifies against the failed test; source is
  byte-identical.  Normal/optimized focused tests are each 90/90 and
  production readiness is each 138/138; compile, diff, strict JSON and direct
  Secret hygiene checks pass without changing the `25/29` / `25/38` state.
- Candidate revision/tree and own CI stay empty/pending with all observation
  counts zero until self-binding.  One commit, one normal non-force push and
  one unique attempt-one push/PR observation are the complete authority;
  failure/cancel stops and retry, rerun or second push is forbidden.
- The runtime boundary is unchanged: four execution gates false, credentials
  and capture capsule `NOT_PROVISIONED`, operational authorization/readiness
  false and all current-round operational/cost counts zero.  OAuth, provider
  calls, capture and materialization remain future independent gates.  S0,
  Item 26, M1/M2, readiness and credit do not change.

## Item 26 M1 portability successor terminal acceptance architecture (2026-08-20)

- Exact-five `4bddf697f9ed8d86890b851e5390c402e8413950`, parent
  `2b690ffe7f484e07075e776f52fdb436d297dc4d`, tree
  `d9ad6d1a2a359b900da7148779f830e8b63b78f1`, is the accepted append-only
  portability successor.  Its five path identities are frozen in the readiness
  ledger.  The repaired test remains 276,592 bytes/blob
  `395183cda18a6021a923764ea0f584abacdbebf4`/SHA-256
  `00e04d37b58ef746766a59b7ee57d58cf5adf146f9cb20ea27db29734d96b121`;
  source and all five embedded payload identities remain unchanged.
- Push `32317333050`/`96272304838` and PR
  `32317336506`/`96272314969` are the unique terminal-success routes for this
  exact revision.  Both are attempt one, previous-attempt null, rerun zero and
  22/22 steps.  Each ran Unit 2,790 with F0/E0/skip36, frozen
  `[10,1,12,22,21]`, Quality 7 PASS + 1 EXPECTED_FAIL, PostgreSQL 6 OK,
  readiness 138/138 and Compose success.  Each has one Node 20-to-24 warning
  and no error/failure annotations; four terminal pointers and the exact
  push-plus-PR inventory agree.
- `CTO-AUTH-ITEM26-M1-SOURCE-CI-PORTABILITY-ACCEPTANCE-001` permits only one
  direct-child exact-four ledger acceptance candidate.  Its revision/tree and
  own CI stay empty/pending/zero before self-binding.  The full allowance is
  one commit, one normal non-force push and one unique attempt-one push/PR
  observation; failure/cancel stops and retry, rerun or second push is
  forbidden.
- Acceptance changes controlled source topology only.  The exact-four child
  must not change source, test or payload bytes.  Execution gates, credential /
  capture provisioning, operational authority/readiness, actions, cost, S0,
  Item 26, M1/M2, readiness and credit remain unchanged and fail-closed.

## Item 26 temporary-STS capsule source architecture (2026-08-20)

- Exact-four acceptance f6 `f6a8062de96623ce383eb4d1b5cd401ff9fa9cc5`,
  parent `4bddf697f9ed8d86890b851e5390c402e8413950`, tree
  `0ac436757b6ab0e5cbdffc5109b3736eb1a914a9`, is terminally accepted by unique
  attempt-one push `32320719736`/`96282216090` and PR
  `32320721588`/`96282221003`.  Both are 22/22, previous-attempt null,
  rerun zero, Unit 2,790 F0/E0/skip36, `[10,1,12,22,21]`, Quality 7+1,
  PostgreSQL 6, readiness 138 and Compose green.  The four terminal pointers
  and exact two-run inventory agree.
- `CTO-AUTH-ITEM26-M1-CREDENTIAL-OAUTH-CAPSULE-SOURCE-001` permits exactly one
  f6 direct-child exact-six source candidate: four ledgers plus
  `tools/item26_aliyun_temporary_sts_capsule_v1.py` and its test.  Source/test
  identities are respectively 49,494B/blob
  `99110863d055929fbc76950ec2bc9aa8fd0f7bc6`/SHA-256
  `7ed50fd5acdbb5733a174367e8bcb339b3a6bc07b49fed3a31243fddf763e4e3`
  and 57,199B/blob `37c5ce3040a8dd7636fb7e173a66881405f7bef7`/
  SHA-256 `d2fc65f83790552d71f0b6c9aacf5ffc0b9486dca24cb5220b860747b75fc565`.
  Red-team is 0/0/0 and normal/optimized are each 46/46.
- The new module defines an inert temporary-STS custody capsule, not an OAuth
  client or installer.  It binds strict canonical schemas, domain-separated
  account/principal commitments, anonymous blocking FD roles, bounded private
  envelopes, integer non-increasing TTL, one-shot copies and explicit scrub,
  plus a future root-owned O_EXCL/NOFOLLOW inventory contract.  The accepted
  M1 stager/source/test and its five embedded payloads are not changed.
- Source status is complete/not-authorized, credential status is
  `NOT_PROVISIONED`, all four gates are false and the action entrypoint is an
  unconditional refusal.  Self revision/tree and own CI are empty/pending/0;
  authority is one commit, one normal non-force push and one unique
  attempt-one dual-CI observation, with failure stop and no retry/rerun/second
  push.
- Audit accounting deliberately separates one incidental non-provider
  Homebrew metadata download and one possible cache-write event caused by
  `brew list --versions aliyun-cli` from zero Aliyun/provider/cloud calls.
  Generic network-zero and filesystem-write-zero are not claimed.  Homebrew
  install/upgrade, cleanup/retry, Aliyun config/login/OAuth, root/sudo,
  credential action, database, capture and materialization remain zero.
  Provisioning and its receipt acceptance are later independent gates;
  operational capture requires another separate authorization.

## C1 credential-capsule source terminal acceptance boundary (2026-08-20)

- Exact-six source revision `86206f816fb092a7fca7a577b1391e251dfca5ca`
  is fixed above f6 with tree `99d83cae1c82ad12e231172e87ff5e1eefae267c`.
  Its attempt-one push `32327347443`/job `96301181826` and PR
  `32327349489`/job `96301188689` are terminal success, previous attempt null,
  rerun0 and 22/22.  Each route runs Unit2836 F0/E0/skip36, all 46 capsule
  test methods, `[10,1,12,22,21]`, Quality7+1EF, PG6, readiness138/0 and
  Compose success; terminal pointers are exact and inventory is exactly two.
- `CTO-AUTH-ITEM26-M1-CREDENTIAL-CAPSULE-SOURCE-ACCEPTANCE-001` accepts the
  inert source implementation and permits only one 862 direct-child exact-four
  ledger candidate.  Source/test and all prior payloads are zero-touch.
  Candidate self revision/tree and own CI remain empty/pending/0 until its one
  commit, one normal non-force push and unique attempt-one dual-CI observation;
  failure/cancel stops and retry, rerun and second push are prohibited.
- This is an architecture/source acceptance, not credential or operational
  acceptance.  Credential state remains `NOT_PROVISIONED`; all four execution
  gates and every login/OAuth/config/root/sudo/API/provider/cloud/database/
  capture/materialization/private-key/paid/cleanup/replay authority remain
  false.  Separate provisioning authorization and secret-free receipt
  acceptance must precede a separate capture operational authorization.
- The historical Homebrew deviation remains explicit: one non-provider API
  metadata-network event and one possible cache write; generic network/write
  zero is not claimed.  Homebrew install/upgrade/cleanup/retry and all
  Aliyun/provider/cloud actions remain zero.  Item26/evidence/S0/M1/M2,
  readiness `25/29`/`25/38` and credit false are unchanged.

## C2 same-root capsule capture-wiring source boundary (2026-08-20)

- Exact-four acceptance revision `314a6b885bc7bda9790074a201ac176e498326b5`
  is fixed above 862 with tree `2c88d9ccca1cee709e4ccca9df573e0f6f28dc65`.
  Its attempt-one push `32329891018`/job `96308385583` and PR
  `32329894079`/job `96308393220` are terminal success, previous attempt null,
  rerun0 and 22/22; each has Unit2836 F0/E0/skip36,
  `[10,1,12,22,21]`, Quality7+1EF, PG6, readiness138/0 and Compose success.
  Four terminal pointers are exact and inventory is exactly two.
- `CTO-AUTH-ITEM26-M1-CREDENTIAL-CAPSULE-CAPTURE-WIRING-SOURCE-001`
  permits only one 314 direct-child exact-six candidate: four ledgers plus the
  existing M1 stager/test.  Their frozen identities are 500,417B/
  `e7cbac47…`/blob `bf968ab6…` and 344,891B/`78eff1e2…`/blob
  `e95d1213…`; focused normal/optimized are 107/107 and red-team is 0/0/0.
- C2 binds a same-root READY/ACK exchange to a live opaque session.  Its
  Darwin `st_dev` shim is deliberately local to the C2 capture wiring; the C1
  standalone default Darwin limitation is explicit and uncorrected.  Capture
  bootstrap/root change to 14,543B/136,488B with frozen identities; the other
  three embedded payloads and standalone C1 capsule source remain exact.
- This remains source-only and fail closed.  Credential state is
  `NOT_PROVISIONED`, gates are false and no login/OAuth/configuration/root/
  sudo/provider/API/cloud/database/capture/materialization/private-key/paid/
  cleanup/replay authority is created.  Self revision/tree and own CI are
  empty/pending/0; one commit, one normal push and unique attempt-one dual CI
  are the whole authority, with failure stop and no retry/rerun/second push.
- The historical Homebrew network/cache deviation remains one/one with generic
  historical zero claims false; C2 adds no external/provider/root action.
  Item26/evidence/S0/M1/M2, readiness `25/29`/`25/38` and credit false remain
  unchanged.

## C2 capture-wiring source terminal acceptance boundary (2026-08-20)

- Exact-six revision `3270e0abcfe515a1c066335da182b26031abb5eb` is fixed
  above 314 with tree `0c1fded8418bb2ca0f1ee1f97dd29257198ee77f`.
  Attempt-one push `32339345367`/job `96335113128` and PR
  `32339348621`/job `96335122834` are terminal success, previous attempt null,
  rerun0 and 22/22.  Each route has Unit2853 F0/E0/skip36, durations
  1818.639s/1410.058s, focused methods 90→107 (+17), ambient 2836→2853 (+17),
  `[10,1,12,22,21]`, Quality7+1EF, PG6, readiness138/0 and Compose success;
  terminal pointers are exact and inventory is exactly two.
- `CTO-AUTH-ITEM26-M1-CREDENTIAL-CAPSULE-CAPTURE-WIRING-SOURCE-ACCEPTANCE-001`
  accepts the C2 source boundary and permits only one 3270 direct-child
  exact-four ledger candidate.  Stager/test, five payloads and C1 source are
  zero-touch.  Self revision/tree and own CI are empty/pending/0 until one
  commit, one normal push and unique attempt-one dual CI; failure stops and
  retry/rerun/second push are prohibited.
- Same-root READY/ACK remains live-session-bound and opaque.  Darwin `st_dev`
  compatibility remains C2-only; C1 standalone default Darwin behavior is
  explicitly uncorrected.  Credential remains `NOT_PROVISIONED`, all gates and
  operational authority remain false, and future provisioning, receipt
  acceptance and capture authorization remain independent.
- Historical Homebrew research/audit remains network one, possible cache write
  one, generic historical zero claims false; no new external/provider/root
  action occurs.  Item26/evidence/S0/M1/M2, `25/29`/`25/38` and credit false
  remain unchanged.

## C3 stock Aliyun CLI OAuth capability NO-GO source boundary (2026-08-20)

- Exact-four base `74c1c732c3fdafdc402ec2cc313fc9eafd45d839` is fixed
  above 3270 with tree `026f78d609ee13c85d43634ec4cf4290b27e51ac`.
  Attempt-one push `32343007517`/suite `87675939533`/job `96345723914` and
  PR `32343013275`/suite `87675953859`/job `96345739667` are terminal
  success, previous null, rerun0 and 22/22.  Each route has Unit2853
  F0/E0/skip36, duration1835.234s/1867.948s, 107 focused methods,
  `[10,1,12,22,21]`, Quality7+1EF, PG6, readiness138/0 and Compose success;
  four pointers are exact and inventory is exactly two.
- `CTO-AUTH-ITEM26-M1-ALIYUN-CLI-OAUTH-CAPABILITY-SOURCE-001` permits only
  one 74c1 direct-child exact-six: four ledgers plus the new stock-capability
  source/test.  Identities freeze at 19,960B/`1d591941…`/blob `07ef4524…`
  and 36,379B/`dfcbb4ce…`/blob `cf89538f…`; red-team is 0/0/0 and focused
  normal/optimized are 37/37.
- Official `v3.4.11` is commit-pinned to
  `f54f5fe9caa99723a6324b20eaa60f3de3b049cb`.  Eleven official evidence
  entries bind exact source, commit/release and official docs.  The matrix
  distinguishes 11 observed stock capabilities from eight NoteAI accepted
  requirements; all accepted rows reject stock support.  Result is precisely
  `NO_GO_STOCK_CLI_FD_ONLY_OAUTH`, not a generic no-OAuth assertion.
- Local CLI identity is a static tracked-ledger fact: version3.4.11, resolved
  Homebrew path, mode0555, owner `openclaw:admin`, 87,064,450B and SHA-256
  `7a418ea4…`; no CLI execution or live inspection occurs.  Research browsing
  occurred, its request count is null/not-enumerated and generic network-zero
  is false; provider/login/API/config-write remain zero.  Historical Homebrew
  network/cache remains one/possible-one.
- Candidate self revision/tree and own CI remain empty/pending/0; all six gates
  are false, credential remains `NOT_PROVISIONED`, and this source authorizes
  no operational action.  Source acceptance, capability replacement/decision,
  provisioning plus receipt acceptance, and capture authorization remain
  separate future gates.  Item26/evidence/S0/M1/M2, `25/29`/`25/38` and credit
  false are unchanged.

## C3 stock Aliyun CLI OAuth capability source acceptance boundary (2026-08-20)

- Exact-six source `a988f9860a5c95fee128dba3fca6860a16172128` fixes
  parent `74c1c732c3fdafdc402ec2cc313fc9eafd45d839`, tree
  `7e992f3ceeef88ad0854e55cd2ea83be97caebdb` and exactly four
  ledgers plus the 19,960B source and 36,379B test identities already frozen.
- Attempt-one push `32349632989`/suite `87693372678`/job `96365747877` and
  PR `32349637512`/suite `87693384175`/job `96365761404` are terminal
  success, previous null, rerun0 and 22/22.  Their Unit step 13 windows are
  `08:37:18Z`–`09:10:45Z` and `08:37:31Z`–`09:02:31Z`, both success.  Each
  route has Unit2890 F0/E0/skip36, duration1988.053s/1481.296s, all 37 new
  focused methods above baseline2853, `[10,1,12,22,21]`, Quality7+1EF, PG6,
  readiness138/0 and Compose success.  Four final run/job pointers are exact;
  inventory is exactly two and annotations are warning1/error0/failure0.
- `CTO-AUTH-ITEM26-M1-ALIYUN-CLI-OAUTH-CAPABILITY-SOURCE-ACCEPTANCE-001`
  accepts only this source capability checkpoint and permits one a988
  direct-child exact-four ledger candidate.  Its self revision/tree and own CI
  remain empty/pending/0; one commit, one normal push and unique attempt-one
  dual CI are the whole future scope, with failure stop and no retry/rerun/
  second push.
- The acceptance preserves the exact decision boundary:
  `NO_GO_STOCK_CLI_FD_ONLY_OAUTH`, credential `NOT_PROVISIONED`, official
  v3.4.11/full-commit evidence and matrix frozen, local CLI identity static,
  and all six execution gates false.  It authorizes no login, OAuth, config,
  provider/API, cloud, root, credential or capture action.
- Official research remains web=true with count null/not-enumerated and generic
  network-zero false.  Homebrew history remains network1/possible-cache1; the
  acceptance adds no new external/provider/root action.  Item26/evidence/S0/
  M1/M2, readiness `25/29`/`25/38` and credit false remain unchanged.
