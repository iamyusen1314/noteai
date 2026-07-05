# Current Task Handoff

Last updated: 2026-07-05

## 2026-07-05 Execution Update - XHS Sidecar Contract and Admin Visibility

### 本轮完成了什么

- Completed the next stage of the XHS high-availability evidence plan.
- Expanded the XHS-Downloader sidecar adapter contract with detail-path configuration and tolerant payload normalization.
- Added normalized sidecar detail extraction for note id, title, body, likes, saves, comments, and shares.
- Changed sidecar health recording so a sidecar response only counts as valid evidence when it contains content or metrics.
- Added Admin UI cards and tables for XHS freshness, missing domains, daily deadline, sidecar configured state, per-domain ledger, and recent health records.
- Added mocked sidecar success/failure tests; no real sidecar or external URL was called.
- Did not install XHS-Downloader, did not run real crawler/worker, did not access Xiaohongshu, did not call live AI, and did not deploy.

### 修改了哪些文件

- `model/xhs_acquisition.py`
- `model/admin.html`
- `model/.env.example`
- `tests/test_xhs_acquisition.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/xhs_acquisition.py`: Added `normalize_sidecar_detail()`, tolerant note payload traversal, count parsing including `万`, configurable `NOTEAI_XHS_DOWNLOADER_DETAIL_PATH`, and stricter sidecar evidence validity.
- `model/admin.html`: Added crawler page UI for XHS freshness and health monitoring using the existing admin endpoints.
- `model/.env.example`: Added `NOTEAI_XHS_DOWNLOADER_DETAIL_PATH=/xhs/detail`.
- `tests/test_xhs_acquisition.py`: Added mocked HTTP tests for sidecar success normalization and login/risk failure recording.
- `.codex/handoffs/current-task.md`: Recorded this stage per workflow.

### 关键决策

- The adapter does not assume one fixed XHS-Downloader response shape; it accepts common `data`, `note`, `item`, `detail`, `result`, and list wrappers.
- Sidecar calls remain opt-in behind `NOTEAI_XHS_DOWNLOADER_URL`; if not configured, no network call is made.
- Admin UI shows sidecar host/scheme only; it does not show cookies, headers, tokens, raw `.env`, or secret values.
- Empty sidecar success payloads are treated as failed health, not valid evidence.

### 运行了哪些命令

- `.venv/bin/python -m py_compile model/xhs_acquisition.py model/admin_server.py model/api.py model/xhs_health_probe.py`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition`
- `.venv/bin/python -m unittest tests.test_api_contracts tests.test_frontend_report_static`
- `docker compose config --quiet`
- `rg -n "xhs-fresh|xhs-health|loadXhsHealth|admin/xhs|market-timing/freshness|normalize_sidecar|XHSDownloader" ...`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `git diff --check`
- `git status --short`
- `git diff --stat`

### 每个命令的结果

- `py_compile`: passed.
- `tests.test_xhs_acquisition`: passed, 9 tests.
- `tests.test_api_contracts tests.test_frontend_report_static`: passed, 140 tests.
- `docker compose config --quiet`: passed.
- `rg` confirmed new sidecar/admin/API symbols are present in expected files.
- Full unittest discover: passed, 246 tests.
- `git diff --check`: passed.
- Full unittest still prints existing mocked-path API contract logs, including captured Moonshot network/model-router messages; suite result is `OK`.

### 当前仍然失败的问题

- No real sidecar binary/service is installed or configured yet.
- The Admin UI has not been browser-render-smoked in this stage.
- No live sidecar/XHS URL smoke has been performed after adding the adapter contract.

### 当前未完成工作

- Decide whether to install/deploy XHS-Downloader as a sidecar.
- If approved, configure `NOTEAI_XHS_DOWNLOADER_URL` and run one controlled single-URL sidecar smoke.
- Add rendered Admin UI smoke for the new XHS cards.
- Add deadline alert delivery path.

### 当前最高风险

- Sidecar integration is contract-ready but not production-proven until a real service is installed, pinned, and tested.
- Upstream sidecar response shape may differ; normalization is tolerant but must be checked against the real configured version.
- Operational/compliance risk remains: do not add CAPTCHA bypass, account automation, aggressive proxy pools, or high-frequency retries.

### 下一步最小可行计划

1. Run a rendered Admin UI smoke for the new crawler/XHS cards using mocked API responses or local admin server.
2. Prepare sidecar install/deploy options and exact scope for user confirmation.
3. If confirmed, install/configure XHS-Downloader sidecar and run a single live smoke with a Live Crawler Run Plan.

### 不能在未经确认的情况下修改

- Real `.env`, XHS Cookies, production sessions, account automation, external sidecar deployment.
- CAPTCHA solving, proxy pools, aggressive retry/risk-control evasion.
- Production DB, production worker deployment, payment/email/SMS, live AI batch calls.

## 2026-07-05 Execution Update - XHS Health Read APIs and Probe

### 本轮完成了什么

- Added read/query APIs for the XHS freshness and crawler health ledger.
- Added an authenticated user API endpoint for market timing freshness status.
- Added admin-only endpoints for detailed XHS freshness and health diagnostics.
- Added a local CLI probe for cron/monitoring to detect missing XHS evidence before the daily deadline.
- Added sidecar fetch wrapper behavior that records health when `NOTEAI_XHS_DOWNLOADER_URL` is configured or missing; tests cover the not-configured path without network access.
- Did not run real crawler/worker, did not access Xiaohongshu, did not call live AI, did not install/deploy an external sidecar, and did not write production DB.

### 修改了哪些文件

- `model/xhs_acquisition.py`
- `model/xhs_health_probe.py`
- `model/admin_server.py`
- `model/api.py`
- `model/.env.example`
- `tests/test_xhs_acquisition.py`
- `tests/test_api_contracts.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/xhs_acquisition.py`: Added `recent_health()`, `freshness_probe()`, sidecar status redaction, and `fetch_detail_with_sidecar()` that records health without exposing secrets.
- `model/xhs_health_probe.py`: New CLI for cron/monitoring; exits `0` when freshness is satisfied and `2` when any required domain is missing.
- `model/admin_server.py`: Added `/admin/xhs/freshness` and `/admin/xhs/health` with admin auth.
- `model/api.py`: Added authenticated `/market-timing/freshness` endpoint for user/API smoke visibility without exposing internal crawler rows.
- `model/.env.example`: Added `NOTEAI_XHS_FRESHNESS_DEADLINE_HOUR` and `NOTEAI_XHS_FRESHNESS_DEADLINE_MINUTE`.
- `tests/test_xhs_acquisition.py`: Added coverage for recent health, CLI probe, admin handlers, and sidecar-not-configured health recording.
- `tests/test_api_contracts.py`: Added anonymous access guard coverage for `/market-timing/freshness`.
- `.codex/handoffs/current-task.md`: Recorded this stage per workflow.

### 关键决策

- User-facing API only exposes aggregate freshness status; detailed crawler health remains admin-only.
- Sidecar URL status only returns scheme/host/configured state, not secrets, cookies, headers, or raw environment values.
- The CLI probe is read-only except for idempotent ledger table initialization through `hot_keywords.db`.
- External XHS-Downloader/MediaCrawler installation and live sidecar calls remain blocked until separately confirmed.

### 运行了哪些命令

- `.venv/bin/python -m py_compile model/xhs_acquisition.py model/xhs_health_probe.py model/admin_server.py model/api.py`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition tests.test_api_contracts`
- `docker compose config --quiet`
- `git diff --check`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `git status --short`
- `git diff --stat`

### 每个命令的结果

- `py_compile`: passed.
- `tests.test_xhs_acquisition`: passed, 7 tests.
- `tests.test_api_contracts`: passed, 131 tests.
- Combined XHS/API contract run: passed, 138 tests.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.
- Full unittest discover: passed, 244 tests.
- Full unittest still prints existing mocked-path logs from API contract tests, including a captured Moonshot network error and model-router retry log; suite result is `OK`.

### 当前仍然失败的问题

- No real external sidecar is installed or exercised yet.
- No real cloud worker acquisition SLA has been proven yet.
- The system can now see and fail on missing XHS freshness, but secondary/tertiary acquisition still needs implementation and real smoke.

### 当前未完成工作

- Connect a real secondary sidecar behind `NOTEAI_XHS_DOWNLOADER_URL`.
- Add operator/admin UI rendering for the new admin XHS endpoints.
- Add deadline alert delivery path.
- Run one controlled sidecar smoke after a Live Crawler Run Plan.

### 当前最高风险

- Operational risk remains acquisition, not observability: the ledger/probe tells us what is missing, but a configured sidecar/fallback must still obtain the evidence.
- External dependency risk: sidecar contract must be pinned and validated before cloud deployment.
- Compliance risk: do not add CAPTCHA bypass, account automation, aggressive proxies, or high-frequency retries.

### 下一步最小可行计划

1. Add the real sidecar adapter contract tests with mocked HTTP success/failure payloads.
2. Add admin UI cards for freshness, missing domains, last run, and sidecar configured state.
3. If user confirms sidecar installation/deployment scope, install/configure XHS-Downloader separately.
4. Then run one single-URL sidecar live smoke with a Live Crawler Run Plan.

### 不能在未经确认的情况下修改

- Real `.env`, XHS Cookies, production sessions, account automation, or external sidecar deployment.
- CAPTCHA solving, proxy pools, aggressive retry/risk-control evasion.
- Production DB, production worker deployment, payment/email/SMS, live AI batch calls.

## 2026-07-05 Execution Update - XHS Freshness Ledger Hard Gate

### 本轮完成了什么

- Implemented the first execution stage of the final XHS evidence plan.
- Added an XHS acquisition health and freshness ledger layer.
- Connected `market_timing_worker.py` to record real XHS freshness by domain after each scrape.
- Added a production hard gate: when `NOTEAI_XHS_FRESHNESS_REQUIRED=1`, the market timing worker raises `XHS_FRESH_EVIDENCE_UNAVAILABLE` if any core industry lacks real XHS fresh evidence.
- Kept baseline evidence available for local/demo readability, but prevented baseline rows from satisfying the real XHS freshness ledger.
- Added a configurable `XHSDownloaderSidecar` adapter shell for a separately managed XHS-Downloader API service; it is not called unless configured.
- Tightened `hot_keywords.py` sqlite connection handling to avoid unclosed connection warnings as the evidence DB is used more often.
- Did not run real crawler/worker, did not access Xiaohongshu, did not call live AI, did not deploy, and did not write production DB.

### 修改了哪些文件

- `model/xhs_acquisition.py`
- `model/market_timing_worker.py`
- `model/hot_keywords.py`
- `model/.env.example`
- `docker-compose.yml`
- `tests/test_xhs_acquisition.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/xhs_acquisition.py`: New health/freshness ledger module. It creates `xhs_crawler_health` and `xhs_freshness_ledger`, records real XHS evidence by industry, exposes freshness overview/status, and includes a dormant XHS-Downloader sidecar adapter interface.
- `model/market_timing_worker.py`: Records XHS freshness after `scrape_once()` and enforces the production hard gate before generating/exporting a snapshot when required.
- `model/hot_keywords.py`: Added `_db_conn()` so SQLite connections close explicitly across the market timing evidence DB helpers.
- `model/.env.example`: Added `NOTEAI_XHS_FRESHNESS_REQUIRED`, `NOTEAI_XHS_DOWNLOADER_URL`, and `NOTEAI_XHS_DOWNLOADER_TIMEOUT` examples.
- `docker-compose.yml`: Sets `NOTEAI_XHS_FRESHNESS_REQUIRED=${NOTEAI_XHS_FRESHNESS_REQUIRED:-1}` for `noteai-trends-worker`, so production-like worker runs fail loudly if real XHS evidence is missing.
- `tests/test_xhs_acquisition.py`: Added coverage that baseline rows do not satisfy real XHS freshness, real XHS-like scrape rows do satisfy it, and the worker hard gate blocks baseline-only snapshots.
- `.codex/handoffs/current-task.md`: Records this stage per project workflow.

### 关键决策

- Real XHS freshness is now separate from market timing baseline evidence.
- `industry_baseline` can keep local demos and fallback snapshots readable, but it cannot satisfy `xhs_freshness_ledger`.
- The production worker gate happens before snapshot export, so a baseline-only worker run cannot produce a snapshot that appears to satisfy the user's "daily fresh XHS evidence" requirement.
- The XHS-Downloader integration is added as an adapter shell only; installing/running an external sidecar remains a separate confirmed step.
- Did not implement CAPTCHA bypass, proxy rotation, or aggressive retry behavior.

### 运行了哪些命令

- `.venv/bin/python -m py_compile model/xhs_acquisition.py model/market_timing_worker.py`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition`
- `docker compose config --quiet`
- `.venv/bin/python -m unittest tests.test_market_timing_keyword_quality`
- `.venv/bin/python -m unittest tests.test_tracking_performance`
- `.venv/bin/python -m py_compile model/hot_keywords.py model/xhs_acquisition.py model/market_timing_worker.py`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition tests.test_market_timing_keyword_quality`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `git diff --check`
- `git status --short`

### 每个命令的结果

- `py_compile` checks: passed.
- `tests.test_xhs_acquisition`: passed, 4 tests.
- `docker compose config --quiet`: passed.
- `tests.test_market_timing_keyword_quality`: passed, 10 tests.
- `tests.test_tracking_performance`: passed, 4 tests.
- Combined XHS + market timing tests: passed, 14 tests.
- Full unittest discover: passed, 240 tests.
- `git diff --check`: passed.
- Full unittest still prints captured mock-path logs from existing API contract tests, including a Moonshot network error message caught by the test harness; the suite result is `OK`.

### 当前仍然失败的问题

- This stage does not yet install or run XHS-Downloader, MediaCrawler, or any external sidecar.
- This stage does not yet prove a real cloud worker can acquire every core industry daily from Xiaohongshu.
- If `NOTEAI_XHS_FRESHNESS_REQUIRED=1` and the real scrape path returns insufficient XHS evidence, the worker now fails loudly instead of silently exporting a baseline-only snapshot.

### 当前未完成工作

- Implement the real secondary adapter call flow against a vetted XHS-Downloader sidecar after confirming install/deploy scope.
- Add an operator/admin view for `xhs_crawler_health` and `xhs_freshness_ledger`.
- Add deadline-based alerting before the daily evidence window closes.
- Run a controlled real worker smoke with low limits only after a Live Crawler Run Plan.

### 当前最高风险

- Operational SLA risk: the hard gate prevents fake success, but it does not by itself guarantee acquisition. The sidecar/fallback operations layer is still required.
- External dependency risk: XHS-Downloader/MediaCrawler sidecar choices need version pinning, deployment ownership, and maintenance review.
- Compliance risk: do not add CAPTCHA bypass, account abuse automation, or aggressive anti-risk behavior without explicit legal/product review.

### 下一步最小可行计划

1. Add admin/API read endpoints for XHS freshness and crawler health.
2. Add a command-line health probe that reports missing domains before deadline.
3. Integrate a sidecar adapter behind `NOTEAI_XHS_DOWNLOADER_URL`, with tests mocked locally.
4. Only after that, run one controlled sidecar smoke against a single public test URL.

### 不能在未经确认的情况下修改

- Real `.env` secrets, XHS Cookies, production sessions, or account automation.
- External sidecar installation/deployment.
- CAPTCHA solving, proxy pools, or aggressive retry/risk-control evasion.
- Production DB, production worker deployment, payment/email/SMS, or live AI batch calls.

## 2026-07-05 Note - XHS Crawler Feasibility and Stability Requirement

### 本轮完成了什么

- Clarified the production feasibility conclusion after user asked whether it was recorded.
- Recorded that the cloud-deployable infrastructure route is feasible, but stable daily Xiaohongshu evidence acquisition is not guaranteed by the current direct Cookie + selector crawler alone.
- Checked GitHub ecosystem patterns for Xiaohongshu/RedNote crawlers and recorded implementation implications.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Explicitly records the feasibility conclusion, GitHub research direction, and the user's hard requirement that daily fresh XHS evidence must not be treated as optional.

### 关键决策

- The route `Chromium + independent worker + daily schedule + shared DB/snapshot` is considered cloud-deployable infrastructure.
- This is not the same as a guaranteed data-acquisition SLA.
- GitHub projects broadly converge on the same core mechanisms: Playwright or browser-context automation, QR/Cookie login, persistent login state, optional API/server mode, short-link/detail extraction, and health/refresh handling.
- Without an official/authorized data source, no open-source GitHub approach can honestly guarantee 100% daily success against Xiaohongshu because login state, route handling, selectors, short-link resolution, and risk-control pages can change outside our control.
- The user's product requirement is stricter than the current implementation: "daily fresh XHS evidence must not fail." This requires a redundancy design, not just selector patching.

### GitHub evidence reviewed

- `JoeanAmier/XHS-Downloader`: supports XHS detail extraction, short links, Cookie/proxy parameters, API/MCP/server modes, Docker usage, and documents Cookie impact.
- `NanmiCoder/MediaCrawler`: uses Playwright/CDP/browser login patterns, QR login, search/detail crawling, and browser context reuse.
- `yangsijie666/xiaohongshu-crawler`: uses Playwright automation with stealth/browserforge-style browser hardening and MCP-style tool exposure.
- `DeliciousBuding/xiaohongshu-skill`: uses Python + Playwright and extracts structured data from page state.
- `wanghaisheng/MediaCrawlerDP`: uses Playwright as a bridge and preserves logged-in browser context to avoid reimplementing signing logic.

### 当前仍然失败的问题

- Current in-repo crawler cannot guarantee daily fresh Xiaohongshu evidence acquisition.
- A single Cookie + selector path can pass profile health but still fail note-detail access.
- Short links can land on app/intermediate/login/risk-control pages.

### 当前未完成工作

- Design and implement a redundant XHS acquisition layer:
  - primary direct detail extractor,
  - maintained external extractor adapter or sidecar,
  - persistent browser-context refresh,
  - canonical URL resolver,
  - note-page health probe,
  - selector/schema drift detector,
  - per-industry daily freshness ledger,
  - alerting and operator action before freshness deadline.

### 当前最高风险

- Product promise risk: "must not fail" cannot be guaranteed by scraping alone without redundancy and operational maintenance.
- Compliance/operational risk: do not implement CAPTCHA bypass, account-abuse automation, or aggressive retry/anti-risk evasion.

### 下一步最小可行计划

1. Add a crawler health model that distinguishes profile login, note page access, selector extraction, short-link canonicalization, and risk-control detection.
2. Add an adapter interface so NoteAI can try the internal crawler first and a vetted open-source extractor/sidecar second.
3. Add daily freshness ledger and deadline-based alerts so the system knows before the user-facing daily evidence window is missed.
4. Run a single test-owned local DB smoke only after explicit user confirmation.

### 不能在未经确认的情况下修改

