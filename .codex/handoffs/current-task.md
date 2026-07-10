# Current Task Handoff

Last updated: 2026-07-10

## 2026-07-10 Stage Update - Render Deployment Preparation Implemented

### Original Goal

Prepare NoteAI for a Render staging migration without deploying or changing remote resources: identify the real service topology, replace single-host/local-file assumptions, add safe PostgreSQL migration and model-loading paths, verify the Docker image, and give the non-technical product owner an exact Render Dashboard guide.

### Current Status

#### 已完成

- Added `render.yaml` for 5 services plus PostgreSQL: Static Site, Docker API, Docker Admin, market-timing Cron, tracking Cron, and Render PostgreSQL.
- Added PostgreSQL support through Psycopg while retaining isolated local SQLite compatibility.
- Added four versioned PostgreSQL migrations covering product data, admin/shared settings, market timing/analysis, and XHS freshness.
- Moved admin sessions, managed Prompts, model registry state, crawler config, crawler cookies, and crawler logs away from process-local/filesystem-only state into the shared database for cloud operation.
- Moved PostgreSQL market timing, XHS freshness, analysis log, and creator learning data to shared PostgreSQL so Cron and API read the same evidence.
- Added readiness/liveness endpoints that check database, V0.4, and required AI configuration without exposing secret values.
- Added Render-aware `PORT`, graceful shutdown, one-worker defaults, non-root Docker execution, `.dockerignore`, and missing LightGBM `libgomp1` runtime dependency.
- Added runtime frontend API configuration and a static Render build script.
- Added six-hour persistent video-frame cache support for upload-to-diagnosis restart recovery.
- Added private Amazon S3 model download with SHA256 verification; public model buckets are not required.
- Locked cloud model train/deploy mutations unless explicitly enabled, so immutable release images remain authoritative.
- Added guarded SQLite-to-PostgreSQL import tooling. Dry-run is default; apply requires exact destination database confirmation and does not overwrite existing primary keys.
- Added deployment-specific tests and a non-programmer Render guide.
- No Render resource, production deployment, production DB write, or real secret mutation was performed.
- The user approved creating and pushing one deployment-preparation checkpoint on `codex/quality-stabilization-real-chain`; this approval does not include merging or creating Render/AWS resources.
- Pushed deployment checkpoint `f2b1c3b` to the approved branch. Its first GitHub CI runs exposed test-environment dependence on local market/XHS evidence, so CI now explicitly disables those two external-evidence gates for the offline suite; dedicated gate tests still enable and verify them.

#### 进行中

- Confirm the follow-up GitHub CI run is green after the offline test-environment isolation fix.

#### 未完成

- Confirm GitHub CI is green for the pushed deployment-preparation checkpoint.
- Create Render resources from the Blueprint.
- Manually enter Render Secrets.
- Upload the four V0.4 release files to a private S3 path if Render Git LFS checkout is insufficient.
- Trigger the first market-timing Cron and prove fresh real XHS evidence in Render.
- Optionally import selected local test data after a separate backup/apply approval.
- Run full post-deploy acceptance with real staging URLs and test accounts.

#### 不确定 / 待确认

- Whether the user will use private S3 immediately or first rely on Render's Git LFS checkout.
- Whether `NOTEAI_XHS_DOWNLOADER_URL` will be available; without it, Playwright collection may be affected by XHS anti-automation controls.
- Whether the Free PostgreSQL plan is acceptable for the entire test period; it expires after 30 days and has no backups.
- Whether the current branch will be merged to `main` or deployed directly as the staging branch.

### Files Touched

#### Frontend

- `NoteAI_Pro_Demo_Framer.html`: load `runtime-config.js` and use cloud API base instead of hard-coded host/port outside localhost.
- `runtime-config.js`: safe local default for frontend API runtime injection.
- `scripts/build_render_frontend.sh`: create Render static output and generated API runtime config.

#### Backend / API

- `model/api.py`: V0.4 startup gate, shared PostgreSQL timing/learning paths, liveness/readiness, XHS evidence enforcement, persistent video-frame cache, local DB path isolation.
- `model/admin_server.py`: shared Prompt/registry/crawler state, cloud model mutation lock, secret-prefix removal, PostgreSQL-aware system status, admin health endpoints.
- `model/admin_auth.py`: database-backed admin sessions.
- `model/prompt_manager.py`: shared database Prompt loading and default seeding.
- `model/runtime_settings.py`: new shared JSON settings helper.
- `model/crawler.py`, `model/crawler_worker.py`, `model/scheduler_a.py`, `model/xhs_acquisition.py`, `model/hot_keywords.py`: shared cloud config/cookies/logs/trend/freshness data and PostgreSQL SQL compatibility.

#### Database

- `model/db.py`: SQLite/PostgreSQL dispatch, Psycopg-compatible rows, explicit migrations, advisory lock, health check, isolated SQLite path.
- `model/migrations/postgres/0001_initial.sql`: product/user/billing/content tables.
- `model/migrations/postgres/0002_shared_runtime_state.sql`: admin sessions, Prompts, settings.
- `model/migrations/postgres/0003_market_timing.sql`: trends, analysis, creator learning, crawler events.
- `model/migrations/postgres/0004_xhs_freshness.sql`: XHS health/freshness ledger.
- `scripts/render_predeploy.py`: explicit guarded PostgreSQL migration command.
- `scripts/migrate_sqlite_to_postgres.py`: dry-run-first, non-overwriting application data import.

#### Config / Deployment

- `Dockerfile`: resilient dependency install, Chromium, `libgomp1`, non-root user, Render scripts, healthcheck.
- `.dockerignore`: excludes secrets, local DB/data, training data, tests, docs, and non-production model artifacts from image context.
- `.gitignore`: ignores generated `dist/`.
- `render.yaml`: Render staging topology and non-secret settings; sensitive values use `sync: false`.
- `model/.env.example`: variable names for cloud DB, readiness, video cache, private S3, and cloud mutation lock.
- `model/requirements.txt`: adds Psycopg and Boto3.
- `model/artifact_loader.py`: private S3 download before optional public/base URL fallback, with existing SHA256 enforcement.
- `scripts/render_start_api.sh`, `scripts/render_start_admin.sh`: Render `PORT`, workers, graceful shutdown, optional migration-on-start.
- `scripts/render_run_market_timing.sh`, `scripts/render_run_crawler.sh`: one-shot Cron entrypoints.

#### Tests / Docs

- `tests/test_render_deployment.py`: shared state, admin sessions, Prompt seeding, video recovery, PostgreSQL SQL conversion, migration dry-run, Blueprint declarations.
- `docs/RENDER_DEPLOYMENT_GUIDE.md`: full Render Dashboard, S3, variables, first run, migration, acceptance, and rollback guide.
- `docs/MODEL_ARTIFACT_CLOUD_STRATEGY.md`: private S3 strategy and least-privilege IAM guidance.
- `AGENTS.md`, `.codex/notes/architecture-summary.md`, `.codex/notes/risk-register.md`, this handoff: durable engineering memory.

### Key Decisions

- Use mixed deployment: Render Static Site for frontend; Docker for API/Admin/Cron because Chromium, OpenCV, LightGBM, and exact system libraries are required.
- Do not use Redis in staging; no existing queue/cache contract requires it.
- Use PostgreSQL as the only cross-service state authority. Local SQLite remains a development compatibility path.
- Keep one API worker while video cache uses an attached disk; the disk prevents horizontal scale and zero-downtime deploys, acceptable only for staging.
- Keep trend freshness as a hard delivery gate. Baseline evidence may populate tables but cannot impersonate required fresh XHS evidence.
- Keep model release immutable in cloud. Admin train/deploy is locked; update code/image/manifest/S3 release together.
- Prefer private S3 with read-only IAM for model artifacts. Do not make a commercial model bucket public.
- Free PostgreSQL is staging-only because it expires and has no backups.
- Data import never overwrites destination primary keys and excludes sessions/secrets by default.

### Known Bugs

- No known deployment-preparation code failure remains after local verification.
- The initial CI runs for `f2b1c3b` failed three tests because the clean runner inherited production-required market/XHS freshness settings without live evidence. The workflow isolation fix passes all 271 tests locally; remote rerun confirmation remains pending.
- Real Render XHS collection success is unknown until the Cron runs from Singapore; this is an external operational dependency, not proven locally.

### Known Risks

- Fresh real XHS evidence can remain unavailable due platform anti-automation/network restrictions; core delivery intentionally returns 503 rather than fabricate timing evidence.
- Free PostgreSQL expires after 30 days and has no backup.
- API disk prevents zero-downtime deploy and horizontal scaling.
- Admin is a public Free web service protected only by its independent bearer login; use a strong unique password and consider paid IP restrictions before production.
- A future SQL query can work on SQLite and fail on PostgreSQL unless tested against disposable PostgreSQL.
- The repository is public; S3/AWS/AI secrets must only live in Render Secrets.
- Real payment callback/reconciliation is still not confirmed and remains a production-launch blocker separate from staging deployment.

### Verification Status

- `python -m py_compile model/*.py scripts/*.py`: passed.
- `sh -n scripts/*.sh`: passed.
- Full isolated unit suite: passed, 271 tests.
- Full suite with CI's explicit offline market/XHS gate settings: passed, 271 tests.
- Deployment-specific suite: passed, 6 tests.
- Playwright e2e: passed, 3 tests.
- `npm audit --audit-level=moderate`: passed, 0 vulnerabilities.
- `tools/production_readiness_gate.py`: passed, 48/48.
- `tools/quality_gate.py quality/golden_notes.sample.json`: passed expected contracts.
- `docker compose config --quiet`: passed.
- Static Render frontend build with a non-secret example API URL: passed.
- Docker image build: passed after adding `libgomp1`; build context about 6.9 MB.
- Docker API smoke: liveness/readiness 200, V0.4 loaded, artifact checks passed, non-root container healthy.
- Disposable PostgreSQL: migrations applied 4, second run applied 0; shared settings/admin session/hot keywords/XHS ledger passed.
- PostgreSQL market timing baseline/read/compute path: passed.
- API and Admin simultaneously connected to disposable PostgreSQL: both `/health/ready` returned 200 and Docker health was healthy.
- Render CLI schema validation: not run because Render CLI is not installed. `render.yaml` parsed as YAML, uses fields checked against current official Blueprint docs, and deployment tests assert resource declarations.
- No side-effect commands remain running; temporary containers/network/image and Colima were stopped/removed.

### Next Steps

1. 下一步目标：confirm GitHub CI is green for the approved deployment-preparation checkpoint, then begin the manual Render Blueprint flow one screen at a time.
2. 预计修改文件：none for CI review; any CI fix must be separately scoped and verified before another commit.
3. 为什么要改：Render should consume one verified remote SHA, and rollback needs that SHA to remain identifiable.
4. 风险：the checkpoint touches database, auth-session storage, crawler state, API startup, and Docker; do not deploy it if required CI checks fail.
5. 验证方式：inspect the pushed commit and GitHub Actions results, then follow the staging acceptance checklist in `docs/RENDER_DEPLOYMENT_GUIDE.md`.
6. 是否需要用户确认：the current checkpoint commit/push is approved; any merge, Render/AWS resource creation, paid plan, secret entry, migration apply, or deployment still requires explicit confirmation at the relevant step.

After the checkpoint and CI, follow `docs/RENDER_DEPLOYMENT_GUIDE.md` one section at a time. Stop after each Render resource group and verify its success signal before proceeding.

### Do Not Touch Without Approval

- Real `.env` files, Render Secrets, AWS credentials, AI keys, map/Meituan tokens, XHS cookies.
- Any real Render/AWS resource, plan upgrade, deploy, merge, or branch operation. Only the currently approved deployment-preparation checkpoint commit/push is exempt from this restriction.
- `scripts/migrate_sqlite_to_postgres.py --apply` or any production/staging database write.
- Billing/payment/quota semantics and real payment integration.
- Model training, cloud model mutation lock, production registry/manifest, or model release artifacts.
- Freshness hard gates, crawler policies, or external XHS access rules.

## 2026-07-07 Stage Update - Structured Chat Plan Options

### 本轮完成了什么

- 将对话优化里的 A/B/C 从“普通聊天文本”升级为“结构化候选方案卡片”。
- 后端新增多候选输出协议：当用户要求多个方案/方案A-B-C/几个标题/让我选择时，模型应输出 `<options><option id="A">...</option></options>`。
- 后端只解析明确 XML `<option>` 标签，不解析自由文本，避免再次用正则误拆自然语言。
- `/chat/message` 发现 2 个以上结构化候选时：
  - 对每个候选做本地评分。
  - 通过 SSE 发 `plan_options`。
  - 保存到当前 chat session 的 `pending_plan_options`。
  - 不自动保存任何一个候选为正式笔记版本。
- 新增 `/chat/select-plan`：
  - 用户点击某个候选方案后才保存为正式 note version。
  - 更新 `notes`、`growth_records`、chat session 当前稿、当前分数、版本号。
  - 返回标准 `note_update` 形态，前端复用同一套左侧笔记/分数/版本更新逻辑。
- 前端新增候选方案卡：
  - 显示方案 A/B/C、方向、标题、正文预览、评分、相对当前版本提升值、质量提示。
  - 支持展开全文。
  - 点击 `选择并保存` 后调用 `/chat/select-plan`，保存成功后更新左侧当前笔记、分数、版本、localStorage。
- 前端收到 `plan_options` 后，会把原本可能包含 XML 的 AI 气泡替换成一句可读 summary，避免用户看到内部结构化标签。
- 本阶段没有运行真实 AI、真实 crawler、数据库迁移、seed、reset、deploy 或生产写操作。

### 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/api.py`: 增加多候选 prompt 协议、结构化候选解析/评分、`pending_plan_options` 持久化、`/chat/select-plan` 保存接口。
- `NoteAI_Pro_Demo_Framer.html`: 增加候选方案卡 UI、`plan_options` SSE 事件处理、点击保存候选方案的前端逻辑。
- `tests/test_api_contracts.py`: 增加后端契约测试，确认候选方案不会自动保存，选择候选后才写入下一版本。
- `tests/test_frontend_report_static.py`: 增加静态断言，确认前端有候选卡、选择按钮、选择接口调用和 summary 替换。
- `.codex/handoffs/current-task.md`: 记录本阶段结果和验证情况。

### 做了哪些关键决策

- 候选方案不是正式版本；只有用户点击 `选择并保存` 后才成为笔记库版本链的一部分。
- 不靠前端正则拆聊天文本；只接受后端明确结构化的 `<option>` 标签。
- 候选方案评分使用本地评分链，不为候选卡额外调用 AI 二修，避免无计划增加 live AI 成本。
- `/chat/select-plan` 不额外扣 AI 费用，因为它不调用模型，只保存已生成候选。
- 候选方案随 chat session 存入现有 `generate_ctx_json`，不新增 DB schema。

