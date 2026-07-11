# NoteAI Render Staging 正式交接

更新时间：2026-07-11（Asia/Shanghai）

本文件是当前阶段唯一 handoff。历史聊天记录不是事实来源；后续会话必须重新核对 Git、Render 和测试状态。

## 1. 项目当前阶段

- NoteAI 已部署到 Render Staging，正在进行功能检测、缺陷修复和回归验证。
- 当前不是正式生产上线阶段；不得把 Staging 通过等同于商业上线完成。
- AI 诊断、爆文生成、对话优化、截图/视频理解、事实源、积分账本和管理端已完成受控的真实 Staging 验证。
- 正式支付订单、回调签名、幂等、退款与对账流程尚未确认，是独立的生产阻断项 `PROD-001`。
- 当前应优先调查 `BUG-002` 自动轮次搜索来源退化，再串行推进后端幂等 `BILL-001`、时延与 stall 治理 `PERF-001`、成本核算和人工 UI 回归；不要重复已经有充分证据的全链路付费小样本验证。

## 2. 当前环境与版本

### 2.1 Git

- 仓库：`iamyusen1314/noteai`
- 当前分支：`codex/quality-stabilization-real-chain`
- 当前业务代码基线：`d58156792d97d0fe625700ec9398d10b305ae7c4`（`fix(frontend): prevent duplicate AI submissions`）。
- Render Staging Web/API/Admin 与两个 Cron build 已对应 `d581567`；新会话仍必须重新核对 Render Events 中的 live commit。
- 远程跟踪分支：`origin/codex/quality-stabilization-real-chain`
- 禁止直接合并 `main`，禁止 force push。

### 2.2 公共 Staging 地址

- 前端：`https://noteai-staging-web.onrender.com`
- API：`https://noteai-staging-api.onrender.com`
- 管理端：`https://noteai-staging-admin.onrender.com`
- API 就绪检查：`https://noteai-staging-api.onrender.com/health/ready`
- 管理端就绪检查：`https://noteai-staging-admin.onrender.com/health/ready`

### 2.3 Render 服务组成

| 资源 | 名称 | 运行方式 | 区域/存储 |
|---|---|---|---|
| Static Site | `noteai-staging-web` | 静态构建 | Global |
| Web Service | `noteai-staging-api` | Docker Starter | Singapore；1GB `/var/data` 持久盘 |
| Web Service | `noteai-staging-admin` | Docker Free | Singapore |
| Cron Job | `noteai-staging-market-timing` | Docker Starter；`5 * * * *` | Singapore |
| Cron Job | `noteai-staging-tracking` | Docker Starter；`20 * * * *` | Singapore |
| PostgreSQL | `noteai-staging-db` | PostgreSQL 18 Free | Singapore；无生产级备份 |

- 私有对象存储：Amazon S3 Singapore；V0.4 模型位于受控 `model/artifacts` 前缀。桶名和凭据不记录在此。
- 视频缓存：API 持久盘 `/var/data/video_frames`，TTL 6 小时；不是永久素材库。
- 用户 API 与管理端健康检查路径均为 `/health/ready`；容器级存活检查为 `/health/live`。
- Redis/消息队列：当前未发现、未部署。

## 3. 当前问题收口结论

### 3.1 根因

此前 Render 市场时机日志出现 `123 homefeed, 0 search_recommend, 0 hot_search`，根因不是“Cron 被重复触发”：

1. 来源日志把 `search_phrase/search_token` 错归为 `homefeed`，统计口径不可信。
2. 仅直接打开搜索 URL，云端不保证触发搜索框联想接口。
3. 趋势接口返回的 `queries`、`ai_words`、`hint_word.search_word` 未被旧解析器识别。
4. 导航会销毁 Playwright execution context，首次输入可能失败，需要等待最终页面并重试。
5. 早期 Cron 还受 512MiB 内存限制影响；低内存浏览器参数已单独修复。

### 3.2 修改文件

- `model/scheduler_a.py`：显式触发搜索输入、导航后重试、解析趋势字段、来源分类和无敏感值诊断指标。
- `model/hot_keywords.py`：降低 Cron 初始化内存。
- `model/xhs_acquisition.py`：新鲜度与会话状态处理。
- `model/market_timing_worker.py`：新鲜证据失败处理。
- `model/admin_server.py`、`model/admin.html`：Cookie 状态、重新登录提醒和管理端展示。
- `render.yaml`：低内存 Cron 参数与 Staging 配置。
- `tests/test_xhs_acquisition.py`、`tests/test_render_deployment.py`：来源解析、导航重试和部署配置回归。

### 3.3 验证方式与结果

- 最终真实 Render Cron：11:48:38 开始，11:59:04 成功退出。
- 来源：460 条，其中 102 `homefeed`、147 `search_result`、91 `search_recommend`、120 `hot_search`。
- Discovery API：recommend 15 responses / 150 items；trending 12 responses / 156 items。
- `search_inputs_typed=2`；其他页面虽无可见输入框，但页面导航已触发推荐/趋势 API。
- 六个核心行业的新鲜度门禁全部通过，Cookie 状态已验证。
- 定向测试 27 passed；业务 commit 上一次全量 unittest 281 passed；两条 GitHub CI 通过。

### 3.4 影响范围与剩余事项

- 影响市场时机采集、来源统计、新鲜度门禁和 Cookie 运维提醒。
- 未修改 AI 质量评分、积分语义、认证、支付或数据库 schema。
- 历史缺陷曾修复并单轮验证，但 13:05、14:05 自动轮次再次出现搜索结果/推荐来源为 0；当前按 `BUG-002` 重新调查，根因确认前不重复修改。

## 4. 已完成工作

“已部署”表示已包含在业务基线 `a8aa0b8` 并在 Render Staging 运行。文档 checkpoint 不改变业务行为。

### 4.1 本地核心质量与全栈修复

| 能力 | 主要文件 | 当前状态 | 验证证据 | 已部署 |
|---|---|---|---|---|
| V0.4 composite 评分与生成链路 | `model/api.py`, `model/model_router.py`, `model/model_registry.json`, `model/artifacts/` | 已接入 | 真实诊断/生成/重写均返回 V0.4 分数；CI artifact check | 是 |
| 多行业创作方向、约束透传 | `NoteAI_Pro_Demo_Framer.html`, `model/api.py` | 已接入 | API contract、frontend static、既有 Playwright 门禁 | 是 |
| 多图 OCR/视觉描述完整门禁 | `NoteAI_Pro_Demo_Framer.html`, `model/api.py` | 已接入 | 9/9 截图真实识别、OCR 合并成功 | 是 |
| 视频抽帧与理解 | `model/api.py` | 已接入 | 9 秒视频抽 9 帧、送 AI 9 帧、诊断成功 | 是 |
| 高德事实源与占位句治理 | `model/fact_enrichment.py`, `model/api.py` | 已接入 | 真实商家返回 10 类事实，4 类占位句命中 0 | 是 |
| 积分扣减、退款与 usage 记录 | `model/billing.py`, `model/db.py`, `model/api.py` | 业务账本通过 | 6+8+3 主链路对账；失败截图 0 扣分 | 是 |

### 4.2 Render 部署工程

| 能力 | 主要文件 | 当前状态 | 验证证据 | 已部署 |
|---|---|---|---|---|
| Blueprint 与服务拆分 | `render.yaml`, `Dockerfile`, `.dockerignore` | 完成 | 六项 Render 资源可用 | 是 |
| 前端运行时 API Base | `runtime-config.js`, `scripts/build_render_frontend.sh`, `NoteAI_Pro_Demo_Framer.html` | 完成 | 前端请求指向 HTTPS Staging API，无 localhost | 是 |
| SQLite/PostgreSQL 双模式 | `model/db.py`, `model/hot_keywords.py` | 完成 | 本地 SQLite 测试；Render readiness 报 PostgreSQL | 是 |
| 版本化 PostgreSQL migration | `model/migrations/postgres/0001_initial.sql` 至 `0004_xhs_freshness.sql`, `scripts/render_predeploy.py` | 完成 | Pre-Deploy 幂等运行；当前无待应用 migration | 是 |
| SQLite 数据迁移工具 | `scripts/migrate_sqlite_to_postgres.py` | 工具完成，未执行正式导入 | 默认 dry-run 和防护逻辑测试 | 是 |
| 管理员持久会话 | `model/admin_auth.py`, `model/admin_server.py`, `model/db.py` | 完成 | 管理端真实登录；会话在 PostgreSQL | 是 |
| Prompt/共享运行配置 | `model/prompt_manager.py`, `model/runtime_settings.py`, `model/db.py`, `model/admin_server.py` | 完成 | 共享表与管理 API 测试；PostgreSQL 就绪 | 是 |
| V0.4 S3 下载与 SHA256 | `model/artifact_loader.py`, `scripts/fetch_model_artifacts.py`, `scripts/docker_entrypoint.sh` | 完成 | Render API 启动及 readiness 为 `v0.4-composite` | 是 |
| 健康检查与优雅退出 | `model/api.py`, `model/admin_server.py`, `scripts/render_start_*.sh`, `Dockerfile` | 完成 | 两个 `/health/ready` HTTP 200 | 是 |
| 视频缓存持久盘 | `model/api.py`, `render.yaml` | 完成 | 视频 9 帧审计成功；1GB 磁盘已挂载 | 是 |
| Cron 拆分 | `scripts/render_run_market_timing.sh`, `scripts/render_run_crawler.sh`, `render.yaml` | 完成 | 市场时机真实成功；tracking 最近轮次成功 | 是 |