- CAPTCHA solving, risk-control bypass, aggressive proxy rotation, or account automation that could violate platform rules.
- Production Cookie/session handling.
- Production DB, deploy, scheduler setup, or external crawler sidecar installation.

## 2026-07-05 Execution Update - Chromium Install and Real XHS Crawler Validation

### 本轮完成了什么

- Installed the Python Playwright Chromium revision requested by `model/crawler.py`.
- Confirmed the default Python Playwright crawler runtime can now launch Chromium.
- Ran controlled live crawler checks against Xiaohongshu without printing Cookie values.
- Confirmed Cookie/profile check succeeds with the mobile profile context.
- Diagnosed that the user-provided short link can land in different states:
  - mobile note context lands on an app/intermediate page and does not expose note selectors.
  - desktop note context can expose note selectors and did successfully extract title presence plus public interaction fields once.
  - repeated accesses later landed on `/login`, showing Cookie/short-link/risk-control instability.
- Updated crawler context handling:
  - note extraction now defaults to desktop UA/viewport, with environment-variable overrides for cloud deployment.
  - profile Cookie check remains on mobile UA/viewport to avoid false invalidation.
  - short-link extraction now attempts to follow a real note link from an intermediate page when available.
- Stopped further live crawler retries after seeing `/login` to avoid increasing risk against the provided short link/Cookie.

### 修改了哪些文件

- `model/crawler.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/crawler.py`: Added separate browser contexts for note extraction and profile Cookie checks; added environment-variable overrides; added note-container/link helpers for short-link handling.
- `.codex/handoffs/current-task.md`: Recorded the live crawler evidence, commands, results, remaining failures, and next plan.

### 关键决策

- Did not keep using mobile UA for note extraction because real short-link testing showed it lands on an app/intermediate page without note selectors.
- Did not switch Cookie/profile validation fully to desktop because desktop profile check returned false even when mobile profile check succeeded.
- Kept live crawler attempts small and sequential; did not run batch worker, did not mark existing user records due, and did not write production data.
- Treated the desktop extraction success as proof of partial feasibility, not as proof of stable production readiness.

### 运行了哪些命令

- `.venv/bin/python -m playwright install chromium`
- `cd model && ../.venv/bin/python crawler.py check-cookie`
- Several controlled one-off Playwright scripts against the user-provided short link:
  - mobile/default extraction attempt,
  - short-link diagnostic,
  - desktop UA selector diagnostic,
  - desktop UA extraction confirmation,
  - post-fix extraction check.
- `cd model && ../.venv/bin/python - <<'PY' ... crawler_log tail summary ... PY`
- `.venv/bin/python -m py_compile model/crawler.py tools/live_ai_smoke.py`
- `.venv/bin/python -m unittest tests.test_tracking_performance`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `docker compose config --quiet`
- `git diff --check`
- `git status --short`

### 每个命令的结果

- Chromium install:
  - downloaded Playwright Chromium build `v1194`.
  - downloaded Playwright Chromium Headless Shell build `v1194`.
- `crawler.py check-cookie`:
  - before install: previously failed because expected browser revision was missing.
  - after install and mobile profile context: `Cookie valid: True`.
  - after temporarily testing desktop profile context: `Cookie valid: False`, so profile check was split back to mobile context.
- User short-link live extraction:
  - first mobile/default attempt: `extracted: false`, final host `oia.xiaohongshu.com`.
  - mobile diagnostic: final host `www.xiaohongshu.com`, no note selectors, app/open-page signals present.
  - desktop diagnostic: final host `www.xiaohongshu.com`, note-like path, note container/title/interaction selector candidates present.
  - desktop extraction confirmation: `extracted: true`, title present, metric fields present, no DB writes.
  - later post-fix extraction: `extracted: false`, final host `www.xiaohongshu.com`, non-note path.
  - final diagnostic: final path `/login`, no note-link candidates, login/verification/open-app signals present.
- `py_compile`: passed.
- `tests.test_tracking_performance`: passed, 4 tests.
- `tests.test_api_contracts`: passed, 130 tests; one captured Moonshot network error was printed by test code but did not fail the suite.
- full unittest discover: passed, 236 tests; same captured Moonshot network log appeared.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.

### 当前仍然失败的问题

- The provided `xhslink.com` short link is not stable enough to treat as a production-ready crawler proof:
  - it can expose a note page under desktop context,
  - but repeated controlled accesses can also land on `/login` or app/intermediate pages.
- Existing Cookie validity check can prove one profile route works, but does not guarantee desktop note-page extraction remains available.
- The crawler still depends on Xiaohongshu Web DOM selectors and Cookie health; selector changes or risk-control routing can break daily automation.

### 当前未完成工作

- Add a safer production health model for crawler:
  - distinguish `cookie_profile_valid`, `note_page_access_valid`, `selector_valid`, and `risk_control_detected`.
- Add admin/operator guidance for uploading a desktop Web Cookie when note extraction lands on `/login`.
- Add optional manual fallback/URL canonicalization flow when short links cannot be resolved.
- Decide whether to run a DB-backed single local tracking-row crawler smoke; this would write local SQLite and should only use a clearly test-owned row.

### 当前最高风险

- Crawler reliability risk: real Xiaohongshu scraping is externally brittle without official API access.
- Cookie risk: a Cookie can be valid for one route/UA and invalid for another; cloud deployment needs ongoing Cookie health checks.
- Data quality risk: public interaction numbers can be extracted, but selector ambiguity and login/intermediate pages must be detected before using the data for training.
- Compliance/operational risk: do not implement CAPTCHA bypass or aggressive anti-risk behavior; keep rate limits, manual fallback, and transparent failure states.

### 下一步最小可行计划

1. Keep the new desktop note extraction context and mobile profile check split.
2. Add explicit crawler health fields/status for profile-valid vs note-access-valid vs selector-valid.
3. Add a single test-owned DB tracking-row smoke only after user confirms the local DB write scope.
4. Keep worker schedule conservative and daily; on failure, move records to `needs_manual` instead of retrying aggressively.

### 不能在未经确认的情况下修改

- Production Cookie/session handling or automated login.
- CAPTCHA solving, anti-risk bypass, or aggressive crawler retry behavior.
- Existing user-owned tracking records.
- Production DB, production deployment, payment/email/SMS.
- Billing/quota/payment logic.

## 2026-07-05 Execution Update - Capped Live AI Smoke Tool

### 本轮完成了什么

- Added a dedicated capped live AI smoke tool that bypasses the full `/generate` business pipeline.
- Verified the tool with one real Claude call using a synthetic prompt.
- Confirmed this smoke path made exactly one provider call, printed only a sanitized JSON summary, and did not write the application database.

### 修改了哪些文件

- `tools/live_ai_smoke.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `tools/live_ai_smoke.py`: Provides a controlled one-call live AI validation path with no retries, small `max_tokens`, no business DB writes, and no model-content output.
- `.codex/handoffs/current-task.md`: Records the stage completion, commands, results, remaining risks, and next step.

### 关键决策

- Did not reuse `/generate/stream` for smoke because the previous test triggered 23 model calls.
- Did not use `model_router.call()` because it can retry/fallback and records billing usage; the smoke tool calls the provider directly to keep call count and side effects controlled.
- Defaulted to Claude Haiku for the first controlled smoke because it was already observed working in the local provider usage metadata.

### 运行了哪些命令

- `.venv/bin/python -m py_compile tools/live_ai_smoke.py`
- `.venv/bin/python tools/live_ai_smoke.py --provider claude --max-tokens 64 --timeout 45`

### 每个命令的结果

- `py_compile`: passed.
- Live AI smoke:
  - provider: Claude.
  - model: `claude-haiku-4-5-20251001`.
  - actual external provider calls: 1.
  - success: true.
  - input tokens: 35.
  - output tokens: 10.
  - content printed: false.
  - business DB writes: false.

### 当前仍然失败的问题

- The full `/generate/stream` product path remains too expensive for casual live smoke because it can fan out into many model calls.

### 当前未完成工作

- Install the Python Playwright Chromium revision approved by the user.
- Run one real Xiaohongshu crawler validation against the user-provided short link.
- Run final safety checks and summarize crawler feasibility.

### 当前最高风险

- Product-level live AI validation still needs a dedicated capped mode or an explicit call budget before using `/generate/stream` again.

### 下一步最小可行计划

1. Install the Python Playwright Chromium runtime requested by `model/crawler.py`.
2. Run `crawler.py check-cookie` once.
3. Run one direct extraction against the user-provided `xhslink.com` URL without writing production data.

### 不能在未经确认的情况下修改

- Billing, payment, quota, or provider routing logic.
- Full `/generate/stream` fan-out behavior.
- Production environment configuration or secrets.
- Production DB, deploy, email, SMS, or payment flows.

## 2026-07-05 Execution Update - Controlled Live AI and XHS Crawler Smoke

### 本轮完成了什么

- Ran a user-approved controlled live smoke covering local production-style services, real AI provider usage, and real Xiaohongshu access.
- Confirmed local services were already running:
  - API `127.0.0.1:8000`
  - admin `127.0.0.1:8001`
  - frontend `127.0.0.1:5173`
- Confirmed `/health` reports `ok` and model label `v0.4-composite`.
- Confirmed `.env` has AI provider keys present without printing values.
- Confirmed `model/data/xhs_cookies.json` exists and is non-empty without printing Cookie values.
- Ran one real `/generate/stream` request with a synthetic, non-user brief.
- Interrupted the client after the single AI request exceeded the acceptable small-smoke wait time.
- Checked local usage summary after the AI request and confirmed provider models observed through local usage/log metadata.
- Ran real Xiaohongshu cookie/profile access using Playwright with existing browser cache, without installing dependencies.
- Ran `crawler.run_collection_round(limit=1)`.
- Ran a controlled crawler note-page access with a synthetic non-user Xiaohongshu note URL to verify the page-access/extraction function starts.
- Did not deploy, did not run payment/email/SMS, did not output env/secrets/tokens/Cookies, and did not run batch/parallel crawler or AI requests.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the live smoke plan, commands, results, failures, cost/safety implications, and remaining risks.

### 关键决策

- Stopped the AI client request after it exceeded the small-smoke wait window; did not retry.
- Did not install Python Playwright browsers because dependency installation was not separately confirmed.
- Used existing Playwright browser cache to validate real Xiaohongshu profile access instead.
- Did not mark existing user tracking records due or process local user URLs because there were no due records and we avoided touching potentially user-owned tracking data.
- Used a synthetic Xiaohongshu note URL only to verify crawler note-page access starts; this is not evidence of successful metric extraction from a real note.

### 运行了哪些命令

- `.venv/bin/python - <<'PY' ... preflight env/cookie/db presence ... PY`
- `./start_all.sh status`
- `git status --short`
- `.venv/bin/python - <<'PY' ... live /auth/register + /generate/stream smoke ... PY`
- Interrupted the live AI smoke with Ctrl-C after extended wait.
- `cd model && ../.venv/bin/python crawler.py check-cookie`
- `cd model && ../.venv/bin/python - <<'PY' ... crawler.run_collection_round(limit=1) ... PY`
- `tail -n 80 /tmp/noteai_api.log ...`
- `.venv/bin/python - <<'PY' ... usage_records model summary ... PY`
- Read-only Playwright cache checks under `~/Library/Caches/ms-playwright`.
- `cd model && ../.venv/bin/python - <<'PY' ... XHS profile access with existing browser executable ... PY`
- `cd model && ../.venv/bin/python - <<'PY' ... synthetic XHS note-page extraction attempt ... PY`
- `cd model && ../.venv/bin/python - <<'PY' ... crawler_log summary without URL ... PY`
- `git diff --check`

### 每个命令的结果

- Preflight:
  - `ANTHROPIC_API_KEY`: present.
  - `MOONSHOT_API_KEY`: present.
  - XHS Cookie file: exists and non-empty.
  - Local DB exists.
  - `tracked_notes` total: 4.
  - due pending tracking rows: 0.
  - due 7d tracking rows: 0.
- `./start_all.sh status`:
  - main API: `ok`, model `v0.4-composite`.
  - admin: `ok`.
  - frontend: running.
- Live AI `/generate/stream`:
  - one local test user was registered in local SQLite.
  - one `/generate/stream` request was sent with synthetic brief.
  - client was interrupted after extended wait.
  - API logs showed the backend did execute real Claude calls.
  - Local usage summary for latest generate record reported `model_calls: 23`, exceeding the intended <=10 small-smoke protection threshold.
  - Models observed in local usage/log metadata:
    - `claude:claude-haiku-4-5-20251001`
    - `claude:claude-sonnet-4-6`
  - No additional live AI retry was run.
- `crawler.py check-cookie`:
  - failed in the default Python Playwright path because the expected Chromium headless shell revision was missing.
  - no Cookie values were printed.
- `crawler.run_collection_round(limit=1)`:
  - returned `暂无待采集记录`, `collected: 0` because no local tracking rows were due.
- Existing Playwright cache:
  - cache exists, but Python Playwright expected a missing revision.
  - found other cached `chrome-headless-shell` executables.
- XHS profile access with existing browser cache:
  - existing browser executable found.
  - Cookie file loaded.
  - `https://www.xiaohongshu.com/user/profile/me` was accessed.
  - Cookie validity check returned `true`.
- Synthetic note-page extraction:
  - note page access attempted.
  - no metrics/title extracted, expected because the URL was synthetic/non-user.
  - crawler log recorded `extract_failed`.
- Final service status:
  - API/admin/frontend still running locally.
- `git diff --check`: passed.

### 当前仍然失败的问题

- Live AI generation is not under sufficient small-smoke control: one `/generate/stream` request triggered 23 backend model calls, which is too many for casual live validation.
- Default Python Playwright crawler path cannot launch because the exact expected Chromium revision is missing.
- `run_collection_round(limit=1)` had no due tracking tasks, so no real tracked note metrics were collected.
- Synthetic note URL crawler access did not extract metrics/title; this does not prove real note extraction success.

### 当前未完成工作

- Need a cheaper live AI smoke endpoint or a test mode that caps internal generation candidates/model calls before repeating live AI validation.
- Need either:
  - explicit approval to install the Python Playwright Chromium revision, or
  - code/config support for crawler to use an existing browser executable path.
- Need a real public Xiaohongshu note URL, or explicit approval to mark one local tracking row due, before testing real metrics extraction.
- Need to stop local services if the user does not want them left running.

### 当前最高风险

- AI cost/control risk: `/generate/stream` internally fans out to many model calls; this must be capped before further live testing.
- Crawler deployment risk: local existing browser cache can access XHS, but the default Python Playwright runtime is not currently ready.
- Real data risk: processing existing `tracked_notes` could touch user-owned URLs; do not do this without explicit scope.

### 下一步最小可行计划

1. Add or use a low-cost live AI smoke path with strict max-candidate/model-call caps before any further provider calls.
2. Decide whether to install Python Playwright Chromium or add a config option for crawler executable path.
3. Ask for/provide one real public Xiaohongshu note URL for a single extraction test, or explicitly approve marking one local test tracking row due.
4. Keep crawler runs at `limit=1`, no parallelism, no retries, and no URL/title output.

### 不能在未经确认的情况下修改

- AI billing/quota/payment logic.
- Provider routing/fallback behavior beyond a dedicated capped smoke mode.
- Existing user-owned tracking records or URLs.
- Python Playwright browser installation.
- Production deploy, production DB, payment/email/SMS.
- `.env`, provider keys, tokens, Cookies, secrets.

## 2026-07-05 Execution Update - Tracking UI Smoke

### 本轮完成了什么

- Ran a rendered UI smoke for the new note real-performance tracking surfaces.
- Used the in-app Browser first for page identity, console health, and screenshot evidence.
- Browser DOM snapshot failed in the Browser runtime, so the targeted API-mocked interaction smoke was completed with Playwright.
- Verified the library version card shows the linked tracking badge after expanding the version panel.
- Verified the tracking modal opens from the v2 card and submits `source_note_id`, `source_note_version_id`, `note_title`, and `predicted_ces`.
- Verified the profile/growth tracking aggregate renders linked-note status, actual CES, evidence source, and confidence label.
- Verified a mobile viewport (`390x844`) renders the tracking badge without document-level horizontal overflow.
- Did not use the default local DB, did not run crawler/worker, did not access Xiaohongshu or any external site, did not call live AI APIs, and did not output env/secrets.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded this rendered UI smoke, fallback reason, screenshot paths, command results, remaining risks, and next minimum plan.

### 关键决策

- Used route-mocked Playwright instead of a real API server to avoid writing test users or tracking records to the default local SQLite DB.
- Treated the collapsed version panel as expected behavior; the tracking badge is visible after the user expands the note version card.
- Used exact linked fields as the interaction contract for the `POST /notes/track-url` payload.

### 运行了哪些命令 / 浏览器动作

- Read frontend testing and in-app Browser skill instructions.
- Browser runtime:
  - initialized in-app Browser session,
  - opened `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=tracking-ui-smoke&page=library`,
  - checked URL/title/console,
  - captured a Browser screenshot.
- `lsof -nP -iTCP:5173 -sTCP:LISTEN || true`
- `sed -n ... playwright.config.js`
- `rg -n "API_BASE|API_AUTH|..." NoteAI_Pro_Demo_Framer.html`
- Several one-off `node --input-type=module <<'JS' ... JS` Playwright route-mocked smoke scripts:
  - first runs diagnosed test-wait issues,
  - final desktop run passed,
  - final mobile run passed.
- `git status --short`
- `git diff --check`
- `ls -lh /tmp/noteai_tracking_*_smoke.png`

### 每个命令 / 动作的结果

- Browser plugin was available and page navigation worked.
- Browser DOM snapshot failed with `incrementalAriaSnapshot is not a function`; Browser troubleshooting docs were read. This is why the targeted API-mocked interaction used Playwright fallback.
- Browser page health:
  - URL was the local static page.
  - Title was `NoteAI Pro · 小红书创作者智能诊断平台`.
  - Console errors/warnings were empty for the Browser check.
  - Browser screenshot was captured.
- Static server was already listening on `127.0.0.1:5173`; no new server was started.
- First Playwright smoke failed because the version panel was collapsed before checking badge text; diagnosis confirmed badge HTML was correct after expansion.
- Second Playwright smoke failed because profile wait condition matched generic copy before async data rendered; diagnosis confirmed profile list rendered correctly when waiting for linked tracking fields.
- Final desktop Playwright smoke passed:
  - library badge verified: `📡 已完成`, `实际 86.7`, `高置信`.
  - modal submit payload verified:
    - `source_note_id: note-v2-smoke`
    - `source_note_version_id: note-v2-smoke`
    - `note_title: 真实追踪 UI smoke v2`
    - `predicted_ces: 82.4`
  - profile aggregate verified: linked note, actual CES, `自动采集`, `高置信度`.
  - console errors: none.
  - console warnings: none.
  - external calls: 0.
  - real crawler runs: 0.
