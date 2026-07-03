# Risk Register

Last updated: 2026-07-02

## Critical Risks

### Billing or credit accounting is wrong

- 风险描述: Paid operations, monthly credits, recharge credits, refunds/topups, and token cost accounting are revenue-critical. A bug can undercharge users, overcharge users, or make admin revenue reports inaccurate.
- 涉及文件: `model/billing.py`, `model/api.py`, `model/admin_server.py`, `model/db.py`, `model/admin.html`, `NoteAI_Pro_Demo_Framer.html`, `tests/test_billing_token_cost.py`.
- 可能后果: Direct financial loss, user disputes, inability to price packages, wrong margin reporting.
- 建议验证方式: Unit tests for mixed monthly/recharge deduction, topup, refund, quota exhaustion, admin usage stats; real API smoke with a test user; compare user-side and admin-side usage rows.
- 是否需要用户确认后才能修改: yes.

### Auth/session/admin permission regression

- 风险描述: User auth and admin auth are separate. Admin endpoints can adjust users, credits, model state, crawler state, prompts, and logs.
- 涉及文件: `model/auth.py`, `model/admin_auth.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`.
- 可能后果: Permission bypass, account takeover, unauthorized credit/subscription changes, leakage of user/admin data.
- 建议验证方式: Auth contract tests for anonymous/user/admin paths, negative tests for admin endpoints without admin bearer token, manual admin login/logout smoke.
- 是否需要用户确认后才能修改: yes.

### Runtime SQLite schema changes damage data

- 风险描述: Schema and migrations are embedded in `model/db.py` and can run during app initialization. There is no confirmed migration framework or rollback plan.
- 涉及文件: `model/db.py`, `model/hot_keywords.py`, runtime DB files under `model/data/`.
- 可能后果: Data loss, incompatible columns, broken startup, inability to recover production DB.
- 建议验证方式: Run migrations on a copy of production-like DB, inspect `PRAGMA table_info`, run API/admin smoke after migration.
- 是否需要用户确认后才能修改: yes.

### Secrets or tokens leak into Git/logs

- 风险描述: Project uses many third-party keys and tokens. The repo is public per docs, so accidental secret leakage is severe.
- 涉及文件: `.env`, `model/.env`, `model/.env.example`, `docs/DEPLOYMENT_SECRETS.md`, logs, shell scripts, CI.
- 可能后果: API key compromise, account abuse, billing loss, forced key rotation.
- 建议验证方式: `git status`, secret scan with patterns excluding templates, review CI logs, never print `.env` values.
- 是否需要用户确认后才能修改: yes.

### Real payment integration is not confirmed

- 风险描述: Billing/topup/upgrade logic exists, but a real payment order/callback/reconciliation flow is not confirmed in inspected files.
- 涉及文件: `model/api.py`, `model/billing.py`, `model/db.py`, frontend pricing/credit UI.
- 可能后果: Users may receive credits without real payment, or paid launch cannot legally/financially reconcile transactions.
- 建议验证方式: Locate/implement payment provider flow only after approval; test order creation, callback signature verification, idempotency, refunds, reconciliation.
- 是否需要用户确认后才能修改: yes.

## High Risks

### Large uncommitted diff spans many critical modules

- 风险描述: Current branch has a large uncommitted diff across frontend, API, billing, deployment, tests, and docs.
- 涉及文件: all files shown in `git status --short`.
- 可能后果: Hard to review, merge conflicts, accidental commit of local artifacts, difficult rollback.
- 建议验证方式: Review `git diff --stat`, group staged files intentionally, run full tests, make a checkpoint commit after user approval.
- 是否需要用户确认后才能修改: yes.

### Frontend/backend payload drift

- 风险描述: Static frontend manually constructs payloads for AI diagnosis/generation/chat. Backend Pydantic models evolve separately.
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, `tests/test_frontend_report_static.py`, `tests/e2e/content-intent.spec.js`.
- 可能后果: UI controls become decorative, backend ignores user intent, requests fail or silently use defaults.
- 建议验证方式: Playwright route interception, backend contract tests, static assertions for all required fields.
- 是否需要用户确认后才能修改: no for tests/docs; yes for behavior changes.

### Core AI quality may regress despite scoring gates

- 风险描述: V0.4 scoring, prompts, fact routing, sanitizers, and ranker interact. Passing score does not automatically mean content is natural or valuable.
- 涉及文件: `model/api.py`, `model/model_router.py`, V0.4 model/training files, prompt manager files, quality artifacts.
- 可能后果: Generated titles/body feel templated, fake, low-value, or inconsistent across industries.
- 建议验证方式: Real-chain smoke for each core industry and each creation direction; record title/body/score/fact decisions; human review.
- 是否需要用户确认后才能修改: yes for prompt/model/business behavior changes.

### Market timing freshness gate can block core flows

- 风险描述: Production rules require fresh industry trend evidence. If worker/cloud snapshot/authorized source is missing or stale, API may return market timing unavailable.
- 涉及文件: `model/hot_keywords.py`, `model/scheduler_a.py`, `model/market_timing_worker.py`, `model/api.py`, `docker-compose.yml`, `docs/MARKET_TIMING_CLOUD_PIPELINE.md`.
- 可能后果: AI diagnosis/generation fails in production or uses stale evidence if guard regresses.
- 建议验证方式: Worker smoke on cloud-like environment, freshness tests, API behavior test with stale/missing data.
- 是否需要用户确认后才能修改: yes.

### Model artifact loading and deployment are fragile

