# Current Task Handoff

Last updated: 2026-07-03

## 2026-07-03 Execution Update - Controlled Real Crawler Smoke

### 本轮完成了什么

- Ran the user-approved controlled real crawler/worker smoke.
- Used a temporary SQLite DB and temporary `market_timing_snapshot.json`.
- Explicitly avoided local `xhs_state.json` / cookies by pointing scheduler state paths to missing temporary files.
- Limited scope to 6 core industries, one search seed per industry, one scroll round, and short waits.
- Did not use production DB, did not upload object storage, did not run daemon mode, did not deploy, and did not call AI/payment/email/SMS APIs.
- Verified the real public web smoke completed and generated a fresh six-industry snapshot.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the real crawler smoke plan, command result, operational findings, and remaining risks per user instruction.

### 关键决策

- Validate public discovery as a best-effort source, not a production guarantee.
- Treat `search_recommend` as useful fresh public discovery evidence, but not official hot search.
- Keep `industry_baseline` as the guaranteed coverage layer so cloud deployment does not depend on public crawling success.
- Do not use local login state/cookies in this smoke.

### 运行了哪些命令

- One-off `.venv/bin/python - <<'PY' ... PY` controlled smoke script that:
  - set low crawl env knobs,
  - imported `hot_keywords`, `scheduler_a`, and `market_timing_worker`,
  - redirected `hot_keywords.DB_PATH` to a temporary DB,
  - redirected `scheduler_a.STATE_PATH` and `scheduler_a.COOKIES_PATH` to missing temporary files,
  - limited `scheduler_a.CHANNELS` to 美食、旅行、穿搭、美妆、家居、健身,
  - limited `SEARCH_SEEDS` to 1 seed per core industry,
  - ran `market_timing_worker.run_once()` with no upload URL,
  - printed only sanitized aggregate counts and source distributions.

### 每个命令的结果

- Command completed successfully with `ok=true`.
- Public pages attempted: 12.
- Raw scraped keywords: 43.
- Scrape error category: `none`.
- Public source breakdown: `search_recommend=43`, `hot_search=0`, `homefeed=0`.
- Baseline generated rows: 96 candidates; final snapshot source breakdown included `industry_baseline=89`.
- Snapshot domain count: 6.
- Snapshot domains: 健身、家居、旅行、穿搭、美妆、美食.
- Every core domain had fresh qualified evidence:
  - 健身: 25 keywords, 24 qualified, sources `industry_baseline=15`, `search_recommend=10`.
  - 家居: 22 keywords, 22 qualified, sources `industry_baseline=15`, `search_recommend=7`.
  - 旅行: 17 keywords, 17 qualified, sources `industry_baseline=13`, `search_recommend=4`.
  - 穿搭: 25 keywords, 25 qualified, sources `industry_baseline=15`, `search_recommend=10`.
  - 美妆: 26 keywords, 26 qualified, sources `industry_baseline=16`, `search_recommend=10`.
  - 美食: 17 keywords, 15 qualified, sources `industry_baseline=15`, `search_recommend=2`.
- Temporary DB: yes.
- Temporary snapshot: yes.
- Object storage upload: no.
- Login state/cookies used: no.

### 当前仍然失败的问题

- `hot_search` was still 0 in this smoke, so official/hot-search-style signal remains unavailable.
- `homefeed` yielded 0 usable rows in this low-scope smoke; useful public data came from `search_recommend`.
- This smoke ran once from the local network; it does not prove multi-day cloud scheduler reliability.

### 当前未完成工作

- No cloud cron/scheduler deployment has been configured.
- No object storage upload smoke has been run.
- No API runtime smoke against the generated temporary snapshot has been run.
- No multi-day reliability monitoring/alerting exists yet.

### 当前最高风险

- Public crawling remains best-effort and can change due to target site behavior, bot detection, login prompts, or network conditions.
- Production must rely on worker automation + snapshot freshness + `industry_baseline` fallback, not on `hot_search`.
- Product wording must continue to say "行业新鲜样本/市场时机参考", not "官方热搜".

### 下一步最小可行计划

1. Keep the staged no-authorized-source fallback implementation.
2. Add a future cloud deployment smoke for object storage upload/download using a synthetic or worker-generated snapshot.
3. Add monitoring requirements: per-domain freshness, per-domain qualified counts, scrape result counts, baseline-only ratio, and upload success.
4. Do not run wider/full crawler or daemon mode without explicit confirmation.

### 不能在未经确认的情况下修改

- Any production/shared DB or object storage.
- Any daemon crawler/worker run, full crawl, login-state/cookie usage, or high-frequency crawling.
- Any product copy that presents `search_recommend` or `industry_baseline` as official hot search.
- Any deploy, scheduler setup, commit, push, payment/email/SMS operation, or production config change.

## 2026-07-03 Execution Update - Market Timing No-Authorized-Source Fallback

### 本轮完成了什么

- Optimized the market timing evidence pipeline for the user-approved product direction: no authorized/official trend source dependency.
- Added a labelled daily industry baseline evidence pack (`industry_baseline`) covering core industries: 美食、旅行、穿搭、美妆、家居、健身.
- Changed `noteai-trends-worker` behavior from "scrape empty means fail" to "try public scrape, then generate labelled baseline evidence, then export a fresh snapshot".
- Kept the product honesty boundary: `industry_baseline` is fresh industry evidence for coverage and suggestions, but not platform hot search or official trend data.
- Updated docs, env template, and production readiness checks so production no longer requires authorized trend source variables.
- Added/updated tests proving empty scrape can still export a fresh multi-industry snapshot and baseline evidence does not set `is_trending_topic`.

### 修改了哪些文件

- `model/hot_keywords.py`
- `model/market_timing_worker.py`
- `tests/test_market_timing_keyword_quality.py`
- `docs/MARKET_TIMING_CLOUD_PIPELINE.md`
- `docs/DEPLOYMENT_SECRETS.md`
- `docs/REAL_CHAIN_QUALITY_STABILIZATION_PLAN.md`
- `model/.env.example`
- `tools/production_readiness_gate.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/hot_keywords.py`: Added `industry_baseline` source, core domain seed evidence, `baseline_evidence_rows()`, `ensure_daily_evidence_pack()`, and confidence notes that prevent baseline evidence from being presented as official hot search.
- `model/market_timing_worker.py`: Worker now catches public scrape errors/empty results, fills missing core domains with baseline evidence, writes/export snapshots, and only fails if the final snapshot has zero domains.
- `tests/test_market_timing_keyword_quality.py`: Replaced authorized-source worker fallback test with no-authorized baseline fallback tests; added coverage for core domain baseline generation and "fresh but not fake trending" behavior.
- `docs/MARKET_TIMING_CLOUD_PIPELINE.md`: Rewrote deployment semantics around public discovery plus `industry_baseline`, removed authorized source from required production plan, and documented evidence source meanings.
- `docs/DEPLOYMENT_SECRETS.md`: Removed authorized trend token/source from required production secret/config guidance and added baseline-evidence safety wording.
- `docs/REAL_CHAIN_QUALITY_STABILIZATION_PLAN.md`: Added RQS-25 status describing no-authorized-source cloud fallback.
- `model/.env.example`: Removed authorized trend env placeholders from the production template.
- `tools/production_readiness_gate.py`: Removed authorized trend env names from required env checks and added a doc check for `industry_baseline`.
- `.codex/handoffs/current-task.md`: Recorded this stage.

### 关键决策

- Do not depend on authorized/official trend source for production.
- Do not let API user requests run local scraping; the worker produces snapshots, API consumes snapshots.
- Guarantee daily per-industry snapshot coverage through `industry_baseline`, while explicitly labelling it as auxiliary evidence.
- Keep `timing_coefficient` conservative for baseline-only evidence and keep `is_trending_topic=0.0` unless a high-confidence public hot-search style source is actually present.
- Generate slightly more than the minimum seed candidates per domain before cleaning, because the same keyword quality filter may drop weak/mismatched candidates.

### 运行了哪些命令