- Final mobile Playwright smoke passed:
  - viewport `390x844`.
  - tracking badge visible.
  - no document-level horizontal overflow.
- Screenshots saved outside repo:
  - `/tmp/noteai_tracking_library_smoke.png`
  - `/tmp/noteai_tracking_modal_smoke.png`
  - `/tmp/noteai_tracking_profile_smoke.png`
  - `/tmp/noteai_tracking_mobile_smoke.png`
- `git diff --check`: passed.
- `git status --short`: unchanged intended code/doc files plus pre-existing untracked `测试图片/`.

### 当前仍然失败的问题

- No final smoke command is failing.
- Browser plugin DOM snapshot remains unavailable in this environment, but Playwright route-mocked validation completed the target checks.

### 当前未完成工作

- No real API server/browser smoke against a temporary DB-backed localhost API has been run.
- No controlled real crawler smoke has been run.
- Screenshot/OCR evidence intake into tracking is still not implemented.
- No commit/stage/push was performed in this stage.

### 当前最高风险

- Real crawler/cloud worker reliability remains unvalidated.
- Production-like DB migration rehearsal is still needed before deployment.
- The current UI smoke used mocked API responses; a real temp-DB localhost API smoke would be stronger for end-to-end browser testing.

### 下一步最小可行计划

1. Review the current diff as a checkpoint scope.
2. If accepted, stage/commit the tracking loop changes separately from unrelated local artifacts.
3. Before real crawler validation, output a Live Crawler Run Plan with 1 to 3 samples, no production DB, no parallel load, and脱敏 summary.
4. Plan screenshot/OCR evidence intake as the next feature increment.

### 不能在未经确认的情况下修改

- Auth/session/password/token/admin permission.
- Billing, credits, subscriptions, payment, refund, quota, or pricing logic.
- `.env`, provider keys, tokens, secrets, production config.
- Production database, production deploy, payment/email/SMS operations.
- Real crawler/worker external-site runs, live AI calls, batch data runs, or concurrent smoke tests.
- The untracked `测试图片/` local directory.

## 2026-07-05 Execution Update - Tracking Loop Local Temp-DB Smoke

### 本轮完成了什么

- Ran a local smoke for the note real-performance tracking loop using a temporary SQLite DB.
- Registered a test user inside the temporary DB only.
- Saved a root note and a v2 note version.
- Submitted a Xiaohongshu-format URL tracking request from the v2 note.
- Verified the tracking record persisted `source_note_id`, `source_root_note_id`, title, pending status, and next-check scheduling fields.
- Manually filled 7-day interaction metrics.
- Verified the tracking record completed with `actual_ces`, `confidence_label`, `evidence_source`, and manual evidence.
- Verified `growth_records.note_id` points back to the v2 note, not NULL.
- Verified a Hermes/user memory context entry was written for the real-performance result.
- Did not run a real crawler, did not access Xiaohongshu or any external site, did not call live AI APIs, did not deploy, and did not output tokens/secrets.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded this smoke stage, command results, risks, and next minimum plan.

### 关键决策

- Used a temporary SQLite DB through a one-off Python smoke instead of starting local API/admin servers against the default local DB.
- Used FastAPI `TestClient` to validate authenticated API behavior without binding network ports.
- Used manual-fill evidence only; crawler and external sites stayed out of scope.
- Kept output as a脱敏 summary with no bearer token, password, env value, Cookie, API key, or DB path.

### 运行了哪些命令

- `git status --short`
- `sed -n '1,220p' model/auth.py`
- `rg -n "@app.post\\(\\\"/auth/register\\\"|class Register|def register|@app.post\\(\\\"/auth/login\\\"|class Login" model/api.py model/auth.py`
- `sed -n '9878,9908p' model/api.py`
- `.venv/bin/python - <<'PY' ... PY` one-off temporary DB smoke
- `git diff --check`
- `find /tmp -maxdepth 1 -name 'tmp*' -type d -mmin -5 2>/dev/null | wc -l`

### 每个命令的结果

- `git status --short`: showed the intended modified/new tracking-loop files plus pre-existing untracked `测试图片/`.
- Read-only inspections found the auth register/login models and confirmed smoke payload shape.
- Temporary DB smoke passed with:
  - `registered_test_user: true`
  - `temp_db_used: true`
  - `root_note_linked: true`
  - `source_note_linked: true`
  - `title_persisted: true`
  - `status_after_manual_fill: complete`
  - `actual_ces: 55.2`
  - `confidence_label: 中`
  - `evidence_source: manual`
  - `growth_note_linked: true`
  - `memory_written: true`
  - `external_calls: 0`
  - `real_crawler_runs: 0`
- `git diff --check`: passed.
- `/tmp` temp directory check showed no recent smoke temp directory left behind.

### 当前仍然失败的问题

- No command failed in this stage.
- This was not a browser UI smoke; it validated the authenticated API/data loop.
- This did not validate real crawler viability or cloud worker execution.

### 当前未完成工作

- Browser/manual UI smoke with a logged-in test user still needs to verify the library version badge and profile aggregate rendering.
- Screenshot/OCR evidence intake into tracking is still not implemented.
- Controlled real crawler smoke still requires a separate Live Crawler Run Plan and user confirmation.
- No commit/stage/push was performed in this stage.

### 当前最高风险

- Real Xiaohongshu crawler reliability remains the highest operational risk.
- Production-like DB migration rehearsal is still needed before deployment because `model/db.py` schema changes run idempotently on startup/import.
- The static frontend still needs visual/manual verification for the new per-version tracking badge.

### 下一步最小可行计划

1. Start a safe local frontend/API smoke only if a test DB strategy is confirmed for server startup, or use browser route mocking to validate the UI without API writes.
2. Verify the note library card shows tracking status for a linked version and the profile tracking list shows actual CES/confidence after manual fill.
3. Prepare a checkpoint scope for review/commit after UI smoke.
4. For real crawler validation, first output a Live Crawler Run Plan with 1 to 3 samples, no production DB, no parallel load, and脱敏 result summary.

### 不能在未经确认的情况下修改

- Auth/session/password/token/admin permission.
- Billing, credits, subscriptions, payment, refund, quota, or pricing logic.
- `.env`, provider keys, tokens, secrets, production config.
- Production database, production deploy, payment/email/SMS operations.
- Real crawler/worker external-site runs, live AI calls, batch data runs, or concurrent smoke tests.
- The untracked `测试图片/` local directory.

## 2026-07-05 Execution Plan - Note Real Performance Tracking Loop

### 本轮目标

- 将“笔记真实表现追踪”从成长档案里的孤立 URL 追踪，升级为“笔记版本发布后真实表现 -> 用户记忆 -> Hermes 个性化学习 -> 未来训练样本”的闭环。
- 修复从笔记库发起追踪时没有真正持久化原始 `note/version/session` 关联的问题。
- 修复标题长期显示“未获取标题”的问题。
- 统一追踪状态机，避免 `checking_7d` 设计与 crawler 实际状态不一致。
- 引入按行业/时间窗口/证据置信度计算的真实表现评分模块，替代固定 benchmark 简化算法。
- 增加独立 crawler worker/cron 入口和部署配置，但本轮不运行真实 crawler、不访问外部站点、不部署。

### 预计修改文件

- `model/db.py`: 为 `tracked_notes` 增加 source note/session 关联、调度、证据来源、置信度、错误摘要、重试等字段，并保持幂等迁移。
- `model/api.py`: 扩展 `/notes/track-url` 入参和持久化；手动回填改用新的评分模块；追踪完成写入带 `note_id` 的成长记录和用户记忆。
- `model/performance_scoring.py`: 新增真实表现评分模块，输出 `actual_ces`、grade、confidence、insights。
- `model/crawler.py`: 使用统一状态机、`next_check_at`、新评分模块和脱敏错误摘要。
- `model/crawler_worker.py`: 新增云端 worker 入口，支持单轮和循环运行。
- `model/admin_server.py`: 让 admin 触发追踪采集进入统一状态/调度，而不是只改旧状态。
- `NoteAI_Pro_Demo_Framer.html`: 从笔记库追踪时发送 note 关联；在笔记库卡片展示追踪状态；成长档案作为聚合视图。
- `docker-compose.yml` / `Dockerfile` / docs or tests as needed: 增加可选 worker 配置和安全验证覆盖。
- `tests/`: 增加 API、评分、状态机相关测试。

### 关键决策

- 成长档案保留为汇总分析入口，但追踪的主链路应绑定到笔记库里的具体 note version。
- “真实表现”定义为基于 crawler、截图/OCR、手动回填等证据源的表现评分，并带 `evidence_source` 与 `confidence`，不承诺官方绝对真实数据。
- 不依赖官方授权趋势/平台数据；crawler 是辅助证据管道，失败时必须降级到截图/OCR或手动回填。
- 不把 worker 放进 API 进程；未来云端用独立 worker/cron 执行。
- 低置信度数据不能直接污染未来训练样本；训练用途需要记录来源和置信度。

### 实施顺序

1. 只读核查当前 note/version/session、tracking、crawler、测试结构。
2. 修改 DB schema 和 API 入参，先打通 source note/title 持久化。
3. 新增真实表现评分模块并接入手动回填。
4. 统一 crawler 状态机和 worker 入口。
5. 修改前端追踪提交与展示。
6. 增加测试并运行安全验证。
7. 更新本 handoff，记录实际改动、命令结果、剩余风险和下一步。

### 验证计划

- `python -m py_compile model/*.py`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- 静态/前端测试按实际改动补充运行。
- 不运行真实 crawler、不会访问外部站点、不会调用真实 AI API、不会部署、不会运行 DB reset/seed/clean。

### 当前最高风险

- `model/db.py` schema 变更会在应用启动时对 SQLite 执行幂等迁移；需要保证只加列、不删表、不改旧字段语义。
- `NoteAI_Pro_Demo_Framer.html` 是大型静态文件，前端状态变量容易漂移。
- crawler 依赖小红书页面、Cookie 和 Playwright，自动采集不能作为唯一真相来源。

### 不能在未经确认的情况下修改

- Auth/session/password/token/admin permission。
- Billing、credit、subscription、payment、refund、quota 逻辑。
- `.env`、secret、token、API key、生产配置。
- 生产数据库、真实部署、真实支付、邮件、短信。
- 真实 crawler/worker 外部站点访问或批量 live API 调用。
- 未跟踪的 `测试图片/` 本地目录。

## 2026-07-05 Execution Update - Note Real Performance Tracking Loop

### 本轮完成了什么

- Implemented the note real-performance tracking loop as a note-version-linked feature instead of a profile-only URL tracker.
- Added persistent tracking links back to the source note version, root version chain, and optional chat session.
- Preserved note titles when tracking starts from the library, preventing new records from showing `未获取标题` unless the user starts from an external URL without a title.
- Added a unified tracking state path for `pending -> checking_7d -> complete/needs_manual`, while keeping backward compatibility for old `checking_24h` rows.
- Added evidence-source and confidence fields so crawler/manual/screenshot-style evidence can be distinguished before future model training.
- Added a reusable real performance scoring module and wired it into manual fill and crawler completion.
- Added an independent tracking crawler worker entrypoint and Docker Compose service.
- Updated the frontend so the library version card is the primary tracking entry and shows per-version tracking status; profile remains the aggregate view.
- Added tests for performance scoring, source note persistence, and manual fill growth-record linkage.
- Did not run a real crawler, did not access Xiaohongshu or external sites, did not call live AI APIs, did not deploy, and did not output env/secrets.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`
- `model/db.py`
- `model/api.py`
- `model/performance_scoring.py`
- `model/crawler.py`
- `model/crawler_worker.py`
- `model/admin_server.py`
- `docker-compose.yml`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_tracking_performance.py`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the approved plan, actual work, verification, remaining risks, and no-touch areas.
- `model/db.py`: Added idempotent tracking columns for source note/session linkage, scheduling, attempts, evidence source, confidence, errors, completion time, and training eligibility.
- `model/api.py`: Extended `/notes/track-url`; validates source note/session ownership; stores note title and root note; filters tracking records by source; manual fill now scores with evidence confidence and writes `growth_records.note_id`.
- `model/performance_scoring.py`: Centralized real-performance CES scoring by domain, metrics, evidence source, confidence, and training eligibility.
- `model/crawler.py`: Uses `next_check_at`, clearer statuses, finite retry/fallback behavior, new scoring module, evidence confidence, and linked growth records.
- `model/crawler_worker.py`: Provides a cloud-friendly worker entrypoint for cron or long-running background service.
- `model/admin_server.py`: Admin trigger now marks a tracking row as immediately due in the unified state machine instead of forcing old `checking_24h`.
- `docker-compose.yml`: Added a separate `noteai-tracking-worker` service guarded by crawler config.
- `NoteAI_Pro_Demo_Framer.html`: Sends source note/session fields from library tracking; shows tracking status on version cards; enriches profile tracking list; supports optional views in manual fill.
- `tests/test_tracking_performance.py`: Covers scoring confidence, estimated-view confidence reduction, source note/root persistence, and growth-record linkage.

### 关键决策

- The library note version is now the primary tracking object; profile is the aggregate analysis surface.
- Tracking evidence is not treated as official platform truth. Every completed score carries `evidence_source`, `confidence`, and `training_eligible`.
- Worker scheduling is separate from API/admin processes.
- Automatic crawler failure falls back to manual fill rather than unlimited retries.
- Existing old rows remain compatible: old `checking_24h` rows can still be picked up for 7-day completion.

### 运行了哪些命令

- `sed -n ...` / `rg ...` read-only inspections across `model/db.py`, `model/api.py`, `model/crawler.py`, `model/admin_server.py`, `NoteAI_Pro_Demo_Framer.html`, tests, Docker config, and project memory files.
- `python -m py_compile model/*.py`
- `.venv/bin/python -m py_compile model/*.py`
- `.venv/bin/python -m unittest tests.test_tracking_performance`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `npm run test:e2e`
- `docker compose config --quiet`
- `git diff --check`
- `git diff --stat`
- `git status --short`

### 每个命令的结果

- Read-only inspections completed successfully.
- `python -m py_compile model/*.py`: failed because this shell has no `python` command.
- `.venv/bin/python -m py_compile model/*.py`: passed.
- First `.venv/bin/python -m unittest tests.test_tracking_performance`: failed due to a migration ordering issue where an index referenced new columns before old DBs had been altered.
- Fixed `model/db.py` by moving new tracking indexes after idempotent `ALTER TABLE` additions.
- `.venv/bin/python -m unittest tests.test_tracking_performance`: passed, 4 tests OK.
- `.venv/bin/python -m unittest tests.test_api_contracts`: passed, 130 tests OK.
- `.venv/bin/python -m unittest tests.test_frontend_report_static`: passed, 9 tests OK.
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`: passed, 236 tests OK.
- `npm run test:e2e`: passed, 3 Playwright tests OK.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.
- `git status --short`: shows the intended modified/new files plus the pre-existing untracked `测试图片/` directory.

### 当前仍然失败的问题

- No validation command is currently failing.
- Real Xiaohongshu crawler viability was not tested in this stage.
- Screenshot/OCR evidence ingestion into tracking is not implemented yet; the data model and scoring contract are prepared for it.

### 当前未完成工作

- No live crawler smoke was run.
- No cloud cron job was deployed or verified.
- No screenshot/OCR tracking endpoint has been added yet.
- No production DB migration rehearsal was run on a copy of production-like data.
- No training export pipeline was added; current work only marks `training_eligible`.

### 当前最高风险

- `model/db.py` schema additions are idempotent but will mutate SQLite schema on app import/startup. Tests imported `api/db`, so local SQLite schema may have been upgraded; DB files remain untracked.
- Real crawler reliability is still constrained by Xiaohongshu page structure, login/Cookie state, anti-bot behavior, and cloud Playwright behavior.
- The static frontend is still a large single file; per-version tracking UI should be manually checked in browser with a logged-in test user.

### 下一步最小可行计划

1. Do a local authenticated smoke with a test user/test DB strategy: create or reuse a test note, start tracking from the library, verify `/notes/tracking` returns `source_note_id`, title, status, and next check time.
2. Do a manual-fill smoke on that tracking record and verify profile + library card show actual CES and confidence.
3. Only after a separate Live Crawler Run Plan, run 1 to 3 controlled real crawler samples with non-production data.
4. Add screenshot/OCR evidence intake for tracking if manual/crawler smoke confirms the core linked flow.
5. Prepare a checkpoint review/commit scope after user approval.

### 不能在未经确认的情况下修改

- Auth/session/password/token/admin permission.
- Billing, credits, subscriptions, payment, refund, quota, or pricing logic.
- `.env`, provider keys, tokens, secrets, production config.
- Production database, production deploy, payment/email/SMS operations.
- Real crawler/worker external-site runs, live AI calls, batch data runs, or concurrent smoke tests.
- The untracked `测试图片/` local directory.

## 2026-07-05 Execution Update - Frontend User Page Fixes

### 本轮完成了什么

- Fixed the user-facing frontend issue where explicit diagnosis entry points could leave the upload page in generation mode.
- Fixed mobile chat layout clipping at `390x844` by making the chat page stack note preview above the chat panel on narrow screens.
- Verified the fixes in the in-app browser using the local static frontend only.
- Re-ran existing frontend static tests and Playwright e2e tests.
- Did not start API/admin, did not submit auth forms, did not call real AI APIs, did not run DB/crawler/deploy/payment/email/SMS operations, and did not output env or secret values.

### 修改了哪些文件

- `NoteAI_Pro_Demo_Framer.html`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `NoteAI_Pro_Demo_Framer.html`: Added `goToDiagnose()` and routed explicit diagnosis CTAs through it; added chat layout classes and mobile CSS so chat no-session view does not clip horizontally on phones; corrected a library empty-state "go generate" button to use generation mode.
- `.codex/handoffs/current-task.md`: Recorded this repair stage, validation, remaining gaps, and no-touch areas per project workflow.

### 关键决策

- Kept the fix in the static frontend only; no backend/API/database behavior was changed.
- Preserved `goToGenerate()` for generation-specific entry points and introduced `goToDiagnose()` for diagnosis-specific entry points.
- Used CSS class wrappers for the chat layout instead of broad structural refactoring.
- Kept unauthenticated/backend-dependent flows out of scope until a safe temporary-DB API strategy is confirmed.

### 运行了哪些命令 / 浏览器动作

- `find /Users/openclaw/.codex/plugins/cache -path '*frontend-testing-debugging/SKILL.md' -print | head -20`
- `cat AGENTS.md`
- `sed -n '1,220p' .codex/handoffs/current-task.md`
- `cat .codex/notes/architecture-summary.md`
- `cat .codex/notes/risk-register.md`
- `git status -sb`
- `nl -ba NoteAI_Pro_Demo_Framer.html | sed -n ...`
- `rg -n "showPage\\('upload'|goToGenerate|page-chat|chat-main-panel|chat-note-panel" NoteAI_Pro_Demo_Framer.html`
- `git diff --check`
- `git diff -- NoteAI_Pro_Demo_Framer.html | sed -n '1,240p'`
- `python3 -m http.server 5173 --bind 127.0.0.1`
- Browser QA:
  - opened `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html` with a cache-busting query,
  - clicked `生成爆文`,
  - clicked top-nav `开始诊断`,
  - verified upload page returned to diagnosis mode,
  - opened `?page=chat` at `390x844`,
  - verified mobile chat layout direction, panel sizes, visible text, and no horizontal overflow.
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `npm run test:e2e`
- stopped the temporary static server.

### 每个命令 / 动作的结果

- Frontend skill and project memory/risk files were read successfully after locating the current skill cache path.
- Initial `git status -sb`: existing handoff modification plus untracked `测试图片/` directory were present before edits; the directory was not touched.
- `git diff --check`: passed.
- Temporary static server started successfully on `127.0.0.1:5173` and was stopped after validation.
- Diagnosis reset browser check:
  - after clicking `生成爆文` then top-nav `开始诊断`, active page was `page-upload`;
  - title was `诊断你的笔记`;
  - `#modeDiag` had `active`;
  - diagnosis section display was `block`;
  - generation section display was `none`.
