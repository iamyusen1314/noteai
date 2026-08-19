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