### 4.3 云端检测与修复

- Render Blueprint shutdown 配置兼容修复：`4227904`，已部署并验证。
- 512MiB Cron OOM 低内存修复：`991651e`，OOM 已消失。
- XHS freshness、Cookie 状态和重新登录提醒：`35db6a5`，管理端可见。
- 搜索推荐/热搜来源恢复：`0dc0a06`、`a8aa0b8`，真实四来源成功。
- 前端、API、管理端、PostgreSQL、两个 Cron 状态均在 Render Dashboard 核对。

### 4.4 当前真实功能验收

- AI 诊断：HTTP 200，约 214.5 秒，3 标题/3 方案，原文 42.1 分，扣 6 积分。
- 爆文生成：HTTP 200，约 257.2 秒，74.5 分，3 标题变体/4 专家意见，扣 8 积分。
- 对话深度重写：HTTP 200，约 146 秒，74.9 分，SSE 事件完整，扣 3 积分。
- PostgreSQL 对账：上述账号月度积分精确减少 17；诊断、生成、重写 usage 均存在。
- 9 图：9/9 HTTP 200，全部可见图有视觉描述；OCR 合并 HTTP 200，扣 4.5 积分。
- 无效截图：上游失败返回 502，余额不变，usage 标记退款。
- 视频：上传和诊断 HTTP 200，9/9 帧送 AI，71.6 分，扣 6 积分。
- 高德：真实餐饮商家返回地址、商圈、营业时间、价格、评分、关键词、必点等事实；三篇正文均无占位句污染。
- 真实凭据、测试账号密码和 Cookie 均未写入本文件。

## 5. 唯一任务清单

### STG-001 — Render 六服务与基础依赖验收

- 状态：**VERIFIED**
- 问题描述/现象：需确认部署不是只有 Build 绿色，而是服务真实可用。
- 预期结果：Web/API/Admin/DB/Cron 均可用，健康检查与依赖正确。
- 风险级别：High
- 涉及模块：`render.yaml`, Docker/scripts, health endpoints。
- 根因定位：不适用；验收任务。
- 修改状态/进度：部署工程已完成；六资源、CORS、安全头、PostgreSQL、V0.4 均验证。
- 下一步：不重复；每次新部署只做增量 smoke。
- 验收标准：Render live commit 可追溯；API/Admin ready HTTP 200；Cron 最近轮次可解释。
- 真实外部服务：需要 Render；已完成。
- 费用/数据：会产生 Staging 基础费用；不修改生产数据。

### BUG-001 — Market Timing Cron 512MiB OOM

- 状态：**VERIFIED**
- 当前现象：早期 Cron 在 jieba/浏览器初始化后超过 512MiB。
- 预期结果：Starter Cron 在限制内完成。
- 风险级别：High；Render 特有。
- 涉及模块：`model/scheduler_a.py`, `model/hot_keywords.py`, `render.yaml`。
- 根因：已定位，浏览器/分词初始化与并发目标占用过高。
- 修改状态/进度：已使用低内存浏览器、单目标会话、关闭 token discovery、限制 allocator；真实运行不再 OOM。
- 下一步：只监控，不重复调参。
- 验收标准：Cron 正常退出且无 OOM。
- 真实外部服务：需要 Render；已完成。
- 费用/数据：按 Cron 时长计费；写入 Staging 趋势证据。

### BUG-002 — XHS 推荐/热搜来源为 0

- 状态：**INVESTIGATING**
- 当前现象：旧日志显示 0 recommendation / 0 hot search。
- 预期结果：来源统计准确，四类来源非零，六行业门禁通过。
- 风险级别：High；原有逻辑与云端导航差异共同触发。
- 涉及模块：`model/scheduler_a.py`, `model/xhs_acquisition.py`, tests。
- 根因：历史缺陷根因已定位，见第 3 节；当前连续自动轮次回退的根因尚未确认。
- 修改状态/进度：历史修复曾真实验证 460 条四来源；2026-07-11 自动轮次 13:05、14:05、15:05 连续退化为 `search_result=0`、`search_recommend=0`。QA 已确认“Cron 为何仍成功”：响应解析异常被静默吞掉、单目标失败按 best-effort 继续，worker hard gate 使用同日累计 freshness；但“搜索页面/端点为何突然不产出”仍因日志不足而未确认。
- 下一步：先实施 `BUG-002B` 脱敏诊断 instrumentation，部署后只观察连续 2–3 个自动轮次，再根据页面类别、响应/JSON/schema 与过滤漏斗证据确定具体修复；根因确认前不盲改 selector、不手工触发 Cron。
- 验收标准：至少连续 2–3 个自动轮次中 `search_result` 与 `search_recommend` 均满足已确认的健康阈值，且健康状态不再被当天累计旧证据掩盖。
- 真实外部服务：需要授权 XHS 会话；已完成。
- 费用/数据：Cron 时长费用；写入 Staging 数据。

### BUG-002B — 搜索来源退化的脱敏诊断漏斗

- 状态：**VERIFIED**
- 优先级：Critical（当前最高优先级调查包）。
- 问题描述：当前仅有最终来源数、推荐/趋势响应数和输入成功/失败数；JSON 解析异常被静默忽略，无法区分导航、页面类别、端点未出现、JSON/schema 变化、候选过滤或去重。
- 证据：12:05 搜索来源正常；13:05/14:05/15:05 连续 `typed=0/fail=12`、推荐响应 0，且 13:05/15:05 无导航错误。静态与 mock 已排除空 seed、数据库落库和部署版本作为单一原因，并确认路径变体可能被 broad matcher 命中却绕过推荐专用分支。
- 根因是否确认：诊断缺口根因已确认；外部搜索退化的最终根因尚未确认。
- 涉及文件：`model/scheduler_a.py`, `model/market_timing_worker.py`, `model/xhs_acquisition.py`, `tests/test_xhs_acquisition.py`；不改 selector、重试、Cron 调度、hard gate、Cookie、数据库 schema 或业务数据语义。
- 风险：日志过细可能泄漏平台/用户数据；只允许计数、状态类枚举和固定错误码，禁止 URL/query、seed、Cookie、响应正文、标题、关键词、DOM 或异常全文。
- 执行代理：Repository Explorer（单一 Implementation Agent）；验证代理：Test Finder（独立 Verification Agent）。
- 修改状态/进度：最小 instrumentation 已实施、本地独立复验并部署到 Render Staging。手工轮次 `96ef24f8-…` 12/12 搜索目标闭合：navigation ok=12、challenge=12、input failed=12、search response 393/json failed 109/title 0、recommend response 0；日志只含计数/枚举/固定错误码，未出现 URL/query/Cookie/正文/标题/关键词/evidence_keys。该任务的“可诊断”目标已闭环；恢复搜索来源由 `BUG-002C` 继续。
- 验收标准：每轮搜索目标计数闭合；缺输入框、导航失败、响应未观察、非 JSON、空 schema、路径变体、全部过滤/去重与正常成功均有确定计数/错误码；来源为 0 时至少有一个可验证原因码；日志和 health details 不含敏感/原始内容；既有 Cron 成功/门禁语义不变。
- 是否需要用户决定：否；2026-07-11 用户已明确批准 Staging 部署、手工触发采集及真实外部调用。
- 是否涉及真实外部调用：是；获批后可手工触发 1 次 Staging 采集并继续观察 2–3 个自动轮次。
- 是否已部署到 Render：是；commit `46ed3db`，手工 Staging 轮次已验证。

### BUG-002A — 最新单轮来源健康与失败分类