- Mobile chat browser check at `390x844`:
  - active page was `page-chat`;
  - `.chat-layout` direction was `column`;
  - document/body scroll width was `390`;
  - horizontal overflow was `false`;
  - note preview panel and chat panel were both within viewport width;
  - no-session heading `对话式笔记优化` and CTA were visible.
- `.venv/bin/python -m unittest tests.test_frontend_report_static`: passed, 7 tests OK.
- `npm run test:e2e`: passed, 3 Playwright tests OK.

### 当前仍然失败的问题

- No validation command failed in this stage.
- Pricing page still logs a static fallback warning when API is intentionally not running; this remains expected for static-only QA.

### 当前未完成工作

- No authenticated frontend flow was tested end-to-end.
- No safe temporary-DB API server smoke was run.
- No screenshot OCR, video upload, `/analyze/stream`, `/generate/stream`, chat backend, billing/accounting, or admin flow was tested in this stage.
- No live AI API call was run.

### 当前最高风险

- Full frontend + API user-flow testing still needs a safe test DB strategy because direct API startup may touch `model/data/noteai.db`.
- Static HTML remains large and fragile; future navigation/mode changes should keep Playwright coverage close.

### 下一步最小可行计划

1. Let the user manually retest the user page from the current branch.
2. If the user confirms these two UI fixes, stage only `NoteAI_Pro_Demo_Framer.html` and `.codex/handoffs/current-task.md` when preparing the next checkpoint.
3. Plan a safe local API smoke using a temporary DB/module patch or explicit test harness before testing auth/profile/pricing backend paths.
4. Do not broaden into backend, billing, auth, DB, live AI, crawler, or deploy work without confirmation.

### 不能在未经确认的情况下修改

- Auth/session/password/token logic.
- Billing, credit, top-up, subscription, payment, refund, and quota logic.
- Database schema, default local DB files, migrations, seed/reset/cleanup.
- `.env`, `model/.env`, secrets, tokens, provider keys, and production config.
- Live AI API calls, OCR/video provider calls, crawler/worker runs, deploys, payment/email/SMS operations.
- The untracked `测试图片/` directory or any local test assets.

## 2026-07-05 Execution Update - Frontend User Page QA

### 本轮完成了什么

- Opened the user-facing frontend at `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html` in the in-app browser.
- Started only a temporary local static HTTP server for the frontend; did not start the API/admin servers.
- Verified landing page, upload/diagnosis page, generation mode, auth modal basics, report page, profile page, tech page, chat page, pricing page, and library page.
- Tested desktop and mobile viewport behavior.
- Ran existing frontend static tests and Playwright e2e tests.
- Did not submit login/register forms, did not call real AI APIs, did not run payment/email/SMS/crawler/deploy operations, and did not print env values or secrets.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the frontend QA scope, results, findings, commands, remaining risks, and next minimal fix plan per project workflow rules.

### 关键决策

- Did not start `./start_all.sh start` because `model/db.py` currently hard-codes `model/data/noteai.db`; starting the API may initialize or migrate the default local SQLite DB.
- Treated the current run as frontend/static/mock validation only.
- Did not perform live AI, real auth registration, backend billing, OCR/video upload, crawler, worker, or deployment validation in this stage.
- Used the Browser plugin first, then existing Playwright e2e as project automation coverage.

### 运行了哪些命令 / 浏览器动作

- `cat AGENTS.md`
- `cat .codex/handoffs/current-task.md`
- `cat .codex/notes/architecture-summary.md`
- `cat .codex/notes/risk-register.md`
- `git status -sb`
- `cat package.json`
- `cat playwright.config.js`
- `rg --files tests | sort`
- `./start_all.sh status`
- `lsof -nP -iTCP:5173 -sTCP:LISTEN`
- `lsof -nP -iTCP:8000 -sTCP:LISTEN`
- `python3 -m http.server 5173 --bind 127.0.0.1`
- Browser QA:
  - opened landing page,
  - clicked `开始 AI 诊断`,
  - selected `决策转化型`,
  - selected `展示商家`,
  - filled merchant name with a test value,
  - clicked empty diagnosis submit,
  - switched to generation mode,
  - clicked empty generation submit,
  - opened register/login modal and switched auth tabs without submitting,
  - swept top navigation pages,
  - opened direct `?page=pricing` and `?page=library`,
  - tested mobile viewport at `390x844`.
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `npm run test:e2e`

### 每个命令 / 动作的结果

- `git status -sb`: branch was clean before QA except for later handoff update.
- `./start_all.sh status`: API/admin/frontend were not running at the start.
- `lsof` checks for ports 5173 and 8000: no listeners before starting the temporary static server.
- Static server: started successfully on `127.0.0.1:5173`.
- Landing page:
  - URL and title were correct.
  - Main hero and CTA controls rendered.
  - No relevant console errors/warnings.
- Diagnosis entry:
  - `开始 AI 诊断` navigated to the upload workflow.
  - Content intent controls, merchant visibility controls, and diagnosis submit button rendered.
  - Empty screenshot-mode submit showed `请先上传图片` and did not proceed to backend.
- Content intent controls:
  - `决策转化型` selected state changed to `on`.
  - `展示商家` selected state changed to `on`.
  - Merchant test input persisted in the field.
  - Intent hint changed to the expected decision/fact-source guidance.
- Generation mode:
  - `AI 生成爆文` mode became active.
  - Generation section rendered with domain and brief controls.
  - Empty generation submit showed `请上传素材图片/视频或填写创作简报`.
- Auth modal:
  - Register modal opened with username/email/phone/password fields.
  - Login tab switched submit text to `登录`.
  - No form submission was performed.
- Top navigation pages:
  - `首页`, `开始诊断`, `处理进度`, `诊断报告`, `成长档案`, `技术引擎`, and `对话优化` all displayed their expected page containers.
- Pricing page:
  - Direct `?page=pricing` rendered pricing content.
  - Because API was intentionally not running, console logged the expected static fallback warning for pricing config fetch.
- Library page:
  - Direct `?page=library` rendered the unauthenticated library prompt.
- Mobile viewport:
  - Landing, upload, and pricing did not create document-level horizontal overflow.
  - Chat page visually clipped the right-side chat content at `390x844`.
- `.venv/bin/python -m unittest tests.test_frontend_report_static`: passed, 7 tests OK.
- `npm run test:e2e`: passed, 3 Playwright tests OK.

### 当前仍然失败的问题

- Mobile chat layout is broken at `390x844`: the chat content area is shifted/clipped horizontally, so users cannot read the right side of the empty chat state.
- Upload workflow state can be confusing: after entering generation mode, clicking top-nav `开始诊断` returns to the upload page but keeps generation mode active, so the heading remains `AI 生成爆文`.
- Pricing page logs a fallback warning when the API is not running. The fallback content renders, so this is expected in static-only QA, but it should be checked again with a safe local API/test DB strategy.

### 当前未完成工作

- No authenticated frontend flow was tested end-to-end.
- No real user registration/login was submitted.
- No local API smoke was run because default DB path is hard-coded.
- No screenshot OCR, video upload, `/analyze/stream`, `/generate/stream`, chat backend, billing/accounting, or admin flow was tested in this stage.
- No live AI API call was run.
- No code fix was made for the two frontend findings.

### 当前最高风险

- Mobile chat layout is user-visible and should be fixed before broad manual testing on phones.
- The top-nav `开始诊断` state retention can misroute users into generation mode and confuse test results.
- A safe test DB strategy is needed before full frontend + local API user-flow testing, otherwise app startup may touch `model/data/noteai.db`.

### 下一步最小可行计划

1. Fix mobile chat responsive layout in `NoteAI_Pro_Demo_Framer.html` with minimal CSS/layout changes.
2. Fix `开始诊断` navigation so explicit diagnosis entry resets upload mode to diagnosis, while `生成爆文` still uses generation mode.
3. Rerun browser checks at desktop and `390x844`.
4. Rerun `.venv/bin/python -m unittest tests.test_frontend_report_static`.
5. Rerun `npm run test:e2e`.
6. Only after confirmation, design a safe temporary-DB local API smoke for auth/pricing/profile paths.

### 不能在未经确认的情况下修改

- Auth/session/password/token logic.
- Billing, credit, top-up, subscription, payment, refund, and quota logic.
- Database schema, default local DB files, migrations, seed/reset/cleanup.
- `.env`, `model/.env`, secrets, tokens, provider keys, and production config.
- Live AI API calls, OCR/video provider calls, crawler/worker runs, deploys, payment/email/SMS operations.

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

## 2026-07-05 Stage Update — Static UI Premium Polish

### 1. 本轮完成了什么

- 按用户要求，没有引入 React、shadcn 依赖或新生产依赖，直接在现有静态 HTML/CSS/JS 中手工吸收 shadcn / MagicUI / assistant-ui 的设计语言。
- AI Chat 页升级为更像 assistant 工作台的空态：玻璃拟态面板、3 个上下文/弱项/版本状态卡、图标化主 CTA、图标化快捷指令、消息气泡和 thinking chain 视觉增强。
- 上传/素材处理页增加 dropzone、上传卡、内容方向、商家策略、约束标签和生成三步卡片的高级 hover、边框、阴影、网格背景和响应式样式。
- 定价/订阅页的静态 fallback 与后端动态套餐渲染同时接入 `pricing-card` / `billing-info-card` / `topup-card` 等样式类，提升商业化套餐卡、扣费说明和充值卡片质感。
- 成长档案、笔记库、V0.4 landing/agent 动画卡片、处理进度相关卡片获得统一 premium glass/card/hover 视觉层。
- 用 Codex 内置浏览器验证了 chat/upload/pricing/profile/library 页面桌面和 390px 移动宽度没有横向溢出。

### 2. 修改了哪些文件

- `NoteAI_Pro_Demo_Framer.html`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `NoteAI_Pro_Demo_Framer.html`: 添加 premium UI tokens、动效、chat 空态 DOM、快捷指令图标、上传/定价/笔记库/档案/landing 的视觉 class 与样式；不改变 API payload、上传函数、计费逻辑、认证逻辑或真实 AI 调用逻辑。
- `.codex/handoffs/current-task.md`: 按项目规则记录本阶段完成内容、修改文件、验证命令、风险和下一步计划。

### 4. 做了哪些关键决策

- 不安装 `shadcn/ui`、MagicUI、assistant-ui 或任何新依赖；继续维持单文件静态前端架构。
- 只做视觉和交互质感增强，避免重构业务流程、API 调用、认证、计费、数据库、crawler/worker。
- 定价页同时覆盖静态 fallback 和动态 `renderPricingConfig()`，避免后端 API 不可用时 UI 退回旧样式。
- 移动端 chat 保持“笔记预览在上、对话区在下”的前一轮修复，并把新增 agent cards 压成单列。

### 5. 运行了哪些命令

- `git diff --check`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `npm run test:e2e`
- `lsof -nP -iTCP:5173 -sTCP:LISTEN`
- `python3 -m http.server 5173 --bind 127.0.0.1`
- Codex 内置浏览器 smoke: 打开 `chat`, `upload`, `pricing`, `profile`, `library`，并切到 `390x844` 检查 chat 移动布局。

### 6. 每个命令的结果

- `git diff --check`: passed，无空白/补丁格式问题。
- `.venv/bin/python -m unittest tests.test_frontend_report_static`: passed，7 tests OK。
- `npm run test:e2e`: passed，3 Playwright tests OK。
- `lsof -nP -iTCP:5173 -sTCP:LISTEN`: 没有进程监听，随后临时启动静态服务。
- `python3 -m http.server 5173 --bind 127.0.0.1`: 本地静态服务启动成功；browser smoke 后已用 Ctrl-C 关闭。
- 内置浏览器 smoke: desktop `chat/upload/pricing/profile/library` 均 active 正确；`overflowX=false`；移动 `390x844` chat `scrollWidth=390`，agent card 单列，未发现横向溢出。

### 7. 当前仍然失败的问题

- 本阶段没有发现新的测试失败。
- 静态 smoke 中 pricing 页出现 `[pricing] use static fallback TypeError: Failed to fetch` warning，原因是只启动了静态前端、没有启动后端 API；这是现有降级路径，不是本轮新增失败。

### 8. 当前未完成工作

- 尚未做完整真实 AI 链路回归。
- 尚未做登录后真实 profile/library 数据态视觉检查。
- 尚未做 admin 后台 UI 高级化。
- 尚未做全量 unit discovery、`py_compile`、quality gate、production readiness gate、Docker compose config。

### 9. 当前最高风险

- `NoteAI_Pro_Demo_Framer.html` 是大型单文件，视觉层改动较大，未来继续叠加时容易产生 CSS 选择器冲突。
- 真实登录数据态的 profile/library 卡片依赖后端返回内容，当前只验证了未登录/静态 DOM 状态。
- 定价页按钮仍连接现有升级/充值入口；本轮只改样式，没有验证真实 billing mutation，不能据此判断支付/扣费链路。

### 10. 下一步最小可行计划

- 用户人工打开前端，重点检查 chat、upload、pricing、profile/library 的视觉观感和交互手感。
- 若用户指出具体 UI 不满意，优先在 `NoteAI_Pro_Demo_Framer.html` 做小范围视觉修补。
- 如需进入功能回归，再启动本地 API/admin/frontend 做非生产 smoke；涉及真实 AI 调用前继续输出 Live API Run Plan。

### 11. 哪些地方不能在未经确认的情况下修改

- 不能引入 React/shadcn/MagicUI/assistant-ui/npm 生产依赖。
- 不能修改 auth/session/admin 权限、billing/credits/payment、DB schema/migration、crawler/worker 写入逻辑、生产配置或 `.env`。
- 不能运行真实 AI 批量调用、crawler、worker、deploy、DB reset/seed/migration、真实支付/邮件/短信。
- 不能删除、提交或处理未跟踪的本地 `测试图片/` 目录，除非用户确认。

## 2026-07-05 Stage Update — User Frontend Read-only UI Audit

### 1. 本轮完成了什么

- 按用户要求打开用户前端页面，并在 Codex 内置浏览器中做只读 UI 审核。
- 审核范围：landing、upload、chat、pricing、profile、library。
- 覆盖桌面视口和移动端 `390x844` 视口。
- 本轮未修改业务代码。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录本轮只读审核发现、运行命令和下一步计划。

### 4. 做了哪些关键决策

- 审核阶段只记录问题，不直接修复。
- 保留本地静态服务运行，方便用户继续在浏览器中人工点验用户页面。
- 不启动后端 API/admin，不调用真实 AI API，不触碰 DB、认证、计费或生产配置。

### 5. 运行了哪些命令

- `lsof -nP -iTCP:5173 -sTCP:LISTEN`
- `python3 -m http.server 5173 --bind 127.0.0.1`
- Codex 内置浏览器导航/截图/DOM 检查：桌面 `landing/upload/chat/pricing/profile/library`。
- Codex 内置浏览器 viewport `390x844` 检查：移动端 `landing/upload/chat/pricing/profile/library`。

### 6. 每个命令的结果

- `lsof -nP -iTCP:5173 -sTCP:LISTEN`: 初始没有服务监听。
- `python3 -m http.server 5173 --bind 127.0.0.1`: 本地静态用户前端启动成功。
- 桌面浏览器审核：各页面 active 正确，未发现横向溢出。
- 移动端浏览器审核：各页面 active 正确，`overflowX=false`，chat 左侧笔记预览在移动端高度为 220px，未发现横向溢出。

### 7. 当前仍然失败的问题

- 定价页桌面宽度下 5 张套餐卡呈现为 4 + 1，最后一张单独掉到第二行，视觉上不够商业化。
- `pricing` 页面不在主导航高亮体系中，进入定价页后顶部导航没有对应 active 项，用户可能不知道当前所在位置。
- `library` 页面也不是主导航项，未登录态下顶部没有 active 高亮。
- 未登录的 profile/library 空态过于空，缺少和新版 premium UI 一致的卡片容器、价值说明或二级 CTA。
- 移动端 chat 空态可用，但第三张 agent card 首屏下方被截断；不是功能错误，但首屏信息密度偏高。
- 静态前端单独运行时 pricing 会尝试请求后端 billing tiers 并 fallback；这是现有预期 warning，不是新失败。

### 8. 当前未完成工作

- 未检查登录后的真实 profile/library 数据态。
- 未检查真实上传、真实 AI 生成、真实对话优化链路。
- 未检查 admin 页面。
- 未做本轮 UI 问题修复。

### 9. 当前最高风险

- 视觉高级化已经覆盖多个页面，但未登录态、定价布局和导航信息架构仍可能影响用户第一印象。
- 登录态数据卡片可能出现真实文案长度、分数、账单数据导致的布局问题，需要后端/测试账号配合验证。

### 10. 下一步最小可行计划

- 优先修复定价页桌面套餐卡布局，让 5 张卡形成更均衡的 5 列或 3+2 布局。
- 为 profile/library 未登录态增加统一 premium empty-state card。
- 给 pricing/library 增加明确入口/导航状态，避免页面无 active 高亮。
- 微调移动端 chat 空态高度和卡片密度，让 CTA 更早进入首屏。

### 11. 哪些地方不能在未经确认的情况下修改

- 不改后端 billing 规则、真实扣费、套餐语义或支付相关逻辑。
- 不改 auth/session/admin 权限。
- 不引入 React/shadcn/MagicUI/assistant-ui/npm 生产依赖。
- 不运行真实 AI API、DB migration/seed/reset、crawler/worker、deploy。
- 不处理未跟踪的 `测试图片/` 目录。

## 2026-07-05 Stage Update — Fix Four User UI Issues

### 1. 本轮完成了什么