### 运行了哪些命令

- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_chat_plan_options_are_structured_and_not_auto_saved tests.test_api_contracts.ApiContractTests.test_chat_select_plan_saves_chosen_option_as_next_version`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `node - <<'NODE' ... inline_scripts_syntax ... NODE`
- In-app Browser smoke for `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=plan-options-smoke&page=chat`
- Local Playwright rendered smoke for `plan_options` card rendering and selecting方案 B
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m py_compile model/*.py`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `npm run test:e2e`
- `git diff --check -- model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py tests/test_frontend_report_static.py .codex/handoffs/current-task.md`

### 每个命令的结果

- `py_compile model/api.py`: passed.
- Targeted structured plan API tests: passed, 2 tests.
- Frontend static tests: passed, 14 tests.
- Inline JS syntax parse: passed, 1 inline script.
- In-app Browser smoke: page identity, screenshot, and console health passed; DOM snapshot still unavailable due known `incrementalAriaSnapshot` issue.
- Local Playwright rendered smoke: passed.
  - `plan_options` 渲染 3 张候选卡。
  - AI XML 气泡被 summary 替换。
  - 点击方案 B 后发送 `{session_id, option_id:"B"}` 到 `/chat/select-plan`。
  - 左侧当前笔记更新为方案 B，分数 `70.5`，版本 `第 2 版`，状态 `第 1 次优化`。
  - localStorage 保存 `note-v2 / version=2 / score=70.5`。
  - Screenshot evidence saved outside repo at `/tmp/noteai-plan-options-smoke.png`.
- Full API contract tests: passed, 141 tests.
- `py_compile model/*.py`: passed.
- Full unittest discovery: passed, 264 tests.
- `npm run test:e2e`: passed, 3 tests.
- `git diff --check`: passed.

### 当前仍然失败的问题

- 本阶段自动化和渲染 smoke 没有剩余失败。
- 尚未运行真实 AI live sample 来确认模型在真实对话里稳定输出 `<options>`。需要时必须先输出 Live API Run Plan。
- In-app Browser DOM snapshot 仍受本地 Browser runtime 限制不可用，已用 Playwright 补交互证明。

### 当前未完成工作

- 用户刷新页面后，手测“让 AI 给 3 个方案 -> 点击其中一个保存 -> 笔记库版本链是否追加”。
- 如真实模型没有稳定按 `<options>` 输出候选，需要做 1-3 条受控 live AI sample，再微调多候选 prompt。
- 如果用户希望“基于此方案继续优化”不保存而直接追问，可在候选卡上再加第二个按钮；本阶段先做最安全的“选择并保存”。

### 当前最高风险

- 真实 AI 可能仍以普通 markdown 输出 A/B/C，而不是结构化 `<options>`；代码已具备结构化接收能力，但真实提示遵循度仍需 live 验证。
- 大 diff/worktree 仍包含与本阶段无关的 crawler、model-router、start_all、tools 等未提交改动，后续 commit 必须精确分组。
- 如果浏览器缓存旧 HTML，用户可能看不到候选卡，需要刷新并确认本地服务加载最新文件。

### 下一步最小可行计划

1. 刷新前端页面。
2. 从真实 AI 内容诊断或爆文生成进入对话优化。
3. 让 AI “给我三个不同优化方案/方案A-B-C让我选”。
4. 如果出现候选卡，点击其中一个，检查左侧分数/版本和笔记库版本链。
5. 如果没有出现候选卡，先做受控 live AI sample，确认模型是否没有遵循 `<options>` 协议，再只调 prompt。

### 哪些地方不能在未经确认的情况下修改

- Production config, `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands。
- Billing/payment/quota semantics, auth/session/admin permissions。
- 真实 AI 批量调用、crawler/worker 运行、外部 XHS 访问、训练数据入库。
- 与本阶段无关的 crawler、model-router、sidecar、工具脚本和图片 artifact 改动。

## 2026-07-07 Stage Update - Chat Score/Version Authority Fix

### 本轮完成了什么

- 排查并修复用户截图中“诊断报告 62 分、笔记库 v2 70.5 分、对话页显示 71 / 第3版 / 不知道是哪篇”的口径混乱。
- 确认根因不是单一分数算法问题，而是三类问题叠加：
  - 前端聊天仪表盘把小数分数 `Math.round()` 成整数，导致 `70.4803` 显示成 `71`。
  - 聊天页进入/恢复/更新时版本计数会被前端自行推进，导致一次 v2 更新可能显示成“第3版”。
  - 聊天历史中的 A/B/C 草稿没有结构化评分，后续追问“方案A分数”时容易把草稿和后端保存的最终稿混在一起。
- 修复聊天分数显示为一位小数口径：`70.4803 -> 70.5`，`62.0 -> 62`。
- 修复 `note_update` 事件携带并使用后端保存版本 `saved_note_version`，前端不再凭空自增版本。
- 修复三条入口的版本初始化：
  - `AI 内容诊断 -> 选方案 -> 对话优化`
  - `AI 生成爆文 -> 对话优化`
  - `笔记库历史版本 -> 继续优化`
- 额外发现并修复两个真实前端入口 bug：
  - `startChatFromDiagnosis()` 误读未定义变量 `d`。
  - `startChatOptimization()` 误读未定义变量 `note`。
- 把诊断报告成长闭环中的“方案”文案改成“最佳建议”，并明确“仅为诊断建议；点击方案后才进入对话”，避免用户误以为这是已选择/已保存版本。
- 后端聊天 prompt 增加“对话分数与版本口径”，明确当前笔记标题/正文/评分为权威最终稿，历史 A/B/C 草稿没有保存为 `note_update` 时不应被当成最终评分。
- 后端 `note_update` SSE 增加 `saved_note_version`，保存后向会话历史追加隐藏的“当前最终稿”记录，降低后续追问时模型引用旧草稿的概率。
- 未运行真实 AI、真实 crawler、数据库迁移、seed、reset、deploy 或生产写操作。

### 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/api.py`: 给聊天系统 prompt 加入权威分数/版本口径；`note_update` 事件携带 `saved_note_version`；保存当前最终稿后写入会话历史；`/chat/start` 的 `generate_context` 保留选中方案分数和当前分数。
- `NoteAI_Pro_Demo_Framer.html`: 统一分数格式化；使用后端版本号渲染聊天版本；修复诊断/生成/笔记库三条入口的版本初始化；报告生命周期文案从“方案”改为“最佳建议”。
- `tests/test_api_contracts.py`: 增加后端契约断言，确认 `/chat/start` 保留 `selected_plan_score/current_score`，`note_update` 返回 `saved_note_version` 并追加当前最终稿上下文。
- `tests/test_frontend_report_static.py`: 增加静态断言，防止聊天版本再次前端自增、分数再次整数化、入口再次读取错误变量。
- `.codex/handoffs/current-task.md`: 记录本阶段结果，便于后续继续手测和修复。

### 做了哪些关键决策

- 当前可交付版本以“后端保存并评分后的 note_update”为权威，不以聊天里出现过的 A/B/C 草稿为权威。
- 诊断报告中的 A/B/C 是诊断建议；只有用户点击某个方案进入对话并保存后，才成为笔记库版本链的一部分。
- 前端只展示后端返回的保存版本号，不再靠本地计数推断新版本。
- 分数显示保留最多一位小数，避免 `70.5` 被误读为 `71`。
- 本阶段只做 mock/fixture/rendered smoke 和自动化回归；不需要 live AI，因为修复点是状态口径和 UI/事件契约。

### 运行了哪些命令

- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_chat_start_prefers_selected_plan_score_over_original_diagnosis_score tests.test_api_contracts.ApiContractTests.test_chat_note_update_is_emitted_after_version_save`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `node - <<'NODE' ... inline_scripts_syntax ... NODE`
- `git diff --check -- model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py tests/test_frontend_report_static.py`
- In-app Browser smoke for `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=score-version-smoke&page=chat`
- Local Playwright rendered smoke for chat score/version, diagnosis entry, generation entry, library entry, and report lifecycle label
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m py_compile model/*.py`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `npm run test:e2e`

### 每个命令的结果

- `py_compile model/api.py`: passed.
- Targeted API contract tests: passed, 2 tests.
- Frontend static tests: passed, 13 tests.
- Inline JS syntax parse: passed, 1 inline script.
- `git diff --check`: passed.
- In-app Browser smoke: page identity, screenshot, and console health passed; DOM snapshot still unavailable in this runtime due known `incrementalAriaSnapshot` issue.
- Local Playwright rendered smoke: passed.
  - 初始 `70.4803` 显示为 `70.5`、`第 1 版`、`初始版本`。
  - `note_update(saved_note_version=2)` 后显示为 `70.5`、`第 2 版`、`第 1 次优化`，toast 为 `v2 · 新评分 70.5分`。
  - localStorage 保存 `noteId=note-v2`、`version=2`、`score=70.5`。
  - 诊断方案入口使用 `selected_plan_score=68.2` 并显示 `第 1 版`。
  - 爆文生成入口显示 `第 1 版`，没有未定义变量错误。
  - 笔记库 v2 入口显示 `第 2 版`。
  - 报告成长闭环显示 `最佳建议 / 仅为诊断建议；点击方案后才进入对话`。
  - Screenshot evidence saved outside repo:
    - `/tmp/noteai-score-version-chat.png`
    - `/tmp/noteai-score-version-report.png`
- Full API contract tests: passed, 139 tests.
- `py_compile model/*.py`: passed.
- Full unittest discovery: passed, 261 tests.
- `npm run test:e2e`: passed, 3 tests.

### 当前仍然失败的问题

- 本阶段自动化和渲染 smoke 没有剩余失败。
- In-app Browser DOM snapshot 仍受本地 Browser runtime 限制不可用；已用 Playwright 渲染 smoke 补足交互证明。

### 当前未完成工作

- 用户需要刷新前端页面，避免浏览器继续使用旧 JS。
- 如果要验证真实模型在追问“方案A分数是多少”时的回答质量，需要另开受控 live AI sample，并先输出 Live API Run Plan。
- 当前 worktree 仍有与本阶段无关的 crawler/model-router/tool artifacts 等脏文件，后续 checkpoint/commit 需要精确分组。

### 当前最高风险

- 浏览器缓存或旧本地服务进程可能让用户手测打到旧前端/旧 API。
- 真实 AI 多轮追问仍可能受历史草稿影响；本阶段已用 prompt 和隐藏最终稿上下文降低风险，但未做 live AI 追问验证。
- 大 diff 中存在其他未提交模块改动，不能把本阶段修复和 crawler/sidecar 等无关改动混提交。

### 下一步最小可行计划

1. 刷新用户页面，优先复测三条链路：
   - AI 内容诊断 -> 开始对话优化 -> 重写一版 -> 笔记库 v1/v2。
   - AI 生成爆文 -> 开始对话优化 -> 重写一版 -> 笔记库 v1/v2。
   - 笔记库打开历史版本 -> 继续对话优化 -> 新版本接在同一卡片下。
2. 如果用户仍看到 `71` 或错误版本号，先确认浏览器是否加载最新 `Last-Modified` 的 HTML，再查本地服务进程。
3. 如果真实 AI 对“方案A分数”回答仍混淆，做 1-3 条受控 live AI 追问验证后，只调聊天上下文口径，不做大重构。

### 哪些地方不能在未经确认的情况下修改

- Production config, `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands.
- Billing/payment/quota semantics, auth/session/admin permissions.
- 真实 AI 批量调用、crawler/worker 运行、外部 XHS 访问、训练数据入库。
- 与本阶段无关的 crawler、model-router、sidecar、工具脚本和图片 artifact 改动。

## 2026-07-07 Stage Update - Structured Supplement Facts in Chat Optimization

### 本轮完成了什么

- Fixed the chat supplement UX where clicking `补充人均/价格` or `补充必点` only wrote text into the bottom chat input and could overwrite another supplement draft.
- Replaced supplement buttons with inline fields inside the supplement card, allowing multiple missing facts to be filled independently.
- Added a clear `提交补充并优化` action that sends structured `supplement_values` to `/chat/message`.
- Kept the bottom chat draft independent from supplement fields; clicking and submitting supplement facts no longer overwrites the normal chat input.
- Added backend support for `ChatMessageInput.supplement_values`.
- Added backend normalization that maps structured fields into fact boundaries, for example:
  - `price` -> `价格/人均`
  - `must_order` -> `必点/招牌菜`
  - `business_hours` -> `营业时间`
- Merged user-supplied supplement facts into the same-round chat system prompt before the model call, so Hermes/agents can use the facts immediately instead of treating them as loose natural-language chat.
- Fixed chat session persistence so updated `generate_ctx_json` is written on conflict; this keeps newly confirmed supplement facts recoverable after a local API restart.
- Added backend and frontend regression tests. No live AI call, crawler, migration, seed, reset, deploy, production config change, or production DB write was run in this stage.

### 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/api.py`: Added `supplement_values` to `/chat/message`, normalized structured supplement values into `fact_context`, injected them before `_build_chat_system_prompt()`, and updated chat session persistence to write `generate_ctx_json` on update.
- `NoteAI_Pro_Demo_Framer.html`: Reworked the supplement card into inline multi-field inputs with a submit button; extended `chatSendMessage()` so structured supplement submits do not overwrite bottom chat drafts or accidentally send current attachments.
- `tests/test_api_contracts.py`: Added a backend contract test that verifies `price`/`must_order`/`business_hours` merge into `fact_context`, preserve `11:00-22:00` time formats, and appear in the chat system prompt.
- `tests/test_frontend_report_static.py`: Added static assertions for card-local fields, `supplement_values` payload, submit button text, and a guard against the old `inp.value = item.action_text` behavior.
- `.codex/handoffs/current-task.md`: Recorded this stage per project workflow.

### 做了哪些关键决策

- Supplement facts are treated as structured confirmed user facts, not as a fragile free-text instruction in the bottom chat box.
- User-supplied facts override older same-label fact lines in `fact_context` to avoid stale values such as old prices being read first.
- `11:00-22:00` style time strings must not be damaged by generic colon-prefix stripping.
- Supplement submit uses `useCurrentAttachments: false`, so a user can keep an unrelated attachment or draft in the bottom composer without it being accidentally sent by a supplement card.
- This stage used mock SSE/browser validation only; real AI wording quality still needs a controlled live sample later.

### 运行了哪些命令

- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_chat_start_surfaces_missing_fact_supplement_prompts tests.test_api_contracts.ApiContractTests.test_chat_structured_supplements_merge_into_fact_context`
- `node - <<'NODE' ... inline_scripts_syntax ... NODE`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `git diff --check -- model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py tests/test_frontend_report_static.py`
- In-app Browser smoke for `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=supplement-facts&page=chat`
- Local Playwright mock rendered smoke for supplement card open/fill state
- Local Playwright mock payload smoke for `/chat/message`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `.venv/bin/python -m py_compile model/*.py`
- `npm run test:e2e`

### 每个命令的结果

- `py_compile model/api.py`: passed.
- Frontend static tests: passed, 13 tests.
- Targeted chat supplement API tests: passed, 2 tests.
- Inline JS syntax parse: passed, 1 inline script.
- Full API contract tests: passed, 139 tests.
- `git diff --check`: passed.
- In-app Browser smoke: page identity passed, screenshot captured, no relevant console errors or warnings; DOM snapshot still unavailable in this runtime due the known `incrementalAriaSnapshot` issue.
- Local Playwright rendered smoke: passed after waiting for page initialization before injecting mock chat state.
  - Confirmed supplement card renders inside the active chat area.
  - Confirmed `补充人均/价格` and `补充必点` open card-local inputs.
  - Screenshot evidence saved outside repo at `/tmp/noteai-supplement-card-stable-after-init.png`.
- Local Playwright payload smoke: passed.
  - Captured `/chat/message` payload includes `supplement_values: {"price":"100元","must_order":"小青龙乌冬、汤泡饭"}`.
  - Confirmed bottom draft stayed `底部草稿保留` before and after supplement submit.
  - Confirmed visible user bubble summarizes the submitted facts.
  - Confirmed no relevant console errors or warnings.
- Full unittest discovery: passed, 261 tests.
- `py_compile model/*.py`: passed.
- `npm run test:e2e`: passed, 3 tests.

### 当前仍然失败的问题

- No failing automated test remains for this stage.
- No live AI `/chat/message` sample was run in this stage, so natural integration quality of structured supplement facts still needs controlled live verification.
- In-app Browser DOM snapshot remains blocked by the local Browser runtime issue; interaction proof used local Playwright fallback.

### 当前未完成工作

- Reload/restart local frontend/API before user retests if the browser is still serving stale JS.
- Run one controlled live chat optimization sample later, with Live API Run Plan, to verify the model naturally incorporates `价格/人均` and `必点/招牌菜` without sounding like a hard ad.
- Consider adding a first-class persisted display of confirmed supplement facts in the chat UI/history if users need to review or edit them after submission.

### 当前最高风险

- Real AI may still phrase user-supplied facts unnaturally; this stage proves data plumbing and UI behavior, not final copy quality.
- The worktree still contains unrelated pre-existing dirty files outside this stage, including crawler/trends/model-router/tool artifacts.
- Existing saved chat sessions before this change do not retroactively gain structured supplement values.

### 下一步最小可行计划

1. Reload the user page and retest a normal diagnosis/generation -> chat optimization flow.
2. Click multiple supplement prompts, fill them in-card, and submit once.
3. Confirm the generated rewrite uses those facts naturally and the note version saves under the same card.
4. If live AI phrasing is poor, tune only the chat prompt/fact integration boundary with a controlled live sample.

### 哪些地方不能在未经确认的情况下修改

- Production config, `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands.
- Billing/payment/quota semantics, auth/session/admin permissions.
- Real AI batch calls, crawler/worker runs, external XHS access, or training-data ingestion.
- Pre-existing unrelated Kimi/model-router/live-smoke/tool-image changes outside this structured supplement facts scope.

## 2026-07-07 Live QA Update - Supplement Facts Naturalness Sample

### 本轮完成了什么

- Ran one controlled live AI sample to verify whether structured supplement facts are naturally integrated into chat optimization output.
- Tested synthetic food note context with user-supplied facts:
  - `price`: `100元`
  - `must_order`: `小青龙乌冬、汤泡饭`
- Verified the backend fact merge happened before the real model call:
  - `fact_context_contains_price=true`
  - `fact_context_contains_must_order=true`
- Confirmed the live model output did integrate `人均100元`、`小青龙乌冬`、`汤泡饭` in a readable and mostly natural way.
- Found an important remaining fact-boundary issue: the live output introduced unprovided details such as `带了四个朋友` and `四到八人`, and the quality issue list caught this as `出现未提供的人数/适用规模信息，结构化事实不能编造`.
- No code was changed in this live QA stage besides this handoff update.
- Follow-up user decision: this level of plausible scene/storytelling detail is acceptable and does not need to be fixed now.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the controlled live AI verification result, actual model-router observations, quality assessment, and next risk.

### 做了哪些关键决策

- Used direct `_chat_sse_generator()` invocation instead of `/chat/message` endpoint to avoid local billing/notes DB side effects while still exercising the real chat prompt/model-router path and the new `supplement_values` fact merge.
- Temporarily no-op'd `_persist_chat_session` for the script run, then restored it in `finally`.
- Used synthetic input only; no real user private content was sent.
- Stopped after one live sample; no batch, no concurrency, no infinite retry.
- Product decision: allow reasonable scene-level storytelling embellishment for readability and爆款感, such as friend gatherings or suggested use scenes. Continue to strictly guard hard facts like price, address,营业时间, official ratings, discounts, quotas, rankings, or external-source claims.

### 运行了哪些命令

- `.venv/bin/python - <<'PY' ... controlled_live_supplement_sample ... PY`

### 每个命令的结果

- Live sample completed successfully with no SSE error events.
- Observed model-router logs:
  - `task=content_gen model=claude-haiku-4-5-20251001 attempt=1/3`
  - `task=chat model=claude-sonnet-4-6 attempt=1/3`
- Actual streaming events included:
  - `typing=1`
  - `thinking_start=1`
  - `thinking_chunk=40`
  - `thinking_end=1`
  - `content_chunk=37`
  - `quality_repaired=1`
  - `note_update=1`
  - `done=1`
- Elapsed time: about 119.3 seconds.
- The returned note update had score `68.2`, grade `良好`, and no saved note ID because the script did not use a real user/session save path.
- The note update body naturally included the confirmed facts:
  - `人均100元`
  - `小青龙乌冬`
  - `汤泡饭`
- Remaining quality issues included:
  - title is short because the sample intentionally used `不改标题`
  - missing business hours/weekend info
  - unprovided people-count / suitable-scale details were introduced

### 当前仍然失败的问题

- Supplement facts data plumbing is live-verified.
- The live chain can add plausible experience/scale storytelling details; user accepts this product behavior, so it is no longer treated as a blocking bug.
- The sample did not use the full authenticated `/chat/message` endpoint to avoid DB/billing side effects, so endpoint-level billing/session writes were not live-verified in this stage.

### 当前未完成工作

- Do not add the previously proposed count/party-size guard unless the user later changes this product direction.
- Keep strict guardrails for hard facts such as price, address,营业时间,官方评分,优惠,库存/名额,真实榜单, or external data.
- Separately test full endpoint path with the long-term test account only if the user explicitly wants local DB/session/billing behavior included.

### 当前最高风险

- The accepted product behavior depends on a clear boundary: scene-level storytelling is acceptable, but hard facts must remain sourced or user-supplied.

### 下一步最小可行计划

1. Leave scene-level narrative embellishment unchanged.
2. Continue user testing on the full diagnosis/generation/chat flow.
3. If the copy fabricates hard facts, fix only that narrower hard-fact boundary.
4. Run another controlled live AI sample only when a new copy-quality issue needs verification.

### 哪些地方不能在未经确认的情况下修改

- Production config, `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands.
- Billing/payment/quota semantics, auth/session/admin permissions.
- More than 10 live AI calls, live crawler runs, external XHS access, or training-data ingestion without explicit confirmation.

## 2026-07-07 Stage Update - Screenshot OCR Title/Body/Topic Separation

### 本轮完成了什么

- Fixed the screenshot OCR handoff risk where topics could be removed from body-length accounting but not preserved as first-class topics for diagnosis.
- Added backend OCR topic extraction: `/extract-screenshot` now asks the vision model for `tags`, strips inline `#话题` from `body`, and returns clean `body + tags`.
- Added backend multi-image OCR validation topic preservation: `/validate-ocr` now returns `title/body/tags/domain/char_count`, with `body` excluding topics and `tags` deduplicated.
- Added frontend screenshot confirmation UI for three separate lanes: `标题`、`正文预览`、`话题`.
- Updated frontend diagnosis submit behavior: it recombines `正文 + 话题` for `/analyze/stream` scoring, while `ocr_char_count` stays body-only so hashtags do not inflate body length.
- Added mock tests and rendered smoke. No real OCR, live AI, crawler, DB migration, seed, reset, deploy, or production write was run in this stage.

### 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/api.py`: Added OCR tag normalization/splitting helpers; expanded `/extract-screenshot` and `/validate-ocr` contracts to preserve topics separately from body.
- `NoteAI_Pro_Demo_Framer.html`: Added `ss-tags-display`, frontend tag normalization/splitting/joining helpers, and submit recombination so scoring receives tags without counting them in body length.
- `tests/test_api_contracts.py`: Added backend tests that OCR body/tag separation preserves tags and keeps body clean for scoring.
- `tests/test_frontend_report_static.py`: Added static assertions for the new screenshot OCR topic lane and submit recombination logic.
- `.codex/handoffs/current-task.md`: Recorded this stage per project workflow.

### 做了哪些关键决策

- OCR confirmation should be structured as `标题 / 正文 / 话题`, not one mixed text blob.
- Topics should not be counted as body length, but they must be recombined into `desc` before scoring so `commercial_body_tag_count` and `tag_count` are not zero.
- Backend accepts both new `tags` fields and legacy inline `#话题` inside `body`, so older OCR responses are still handled safely.
- Historical reports will not retroactively gain missing topics; this fix applies to new screenshot OCR runs after reload.

### 运行了哪些命令

- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_extract_screenshot_preserves_uploaded_image_media_type tests.test_api_contracts.ApiContractTests.test_ocr_body_and_tags_are_separated_for_scoring tests.test_api_contracts.ApiContractTests.test_validate_ocr_preserves_topics_as_separate_field tests.test_api_contracts.ApiContractTests.test_validate_ocr_agent_merges_topics_without_polluting_body tests.test_api_contracts.ApiContractTests.test_extract_screenshot_maps_moonshot_network_error_to_503`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `node - <<'NODE' ... inline_scripts_syntax ... NODE`
- Local Playwright mock screenshot OCR rendered smoke:
  - inject mocked OCR result with inline tags and explicit tags
  - render screenshot confirmation section
  - intercept `/analyze/stream`
  - verify submitted `desc` and body-only `ocr_char_count`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `npm run test:e2e`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `.venv/bin/python -m py_compile model/*.py`
- `git diff --check -- model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py tests/test_frontend_report_static.py`

### 每个命令的结果

- Targeted OCR API tests: passed, 5 tests.
- Frontend static tests: passed, 13 tests.
- Inline JS syntax parse: passed, 3 inline scripts.
- Local Playwright mock rendered smoke: passed.
  - Confirmed UI title: `点都德红米肠推荐`.
  - Confirmed UI body preview excludes hashtags.
  - Confirmed UI topics: `#广州美食 #北京路早茶 #虾饺皇`.
  - Confirmed intercepted `/analyze/stream` payload sends `desc` as body plus tags.
  - Confirmed `ocr_char_count=11`, excluding tags.
- Full API contract tests: passed, 137 tests.
- `npm run test:e2e`: passed, 3 tests.
- Full unittest discovery: passed, 258 tests.
- `py_compile model/*.py`: passed.
- `git diff --check`: passed.

### 当前仍然失败的问题

- No failing test remains for this stage.
- No real OCR/live AI sample was run in this stage, so provider output quality for the new `tags` instruction still needs controlled live verification later.

### 当前未完成工作

- Restart/reload local services before user retests, otherwise the browser/API may still serve older code.
- Run one controlled live screenshot OCR sample later with a Live API Run Plan to ensure Kimi returns or preserves `tags` as expected.
- If real OCR returns non-hashtag topic text such as `广州美食、北京路早茶`, verify normalization in the UI and backend still produces `#广州美食 #北京路早茶`.

### 当前最高风险

- Historical saved diagnoses that already lost topics cannot be repaired without original OCR/source images.
- New backend contract is backward-compatible for old body-inline hashtags, but real provider adherence to the new `tags` field needs live verification.
- Mixed worktree risk remains: pre-existing unrelated uncommitted files are still present outside this OCR stage.

### 下一步最小可行计划

1. Restart local services or reload frontend/API.
2. User retests screenshot upload with images that visibly contain topic tags.
3. Confirm the recognition panel shows `标题 / 正文 / 话题`.
4. Confirm the resulting diagnosis no longer shows topic count as 0 when the screenshot contained topics.
5. If still failing, capture a controlled live OCR result summary without exposing full user content or secrets.

### 哪些地方不能在未经确认的情况下修改

- Production config, `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands.
- Billing/payment/quota semantics, auth/session/admin permissions.
- Real AI batch calls, crawler/worker runs, external XHS access, or training-data ingestion.
- Pre-existing unrelated Kimi/model-router/live-smoke/tool-image changes outside this OCR topic scope.

## 2026-07-07 Stage Update - Title Length Strategy and Refinement Metadata

### 本轮完成了什么

- Changed the AI rewrite title delivery rule from a hard `≤18字` mindset to `优先16-20字，平台硬上限20字`.
- Removed direct fallback hard-cutting of titles. Fallback now only accepts narrow semantic compression candidates; if semantic compression cannot produce a complete 16-20字 title, it preserves the original title and lets quality metadata mark it as `需精修`.
- Added title quality detection for titles that collapse into `价格+菜品+泛评价`, so plans like `198元龙虾乌冬，汤浓到底不腻` are flagged as needing a fuller attraction point.
- Added backend `title_meta` fields for diagnosis rewrite plans, including title length, target range, platform max, compression status, and refine status.
- Added frontend chips under each rewrite title to show `标题字数 / 目标16-20字` and `未压缩 / 已语义压缩 / 需精修`.
- Verified the UI with a localhost mock report. No real AI call was made in this stage.

### 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `model/api.py`: Updated title target constants, prompt contracts, fallback compression behavior, title quality issues, and rewrite-plan metadata output.
- `NoteAI_Pro_Demo_Framer.html`: Added visible title metadata chips and changed the manual title placeholder from `≤18字` to platform max 20 / AI target 16-20.
- `tests/test_api_contracts.py`: Updated backend contract tests for no hard-cut fallback, semantic compression, price+dish+generic title detection, and title metadata.
- `tests/test_frontend_report_static.py`: Added static assertions that title metadata UI and new labels remain present.
- `.codex/handoffs/current-task.md`: Recorded this stage per project workflow.

### 做了哪些关键决策

- `16-20字` is now the preferred delivery range; `20字` is the platform hard upper bound.
- A title already inside 16-20字 is not compressed just to be shorter, because that can remove the attraction point.
- Fallback is allowed to do only semantic phrase-level compression, not character slicing.
- If semantic compression fails, preserving the original title is safer than silently truncating; the UI now tells the user `需精修`.
- The frontend only displays backend metadata; it does not apply its own mechanical title truncation.

### 运行了哪些命令

- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_generation_delivery_limits_block_title_boundary_and_overlong_food_body tests.test_api_contracts.ApiContractTests.test_rqs_title_tail_repairs_cover_latest_probe_patterns tests.test_api_contracts.ApiContractTests.test_plan_title_distinct_repair_handles_duplicate_titles`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_title_readability_blocks_score_hacking_titles tests.test_api_contracts.ApiContractTests.test_food_delivery_keeps_sourced_dim_sum_names tests.test_api_contracts.ApiContractTests.test_generation_delivery_limits_block_title_boundary_and_overlong_food_body`
- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `node - <<'NODE' ... inline_scripts_syntax ... NODE`
- `git diff --check -- model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py tests/test_frontend_report_static.py`
- `rg -n "≤18字|18字以内|_TITLE_DELIVERY_MAX = 18|目标18|硬上限.*18|平台.*18" ...`
- Browser local smoke for `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=title-meta-smoke&page=report`
- Local Playwright mock rendered smoke for title metadata chips
- `npm run test:e2e`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `.venv/bin/python -m py_compile model/*.py`

### 每个命令的结果

- Targeted title API tests: passed after updating old hard-cut expectations.
- `py_compile model/api.py`: passed.
- Frontend static tests: passed, 13 tests.
- API contract tests: passed, 134 tests.
- Inline JS syntax parse: passed, 3 inline scripts.
- `git diff --check`: passed.
- `rg` check: remaining `≤18字` only appears in legacy marker-cleaning lists and a static negative assertion, not as an active generation rule.
- Browser local smoke: page identity passed, no relevant console errors; DOM snapshot API is still unavailable in this environment due the known `incrementalAriaSnapshot` runtime issue.
- Browser fixture injection was blocked by the in-app browser runtime disabling `eval`, so local Playwright was used as a supplement.
- Local Playwright mock rendered smoke: passed. A showed `15字 / 目标16-20字 + 需精修`, B showed `16字 / 目标16-20字 + 已语义压缩`, C showed `17字 / 目标16-20字 + 未压缩`; clicking B activated the B panel.
- `npm run test:e2e`: passed, 3 tests.
- Full unittest discovery: passed, 255 tests.
- `py_compile model/*.py`: passed.

### 当前仍然失败的问题

- No failing test remains for this stage.
- The in-app Browser DOM snapshot capability remains unavailable in this environment; rendered validation used page identity/console checks there plus local Playwright mock smoke.

### 当前未完成工作

- Run a real AI sample later, after user confirmation and Live API Run Plan, to verify provider-generated titles now follow 16-20字 and return useful `title_meta`.
- Manually test with the long-term account after services reload, because older saved diagnosis records will not retroactively contain `title_meta`.
- Decide later whether generated-post main title, not just diagnosis rewrite-plan titles, should expose the same title metadata in the generation report.

### 当前最高风险

- Existing saved diagnoses may still display old titles without metadata because the new fields are generated only for new responses.
- Some title quality judgments are heuristic; real AI samples may need further tuning if they over-flag or under-flag industry-specific attraction points.
- Mixed worktree risk remains: there are pre-existing unrelated uncommitted changes outside this title-strategy stage.

### 下一步最小可行计划

1. Restart or reload the local frontend/API if the browser is still serving stale code.
2. Have the user generate one new diagnosis and inspect the three rewrite-plan title chips.
3. If the chip behavior is correct, run one controlled live AI sample only with a Live API Run Plan.
4. Keep any further tuning limited to title strategy and metadata display; avoid unrelated prompt/model refactors.

### 哪些地方不能在未经确认的情况下修改

- Production config, `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands.
- Billing/payment/quota semantics, auth/session/admin permissions.
- Real AI batch calls, crawler/worker runs, external XHS access, or training-data ingestion.
- Pre-existing unrelated Kimi/model-router/live-smoke/tool-image changes outside this title-strategy scope.

## 2026-07-05 Live QA Update - Full AI Diagnosis/Generation Sweep

### 本轮完成了什么

- Used the long-term test account `noteai_pro_test` to run a real end-to-end user QA sweep.
- Ran real AI diagnosis for three entry modes: manual text, screenshot extraction + diagnosis, and video upload + diagnosis.
- Ran real AI generation for three entry modes: text brief, image material, and video material.
- Ran two real chat optimization flows: from a selected diagnosis plan and from a generated post.
- Verified diagnosis report history, library grouped version chains, growth profile records, Hermes memory count, and tracking entry state through API and in-app browser.
- Did not modify business code, did not commit, did not deploy, did not run migrations/seed/reset, did not output secrets.

### 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `.codex/handoffs/current-task.md`: Recorded the live QA sweep, results, remaining issues, risks, and next minimum plan per project workflow.

### 关键决策

- The user explicitly authorized a comprehensive real AI sweep exceeding 10 external AI calls.
- The test was still run sequentially, with no batch pressure, no concurrency load test, and no uncontrolled retry loop.
- Synthetic local food/cafe media was used for screenshot/image/video tests; no real user private material was used.
- Generation results were saved to the local test DB to mimic the frontend `autoSaveGeneratedNote()` behavior and verify library version chains.

### 运行了哪些命令

- `./start_all.sh status`
- `git status --short`
- Code/context inspection commands using `rg` and `sed`
- `.venv/bin/python - <<'PY' ...` live QA script:
  - `/auth/login`
  - `/analyze/stream` manual diagnosis
  - `/extract-screenshot`
  - `/analyze/stream` screenshot diagnosis
  - `/upload-video`
  - `/analyze/stream` video diagnosis
  - `/generate/stream` text brief generation
  - `/generate/stream` image material generation
  - `/generate/stream` video material generation
  - `/notes` save generated post
  - `/chat/start` and `/chat/message` from diagnosis selected plan
  - `/chat/start` and `/chat/message` from generated post
  - `/diagnoses`, `/notes?grouped=true`, `/profile/growth`, `/profile/memories`, `/profile/achievements`, `/notes/tracking`
- In-app Browser rendered smoke for:
  - `page=report`
  - `page=library`
  - `page=profile`
- Follow-up API read checks for grouped library/version chains and profile records.

### 每个命令的结果

- `start_all.sh status`: API 8000, admin 8001, frontend 5173 were running.
- Manual text diagnosis: passed. Score 47.2, 3 plans, model label `claude-routed-5-agents`, elapsed 216.6s.
- Screenshot extraction: passed. Recognized as text screenshot; title/body/domain returned, elapsed 2.8s.
- Screenshot diagnosis: passed. Score 41.0, visual score 55.5, 3 plans, elapsed 223.5s.
- Video upload: passed. Local parser extracted 2 frames for AI use.
- Video diagnosis: passed. Score 65.5, 3 plans, elapsed 223.0s.
- Text brief generation: passed. Score 73.3, complete title/body/variants, elapsed 272.2s.
- Image material generation: passed. Score 74.3, visual score 49.3, complete title/body/variants, elapsed 314.0s.
- Video material generation: passed. Score 71.9, complete title/body/variants, elapsed 284.5s.
- Generated post save: passed; local test DB received the generated root note.
- Chat from diagnosis selected plan: passed. Streaming emitted typing, thinking_start, 80 thinking chunks, thinking_end, 64 content chunks, quality_repaired, note_update, done; elapsed 129.7s.
- Chat from generated post: passed. Streaming emitted typing, thinking_start, 42 thinking chunks, thinking_end, 40 content chunks, quality_repaired, note_update, done; elapsed 106.9s.
- Report UI smoke: passed. Diagnosis history showed the new diagnoses; latest video diagnosis report loaded with growth-loop card.
- Library UI smoke: passed. Main cards showed v1/v2 version chains, score trends, `继续优化`, `追踪效果`, and unbound tracking state.
- Growth profile UI smoke: passed. Profile showed 10 total growth records, latest score curve, 8 note versions, 10 memories, and tracking prompt.
- API grouped library recheck: passed. `/notes?grouped=true` returns `groups`, not `notes`; earlier script check was adjusted. The generated post has v1/v2 score trend 73.3 -> 74.6, and the manual diagnosis has v1/v2 score trend 47.2 -> 72.1.
- Tracking read check: passed but empty; no XHS URL was bound in this test, so real tracking data was not produced.

### 当前仍然失败的问题

- No core live AI endpoint failed in this sweep.
- Real end-to-end latency is too high for the current frontend promise:
  - Diagnosis entries took roughly 216-224s each.
  - Generation entries took roughly 272-314s each.
  - Chat optimization took roughly 107-130s.
- Some generated copy over-infers experience details from limited input, for example claims like long sitting time or not being rushed when those facts were not explicitly provided.
- Video diagnosis root note saved to library can contain raw video-understanding text/markdown, which is useful for audit but not polished as a user-facing library card.
- Tracking is only showing the unbound entry state in this sweep; no real XHS tracking URL, crawler result, or 7-day performance row was verified.

### 当前未完成工作

- Run a real tracking-bind flow with a user-provided XHS URL and verify crawler/sidecar outcome separately.
- Decide whether generated copy should block or downgrade when it invents experiential facts not present in user input.
- Improve long-running UX: background job/resumable state, clearer ETA, and stronger progress events for multi-minute runs.
- Clean up video-diagnosis library presentation so the initial card is not dominated by raw video analysis markdown.
- Add a test/QA script that reads `groups` from grouped library responses correctly.

### 当前最高风险

- Product delivery risk is latency, not basic connectivity: all major live AI paths worked, but the wait time is multi-minute.
- Copy quality risk: factual boundary enforcement is not strict enough for experiential claims.
- Library/presentation risk: video-derived diagnosis notes can look like internal analysis rather than a creator-facing note asset.
- Tracking value risk: the UI loop is ready, but no real bound tracking evidence was produced in this sweep.
- Worktree risk remains mixed: unrelated uncommitted Kimi/live-smoke/tool-image changes still exist outside this QA stage.

### 下一步最小可行计划

1. Fix or design a mitigation for multi-minute AI task UX before calling the flow production-polished.
2. Tighten factual/experiential claim guards in generation and chat repair prompts/scoring.
3. Normalize video diagnosis saved-note presentation for library cards.
4. Add a focused regression test for grouped library `groups` response and version-chain display.
5. Separately run a controlled XHS tracking-bind live test when the user supplies a URL and confirms crawler scope.

### 不能在未经确认的情况下修改

- Production config, `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands.
- Billing/payment/quota semantics or manual credit top-ups.
- Real XHS crawler/sidecar execution, external site access, or production worker scheduling.
- Broad model routing changes, prompt rewrites across all tasks, or Kimi/Claude provider policy changes.

## 2026-07-05 Execution Update - Diagnosis/Library/Profile Growth Loop IA

### 本轮完成了什么

- Reworked the frontend information architecture so `诊断报告`、`我的笔记库`、`成长档案` present one connected growth loop instead of three isolated surfaces.
- Added a diagnosis report lifecycle card that links current diagnosis score, selected rewrite plan score, version archive, tracking status, and Hermes learning state.
- Added a per-note lifecycle strip to library cards so main cards directly show origin, version count, tracking state, and learning回流 state.
- Added growth profile loop insight cards to summarize prediction/optimization, note assets, real tracking calibration, and Hermes learning memory.
- Kept the change frontend-only for this stage: no database schema changes, no API contract changes, no production config changes, no real AI/crawler calls.

### 修改了哪些文件

- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 每个文件为什么修改

- `NoteAI_Pro_Demo_Framer.html`: Added the user-facing growth-loop UI bridge across diagnosis report, library cards, and growth profile. Also expanded profile data loading with a read-only tracking fetch fallback so the profile can show tracking calibration context when available.
- `tests/test_frontend_report_static.py`: Added static coverage that the new lifecycle containers, render functions, and growth-loop wording remain present in the static frontend.
- `.codex/handoffs/current-task.md`: Recorded this stage per project workflow.

### 关键决策

- The user value model is now: diagnose a note, choose or rewrite a version, archive all versions under the same note card, track real performance, then feed the result back into Hermes memory and future generation.
- `评分成长曲线` alone is not enough product value; it now sits inside `预测-优化-真实表现闭环`, with adjacent cards explaining why the data matters.
- The library remains the source-of-truth asset view for note/version/tracking actions; growth profile becomes the cross-note intelligence layer rather than a detached feature.
- No shadcn/React dependency was introduced; the design language was hand-applied to the existing static HTML/CSS/JS surface.

### 运行了哪些命令

- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `git diff --check -- NoteAI_Pro_Demo_Framer.html tests/test_frontend_report_static.py`
- In-app Browser local smoke for:
  - `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=loop-ia&page=profile`
  - `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=loop-ia&page=library`
  - `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=loop-ia&page=report`

### 每个命令的结果

- Frontend static unittest: passed, 11 tests.
- Targeted diff whitespace check: passed.
- Browser profile smoke: passed. `预测-优化-真实表现闭环`、`Hermes 学习`、`真实校准` visible; no relevant console warnings/errors.
- Browser library smoke: passed. Main note cards show direct `继续优化`、`追踪效果`、tracking status, and lifecycle strip; no relevant console warnings/errors.
- Browser report smoke: passed. `本篇成长闭环` visible with diagnosis, selected plan, version, tracking, and Hermes learning states; no relevant console warnings/errors.
- Browser DOM snapshot API was unavailable in this environment, so rendered validation used read-only page evaluation plus screenshots instead.

### 当前仍然失败的问题

- No app-level failure was found in this stage.
- This stage did not run full API contracts, full unit discovery, Playwright e2e, real AI, or real crawler.

### 当前未完成工作

- User should manually test the product loop with the long-term test account: diagnosis -> choose rewrite plan -> chat optimize -> library same-card versions -> tracking -> growth profile summary.
- The UX bridge is still frontend presentation; deeper value requires reliable tracking ingestion and durable linkage between note/version/session/tracking rows.
- Mobile visual QA for the new profile/library/report growth-loop blocks is still pending.

### 当前最高风险

- Mixed worktree risk remains: there are pre-existing uncommitted Kimi/live-smoke/tool-image changes outside this frontend IA stage.
- Product risk: if tracking rows are missing or delayed, Hermes learning cards must not overclaim real-world calibration.
- Data risk: future training usage still needs strict gating so failed/low-confidence crawler results do not enter model-training datasets.

### 下一步最小可行计划

1. Ask the user to refresh and manually test the diagnosis -> optimize -> library -> tracking -> profile loop.
2. If the loop feels right, run targeted API/static tests again and then broaden to full unit discovery.
3. Do mobile viewport browser QA for report, library, and profile.
4. Only after user confirmation, prepare a narrow checkpoint commit that separates this frontend IA work from unrelated Kimi/live-smoke changes.

### 不能在未经确认的情况下修改

- Production config, real `.env`, API keys, tokens, cookies, production DB, migrations, seed/reset/deploy/clean commands.
- Billing/payment/quota semantics, auth/session/admin permissions.
- Real crawler/worker execution, external XHS access, live AI calls, or training-data ingestion.
- Pre-existing Kimi model/live-smoke/tool-image changes that are outside this UI IA scope.

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
- staged secret-pattern scan over cached files
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

## 2026-07-05 Stage Update — Library Primary Tracking Actions Visible

### 1. 本轮完成了什么

- 修复笔记库主卡片入口不可见问题。
- 现在无论是否长期测试账号、无论笔记是 v1 单版本还是多版本链，笔记库主卡都会直接显示：
  - `未绑定追踪/追踪状态`
  - `继续优化`
  - `追踪效果`
- 验证 `noteai_pro_test` 当前本地数据仍是 2 个 v1 单版本、0 个 tracking 记录；修复后这类数据也会直接看到入口。

### 2. 修改了哪些文件

- `NoteAI_Pro_Demo_Framer.html`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `NoteAI_Pro_Demo_Framer.html`: 在 `buildGroupCard()` 主卡片区域直接渲染最新版笔记的 tracking badge 和主操作按钮，避免入口只存在于多版本展开面板。
- `.codex/handoffs/current-task.md`: 按阶段记录本轮修复、验证、风险和下一步。

### 4. 做了哪些关键决策

- 不再把“继续优化/追踪效果/追踪状态”只藏在版本面板里。
- 多版本面板内每个版本的细粒度按钮继续保留。
- 未绑定状态文案从“发布后可绑定真实表现追踪”改为“未绑定追踪 · 发布后可绑定真实表现”，让用户明确看到当前状态。
- 不改后端 API、DB schema、认证、权限、billing、crawler worker。

### 5. 运行了哪些命令

- `git status -sb`
- `nl -ba NoteAI_Pro_Demo_Framer.html | sed -n '9200,9320p'`
- `rg -n "function openNoteDetail|function startChatFromNote|trackNoteFromLibrary|escapeHtml\\(" NoteAI_Pro_Demo_Framer.html`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `git diff -- NoteAI_Pro_Demo_Framer.html | sed -n '1,220p'`
- `python3 - <<'PY' ... noteai_pro_test grouped note summary ... PY`
- `git diff --check -- NoteAI_Pro_Demo_Framer.html`
- Browser validation on `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=library-primary-actions&page=library`

### 6. 每个命令的结果

- 工作区仍存在此前刻意保留的 Kimi/live smoke 未提交改动。
- 前端静态测试：9 tests passed。
- `git diff --check -- NoteAI_Pro_Demo_Framer.html`: 通过。
- `noteai_pro_test` 数据检查：
  - 用户存在。
  - 当前 2 个笔记组。
  - 两个组都是 `version_count=1`。
  - 当前无 tracking 记录。
- 浏览器验证：
  - 页面可加载。
  - DOM 中可见 `未绑定追踪`、`继续优化`、`追踪效果`。
  - 点击主卡 `追踪效果` 可打开追踪弹窗。
  - 未提交 URL，未创建 tracking 记录。
  - 相关 console error/warn 为空。

### 7. 当前仍然失败的问题

- 暂无本轮新增失败。
- 当前打开的浏览器会话不是 `noteai_pro_test` 登录态，但本地 DB 已确认该账号的数据形态；修复逻辑对所有账号和所有单版本/多版本卡片统一生效。

### 8. 当前未完成工作

- 本轮修复尚未 commit/push。
- 当前仍保留此前未提交 Kimi/live smoke 改动：
  - `model/api.py`
  - `model/model_router.py`
  - `tools/ai_prelabel_review_batch.py`
  - `tools/live_ai_smoke.py`
  - `测试图片/`

### 9. 当前最高风险

- 当前 worktree 仍是混合状态；如果后续 commit，需要精确 stage，只提交本轮 HTML/handoff 或用户确认的 scope。

### 10. 下一步最小可行计划

- 用户刷新笔记库页面后，用 `noteai_pro_test` 验证两张旧 v1 卡是否直接显示三个入口。
- 如确认通过，再按用户要求决定是否单独 commit/push 本轮 UI 修复。

### 11. 哪些地方不能在未经确认的情况下修改

- 不提交 Kimi/live smoke scope。
- 不提交 `测试图片/`。
- 不改认证、billing、DB schema、crawler worker 或生产配置。
- 不运行 migration/seed/reset/deploy/clean。

## 2026-07-05 Stage Update — Selected Diagnosis Plan Score Matches Chat Start

### 1. 本轮完成了什么

- 查实并修复：诊断报告中 3 个改写方案各自显示分数，但点击某个高分/喜欢的方案进入对话优化后，chat 起始分可能回落为原诊断分的问题。
- 修复后，用户点击哪个改写方案进入对话优化，chat 起始分就使用该方案的 `suggested_plans[idx].score` / `suggested_title_scores[idx]`。
- 同时让诊断报告顶部“开始对话优化”使用报告展示分，避免 `composite_score` 与 `ces_percentile` 口径漂移。

### 2. 修改了哪些文件

- `NoteAI_Pro_Demo_Framer.html`
- `model/api.py`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `NoteAI_Pro_Demo_Framer.html`: 新增 `diagnosisDisplayScore()`、`diagnosisPlanScore()`，`loadPlanToChat(idx)` 保存选中方案分数，并把 `current_score` / `selected_plan_score` 带进 `/chat/start` 的 `generate_context`。
- `model/api.py`: `/chat/start` 分数优先级改为 `current_score -> selected_plan_score -> plan_score -> composite_score -> ces_percentile`；当使用选中方案分时，等级按该分数重新计算，避免“高分但旧等级”。
- `tests/test_api_contracts.py`: 新增后端 contract test，验证原诊断 51.2、选中方案 76.9 时，chat 起始分必须是 76.9 且等级为优秀。
- `tests/test_frontend_report_static.py`: 新增静态断言，保证前端方案分数会进入 chat start 上下文。
- `.codex/handoffs/current-task.md`: 记录本轮修复、验证和剩余风险。

### 4. 做了哪些关键决策

- 保留原诊断分在上下文中的 `diagnosis_ces_percentile` / `diagnosis_composite_score`，供后续分析弱项使用。
- 用户当前选中方案的分数才是 chat 当前稿起始分。
- 后端继续兼容旧客户端：如果没有新字段，仍按 `composite_score` / `ces_percentile` 兜底。
- 不改 DB schema，不改 billing/auth/crawler，不做真实 AI 调用。

### 5. 运行了哪些命令

- `rg -n "suggested_plans|suggested_title_scores|selected_plan_score|current_score|ChatStartInput|chat_start" ...`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_chat_start_prefers_selected_plan_score_over_original_diagnosis_score tests.test_api_contracts.ApiContractTests.test_chat_start_binds_existing_note_for_library_version_chain`
- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `git diff --check -- NoteAI_Pro_Demo_Framer.html model/api.py tests/test_api_contracts.py tests/test_frontend_report_static.py`
- `git status -sb`

### 6. 每个命令的结果

- 前端静态测试：10 tests passed。
- 聚焦 API contract：2 tests passed。
- `model/api.py` 编译检查：通过。
- 完整 `tests.test_api_contracts`：132 tests passed。
- diff whitespace 检查：通过。
- 测试输出中仍出现外部 provider 错误路径日志，但本轮没有执行 live API 成功调用，也没有做真实批量调用。

### 7. 当前仍然失败的问题

- 暂无本轮新增失败。

### 8. 当前未完成工作

- 本轮修复尚未 commit/push。
- 当前工作区仍混有此前刻意保留的 Kimi/live smoke 未提交改动，尤其 `model/api.py` 内还有 `_KIMI_MODEL` 的旧 hunk，后续 commit 必须精确 stage。

### 9. 当前最高风险

- `model/api.py` 当前同时包含本轮 `/chat/start` 修复和此前 Kimi 默认模型未提交 hunk；如果直接 `git add model/api.py` 会混入无关 scope。

### 10. 下一步最小可行计划

- 让用户刷新页面并实际点诊断报告中的任一改写方案进入对话优化，确认 chat 起始分与该方案卡片分数一致。
- 如用户确认提交，再只 stage 本轮相关 hunk 和测试；不要混入 Kimi/live smoke 改动。

### 11. 哪些地方不能在未经确认的情况下修改

- 不提交 Kimi/live smoke scope。
- 不提交 `测试图片/`。
- 不运行真实 AI、crawler、migration、seed、reset、deploy、clean。
- 不改 billing/auth/DB schema/生产配置。

## 2026-07-05 Stage Update — Video Library Cleanup, Fact Supplement Prompts, Full Thinking Display

### 1. 本轮完成了什么

- 修复视频诊断保存到笔记库时展示原始视频理解 markdown 的问题：模型诊断仍使用完整视频画面理解，笔记库根版本只保存面向用户的素材摘要。
- 在诊断、生成、对话开始链路新增 `supplement_prompts`：把“缺少营业时间/价格/位置/必点”等质量问题转化为自然补充提示。
- 对话优化开场现在会提示用户可补充真实信息；若用户暂时不补充，系统提示模型不得编造这些事实。
- 前端聊天区新增“补充真实信息”快捷卡，用户可一键把补充前缀写入输入框，也可选择“先不补充，继续优化”。
- 生成处理页与聊天区的 thinking/专家过程默认完整展示，完成后不再折叠或隐藏。
- 清理 handoff 中历史 secret-scan 命令的正则细节，避免 production readiness gate 把变量名模式误判为敏感值。

### 2. 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `model/api.py`: 新增视频素材摘要 helper；给 `AnalyzeResponse`、`GenerateResponse`、`ChatStartResponse` 增加 `supplement_prompts`；在诊断/生成/流式生成/chat start 中传递补充提示；把补充事实写入 chat system prompt，明确不得擅自编造；在视频诊断 `input_diagnostics` 中记录视频秒数、抽帧数和实际送 AI 帧数。
- `NoteAI_Pro_Demo_Framer.html`: 新增聊天补充事实卡；诊断方案进入 chat 时传递选中方案质量问题和补充提示；生成/诊断 expert 内容不再前端截断；生成和 chat thinking 完成后继续完整展示。
- `tests/test_api_contracts.py`: 增加视频素材摘要清洗测试、chat start 补充提示测试，并补充视频诊断抽帧审计断言。
- `tests/test_frontend_report_static.py`: 增加静态契约测试，覆盖补充事实卡、补充提示传参、thinking 不折叠旧文案。
- `.codex/handoffs/current-task.md`: 按项目规则记录本阶段完成内容、测试结果、风险和下一步计划；清理历史 secret-scan 记录中的敏感模式字面量。

### 4. 做了哪些关键决策

- 不改变模型诊断上下文：视频画面完整理解仍用于评分和五 agent 诊断，只把用户笔记库展示改成干净摘要。
- 不新增 DB schema，也不把补充提示持久化到新表；补充提示随 API 响应和 chat session context 传递。
- 不把缺失营业时间等事实强行写成占位句；只提示用户补充，或要求模型在未补充时避开编造。
- 尊重用户偏好：不折叠、不过度隐藏 thinking/草稿过程。
- 不修改用户已明确接受的体验型爆款表达边界。

### 5. 运行了哪些命令

- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `.venv/bin/python -m py_compile model/*.py`
- `git diff --check -- model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py tests/test_frontend_report_static.py`
- `.venv/bin/python tools/production_readiness_gate.py`
- `npm run test:e2e`
- Browser render smoke for `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=post-fix&page=chat`
- Temporary Playwright component smoke outside repo for chat supplement card and thinking display.

### 6. 每个命令的结果

- `model/api.py` 编译检查：通过。
- 前端静态测试：12 tests passed。
- API contract 测试：134 tests passed。
- 全量 Python unittest：254 tests passed。
- `model/*.py` 编译检查：通过。
- diff whitespace 检查：通过。
- production readiness gate：PASS，48 checks passed。
- Playwright e2e：3 tests passed；该 e2e 只访问 localhost，且 `/generate/stream` 被 mock，不触发真实 AI。
- Browser render smoke：页面身份正确，`page-chat` 激活，非空，console 无相关 warning/error；Browser 只读上下文无法直接读取全局函数，后续用临时 Playwright component smoke 补证。
- 临时 Playwright component smoke：补充事实卡可见，点击补充按钮会把 `补充营业时间：` 写入输入框；thinking 区可见，完成状态显示“已完整展示”，未出现旧折叠文案；console 无相关错误。

### 7. 当前仍然失败的问题

- 本阶段本地回归未发现失败。
- Browser 只读 evaluate 未能直接读取全局函数，但 DOM 中包含新函数定义；组件级渲染已由临时 Playwright smoke 验证通过。

### 8. 当前未完成工作

- 还需要按用户要求做一轮小样本 live 验证，确认真实 AI 链路返回的 `supplement_prompts`、视频入库摘要和 chat 开场提示都能在真实响应中成立。
- 本轮修复尚未 commit/push。
- 未做真实 crawler、支付、邮件、短信、部署或生产环境验证。

### 9. 当前最高风险

- Live AI 链路耗时仍可能较长；本轮修复改善等待展示，但没有降低真实调用时长。
- `model/api.py` 工作区仍混有此前未提交的其它 scope，后续如需 commit 必须精确 stage，避免混入无关 Kimi/live-smoke 改动。
- 视频摘要清洗是展示层清洗，不是视频理解质量提升；真实视频理解质量仍取决于抽帧、画面清晰度和视觉模型输出。

### 10. 下一步最小可行计划

1. 输出 Live API Run Plan。
2. 用长期测试账号做 1 个视频诊断 live sample，验证抽帧审计、视频摘要入库、无原始 markdown。
3. 用 1 个缺少营业时间的生成/chat start live sample，验证补充提示和开场询问。
4. 如 live 失败，只做最小修复并重跑对应小样本；不扩大到批量或并发。

### 11. 哪些地方不能在未经确认的情况下修改

- 不运行 migration、seed、reset、deploy、clean。
- 不修改生产配置、真实凭据、生产 DB、billing/payment/quota、auth/admin 权限。
- 不触发真实支付、邮件、短信、部署或生产写操作。
- 不运行真实 crawler/worker 或外部站点访问，除非用户单独确认。
- 不提交或删除 `测试图片/`、live smoke 工具、Kimi scope 等无关未提交改动。

## 2026-07-05 Live Validation Update — Current Code Video Cleanup and Supplement Prompts

### 1. 本轮完成了什么

- 在当前代码进程中完成 2 条小样本 live 验证：
  - 视频诊断：合成 3 秒短视频 -> `/upload-video` -> `/analyze/stream` -> 笔记库读取。
  - 缺失事实生成：决策型美食 brief -> `/generate/stream` -> `/chat/start`。
- 验证视频诊断现在返回抽帧审计字段，并且保存到笔记库的根版本不再包含原始 markdown/`深度解读`。
- 验证真实生成返回的质量问题能转化为 `supplement_prompts`，并在 chat start welcome 中提示用户补充、避免编造。
- 发现并记录本地服务管理问题：`start_all.sh stop/start` 未停止长期 screen 持有的旧 8000 API，导致首次 live 打到旧进程；最终用当前 FastAPI app 的 TestClient 方式完成当前代码验证。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录 live 验证计划、结果、旧进程干扰、当前代码验证结论和剩余风险。

### 4. 做了哪些关键决策

- 首次 HTTP live 结果判定为无效验证，因为 OpenAPI 显示旧 API 进程没有 `supplement_prompts` 字段。
- 为避免继续被 8000 端口旧进程干扰，切换为 TestClient 直接运行当前工作区 `api.app`；仍然真实调用外部 AI provider，只是不依赖本地 uvicorn 常驻进程。
- 不继续扩大样本，不并发压测，不运行 crawler/worker，不触发生产写操作。

### 5. 运行了哪些命令

- `./start_all.sh status`
- `./start_all.sh stop && ./start_all.sh start`
- `lsof -nP -iTCP:8000 -sTCP:LISTEN`
- `curl -s http://127.0.0.1:8000/openapi.json | ...`
- local API restart attempts using current `.venv` and uvicorn.
- in-process live validation script using `fastapi.testclient.TestClient(api.app)`:
  - `/upload-video`
  - `/analyze/stream`
  - `/notes?grouped=true`
  - `/generate/stream`
  - `/chat/start`

### 6. 每个命令的结果

- `start_all.sh status`: initially reported main API ok, but later admin/frontend not running after restart attempt.
- `start_all.sh stop/start`: did not stop the old long-running API process; new API bind failed because port 8000 was already in use.
- OpenAPI check against old 8000: `AnalyzeResponse` had `input_diagnostics` but did not have `supplement_prompts`; `GenerateResponse`/`ChatStartResponse` also lacked `supplement_prompts`, proving it was old code.
- Manual uvicorn restart without a persistent wrapper exited after the shell ended; `nohup` attempt first missed the env-file pointer and then confirmed new OpenAPI fields, but process lifetime remained unreliable in this shell context.
- Final in-process current-code live validation completed.

### 7. Live API Result Summary

- 实际 provider/model：Moonshot/Kimi vision path for video understanding; Claude Haiku routed calls for diagnosis/generation/semantic/content generation; Claude Sonnet routed calls for arbitration/repair.
- 实际调用范围：2 main live tasks on current code, sequential, no concurrency.
- 可观察外部调用情况：current-code run included 1 Kimi video-understanding call, multiple Claude Haiku routed calls, and multiple Claude Sonnet arbitration calls from the existing multi-agent pipeline; one Claude Haiku diagnosis attempt failed and was retried by the existing router.
- 视频样本结果：
  - Upload: 3.0s video, 2 frames extracted, 2 frames sent to AI.
  - Analyze complete: score 67.4, grade `良好`, saved note id present.
  - `input_diagnostics`: `video_duration_sec=3.0`, `video_frames_extracted=2`, `video_frames_to_ai=2`, `video_analysis_chars=604`.
  - Library root note: found; includes `【视频素材理解】`; no `###` or `深度解读` raw markdown detected.
- 生成/chat 样本结果:
  - Generate complete: score 63.7, grade `良好`, 1 quality issue.
  - The live quality issue was missing price/person-average, so `supplement_prompts=["price"]`.
  - `/chat/start`: current score 63.7, grade `良好`, `supplement_prompts=["price"]`, welcome includes supplement guidance and no-fabrication wording.
- 是否产生文件或日志：temporary synthetic video was created in system temp and deleted; local DB received test diagnosis/note/chat records; local logs were written under `/tmp`.
- 是否发现真实链路问题：本轮代码目标通过；剩余真实链路问题是 latency 和本地 service manager 不能 reliably replace long-running old API process.

### 8. 当前仍然失败的问题

- 本阶段代码目标无失败：视频入库清洗、抽帧审计、补充提示、chat welcome 均在 current-code live 中通过。
- 本地服务管理仍有问题：存在长期 screen 启动的旧 API 进程时，`start_all.sh stop/start` 可能无法替换它，容易让 smoke 打到旧代码。
- 生成样本的 live issue 最终是缺少价格，不是缺少营业时间；营业时间补充已由 unit/contract 测试覆盖，live 证明了真实 issue -> supplement prompt -> chat welcome 的通用链路。

### 9. 当前未完成工作

- 修复或增强本地 `start_all.sh` 对旧 API/screen 进程的识别与停止策略，避免后续手测误打旧进程。
- 如需要更严格证明“营业时间”live 分支，可另做一个只针对 chat_start 的无外部 AI contract 或再跑一个更定向 live 样本；当前不建议继续扩大调用。
- 本轮修复尚未 commit/push。

### 10. 当前最高风险

- Service manager 风险：本地/未来云端如果有旧 worker/API 进程未替换，测试结果会误判。
- Cost/latency 风险：单个 multi-agent live task 会 fan out 到多个 provider 子调用，真实耗时仍为多分钟级。
- Worktree 风险：仍有无关未提交 scope，后续 commit 必须精确 stage。

### 11. 下一步最小可行计划

1. 修复或至少记录 `start_all.sh`/本地 screen 旧进程替换问题。
2. 再跑一次不调用外部 AI 的 OpenAPI/contract smoke，确认本地服务启动的是当前代码。
3. 如用户确认，再准备本轮最小 checkpoint scope：`model/api.py`、`NoteAI_Pro_Demo_Framer.html`、相关测试和 handoff。

### 12. 哪些地方不能在未经确认的情况下修改

- 不运行 migration、seed、reset、deploy、clean。
- 不修改生产配置、真实凭据、生产 DB、billing/payment/quota、auth/admin 权限。
- 不运行真实 crawler/worker 或外部站点访问。
- 不继续扩大 live AI 样本、并发调用或批量压力测试。
- 不提交无关 Kimi/live-smoke/tool-image scope。

## 2026-07-05 Checkpoint Update — Precise Stage and Local Service Restart Fix

### 1. 本轮完成了什么

- 已完成并推送上一阶段功能 checkpoint：`polish note growth loop and fact prompts`，只包含诊断/生成/笔记库/成长闭环相关代码、测试和 handoff 记录。
- 修复本地 `start_all.sh stop/start` 无法稳定替换旧 API 进程的问题。
- 验证当前本地 8000 API 已暴露新 OpenAPI 字段，不再误打长期 screen 中的旧代码。
- 验证 `./start_all.sh start` 再次运行时会替换旧 listener，并把 API、admin、frontend 留在本地运行状态，方便用户继续手测。

### 2. 修改了哪些文件

- `start_all.sh`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `start_all.sh`: 启动前清理旧 pid、旧 screen session、已占用端口 listener；在 Codex 非交互 shell 环境下优先用 `screen` 托管 API/admin/frontend，避免服务随工具 shell 退出而消失；同时保留无 `screen` 时的 `nohup` fallback。
- `.codex/handoffs/current-task.md`: 记录本阶段 checkpoint scope、服务管理修复、验证命令和剩余风险。

### 4. 做了哪些关键决策

- 本阶段 checkpoint 精确到 Stage：上一阶段业务/UI/API/测试修复已单独 commit/push；本阶段只提交服务管理修复和 handoff。
- 不把未确认的 `model/api.py` Kimi model 行、`model/model_router.py`、AI 预标注工具、live smoke 工具、测试图片目录混入本次提交。
- 不手动杀掉旧的 `noteai-local` screen session；通过端口 listener 清理和固定 `noteai-api`/`noteai-admin`/`noteai-frontend` screen session 管理当前服务。

### 5. 运行了哪些命令

- `git status --short`
- `sed -n '1,260p' start_all.sh`
- `git diff -- start_all.sh`
- `bash -n start_all.sh`
- `screen -ls || true`
- `./start_all.sh stop && ./start_all.sh start`
- `./start_all.sh status`
- `lsof -nP -iTCP -sTCP:LISTEN | egrep ':(8000|8001|5173) ' || true`
- OpenAPI schema check against `http://127.0.0.1:8000/openapi.json`
- PID replacement smoke using `./start_all.sh start`
- `git diff --check -- start_all.sh`

### 6. 每个命令的结果

- `git status --short`: 工作区仍有未确认改动；本阶段只处理 `start_all.sh` 和 handoff。
- `bash -n start_all.sh`: 通过。
- 初始 `screen -ls`: 存在长期 `noteai-local` screen；这是旧进程干扰风险来源。
- `./start_all.sh stop && ./start_all.sh start`: 成功启动主 API、管理后台、前端页面；后续补丁消除了 `screen` session 不存在时的无害噪音。
- `./start_all.sh status`: 主 API `ok`，模型 `v0.4-composite`；管理后台 `ok`；前端页面运行中。
- `lsof`: 8000、8001、5173 均有新的 Python listener。
- OpenAPI schema check: `AnalyzeResponse` 包含 `input_diagnostics` 和 `supplement_prompts`；`GenerateResponse`、`ChatStartResponse` 包含 `supplement_prompts`，证明本地 API 是当前代码。
- PID replacement smoke: 运行前 API/admin/frontend PID 为 `95422/95432/95436`，再次 `start` 后变为 `96657/96665/96669`，证明启动会替换旧 listener。
- `git diff --check -- start_all.sh`: 通过。

### 7. 当前仍然失败的问题

- 本阶段服务管理验证未发现失败。
- 旧的 `noteai-local` screen session 仍然存在，但当前端口 listener 已由新脚本管理；如果该 session 未来重新拉起旧服务，`./start_all.sh start` 会再次清理端口 listener。

### 8. 当前未完成工作

- 本阶段服务管理修复待 commit/push。
- 用户侧仍需继续全量手测 AI 诊断、AI 生成爆文、笔记库、成长档案、追踪效果等产品链路。
- 云端部署方案仍保持计划状态，待所有功能验证商业价值和稳定性后再迁移。

### 9. 当前最高风险

- 工作区仍有其它未确认改动，后续提交必须继续精确 stage。
- 本地长期 screen session 如果由外部脚本重新启动旧服务，仍可能短暂造成误判；固定使用 `./start_all.sh start/status` 可降低风险。
- Live AI 多 agent 链路仍有成本和耗时风险，后续大样本验证需继续记录 Live API Run Plan 和 Result Summary。

### 10. 下一步最小可行计划

1. 精确 stage `start_all.sh` 和 `.codex/handoffs/current-task.md`。
2. 提交服务管理 checkpoint。
3. Push 到 `origin/codex/quality-stabilization-real-chain`。
4. 保持本地服务运行，支持用户继续手测。

### 11. 哪些地方不能在未经确认的情况下修改

- 不提交或删除未确认的 Kimi model 行、`model/model_router.py`、AI 预标注工具、live smoke 工具、测试图片目录。
- 不运行 migration、seed、reset、deploy、clean。
- 不修改生产配置、真实凭据、生产 DB、billing/payment/quota、auth/admin 权限。
- 不触发真实支付、邮件、短信、部署或生产写操作。
- 不扩大 live AI 样本、并发调用、批量跑数据或运行 crawler/worker，除非用户明确确认。

## 2026-07-07 Stage Update — Market Timing Evidence Empty Read-only Diagnosis

### 1. 本轮完成了什么

- 只读排查用户在诊断报告中看到“市场时机证据”无数据的问题。
- 确认当前页面不是缓存问题，API 当前读到的 `美食` 行业热词库确实没有新鲜、合格、分行业证据。
- 确认本地 `./start_all.sh` 当前只启动主 API、admin 和前端，没有启动 `noteai-trends-worker`、`market_timing_worker.py`、`scheduler_a` 或 crawler 进程。
- 确认 `docker-compose.yml` 已定义 `noteai-trends-worker`，但这只在 Docker/云端编排运行时生效，不等于当前本地手测环境已每日运行。

### 2. 修改了哪些文件

- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.codex/handoffs/current-task.md`: 记录市场时机证据为空的运行态根因、当前风险和后续最小修复计划。

### 4. 做了哪些关键决策

- 本阶段不启动真实 crawler/worker，不访问外部站点，不写入 hot keyword DB，不生成 snapshot。
- 把问题先归类为“趋势 worker 未在当前本地环境运行 + 当前 DB 无新鲜分行业合格证据 + worker fallback/gate 逻辑需复核”，而不是 UI 展示或 AI 生成质量问题。
- 后续如要运行 `market_timing_worker.py --once`，必须先输出 Live Crawler/Worker Run Plan，因为它可能访问外部站点并写本地 DB/snapshot。

### 5. 运行了哪些命令

- `rg -n "market_timing|market-timing|hot_keywords|scheduler|cron|daily|freshness|..." model docker-compose.yml Dockerfile start_all.sh .codex/handoffs/current-task.md docs .github`
- `find model/data -maxdepth 1 -type f ...`
- `./start_all.sh status`
- `ps aux | rg -i "market_timing_worker|scheduler_a|crawler|xhs|hot_keywords|cron|apscheduler|worker"`
- `sed -n '1080,1365p' model/api.py`
- `sed -n '1,260p' model/hot_keywords.py`
- `sed -n '260,620p' model/hot_keywords.py`
- `sed -n '880,1235p' model/hot_keywords.py`
- `sed -n '1235,1385p' model/hot_keywords.py`
- `sed -n '1,140p' start_all.sh`
- `sed -n '140,260p' start_all.sh`
- `sed -n '36,78p' docker-compose.yml`
- `sed -n '1,130p' model/market_timing_worker.py`
- `sed -n '120,190p' model/xhs_acquisition.py`
- `sed -n '470,530p' model/xhs_acquisition.py`
- `sqlite3 model/data/hot_keywords.db ...`
- `rg -n "market|timing|hot|keyword|scheduler|worker|XHS|fresh" /tmp/noteai_api.log /tmp/noteai_admin.log /tmp/noteai_frontend.log`
- `git status --short`

### 6. 每个命令的结果

- `./start_all.sh status`: 主 API、admin、前端运行中；状态脚本没有趋势 worker 项。
- 进程检查: 未发现 `market_timing_worker`、`scheduler_a`、crawler、cron、apscheduler worker 进程。
- `docker-compose.yml`: 存在 `noteai-trends-worker`，命令为 `python market_timing_worker.py --daemon --interval ...`，但当前本地 `start_all.sh` 不会启动它。
- `hot_keywords.db`: 只有 `analysis_log`、`hot_keywords`、`keyword_snapshots`、`sqlite_sequence`、`user_learn`；未看到 `xhs_crawler_health`/freshness ledger 表，说明当前 DB 未记录 XHS crawler health 分层结果。
- `hot_keywords` 聚合: 10247 条均为 `category=''`、`source='homefeed'`、`quality_score=50`、`evidence_level=weak`；最新采集时间为 `2026-06-24T18:00:56.437782`；`美食` 等核心行业没有分行业样本。
- API 日志: 看到诊断时加载分词/热词模块，但没有趋势 worker 实际采集日志。
- 代码检查: `compute_market_timing()` 在行业无新鲜合格证据时会正确返回 `data_stale/evidence_unavailable`，因此前端显示停用是当前数据状态的真实反馈。
- 代码检查: `market_timing_worker.py` 在 `NOTEAI_XHS_FRESHNESS_REQUIRED` 打开且 XHS freshness 不通过时，会在 `ensure_daily_evidence_pack()` 前抛错；这和文档中“公开采集不足时补 baseline”的目标存在运行顺序风险，需要后续修复。

### 7. 当前仍然失败的问题

- 当前本地手测环境没有自动每日更新市场时机证据。
- 当前 `hot_keywords.db` 无今日 `美食` 行业的合格证据，诊断报告市场时机卡片会继续显示停用。
- `market_timing_snapshot.json` 未在当前 `model/data` 中看到，API 没有可消费的新鲜快照。
- worker 的 XHS freshness gate 和 baseline fallback 顺序存在风险：如果强制 XHS freshness，公开抓取失败可能导致每日行业基线包也无法生成。

### 8. 当前未完成工作

- 尚未修复 `start_all.sh` 对本地趋势 worker 的可选启动/status/stop 管理。
- 尚未运行真实 `market_timing_worker.py --once`。
- 尚未验证 XHS crawler health 分层在当前 DB 中是否能生成有效记录。
- 尚未让诊断报告区分“worker 未运行 / DB 无行业样本 / XHS health 失败 / selector 或 cookie 失败 / snapshot 未同步”。

### 9. 当前最高风险

- 用户手测会误以为市场时机功能已每日自动采集，但当前本地运行态并没有启动独立趋势 worker。
- 若直接运行 worker，可能访问外部站点并写入本地 DB/snapshot；必须先确认运行计划。
- 若未来云端启用强制 XHS freshness，公开抓取不稳定可能让整个市场时机快照生成失败。

### 10. 下一步最小可行计划

1. 修复本地服务管理：给 `start_all.sh` 增加可选趋势 worker 的 start/stop/status，而不是默认偷偷运行。
2. 修复 worker fallback/gate 顺序：即使真实 XHS freshness 失败，也应生成清晰标记的每日行业辅助证据快照，同时记录 XHS health 失败原因；如果产品要求“真实 XHS 才可用于训练”，训练链路仍应读取 health gate。
3. 增加诊断报告/Admin 可观测性：显示 worker 状态、最近一次 worker run、snapshot 时间、XHS health 分层、行业样本量和失败原因。
4. 用户确认 Live Crawler/Worker Run Plan 后，再小样本运行一次 `market_timing_worker.py --once`，验证能否生成今日分行业快照。

### 11. 哪些地方不能在未经确认的情况下修改

- 不运行 `market_timing_worker.py --once/--daemon`、crawler、XHS 外部访问或云端上传。
- 不写生产 DB，不部署云端 worker，不配置生产 secrets。
- 不把 stale/弱证据伪装成真实小红书趋势或官方热搜。
- 不把 XHS health 失败的数据进入训练数据闭环。
- 不修改 billing/payment/quota、auth/admin 权限、生产配置。

## 2026-07-07 Stage Update — 9-image Screenshot OCR UX Gate

### 1. 本轮完成了什么

- 排查用户手测截图上传问题：本地 API 日志显示用户上传 9 张图片后，后端收到 9 次 `/extract-screenshot`，随后收到 1 次 `/validate-ocr`，证明不是只识别图 1，而是前端进度文案写死导致误解。
- 修复截图上传识别 UX：
  - 每张缩略图显示独立状态：等待识别、识别中、已识别、识别失败。
  - 底部进度从固定“识别图1 内容中…”改为 `正在识别图片 x/9 张`。
  - 识别完成后显示合并标题、正文预览、确认提示和图1-图9逐图识别摘要。
  - `开始 AI 诊断` 在截图未上传、识别中、AI 鉴别去重中、任一图片失败、结果尚未合并时均真实禁用；全部成功后才恢复可点击。
  - 401/402/HTTP/空识别结果会落到对应图片失败状态，不再让 UI 无限卡在 pending。

### 2. 修改了哪些文件

- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `NoteAI_Pro_Demo_Framer.html`: 增加截图 OCR 前端状态机、逐图缩略图状态、逐图识别摘要、确认提示和诊断按钮禁用/解锁逻辑。
- `tests/test_frontend_report_static.py`: 增加静态断言，防止截图识别 UX 回退成固定图1文案或只在点击后拦截。
- `.codex/handoffs/current-task.md`: 记录本阶段完成内容、验证结果、剩余风险和下一步计划。

### 4. 做了哪些关键决策

- 不修改后端 OCR/API 合约，因为现有 `/extract-screenshot` 和 `/validate-ocr` 已能支持 9 张图识别与合并。
- 不触发真实 AI：本阶段验证使用 mock `/extract-screenshot` 和 `/validate-ocr`，只验证前端状态机和渲染。
- 按并发识别事实设计 UX：底部展示总体进度，缩略图/摘要展示每张图状态，而不是伪装成严格串行图1、图2、图3。
- 对识别失败采取硬拦截：任一图片失败时按钮保持禁用，符合“必须完整识别后才能诊断”的业务规则。

### 5. 运行了哪些命令

- `tail -n 240 /tmp/noteai_api.log`
- `rg -n "识别图|OCR|ocr|image|screenshot|截图|开始 AI 诊断|开始AI诊断|analyze" ...`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- `git diff --check -- NoteAI_Pro_Demo_Framer.html tests/test_frontend_report_static.py`
- inline JS syntax parse using `node`
- Browser basic smoke against `http://127.0.0.1:5173/NoteAI_Pro_Demo_Framer.html?qa=ocr-ui-fix&page=upload`
- temporary Playwright 9-image OCR UI smoke with mocked `/extract-screenshot` and `/validate-ocr`
- `npm run test:e2e`
- `git status --short`

### 6. 每个命令的结果

- API log check: 用户本次上传后有 9 次 `/extract-screenshot` 200 OK，1 次 `/validate-ocr` 200 OK，随后进入 `/analyze/stream`。
- 静态代码搜索: 定位到原固定文案 `识别图1 内容中…` 和截图 OCR 状态机。
- `tests.test_frontend_report_static`: 12 tests passed。
- diff whitespace check: passed。
- inline JS syntax parse: `inline_scripts_syntax=PASS count=1`。
- Browser basic smoke: 页面可加载，标题正确，按钮初始禁用；Browser DOM snapshot 能力在当前页面报运行时错误，已记录并用 evaluate/screenshot + Playwright 补证。
- Playwright 9-image OCR UI smoke: 初始按钮禁用；上传 9 张 mock 图片后识别中按钮禁用且显示 `识别中 5/9`；完成后按钮恢复为 `开始 AI 诊断（约 30-60 秒）`，逐图摘要 9 条，9 个缩略图均显示已识别；mock 收到 9 次 `/extract-screenshot` 和 1 次 `/validate-ocr`；console 无 error/warn。
- `npm run test:e2e`: 3 tests passed。
- `git status --short`: 本阶段新增修改为 `NoteAI_Pro_Demo_Framer.html`、`tests/test_frontend_report_static.py`、handoff；仍存在此前未确认的 `model/api.py`、`model/model_router.py`、`tools/ai_prelabel_review_batch.py`、`tools/live_ai_smoke.py`、`测试图片/`。

### 7. 当前仍然失败的问题

- 本阶段目标未发现失败。
- Browser 插件的 `domSnapshot()` 在当前页面上报 `incrementalAriaSnapshot` 相关错误；渲染验证已用 Browser screenshot/evaluate 和 Playwright mock upload 补充。

### 8. 当前未完成工作

- 用户需要刷新前端页面后重新手测真实 9 图上传。
- 本阶段尚未 commit/push。
- 未做真实外部 AI OCR 重跑；若用户要验证真实 provider 行为，需要先输出 Live API Run Plan。

### 9. 当前最高风险

- 截图 OCR 是真实外部 AI 成本链路；大量手测 9 图上传会产生多次 OCR 调用和积分/成本消耗。
- 静态单页仍然很大，截图识别状态与全局诊断状态耦合，后续改动要避免破坏手动/视频诊断入口。
- 工作区仍有非本阶段未确认改动，后续 commit 必须继续精确 stage。

### 10. 下一步最小可行计划

1. 用户刷新页面，重新上传 9 张图片手测。
2. 如果真实 OCR 仍有问题，先看 `/tmp/noteai_api.log` 是否 9 次请求都成功，再判断是 provider 识别质量、前端展示、还是积分/登录问题。
3. 若需要真实 AI 复测，先输出 Live API Run Plan，控制样本数量并脱敏结果。
4. 用户确认后，再精确 stage 本阶段 3 个文件并 commit/push。

### 11. 哪些地方不能在未经确认的情况下修改

- 不提交或删除未确认的 Kimi model 行、`model/model_router.py`、AI 预标注工具、live smoke 工具、测试图片目录。
- 不运行 migration、seed、reset、deploy、clean。
- 不修改生产配置、真实凭据、生产 DB、billing/payment/quota、auth/admin 权限。
- 不触发真实支付、邮件、短信、部署或生产写操作。
- 不扩大 live AI 样本、并发调用、批量跑数据或运行 crawler/worker，除非用户明确确认。

## 2026-07-07 Stage Update — Local Market Timing Worker Test Mode

### 1. 本轮完成了什么

- 增加本地趋势 worker 显式测试模式，让用户本地手测也能运行市场时机管道。
- `start_all.sh` 新增：
  - `start --with-trends`
  - `start-full-test`
  - `restart-core`
  - `trends-start`
  - `trends-stop`
  - `trends-status`
- `trends-start` 增加本地安全检查：拒绝 production 环境、拒绝 snapshot upload 配置、拒绝远程 DB 连接配置；本地模式只写 `model/data`。
- 修复 `market_timing_worker.py` 的 fallback/gate 顺序：真实 XHS freshness 不满足时，默认仍生成带 `industry_baseline` 来源标记的每日行业辅助快照；只有显式 `--hard-fail-on-xhs-missing` 或 `NOTEAI_XHS_FRESHNESS_HARD_FAIL=1` 才失败。
- 诊断报告市场时机卡增加管道状态与 XHS health 摘要，避免用户只看到空卡却不知道是 worker、DB、XHS freshness 还是样本质量问题。
- 修复 API 注解层覆盖 baseline 语义的问题：`不代表平台官方热搜` 的说明现在会保留，并追加 freshness 说明。
- 将 `model/data/market_timing_snapshot.json` 加入 `.gitignore`，它是本地运行产物，不进入提交。
- 执行一次受控真实本地 worker smoke：安全模式下关闭 search discovery、只跑 1 轮滚动、最多约 10 个频道页访问，生成今日本地快照。

### 2. 修改了哪些文件

- `.gitignore`
- `start_all.sh`
- `model/market_timing_worker.py`
- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_xhs_acquisition.py`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `.gitignore`: 忽略本地趋势 worker 生成的 `model/data/market_timing_snapshot.json`。
- `start_all.sh`: 增加本地趋势 worker 启停/status/restart-core 和安全检查，支持用户本地真实测试市场时机功能。
- `model/market_timing_worker.py`: 调整 XHS freshness gate 与 baseline fallback 顺序；新增 explicit hard-fail 开关和结果摘要字段。
- `model/api.py`: `MarketTiming` 增加 `pipeline_status`；API 注解层补充 XHS freshness/health 摘要；保留 baseline 来源语义。
- `NoteAI_Pro_Demo_Framer.html`: 市场时机卡展示管道状态、XHS health、worker hint 和更明确的失败/可用状态。
- `tests/test_xhs_acquisition.py`: 更新 worker gate 预期，覆盖默认生成 baseline 快照与显式 hard-fail 两种行为。
- `tests/test_api_contracts.py`: 增加回归测试，确保 API 保留 `industry_baseline` 不代表官方热搜的说明。
- `tests/test_frontend_report_static.py`: 增加静态断言，防止市场时机卡丢失管道状态/XHS health 展示。
- `.codex/handoffs/current-task.md`: 记录本阶段改动、真实 worker smoke 和剩余风险。

### 4. 做了哪些关键决策

- 本地普通 `start` 不偷偷启动趋势 worker；必须显式 `start --with-trends`、`start-full-test` 或 `trends-start`。
- 本地趋势 worker 默认不上传云端 snapshot、不连接远程 DB、不触碰生产配置。
- 真实 XHS freshness 与行业辅助 baseline 分层展示：baseline 可用于让市场时机模块每日可测，但不能伪装成真实 XHS 热搜或训练级证据。
- `restart-core` 保留趋势 worker，只重启 API/admin/frontend，用于代码变更后刷新本地服务而不触发第二次 crawler。

### 5. 运行了哪些命令

- `bash -n start_all.sh`
- `.venv/bin/python -m py_compile model/market_timing_worker.py model/api.py`
- `.venv/bin/python -m unittest tests.test_market_timing_keyword_quality tests.test_xhs_acquisition tests.test_frontend_report_static`
- `./start_all.sh trends-status`
- `./start_all.sh status`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- inline JS syntax parse using `node`
- `npm run test:e2e`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `NOTEAI_XHS_SEARCH_DISCOVERY=0 NOTEAI_XHS_SCROLL_ROUNDS=1 NOTEAI_XHS_CHANNEL_SETTLE_SECONDS=1 NOTEAI_XHS_SCROLL_WAIT_SECONDS=0.2 NOTEAI_MARKET_TIMING_WORKER_INTERVAL_MINUTES=1440 ./start_all.sh trends-start`
- `tail -n 160 /tmp/noteai_trends_worker.log`
- `./start_all.sh restart-core`
- pure local `_compute_market_timing_for_delivery(...)` check for `美食`
- `git check-ignore -v model/data/market_timing_snapshot.json`
- `git diff --check -- ...`
- `git status --short`

### 6. 每个命令的结果

- Shell syntax: passed。
- Python compile: passed。
- Market timing/XHS/frontend static targeted tests: 34 tests passed；后续扩展相关组合 172 tests passed。
- API contracts: 137 tests passed。
- Full unittest discovery: 259 tests passed。
- Inline JS syntax parse: `inline_scripts_syntax=PASS count=1`。
- Playwright e2e: 3 tests passed。
- `trends-status` 初始显示：worker 未运行、快照不存在、核心行业样本为 0。
- Live Crawler/Worker Run Plan 后执行本地 worker smoke：worker 运行中，pid 已记录在状态输出；快照生成于 `2026-07-07T21:18:31`。
- 本轮真实公开页面抓取结果：`scheduler_a` scraped 0 keywords；XHS freshness 各核心行业为 `insufficient`、evidence_count=0。
- Worker fallback 结果：生成 `industry_baseline` 行业辅助证据，快照覆盖 `美食/旅行/穿搭/美妆/家居/健身`。
- 当前本地状态：
  - `美食`: 样本 15，合格 13，强证据 0，来源 `industry_baseline`。
  - `旅行`: 样本 13，合格 13，强证据 0，来源 `industry_baseline`。
  - `穿搭`: 样本 15，合格 15，强证据 0，来源 `industry_baseline`。
  - `美妆`: 样本 16，合格 16，强证据 0，来源 `industry_baseline`。
  - `家居`: 样本 15，合格 15，强证据 0，来源 `industry_baseline`。
  - `健身`: 样本 16，合格 15，强证据 0，来源 `industry_baseline`。
- API 本地计算检查：`data_stale=false`、`evidence_unavailable=false`、`pipeline_state=ready`、`xhs_latest_status=insufficient`；confidence note 保留“当前证据来自每日行业基线包，不代表平台官方热搜”。
- `.gitignore` 检查：`model/data/market_timing_snapshot.json` 已被忽略。
- diff whitespace check: passed。

### 7. 当前仍然失败的问题

- 真实公开 XHS 页面抓取本轮仍为 0 条；当前可用市场时机证据来自 `industry_baseline`，不是真实 XHS 趋势证据。
- XHS freshness/health 记录显示 `scheduler_a` 对核心行业 evidence_count=0、status=`insufficient`；页面访问/selector 没有产生有效证据。
- 当前 worker 可让本地诊断报告不再空白，但还不能证明“每日稳定拿到真实小红书证据”。

### 8. 当前未完成工作

- 继续增强真实 XHS crawler health 分层：需要把 profile cookie、页面访问、selector、risk/login、空结果原因记录得更精确。
- 需要排查 `scheduler_a` 为什么频道页访问后没有提取到关键词：可能是页面结构变化、cookie/state 无效、headless 行为、风控、selector/API pattern 失效或滚动/等待不足。
- 需要进一步验证 sidecar/XHS-Downloader 对真实小红书详情页或搜索页的稳定采集能力。
- 如果要用真实 XHS 数据进入训练闭环，仍必须以 XHS freshness ok 为准，不能用 baseline 代替。

### 9. 当前最高风险

- 产品层面：用户现在能测市场时机模块，但看到的“可用”更多是行业辅助证据，不是平台真实趋势证据；前端已经显示 XHS health 未通过，仍需用户理解分层。
- 工程层面：`scheduler_a` 真实抓取 0 条是下一阶段最高阻塞。
- 运行层面：趋势 worker 目前在本地运行，间隔 1440 分钟；若不再需要，应运行 `./start_all.sh trends-stop` 停止。
- Git 层面：工作区仍有其它未确认改动，后续提交必须精确 stage。

### 10. 下一步最小可行计划

1. 用户刷新页面后重新跑一次诊断报告，确认市场时机卡显示今日行业辅助证据、pipeline 状态和 XHS health。
2. 下一阶段专门排查真实 XHS 抓取 0 条：先看 `scheduler_a` 页面访问与 selector/API 拦截，再评估是否应优先走 XHS-Downloader sidecar。
3. 增加 worker run summary 小文件或 admin 状态卡，让最近一次 worker 结果不用看日志也能定位。
4. 用户确认后精确 stage 本阶段文件；不要把本地 DB/snapshot/runtime 日志提交。

### 11. 哪些地方不能在未经确认的情况下修改

- 不把 `industry_baseline` 当成真实 XHS 热搜或训练级数据。
- 不提交本地 DB、snapshot、cookie/state、日志或测试图片。
- 不修改生产配置、部署、远程 DB、云端 worker、snapshot upload URL 或 secrets。
- 不运行全量 crawler、高频 daemon、并发压测或超过计划范围的外部访问。
- 不修改 billing/payment/quota、auth/admin 权限。

## 2026-07-07 Stage Update - Live Chain Verification and Report Version Sync

### 1. 本轮完成了什么

- 按用户要求，用长期测试账号 `noteai_pro_test` 做了一次受控真实链路测试：
  - AI 内容诊断 `/analyze/stream`
  - 从诊断最佳建议进入 `/chat/start`
  - 对话优化 `/chat/message` 生成结构化 A/B/C 候选
  - 选择候选方案 A，调用 `/chat/select-plan` 保存为同一笔记链 v2
  - 验证笔记库、成长档案、诊断报告三处展示
- 实测数据：
  - 诊断记录：`真实测试｜广州龙虾乌冬冬面要不要冲`
  - 诊断分：`47.9`
  - 诊断建议最佳方案 A：`70.9`
  - 对话候选 A/B/C：`64.0 / 61.4 / 59.4`
  - 实际选择并保存：方案 A，保存为 chat v2，分数 `64.0`
  - 笔记库版本链：`47.9 -> 64.0`
- 发现并修复一个展示一致性问题：
  - 笔记库和成长档案已正确显示 v2=64.0。
  - 诊断报告“本篇成长闭环”原本只显示诊断时最佳建议 `70.9`，没有显示用户实际选择并保存的对话版本 `v2=64.0`。
  - 修复后报告页同时显示：
    - 当前诊断 `47.9`
    - 最佳建议 `方案 A · 70.9`
    - 实际已选版本 `v2 · 64分`
    - 已选对话方案标题
- 重启本地 API/admin/frontend，使浏览器验证命中新代码。
- 本阶段没有修改生产配置、没有运行 migration/seed/reset/deploy、没有触发支付/短信/邮件、没有写生产数据库、没有输出任何 secret 或 token。

### 2. 修改了哪些文件

- `model/api.py`
- `NoteAI_Pro_Demo_Framer.html`
- `tests/test_api_contracts.py`
- `tests/test_frontend_report_static.py`
- `.codex/handoffs/current-task.md`

### 3. 每个文件为什么修改

- `model/api.py`: 新增只读 helper `_build_note_version_group_for_root(...)`，让 `/diagnoses/{diag_id}` 返回该诊断根 note 的版本组 `note_version_group`，用于报告页精准展示后续选中的 chat 版本。
- `NoteAI_Pro_Demo_Framer.html`: 报告页 `renderReportLifecycle(...)` 读取 `note_version_group`，把“版本”卡从泛化的“已进入笔记库”更新为实际 `v2 · 64分 / 已选对话方案：标题`；同时保留异步 fallback，从 `/notes?grouped=true` 补链路。
- `tests/test_api_contracts.py`: 增加后端契约测试，确认诊断根 note 能找到被用户选择保存的 chat v2，并生成正确 `score_trend`。
- `tests/test_frontend_report_static.py`: 增加前端静态断言，防止报告页再次丢失真实版本链展示。
- `.codex/handoffs/current-task.md`: 记录本轮测试、修复、命令结果、风险和下一步。

### 4. 做了哪些关键决策

- 诊断建议分和实际保存版本分必须分开展示：
  - `70.9` 是诊断时的“最佳建议预测/重写方向”。
  - `64.0` 是用户在对话优化里实际选择并保存的版本分。
- `/chat/select-plan` 仍不调用 AI、不扣额外 AI 成本，只保存已有候选；这条语义保持不变。
- 不改 DB schema；利用现有 notes `parent_id` 版本链做只读聚合。
- 报告页不再用“已进入笔记库”这种模糊文案代替实际版本状态。
- 本轮真实 AI 测试只用了一个小样本；后续如要批量质量评估，应另开 Live API Run Plan。

### 5. 运行了哪些命令

- `./start_all.sh status`
- local `/health` check
- local DB session lookup for `noteai_pro_test`（不输出 token）
- Live API script:
  - `POST /analyze/stream`
  - `POST /chat/start`
  - `POST /chat/message`
  - `POST /chat/select-plan`
- API verification script:
  - `GET /notes?grouped=true`
  - `GET /diagnoses/{diag_id}`
  - `GET /diagnoses`
  - `GET /profile/growth`
  - `GET /profile/memories`
  - `GET /profile/achievements`
  - `GET /notes/tracking`
- In-app Browser / Playwright-style rendered checks for:
  - 笔记库
  - 成长档案
  - 诊断报告
- `.venv/bin/python -m py_compile model/api.py`
- `.venv/bin/python -m unittest tests.test_api_contracts.ApiContractTests.test_note_version_group_for_diagnosis_includes_selected_chat_version`
- `.venv/bin/python -m unittest tests.test_frontend_report_static.FrontendReportStaticTests.test_report_library_profile_share_growth_loop_language`
- `.venv/bin/python -m unittest tests.test_api_contracts`
- `.venv/bin/python -m unittest tests.test_frontend_report_static`
- inline JS syntax parse using `node`
- `./start_all.sh stop && ./start_all.sh start && ./start_all.sh status`
- Post-fix API verification for `/diagnoses/{diag_id}`
- Post-fix Browser rendered verification for report/library/profile
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`
- `npm run test:e2e`
- `git diff --check -- model/api.py NoteAI_Pro_Demo_Framer.html tests/test_api_contracts.py tests/test_frontend_report_static.py`
- local `usage_records` query for model/cost summary（不输出 secret/token）
- `git status --short`

### 6. 每个命令的结果

- 初始 `/health`: ok，model=`v0.4-composite`。
- 初始发现本地 API 进程较旧，`/chat/select-plan` 未出现在 OpenAPI；执行本地 stop/start 后已恢复。
- Live API endpoint-level 调用：
  - `/analyze/stream`: success，诊断完成，诊断分 `47.9`，保存 root note。
  - `/chat/start`: success，session 创建，初始当前分 `70.9`。
  - `/chat/message`: success，真实模型返回 3 个结构化候选，分数 `64.0 / 61.4 / 59.4`。
  - `/chat/select-plan`: success，选择方案 A，保存为 note v2，分数 `64.0`。
- usage_records 记录的本轮模型调用摘要：
  - `analyze`: model_names=`claude:claude-haiku-4-5-20251001,claude:claude-sonnet-4-6`，model_calls=`27`，estimated_cost_rmb=`1.45`。
  - `chat_rewrite`: model_names=`claude:claude-sonnet-4-6,claude:claude-haiku-4-5-20251001`，model_calls=`4`，estimated_cost_rmb=`0.63`。
  - `select-plan`: 不调用模型。
- API verification:
  - 笔记库 grouped: found v2，version_count=`2`，score_trend=`[47.9, 64.0]`。
  - 诊断详情 post-fix: `note_version_group.latest.title=广州人均100，龙虾鲍鱼小青龙三合`，latest score=`64.0`，latest version=`2`。
  - 成长档案: latest_score=`64.0`，最近动作包含 `chat_select_plan`。
- Browser rendered verification:
  - 笔记库：显示同一卡片版本链、`47.9 -> 64`、v2、`继续优化`、`追踪效果`。
  - 成长档案：显示最近动作 `chat_select_plan`、曲线末端 `64`、笔记标题。
  - 诊断报告：修复前只显示最佳建议 `70.9`；修复后显示 `v2 · 64分` 和已选对话方案标题。
  - Console: no relevant error/warn。
  - in-app Browser 的 `domSnapshot()` 仍有已知 runtime 限制 `incrementalAriaSnapshot`，已用 Browser evaluate/screenshot 和本地 Playwright-style 断言补足。
- Tests:
  - `py_compile model/api.py`: passed。
  - Targeted API contract: 1 passed。
  - Targeted frontend static: 1 passed。
  - Full API contracts: 142 passed。
  - Frontend static: 14 passed。
  - Inline JS syntax parse: parsed 3 inline scripts。
  - Full unittest discovery: 265 passed。
  - Playwright e2e: 3 passed。
  - `git diff --check`: passed。

### 7. 当前仍然失败的问题

- 本轮修复后，笔记库 / 成长档案 / 诊断报告三处版本链展示没有剩余已知错误。
- 当前最高产品质量发现不是“展示错误”，而是“对话候选分数可能低于诊断建议分”：
  - 诊断建议 A 是 `70.9`。
  - 真实对话候选 A 保存后是 `64.0`。
  - 这是可解释的，因为诊断建议分是候选方向预测，对话候选重新生成后要重新评分；但从用户体验上，需要考虑是否加“低于当前版本/建议分”的选择提醒。
- 本地 `./start_all.sh status` 显示趋势 worker 未运行；趋势快照仍是今日数据。本轮不是 crawler 测试，但这是环境状态风险。

### 8. 当前未完成工作

- 是否要加“选择候选时若低于当前分/诊断建议分，提示用户确认”的 UX guard，需要用户确认。
- 是否要在候选卡上显示“相对诊断建议分”和“相对当前保存版本分”两个 delta，需要产品确认。
- 当前大 diff 仍包含 crawler、market timing、model router、start_all、工具脚本等其它未提交改动，后续 commit 需要精确分组。

### 9. 当前最高风险

- 用户可能误把诊断建议分当成已保存版本分；本轮已在报告页分开展示，但候选卡/对话页仍可以继续优化解释口径。
- 真实 AI 多轮输出质量仍有波动，候选方案分数可能低于上一轮或诊断建议；这是质量策略问题，不是当前版本链保存 bug。
- 本地服务重启会让趋势 worker 停止；如果用户要继续测市场时机每日更新，需要单独启动或使用 `restart-core` 保留 worker。
- 大 diff 仍需 checkpoint scope，不能混提交无关模块。

### 10. 下一步最小可行计划

1. 用户刷新浏览器后，复测当前这条诊断记录：
   - 笔记库：看同一卡片 `v1=47.9 / v2=64.0`。
   - 成长档案：看最近动作和曲线末端 `64`。
   - 诊断报告：看“最佳建议 70.9”和“实际版本 v2 · 64分”是否分开展示。
2. 如果用户认同，再加候选选择保护：
   - 低于当前版本分时显示确认提示。
   - 低于诊断建议分时显示“这是重评分后的实际候选，不是诊断预测分”。
3. 准备下一次 checkpoint 时只 stage 本轮相关文件，避免混入 crawler/market timing 无关改动。

### 11. 哪些地方不能在未经确认的情况下修改

- 不把诊断建议分强行覆盖成已保存版本分。
- 不自动选择最高分以外的方案，不自动替用户保存候选。
- 不修改 billing/payment/quota、auth/session/admin 权限。
- 不运行 migration/seed/reset/deploy/clean。
- 不提交本地 DB、token、cookie、日志、截图、runtime snapshot 或未确认 artifact。
- 不继续扩大真实 AI 调用样本量，除非先给出新的 Live API Run Plan。