- 状态：**VERIFIED**
- 问题描述：当前 API readiness 和六行业 freshness 使用最新采集时间与同日累计证据，可能在最新轮次 `search_result=0`、`search_recommend=0` 时继续显示绿色。
- 预期结果：最新单轮来源健康与同日累计 freshness 分开呈现；缺少搜索结果/推荐时明确标记 degraded 和无敏感值错误码，不误报 Cookie 失效。
- 风险级别：High；属于可观测性与运维判断修复，不改变市场时机业务门禁。
- 涉及模块：`model/xhs_acquisition.py`, `model/api.py`, `model/admin.html`, `tests/test_xhs_acquisition.py` 及相关静态/合同测试。
- 根因：已确认；`freshness_status()` 合并同日历史 evidence keys，API readiness 只看数据库最新采集时间，未检查最新 run 的来源多样性。
- 修改状态/进度：最小修复已实施。使用现有 `xhs_crawler_health.details_json` 归一化最新 run 来源分布，API readiness 与管理端新增非阻断来源退化状态，并增加成功→退化、兼容旧记录、字段白名单与管理端文案回归。独立验证：定向 175/175、全量 288/288、Production Readiness 48/48、Compose、Python 编译和 diff check 全部通过。
- 执行代理：Repository Explorer（单一 Implementation Agent）；验证代理：Test Finder（独立 Verification Agent）。
- 涉及文件：`model/xhs_acquisition.py`, `model/api.py`, `model/admin.html`, `tests/test_xhs_acquisition.py`, `tests/test_api_contracts.py`, `tests/test_render_deployment.py`。
- 下一步：本包无需继续修改；API readiness 已在线显示累计 `ok=true`、最新轮次 `degraded/latest_run_search_sources_missing`、`blocking_readiness=false`，管理端文案已区分累计与最新一轮。
- 验收标准：同日成功轮次后出现退化轮次时，累计 freshness 可保持原语义，但 `latest_run_source_health.ok=false`、状态为 degraded、错误码可区分缺少结果/推荐；Cookie 不被标记失效；API readiness 仍向后兼容且不阻断；管理端明确显示本轮来源退化。
- 真实外部服务：不需要；全部使用临时 SQLite 和 mock rows 验证，不触发 Cron。
- 费用/数据：无外部费用，不写远程数据，不新增 schema/migration。
- 是否需要用户决定：否；2026-07-11 用户已明确批准本轮提交、推送、Render Staging 部署、付费 Smoke、真实 AI 和手工采集。
- 是否涉及真实外部调用：是；部署后执行受控付费 AI Smoke 和一次手工采集。
- 是否已部署到 Render：是；commit `46ed3db`，Web/API/Admin 与 Cron build 已验证。

### QA-001 — 真实 AI 主链路与积分对账

- 状态：**VERIFIED**
- 问题描述：需验证真实 Claude/Kimi、多 Agent、V0.4 和账本不是 mock。
- 预期结果：诊断/生成/对话均成功，输出完整，扣分与 PostgreSQL 一致。
- 风险级别：Critical（商业计费相关）。
- 涉及模块：API、billing、PostgreSQL、V0.4、外部 AI。
- 根因定位：不适用；验收任务。
- 修改状态/进度：最小真实样本通过，合计扣 17 积分。
- 下一步：真实成本由 `FIN-001` 继续。
- 验收标准：HTTP/SSE 成功、输出结构完整、usage 与余额一致。
- 真实外部服务：已调用 Claude/Kimi。
- 费用/数据：产生少量 AI 费用；只写 Staging 测试数据。

### QA-002 — 多图、视频、事实源与失败退款

- 状态：**VERIFIED**
- 当前现象：需确认所有上传图都识别、视频帧完整、事实句自然、失败不扣分。
- 预期结果：9/9 识别、9/9 视频帧、真实高德事实、失败退款。
- 风险级别：High。
- 涉及模块：上传/OCR/视频、Moonshot、高德、billing。
- 根因定位：不适用；验收任务。
- 修改状态/进度：后端真实链路全部通过。
- 下一步：UI 文件选择仍由 `QA-003` 人工回归。
- 验收标准：审计计数与上传数一致，占位句 0，失败余额不变。
- 真实外部服务：已调用 Moonshot/Amap。
- 费用/数据：产生少量 API 费用；写 Staging 测试数据。

### OPS-001 — XHS Cookie/session 持续有效性

- 状态：**INVESTIGATING**
- 问题描述：授权 Cookie 会过期或被平台判失效。
- 当前现象：最近真实轮次为 verified；未来会自然过期。
- 预期结果：管理端及时显示 `needs_attention`/`needs_relogin`，更新后手工 Cron 恢复。
- 风险级别：High；外部平台固有风险。
- 涉及模块：crawler admin、runtime settings、market timing Cron。
- 根因：已定位为授权会话生命周期，不是一次性代码缺陷。
- 修改状态/进度：提醒机制已部署；持续监控不可“永久完成”。
- 下一步：每次 Cron 失败先查管理端 Cookie 状态，再决定是否重新登录。
- 验收标准：提醒不泄露 Cookie；更新后四来源和 freshness 恢复。
- 真实外部服务：需要 XHS 授权账号。
- 费用/数据：手工 Cron 产生少量费用；会写 Staging 趋势证据。

### FIN-001 — 配置并验证真实模型 Token 成本

- 状态：**BLOCKED**
- 问题描述：`actual_model_cost_rmb=0`，当前 `cost_rmb` 是操作级固定估算。
- 当前现象：Token 数已记录，但 Render 未配置 Claude/Kimi 单价与汇率变量。
- 预期结果：诊断/生成/对话的真实 Token 成本大于 0，前后台汇总一致，可用于毛利分析。
- 风险级别：Critical；原有商业配置缺口。
- 涉及模块：`model/billing.py`, `model/.env.example`, Render API env, admin usage。
- 根因：已确认；Render 缺少价格变量，不是 Token 计数缺失。
- 修改状态/进度：代码支持变量；尚未由产品负责人确认生效价格/汇率，未填 Render，未重跑。
- 下一步：只读代理先核对启用模型与计价单位；主 CTO 给出变量名/公式/最小验证计划；用户确认价格和真实调用费用后再配置。
- 验收标准：三个最小操作均有 `actual_model_cost_rmb > 0`；汇率、Token、操作成本、后台汇总可复算；积分语义不变。
- 真实外部服务：需要一次最小真实 AI 验证。
- 费用/数据：会产生少量 AI 费用并写 Staging usage；执行前必须说明。

### UX-001 — 云端时延与“30–60秒”承诺不一致

- 状态：**VERIFIED**
- 问题描述：真实诊断约 193–228 秒、生成约 257 秒、重写约 146 秒。
- 当前现象：修复前诊断展示“约30–60秒”、生成展示“约30–40秒”，且生成入口缺少函数级单请求锁和按钮禁用；UX-001A 已部署到 Render Staging 并通过独立无付费 Smoke Test。
- 预期结果：本修复包 UX-001A 先移除未经验证的固定耗时承诺，并保证诊断/生成请求期间只能提交一次；阶段耗时、stall timeout 和 P50/P95 另立性能包，不混入本次修改。
- 风险级别：High；Staging 揭示的体验问题。
- 涉及模块：静态前端、API 多 Agent/评分/二修流程。
- 根因：固定文案与真实 Staging 耗时不符；`startGeneration()` 未检查 `_genStreamActive`，生成按钮也未绑定可恢复的禁用状态。根因已确认。
- 修改状态/进度：UX-001A 已完成实施、本地独立验证、GitHub CI、Render 部署和 Staging 独立验证。移除固定秒数承诺；生成/诊断入口增加单请求 guard；生成按钮增加 busy/disabled/ARIA 状态并在统一 `finally` 恢复；新增静态与 Playwright 回归。独立验证结果为 frontend static 15/15、Playwright 4/4、全量 unittest 282/282、production readiness 48/48、Compose 与 diff check 通过；线上 mock 连续调用各入口两次均只有一个请求，按钮状态正确恢复，真实 AI 调用为 0。
- 下一步：本修复包无需继续修改；阶段耗时、stall timeout、真实 P50/P95 和后端 request-id 幂等应作为独立任务推进。
- 验收标准：不再显示“30–40秒/30–60秒”；连续点击诊断或生成分别只产生一个请求；成功、401、402、异常和流结束后按钮恢复；既有 payload、截图门禁和质量行为不回退。
- 真实外部服务：已部署 Render Staging；线上 Smoke 使用 route mock，未调用真实 AI。
- 费用/数据：产生正常 GitHub/Render 构建与部署活动；未产生 AI 费用、未写业务数据、未手工触发 Cron。

### BILL-001 — 后端 request-id 幂等与防重复扣费

