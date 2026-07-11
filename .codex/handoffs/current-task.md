# NoteAI Render Staging 正式交接

更新时间：2026-07-11（Asia/Shanghai）

本文件是当前阶段唯一 handoff。历史聊天记录不是事实来源；后续会话必须重新核对 Git、Render 和测试状态。

## 1. 项目当前阶段

- NoteAI 已部署到 Render Staging，正在进行功能检测、缺陷修复和回归验证。
- 当前不是正式生产上线阶段；不得把 Staging 通过等同于商业上线完成。
- AI 诊断、爆文生成、对话优化、截图/视频理解、事实源、积分账本和管理端已完成受控的真实 Staging 验证。
- 正式支付订单、回调签名、幂等、退款与对账流程尚未确认，是独立的生产阻断项 `PROD-001`。
- 当前应继续完成成本核算、时延体验和人工 UI 回归；不要重复已经通过的市场时机来源修复或全链路小样本验证。

## 2. 当前环境与版本

### 2.1 Git

- 仓库：`iamyusen1314/noteai`
- 当前分支：`codex/quality-stabilization-real-chain`
- 当前业务代码基线：`a8aa0b81b4b46c7e689324ecbb92cf4d632ebf0b`（`retry XHS search discovery after redirects`）
- Render Staging 在本 handoff 编写时对应上述业务 commit；交接 checkpoint commit 只更新文档，推送后 Render 可能自动构建该文档 commit。新会话必须重新核对 Render Events 中的 live commit。
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
- 该缺陷已修复并验证，不应重复开发；Cookie 过期仍是持续运维事项 `OPS-001`。

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

- 状态：**已验证**
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

- 状态：**已验证**
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

- 状态：**已验证**
- 当前现象：旧日志显示 0 recommendation / 0 hot search。
- 预期结果：来源统计准确，四类来源非零，六行业门禁通过。
- 风险级别：High；原有逻辑与云端导航差异共同触发。
- 涉及模块：`model/scheduler_a.py`, `model/xhs_acquisition.py`, tests。
- 根因：已定位，见第 3 节。
- 修改状态/进度：已修改并真实验证 460 条四来源。
- 下一步：不重复开发；纳入 `OPS-001` 监控。
- 验收标准：成功退出、四来源非零、六行业 freshness pass。
- 真实外部服务：需要授权 XHS 会话；已完成。
- 费用/数据：Cron 时长费用；写入 Staging 数据。

### QA-001 — 真实 AI 主链路与积分对账

- 状态：**已验证**
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

- 状态：**已验证**
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

- 状态：**进行中（运维）**
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

- 状态：**未完成；已定位根因；未开始业务修改**
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

- 状态：**未完成；已复现；未开始修改**
- 问题描述：真实诊断约 193–228 秒、生成约 257 秒、重写约 146 秒。
- 当前现象：页面仍展示“约30–60秒”，可能误导并诱发重复提交。
- 预期结果：先让文案、进度、超时和重复提交保护符合真实时延；性能优化不得牺牲质量。
- 风险级别：High；Staging 揭示的体验问题。
- 涉及模块：静态前端、API 多 Agent/评分/二修流程。
- 根因：端到端多 Agent 和质量修复耗时已观测；各阶段占比尚未完整剖析。
- 修改状态/进度：已量化，未改。
- 下一步：QA 只读采集阶段耗时；产品确认体验文案；性能改动另立小修复包。
- 验收标准：不再虚假承诺；重复提交被阻止；质量和 60 分门禁不下降；P50/P95 有记录。
- 真实外部服务：性能验收需要真实 AI。
- 费用/数据：会产生 AI 费用；执行前必须说明。

### QA-003 — 人工 UI 上传与关键页面回归

- 状态：**未完成**
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

- 状态：**正式上线前事项；未完成**
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

- 状态：**正式上线前事项；未完成**
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

- 状态：**暂缓；生产前评估**
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

- 本 handoff 以业务 commit `a8aa0b8` 为事实基线。
- 交接提交使用主题 `docs(handoff): checkpoint Render staging validation`；其 SHA 由新会话通过 `git log -1` 获取，避免在 commit 内记录自引用哈希。
- 本地工作树中的三份 `.lgb` 是缺少 Git LFS filter 的表现，未纳入交接提交。
- 文档阶段本地回归：281 unittest passed；production gate 48/48；Compose config passed；4/4 V0.4 artifacts valid。
- 文档阶段从本机再次访问公开健康地址时网络连接超时；未据此判定云端故障，因为同一阶段 Render Dashboard 为 Deployed 且此前 readiness HTTP 200。推送后必须从 Render Events/Logs 或可用浏览器重新核对。
- 交接提交只应包含：`AGENTS.md`、本文件、`.codex/notes/risk-register.md`、`docs/RENDER_DEPLOYMENT_GUIDE.md`。
- 推送后应等待 GitHub CI；Render Staging 可能因 `checksPass` 自动部署文档 commit，业务代码仍与 `a8aa0b8` 相同。