- 修复定价页桌面 `4 + 1` 套餐卡布局：桌面改为 5 张同排，平板 3 列，移动 1 列。
- 修复 pricing/library 页面缺少导航状态的问题：顶部右侧快捷入口增加 `is-active` 状态，`showPage()` 会同步高亮。
- 升级 profile/library 未登录和空列表状态：改为 premium glass empty-state card，增加价值说明、3 个小能力卡和双 CTA。
- 微调移动端 chat 空态：降低笔记预览高度，压缩空态卡间距和 agent 卡密度，让 CTA 进入首屏。

### 2. 修改了哪些文件

- `NoteAI_Pro_Demo_Framer.html`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `NoteAI_Pro_Demo_Framer.html`: 修复用户审核发现的 4 个 UI 问题；仅改静态 HTML/CSS/前端展示状态，不改后端、API、数据库、认证、计费或真实 AI 逻辑。
- `.codex/handoffs/current-task.md`: 按项目规则记录阶段性修复、命令、结果、风险和下一步。

### 4. 做了哪些关键决策

- 定价页不改变套餐、积分、价格和扣费语义，只改布局和卡片排布。
- pricing/library 不加入主 nav-tab 数组，避免挤压主导航；改为右侧快捷入口 active 状态。
- 空态升级为展示层，不改变登录、注册、鉴权逻辑。
- 移动 chat 只压缩首屏密度，不隐藏核心说明和 CTA。

### 5. 运行了哪些命令

- `git diff --check`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `npm run test:e2e`
- Codex 内置浏览器 QA: desktop `pricing/profile/library/chat`，mobile `chat` at `390x844`。
- Codex 内置浏览器 console check filtered by `four-ui-fixes`。

### 6. 每个命令的结果

- `git diff --check`: passed。
- `.venv/bin/python -m unittest tests.test_frontend_report_static`: passed，7 tests OK。
- `npm run test:e2e`: passed，3 Playwright tests OK。
- Browser QA:
  - pricing: 5 张套餐卡同一行，`pricingRows=1`，无横向溢出。
  - profile: 未登录 empty-state card 可见。
  - library: 未登录 empty-state card 可见，library 快捷入口 active。
  - chat mobile: `noteHeight=168`，CTA 在 `390x844` 首屏内可见，无遮挡，无横向溢出。
- Console filtered by `four-ui-fixes`: no current warnings/errors。

### 7. 当前仍然失败的问题

- 本阶段没有发现新的测试失败。
- 静态前端单独运行时，如访问 pricing 仍可能触发后端 billing tiers fetch fallback；本轮 filtered 当前 QA 未出现相关 warning。

### 8. 当前未完成工作

- 未检查登录后的真实 profile/library 数据态。
- 未检查真实 billing mutation、升级/充值后端行为。
- 未检查真实 AI 上传/生成/chat 链路。
- 未检查 admin 后台 UI。

### 9. 当前最高风险

- 登录态真实数据可能出现长标题、长正文、账单记录、评分等导致的布局压力，需要测试账号数据态继续 QA。
- 顶部右侧 pricing/library active 是快捷入口状态，不是主导航项；如果后续要做完整信息架构，仍需设计导航体系。

### 10. 下一步最小可行计划

- 由用户人工检查这 4 个 UI 修复是否满意。
- 如继续 UI 打磨，优先看登录态 profile/library 和生成后的 chat 活跃态。
- 如进入功能测试，启动本地 API/admin/frontend，并按非生产 smoke 策略检查登录、生成、保存、笔记库、档案链路。

### 11. 哪些地方不能在未经确认的情况下修改

- 不改价格、套餐、积分扣费、支付/充值/升级接口语义。
- 不改认证、session、admin 权限、DB schema/migration。
- 不引入 React/shadcn/MagicUI/assistant-ui/npm 生产依赖。
- 不运行真实 AI API、DB reset/seed/migration、crawler/worker、deploy。
- 不处理未跟踪的 `测试图片/` 目录。

## 2026-07-05 Stage Update — Manual Function Testing Setup

### 1. 本轮完成了什么

- 按用户要求进入“用户亲自逐项测试功能”的准备阶段。
- 启动本地用户 API、Admin API 和静态前端页面，供用户手动测试。
- 发现普通 `./start_all.sh start` 在 Codex 单次命令结束后进程会被清理，因此改用本机 `screen` 会话 `noteai-local` 承载本地服务。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录本轮测试准备、启动方式、命令结果、当前风险和下一步，便于后续继续接手。

### 4. 做了哪些关键决策

- 不修改业务代码、不改配置、不运行数据库迁移/seed/reset/deploy。
- 用 `screen` 保持本地服务持续运行，避免 Codex 命令执行器清理后台进程导致用户测试中断。
- 本轮只做本地 health/smoke 检查，没有触发真实 AI API 调用。

### 5. 运行了哪些命令

- `tail -n 120 /tmp/noteai_api.log`
- `tail -n 120 /tmp/noteai_admin.log`
- `tail -n 80 /tmp/noteai_frontend.log`
- `ls -l /tmp/noteai_*.pid 2>/dev/null || true`
- `lsof -nP -iTCP:5173 -sTCP:LISTEN; lsof -nP -iTCP:8000 -sTCP:LISTEN; lsof -nP -iTCP:8001 -sTCP:LISTEN`
- `ps -p $(cat /tmp/noteai_api.pid 2>/dev/null) -o pid,ppid,stat,command 2>/dev/null || true`
- `ps -p $(cat /tmp/noteai_admin.pid 2>/dev/null) -o pid,ppid,stat,command 2>/dev/null || true`
- `ps -p $(cat /tmp/noteai_frontend.pid 2>/dev/null) -o pid,ppid,stat,command 2>/dev/null || true`
- `sed -n '1,260p' start_all.sh`
- `./start_all.sh status`
- `command -v tmux || true`
- `command -v screen || true`
- `screen -S noteai-local -X quit >/dev/null 2>&1 || true`
- `screen -dmS noteai-local bash -lc 'cd /Users/openclaw/Desktop/noteai && ./start_all.sh start; while true; do sleep 3600; done'`
- `screen -ls | sed -n '1,20p'`

### 6. 每个命令的结果

- 日志显示主 API、Admin API、前端都曾成功启动，且 health/页面请求返回成功。
- 初始 `lsof` 和 `./start_all.sh status` 显示三个端口未持续监听，确认普通后台启动不适合当前 Codex 执行环境。
- `ps` 检查显示 pid 文件存在但对应进程已不存在。
- `start_all.sh` 检查确认脚本只启动本地 `127.0.0.1` 的 API/Admin/静态前端，未包含 migration/seed/reset/deploy。
- `tmux` 不可用；`screen` 可用。
- 使用 `screen` 启动后，`./start_all.sh status` 返回：主 API `ok`、模型标签 `v0.4-composite`、Admin API `ok`、前端页面运行中。
- `lsof` 确认 `127.0.0.1:8000`、`127.0.0.1:8001`、`127.0.0.1:5173` 均在监听。
- `screen -ls` 确认存在 detached 会话 `noteai-local`。

### 7. 当前仍然失败的问题

- 未发现本地服务启动失败。
- 尚未进行用户逐项功能测试；具体功能问题需要用户人工操作后反馈。

### 8. 当前未完成工作

- 未执行真实 AI 生成/诊断/chat live 验证。
- 未执行上传、保存、笔记库、档案、计费、Admin 后台的人工全链路测试。
- 未检查登录态真实数据下的 UI 长文案/长列表布局。

### 9. 当前最高风险

- 用户手动测试若触发真实 AI 生成/诊断，可能产生外部 API 成本；需要控制样本量并避免批量/并发调用。
- 认证、计费、积分、Admin 权限、DB 写入链路均属于高风险区域，发现问题后应先最小定位，不做扩大重构。

### 10. 下一步最小可行计划

- 用户从本地前端页面开始逐项人工测试。
- 每发现一个问题，记录页面、操作步骤、期望结果、实际结果、是否可复现、是否触发真实 AI/API/上传。
- 我根据用户反馈先复现，再做最小修复，并在每个阶段继续更新本 handoff。

### 11. 哪些地方不能在未经确认的情况下修改

- 不修改生产配置、`.env`、API key、token、secret、数据库连接串。
- 不运行 DB migration/seed/reset/deploy/clean。
- 不触发真实支付、真实邮件、真实短信、部署或生产写操作。
- 不批量调用真实 AI API，不全量跑数据，不并发压测。
- 不处理未跟踪的 `测试图片/` 目录，除非用户确认。

## 2026-07-05 Stage Update — Full Manual Test Surface Policy

### 1. 本轮完成了什么

- 用户明确要求：只要由用户亲自测试系统，就必须开放完整测试面，而不是只开放单一模块。
- 确认当前本地用户 API、Admin API 和前端仍在运行，可继续进行全量人工功能测试。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录用户对测试开放范围的明确要求，作为后续测试/修复协作规则。

### 4. 做了哪些关键决策

- 后续用户人工测试时，默认把前端页面、用户 API、Admin API、上传、诊断、生成、Chat、笔记库、档案、计费展示、worker/crawler 相关入口都视为可测试对象。
- 不用 mock 结果冒充真实链路；如果用户测试触发真实 AI，需要如实记录真实成功/失败。
- 仍保留生产安全边界：不开放真实支付、真实邮件/短信、部署、生产写操作、DB reset/seed/migration、批量/并发真实 AI 调用。

### 5. 运行了哪些命令

- `./start_all.sh status`

### 6. 每个命令的结果

- `./start_all.sh status`: 主 API `ok`，模型标签 `v0.4-composite`；Admin API `ok`；前端页面运行中。

### 7. 当前仍然失败的问题

- 暂无新增失败；等待用户全量人工测试反馈。

### 8. 当前未完成工作

- 尚未由用户完成逐项功能测试。
- 尚未复现用户实际测试中发现的问题。

### 9. 当前最高风险

- 全量人工测试可能触发真实 AI API 成本、DB 写入、上传文件写入和计费/积分状态变化；需要将测试保持在本地/测试环境，并避免生产副作用。

### 10. 下一步最小可行计划

- 用户从前端开始全量测试。
- 每发现一个问题，我先定位和复现，再按最小改动修复。
- 每完成一个阶段性修复，继续更新本 handoff。

### 11. 哪些地方不能在未经确认的情况下修改

- 不修改生产配置、`.env`、secret、token、API key 或数据库连接串。
- 不运行 DB migration/seed/reset/deploy/clean。
- 不触发真实支付、真实邮件、真实短信、部署或生产写操作。
- 不进行无上限真实 AI 调用、批量数据调用或并发压测。
- 不处理未跟踪的 `测试图片/` 目录，除非用户确认。

## 2026-07-05 Stage Update — Library Version Chain Investigation

### 1. 本轮完成了什么

- 调查用户反馈的“笔记库应按初始卡片归档诊断/生成/多轮对话优化版本，但现在没有”的问题。
- 只读检查前端、后端 API、DB schema 和当前本地 DB 聚合形态；未修改业务代码。
- 确认后端 `/notes` 仍具备 `parent_id/version/score_trend/versions` 版本组能力，前端笔记库也调用 `/notes?grouped=true` 展示版本组。
- 确认当前断点主要是：诊断结果没有稳定进入 `/notes` 初始卡片；`/chat/start` 没接收/保存 `note_id`，导致 chat 自动保存时无法挂到初始卡片。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录本轮调查原因、证据、命令、风险和下一步最小修复方向。

### 4. 做了哪些关键决策

- 本轮先查原因，不做修复。
- 不读取/输出笔记标题正文或用户内容，只看代码和 DB 聚合统计。
- 不触发真实 AI API，不执行 DB 写入、迁移、seed、reset。

### 5. 运行了哪些命令

- `rg -n "library|note library|notes|saved|diagnos|chat|version|优化|笔记库|save" NoteAI_Pro_Demo_Framer.html | head -n 240`
- `rg -n "@app\\.(get|post|put|delete).*notes|/notes|chat/start|chat/message|saved_diagnoses|diagnoses|create_note|save_note|version" model/api.py model/db.py model/*.py tests -g '!model/data/**'`
- `git diff --stat`
- `git diff -- NoteAI_Pro_Demo_Framer.html | rg -n "library|notes|save|chat|version|diagnos|showPage|profile|pricing" -C 3`
- `rg -n "notes|library|chat|save|version|diagnos" tests package.json`
- `sed -n '10180,10390p' model/api.py`
- `sed -n '12780,13280p' model/api.py`
- `sed -n '6800,7100p' NoteAI_Pro_Demo_Framer.html`
- `sed -n '8200,8505p' NoteAI_Pro_Demo_Framer.html`
- `sed -n '9080,9635p' NoteAI_Pro_Demo_Framer.html`
- `sed -n '11080,11230p' model/api.py`
- `sed -n '5800,6085p' NoteAI_Pro_Demo_Framer.html`
- `rg -n "note_update|_last_note_id|ChatStartInput|note_id|parent_id|_saved_note_id|autoSaveGeneratedNote|autoSave" model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py`
- `sqlite3 model/data/noteai.db "SELECT source, COUNT(*) ... GROUP BY source ..."`
- `sqlite3 model/data/noteai.db "SELECT COALESCE(parent_id,'<root>') ..."`
- `sqlite3 model/data/noteai.db "SELECT COUNT(*) FROM notes n LEFT JOIN notes p ..."`
- `git blame -L 8160,8210 NoteAI_Pro_Demo_Framer.html`
- `git blame -L 9528,9625 NoteAI_Pro_Demo_Framer.html`
- `git blame -L 12808,12834 model/api.py`
- `git blame -L 12968,13070 model/api.py`
- `nl -ba model/api.py | sed -n '10210,10350p'`
- `nl -ba model/api.py | sed -n '12808,13090p'`
- `nl -ba NoteAI_Pro_Demo_Framer.html | sed -n '6848,6912p'`
- `nl -ba NoteAI_Pro_Demo_Framer.html | sed -n '8171,8210p'`
- `nl -ba NoteAI_Pro_Demo_Framer.html | sed -n '9528,9602p'`
- `nl -ba NoteAI_Pro_Demo_Framer.html | sed -n '9098,9158p'`

### 6. 每个命令的结果

- 代码搜索确认 `model/api.py` 的 `/notes` 保存接口支持 `parent_id`，`/notes?grouped=true` 会按根节点分组并返回 `version_count`、`score_trend`、`versions`。
- 前端 `loadLibrary()` 确认只读取 `/notes?grouped=true`，不合并 `/diagnoses`。
- 前端 `autoSaveGeneratedNote()` 只在生成完成后保存 source=`generate` 的初始笔记，未发现诊断完成后等价保存初始笔记的函数。
- 前端 `startChatOptimization()` 会传 `note_id: d._saved_note_id`，但后端 `ChatStartInput` 没有 `note_id` 字段。
- 前端 `startChatFromLibrary()` 只把 `note.id` 存在 `_chatParentNoteId` 前端变量，没有把 `note_id` 传给 `/chat/start`。
- 后端 chat 自动保存版本时用 `session.get("_last_note_id")` 作为 `parent_id`，但 `chat_start()` 没有初始化 `_last_note_id`。
- `_persist_chat_session()` 没有持久化 `note_id`，`_load_chat_session_from_db()` 也没有恢复 `_last_note_id`。
- 本地 DB 聚合只读统计：`chat` notes 28 条，其中 17 条是根、11 条是子版本；`generate` 9 条全部是根；`diagnose` 5 条全部是根；没有悬空 parent_id。
- blame 显示这套不完整契约主要来自初始化仓库时的实现，后续内容意图/约束改动没有补齐 `note_id`。

### 7. 当前仍然失败的问题

- AI 诊断完成后，只稳定保存到 `saved_diagnoses` 诊断历史，不稳定保存为 `/notes` 初始卡片，因此笔记库可能看不到诊断对应的初始卡片。
- 从诊断报告进入对话优化时 `_chatParentNoteId` 被置空，第一轮 chat 改写无法挂到诊断初始卡片。
- 从生成结果进入对话优化时，即使前端传了 `_saved_note_id`，后端也忽略 `note_id`，第一轮 chat 改写会变成新的根卡片。
- 从笔记库继续优化时，前端只在本地变量记住父笔记，后端没有接收，仍不能保证版本链归档。
- 服务重启后 chat session 恢复缺少 note_id/last_note_id，版本链可能继续断。

### 8. 当前未完成工作

- 未修复前后端契约。
- 未新增测试覆盖 `/notes` 版本链、诊断转笔记、生成转 chat、笔记库继续 chat。
- 未对已有本地拆散数据做修复/迁移。

### 9. 当前最高风险

- 这是用户核心资产归档链路，影响用户对“每次诊断/生成/优化都有历史和分数变化”的信任。
- 修复涉及后端保存行为和 DB 写入路径，必须小心避免重复保存、错误归属、跨用户挂载、成长记录重复。

### 10. 下一步最小可行计划

- 后端 `ChatStartInput` 增加可选 `note_id`，并在 `chat_start()` 校验该 note 属于当前用户后写入 session `_last_note_id`。
- `_persist_chat_session()` 写入 `chat_sessions.note_id`，`_load_chat_session_from_db()` 恢复 `_last_note_id`。
- 前端 `startChatFromLibrary()` 也向 `/chat/start` 传 `note_id: note.id`。
- 诊断进入 chat 前先确保诊断原文被保存为 `/notes` 初始卡片，source 建议为 `diagnose`，并把返回 id 写入 `_diagnoseResult._saved_note_id` / `_noteDetailData.id`。
- 增加针对 grouped notes/version chain 的后端单元测试；必要时加前端静态断言。

### 11. 哪些地方不能在未经确认的情况下修改

- 不直接修改或清洗现有本地/生产 DB 历史数据。
- 不批量回填旧 notes 版本链，除非用户确认迁移/修复策略。
- 不改变认证归属校验，不允许前端传入任意 note_id 后跨用户挂载。
- 不改变计费/积分/真实 AI 调用逻辑。
- 不输出用户笔记标题、正文、token、secret 或 `.env` 值。

## 2026-07-05 Stage Update — Fix Library Version Chain

### 1. 本轮完成了什么

- 修复“笔记库初始卡片 + 多轮对话优化版本 + 分数趋势”链路。
- 后端诊断成功后会同步创建 `/notes` 根笔记，并在诊断响应/历史 JSON 中返回 `saved_note_id`。
- `/chat/start` 新增可选 `note_id`，并校验该 note 必须属于当前登录用户。
- Chat 自动保存新版本时，使用当前 note 的真实版本号递增，挂到正确 `parent_id` 下。
- `chat_sessions` 持久化 `note_id`，服务重启后继续对话也能恢复版本链父节点。
- 前端从诊断报告、生成报告、笔记库详情进入 Chat 时都会传递 note id。
- 新增后端契约测试和前端静态测试，覆盖 note id 绑定和前端 payload。
- 已重启本地 `noteai-local` 服务会话，让用户测试页面使用最新代码。