- `.venv/bin/python -m unittest tests.test_market_timing_keyword_quality`
- `.venv/bin/python -m py_compile model/hot_keywords.py model/market_timing_worker.py tests/test_market_timing_keyword_quality.py tools/production_readiness_gate.py`
- `git diff --check`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `.venv/bin/python tools/production_readiness_gate.py`
- `docker compose config --quiet`
- `git status --short --branch`
- `git diff --name-status`
- `git diff --stat`

### 每个命令的结果

- Initial `tests.test_market_timing_keyword_quality`: failed 2 tests because baseline generation produced only 11 qualified rows for 美食/旅行 after keyword cleaning.
- After increasing baseline candidate rows per domain, `tests.test_market_timing_keyword_quality`: passed, 10 tests OK. Existing sqlite `ResourceWarning` messages still appear but do not fail the suite.
- py_compile for changed Python files: passed.
- `git diff --check`: passed.
- `tests.test_api_contracts`: passed, 127 tests OK; expected mocked/provider error log lines appeared inside tests.
- Full unittest discovery: passed, 227 tests OK.
- `production_readiness_gate.py`: passed, `production_readiness=PASS`, 48 checks, 0 failed.
- `docker compose config --quiet`: passed.
- Final unstaged diff for this stage spans 8 functional/doc/test files before staging, with about 186 insertions and 82 deletions.

### 当前仍然失败的问题

- No validation command is failing after the fix.
- Existing sqlite `ResourceWarning` noise remains in market timing tests.
- This stage does not prove that public Xiaohongshu scraping will succeed daily; it guarantees that the worker can still publish fresh labelled industry evidence if public scrape is empty or fails.

### 当前未完成工作

- This optimization has not been committed or pushed.
- The worker was not actually run against external sites in this stage.
- No object storage/CDN upload smoke was run.
- No production scheduler/cron was configured or deployed.
- No API runtime smoke against a generated baseline snapshot was run.

### 当前最高风险

- Product wording risk: `industry_baseline` must never be described as official/platform hot search.
- Data quality risk: baseline evidence ensures freshness and industry coverage, but it is weaker than live public discovery.
- Operational risk: cloud scheduler, object storage upload, and alerting are still required to make daily automation production-grade.
- Existing staged checkpoint is large; these new changes modify a subset of already staged files and should be staged intentionally if included in the same checkpoint.

### 下一步最小可行计划

1. Stage this market timing optimization into the current checkpoint scope if user wants it included.
2. Optionally run `npm run test:e2e` again, although this stage did not change frontend code.
3. If user wants production confidence, add a future no-external-crawl smoke using a synthetic generated snapshot file and API import path.
4. Do not run real worker/crawler or object storage upload without explicit confirmation.

### 不能在未经确认的情况下修改

- Any real crawler/worker run against external sites.
- Any object storage/CDN upload or production scheduler configuration.
- Any product copy that claims `industry_baseline` is official trend/hot-search evidence.
- Any commit, push, deploy, DB migration/seed/reset/cleanup, payment/email/SMS operation, or production config change.
- `.env`, `model/.env`, secret/token/API key values, local DBs, and raw runtime/probe artifacts.

## 2026-07-03 Execution Update - Checkpoint Validation and Staging

### 本轮完成了什么

- Ran the approved final no-side-effect validation bundle before checkpointing.
- Staged the reviewed checkpoint scope explicitly by file path.
- Verified no ignored local artifact, local DB, `.env`, Playwright report/result, cache, or log file entered the staging area.
- Fixed three documentation/memory EOF blank-line hygiene issues reported by `git diff --cached --check`.
- Re-staged the hygiene-only documentation fixes and confirmed staged diff checks now pass.
- Did not commit, push, deploy, run migrations/seeds/resets, start Docker services, run crawlers/workers, or make any live API calls in this stage.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`
- `AGENTS.md`
- `.codex/notes/architecture-summary.md`
- `.codex/notes/risk-register.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded validation, staging, command results, remaining risks, and next plan per user instruction.
- `AGENTS.md`: Removed one extra blank line at EOF so staged diff whitespace checks pass.
- `.codex/notes/architecture-summary.md`: Removed one extra blank line at EOF so staged diff whitespace checks pass.
- `.codex/notes/risk-register.md`: Removed one extra blank line at EOF so staged diff whitespace checks pass.

### 关键决策

- No live AI/API validation was run in this stage because the immediate goal was checkpoint hygiene and no-side-effect validation.
- No commit was created yet; staging was completed as an explicit checkpoint-prep step.
- Kept checkpoint as one integrated staging set because the diff spans coupled frontend/API/billing/admin/deploy/test/docs behavior.
- Treated the initial staged whitespace failure as documentation hygiene only; no business code was modified to fix it.

### 运行了哪些命令