- 状态：**VERIFIED**
- 优先级：Critical。
- 问题描述：浏览器端已阻止重复点击，但 API 尚未确认具备跨进程、并发重试和网络重放级别的幂等保护；同一付费请求可能重复扣积分、创建多个 usage row 或重复调用模型。
- 预期结果：同一用户、同一操作、同一幂等键只允许一个执行和一次扣费；相同键不同 payload 明确拒绝；不同用户之间严格隔离；失败、超时和重试语义可审计。
- 风险级别：Critical；涉及计费、并发、数据隔离和潜在数据库 schema。
- 涉及模块：`model/api.py`, `model/billing.py`, `model/db.py`, `model/migrations/postgres/`, 前端请求头和相关 tests。
- 根因：已确认。付费入口没有持久化幂等记录；`check_and_deduct()` 的余额读取、扣减、usage 与退款由多个独立连接/事务完成，现有 DB 抽象不能保证并发 claim、扣费和最多一次退款原子性；浏览器单请求锁无法覆盖多标签、代理重放、网络重试和跨进程并发。
- 证据：Repository Explorer 已核对 Analyze/Generate/Chat 扣费链；Security Reviewer 确认重复执行、并发余额竞争和 SSE 断连账务闭环为 Critical；Render/DevOps Reviewer 进一步确认必须新增 transaction API 与增量 migration，不能用内存锁或仅用 SQLite 测试替代。
- 修改状态/进度：第一阶段兼容实现完成。新增仅存哈希和固定账务标记的 `idempotency_requests` 空表；SQLite/PostgreSQL 显式事务将 claim、扣费和主 usage 原子化，AI 在事务外，complete/refund 使用 owner-only 短事务且最多一次；Analyze/Generate JSON+SSE、付费 Chat 和前端 `X-Request-ID` 已接入，无 header 与免费 Chat 保持旧语义。独立安全审查曾发现跨月/升级错退，已改为绑定原 subscription/period 并统一 user-first 锁；真实 PG 首轮又发现 FK KeyShare→FOR UPDATE 死锁，改为任何 claim INSERT 前先锁用户行且未用 retry 掩盖。重建全新 PostgreSQL 18 后 migration 二次、同键20并发、不同键争抢余额、退款20并发、升级/claim并发 5/5 通过。最终全量 unittest 343/343（默认跳过5条需双开关PG用例）、Playwright 7/7、独立定向207、py_compile、Compose、diff check 均通过。
- 执行代理：Repository Explorer（单一 Implementation Agent）；验证代理：Test Finder + Security/Concurrency Reviewer（独立只读，最终 PASS）。
- 下一步：按已批准的两阶段兼容发布，第一阶段仅新增 `idempotency_requests` 增量表、SQLite/PostgreSQL transaction API、原子 claim/扣费/最多一次退款，并覆盖 Analyze、Generate、付费 Chat；完整 SSE 回放、结果恢复、stale 自动接管和 exactly-once 业务副作用明确延后。
- 验收标准：两个并发相同请求只能执行一次、扣费一次、产生一个主 usage；同键同 payload 可安全重试并得到稳定幂等状态/错误码且不重复产生副作用；同键不同 payload 返回冲突；跨用户不可互相命中；失败/退款后按明确规则返回；SQLite/PostgreSQL 均通过。本阶段不要求透明回放原始 SSE/AI 结果，不宣称断线自动恢复、stale lease 自动接管或任意崩溃点 exactly-once。
- 真实外部服务：用户已批准一次性 PostgreSQL 并发测试、Render Staging migration、付费 Smoke 和真实 AI；仍按最小样本执行。
- 费用/数据：方案新增一张空表和索引，无 backfill；一次性 PostgreSQL 使用本机全新临时容器和合成数据，测试后已删除并停止 Colima。尚未修改 Staging 数据库或调用真实 AI。
- 是否需要用户决定：否；2026-07-11 用户已批准 schema/migration、计费事务重构、一次性 PostgreSQL 并发测试、Staging migration、付费 Smoke 和真实 AI；采用推荐的两阶段兼容发布。
- 是否涉及真实外部调用：是；独立验证通过后可应用 Render Staging migration，并执行受控写入型 Smoke。
- 是否已部署到 Render：是；commit `cfbd132`。Pre-deploy 只应用 `0005_idempotency_requests.sql`；API/Admin ready。真实 Analyze 首次 200、同键重放 409；合成账户管理端仅 1 次操作、约 ¥1.45 模型成本、无第二 usage。独立 Security/Concurrency 云端复验结论 PASS/VERIFIED。

### PERF-001 — 阶段耗时、SSE stall timeout 与 P50/P95

- 状态：**INVESTIGATING**
- 问题描述：当前只有进度阶段和零散模型调用日志，没有统一阶段耗时、总耗时或可复算的 P50/P95；前端对 SSE 静默/断流缺少明确 stall timeout，用户可能无限等待。
- 预期结果：诊断/生成主要阶段有单调递增时间戳和耗时；SSE 静默达到安全阈值后给出可恢复错误，按钮与任务状态一致；离线工具可从受控样本计算 P50/P95，且不伪造样本量。
- 风险级别：High；错误 timeout 可能中断仍在运行的付费任务，过度日志可能泄露内容或增加存储成本。
- 涉及模块：`model/api.py`, `model/model_router.py`, `NoteAI_Pro_Demo_Framer.html`, usage/日志与相关 tests。
- 根因：部分确认；`_emit_progress()` 未附带阶段时间，外部模型只记录零散 elapsed 日志，前端没有统一 SSE stall 计时器。实际各阶段瓶颈占比尚未确认。
- 修改状态/进度：`PERF-001A` 已完成统一 timing envelope、保守 stall 告警和离线统计基础；父任务仍保留真实 P50/P95 与原子终态可靠性。BUG-003 独立验证新增边界：notes 已提交但 chat session 持久化失败时正式版本不丢，然而服务重启后的对话上下文可能落后一轮；若连接恰在流式草稿与 `canonical_response` 之间断开，页面可能暂时保留草稿。该问题应与结果恢复/终态协议统一治理，不在 BUG-003 中扩大修改。
- 下一步：QA Investigator 定义 stall、断流和恢复的最小失败用例；Explorer 核对事件链和 provider timeout；Test Finder 确定协议兼容与统计测试；真实 P50/P95 样本数量和费用在执行前单独批准。
- 验收标准：所有主要事件包含可验证的总耗时/阶段耗时且保持向后兼容；mock SSE 静默和断流能恢复 UI、不重复扣费；统计工具对固定样本准确输出 P50/P95；真实指标只在样本量、费用和数据范围获批后发布。
- 真实外部服务：本地 mock 不需要；真实 P50/P95 需要受控 Claude/Kimi 样本并会产生费用。
- 费用/数据：当前调查无费用、不写远程数据；真实采样前必须说明样本数、预计费用和 Staging usage 影响。

### OPS-001 — 长请求期间 Render health check 瞬时超时重启

- 状态：**INVESTIGATING**
- 优先级：High。
- 问题描述：Render API Events 已从一次偶发升级为稳定小时级 health timeout：18:09、19:10、20:09、21:10、22:09 均出现 5 秒健康检查超时，随后约 1 分钟内自动恢复。
- 证据：五次失败时间都紧邻 Market Timing `5 * * * *` 小时任务窗口；22:33 BUG-003 真实付费 Chat 完成后未出现新重启，因此“长 AI 请求本身”不是充分解释。未见 migration failure 或应用 Traceback。
- 根因是否确认：否；与小时 Cron 存在强时间相关，但市场 Cron 是独立服务，仍需核对 PostgreSQL 锁/连接、共享资源、readiness DB 查询和 Render 实例指标，不能把相关性直接当因果。
- 涉及文件：待调查 `model/api.py` 长任务执行边界、Render health check/资源配置和运行指标；本任务不先改 timeout。
- 风险：成功请求后实例重启会中断其他并发请求；若频繁发生，会降低 Staging/生产可用性。
- 执行代理：待指定 Render/DevOps Reviewer + QA Investigator；验证代理：独立 Verification Agent。
- 验收标准：至少连续 3 个小时任务窗口与受控长请求期间 readiness 均持续成功，或确认并修复可复现的共享依赖阻塞；不得仅靠放宽健康标准掩盖数据库/事件循环问题。
- 是否需要用户决定：若需升级 Render 资源或产生持续费用，则需要；只读调查与本地复现不需要。
- 是否涉及真实外部调用：调查 Render 指标需要只读云端访问；额外付费 AI 样本需沿用已批准的小样本范围并单独计数。
- 是否已部署到 Render：不适用；当前为运行时风险。

### OPS-001A — Market Cron 趋势计算 N+1 PostgreSQL 连接