- 风险描述: Production requires V0.4 artifacts and SHA/checks. Git LFS/object storage availability is deployment-platform dependent.
- 涉及文件: `model/artifacts/`, `model/model_registry.json`, `scripts/fetch_model_artifacts.py`, `Dockerfile`, `scripts/docker_entrypoint.sh`, docs.
- 可能后果: Service starts with missing/legacy model, startup failure, wrong scoring behavior.
- 建议验证方式: `python scripts/fetch_model_artifacts.py --check-only --required`, production readiness gate, container startup smoke.
- 是否需要用户确认后才能修改: yes.

### External provider reliability/cost risk

- 风险描述: Claude/Kimi/Amap/Meituan calls have timeouts, concurrency limits, token costs, and possible regional network issues.
- 涉及文件: `model/model_router.py`, `model/api.py`, `model/fact_enrichment.py`, `model/billing.py`.
- 可能后果: Empty responses, failed OCR, slow diagnosis, inaccurate billing cost, poor user experience.
- 建议验证方式: Provider-specific smoke tests with timeout/retry logging and usage record checks; avoid logging secrets.
- 是否需要用户确认后才能修改: yes for live-cost tests or provider changes.

## Medium Risks

### `/health` model label is misleading

- 风险描述: `/health` currently reports `legacy_score_model` even when V0.4 loads.
- 涉及文件: `model/api.py`.
- 可能后果: Operators/user believe V0.4 is not active; monitoring is misleading.
- 建议验证方式: Update health payload with actual model status and test it.
- 是否需要用户确认后才能修改: yes during current handoff pause.

### Fact enrichment can pollute delivery copy

- 风险描述: Generic fallback facts or placeholders can leak into publishable body if routing/sanitizers regress.
- 涉及文件: `model/api.py`, `model/fact_enrichment.py`, `tests/test_api_contracts.py`.
- 可能后果: Unnatural copy, fake facts, loss of user trust.
- 建议验证方式: Tests for no placeholder sentences, decision intent requiring confirmed merchant, Amap/Meituan facts natural integration.
- 是否需要用户确认后才能修改: yes for behavior changes.

### Screenshot OCR gating can break upload workflows

- 风险描述: The rule requires every uploaded screenshot to finish AI recognition before diagnosis. Failures or pending state handling can block users.
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, Kimi/Moonshot OCR helpers.
- 可能后果: Users cannot start diagnosis after uploading images; or diagnosis starts without full visual context.
- 建议验证方式: Browser/e2e upload tests with multiple images, failure handling tests, API OCR smoke.
- 是否需要用户确认后才能修改: no for tests; yes for UX/business rule changes.

### Admin and frontend pricing displays may drift from backend billing

- 风险描述: Pricing page, balance dialogs, profile/admin usage views must match `billing.py`.
- 涉及文件: `model/billing.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`, `NoteAI_Pro_Demo_Framer.html`.
- 可能后果: User confusion, support disputes, wrong package economics.
- 建议验证方式: Tests that frontend/admin read `/billing/tiers` and usage endpoints rather than hard-coded stale values.
- 是否需要用户确认后才能修改: yes for pricing changes.

### Crawler/Playwright cloud behavior may differ from local

- 风险描述: Docker installs Playwright Chromium, but scraping/market timing behavior may still depend on network, cookies, display/headless constraints, and platform policies.
- 涉及文件: `Dockerfile`, `model/crawler.py`, `model/scheduler_a.py`, `model/market_timing_worker.py`, `docker-compose.yml`.
- 可能后果: Market data unavailable, blocked crawler, unstable worker.
- 建议验证方式: Cloud-like container run, worker logs, data freshness check.
- 是否需要用户确认后才能修改: yes.

## Low Risks

### `model/api.py` is too large

- 风险描述: Many unrelated concerns live in a single large file.
- 涉及文件: `model/api.py`.
- 可能后果: Hard to review, accidental regressions, duplicated logic.
- 建议验证方式: Increase tests around changed behavior before any refactor.
- 是否需要用户确认后才能修改: yes, because refactor risk is high.

### Static HTML is hard to maintain

- 风险描述: A very large single HTML file holds layout, state, API calls, and rendering.
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`.
- 可能后果: UI regressions, hidden duplicate state, hard-to-test changes.
- 建议验证方式: Keep Playwright e2e and static tests close to every UI contract.
- 是否需要用户确认后才能修改: yes for structural refactor.

### Generated/local artifacts can clutter reviews

- 风险描述: Probe JSON, crawler logs, pycache, local screenshots, test reports, and DB changes can appear during development.
- 涉及文件: `quality/*.json`, `model/data/*.json`, `__pycache__/`, `test-results/`, local DB files.
- 可能后果: Accidental noisy commits or leaking local state.
- 建议验证方式: `git status --short`, `.gitignore`, explicit staging.
- 是否需要用户确认后才能修改: no for docs/gitignore; yes before deleting artifacts.

### No confirmed lint/typecheck command

- 风险描述: CI relies on py_compile and unittest, but no lint/typecheck workflow is confirmed.
- 涉及文件: `package.json`, `.github/workflows/ci.yml`, Python files.
- 可能后果: Style drift, dead code, dynamic runtime bugs.
- 建议验证方式: Add lint/typecheck only after user approval; otherwise rely on tests.
- 是否需要用户确认后才能修改: yes.

### Documentation can become stale

- 风险描述: Rapid changes to AI strategy, billing, deployment, and model training may outpace docs.
- 涉及文件: `docs/`, `.codex/`, `AGENTS.md`.
- 可能后果: Future agents follow outdated assumptions.
- 建议验证方式: Update handoff after each stage and reconcile docs before checkpoint commit.
- 是否需要用户确认后才能修改: no for handoff/docs, yes for code behavior.