- `git diff --check`
- `find model tools tests -name '*.py' -print0 | xargs -0 .venv/bin/python -m py_compile`
- `.venv/bin/python -m py_compile scripts/fetch_model_artifacts.py`
- `bash -n start_all.sh`
- `bash -n scripts/docker_entrypoint.sh`
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`
- `.venv/bin/python tools/production_readiness_gate.py`
- `docker compose config --quiet`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `npm run test:e2e`
- `git add -- ...` with the reviewed checkpoint file list
- `git diff --cached --name-status`
- `git diff --cached --stat`
- `git diff --cached --check`
- `git status --short --branch`
- `tail -n 8 AGENTS.md`
- `tail -n 8 .codex/notes/architecture-summary.md`
- `tail -n 8 .codex/notes/risk-register.md`
- `git add -- AGENTS.md .codex/notes/architecture-summary.md .codex/notes/risk-register.md`
- final `git diff --cached --check`
- final `git diff --check`
- final `git status --short --branch`
- final `git diff --name-status`

### 每个命令的结果

- `git diff --check`: passed before staging.
- Python py_compile over `model`, `tools`, and `tests`: passed.
- `scripts/fetch_model_artifacts.py` py_compile: passed.
- `bash -n start_all.sh`: passed.
- `bash -n scripts/docker_entrypoint.sh`: passed.
- `quality_gate.py quality/golden_notes.sample.json`: passed; the known bad sample remained `EXPECTED_FAIL` by design.
- `production_readiness_gate.py`: passed, `production_readiness=PASS`, 47 checks, 0 failed.
- `docker compose config --quiet`: passed.
- Full unittest discovery: passed, 225 tests OK. It printed expected mocked/provider-error log lines inside tests, but no test failed.
- `npm run test:e2e`: passed, 3 Playwright tests OK against local static web server.
- Explicit `git add -- ...`: succeeded.
- Staged file list: 37 files staged, including memory files, frontend/API/admin/billing/DB/market timing code, tests, docs, config, and tooling.
- Staged stat after initial add: 10,004 insertions and 1,171 deletions.
- Initial `git diff --cached --check`: failed only on extra EOF blank lines in `AGENTS.md`, `.codex/notes/architecture-summary.md`, and `.codex/notes/risk-register.md`.
- EOF blank lines were removed with a docs-only patch and re-staged.
- Final `git diff --cached --check`: passed.
- Final `git diff --check`: passed.
- Final `git status --short --branch`: all checkpoint files are staged; no unstaged tracked/untracked checkpoint residue is visible.
- Final `git diff --name-status`: no unstaged diff output.

### 当前仍然失败的问题

- No validation command is currently failing.
- The previously noted full `/generate` live endpoint smoke quality issue remains: HTTP 200 succeeded, but selected score was `71.6` with 2 quality issues, and score-lift was constrained by live-call cap.
- Real paid-user billing/accounting for `/generate` is still unvalidated because the smoke intentionally used temp DB and no-op billing.

### 当前未完成工作

- No checkpoint commit has been created yet.
- No push or PR has been created.
- No real production DB migration rehearsal, real payment callback/reconciliation, real admin UI smoke, container build/up, or market timing worker/crawler run has been performed.
- No additional live AI endpoint samples have been run after the staged checkpoint validation.

### 当前最高风险

- The staged checkpoint is large and touches high-risk business surfaces: billing, DB schema migration, admin cost views, API contracts, static frontend payloads, deploy config, and market timing worker/crawler.
- The staging area is clean from a Git hygiene perspective, but product risk still requires human review before commit/merge/deploy.
- Production DB startup migrations remain high risk until tested on a safe copy of production-like data.
- Market timing worker and crawler behavior remain high risk and should not be run against production/shared resources without explicit confirmation.

### 下一步最小可行计划

1. Ask user whether to create the checkpoint commit from the current staging area.
2. If approved, commit the staged checkpoint with a clear stabilization message.
3. After commit, do not push or deploy unless separately confirmed.
4. If user wants more review before commit, inspect staged diff by risk group without changing code.
5. For follow-up product quality, investigate the `/generate` score `71.6` smoke result with a new Live API Run Plan before any further real calls.

### 不能在未经确认的情况下修改

- Any staged business code after this checkpoint-prep point unless the user asks for a fix.
- Any commit, push, branch operation, PR, deploy, Docker service startup, crawler/worker run, DB migration/seed/reset/cleanup, payment/email/SMS operation, or production config change.
- Any additional live external AI/API call without a fresh Live API Run Plan.
- `.env`, `model/.env`, secrets/tokens/API keys, local DBs, raw runtime logs, and raw probe artifacts.

## 2026-07-03 Execution Update - Risk Group Diff Review and Checkpoint Scope

### 本轮完成了什么

- Completed the requested risk-group review of the current large diff after the controlled full `/generate` endpoint smoke.
- Confirmed there are no deleted tracked files in the current diff.
- Grouped the checkpoint surface into frontend/UI, API/AI quality chain, billing/DB/admin, market timing/crawler, deploy/config, tests, docs/memory, and local artifact exclusions.
- Confirmed the two raw JSON artifacts previously discussed are now ignored and no longer appear as untracked checkpoint candidates.
- Prepared a safe checkpoint scope recommendation without staging, committing, running migrations, running crawlers, running deploys, or printing secret values.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded this review stage, commands, grouped findings, checkpoint inclusion/exclusion advice, remaining risks, and next plan per user instruction.

### 关键决策

- Recommend treating the current diff as one integrated stabilization checkpoint rather than cherry-picking only isolated files, because frontend payloads, backend Pydantic models, billing response shapes, tests, docs, and deployment config are tightly coupled.
- Explicitly exclude local runtime/probe artifacts from any checkpoint: `model/data/crawler_log.json`, `quality/billing_probe_*.json`, local DB files, local `.env`, Playwright reports/results, cache files, logs, and generated model/data artifacts.
- Mark billing/DB/admin, market timing worker/crawler, deployment config, and live AI endpoint behavior as high-risk areas that should not be modified further or run in production-like mode without confirmation.
- Treat the full `/generate` endpoint live smoke as proof that the endpoint can return HTTP 200 through the real provider chain under a temp DB/no-op billing strategy, not as proof of real paid-user accounting.

### 运行了哪些命令

- `git status --short --branch`
- `git diff --name-status`
- `git diff --numstat`
- `git diff --stat`
- `git ls-files --others --exclude-standard`
- `git diff --unified=0 -- model/api.py`
- `git diff --unified=0 -- model/billing.py model/db.py model/admin_server.py`
- `git diff --unified=0 -- model/hot_keywords.py model/scheduler_a.py model/crawler_config.json`
- `git diff --unified=0 -- NoteAI_Pro_Demo_Framer.html model/admin.html`
- `git diff -- package.json`
- `git diff -- Dockerfile docker-compose.yml scripts/docker_entrypoint.sh start_all.sh model/requirements.txt tools/production_readiness_gate.py`
- `rg -n "^(def|async def|class) " model/market_timing_worker.py tools/pricing_cost_model.py tests/test_billing_token_cost.py tests/test_frontend_report_static.py tests/test_market_timing_keyword_quality.py`
- `rg -n "^(test|import|from|describe|it|const|async function|function)" tests/e2e/content-intent.spec.js playwright.config.js`
- `git diff --name-only --diff-filter=D`
- `sed -n '1,220p' .codex/handoffs/current-task.md`
- `sed -n '1,160p' model/market_timing_worker.py`
- `sed -n '1,180p' tools/pricing_cost_model.py`
- `sed -n '1,140p' tests/e2e/content-intent.spec.js`
- `tail -n 260 .codex/handoffs/current-task.md`
- `wc -l .codex/handoffs/current-task.md`
- `rg -n "(class .*Input|class .*Response|def _normalize|def _content_intent|def _maybe_enrich|def _run_.*pipeline|def _generate|def generate|def analyze|@app\\.post|@app\\.get|check_and_deduct|refund_operation_charge|record_model_usage|_health_model_label)" model/api.py`
- `rg -n "(def check_and_deduct|def refund_operation_charge|def record_model_usage|def get_quota_status|def purchase_credit_package|def grant_credits|def topup_credits|TIERS|OPERATIONS|CREDIT_PACKAGES|used_monthly_credits|actual_model_cost|payment_ref)" model/billing.py model/db.py model/admin_server.py`
- `rg -n "(def ensure_fresh|def sync_|def import_|def export_|def compute_market_timing|def db_status|def clean_scraped|def scrape_once|NOTEAI_|AUTHORIZED|CLOUD|upsert_keywords|write_keyword_snapshot)" model/hot_keywords.py model/scheduler_a.py model/market_timing_worker.py`
- `rg -n "(content_intent|merchant_visibility|fact_source_policy|user_constraints|generate/stream|analyze/stream|billing|credits|pricing|monthly_credits|live3d|renderReport|loadBillingPlan|getContentIntentPayload|shouldAskMerchantBeforeRun)" NoteAI_Pro_Demo_Framer.html model/admin.html`
- `git diff -- .gitignore docs/DEPLOYMENT_SECRETS.md docs/REAL_CHAIN_QUALITY_STABILIZATION_PLAN.md docs/CONTENT_INTENT_FACT_SOURCE_EXECUTION_PLAN.md docs/MARKET_TIMING_CLOUD_PIPELINE.md docs/PRICING_COST_MODEL.md`
- `rg -n "(SECRET|TOKEN|KEY|PASSWORD|DATABASE|API|NOTEAI_|AMAP|MEITUAN|ANTHROPIC|MOONSHOT|KIMI)" model/.env.example docs/DEPLOYMENT_SECRETS.md docs/MARKET_TIMING_CLOUD_PIPELINE.md docs/PRICING_COST_MODEL.md docs/CONTENT_INTENT_FACT_SOURCE_EXECUTION_PLAN.md docs/REAL_CHAIN_QUALITY_STABILIZATION_PLAN.md`
- `git diff -- model/.env.example`
- `git diff --check`
- `git status --short --branch`
- `sed -n '1,180p' .codex/handoffs/current-task.md`

### 每个命令的结果

- Git status still shows the same broad dirty worktree on branch `codex/quality-stabilization-real-chain`; nothing is staged or committed.
- Tracked diff: 23 modified files, about 7,445 insertions and 1,171 deletions.
- Untracked checkpoint candidates remain: project memory files, new docs, `model/market_timing_worker.py`, Playwright config/e2e tests, new unit tests, and `tools/pricing_cost_model.py`.
- No tracked deletions were found.
- Frontend/admin diff is large and coupled to backend response contracts: content intent controls, user constraints propagation, report rendering, live progress UI, pricing/monthly credits, token display, and admin usage/cost surfaces.
- API diff is the largest risk area: `/health` label, analyze/generate/stream/chat models, content intent/fact-source routing, user constraint contracts, market timing integration, quality issue filtering, Kimi usage recording, refund paths, and response shape additions.
- Billing/DB/admin diff is revenue/data critical: monthly credit tiers, mixed monthly+wallet deduction, paid top-up vs gift separation, refund restoration, token/model usage aggregation, and idempotent SQLite column additions.
- Market timing/crawler diff is operationally risky: cloud snapshot import/export, authorized trend source, freshness gate, keyword quality filtering, independent worker, crawler/search discovery tuning, and one tracked timestamp in `model/crawler_config.json`.
- Deploy/config diff adds Playwright runtime dependency, Docker Chromium install, trends worker service, entrypoint skip flag for worker, local frontend service startup, new readiness checks, and env template names/placeholders.
- Test/tooling diff adds Playwright scripts/config/e2e tests plus unit tests for API contracts, billing token cost, frontend static behavior, and market timing quality.
- Docs diff records deployment secrets names/placeholders, market timing cloud pipeline, pricing cost model, and quality stabilization state; no real secret values were reviewed or output.
- Final `git diff --check` passed with no whitespace errors.
- Final status remains dirty with the reviewed diff; nothing is staged or committed.
- Handoff top section now contains this risk review and checkpoint scope.

### 当前仍然失败的问题

- No diff-review command failed.
- The earlier full `/generate` live endpoint smoke returned HTTP 200, but its selected score was `71.6`, below the usual `72` target, with 2 quality issues; later score-lift attempts were blocked by the live-call cap before external calls.
- The full endpoint smoke used temp DB, dependency override, and no-op billing, so real paid-user accounting remains unvalidated.
- No real admin UI smoke, real payment flow, production DB migration rehearsal, container build/up, crawler worker run, or production deployment check has been executed in this stage.

### 当前未完成工作

- Nothing has been staged or committed.
- No final checkpoint has been created.
- Real paid-user `/generate` accounting is still not validated because the smoke intentionally bypassed auth/billing writes.
- Market timing worker/crawler has not been run in this stage and should remain blocked without confirmation.
- Production deployment resource configuration, object storage trend snapshot hosting, and authorized trend source availability remain unconfirmed.

### 当前最高风险

- Highest: broad uncommitted diff across business-critical billing/DB/admin, API contracts, frontend payloads, and deployment config.
- High: frontend static HTML and FastAPI models can drift because contracts are hand-maintained.
- High: SQLite idempotent migrations mutate DB on app startup; production migration behavior has not been rehearsed on a safe copy.
- High: market timing worker can crawl external sites, write DB/snapshot files, and upload snapshots if configured.
- High: billing top-up/package naming currently models test/demo purchase flows but no real gateway callback/reconciliation is confirmed.
- Medium/high: Docker Compose config is valid, but container build/up was not run in this stage.

### 下一步最小可行计划

1. If user approves checkpointing, prepare an explicit staging list grouped by scope before running `git add`.
2. Stage only reviewed project files and keep ignored/local artifacts out.
3. Run a final no-side-effect validation bundle before commit: `git diff --check`, full unit tests, py_compile, quality gate, production readiness gate, Docker Compose config, and Playwright e2e.
4. Do not run additional live AI endpoint samples unless a new Live API Run Plan is approved.
5. After validation, create one checkpoint commit for the integrated stabilization state, or split only if the user explicitly prefers a multi-commit checkpoint.

### 建议 checkpoint scope

- Include core frontend/API/admin/billing/DB/market timing code: `NoteAI_Pro_Demo_Framer.html`, `model/admin.html`, `model/api.py`, `model/model_router.py`, `model/billing.py`, `model/db.py`, `model/admin_server.py`, `model/hot_keywords.py`, `model/scheduler_a.py`, `model/market_timing_worker.py`, `model/crawler_config.json`.
- Include tests/tooling that protect the behavior: `tests/test_api_contracts.py`, `tests/test_billing_token_cost.py`, `tests/test_frontend_report_static.py`, `tests/test_market_timing_keyword_quality.py`, `tests/e2e/content-intent.spec.js`, `playwright.config.js`, `package.json`, `package-lock.json`, `tools/pricing_cost_model.py`, `tools/production_readiness_gate.py`.
- Include deploy/config/docs/memory: `.gitignore`, `Dockerfile`, `docker-compose.yml`, `scripts/docker_entrypoint.sh`, `start_all.sh`, `model/.env.example`, `model/requirements.txt`, `AGENTS.md`, `.codex/handoffs/current-task.md`, `.codex/notes/architecture-summary.md`, `.codex/notes/risk-register.md`, `docs/DEPLOYMENT_SECRETS.md`, `docs/REAL_CHAIN_QUALITY_STABILIZATION_PLAN.md`, `docs/CONTENT_INTENT_FACT_SOURCE_EXECUTION_PLAN.md`, `docs/MARKET_TIMING_CLOUD_PIPELINE.md`, `docs/PRICING_COST_MODEL.md`.
- Exclude ignored/local/runtime/probe artifacts: `.env`, `model/.env`, `model/data/*.db`, `model/data/crawler_log.json`, `model/data/xhs_*.json`, `quality/billing_probe_*.json`, Playwright reports/results, caches, logs, and any generated model/data artifact not explicitly reviewed.

### 不能在未经确认的情况下修改

- Any auth/session/password/token logic.
- Any further billing/payment/quota/refund/cost behavior.
- Any DB schema, local DB files, migrations, reset, seed, or cleanup.
- Any crawler, trend worker, upload, external fact-source, or production-like market timing run.
- Any deploy, Docker service startup, production config, GitHub secret, object storage, payment, email, SMS, or production write operation.
- Any additional live AI run that exceeds the approved smoke scope or lacks a fresh Live API Run Plan.
- Any staging/commit/push action.

## 2026-07-03 Execution Update - Health Label Stabilization

### 本轮完成了什么

- Completed takeover implementation stage after user approval.
- Fixed the misleading `/health` model label without changing diagnosis, generation, chat, billing, auth, DB schema, payment, crawler, or deployment behavior.
- `/health` now reports `v0.4-composite` when local V0.4 composite report and regressor artifact are production-ready and present; it falls back to `legacy_score_model` when V0.4 is disabled, not deployable, missing, or unreadable.
- Added contract tests for both the V0.4-ready health label and legacy fallback.
- Ran offline/mock validation only. No live external AI API calls were made.
- Confirmed two untracked JSON artifacts should not enter a commit plan without further user approval:
  - `model/data/crawler_log.json` appears to be a local crawler runtime log.
  - `quality/billing_probe_ai_diagnosis_20260629.json` contains billing/usage/credits/diagnosis-style probe fields and should be treated as sensitive operational output unless converted into a sanitized fixture/summary.

### 修改了哪些文件

- `model/api.py`
- `tests/test_api_contracts.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/api.py`: Added a small local-only `_health_model_label()` helper and wired `/health` to it, replacing the hard-coded `legacy_score_model` label. The helper reads only local report/artifact state and does not load the model, download artifacts, call providers, or mutate data.
- `tests/test_api_contracts.py`: Added two health contract tests using temporary files to verify `v0.4-composite` and `legacy_score_model` labels without relying on real artifacts or external APIs.
- `.codex/handoffs/current-task.md`: Recorded this stage's changes, decisions, commands, results, remaining gaps, risks, and next plan per user instruction.

### 关键决策

- Treat `/health` as observability/ops surface, not business behavior. No diagnosis/generation/billing logic was changed.
- Avoid calling `get_v04_composite_model()` from `/health` because it can load model artifacts and may trigger artifact ensure/download behavior depending on environment.
- Use only local V0.4 train report gate, `do_not_deploy`, and regressor file presence for health label reporting.
- Keep raw local runtime/probe JSON files out of any commit plan until the user explicitly decides whether to ignore, sanitize, rename, or fixture them.

### 运行了哪些命令

- `git diff --check`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_health_reports_local_v04_composite_model_label tests.test_api_contracts.ApiContractTests.test_health_falls_back_to_legacy_model_label_when_v04_is_not_ready`
- `bash -n scripts/docker_entrypoint.sh`
- `bash -n scripts/push_remote.sh`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest tests.test_billing_token_cost`
- `.venv/bin/python -m unittest tests.test_market_timing_keyword_quality`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `find model tools tests -name '*.py' -print0 | xargs -0 .venv/bin/python -m py_compile && .venv/bin/python -m py_compile scripts/fetch_model_artifacts.py`
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`
- `.venv/bin/python tools/production_readiness_gate.py`
- `docker compose config --quiet`
- `npm run test:e2e`
- `git status --short --branch`

### 每个命令的结果

- `git diff --check`: passed with no whitespace errors.
- Targeted health tests: passed, 2 tests OK.
- `bash -n scripts/docker_entrypoint.sh`: passed.
- `bash -n scripts/push_remote.sh`: passed.
- `tests.test_api_contracts`: passed, 127 tests OK.
- `tests.test_frontend_report_static`: passed, 7 tests OK.
- `tests.test_billing_token_cost`: passed, 13 tests OK.
- `tests.test_market_timing_keyword_quality`: passed, 8 tests OK; emitted existing sqlite `ResourceWarning` messages but no test failures.
- Full unittest discovery: passed, 225 tests OK.
- Python `py_compile`: passed.
- `quality_gate.py quality/golden_notes.sample.json`: passed; expected failing sample remained `EXPECTED_FAIL` as designed.
- `production_readiness_gate.py`: passed, `production_readiness=PASS`, 47 checks, 0 failed.
- `docker compose config --quiet`: passed.
- `npm run test:e2e`: passed, 3 Playwright tests OK against local static server; no live AI API.
- `git status --short --branch`: still shows the large pre-existing uncommitted diff plus this stage's modifications; nothing staged or committed.

### 当前仍然失败的问题

- No command failed in this stage.
- Existing non-failing warning: `tests.test_market_timing_keyword_quality` emits sqlite `ResourceWarning` messages under the local Python runtime.

### 当前未完成工作

- No commit/staging has been performed.
- Full endpoint-level Claude/Kimi four-direction content quality smoke is still not run; a later minimal live `content_gen` route smoke has passed for all four directions.
- Live OCR/video/fact-source/market-timing external-provider validation is still not run.
- The two untracked runtime/probe JSON artifacts still need a user decision: ignore, delete later, sanitize, rename as sample, or convert to fixtures.
- Payment gateway/order/callback/reconciliation remains unconfirmed.
- Production deployment platform and Git LFS/object storage behavior still need confirmation.

### 当前最高风险

- The worktree still has a very large uncommitted diff across frontend, API, billing, DB migration code, admin, deployment, tests, docs, and local artifacts.
- Billing and DB schema areas remain revenue/data critical and were intentionally not changed in this stage.
- Future live API validation can incur real provider cost and may write local runtime logs unless explicitly controlled.

### 下一步最小可行计划

1. Review the large diff by risk group before any staging.
2. Decide what to do with `model/data/crawler_log.json` and `quality/billing_probe_ai_diagnosis_20260629.json`.
3. If user approves, prepare a Live API Run Plan for a 1-3 sample, max 10-call, no-production-write four-direction smoke.
4. After live smoke, summarize provider/model counts, success/failure, sanitized errors, generated files/logs, and smallest follow-up fixes.
5. Only after explicit user approval, stage intentionally and create a checkpoint commit.

### 不能在未经确认的情况下修改

- `.env`, `model/.env`, secret/token/API key values, production environment variables.
- `model/db.py`, local DB files, DB schema/migration/reset/seed/data cleanup.
- `model/auth.py`, `model/admin_auth.py`, auth/session/token/password logic.
- `model/billing.py`, billing/payment/quota/top-up/refund/cost logic.
- `model/admin_server.py` admin adjustment/model deploy/train/crawler mutation endpoints.
- Docker/deploy scripts, GitHub secrets, production deployment settings.
- Model artifacts, model registry, Git LFS release artifacts.
- Crawler/market timing worker writes or external trend/crawler runs.
- Any live external AI/API run beyond the approved Live API Run Plan.
- Any generated local artifact unless the user confirms it belongs in Git.

## 2026-07-03 Execution Update - Local Artifact Ignore Rules

### 本轮完成了什么

- Implemented the approved handling for two local JSON artifacts.
- Kept both local files on disk and did not delete, sanitize, rename, stage, or commit them.
- Added precise ignore rules so the raw runtime/probe artifacts do not accidentally enter a future checkpoint.
- Verified both ignore rules with `git check-ignore`.

### 修改了哪些文件

- `.gitignore`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.gitignore`: Added `model/data/crawler_log.json` for local crawler runtime logs and `quality/billing_probe_*.json` for billing/diagnosis probe outputs.
- `.codex/handoffs/current-task.md`: Recorded this stage's artifact decision, commands, results, remaining risks, and next plan per user instruction.

### 关键决策

- Do not commit raw `model/data/crawler_log.json`; treat it as local runtime state.
- Do not commit raw `quality/billing_probe_ai_diagnosis_20260629.json`; treat it as sensitive operational/probe output because its schema contains billing, credits, transactions, usage, token, cost, model, and diagnosis fields.
- Do not delete either file during this stage.
- If evidence is needed later, create a sanitized summary or explicit sample fixture rather than committing raw JSON.

### 运行了哪些命令

- `git check-ignore -v model/data/crawler_log.json quality/billing_probe_ai_diagnosis_20260629.json`
- `git diff --check`
- `git status --short --branch`
- `git diff -- .gitignore`

### 每个命令的结果

- `git check-ignore -v ...`: passed; `model/data/crawler_log.json` matched `.gitignore` line for `model/data/crawler_log.json`; `quality/billing_probe_ai_diagnosis_20260629.json` matched `.gitignore` line for `quality/billing_probe_*.json`.
- `git diff --check`: passed with no whitespace errors.
- `git status --short --branch`: the two JSON files no longer appear as untracked; the pre-existing large uncommitted diff remains.
- `git diff -- .gitignore`: confirmed the two new ignore rules are present. The file also still includes prior Playwright report/result ignore changes from the existing uncommitted diff.

### 当前仍然失败的问题

- No command failed in this stage.

### 当前未完成工作

- No sanitized sample/fixture was created for either JSON artifact.
- No live API validation has been run.
- No staging or commit has been performed.
- The large pre-existing uncommitted diff still needs deliberate review before checkpointing.

### 当前最高风险

- The worktree still contains a broad uncommitted diff across high-risk areas. The ignore rules reduce artifact commit risk but do not reduce the need for grouped review.

### 下一步最小可行计划

1. Review current diff by risk group and confirm intended checkpoint scope.
2. If desired, prepare a sanitized sample/summary for the billing probe without raw user/usage/cost/provider details.
3. Prepare a Live API Run Plan before any real Claude/Kimi/Amap/Meituan validation.
4. Only after explicit approval, stage files intentionally and create a checkpoint commit.

### 不能在未经确认的情况下修改

- Raw local artifact contents or deletion of `model/data/crawler_log.json` and `quality/billing_probe_ai_diagnosis_20260629.json`.
- `.env`, `model/.env`, secret/token/API key values, production environment variables.
- Billing/payment/quota/refund/cost logic.
- DB schema, migrations, local DB files, reset/seed/cleanup.
- Auth/admin auth/session/password/token logic.
- Deployment settings, model artifacts/registry, crawler/market timing worker writes.
- Any live external API run beyond an approved Live API Run Plan.

## 2026-07-03 Execution Update - Controlled Live API Smoke

### 本轮完成了什么

- Executed the approved first controlled live API smoke after outputting a Live API Run Plan.
- Verified the real `content_gen` model route works for all four creation directions with synthetic input.
- Kept the smoke deliberately below full endpoint/e2e scope: no API server, no FastAPI endpoint, no auth, no billing deduction, no DB writes, no file writes, no crawler, no payment, no deploy.
- Monkey-patched the model router usage recorder in the one-off smoke script so provider token callbacks did not import billing/DB or write usage rows.
- Actual live calls stayed under the approved cap: 4 external model calls total.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the Live API Run Plan, actual result summary, command result, remaining gaps, risks, and next plan per user instruction.

### 关键决策

- Did not run the full `/generate` endpoint because it requires logged-in user billing and can write local SQLite usage/state.
- Did not run the full multi-agent generation pipeline because one sample can trigger multiple agent, candidate, semantic, and repair provider calls and could approach/exceed the 10-call cap.
- Used a minimal direct `model_router.call("content_gen", ...)` smoke to validate provider availability and direction-sensitive prompt behavior with predictable call count.
- Used synthetic restaurant input only; no real user data.
- Did not print raw provider responses; only printed summarized title/body lengths, route attempts, and string-level red-flag checks.

### Live API Run Plan 实际执行范围

- Purpose: low-cost smoke for live provider route and four creation direction behavior.
- Directions: `真实种草型`, `决策转化型`, `测评避坑型`, `清单攻略型`.
- Primary provider/model: Anthropic Claude `claude-haiku-4-5-20251001` via `content_gen`.
- Fallback provider/model: Moonshot/Kimi `kimi-k2.5`, allowed only if primary failed.
- Retry policy: same-model retries disabled via `NOTEAI_MODEL_RETRY_ATTEMPTS=1`; sequential execution only.
- Expected cap: 4 primary calls, at most 8 total if fallback was needed.
- Input: synthetic food/local-life sample; no real user data.
- Writes: no intended DB/file writes; model usage recorder disabled in script.
- Production impact: none; no service startup, deploy, payment, email, SMS, crawler, or production write.

### Live API Result Summary

- Actual provider/model: Anthropic Claude `claude-haiku-4-5-20251001`.
- Actual call count: 4 calls total.
- Fallbacks: none; Moonshot/Kimi was configured but not used.
- Same-model retries: none.
- Success/failure:
  - `真实种草型`: success; title/body returned; no string-level red flags.
  - `决策转化型`: success; title/body returned; string-level scan found `营业时间`.
  - `测评避坑型`: success; title/body returned; string-level scan found `营业时间`.
  - `清单攻略型`: success; title/body returned; no string-level red flags.
- Error summary: no provider errors.
- Generated files/logs: no files intentionally generated; only terminal output.
- Real chain finding: live Claude route is reachable and returns structured output for all four directions. The two `营业时间` mentions need human/follow-up inspection in a full endpoint smoke because the summary-only scan cannot distinguish safe "needs confirmation" wording from unwanted fact injection.

### 运行了哪些命令

- One-off `.venv/bin/python - <<'PY' ... PY` live smoke script using `model_router.call("content_gen", ...)`.
- `git status --short --branch`
- `git diff --check`

### 每个命令的结果

- Live smoke script: passed; 4/4 directions returned structured summaries; actual calls were 4 Claude Haiku calls, 0 fallback, 0 retries.
- `git status --short --branch`: no new untracked artifacts appeared after the live smoke; pre-existing large uncommitted diff remains.
- `git diff --check`: passed with no whitespace errors.

### 当前仍然失败的问题

- No command failed in this stage.
- The `营业时间` red-flag mentions in two live outputs remain a follow-up quality review item, not a confirmed bug yet.

### 当前未完成工作

- Full `/generate` or `/generate/stream` endpoint smoke is not run.
- Full multi-agent generation pipeline live smoke is not run.
- Full `/analyze` live diagnosis, chat optimization, OCR/video, Amap/Meituan fact-source, and market timing live validation are not run.
- No staging or commit has been performed.

### 当前最高风险

- The first live smoke proves provider reachability, not full SaaS endpoint correctness.
- Full endpoint validation will touch billing/auth/local DB unless carefully isolated with a test user/test DB plan.
- The large uncommitted diff remains the biggest project management risk.

### 下一步最小可行计划

1. Decide whether to run a second Live API Run Plan for one full endpoint-level `/generate` smoke using a controlled local test user/test DB strategy.
2. If not running more live API now, review diff by risk group and prepare an intentional checkpoint scope.
3. Keep billing, DB schema, auth, admin, crawler, deploy, and payment untouched unless the next plan explicitly requires them and user approves.

### 不能在未经确认的情况下修改

- Any live API run beyond the already executed 4-call smoke.
- Any full endpoint smoke that writes local DB/auth/billing records.
- Billing/payment/quota/refund/cost logic.
- DB schema/migrations or local DB cleanup/reset/seed.
- Auth/admin auth/session/password/token logic.
- Production env/config, deployment, crawler/worker writes, external fact-source writes.
- Raw provider outputs beyond sanitized summaries.

## 2026-07-03 Execution Update - Full `/generate` Endpoint Smoke

### 本轮完成了什么

- Executed a controlled full FastAPI `/generate` endpoint smoke through `TestClient`.
- Used a synthetic test user and a temporary SQLite DB strategy so the endpoint could pass auth/billing gates without using the repo's persistent `model/data/noteai.db` for user/billing writes.
- Confirmed `/generate` returned HTTP 200 and a valid `GenerateResponse` for a synthetic `清单攻略型` food/local-life prompt.
- Confirmed fact source routing respected the request: `fact_source_policy=skip`, `merchant_visibility=hide`, and `fact_source_decision.enabled=false`.
- Confirmed the smoke produced no new repo files and did not stage or commit anything.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the full endpoint Live API Run Plan, actual results, command results, call cap behavior, remaining issues, and next plan.

### 关键决策

- Used `TestClient` instead of starting local API/admin/frontend services.
- Created a temporary copy of `model/db.py` in a system temp directory with `_DB_PATH` pointed at a temporary SQLite file, then put that directory first in `sys.path` before importing `api`.
- Inserted only one synthetic test user into the temporary DB.
- Overrode `api._auth.get_current_user` to return the synthetic test user.
- Replaced billing charge/subscription/refund/model-usage functions with no-op/test returns for the smoke.
- Disabled local market timing for this smoke by replacing `_compute_market_timing_for_delivery` with a no-op; market timing live validation remains separate.
- Set `NOTEAI_MULTI_CANDIDATE=0`, `NOTEAI_GENERATION_CANDIDATE_COUNT=1`, and `NOTEAI_MODEL_RETRY_ATTEMPTS=1` to control provider calls.
- Added a live call cap wrapper. Provider calls were allowed until the cap; later score-lift attempts were blocked by the wrapper.

### Live API Run Plan 实际执行范围

- Endpoint: `POST /generate` via FastAPI `TestClient`.
- Input: one synthetic `美食` / `清单攻略型` prompt with virtual restaurant materials and explicit "do not invent facts" constraints.
- No image, no video, no crawler, no external fact-source lookup.
- Intended provider scope:
  - `content_gen`: Claude Haiku primary, Kimi fallback if needed.
  - `arbitrate`: Claude Sonnet primary, Claude Haiku fallback if needed.
  - semantic scoring: Claude Haiku sync call.
- Same-model retries disabled.
- No production DB, no persistent repo DB user/billing writes, no deploy, no payment, no email/SMS.

### Live API Result Summary

- HTTP status: 200.
- Actual result: response model was valid.
- Actual model label from endpoint: `claude-routed-5-agents`.
- Response summary:
  - `content_intent`: `清单攻略型`
  - `grade`: `良好`
  - `ces_percentile`: `71.6`
  - `quality_issue_count`: `2`
  - `red_flags`: none from the configured string scan.
  - `fact_source_decision.enabled`: `false`
  - `fact_source_decision.reason`: `user_or_ui_skipped_fact_source`
- Actual provider behavior:
  - Full endpoint triggered the expected multi-stage pipeline: P2 content/growth/user agents, P3 Sonnet arbitration, P4 semantic scoring and refinement.
  - The one-sample endpoint path is much heavier than the minimal route smoke.
  - The cap wrapper blocked a later score-lift attempt with `live call cap exceeded (9)`.
  - Endpoint still returned 200 by selecting the best available candidate before the blocked score-lift.
- Actual writes:
  - Temporary DB rows: `users=1`, `usage_records=0`, `credit_transactions=0`.
  - No repo files intentionally generated.

### 运行了哪些命令

- One-off `.venv/bin/python - <<'PY' ... PY` script that:
  - created a temp DB module/path,
  - imported `api`,
  - used FastAPI `TestClient`,
  - called `POST /generate`,
  - summarized response and call behavior.
- `git status --short --branch`
- `git diff --check`
- `git diff --stat`

### 每个命令的结果

- Full endpoint smoke script: completed with exit code 0 and HTTP 200.
- `git status --short --branch`: no new untracked files from the smoke; pre-existing large uncommitted diff remains.
- `git diff --check`: passed with no whitespace errors.
- `git diff --stat`: now shows tracked diff of 23 files, `7445 insertions(+), 1171 deletions(-)`; this includes pre-existing large changes plus current thread edits.

### 当前仍然失败的问题

- No command failed.
- The endpoint returned a score of `71.6`, slightly below the nominal 72 delivery target, with 2 quality issues. This should be reviewed before treating the endpoint as fully production-ready for this scenario.
- The score-lift stage attempted to continue beyond the live call cap and was blocked by the smoke wrapper. That is expected for this controlled run, but it proves full endpoint live validation can become expensive quickly.

### 当前未完成工作

- No second endpoint sample was run.
- `/generate/stream`, `/analyze`, chat optimization, OCR/video, Amap/Meituan fact-source, and market timing live validations are still not run.
- No code change was made in response to the 71.6 score or quality issues.
- No staging or commit has been performed.

### 当前最高风险

- Full `/generate` endpoint can trigger many provider calls through P2/P3/P4/refinement/score-lift. Cost control requires explicit call caps and small sample sizes.
- The large worktree diff remains broad and high-risk.
- Billing/DB/auth were safely bypassed for this smoke, so this smoke does not validate real paid-user accounting.

### 下一步最小可行计划

1. Do a risk-group review of the current large diff and prepare a checkpoint scope.
2. Do not run more live endpoint samples until another Live API Run Plan is approved.
3. If further endpoint live validation is needed, decide whether to accept billing/test DB writes or keep no-op billing isolation.

### 不能在未经确认的情况下修改

- More live API endpoint samples or any run that could exceed 10 provider calls.
- Billing/payment/quota/refund/cost logic.
- DB schema/migrations, persistent DB files, reset/seed/cleanup.
- Auth/admin auth/session/password/token logic.
- Deployment, crawler/worker, external fact-source, payment/email/SMS operations.
- Raw provider outputs beyond sanitized summaries.

## Original Goal

Build NoteAI Pro into a commercially valuable full-stack SaaS for Xiaohongshu/RedNote creators. The core value is high-quality AI diagnosis and explosive post generation across multiple industries, using Claude as the main reasoning/generation brain, Kimi/Moonshot for vision/OCR and secondary review where configured, V0.4 composite quality models, fact enrichment, creator memory, admin cost accounting, and transparent credit billing.

The most recent business focus before this handoff was stabilizing the "content intent / creation direction" feature: 真实种草型, 决策转化型, 测评避坑型, 清单攻略型, plus merchant/brand visibility strategy, so AI diagnosis, generation, and chat optimization do not blindly inject fake store facts or template phrases.

The current user instruction is to stop feature implementation and create sustainable engineering memory files.

## Current Status

### 已完成

- Repo inspection completed without reading or printing `.env` values.
- Git repo confirmed at `/Users/openclaw/Desktop/noteai`.
- Current branch confirmed: `codex/quality-stabilization-real-chain`.
- Large uncommitted diff confirmed.
- Local services were previously started and verified:
  - API: `http://127.0.0.1:8000/health`
  - Admin: `http://127.0.0.1:8001/admin/health`
  - Static frontend: `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html`
- `start_all.sh` was previously changed to load `model/.env` through `python-dotenv`, start API/admin/frontend, and avoid unsafe shell export of env values.
- Playwright e2e environment was previously installed and configured.
- `npm run test:e2e` passed with 3 tests for content intent UI and payload behavior.
- Targeted backend/frontend tests for content intent/fact routing previously passed.
- V0.4 model load was previously checked by calling API internals; V0.4 composite model loaded with 124 feature columns and deployment gate passed. `/health` has now been updated to report local V0.4 readiness instead of a hard-coded legacy label.

### 进行中

- Engineering memory system creation:
  - `AGENTS.md`
  - `.codex/handoffs/current-task.md`
  - `.codex/notes/architecture-summary.md`
  - `.codex/notes/risk-register.md`

### 未完成

- Full regression suite has not been rerun after all current uncommitted changes.
- Full real Claude/Kimi end-to-end generation for all four creation directions has not been completed in this handoff phase. A minimal 4-call live `content_gen` route smoke did pass for all four directions.
- Full production readiness validation has not been rerun after the latest Playwright changes.
- Payment gateway/order/callback/reconciliation flow is not confirmed as implemented.
- Market timing cloud evidence pipeline still needs production-grade confirmation with fresh authorized/current data.
- The large uncommitted diff has not been checkpoint committed.

### 不确定 / 待确认

- Final production hosting provider is not confirmed.
- Whether Git LFS artifacts will be available on the selected deployment platform is not confirmed.
- Whether official/authorized market timing trend sources are configured in production is not confirmed.
- Whether Meituan travel CLI is installed/configured in target cloud runtime is not confirmed.
- Whether all currently modified files are intended to be part of the next checkpoint is not confirmed.

## Files Touched

This list reflects current Git status during handoff. Some files were modified before this handoff task.

### Frontend

- `NoteAI_Pro_Demo_Framer.html`: major frontend updates for V0.4 homepage, upload flow, content intent/merchant visibility controls, user constraints, 3D-like processing UI, report rendering, pricing/credits display, screenshot OCR gating, diagnosis/generation/chat payload propagation.
- `model/admin.html`: admin UI updates for usage/cost/credit/model/crawler related surfaces.
- `assets/landing/v04-quality-engine.png`: landing asset exists in repo; recently modified before this handoff, exact current diff status not shown as modified.
- `assets/vendor/three.module.min.js`: vendor asset exists; not currently modified in Git status.

### Backend / API

- `model/api.py`: major changes across AI diagnosis, generation, chat optimization, V0.4 composite scoring, multi-agent output, content intent contracts, fact source routing, market timing enforcement, delivery shaping, title/body sanitizers, billing integration.
- `model/admin_server.py`: admin overview/users/revenue/usage/prompts/models/crawler/settings/logs endpoints and admin adjustments.
- `model/model_router.py`: Claude/Kimi routing, retry, timeout, concurrency, usage recording.
- `model/billing.py`: operation credit costs, subscriptions, usage accounting, token/cost calculation, top-up packages.
- `model/hot_keywords.py`: hot keyword DB, market timing freshness, cloud snapshot/authorized trend logic.
- `model/scheduler_a.py`: market timing/crawler scheduling related updates.
- `model/market_timing_worker.py`: new cloud/worker-style market timing collection process.
- `model/fact_enrichment.py`: fact source routing for Amap, Meituan travel, local verified facts, search providers.
- `model/db.py`: SQLite tables and idempotent column migrations for users, sessions, notes, chat, memories, growth, subscriptions, usage, credits, transactions, diagnoses, tracked notes.
- `model/crawler_config.json`: crawler configuration updated.
- `model/data/crawler_log.json`: new local crawler log data; confirm whether this should be committed.

### Database

- `model/db.py`: schema/migration logic modified.
- Local SQLite files under `model/data/*.db` exist and were recently modified but are ignored by `.gitignore`; do not commit DB files.

### Auth / Permission

- `model/auth.py`: current user auth module; no current Git diff shown, but it is high-risk.
- `model/admin_auth.py`: current admin auth module; no current Git diff shown, but it is high-risk.
- `model/admin_server.py`: admin-only endpoints use `Depends(_aauth.get_admin_user)`.

### Config / Deployment

- `.gitignore`: added Playwright reports/results ignore entries.
- `Dockerfile`: updated Docker runtime dependencies/Playwright Chromium installation.
- `docker-compose.yml`: noteai, noteai-admin, and noteai-trends-worker services.
- `scripts/docker_entrypoint.sh`: artifact/startup behavior touched.
- `start_all.sh`: local API/admin/frontend launcher touched.
- `model/.env.example`: env variable template updated; values must not be copied into docs/output.
- `.github/workflows/ci.yml`: existing CI uses Python 3.11, Git LFS, py_compile, unittest discovery, quality gate, production readiness, Docker Compose config. No current Git diff shown for workflow.
- `package.json`: Playwright e2e scripts and dev dependency added.
- `package-lock.json`: changed by prior `npm install --save-dev @playwright/test`.
- `playwright.config.js`: new Playwright config for static frontend e2e tests.

### Tests

- `tests/test_api_contracts.py`: extensive backend contract tests updated.
- `tests/test_frontend_report_static.py`: static frontend assertions updated/new.
- `tests/test_billing_token_cost.py`: new billing/cost tests.
- `tests/test_market_timing_keyword_quality.py`: new market timing keyword quality tests.
- `tests/e2e/content-intent.spec.js`: new Playwright e2e tests for content intent UI/payload.

### Docs

- `docs/REAL_CHAIN_QUALITY_STABILIZATION_PLAN.md`: stabilization plan updated.
- `docs/DEPLOYMENT_SECRETS.md`: deployment secret/variable guidance updated.
- `docs/CONTENT_INTENT_FACT_SOURCE_EXECUTION_PLAN.md`: new plan/status for content intent and fact source execution.
- `docs/MARKET_TIMING_CLOUD_PIPELINE.md`: new market timing pipeline plan.
- `docs/PRICING_COST_MODEL.md`: new pricing/cost model document.
- `tools/pricing_cost_model.py`: new pricing/cost modeling helper.
- `tools/production_readiness_gate.py`: updated readiness checks.
- `quality/billing_probe_ai_diagnosis_20260629.json`: new probe artifact; confirm whether to commit.

## Key Decisions

- Frontend remains a static HTML/CSS/JS page rather than a React/Vue/Next app.
- Backend is FastAPI with raw SQLite; no ORM/migration tool confirmed.
- User auth uses PBKDF2-SHA256 password hashes and SQLite-backed bearer sessions.
- Admin auth is separate from user auth; admin credentials come from environment variables and admin sessions are in memory.
- V0.4 composite model is the production scoring direction; model artifacts and release reports are expected under `model/artifacts/`.
- Claude is the primary text reasoning/generation route; Kimi/Moonshot is used for vision/OCR and fallbacks where configured.
- AI diagnosis, generation, and chat optimization should propagate user constraints and content intent fields.
- Content intent controls:
  - 真实种草型 should avoid forcing merchant facts when no merchant is confirmed.
  - 决策转化型 should require/encourage confirmed merchant/hotel/destination facts before using fact sources.
  - 测评避坑型 should not fabricate negatives without evidence.
  - 清单攻略型 should cover multiple materials/items and avoid only using the first image.
- Fact enrichment strategy:
  - Food/local life uses Amap as the base fact source when a confirmed merchant/store signal exists and the selected intent needs facts.
  - Travel/hotel can use Meituan travel where configured.
  - Other industries default to no external fact source unless a specific safe source is implemented.
- Billing model uses monthly and recharge credits rather than hard per-feature package quotas.
- Video understanding currently records platform cost but does not separately deduct recharge credits unless future UX explicitly confirms it.
- Market timing evidence should be a separate worker/cloud pipeline; API should not silently use stale trend evidence when freshness is required.

## Known Bugs

- `/health` model label was fixed in this thread to report `v0.4-composite` when local V0.4 report/artifact state is ready, with legacy fallback when not ready.
- Full four-direction real Claude/Kimi e2e content quality validation is not complete.
- Current in-app browser had limitations inspecting page global functions; Playwright e2e is now the reliable frontend automation path.
- The repo has a very large uncommitted diff, increasing merge/conflict risk.
- Local DB files changed during testing but are ignored; do not rely on local DB state as canonical.

## Known Risks

- Frontend fields and backend Pydantic models may drift because the frontend is a large static HTML file.
- API response shape may drift across streaming and non-streaming endpoints.
- SQLite schema changes are embedded in runtime code; mistakes can mutate local/production DB on startup.
- Billing credits/cost accounting touches revenue-critical flows and must be regression tested before launch.
- Admin endpoints can adjust subscriptions/credits/users and must remain protected.
- Market timing freshness gate can block core AI flows if cloud snapshots/worker are not configured.
- Fact enrichment may leak placeholder or generic facts into generated copy if routing/sanitizers regress.
- Model artifacts and Git LFS/cloud artifact loading must be verified in the actual deployment platform.
- Package lockfile was changed by adding Playwright; this is intentional from the previous testing task but should be included consciously in a checkpoint.

## Verification Status

### 已运行过的命令

- `./start_all.sh status`
  - Result: API, admin, and frontend were running during previous validation.
- `curl` checks for API/admin/frontend
  - Result: API/admin health and frontend HTML returned successfully.
- `.venv/bin/python -m unittest tests.test_frontend_report_static.FrontendReportStaticTests.test_content_intent_controls_are_real_payload_fields ...`
  - Result: 7 targeted tests passed.
- `npx playwright test --list`
  - Result: 3 e2e tests discovered.
- `npm run test:e2e`
  - Result: 3 Playwright tests passed.
- Playwright screenshot/payload probe for content intent
  - Result: no console errors; payload included `content_intent`, `merchant_visibility`, `merchant_name`, `fact_source_policy`.

### 尚未运行但应该运行的命令

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `python -m py_compile model/*.py`
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`
- `.venv/bin/python tools/production_readiness_gate.py`
- `docker compose config --quiet`
- Full real-chain smoke tests for AI diagnosis, generation, and chat optimization across core industries.

### 当前无法确认 / 未运行原因

- Full real AI quality tests require live third-party APIs and can consume credits/costs.
- Docker/build/deployment checks can be slow and may require explicit confirmation in this handoff stage.
- Database-affecting commands were intentionally not run.

### 需要用户确认后才能运行的命令

- `docker compose up --build`
- Any deploy command or production build/release.
- Any admin adjustment endpoint or billing mutation endpoint.
- Any DB reset/cleanup/migration/seed beyond normal app-owned idempotent startup behavior.
- Any crawler or market timing worker that writes shared data.

## Next Steps

1. 下一步目标：create a checkpoint commit after reviewing the full uncommitted diff.
2. 预计修改文件：none before review; potentially only docs/tests if review finds missing memory.
3. 为什么要改：the diff is large and spans billing, AI generation, frontend, deployment, and tests; checkpointing reduces recovery risk.
4. 风险：committing unintended local artifacts such as crawler logs or billing probes.
5. 验证方式：`git status --short`, `git diff --stat`, targeted tests, full unittest discovery when approved.
6. 是否需要用户确认：yes, before staging/committing.

1. 下一步目标：run full non-destructive validation.
2. 预计修改文件：none unless tests fail and user approves fixes.
3. 为什么要改：confirm the large diff is internally consistent.
4. 风险：full tests may take time; live AI tests may cost money.
5. 验证方式：unittest discovery, py_compile, Playwright e2e, quality gate, production readiness gate, docker compose config.
6. 是否需要用户确认：yes for any live API/costly or Docker/deploy-adjacent checks.

1. 下一步目标：fix misleading `/health` model label.
2. 预计修改文件：`model/api.py`, tests.
3. 为什么要改：avoid confusion about V0.4 loading.
4. 风险：low, but health endpoint is used by Docker/CI and should remain backward compatible.
5. 验证方式：API health unit/smoke test.
6. 是否需要用户确认：yes, because current task forbids further business code changes.

1. 下一步目标：complete real four-direction content quality smoke.
2. 预计修改文件：unknown until results; likely prompts/API/front-end only if defects are found.
3. 为什么要改：prove content intent is not only passed through but improves generated content.
4. 风险：live API cost and quality regressions.
5. 验证方式：record request payloads, fact decisions, final titles/bodies/scores for all four directions.
6. 是否需要用户确认：yes.

## Do Not Touch Without Approval

- `.env`, `model/.env`, any secret/token/API key values.
- `model/db.py` schema and local DB files.
- `model/auth.py`, `model/admin_auth.py`, auth/session/token logic.
- `model/billing.py`, billing/credits/subscription behavior.
- `model/admin_server.py` admin adjustment endpoints.
- `Dockerfile`, `docker-compose.yml`, deployment scripts, GitHub secrets/docs.
- Model artifacts and model registry/release manifest.
- Crawler/market timing worker writes.
- `package-lock.json` unless intentionally handling the Playwright dependency change.
- Any generated local artifacts unless the user confirms they belong in Git.