- 状态：**READY_TO_VERIFY**
- 优先级：High。
- 问题描述：Market Cron 在结果构建阶段对每个候选关键词逐个调用 `compute_trend_dir()`，每次都新建/关闭 PostgreSQL 连接；五个 18:09–22:09/10 API health timeout 与该阶段 5/5 重合。
- 证据：18–22 点 Cron 均 05:02 启动、约 10:28–10:46 才输出 Scraped，API 在 09/10 分超时并紧邻该阶段结束恢复；代码路径 `scheduler_a.scrape_once()`→`compute_trend_dir()`→`hot_keywords._db_conn()` 已确认 N+1。最终 homefeed 结果每轮 101–121，过滤前理论上最多 10×300 个候选；22:09:48–49 PostgreSQL 日志两秒内至少 12 次授权连接，无 ERROR/FATAL/死锁。
- 根因是否确认：是；N+1 连接风暴已确认。它与 readiness 多连接共同造成 timeout 的因果置信度约 85%，但本包只消除已确认的 Cron 放大器，以自然轮次验证因果。
- 涉及文件：`model/hot_keywords.py`, `model/scheduler_a.py`, `tests/test_market_timing_keyword_quality.py` 及必要的采集回归；不改 API readiness、schema、Cron 时间、Cookie、selector 或资源规格。
- 风险：批量查询若改变最近四次快照的排序/去重，会改变趋势方向和最终排序；必须保持 SQLite/PostgreSQL 兼容并限制 SQL 参数规模。
- 执行代理：单一 Repository Explorer；验证代理：独立 QA/Test Finder。
- 修改状态/进度：最小实施与本地独立验证已完成。新增批量趋势方向查询，800 参数分块、窗口函数每关键词仅取最近4条、所有分块共享同一连接；单关键词函数保持兼容并委托批量实现；Scheduler 在候选循环前一次去重预计算。首个失败证据为批量 API/SQL 构造器不存在的3项 ERROR及 Scheduler 预计算 0!=1。独立验证：SQLite 边界与3000词连接预算通过；全新 PostgreSQL 18 以15,000条快照/3,000词真实执行，结果与独立逐词算法全量一致，3000词1连接/4 SELECT、100词1连接/1 SELECT；market+XHS+Render+API 209/209、全量 unittest 359/359（5 skip）、Production Readiness 48/48、py_compile/Compose/diff check 全部通过。临时 PG 容器和本轮 Colima 已清理；无本地代码阻断，但必须部署后连续观察2–3个自然小时窗口才能标记 VERIFIED。
- 验收标准：批量结果与旧算法逐词结果一致；100–3000 个候选仅使用常数级连接（目标 1 个，允许同一连接内分批 SQL）；采集来源/数量/排序语义不回退；本地全量通过；部署后连续 2–3 个自然 `:05–:12` 窗口 API 无 health timeout 且 Cron 成功。
- 是否需要用户决定：否；不改变产品行为或付费资源。
- 是否涉及真实外部调用：本地实施不需要；最终只观察自然 Cron，不手工追加采集。
- 是否已部署到 Render：否。

### OPS-001B — Render readiness 轻量化与有限 DB 超时

- 状态：**TODO**
- 优先级：High。
- 问题描述：`/health/ready` 将 Market Timing 标为 nonblocking，但仍同步建立约 11 个 PostgreSQL 连接并执行约 14 条查询；单连接延迟约 520ms 时，本地 PostgreSQL 路径 Mock 可把 readiness 拖到 5.251 秒。
- 证据：`api._readiness_payload()`、`hot_keywords.db_status()`、六行业 `freshness_status()`、access/cooldown/latest health 串行调用链已核对；Admin 的轻量 readiness 未出现同类小时级失败。
- 根因是否确认：是；readiness 自身是连接/延迟放大器，但先等待 OPS-001A 自然窗口以隔离因果，再串行实施。
- 涉及文件：待限定 `model/api.py`, `model/db.py`, Market Timing 观测缓存与 tests；不删除真实 blocking 检查，不仅改 Render timeout。
- 风险：过度轻量化可能把数据库或模型真实故障误报为 ready；必须保留单次 DB ping、模型加载和 AI 配置检查，并维持公开响应兼容或明确缓存时间。
- 执行代理：待指定；验证代理：独立 QA/DevOps。
- 验收标准：受控 DB 延迟下 readiness <2 秒且绝不超过5秒；市场观测变慢只能返回缓存/unknown；DB 连接/查询失败有限时间内返回 503；不弱化真实 readiness。
- 是否需要用户决定：若要升级资源需要；代码轻量化不需要。
- 是否涉及真实外部调用：本地 Mock/临时 PostgreSQL；部署后只读观察。
- 是否已部署到 Render：否。

### PERF-001A — SSE 阶段计时、慢响应保护与可复算统计基础

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：诊断、生成、对话 SSE 缺少统一的事件序号、总耗时、阶段耗时和明确终态；诊断/生成无 stall 保护，对话现有 stall 会直接取消 reader 并提示重试，可能诱导付费任务重复执行；当前也没有可复算 P50/P95 的安全记录格式。
- 证据：QA 只读调查确认 Analyze/Generate 缺少连接、首事件与事件间 stall guard；Chat 只有 fetch 后 30/90/180 秒 reader cancel，缺少 connect timeout 与结构化终态；`_emit_progress()` 未附带 timing；真实 Staging 样本曾达到约 146–257 秒，不能用激进硬超时中断任务。
- 根因是否确认：是；协议缺少统一 timing/terminal envelope，客户端把“暂时静默”和“任务失败”混为一体。
- 涉及文件：`model/api.py`, `NoteAI_Pro_Demo_Framer.html`, `tools/sse_latency_report.py`, `tests/test_sse_latency_report.py`, `tests/e2e/sse-stall-guard.spec.js`, `tests/test_api_contracts.py`, `tests/test_frontend_report_static.py`；不修改 billing、数据库、provider timeout 或模型编排。
- 风险：High；若将 stall 当成失败或自动重试，可能重复扣费。修复必须只告警并保持单请求锁，不宣称后台已取消。
- 执行代理：Repository Explorer（单一 Implementation Agent）；验证代理：Test Finder（独立 Verification Agent）。
- 修改状态/进度：已完成最小实施与本地独立验证。服务端在三条 SSE 出口增加 `sse.v1` timing envelope；前端以 30/60/120 秒保守阈值只告警、不取消、不重试、不提前解锁；无终态 EOF 明确判错；离线工具仅接受白名单脱敏维度，异质 overall 不标为可靠 SLA，同质组少于 100 样本不标 P95 可靠。独立验证：PERF 定向 165/165、全量 unittest 294/294、Playwright 7/7、Production Readiness 48/48、Compose、相关 py_compile 和 LFS-safe diff check 全部通过；未调用真实付费服务。
- 验收标准：Analyze/Generate/Chat 事件向后兼容且带安全的 `trace_id/seq/server_ts/elapsed_ms/stage_elapsed_ms/terminal/outcome`；连接、首事件或事件间静默时只显示“仍可能处理中、不要重复提交”，不自动重试、不提前解锁；无终态 EOF 明确报错并恢复 UI；固定样本能准确计算 P50/P95并披露样本量；日志/指标不含正文、Prompt、reasoning、Token、Cookie 或原始幂等键。
- 是否需要用户决定：受控 Staging Smoke 与真实 AI 已获批准；大规模可靠 P95（每同质组至少 100 个样本）仍需另定样本预算，不能由本次最小 Smoke 推定。
- 是否涉及真实外部调用：是；本轮最多各 1 次诊断、生成和付费对话，用于功能/计时 Smoke，不宣称统计可靠性。
- 是否已部署到 Render：是；commit `46ed3db`。真实诊断、生成、付费对话各 1 次均完成，无重复请求、无错误 stall、UI 正常恢复；合计准确扣 17 积分。该最小 Smoke 不能代表可靠 P50/P95。

### BUG-002C — XHS 搜索访问挑战的安全恢复策略