### 2. 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `model/api.py`: 补齐诊断保存到笔记库、Chat note_id 契约、版本链父节点校验、chat session note_id 持久化和版本号递增。
- `NoteAI_Pro_Demo_Framer.html`: 让诊断/生成/笔记库三个进入 Chat 的入口传递当前 note id；兼容 `saved_note_id` 并在旧诊断缺失时尽力补根笔记。
- `tests/test_api_contracts.py`: 新增 `/chat/start` 绑定已有 note 与拒绝非本人 note 的后端测试。
- `tests/test_frontend_report_static.py`: 新增静态断言，防止前端再次丢失 note id 传递。
- `.codex/handoffs/current-task.md`: 记录本轮修复、验证、风险和下一步。

### 4. 做了哪些关键决策

- 版本链的真实归档由后端负责，不再只依赖前端本地变量。
- 诊断生成的初始笔记保存为 `source='diagnose'`，Chat 后续版本保存为 `source='chat'`。
- `note_id` 不能被前端任意挂载，后端必须按当前用户校验 ownership。
- 不回填/修复已有被拆散的历史本地数据，避免未确认的数据迁移风险。
- 不改计费、积分、真实 AI 调用、认证 token 或 DB schema。

### 5. 运行了哪些命令

- `python -m py_compile model/api.py`
- `.venv/bin/python -m py_compile model/api.py`
- `git diff --check`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_chat_start_binds_existing_note_for_library_version_chain tests.test_api_contracts.ApiContractTests.test_chat_start_rejects_note_id_not_owned_by_user tests.test_api_contracts.ApiContractTests.test_chat_ownership_is_checked_before_billing`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `npm run test:e2e`
- `screen -S noteai-local -X quit >/dev/null 2>&1 || true`
- `./start_all.sh stop >/tmp/noteai_stop.log 2>&1 || true`
- `screen -dmS noteai-local bash -lc 'cd /Users/openclaw/Desktop/noteai && ./start_all.sh start; while true; do sleep 3600; done'`
- `./start_all.sh status`
- `lsof -nP -iTCP:8000 -sTCP:LISTEN`
- `lsof -nP -iTCP:8001 -sTCP:LISTEN`
- `lsof -nP -iTCP:5173 -sTCP:LISTEN`
- local API smoke: register temporary local test user, create root note, start chat without sending messages.
- local `/notes` version-chain smoke: register temporary local test user, create root note + child note by `parent_id`, read `/notes?grouped=true`.
- `sqlite3 model/data/noteai.db "SELECT COUNT(*) FROM chat_sessions c JOIN users u ON c.user_id=u.id JOIN notes n ON c.note_id=n.id WHERE u.username LIKE 'noteai_smoke_%';"`
- `git status --short`
- `git diff --stat`

### 6. 每个命令的结果

- `python -m py_compile model/api.py`: failed，本机没有裸 `python` 命令。
- `.venv/bin/python -m py_compile model/api.py`: passed。
- `git diff --check`: passed。
- `.venv/bin/python -m unittest tests.test_frontend_report_static`: passed，8 tests OK。
- 窄范围后端 Chat 契约测试：passed，3 tests OK。
- `.venv/bin/python -m unittest tests.test_api_contracts`: passed，129 tests OK。期间有一条模拟 Moonshot 网络失败日志，是既有测试用例验证失败处理，不是真实 API 调用。
- `npm run test:e2e`: passed，3 Playwright tests OK。
- 本地服务重启后 `./start_all.sh status`: 主 API `ok`，模型 `v0.4-composite`；Admin API `ok`；前端运行中。
- `lsof`: `127.0.0.1:8000`、`127.0.0.1:8001`、`127.0.0.1:5173` 均在监听，当前 screen 会话为 `noteai-local`。
- local API smoke: passed，临时本地测试用户创建 1 个笔记库分组，Chat session 创建成功，根版本为 v1；未调用 `/chat/message`，未触发外部 AI。
- local DB 只读确认：至少 1 条本地测试 chat session 的 `note_id` 成功关联到 notes。
- local `/notes` version-chain smoke: passed，`groups=1`，`version_count=2`，子版本为 v2，`score_trend=[66.0,72.0]`。
- `git status --short`: 当前修改包括 handoff、前端 HTML、`model/api.py`、两份测试；未跟踪 `测试图片/` 仍存在且未处理。

### 7. 当前仍然失败的问题

- 尚未用真实 AI 完整跑“诊断 → Chat 重写 → 笔记库多版本”端到端，因为那会触发真实外部 AI 成本，需要用户测试时按样本执行。
- 旧的本地历史数据中，已经拆散成独立根卡片的 chat notes 没有自动回填修复。

### 8. 当前未完成工作

- 用户需要在前端手动验证：
  - 新诊断完成后是否出现在笔记库。
  - 从诊断报告点对话优化后，Chat 新版本是否归在同一张笔记库卡片下。
  - 从 AI 生成爆文点对话优化后，Chat 新版本是否归在生成根卡片下。
  - 从笔记库历史版本点继续优化后，新版本是否接在该卡片版本链下。
- 若用户要求，需要另行设计旧数据回填策略。

### 9. 当前最高风险

- 诊断成功现在会新增一条 `notes` 根笔记，这是正确产品行为，但会增加本地/生产 DB 写入；需要上线前确认不会和历史诊断页造成重复展示困惑。
- 旧历史诊断记录可能没有 `saved_note_id`，前端只在用户进入 Chat 时做最佳努力补根笔记；不做批量迁移前，旧数据体验不会完全一致。

### 10. 下一步最小可行计划

- 由用户手动测试笔记库链路，优先小样本：
  1. 新建一次 AI 内容诊断。
  2. 点“开始对话优化”，重写一版。
  3. 打开笔记库，确认同一卡片下至少 v1/v2 且分数趋势可见。
  4. 新建一次 AI 生成爆文，重复同样检查。
- 如果真实 AI 测试失败，先区分是 AI 输出未产生 `note_update`、后端保存失败、还是前端展示分组问题。

### 11. 哪些地方不能在未经确认的情况下修改

- 不批量迁移/清洗旧 notes 数据。
- 不删除旧诊断历史或旧拆散的 chat 根卡片。
- 不修改计费、积分、套餐、支付、认证、admin 权限。
- 不运行 DB migration/seed/reset/deploy。
- 不输出用户笔记正文、账号 token、secret、`.env` 值或真实 API key。

## 2026-07-05 Stage Update — Live Version Chain QA

### 1. 本轮完成了什么

- 按用户授权执行受控真实 AI 小样本验证，重点覆盖 3 条版本链：
  1. AI 内容诊断 -> 开始对话优化 -> 重写一版 -> 笔记库同一卡片 v1/v2。
  2. AI 生成爆文 -> 开始对话优化 -> 重写一版 -> 笔记库同一卡片 v1/v2。
  3. 笔记库打开历史版本 -> 继续对话优化 -> 新版本接在同一卡片下。
- 使用本地测试账号和本地 SQLite 数据库，未触发生产资源、支付、邮件、短信、部署或 DB migration/seed/reset。
- 前端笔记库页面完成可视验证：
  - 生成爆文卡片显示“共3个版本”，版本链为 v1/v2/v3，分数历程为 `69.9 -> 72.1 -> 71.6`。
  - 诊断卡片显示“共2个版本”，版本链为 diagnose v1 + 对话优化 v2，分数历程为 `42.2 -> 70.1`。
  - 从笔记库版本面板点击“继续优化”可进入对话优化上下文，页面显示当前笔记评分 `71.6`，未发送额外 AI 消息。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录本轮 live QA 的范围、结果、命令、风险和下一步。

### 4. 做了哪些关键决策

- live QA 使用合成测试输入，不使用真实用户数据。
- API/DB 验证和前端 UI 验证分开执行，先确认后端版本链，再确认页面展示。
- 对“继续优化”入口只验证进入 chat 上下文，不发送新消息，避免超出本轮真实 AI 调用计划。
- 生成流耗时较长时不并发重试，避免重复成本和状态污染。
- 第一次 live 脚本的 `/notes` 查询因测试脚本 token 传参错误返回 401；判定为测试脚本问题，不作为产品失败，并使用同一测试账号继续验证。

### 5. 运行了哪些命令

- `/tmp/noteai_live_chain_test.py`：受控 live 诊断链路脚本。
- `/tmp/noteai_live_chain_resume.py`：继续同一测试账号，完成生成链路与笔记库续写链路。
- `./start_all.sh status`
- `screen -ls`
- `find . -maxdepth 3 -type f \( -name '*.log' -o -name 'uvicorn*.out' -o -name '*server*.log' \)`
- Browser in-app QA:
  - 打开 `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=live-chain&page=landing`
  - 使用页面登录本地测试账号。
  - 进入笔记库、展开两个版本卡片、点击一次“继续优化”进入 chat 上下文。
  - 保存截图到 `/tmp/noteai-live-chain-library-expanded.png` 和 `/tmp/noteai-live-chain-chat-context.png`。
- `git status --short`
- `tail -n 120 .codex/handoffs/current-task.md`

### 6. 每个命令的结果

- live 诊断链路：passed。
  - `/analyze/stream` 返回 complete，`model_used=claude-routed-5-agents`，保存根 note。
  - `/chat/start` + `/chat/message` 返回 `note_update`，笔记库分组为 2 个版本，分数 `42.2 -> 70.1`。
- live 生成链路：passed。
  - `/generate/stream` 返回 complete，`model_used=claude-routed-5-agents-stream`，保存根 note，耗时约 234.2 秒。
  - `/chat/start` + `/chat/message` 返回 `note_update`，笔记库分组为 2 个版本，分数 `69.9 -> 72.1`，耗时约 78.1 秒。
- live 笔记库续写链路：passed。
  - 从最新生成版本继续 chat，返回 `quality_repaired` + `note_update`，同一分组扩展为 3 个版本，分数 `69.9 -> 72.1 -> 71.6`，耗时约 113.9 秒。
- 本地服务状态：主 API 8000 ok，Admin 8001 ok，前端 5173 运行中。
- Browser QA：passed。
  - 页面身份正确，加载非空，console 未见相关 error/warn。
  - 笔记库 UI 显示 2 张卡片：生成卡 `共3个版本`，诊断卡 `共2个版本`。
  - 展开生成卡可见 `AI生成 v1`、`对话优化 v2`、`对话优化 v3 · 最新`。
  - 展开诊断卡可见 `diagnose v1`、`对话优化 v2 · 最新`。
  - 点击“继续优化”进入对话优化，显示当前笔记评分 `71.6`。
- `git status --short`: 仍有已知修改文件和未跟踪 `测试图片/`；本轮未提交、未 staging、未 push。

### 7. 当前仍然失败的问题

- 未发现这 3 条重点版本链的产品失败。
- 已知非产品失败：第一次 live 脚本在已完成诊断与 chat 后，因测试脚本对 `/notes` 请求传 token 的方式错误导致 401；后续已用同账号补测并通过。
- Browser DOM snapshot 接口对当前页面报浏览器侧方法错误，已改用只读 DOM query、locator、console logs 和 screenshot 完成验证；不影响产品页面本身。

### 8. 当前未完成工作

- 还没有跑“用户手动从 UI 发起完整诊断/生成再 chat”的全流程，因为本轮 live AI 调用已覆盖 API/DB 真实链路，UI 层验证使用同一测试账号读取结果并验证入口。
- 旧历史数据中已经拆散的卡片仍未回填。
- 尚未提交当前修改。

### 9. 当前最高风险

- 真实 AI 生成耗时较长，生成流约 234 秒；上线体验需要考虑超时、进度反馈和 provider 慢响应。
- 旧数据不回填时，用户历史上已拆散的笔记可能不会自动合并。
- Browser 自动化的 DOM snapshot 能力不稳定，后续 UI QA 需要继续保留 screenshot/DOM query 备用路径。

### 10. 下一步最小可行计划

- 用户亲自打开页面复测这 3 条链路。
- 若用户发现 UI 操作路径和本轮 API/DB 结果不一致，优先定位：
  1. 前端是否把正确 `note_id` 传给 `/chat/start`。
  2. `/chat/message` 是否收到并保存 `note_update`。
  3. `/notes?grouped=true` 是否返回同一 `parent_id` 下的新版本。
  4. 笔记库是否刷新/展开了最新版本链。
- 如果需要处理旧数据，再单独设计可回滚的回填/合并方案，并先征得用户确认。

### 11. 哪些地方不能在未经确认的情况下修改

- 不批量回填、合并、删除或清洗旧 notes/chat_sessions 数据。
- 不修改计费、积分、套餐、支付、认证、admin 权限。
- 不运行 DB migration/seed/reset/deploy。
- 不触发额外真实 AI 批量调用、并发压测或超过 10 次调用的验证。
- 不输出 token、密码、`.env` 值、API key、secret、数据库连接串或完整用户内容。

## 2026-07-05 Stage Update — UI-Origin Version Chain Fixes

### 1. 本轮完成了什么

- 继续执行用户授权的 UI-origin live QA，覆盖从前端按钮发起的诊断、生成、对话优化和笔记库展示。
- 发现并修复两个真实 UI-origin 问题：
  1. Chat `note_update` 在后端写入 notes 之前先发给前端，用户很快进笔记库时可能看到旧版本链。
  2. AI 生成爆文完成后，报告页会自动打开最新诊断历史，导致生成报告被旧诊断报告覆盖。
- 修复后重新验证：
  - UI 诊断 -> 报告页 -> 对话优化重写 -> 笔记库显示同一卡片 v1/v2，分数 `36.9 -> 68.6`。
  - UI 生成爆文 -> 生成报告 -> 对话优化重写 -> 笔记库显示同一卡片 v1/v2，分数 `69.9 -> 72.5`。
  - 之前的笔记库历史版本继续优化链路仍显示同一卡片 v1/v2/v3，分数 `69.9 -> 72.1 -> 71.6`。

### 2. 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `model/api.py`: 将 chat 新版本保存到 notes 的动作提前到 `note_update` 事件之前，并在 `note_update` 中返回 `saved_note_id`，避免前端看到“生成完成”但笔记库尚未落库的竞态。
- `NoteAI_Pro_Demo_Framer.html`: 前端接收 `note_update.saved_note_id` 并更新当前 `_chatParentNoteId`；生成报告模式不再自动打开诊断历史；生成 complete 等待 `autoSaveGeneratedNote` 完成，确保生成报告进入 Chat 时有根 note id。
- `tests/test_api_contracts.py`: 新增契约测试，确认 `note_update.saved_note_id` 对应已插入 notes 的新版本。
- `tests/test_frontend_report_static.py`: 新增静态断言，锁住前端 note id 传递、生成报告上下文和生成保存等待逻辑。
- `.codex/handoffs/current-task.md`: 记录本轮 live QA、修复、命令、结果和风险。

### 4. 做了哪些关键决策

- 后端保存顺序优先保证一致性：先保存 notes，再发送 `note_update`。
- `saved_note_id` 作为向后兼容的新增字段，不改变已有 `note_update` 字段。
- 生成报告页和诊断报告页共用容器，但生成模式禁止自动展开诊断历史详情，避免上下文污染。
- 不回填本轮测试中因旧逻辑产生的单独 generate v1 测试卡；它是本地测试数据，不影响产品修复。
- 达到本轮 live API 调用上限后停止，不继续触发额外真实 AI。

### 5. 运行了哪些命令

- 受控 UI live 操作：前端诊断、诊断后 chat 重写、前端生成、生成后 chat 重写、笔记库检查。
- SQLite 只读核对 notes/chat_sessions version chain。
- `.venv/bin/python -m py_compile model/api.py`
- `git diff --check`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_chat_note_update_is_emitted_after_version_save tests.test_api_contracts.ApiContractTests.test_chat_start_binds_existing_note_for_library_version_chain tests.test_api_contracts.ApiContractTests.test_chat_start_rejects_note_id_not_owned_by_user`
- `./start_all.sh status`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `npm run test:e2e`
- Browser QA 截图保存到 `/tmp/noteai-final-library-version-chains.png`。

### 6. 每个命令的结果

- UI live 诊断链路：passed，笔记库显示 `共2个版本`，分数 `36.9 -> 68.6`。
- UI live 生成链路：passed，笔记库显示 `共2个版本`，分数 `69.9 -> 72.5`。
- 既有历史版本续写链路：仍 passed，笔记库显示 `共3个版本`，分数 `69.9 -> 72.1 -> 71.6`。
- SQLite notes 检查：确认 UI 生成 v2 的 `parent_id` 指向生成根 note，`version=2`，`source=chat`。
- `.venv/bin/python -m py_compile model/api.py`: passed。
- `git diff --check`: passed。
- `.venv/bin/python -m unittest tests.test_frontend_report_static`: passed，9 tests OK。
- 窄范围后端契约测试：passed，3 tests OK。
- `./start_all.sh status`: 主 API 8000 ok，Admin 8001 ok，前端 5173 运行中。
- `.venv/bin/python -m unittest tests.test_api_contracts`: passed，130 tests OK；期间有既有模拟/失败处理日志，不是真实 live 验证失败。
- `npm run test:e2e`: passed，3 tests OK。

### 7. 当前仍然失败的问题

- 本轮 3 条重点版本链没有发现剩余失败。
- 体验风险仍在：前端会展示较长模型“深度思考”文本，包含英文推理/草稿过程，后续需要决定是否折叠、摘要化或不展示原始 thinking。
- 真实 AI 生成耗时偏长，部分生成流接近数分钟。

### 8. 当前未完成工作

- 未做旧数据回填/合并。
- 未处理本地测试过程中由旧逻辑产生的一张单独 generate v1 测试卡。
- 未提交当前修改。
- 未继续触发更多 live API，因为本轮已达到约定的最多 10 次真实 AI 成本 endpoint。

### 9. 当前最高风险

- 上线前需要处理 thinking 展示策略，避免把模型草稿/推理过程原样暴露给普通用户。
- provider 慢响应会影响处理进度页体验，需要后续优化超时、阶段提示和降级策略。
- 历史数据不回填时，旧卡片仍可能保持拆散状态。

### 10. 下一步最小可行计划

- 用户在当前本地页面亲自复测三条主链路。
- 若复测通过，准备 checkpoint/commit 范围。
- 若复测发现展示问题，优先看 `/notes?grouped=true` 返回、`note_update.saved_note_id`、以及前端是否使用最新 HTML。
- 单独开一轮处理 thinking 展示和生成耗时体验，不和版本链修复混在一起。

### 11. 哪些地方不能在未经确认的情况下修改

- 不批量改/删/合并旧 notes、diagnoses、chat_sessions。
- 不修改计费、积分、套餐、支付、认证、admin 权限。
- 不运行 DB migration/seed/reset/deploy。
- 不再触发额外真实 AI 批量验证，除非用户重新确认 live API 调用计划。
- 不输出 token、密码、`.env` 值、API key、secret、数据库连接串或完整用户内容。

## 2026-07-05 Stage Update — Commit Authorization And Thinking UX Decision

