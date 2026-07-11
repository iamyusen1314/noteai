# Risk Register

Last updated: 2026-07-11

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

### Database migration or SQLite/PostgreSQL drift damages data

- 风险描述: Local SQLite and cloud PostgreSQL now share one helper surface but use different schema/migration paths. A new query can work locally and fail on PostgreSQL.
- 涉及文件: `model/db.py`, `model/hot_keywords.py`, `model/migrations/postgres/`, `scripts/render_predeploy.py`, `scripts/migrate_sqlite_to_postgres.py`.
- 可能后果: Data loss, incompatible columns, failed pre-deploy, broken API/Cron startup, partial data import if safeguards are bypassed.
- 建议验证方式: Apply every migration twice to a disposable PostgreSQL, run shared-state/trend/API/admin container probes, back up before any guarded SQLite import.
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

### Render model prices are not configured for actual cost accounting

- 风险描述: Staging 已记录 Claude/Kimi 的 Token 与模型名称，但模型 INPUT/OUTPUT 单价环境变量未配置，导致 `actual_model_cost_rmb=0`，`cost_rmb` 继续使用操作级固定估算。
- 涉及文件: `model/billing.py`, `model/api.py`, `model/.env.example`, Render API 环境变量，后台用量页面。
- 可能后果: 毛利、套餐定价和供应商费用预警建立在估算值而非真实 Token 成本上，可能误判盈利能力。
- 建议验证方式: 由产品负责人确认精确模型价格和汇率后，各跑一次最小诊断/生成/重写，要求 `actual_model_cost_rmb>0` 且手工复算一致。
- 是否需要用户确认后才能修改: yes，配置和验证会影响商业核算并产生少量 API 费用。

## High Risks

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

- 风险描述: Production requires V0.4 artifacts and SHA checks. Git LFS availability is platform-dependent; private S3 credentials and object paths must be exact.
- 涉及文件: `model/artifacts/`, `model/model_registry.json`, `model/artifact_loader.py`, `scripts/fetch_model_artifacts.py`, `Dockerfile`, `scripts/docker_entrypoint.sh`, docs.
- 可能后果: Service starts with missing/legacy model, startup failure, wrong scoring behavior.
- 建议验证方式: `python scripts/fetch_model_artifacts.py --check-only --required`, production readiness gate, container startup smoke.
- 是否需要用户确认后才能修改: yes.

### External provider reliability/cost risk

- 风险描述: Claude/Kimi/Amap/Meituan calls have timeouts, concurrency limits, token costs, and possible regional network issues.
- 涉及文件: `model/model_router.py`, `model/api.py`, `model/fact_enrichment.py`, `model/billing.py`.
- 可能后果: Empty responses, failed OCR, slow diagnosis, inaccurate billing cost, poor user experience.
- 建议验证方式: Provider-specific smoke tests with timeout/retry logging and usage record checks; avoid logging secrets.
- 是否需要用户确认后才能修改: yes for live-cost tests or provider changes.

### Render AI latency exceeds the current user-facing promise

- 风险描述: 真实 staging 样本中，诊断约 194–228 秒、生成约 257 秒、对话深度重写约 146 秒，而前端按钮仍承诺“约30–60秒”。
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, `model/model_router.py`, 多 Agent/评分/二修流程。
- 可能后果: 用户认为系统卡死或虚假承诺，重复提交导致重复扣分和更高模型费用。
- 建议验证方式: 先修正文案与进度/防重复提交；再用阶段耗时日志定位 Claude 并发、评分和二修瓶颈，优化后保持同一质量门禁做 A/B 实测。
- 是否需要用户确认后才能修改: 文案与防重复提交可按事实修复；改变 Agent 数量、模型、并发或二修策略需要用户确认，因为可能影响交付质量和费用。

## Medium Risks

### Render Free PostgreSQL expires and has no backups

- 风险描述: `render.yaml` intentionally uses Free PostgreSQL for staging. It expires after 30 days and does not include backups.
- 涉及文件: `render.yaml`, `docs/RENDER_DEPLOYMENT_GUIDE.md`.
- 可能后果: Test data becomes inaccessible and is eventually deleted if the database is not upgraded/exported.
- 建议验证方式: Record creation date, configure a reminder, export important test data, and upgrade before using production-like records.
- 是否需要用户确认后才能修改: yes, because plan upgrades create cost.

### Video cache disk prevents zero-downtime API deploys

- 风险描述: Staging API uses a 1GB Render disk for six-hour video frame recovery. Render cannot perform zero-downtime replacement for a disk-attached service and cannot scale it horizontally.
- 涉及文件: `render.yaml`, `model/api.py`, `docs/RENDER_DEPLOYMENT_GUIDE.md`.
- 可能后果: Brief deploy interruption, disk pressure if cleanup fails, and inability to scale beyond one API instance.
- 建议验证方式: Upload/restart/recover smoke, disk usage monitoring, and replace the cache with object storage before horizontal scaling.
- 是否需要用户确认后才能修改: yes.

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
- 建议验证方式: Cloud-like container run, worker logs, data freshness check, same-day de-duplicated evidence accumulation, and admin session-health status.
- 是否需要用户确认后才能修改: yes.

### XHS test-account session can expire and requires operator action

- 风险描述: Render 的市场时机采集依赖由用户登录生成的测试账号会话；提醒机制已部署，但平台风控、Cookie 到期或页面策略变化仍会令会话失效并需要人工重新登录。
- 涉及文件: `model/scheduler_a.py`, `model/market_timing_worker.py`, `model/xhs_acquisition.py`, `model/admin_server.py`, `model/admin.html`, `render.yaml`。
- 可能后果: 六个核心行业无法达到真实新鲜证据门禁，Cron 退出非零，市场时机证据停止更新。
- 建议验证方式: 管理端显示 `已验证 / 登录已失效 / 需要检查`；Render Cron 仅失败通知；每次重新登录后以真实采集证据验证，而不是只检查 Cookie 是否存在。
- 是否需要用户确认后才能修改: 重新登录和替换 Cookie 需要用户确认；健康检测和无敏感值提醒可按现有方案维护。

### XHS evidence source diversity can regress

- 风险描述: 当前四类来源已在 Render 真实通过；未来页面/API 变化仍可能让来源退化，而单看关键词总数可能掩盖来源单一。
- 涉及文件: `model/scheduler_a.py`, `model/xhs_acquisition.py`, `model/market_timing_worker.py`, `model/admin_server.py`。
- 可能后果: 市场时机证据数量达标但缺少用户主动搜索与趋势信号，降低报告可信度。
- 建议验证方式: 每轮记录 `homefeed / search_result / search_recommend / hot_search` 独立数量及 API 响应指标；云端至少确认搜索结果和推荐来源非零，再评估是否增加来源多样性门禁。
- 是否需要用户确认后才能修改: 观测与解析修复不需要；新增硬性来源门禁需要产品确认和生产样本校准。

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

### Missing local Git LFS filter creates false model modifications

- 风险描述: 本机未安装或未启用 Git LFS filter 时，三份已跟踪 `.lgb` 会显示 modified，即使业务模型内容没有被主动修改。
- 涉及文件: `.gitattributes`, `model/artifacts/*.lgb`。
- 可能后果: 误把大模型二进制加入提交、污染 diff 或破坏远端 LFS 指针。
- 建议验证方式: 使用 LFS-safe status 核对；提交时只显式 stage 目标文件；恢复 Git LFS 后再处理工作树表现。
- 是否需要用户确认后才能修改: 安装依赖或改模型文件需要确认；排除 staging 不需要。

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