- 状态：**READY_TO_VERIFY**
- 优先级：Critical。
- 问题描述：最新手工轮次 12 个搜索目标全部进入 challenge 页面，导致搜索输入、标题和推荐来源归零；首页/热搜仍工作。
- 证据：navigation 12/12 成功、final page challenge 12/12、input 0/12、recommend endpoint 0、search title 0；session configured 且 auth cookie 未过期。已排除空 seed、普通导航失败、数据库去重和 Cookie 完全失效为单一原因。
- 根因是否确认：是；搜索链路受到访问挑战/反自动化退化。最小安全方案为 challenge 感知的单轮熔断、6 小时跨轮次冷却与半开探针，禁止绕过 CAPTCHA 或平台安全控制。
- 涉及文件：`model/scheduler_a.py`, `model/market_timing_worker.py`, `model/xhs_acquisition.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`, `render.yaml`, `tests/test_xhs_acquisition.py`, `tests/test_api_contracts.py`, `tests/test_render_deployment.py`；不改 selector、Cookie、UA/viewport 或验证码处理。
- 风险：继续高频搜索会增加 Cron 成本并加重挑战；激进指纹规避可能违反平台安全边界。
- 执行代理：Repository Explorer（单一 Implementation Agent）；验证代理：独立 QA/Render Reviewer。
- 修改状态/进度：最小修复已实施并通过第二轮独立验证。首轮验证发现 `/admin/xhs/health` 删除既有 `error_summary/details` 且可能清空安全错误码；修正为保留旧字段结构、固定摘要映射和严格 details 白名单。最终证据：相关 194/194、全量 unittest 311/311、前端静态 16/16、Python 编译、Compose 和 diff check 均通过；HTTP 200 challenge 首目标熔断、homefeed 保留、冷却零搜索浏览器、6 小时边界、半开探针和默认兼容均通过。commit `878787b` 已部署。18:05 自然轮次 `b281661a-…` 验证 cooldown 零搜索启动并保留 homefeed/hot_search；21:10 `46863376-…` 与 22:10 `e9ef2b10-…` 又连续明确报告 degraded，后者 homefeed=49、hot_search=72、search_result=0、search_recommend=0。最新单轮未被累计 freshness 伪装成绿色，但搜索来源仍未恢复，任务继续保持 READY_TO_VERIFY，不手工追加采集。
- 验收标准：不绕过安全控制；挑战出现时及时停止/退避并给出稳定状态；若采用安全恢复策略，至少连续 2–3 个自然轮次恢复 search/recommend 健康阈值，否则明确降级而不浪费全轮成本。
- 是否需要用户决定：技术默认采用 Staging 6 小时冷却、Cron 继续成功但明确 degraded；不自动重新登录、不减少长期行业覆盖。如后续要改 hard fail 或每行业 seed 数再单独决策。
- 是否涉及真实外部调用：最终验证需要自然 Cron；不再手工连续触发。
- 是否已部署到 Render：是；commit `878787b`。云端服务健康，尚待自然 Cron 功能结果。

### SEC-002 — 保留可解释 Agent 思考体验并隔离原始 reasoning

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：产品必须保留“AI Agents 为什么这样做”的可解释过程；当前实现却把供应商原始 thinking/reasoning 逐字展示并在 Chat 长期持久化，无法区分可交付决策说明与内部中间草稿。
- 证据：2026-07-11 Staging 真实生成与重写均可见完整 reasoning；未在消息中复制敏感值。
- 根因是否确认：是；Claude `thinking_delta` 和 Kimi `reasoning_content` 被 Router 原样转成 SSE，Generate/Chat 前端完整展示；Chat 还将 `reasoning_content` 写入 `chat_sessions.messages_json` 并在加载时恢复。未发现跨用户读取或应用主动写日志，但浏览器、网络和数据库暴露已确认。
- 涉及文件：`model/api.py`, `NoteAI_Pro_Demo_Framer.html`, Chat session/notes persistence 与 tests。
- 风险：泄露内部 prompt/推理、扩大 Prompt Injection 影响、保存不必要敏感内容；若只隐藏内容又会破坏产品的可信、可解释体验。
- 执行代理：Security Reviewer + Repository/UX Explorer（只读调查）及单一 Repository Explorer（实施）；验证代理：独立 Security/QA Verification Agent。
- 修改状态/进度：已以最小兼容方案完成。模型仍可内部推理，但 Generate/Chat 的公开 SSE 只转发最终正文与 `process.v1` 白名单结构化解释；旧 `thinking_*` 事件在前端被丢弃；Chat 不再累积或持久化 `reasoning_content`；只有最终候选、修复、评分和保存结果确定后才发出对应解释，保存失败不宣称“已保存”。本地独立验证：SEC/API/frontend static 169/169、全量 unittest 348/348（5 skip）、Playwright 8/8、py_compile/diff check 通过；provider sentinel 未进入 SSE、DOM、HTML、浏览器存储、内存 session、数据库或 stderr。Render Staging 独立只读复核通过：API/Admin readiness HTTP 200，线上 Web 含安全解释与两处旧 reasoning 丢弃保护，不含“完整展示”承诺。
- 验收标准：页面继续实时展示各 Agent 的观察、依据、分歧、取舍、决定和最终修改原因；任何 provider `thinking_delta/reasoning_content` 原文、系统 Prompt、中间草稿或敏感哨兵不进入 SSE、DOM、session、数据库或日志；数据库只保留安全结构化决策说明；最终说明必须与实际保存/展示的最终版本一致，Claude/Kimi fallback 不回退。
- 是否需要用户决定：否；2026-07-11 产品负责人明确要求保留可解释 Agent 思考体验，同时控制原始 reasoning 泄露与长期持久化。历史 Staging 原始 reasoning 清理仍单独执行：先只统计受影响行数，不读取内容，再制定可回滚脱敏方案。
- 是否涉及真实外部调用：调查与 mock 不需要。
- 是否已部署到 Render：是；commit `7c52b6f`。Web/API/Admin 均完成部署，API 日志确认 `migrations_applied=0`、启动完成并连续 readiness 200；本轮未调用真实 AI、未新增付费或业务数据。历史 Staging reasoning 未批量清理，只会在记录被读取并重新持久化时净化；模型 HTML/raw 暴露继续由 `SEC-003` 独立处理。

### SEC-003 — 模型输出 HTML 注入与诊断 raw 字段暴露

- 状态：**INVESTIGATING**
- 优先级：High。
- 问题描述：Generate 报告和 Chat Markdown 存在将模型自由文本写入 `innerHTML` 的路径；Analyze/Generate 响应与持久化还包含专家 `raw`/原始 XML，扩大模型输出注入和不必要数据暴露面。
- 证据：Security Reviewer 定位 `NoteAI_Pro_Demo_Framer.html` 的 Generate expert report、`addBubble`、`chatMD` 路径，以及 `model/api.py` 的 `_normalize_expert_opinion`、saved diagnosis serialization 与 Chat generate context。
- 根因是否确认：部分确认；未转义模型文本进入 HTML 的危险路径已确认，所有可利用上下文与现有 CSP/浏览器行为仍需独立复现。
- 涉及文件：`model/api.py`, `NoteAI_Pro_Demo_Framer.html`, Analyze/Generate persistence 与安全 tests。
- 风险：High；模型输出或 Prompt Injection 内容可能影响页面结构或执行事件属性，并在诊断历史中长期保留 raw 文本。
- 执行代理：Security Reviewer + QA Investigator（只读）；验证代理：独立 Security/Browser Verification。
- 验收标准：任意 `<script>`、`<img onerror>`、事件属性和未知 HTML 只能作为文本显示；公开/持久化专家对象不含 raw XML；正常报告和 Chat 格式不回退。
- 是否需要用户决定：否；属于安全修复，不改变产品功能。
- 是否涉及真实外部调用：本地 sentinel 与浏览器测试不需要；最终 Staging 仅需无付费 Smoke。
- 是否已部署到 Render：否。