### 1. 本轮完成了什么

- 用户确认允许 stage / commit / push 当前版本链修复。
- 用户明确产品偏好：不建议折叠摘要或隐藏原始 thinking，更愿意让用户看到深度思考/草稿过程。
- 将该产品决策记录为后续 UI/体验方向：当前不把 thinking 展示视为必须修复的问题，只把其作为需要设计呈现方式和边界的透明体验能力。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录用户对 commit/push 的授权，以及保留深度思考/草稿过程展示的产品决策。

### 4. 做了哪些关键决策

- 本次 commit scope 仅包含已确认的 5 个修改文件：
  - `.codex/handoffs/current-task.md`
  - `NoteAI_Pro_Demo_Framer.html`
  - `model/api.py`
  - `tests/test_api_contracts.py`
  - `tests/test_frontend_report_static.py`
- 不 stage 未跟踪目录 `测试图片/`。
- 不把 raw thinking 展示作为当前阻塞缺陷；后续若优化，也应围绕可读性、层级、展开/收起体验或用户控制，而不是默认隐藏。

### 5. 运行了哪些命令

- `git branch --show-current`
- `git remote -v`
- `git status --short`
- `git diff --stat`

### 6. 每个命令的结果

- 当前分支：`codex/quality-stabilization-real-chain`。
- remote：`origin` 指向 GitHub repo `iamyusen1314/noteai`。
- 当前待提交修改为上述 5 个文件。
- 未跟踪目录 `测试图片/` 仍存在，未纳入提交计划。

### 7. 当前仍然失败的问题

- 暂无新增失败。

### 8. 当前未完成工作

- 尚未执行 stage / commit / push；下一步立即执行。

### 9. 当前最高风险

- commit scope 较大，主要因为 handoff 记录较长、前端单文件体量大；提交前需确保只 stage 预期文件。

### 10. 下一步最小可行计划

- `git add` 5 个确认文件。
- `git commit` 创建 checkpoint。
- `git push origin codex/quality-stabilization-real-chain`。
- 最终报告 commit hash、push 结果和未跟踪文件状态。

### 11. 哪些地方不能在未经确认的情况下修改

- 不 stage / commit `测试图片/`。
- 不修改生产配置、secrets、`.env`。
- 不运行 migration/seed/reset/deploy。

## 2026-07-05 Stage Update — Git Commit And Push Result

### 1. 本轮完成了什么

- 已按用户授权 stage / commit / push 版本链修复。
- 主修复 commit 已推送到 `origin/codex/quality-stabilization-real-chain`。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录实际 Git stage / commit / push 结果，避免交接文件停留在“准备执行”状态。

### 4. 做了哪些关键决策

- 主修复 commit 仅包含 5 个确认文件。
- 未跟踪目录 `测试图片/` 没有 stage、commit 或 push。

### 5. 运行了哪些命令

- `git add .codex/handoffs/current-task.md NoteAI_Pro_Demo_Framer.html model/api.py tests/test_api_contracts.py tests/test_frontend_report_static.py`
- `git status --short`
- `git diff --cached --stat`
- `git diff --check --cached`
- `git commit -m "fix note version chain continuity"`
- `git push origin codex/quality-stabilization-real-chain`
- `git rev-parse --short HEAD`

### 6. 每个命令的结果

- `git add`: 成功 stage 5 个确认文件。
- `git status --short`: 5 个确认文件已暂存；`测试图片/` 仍未跟踪。
- `git diff --cached --stat`: 5 files changed，`2329 insertions(+), 113 deletions(-)`。
- `git diff --check --cached`: passed。
- `git commit -m "fix note version chain continuity"`: created commit `d3861e9`。
- `git push origin codex/quality-stabilization-real-chain`: pushed `dd7cfad..d3861e9` to GitHub。
- GitHub remote 提示 default branch 有 1 个 low vulnerability；这不是本轮提交引入的验证失败。
- `git rev-parse --short HEAD`: `d3861e9`。

### 7. 当前仍然失败的问题

- 暂无本轮 Git 操作失败。

### 8. 当前未完成工作

- 需要把本 handoff 结果记录再提交并推送，保持工作区干净。

### 9. 当前最高风险

- `测试图片/` 仍是未跟踪目录，后续若要处理需要用户单独确认。

### 10. 下一步最小可行计划

- stage 本 handoff 记录。
- commit 为 handoff 结果记录。
- push 到同一分支。
- 最终报告两个 commit 和当前 Git 状态。

### 11. 哪些地方不能在未经确认的情况下修改

- 不 stage / commit / push `测试图片/`。
- 不运行 deploy、migration、seed、reset。

## 2026-07-05 Stage Update — Admin XHS UI Rendered Smoke

### 1. 本轮完成了什么

- 完成 Admin UI rendered smoke，重点验证 `model/admin.html` 中新增的 XHS freshness / missing domains / deadline / sidecar cards、XHS 行业证据账本、XHS Health 最近记录。
- 使用本地临时 mock API 渲染 Admin 页面，没有读取或输出 `.env`、admin token、API key、Cookie、数据库连接串。
- 临时服务仅绑定 `127.0.0.1:5191`，验证后已关闭。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 按用户要求记录阶段性验证结果、命令、风险和下一步。

### 4. 做了哪些关键决策

- Admin UI smoke 先用 mock admin API 做纯渲染验证，避免依赖真实 admin 凭据或泄露敏感配置。
- 浏览器安全策略拒绝 `data:` 页面后，改用 `/tmp/noteai-admin-smoke.html` + 本地 HTTP 服务渲染；这不修改 repo 业务代码。
- 本轮只验证新卡片展示，不触发真实 crawler、worker、AI 或生产环境操作。

### 5. 运行了哪些命令

- `sed -n '1,220p' /Users/openclaw/.codex/plugins/cache/openai-bundled/browser/26.623.101652/skills/control-in-app-browser/SKILL.md`
- `sed -n '1,260p' /Users/openclaw/.codex/plugins/cache/openai-curated/build-web-apps/d6169bef/skills/frontend-testing-debugging/SKILL.md`
- `sed -n '430,560p' model/admin.html`
- `rg -n "xhs-|loadXhs|showPage|ADMIN_BASE|crawler" model/admin.html`
- `sed -n '560,640p' model/admin.html`
- `sed -n '880,980p' model/admin.html`
- `python3 -m http.server 5191 --bind 127.0.0.1 --directory /tmp`
- Browser runtime actions: navigate to `http://127.0.0.1:5191/noteai-admin-smoke.html`, mock login, click `爬虫管理`, inspect rendered text, inspect console logs, capture screenshot.

### 6. 每个命令的结果

- Browser skill and frontend testing skill instructions read successfully.
- Admin HTML inspection confirmed XHS cards/table render IDs and loaders:
  - `#xhs-fresh-ok`
  - `#xhs-missing-count`
  - `#xhs-deadline`
  - `#xhs-sidecar`
  - `#xhs-fresh-table`
  - `#xhs-health-table`
- Local temp server started on `127.0.0.1:5191` and was stopped after smoke.
- Browser smoke result:
  - Page identity: `NoteAI Pro — 后台管理`
  - Login mock succeeded and Admin shell rendered.
  - `爬虫管理` page rendered.
  - XHS freshness card displayed `达标`.
  - Missing domains displayed `0` and `全部行业已满足`.
  - Deadline rendered as a short local date/time.
  - Sidecar card displayed `已配置`.
  - Ledger table rendered sample rows for `美食`、`美妆`、`家居`.
  - Health table rendered sample rows for `xhs_downloader` and `scheduler_a`.
  - Browser console error/warn count: `0`.
  - Screenshot saved outside repo: `/tmp/noteai-admin-xhs-smoke.png`.

### 7. 当前仍然失败的问题

- Browser plugin `domSnapshot()` 在该页面报内部方法缺失：`incrementalAriaSnapshot is not a function`。
- 该问题不影响本轮通过 URL/title、locator、read-only DOM evaluate、console logs 和 screenshot 完成渲染 smoke；但后续若需要 DOM snapshot 级审计，需改用常规 Playwright 或等待 Browser plugin 修复。

### 8. 当前未完成工作

- 尚未安装 XHS-Downloader。
- 尚未真实访问小红书。
- 尚未运行真实 crawler / worker。
- 尚未执行本轮 live AI 验证。

### 9. 当前最高风险

- 下一阶段会访问真实外部站点和真实 AI API，需要严格控制样本数、重试次数、日志脱敏和本地/生产边界。

### 10. 下一步最小可行计划

- 查阅 XHS-Downloader 官方 repo 的当前安装与运行方式。
- 将 XHS-Downloader 安装到 repo 外的临时/缓存目录，避免污染 Git worktree。
- 输出 Live Crawler Run Plan 后，对用户提供的小红书短链做 1 次真实访问验证。
- 用临时 SQLite 或只读/小样本策略运行 crawler/worker，避免写生产 DB。
- 输出 Live AI Run Plan 后，运行 1 次受控 live AI smoke。

### 11. 哪些地方不能在未经确认的情况下修改

- 不输出 Cookie、token、API key、`.env` 值或数据库连接串。
- 不写生产数据库。
- 不运行 deploy、migration、seed、reset、clean。
- 不触发真实支付、邮件、短信。
- 不批量爬取、不并发压测、不无限重试。
- 不把 XHS-Downloader 整仓库或安装产物加入 Git。

## 2026-07-05 Stage Update — XHS-Downloader Live Crawler Worker And Live AI

### 1. 本轮完成了什么

- 安装并启动 XHS-Downloader sidecar，使用官方 API 模式验证 `POST /xhs/detail`。
- 真实访问用户提供的小红书短链 `http://xhslink.com/o/1ozVDX9STI4`。
- 发现并修复 NoteAI sidecar 归一化器不兼容 XHS-Downloader v2.8 中文字段 schema 的问题。
- 真实运行 NoteAI `crawler_worker -> crawler.run_collection_round` 路径：
  - 初次真实 worker 证明 Playwright selector 路径仍会超时失败。
  - 接入 XHS-Downloader sidecar fallback 后，真实 worker 成功采集 1 条临时 tracking 记录并进入 `checking_7d`。
