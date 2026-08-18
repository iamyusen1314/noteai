# Architecture Summary

Last updated: 2026-08-18

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
- Local root-owned material is not portable CI evidence. A Secret-free,
  clean-clone-replayable terminal capsule or equivalent trusted distribution
  contract remains mandatory before Item 26 credit or any paid PITR successor.

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