### BUG-003 — 对话重写回复与保存版本不一致

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：用户要求删除未经提供的具体时长和效果断言；AI 最终回复声称已删除，但保存的第 2 版仍包含“20分钟、吃不出柴感、半小时”等内容，且评分从 75.3 降至 74.1。
- 证据：2026-07-11 Staging 单次真实 `chat_rewrite` 可稳定观察到回复文本与“当前笔记第2版”不一致；扣费 3 积分正常。
- 根因是否确认：是；聊天气泡先展示未后处理的模型原始回复，而保存版本随后经过 shape/repair/二修形成另一份对象；无独立 `fact_context` 时旧正文还被当作事实来源，可能把本轮要求删除的表达重新引入；保存前没有本轮删除约束的确定性验证，notes 写入异常也会被静默吞掉。前端字段错配、parser 回退和整版分数回退已排除；75.3→74.1 属于现有最多下降 2 分政策允许范围，不在本包改变评分策略。
- 涉及文件：`model/api.py`, Chat generator/parser、notes version persistence、前端事件处理与 tests。
- 风险：用户以为约束已执行但实际发布稿未变，属于交付正确性缺陷。
- 执行代理：Repository Explorer + QA Investigator（只读调查），单一 Repository Explorer（实施）；验证代理：独立 QA Verification Agent。
- 修改状态/进度：2026-07-11 三方只读复核后完成最小实施。Chat 新增本轮删除约束、事实源过滤、所有后处理后的最终约束检查与 `canonical_response`；只有 notes 保存成功后才更新 session、发送 `note_update` 和成功说明，失败时保留上一版；前端以安全 DOM/textContent 替换冲突草稿气泡。首轮独立验证发现历史 session 把实际 DB v5 错报为 v1、通用删除时长误伤明确保留的已确认 `30分钟` 两个阻断；修正后由同一独立代理重放通过。最终独立证据：BUG-003/SEC-002/Chat/付费幂等定向 22/22、全量 unittest 355/355（5 skip）、Playwright 10/10、Production Readiness 48/48、py_compile 与 diff check 全部通过；成功路径 canonical/note_update/notes INSERT/session 字段一致，约束、质量、无 `<note>` 和 notes INSERT 失败均不创建或宣称新版本。未修改 billing/idempotency、schema/migration、模型路由、多候选语义或评分政策；未调用真实 AI。
- 验收标准：最终回复、当前笔记和持久化版本使用同一正文；禁止项不再出现；评分与版本号一致；只扣一次。
- 是否需要用户决定：否。
- 是否涉及真实外部调用：是；本地 mock 不需要，最终只执行 1 次已批准的 Staging 真实重写。
- 是否已部署到 Render：是；commit `c4a51e2`，Push/PR 两条 CI 均通过，Web/API/Admin Deployed，Pre-Deploy `migrations_applied=0`。真实 Smoke 仅 1 次：问题笔记 v2→v3，标题不变，最终气泡、右侧当前笔记和刷新后的笔记库正文/评分/版本一致，`20分钟`、`吃不出柴感`、`半小时` 均从正式正文消失；评分 74.1→72.1（恰为现有允许下降 2 分边界），余额 867→864，管理端 `chat_rewrite` 总次数 1→2，证明只新增一次扣费/usage。未触发新的 Render 重启。

### QA-003 — 人工 UI 上传与关键页面回归

- 状态：**TODO**
- 问题描述：自动化浏览器安全策略不允许选择本机文件，后端链路通过但 UI 文件选择未完成本轮人工验收。
- 当前现象：尚缺人工 9 图上传、视频上传、余额不足弹窗、用户/用量管理页回归。
- 预期结果：真实浏览器操作与后端结果一致，无装饰性控件和状态错位。
- 风险级别：Medium；验证缺口，尚未确认产品缺陷。
- 涉及模块：`NoteAI_Pro_Demo_Framer.html`, `model/admin.html`, API。
- 根因：自动化环境限制已确认；产品是否有缺陷未知。
- 修改状态/进度：未开始代码修改；已有后端与既有 e2e 证据。
- 下一步：用户或可控人工浏览器执行清单，发现缺陷再单独复现。
- 验收标准：9 图全部完成状态后可提交；视频进度正确；余额不足不发起付费操作；管理端账本一致。
- 真实外部服务：UI 主链路会调用真实 AI。
- 费用/数据：会产生少量费用和 Staging 测试数据；先说明样本数量。

### PROD-001 — 正式支付订单/回调/对账

- 状态：**DEFERRED**
- 问题描述：尚未确认真实支付网关的下单、回调签名、幂等、退款与日对账闭环。
- 当前现象：套餐/积分业务逻辑存在，但不能证明已收到真实款项。
- 预期结果：支付与积分发放强一致，可审计、可退款、可对账。
- 风险级别：Critical；仅生产商业上线需要。
- 涉及模块：payment、billing、auth、database、admin。
- 根因：产品/支付接入尚未实施或尚未确认。
- 修改状态/进度：未开始；禁止在 Staging 验收中顺手接入。
- 下一步：单独做支付架构、合规和供应商方案，用户批准后实施。
- 验收标准：签名验证、幂等、金额校验、退款、异常补单、对账、审计测试全部通过。
- 真实外部服务：需要支付沙箱，生产切换另行批准。
- 费用/数据：可能产生支付/沙箱费用；严禁真实扣款测试未授权用户。

### PROD-002 — 生产数据库、备份、域名与恢复演练

- 状态：**DEFERRED**
- 问题描述：Render Free PostgreSQL 无备份且 30 天到期；当前域名均为 Staging。
- 当前现象：适合测试，不符合商业生产可恢复性。
- 预期结果：付费 PostgreSQL、备份/PITR、监控、域名/TLS、恢复演练完成。
- 风险级别：Critical；Render 环境限制。
- 涉及模块：Render DB/Web、DNS、migration、runbook。
- 根因：当前明确采用测试规格。
- 修改状态/进度：未开始，不能自动升级或迁移。
- 下一步：容量与 RPO/RTO 评估后由用户确认付费资源。
- 验收标准：备份可恢复、迁移可回滚、域名/CORS/回调地址正确、故障演练通过。
- 真实外部服务：需要 Render/DNS。
- 费用/数据：持续付费并涉及真实数据迁移，必须单独批准。

### PROD-003 — 视频缓存横向扩展与零停机

- 状态：**DEFERRED**
- 问题描述：API 挂载单实例磁盘，Render 挂盘服务不能无缝横向扩容/零停机。
- 当前现象：Staging 单实例满足短期测试。
- 预期结果：生产按真实流量决定对象存储/任务队列或保持单实例的可接受方案。
- 风险级别：Medium；仅高并发生产明显。
- 涉及模块：视频上传/缓存、部署拓扑。
- 根因：当前最小成本架构选择。
- 修改状态/进度：未开始，暂不扩架构。
- 下一步：有真实容量数据后评估。
- 验收标准：缓存可恢复、并发和重启行为可预测、成本明确。
- 真实外部服务：可能需要对象存储/队列。
- 费用/数据：可能新增持续费用；必须批准。

## 6. 已知问题与风险

### Critical

- **原有/商业上线**：`FIN-001` 真实模型成本未配置，毛利核算不能使用当前固定估算。
- **原有/商业上线**：`PROD-001` 正式支付闭环未确认。
- **生产环境**：`PROD-002` Free PostgreSQL 无备份且会到期，不能承载正式用户数据。
- **长期安全**：任何 Secret/Cookie 泄露到 Git 或日志都会造成账号与费用风险；当前 tracked files 检查未发现 `.env` 或 XHS session 文件。

### High

- **Staging 暴露**：`UX-001` 真实时延明显高于 UI 承诺。
- **持续运维**：`OPS-001` XHS Cookie 可能自然失效；提醒机制已部署但仍需人工更新。
- **原有结构**：前端手工 payload 与后端 Pydantic 模型可能漂移；行为修改需 contract/e2e 双验证。
- **权限**：用户 auth 与 admin auth 均能影响积分/配置，任何修改都必须负向权限测试。

### Medium

- **验证缺口**：`QA-003` 本轮未完成真实浏览器文件选择回归；尚未复现产品故障。
- **Render 特有**：管理端 Free 服务可能冷启动；不等同于 API 故障。
- **架构选择**：`PROD-003` 视频缓存依赖单实例盘，部署有短暂中断。
- **模型质量**：通过 V0.4 分数不自动代表自然度长期稳定，仍需持续 golden/人工抽检。

### Low

- 无独立 lint/typecheck script；当前依赖 py_compile、unit、static/e2e 和 CI gate。
- 本机缺少 Git LFS filter 时三份 `.lgb` 会显示 modified；这是工作树表现，不是业务改动。不得 stage、revert 或重新生成这些文件，先安装/恢复 Git LFS 环境再处理。

## 7. 测试基线

### 7.1 本轮实际重新运行或真实执行

- 本地全量 unittest：281 passed（约 2 秒）。测试日志中的网络/坏模型报错来自预期的异常路径用例，最终结果为 OK。
- Production readiness gate：PASS，48 checks，0 failed。
- Docker Compose 配置：`docker compose config --quiet` 通过。
- V0.4 artifact check：4 个 artifact 均有效，0 missing/invalid，未触发下载或修复。
- Render Dashboard：六资源状态、分支和 live business commit 已核对。
- API `/health/ready`：HTTP 200，PostgreSQL、V0.4、Claude、Moonshot、market timing ready。
- Admin `/health/ready`：HTTP 200，PostgreSQL/admin credentials ready。
- 前端：HTTP 200，运行时 API Base、HSTS、nosniff、Referrer/Permissions Policy 已核对。
- CORS：Staging Web 到 API 预检通过。
- Market Timing Cron：真实四来源 460 条，六行业 freshness pass，成功退出。
- 外部 AI：诊断、生成、对话重写真实成功并完成积分对账。
- 媒体/事实源：9 图、OCR、失败退款、9 帧视频、高德商家真实通过。
- 文档 checkpoint 阶段的本地命令结果写在本文件“Checkpoint 记录”中。

### 7.2 以前运行过，未在文档 checkpoint 中重复