- 完成 1 次受控 live AI smoke，真实 Claude 调用成功。
- 所有真实 crawler/AI 输出均已脱敏，未输出 Cookie、API key、token、正文、标题全文或原始响应。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`
- `model/xhs_acquisition.py`
- `model/crawler.py`
- `tests/test_xhs_acquisition.py`
- `tests/test_tracking_performance.py`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录本阶段真实外部验证、代码修复、测试结果、剩余风险和下一步。
- `model/xhs_acquisition.py`: 扩展 `normalize_sidecar_detail()`，支持 XHS-Downloader v2.8 中文字段（如 `作品ID`、`作品标题`、`点赞数量` 等）；修复 `_first_int()` 遇到缺失候选 key 时过早返回 `0` 的 bug。
- `model/crawler.py`: 在 Playwright 页面 selector 失败后增加 XHS-Downloader sidecar fallback，保持现有 tracking 状态机不变，只补充真实互动数据来源。
- `tests/test_xhs_acquisition.py`: 增加中文 schema fixture，防止 sidecar 返回中文字段时再次被误判为空。
- `tests/test_tracking_performance.py`: 增加 crawler sidecar fallback 单测，确认 fallback 能返回 tracking 所需的 likes/saves/comments/title。

### 4. 做了哪些关键决策

- XHS-Downloader 安装在 repo 外：`/Users/openclaw/.cache/noteai/XHS-Downloader`，避免污染 NoteAI Git worktree。
- XHS-Downloader sidecar 使用本地 API 模式，只绑定本地测试，验证后已关闭。
- XHS 真实验证用小样本、单链接、无下载、无批量、无并发。
- NoteAI worker 真实测试使用 `/tmp` 临时 SQLite 和临时 crawler log，不写主项目 DB 或生产 DB。
- Playwright selector 失败不再直接代表全链路失败；sidecar 可作为更稳定的数据提取 fallback。
- 不把 XHS-Downloader 仓库或它的 `.venv` 纳入 Git。

### 5. 运行了哪些命令

- `git clone https://github.com/JoeanAmier/XHS-Downloader.git /Users/openclaw/.cache/noteai/XHS-Downloader`
- `uv sync --no-dev`
- `uv run python -c "import asyncio; from main import api_server; asyncio.run(api_server(host='127.0.0.1', port=5556, log_level='warning'))"`
- `curl -sS -o /tmp/xhs_downloader_docs_probe.html -w '%{http_code}' http://127.0.0.1:5556/docs`
- 受控 sidecar adapter live smoke（1 条用户提供短链，临时 hot_keywords DB）
- 受控 sidecar schema diagnostic（只输出字段名/类型，不输出原始内容）
- 受控 sidecar adapter live re-check（同一短链，临时 hot_keywords DB）
- 受控 NoteAI worker live smoke（临时 NoteAI DB + 临时 crawler log）
- 受控 NoteAI worker fallback live re-check（临时 NoteAI DB + 临时 hot_keywords DB + 临时 crawler log）
- `.venv/bin/python tools/live_ai_smoke.py --provider auto --max-tokens 32 --timeout 45`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition tests.test_tracking_performance`
- `.venv/bin/python -m py_compile model/*.py`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `git diff --check`
- `docker compose config --quiet`
- `git status --short`
- `git diff --stat`

### 6. 每个命令的结果

- XHS-Downloader clone 成功，当前外部缓存仓库 commit：`56c912e`。
- `uv sync --no-dev`: 成功创建外部 sidecar `.venv` 并安装依赖。
- sidecar API 启动成功，`/docs` 返回 HTTP `200`。
- 第一次 sidecar adapter live smoke：
  - HTTP 层成功。
  - 归一化为空，health 标记 `failed`。
  - 原因不是 sidecar 不能访问，而是 NoteAI 未识别中文字段 schema。
- sidecar schema diagnostic：
  - 顶层字段包括 `data`、`message`、`params`。
  - `data` 内存在中文字段，如 `作品ID`、`作者ID`、`下载地址` 等。
  - 未输出标题、正文、图片 URL 或原始响应。
- 修复后 sidecar adapter live re-check：
  - `adapter_usable: true`
  - `note_id_present/title_present/desc_present: true`
  - 指标成功读取：likes/saves/comments/shares 均为数字。
  - health 记录：`status=ok`、`note_page_access_valid=true`、`selector_valid=true`、`risk_login_detected=false`。
- 初次 NoteAI worker live smoke：
  - Playwright selector 超时：等待 `.note-content, .note-container, #noteContainer` 失败。
  - 临时 tracking：`status=needs_manual`、`last_error_code=extract_failed`。
  - `worker_result`: `collected=0 failed=1 total=1`。
- 接入 sidecar fallback 后 NoteAI worker live re-check：
  - Playwright selector 仍超时，但 fallback 成功。
  - 临时 tracking：`status=checking_7d`、`attempt_count=0`、`likes_24h/saves_24h/comments_24h` 写入成功、`title_present=true`。
  - `worker_result`: `collected=1 failed=0 total=1`。
  - XHS health：`adapter=xhs_downloader`、`status=ok`、`evidence_count=1`、`risk_login_detected=false`。
- Live AI smoke：
  - provider：`claude`
  - model：`claude-haiku-4-5-20251001`
  - calls：`1`
  - success：`true`
  - input tokens：`35`
  - output tokens：`10`
  - DB writes：`false`
  - content printed：`false`
- Focused tests:
  - `tests.test_xhs_acquisition`: 10 tests passed。
  - `tests.test_xhs_acquisition tests.test_tracking_performance`: 15 tests passed。
- `.venv/bin/python -m py_compile model/*.py`: passed。
- Full unittest: 248 tests passed。
- `git diff --check`: passed。
- `docker compose config --quiet`: passed。
- `git status --short`: 当前仍有多文件未提交改动和未跟踪 `测试图片/`。

### 7. 当前仍然失败的问题

- Playwright DOM selector 路径仍会在当前真实小红书页面上超时；当前已由 sidecar fallback 弥补，不再阻塞 tracking worker。
- Browser plugin 的 `domSnapshot()` 仍有内部方法缺失问题；Admin UI smoke 已用其他 browser evidence 覆盖。

### 8. 当前未完成工作

- 尚未把本轮新增修改 commit/push。
- 尚未将 XHS-Downloader sidecar 纳入正式云端部署编排；当前只是本机外部缓存安装和实测。
- 尚未把 sidecar fallback 的生产运行参数（端口、服务名、健康检查、告警）固化到最终部署方案之外的真实云环境。

### 9. 当前最高风险

- 生产每日新鲜小红书证据不能只依赖 Playwright selector；必须以 XHS-Downloader/sidecar 或等价稳定 adapter 作为主路径或强 fallback，并配 crawler health 分层监控。
- XHS-Downloader 是 GPL-3.0 项目，后续若深度集成/分发，需要确认许可证策略；当前作为独立外部 sidecar 调用风险较低但仍需产品/部署层面确认。
- 真实平台访问仍可能受风控、Cookie、IP、频率、页面结构变化影响；需要 daily health 和 alert，而不是静默降级。

### 10. 下一步最小可行计划

- Review 当前 diff，确认 checkpoint scope。
- 如果用户确认，stage/commit/push 本阶段：
  - XHS sidecar schema/fallback 修复
  - Admin XHS visibility
  - tracking worker/crawler hardening
  - tests and handoff
- 后续部署阶段再单独处理 sidecar 云端服务编排、健康检查和日调度告警。

### 11. 哪些地方不能在未经确认的情况下修改

- 不提交或复制 XHS-Downloader 仓库、`.venv`、运行产物到 NoteAI repo。
- 不输出或提交 Cookie、token、API key、`.env` 值、数据库连接串。
- 不写生产数据库，不运行 migration/seed/reset/deploy。
- 不批量爬取、不全量跑行业、不并发压测、不无限重试。
- 不修改 billing/payment/quota 逻辑。
- 不触发真实邮件、短信、支付、部署。

## 2026-07-05 Stage Update — Moonshot Kimi Live Fix And Generate Endpoint Smoke

### 1. 本轮完成了什么

- 按用户确认，补跑显式 Moonshot/Kimi live AI smoke。
- 第一次 Kimi live smoke 失败，返回 HTTP `400 Bad Request`。
- 查官方 Kimi K2.6 文档后，确认当前 repo 中仍有旧默认 `kimi-k2.5`，且 `tools/live_ai_smoke.py` 使用了不合适的 `temperature=0`。
- 最小修复 Kimi 文本默认模型和非思考温度后，Kimi live smoke 成功。
- 运行受控 `/generate` endpoint smoke：
  - 使用 FastAPI `TestClient` 真实 `POST /generate`。
  - 使用 `/tmp` 临时 SQLite test DB 和 test user。
  - 无图片、无视频、禁用事实联网、禁用多候选、禁用模型重试。
  - 设置 10 次内部模型任务硬上限。
  - endpoint 最终 HTTP 200，返回标题、正文、标题变体、分数和质量字段。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`
- `tools/live_ai_smoke.py`
- `model/model_router.py`
- `model/api.py`
- `tools/ai_prelabel_review_batch.py`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录 Kimi live 失败原因、修复、`/generate` live smoke 结果和剩余风险。
- `tools/live_ai_smoke.py`: 将 Kimi 默认模型从 `kimi-k2.5` 更新为 `kimi-k2.6`，并将 non-thinking smoke temperature 从 `0` 调整为 `0.6`。
- `model/model_router.py`: 将统一模型路由中的 Kimi fallback 默认从 `kimi-k2.5` 更新为 `kimi-k2.6`，并将非流式 Kimi non-thinking temperature 调整为 `0.6`。
- `model/api.py`: 将 API 内部 `_KIMI_MODEL` 默认从 `kimi-k2.5` 更新为 `kimi-k2.6`，与文件中已有 K2.6 注释和请求参数保持一致。
- `tools/ai_prelabel_review_batch.py`: 将离线预标注复核工具默认 Kimi 模型更新为 `kimi-k2.6`，避免后续真实批处理沿用旧模型。

### 4. 做了哪些关键决策

- 只更新 Kimi 文本默认模型和 non-thinking temperature，不改 prompt、计费、权限或生成状态机。
- 端点 smoke 不传图片，避免触发 Kimi Vision 与视频/文件 API。
- 端点 smoke 使用临时 DB，并通过 test user 真实走 auth + billing + endpoint；不写生产 DB 或主项目业务数据。
- 通过 wrapper 统计内部 `_mr.call` 调用并设置上限，避免真实模型调用失控。
- `/generate` smoke 只做一次，不重跑；该链路真实成本较高。

### 5. 运行了哪些命令

- `.venv/bin/python tools/live_ai_smoke.py --provider kimi --max-tokens 32 --timeout 45`
- 官方文档查询：Kimi K2.6 quickstart / request parameter guidance。
- `rg -n "kimi-k2\\.5|kimi-k2\\.6|MOONSHOT|moonshot-v1|temperature.*0|thinking" model tools tests -S`
- `.venv/bin/python tools/live_ai_smoke.py --provider kimi --max-tokens 32 --timeout 45`（修复后复验）
- 受控 FastAPI TestClient `/generate` live endpoint smoke（临时 DB、test user、10-call ceiling）
- `.venv/bin/python -m py_compile model/*.py tools/live_ai_smoke.py tools/ai_prelabel_review_batch.py`
- `.venv/bin/python -m unittest tests.test_api_contracts tests.test_billing_token_cost tests.test_xhs_acquisition tests.test_tracking_performance`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `git diff --check`
- `docker compose config --quiet`
- `git status --short && git diff --stat`

### 6. 每个命令的结果

- 修复前 Kimi live smoke：
  - provider：`kimi`
  - calls：`1`
  - success：`false`
  - error type：`HTTPStatusError`
  - error summary：HTTP `400 Bad Request`
  - 未写 DB，未打印模型内容或 key。
- 修复后 Kimi live smoke：
  - provider：`kimi`
  - model：`kimi-k2.6`
  - calls：`1`
  - success：`true`
  - elapsed：约 `921ms`
  - input tokens：`35`
  - output tokens：`8`
  - DB writes：`false`
  - content printed：`false`
- `/generate` live endpoint smoke：
  - HTTP status：`200`
  - response shape：success
  - note title present：true，标题长度 `15`
  - note body present：true，正文长度 `321`
  - title variants count：`3`
  - CES percentile：`69.0`
  - grade：`良好`
  - quality issues count：`0`
  - selection candidate count：`3`
  - internal `_mr.call` count：`10`
  - by task：
    - `content_gen` 3 次
    - `arbitrate` thinking 3 次
    - `semantic` 3 次
    - `content_gen` repair 1 次
  - 临时 DB usage：`generate` 写入 1 条 usage record，free tier 月度积分临时扣 `8.0`。
  - 未输出生成正文全文、token、secret、API key。
- 回归：
  - `py_compile`: passed。
  - focused unittest: 159 tests passed。
  - full unittest: 248 tests passed。
  - `git diff --check`: passed。
  - `docker compose config --quiet`: passed。

### 7. 当前仍然失败的问题

- 无本轮命令失败。
- 但 `/generate` live smoke 显示完整生成链路真实调用很重：在压缩配置下仍触发 10 次内部模型任务，且 Sonnet thinking 仲裁单次约 80-100 秒级。
- `usage_records.model_calls` 记录为 `17`，高于 wrapper 统计的 10 个 `_mr.call` 入口任务；后续需要单独 review 计费模型调用归集口径是否按 provider API call、stream chunk/final usage 或模型路由层记录重复计算。

### 8. 当前未完成工作

- 尚未 commit/push 本轮 Kimi 修复、crawler fallback、Admin XHS UI、handoff 等累计改动。
- 尚未优化 `/generate` 成本/时延；当前只能说明链路可用但成本较高。
- 尚未决定生产上是否默认允许用户频繁触发完整 5-agent + 多轮 refine 链路。

### 9. 当前最高风险

- `/generate` 真实链路成本和时延偏高；如果用户量增加，需要限流、异步任务、进度展示、取消/超时策略、套餐额度保护和更细粒度调用预算。
- Kimi/Moonshot 模型版本需要长期维护；旧模型名或错误 temperature 会直接导致 live API 400。
- 计费 usage `model_calls` 口径需要核查，避免成本展示或账单诊断误导。

### 10. 下一步最小可行计划

- Review 当前 diff，准备 checkpoint scope。
- 若用户确认，stage/commit/push 当前阶段。
- 单独开小任务 review `/generate` 调用预算与 usage model_calls 归集逻辑，不和 crawler/XHS 修复混在一起。

### 11. 哪些地方不能在未经确认的情况下修改

- 不运行第二次 `/generate` live smoke，除非用户明确确认额外成本。
- 不修改 billing/payment/quota 口径，除非单独确认。
- 不写生产 DB，不部署，不迁移，不 seed/reset。
- 不输出生成全文、API key、token、`.env` 值或连接串。

## 2026-07-05 User Decision — Cloud Deployment Deferred Until Value And Stability Validation

### 1. 本轮完成了什么

- 记录用户明确决策：云端部署先只做计划，当前不执行。
- 当前阶段重点继续本地/灰度测试所有功能，验证商业价值、用户价值、真实稳定性后，再整体迁移到云端。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录用户关于上线节奏和云端部署边界的产品/工程决策，避免后续线程误以为需要立即部署。

### 4. 做了哪些关键决策

- 小红书抓取、crawler worker、XHS-Downloader sidecar、daily freshness、Admin health、AI generate 等功能先继续在本地/受控灰度环境验证。
- 云端部署只做规划，不执行部署、不配置生产资源、不迁移数据。
- 等所有关键功能经过手动测试、真实 API 验证、商业价值验证、稳定性观察后，再统一设计并迁移到云端。

### 5. 运行了哪些命令

- `tail -n 180 .codex/handoffs/current-task.md`

### 6. 每个命令的结果

- 成功读取最新 handoff 上下文。

### 7. 当前仍然失败的问题

- 暂无新增失败。

### 8. 当前未完成工作

- 云端部署计划尚未形成正式 checklist。
- 当前未提交 diff 仍需 checkpoint commit/push。
- 仍需继续逐项功能测试，尤其是小红书抓取稳定性、`/generate` 成本/延迟、计费 usage 归集口径、前端完整用户路径。

### 9. 当前最高风险

- 在未完成商业价值和稳定性验证前贸然部署云端，会放大成本、平台风控、数据写入、计费、用户体验和运维风险。
- 小红书抓取当前具备受控灰度能力，但不应承诺全量生产稳定性。

### 10. 下一步最小可行计划

- 不做云端部署。
- 继续配合用户逐项测试产品功能。
- 对已验证通过且需要保留的功能做 checkpoint commit/push。
- 单独维护一份未来云端部署计划：服务拆分、sidecar、cron、health alert、DB、secrets、成本保护、回滚策略。

### 11. 哪些地方不能在未经确认的情况下修改

- 不执行 cloud deploy。
- 不创建/修改生产服务、生产数据库、生产 secrets、生产域名。
- 不运行 migration/seed/reset/deploy。
- 不把本地 XHS-Downloader 安装目录或 `.venv` 纳入 Git。
- 不把未验证商业价值和稳定性的功能直接推成全量生产默认。

## 2026-07-05 Stage Update — Prepare Crawler Sidecar Commit And Pilot Checklist

### 1. 本轮完成了什么

- 按用户要求准备 commit/push 当前 crawler + sidecar fallback 修复。
- 创建 crawler production pilot checklist，用于后续云端部署前的灰度准入标准。
- 明确本次 commit scope 不包含 Kimi/Moonshot live 修复，不包含未跟踪 `测试图片/`。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`
- `.codex/notes/crawler-production-pilot-checklist.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录本轮即将提交的 scope、决策、风险和 checklist。
- `.codex/notes/crawler-production-pilot-checklist.md`: 保存 crawler/XHS-Downloader 云端 pilot 前的准入 checklist，避免当前阶段误部署。

### 4. 做了哪些关键决策

- commit scope 定义为 XHS acquisition/health、crawler worker、sidecar fallback、tracking persistence/API/UI、Admin crawler visibility、相关 tests、handoff 和 pilot checklist。
- 暂不把 Kimi 模型默认修复纳入本次 crawler checkpoint。
- 不提交 XHS-Downloader 外部安装目录、`.venv`、Cookie、cache 或 raw JSON response。
- 不提交未跟踪目录 `测试图片/`。

### 5. 运行了哪些命令

- `sed -n '1,220p' /Users/openclaw/.codex/plugins/cache/openai-curated-remote/github/0.1.5/skills/yeet/SKILL.md`
- `git branch --show-current`
- `git status --short`
- `git diff --name-status`
- `git diff --stat`
- `git diff -- NoteAI_Pro_Demo_Framer.html | rg -n "track|追踪|笔记库|version|history|crawler|xhs|XHS|性能|真实表现" -C 2`
- `git diff -- model/model_router.py tools/ai_prelabel_review_batch.py tools/live_ai_smoke.py | sed -n '1,220p'`
- `git remote -v`
- `ls -la .codex/notes`
- `git diff -- model/api.py | sed -n '1,220p'`

### 6. 每个命令的结果

- 当前分支：`codex/quality-stabilization-real-chain`。
- remote：`origin` 指向 `https://github.com/iamyusen1314/noteai.git`。
- 工作区为混合状态，存在 crawler 相关改动、Kimi live 修复改动、未跟踪 `测试图片/`。
- 前端 diff 包含 tracking index、笔记库版本卡追踪 badge、从笔记卡关联追踪、手动回填 views 等 crawler/tracking 相关 UI。
- `model/model_router.py` 和 `tools/ai_prelabel_review_batch.py` diff 属于 Kimi live 修复，不纳入本次 crawler checkpoint。
- `model/api.py` 同时包含 crawler/tracking hunks 和 `_KIMI_MODEL` hunk；commit 时需要 stage crawler hunks 后反向 unstage Kimi hunk。

### 7. 当前仍然失败的问题

- 暂无新增失败。

### 8. 当前未完成工作

- 尚未 stage / commit / push。
- 尚未在提交后更新 handoff 的实际 commit hash 和 push 结果。

### 9. 当前最高风险

- 当前 worktree 混合多类改动；需要精确 stage，避免把 Kimi 修复或 `测试图片/` 混入 crawler checkpoint。

### 10. 下一步最小可行计划

- 显式 stage crawler/sidecar/tracking/checklist 相关文件。
- 对 `model/api.py` 从 index 中反向移除 `_KIMI_MODEL` hunk，保留 crawler/tracking hunk。
- 运行 cached diff/stat 和 `git diff --cached --check`。
- commit。
- push 当前分支。
- 更新 handoff 记录 commit/push 结果。

### 11. 哪些地方不能在未经确认的情况下修改

- 不 stage/commit Kimi live 修复相关文件：
  - `model/model_router.py`
  - `tools/ai_prelabel_review_batch.py`
  - `tools/live_ai_smoke.py`
- 不提交未跟踪目录 `测试图片/`。
- 不执行 cloud deploy、migration、seed、reset。

## 2026-07-05 Stage Update — Crawler Sidecar Checkpoint Pushed

### 1. 本轮完成了什么

- 已按用户要求 commit/push 当前 crawler + sidecar fallback 修复。
- 已创建并提交 crawler production pilot checklist。
- 已明确保留但不提交无关 Kimi live 修复和未跟踪测试图片目录。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`
- `.codex/notes/crawler-production-pilot-checklist.md`
- `NoteAI_Pro_Demo_Framer.html`
- `docker-compose.yml`
- `model/.env.example`
- `model/admin.html`
- `model/admin_server.py`
- `model/api.py`
- `model/crawler.py`
- `model/crawler_worker.py`
- `model/db.py`
- `model/hot_keywords.py`
- `model/market_timing_worker.py`
- `model/performance_scoring.py`
- `model/xhs_acquisition.py`
- `model/xhs_health_probe.py`
- `tests/test_api_contracts.py`
- `tests/test_tracking_performance.py`
- `tests/test_xhs_acquisition.py`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录本阶段提交、验证、push、剩余风险和下一步边界。
- `.codex/notes/crawler-production-pilot-checklist.md`: 新增 crawler/XHS-Downloader sidecar 上线前 pilot checklist。
- `NoteAI_Pro_Demo_Framer.html`: 接入笔记库追踪入口、版本关联状态、真实表现追踪 UI 反馈。
- `docker-compose.yml`: 增加本地 tracking/crawler worker 与 XHS freshness 相关配置。
- `model/.env.example`: 增加 XHS freshness/sidecar/worker 配置占位说明，不包含真实 secret。
- `model/admin.html`: 增加 Admin crawler/XHS freshness/sidecar health 可视化卡片。
- `model/admin_server.py`: 增加 Admin crawler/freshness 只读状态接口。
- `model/api.py`: 增加 tracking persistence、performance API、market freshness API，并保持 Kimi 默认模型 hunk 不进入本次 commit。
- `model/crawler.py`: 增加 Playwright crawler 与 XHS-Downloader sidecar fallback 归一化路径。
- `model/crawler_worker.py`: 增加受控 tracking worker 入口。
- `model/db.py`: 增加 tracked notes 所需字段和幂等 schema 支持。
- `model/hot_keywords.py`: 支持 worker/freshness 路径的连接清理与数据写入。
- `model/market_timing_worker.py`: 增加 XHS freshness gate。
- `model/performance_scoring.py`: 增加真实表现追踪评分/状态计算基础逻辑。
- `model/xhs_acquisition.py`: 增加 XHS acquisition/freshness ledger/sidecar 归一化与健康判断核心逻辑。
- `model/xhs_health_probe.py`: 增加 crawler health probe 命令入口。
- `tests/test_api_contracts.py`: 补充 API contract 覆盖。
- `tests/test_tracking_performance.py`: 覆盖追踪表现状态和评分逻辑。
- `tests/test_xhs_acquisition.py`: 覆盖 sidecar 归一化、freshness ledger 和采集健康判断。

### 4. 做了哪些关键决策

- 本次 checkpoint 只提交 crawler/sidecar/tracking/Admin/checklist 相关改动。
- 不把 `model/model_router.py`、`tools/ai_prelabel_review_batch.py`、`tools/live_ai_smoke.py` 纳入本次 crawler commit。
- `model/api.py` 中无关 `_KIMI_MODEL` hunk 已从 staged diff 剔除，只保留在 working tree。
- 不提交 XHS-Downloader 外部安装目录、Cookie、cache、raw JSON response 或 `测试图片/`。

### 5. 运行了哪些命令

- `git diff --cached --check`
- `git diff --cached --name-only | tr '\n' '\0' | xargs -0 rg -l "(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-|API_KEY=|TOKEN=|SECRET=|COOKIE=|SESSION=|DATABASE_URL=|Authorization: Bearer)" || true`
- `.venv/bin/python -m unittest tests.test_xhs_acquisition tests.test_tracking_performance tests.test_api_contracts`
- `.venv/bin/python -m py_compile model/api.py model/admin_server.py model/crawler.py model/crawler_worker.py model/db.py model/hot_keywords.py model/market_timing_worker.py model/performance_scoring.py model/xhs_acquisition.py model/xhs_health_probe.py`
- `docker compose config --quiet`
- `git commit -m "stabilize xhs crawler sidecar fallback"`
- `git push origin codex/quality-stabilization-real-chain`

### 6. 每个命令的结果

- `git diff --cached --check`: 通过。
- staged secret pattern scan: 仅命中 `model/.env.example` 占位变量文件；未展开或输出任何真实值。
- 聚焦单测：146 tests passed。
- Python 编译检查：通过。
- Docker Compose 配置检查：通过。
- commit 成功：`dee7cab stabilize xhs crawler sidecar fallback`。
- push 成功：`origin/codex/quality-stabilization-real-chain` 已更新到 `dee7cab`。

### 7. 当前仍然失败的问题

- 本阶段未发现 crawler checkpoint 的新增失败。
- 聚焦单测日志中出现外部 API 错误路径输出，但本轮没有做计划外 live API 成功调用，也没有进行真实批量调用。
- 当前 crawler/sidecar 仍不应标记为 production-ready，只能进入 production pilot checklist 管控下的小样本灰度验证。

### 8. 当前未完成工作

- Kimi live 修复仍留在 working tree，尚未作为独立 scope commit。
- `tools/live_ai_smoke.py` 仍为未跟踪文件，尚未确认是否纳入后续 live AI 工具化提交。
- `测试图片/` 仍为未跟踪目录，当前不提交。
- 云端部署只完成 checklist/计划边界，尚未实施部署。

### 9. 当前最高风险

- 小红书抓取稳定性依赖 Cookie/session、页面可访问性、selector 变化、sidecar 可用性和平台风控；即使 sidecar fallback 本地可跑，也需要 3-7 天小样本 pilot 数据证明稳定性。
- 当前 worktree 仍混有 Kimi live 修复，后续提交必须继续精确 stage，避免 scope 混杂。

### 10. 下一步最小可行计划

- 先让用户按 checklist 做本地/灰度功能验收。
- 如用户确认，再单独处理 Kimi live 修复提交。
- 在不部署云端的前提下，继续完善 pilot 观测：sidecar health、freshness ledger、worker completion、失败原因分层。

### 11. 哪些地方不能在未经确认的情况下修改

- 不部署云端。
- 不运行 migration/seed/reset/deploy/clean。
- 不写生产 DB。
- 不输出或提交 Cookie、token、API key、`.env` 真实值、raw provider response。
- 不把 XHS-Downloader 外部安装目录、cache、日志或测试图片纳入 Git。
- 不将 crawler/sidecar 标记为生产可全量上线，除非完成 pilot checklist 并经用户确认。