- XHS 定向测试：27 passed。
- GitHub Actions：`a8aa0b8` 两条 CI 检查通过；包含 py_compile、artifact check、全量 unittest、quality gate、production readiness gate、Docker Compose config。
- Playwright/e2e：既有内容意图与约束链路门禁通过；本轮未重新跑文件选择。
- SQLite 模式：通过既有单元与本地开发测试。
- PostgreSQL 模式：Render API/Admin/Cron 真实运行及 migration/readiness 通过。
- Docker build/API container：Render build 与容器启动通过；本轮未重复本地构建。

### 7.3 尚未运行或需要条件

- 人工 UI 9 图/视频/余额不足/管理端回归：`QA-003`。
- 真实模型价格验证：`FIN-001`，需产品确认价格并允许最小 AI 费用。
- P50/P95 性能剖析：`UX-001`，需真实 AI 调用。
- 正式支付沙箱：`PROD-001`，尚未接入。
- 生产备份恢复：`PROD-002`，尚无生产资源。

### 7.4 有副作用的命令

- `scripts/render_predeploy.py`、SQLite `--apply` 导入、管理员/积分调整、真实 AI、Crawler/Cron、模型训练/发布、任何 deploy/rollback 都需要明确批准。
- `python scripts/migrate_sqlite_to_postgres.py` 默认 dry-run；只有 `--apply` 写数据库。

## 8. 严格安全边界

后续主会话和所有 Subagents 必须遵守：

- 不读取、输出或提交 Secret、Token、密码、Cookie、私钥或完整连接字符串。
- 不在聊天、日志、Handoff 和 commit 中记录真实凭据。
- 不修改生产资源，不创建或删除生产 Render/AWS/PostgreSQL/S3 资源。
- 不连接正式支付，不执行真实扣款。
- 不执行破坏性数据库操作，不清库、truncate、drop 或覆盖远程数据。
- 不删除任何 Render、AWS、PostgreSQL、S3 或其他远程资源。
- 不启动未经批准的付费 AI、大规模爬虫或批量任务。
- 不修改 billing、payment、quota、auth、admin 和数据库业务语义，除非任务明确要求且用户批准。
- 不为了测试通过而删除测试、降低断言、吞掉异常或关闭安全/质量门禁。
- 不进行无关重构，不覆盖用户已有修改。
- 不 force push，不直接合并 `main`/`master`。
- 所有外部真实调用前必须给出执行计划、预计费用、数据影响和范围。
- 三份本机 Git LFS 假修改 `.lgb` 禁止加入任何提交。

## 9. 推荐 Subagent 分工

### 只读角色

- **Repository Explorer**：核对代码结构、变量引用和调用链，不写文件。
- **QA Investigator**：设计/执行最小测试、复现缺陷，不改断言。
- **Render/DevOps Reviewer**：核对 Render 配置、live commit、日志、资源规格和费用，不修改云资源。
- **Security Reviewer**：检查权限、Secret、输入边界和泄露风险，不读取真实 Secret 值。
- **Test Finder**：定位现有测试与最小回归范围，不新增依赖。

### 写入角色

- **Implementation Agent**：只有主 CTO 批准一个具体、最小修复包后才能改代码。
- **Verification Agent**：独立于 Implementation Agent，不能直接采信其自测结论；按验收标准复核。

### 并行/串行规则

- Repository Explorer、Test Finder、Security Reviewer 可并行只读。
- Render Reviewer 与 QA Investigator 可并行，但真实外部调用必须由主 CTO 统一限额，不能重复产生费用。
- 根因和修复范围确认后，Implementation Agent 必须串行执行。
- Implementation 完成后，Verification Agent 再串行独立验证。
- billing/auth/database/payment 任务不允许多个写代理并行修改。

## 10. 下一会话启动步骤

1. 读取 `AGENTS.md`、本文件、`.codex/notes/architecture-summary.md`、`.codex/notes/risk-register.md`、`docs/RENDER_DEPLOYMENT_GUIDE.md`。
2. 运行 LFS-safe Git status，核对 branch、HEAD、upstream、staged/unstaged/untracked；确认三份 `.lgb` 未被 stage。
3. 在 Render 只读核对 API/Web/Admin live commit、两个 `/health/ready` 和 Market Timing 最近成功轮次；不得假设文档 checkpoint 已部署。
4. 当前最高优先级是 `FIN-001`。先派 Repository Explorer、Test Finder、Security Reviewer 只读核对价格变量、启用模型和账本公式。
5. `STG-001`、`BUG-001`、`BUG-002`、`QA-001`、`QA-002` 已完成，禁止重复大范围修改或重复付费验证。
6. 主 CTO 汇总只读证据，给出最小变量配置与一次诊断/生成/重写验证的费用和数据影响；获得用户确认后，才允许 Implementation Agent 或 Render 配置操作。
7. 完成 `FIN-001` 后按 `UX-001`、`QA-003` 顺序推进；生产事项必须另行批准。
8. 当前工作的停止条件：Handoff checkpoint 已提交并推送；CI/Render 版本可追溯；无业务文件或敏感文件被误提交；向用户输出 10 项交接摘要后停止开发。

## 11. Do Not Touch Without Approval

- `model/billing.py` 及套餐/积分/退款语义。
- `model/auth.py`、`model/admin_auth.py`、权限依赖与管理员接口。
- `model/db.py`、`model/migrations/postgres/`、任何数据库写迁移。
- `render.yaml` 中付费规格、数据库、磁盘、Secret 与生产域名。
- S3 IAM、对象删除/覆盖、模型 manifest/registry 与发布产物。
- XHS Cookie 值、授权账号和大规模采集参数。
- 支付、生产环境、生产数据、DNS 和回调地址。

## 12. Checkpoint 记录

- 接管前 handoff 以业务 commit `a8aa0b8` 为事实基线；当前业务与 Render Staging 基线已更新为 `d581567`。
- 历史交接提交主题为 `docs(handoff): checkpoint Render staging validation`，对应 `807016e`。
- 本地工作树中的三份 `.lgb` 是缺少 Git LFS filter 的表现，未纳入交接提交。
- 历史文档阶段本地回归：281 unittest passed；production gate 48/48；Compose config passed；4/4 V0.4 artifacts valid。
- 历史文档阶段的本机公开健康地址超时已被当前证据取代：`d581567` 部署后 API/Admin readiness 均为 HTTP 200。
- 历史交接提交只包含 `AGENTS.md`、本文件、`.codex/notes/risk-register.md`、`docs/RENDER_DEPLOYMENT_GUIDE.md`；当前 UX-001A 的业务提交与文件范围见下方记录。
- `checksPass` 已将 `d581567` 自动部署到 Render Staging；当前业务代码不再停留于 `a8aa0b8`。

### 2026-07-11 UX-001A 本地修复包

- 状态：`VERIFIED`；业务 commit `d58156792d97d0fe625700ec9398d10b305ae7c4` 已部署 Render Staging。
- 修改文件：`NoteAI_Pro_Demo_Framer.html`、`tests/e2e/content-intent.spec.js`、`tests/test_frontend_report_static.py`；本文件由主 CTO 更新任务证据。
- 修改范围：诚实时延文案、诊断/生成单请求 guard、生成按钮 busy/disabled/ARIA 状态、对应静态和 Playwright 回归；未修改 API、billing、模型、数据库、积分或质量门禁。
- Implementation Agent 自测：frontend static 15/15、Playwright 4/4、diff check 通过。
- 独立 Verification Agent：frontend static 15/15、Playwright 4/4、全量 unittest 282/282、production readiness 48/48、Docker Compose config 和 LFS-safe diff check 通过。
- GitHub：push 与 PR 两条 CI 均通过；远端完成 LFS 拉取、模型校验、全量 unittest、质量门禁、production readiness 和 Compose config。
- Render：Web 14:57 live；两个 Cron 14:58 build succeeded；API 15:00 live；Admin 15:00 live；API/Admin `migrations_applied=0`；最终 Web/API/Admin Deployed、PostgreSQL Available。
- Staging 独立验证：新文案存在、旧固定秒数文案不存在；生成/诊断连续调用各两次均只有一个 mock 请求；busy/disabled/ARIA 进入与恢复正确；API/Admin readiness HTTP 200；真实 AI 调用 0，未写业务数据、未触发 Cron。
- 剩余风险：当前是浏览器端防重复提交，后端仍没有 request-id 幂等；401/402/异常分支由统一 `finally` 与代码审查覆盖，尚未分别增加浏览器级分支用例。
- 下一步：UX-001A 不再修改；按优先级继续 `BUG-002` 只读根因调查，再推进阶段耗时/stall timeout、`FIN-001` 和 `QA-003`。
