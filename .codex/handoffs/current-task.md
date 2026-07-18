# NoteAI 商业上线唯一任务账本

更新时间：2026-07-18（Asia/Shanghai）

本文件是当前阶段唯一 handoff。历史聊天记录不是事实来源；后续会话必须重新核对 Git、Render 和测试状态。

## 1. 项目当前阶段

- NoteAI 已从“Render Staging 稳定化”正式转入“商业生产上线准备”阶段；Staging 继续作为验证环境，不得把 Staging 通过等同于商业上线完成。
- 已确认目标生产拓扑：阿里云华南运行完整生产主系统；Render Singapore 最终只运行最小 Claude Gateway。
- 已确认支付方向：Adapay 作为 V1 聚合支付供应商，目标覆盖支付宝、微信和银联；正式接入仍取决于 NoteAI AI SaaS/积分业务准入与网页三通道能力的书面确认。
- Render Singapore Staging 仍保留全栈验证环境；远程 Claude Gateway 已完成 Staging 多实例安全化。阿里云生产基础设施已进入实施期，但生产应用、ALB/TLS、业务 DNS 与 Adapay 正式支付账本仍未闭环。
- AI 诊断、爆文生成、对话优化、截图/视频理解、事实源、积分账本和管理端已完成受控的真实 Staging 验证。
- 正式支付订单、回调签名、幂等、退款与对账流程尚未实施，是生产阻断项 `PROD-001`。
- `BILL-001`、`FIN-001`、`SEC-005`、`PERF-001B` 与 `QA-003A/B/C/D/E` 已闭环；`BUG-002` 曾由连续自然健康轮次完成验证，但 2026-07-13 最新自然轮次再次退化，已按新证据从 VERIFIED 降回 INVESTIGATING。生产事项不再延期，按本账本商业上线依赖顺序推进。

## 2. 当前环境与版本

### 2.1 Git

- 仓库：`iamyusen1314/noteai`
- 当前分支：`codex/quality-stabilization-real-chain`
- 当前本地发布候选 HEAD：`0ccf3f6`，其直接前序提交为 `199bf5f`；当前分支为 `codex/quality-stabilization-real-chain`。`199bf5f` 包含 CAP-001A1/A2A 的持久 operation/admission 实现，`0ccf3f6` 包含 BUG-002G 的服务端强制注销识别与合规停采实现。两包均已提交，但本账本要求提交后由独立验证代理复核 exact diff、回归与部署边界后才可标记 VERIFIED。
- Render Staging Gateway 已自动部署 `c0afbbe`：Render Events 于 2026-07-13 23:36（Asia/Shanghai）显示 deploy live；公开 `/health/ready` 为 HTTP 200，并返回 `claude-gateway.v2`、`ready_multi_instance`、`shared_control_plane` 与 `dynamodb_shared_atomic`。当前仍为1实例、1 worker，主API仍为Local transport，不能外推为正式切流或2–4实例已验证。
- 远程跟踪分支：`origin/codex/quality-stabilization-real-chain`
- 禁止直接合并 `main`，禁止 force push。

### 2.2 阿里云生产实际状态（2026-07-18）

- 已采购并运行：华南1生产 VPC/C、F 双可用区网络，两台私网 API ECS，RDS PostgreSQL 16 高可用实例，Tair 2 GiB 高可用实例，以及 VPC 级 SNAT/公网出站；节点不以公网 IP 对外提供业务入口。
- 生产 RDS 已在空库中原子应用 PostgreSQL migration `0001`—`0008`：30张 `public` 表、8条 migration 记录、缺失版本0；未导入 Staging 数据，关键业务表保持0行，未运行 Prompt 基线写入，也未删除任何数据。
- `noteaipro.cn` 企业 DNS 已购买并绑定；根域、API、Admin 三张独立 Rapid DV 证书均已签发，但尚未绑定到 ALB。
- 尚未完成：ACR 私有镜像与不可变摘要、生产应用部署、ALB/健康后端、证书绑定、业务 DNS 切流、Admin 入口保护、生产前端落点、备份/PITR恢复演练。
- 容量边界：100个同时AI任务仍未达到。Tair虽已运行，但尚未接入应用；CAP-001A2B、公开202入口、独立Worker、可恢复payload/result与退款/对账尚未完成，不能以两台ECS或供应商配额代替端到端容量证据。
- 当前High风险：ALB健康不能依赖Claude Gateway，否则跨境链路故障会摘除整个站点；XHS Cookie仍有明文持久化风险，Admin日志缺少第二层脱敏；视频缓存仍为节点本地非HA；PostgreSQL尚无已验证连接池与恢复演练。

### 2.3 公共 Staging 地址

- 前端：`https://noteai-staging-web.onrender.com`
- API：`https://noteai-staging-api.onrender.com`
- 管理端：`https://noteai-staging-admin.onrender.com`
- API 就绪检查：`https://noteai-staging-api.onrender.com/health/ready`
- 管理端就绪检查：`https://noteai-staging-admin.onrender.com/health/ready`

### 2.4 Render 服务组成

| 资源 | 名称 | 运行方式 | 区域/存储 |
|---|---|---|---|
| Static Site | `noteai-staging-web` | 静态构建 | Global |
| Web Service | `noteai-staging-api` | Docker Starter | Singapore；1GB `/var/data` 持久盘 |
| Web Service | `noteai-staging-admin` | Docker Free | Singapore |
| Web Service | `noteai-staging-claude-gateway` | Docker Starter；1实例/1 worker | Singapore；无磁盘/数据库/Cron |
| Cron Job | `noteai-staging-market-timing` | Docker Starter；`5 * * * *` | Singapore |
| Cron Job | `noteai-staging-tracking` | Docker Starter；`20 * * * *` | Singapore |
| PostgreSQL | `noteai-staging-db` | PostgreSQL 18 Free | Singapore；无生产级备份 |
| DynamoDB | `noteai-claude-gateway-control` | 按请求计费；TTL；静态加密；CloudFormation Retain | Singapore；仅Gateway控制摘要 |

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
- 历史缺陷曾修复并完成五个连续自然健康轮次，但 2026-07-13 最新自然 run `47d75364-0071-4d8f-b35c-b2975ddd138d` 再次出现搜索结果/推荐来源为 0；当前按 `BUG-002` 重新调查，根因确认前不重复修改、不绕过 challenge、不追加手工高频采集。

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

### LAUNCH-001 — 商业上线总门禁

- 状态：**INVESTIGATING**
- 优先级：Critical。
- 问题描述：现有系统已完成 Staging 核心功能验证，但目标生产架构、正式支付、生产数据保护、跨区域 Claude 调用和上线合规尚未闭环。
- 证据：2026-07-12 主控复核当前 HEAD `c0a39ff`、`render.yaml`、代码调用链与三位只读代理报告；当前 Render 仍运行 Web/API/Admin/Cron/PostgreSQL 全栈，仓库未发现 Claude Gateway 或 Adapay 正式支付实现。
- 根因是否确认：是；此前任务目标是 Staging 稳定化，`PROD-001/002/003` 被延期，尚未进入生产实施。
- 涉及文件：本节全部商业上线子任务；最终范围预计覆盖部署清单、Claude transport/Gateway、payment/billing/database/admin/frontend、运维与合规文档。
- 风险：任何单项未完成都可能造成无法收款、重复扣费、数据不可恢复、Claude 不可用、跨境数据风险或正式用户事故。
- 执行代理：主 CTO/TPM 统一编排；各子任务仅允许单一 Implementation Agent 串行修改收入、认证、数据库和共享调用链。
- 验证代理：独立 Release Verification Agent 汇总 Security、Billing/Database、QA、DevOps 证据，不接受实施代理自报完成。
- 验收标准：所有 Critical/High 上线阻断项达到 VERIFIED；阿里云生产、Render Gateway、Adapay 支付/退款/对账、备份恢复、监控、安全与合规门禁均通过；完成受控灰度和回滚演练后才允许正式开放收费。
- 是否需要用户决定：是；涉及付费云资源、商户申请、域名/备案、生产数据、真实小额支付及最终上线切流。
- 是否涉及真实外部调用：是；阿里云、Render、Adapay、Anthropic、DNS/证书和最小真实支付/AI验证均需分阶段批准。
- 是否已部署到 Render：否；现有 Render 仅为全栈 Staging，不是目标生产拓扑。

### ARCH-001 — 收口 Claude 直连并建立 Transport 边界

- 状态：**VERIFIED**
- 优先级：Critical。
- 问题描述：当前 `model_router.py` 和 `model/api.py` 在业务 API 进程内直接调用 Anthropic，无法把 Claude 安全迁到独立 Render Singapore Gateway。
- 证据：只读架构审计确认 `model_router.py` 的 call/stream/chat/semantic 路径直接创建 Anthropic 客户端，`model/api.py` 仍有绕过 Router 的直连 fallback；仓库没有 Gateway URL、内部协议或远程 usage 回传。
- 根因是否确认：是；Claude provider transport 与业务编排、ContextVar 计费记录耦合。
- 涉及文件：预计 `model/model_router.py`, `model/api.py`, `model/billing.py` 及 Claude 路由/计费/API合同测试；第一包不改变实际部署和供应商选择。
- 风险：收口不完整会导致部分生产请求仍从阿里云直连 Claude；usage 回传错误会使真实成本漏记或错记。
- 执行代理：Repository/Architecture Explorer（Godel）完成只读范围确认后担任单一 ARCH-001 Implementation Agent；修改仅限 runtime transport、API遗留旁路和聚焦测试。
- 验证代理：独立 Security/Compatibility Reviewer 首轮PASS；独立 Repository + Billing/Test Verification Agent 首轮因离线工具未登记判FAIL，最小补充仓库级门禁和 `ARCH-001A` 后最终复核PASS。
- 修改状态/进度：新增 SDK 无关 `ClaudeMessageRequest/Result/StreamEvent`、`ClaudeTransport` 与默认 `LocalAnthropicTransport`；非流式、流式、Chat、同步语义评分及Analyze遗留同步fallback全部经统一边界。Local transport把SDK usage归一化为普通字典，Router继续在原ContextVar账务边界记录；保留常规temperature=0.7、semantic=0.3、thinking budget、history清洗、模型选择、retry/fallback/timeout、SSE和首text block语义。`model/api.py` 已无Anthropic import/client/messages直连。仓库级AST门禁扫描 `model/scripts/tools`，生产只允许Local transport两处构造，三个离线工具固定登记，别名/getattr/importlib/__import__/eval/exec动态模式均受检。
- 验收标准：所有生产 runtime Claude 入口只经过统一 `ClaudeTransport`；local transport 保持现有 Staging 行为；生产 API/Admin/Worker 不存在未受控 Anthropic 直连；仓库级静态门禁固定记录并拒绝新增离线工具直连；全量、API、计费、SSE 和 Production Readiness 通过。
- 是否需要用户决定：否；目标架构已经确认，本包不新增云资源、不切换流量。
- 是否涉及真实外部调用：否；本包全部使用Fake transport和离线测试，Anthropic/Moonshot调用为0。
- 是否已部署到 Render：否。
- 独立验证证据：聚焦34/34；更新门禁后transport 8/8、最终独立组合29/29；全量unittest 441/441（5 skip）；全量Playwright 66/66，其中reasoning/SSE 8/8；Production Readiness 48/48；py_compile、Compose、diff check通过。未修改billing、DB/migration、Prompt、前端、render.yaml或模型行为。

### ARCH-001A — 离线 Claude 工具边界与 Gateway 迁移

- 状态：**INVESTIGATING**
- 优先级：Medium。
- 问题描述：生产 runtime 已由 ARCH-001 收口，但三个明确的离线训练/人工运维工具仍直接创建 Anthropic 客户端，尚未决定未来继续直连还是通过 Gateway。
- 证据：仓库级只读盘点确认 `model/extract_cover_features.py` 的离线 Claude Vision 批处理、`tools/ai_prelabel_review_batch.py` 的离线标注复核、`tools/live_ai_smoke.py` 的人工连通性 Smoke 各有一个独立客户端构造；它们均不在当前 Production API 请求链中。
- 根因是否确认：是；这些工具早于统一 runtime transport，且各自有视觉、超时或人工连通性用途。
- 涉及文件：上述三个离线工具、未来 Gateway 工具客户端及仓库级静态门禁；不涉及在线 API、积分、数据库或用户 SSE。
- 风险：若在阿里云生产容器/Worker误调用会绕过Gateway数据边界；`ai_prelabel_review_batch.py` 解析失败还可能把raw片段写入离线错误日志。
- 执行代理：ARCH-002 协议稳定后指定单一 Offline Tool Implementation Agent；ARCH-001 阶段只建立固定 allowlist，不改工具行为。
- 验证代理：独立 Security/Tooling Verification Agent。
- 验收标准：明确每个工具的允许运行环境和数据范围；需Claude的工具通过受控Gateway或获得经审计的离线例外；raw错误不泄露内容/Secret；仓库静态门禁零未登记构造点。
- 是否需要用户决定：若离线批任务调用真实Claude、产生费用或处理真实用户数据，需要。
- 是否涉及真实外部调用：本地静态治理不需要；最终工具Smoke会产生少量Claude费用。
- 是否已部署到 Render：否；这些工具不得由Render Gateway业务服务自动执行。

### ARCH-002 — Render Singapore Claude Gateway

- 状态：**VERIFIED**
- 优先级：Critical。
- 问题描述：需要新增只负责 Claude 调用的最小服务，主系统通过带版本的内部协议调用；Gateway 不得承载用户、支付、数据库、Admin、Kimi、Cron 或模型文件。
- 证据：当前 `render.yaml` 没有独立 Gateway，API 服务同时持有数据库、Claude/Kimi、S3 和视频磁盘配置；现有 readiness 只检查本进程 Key。
- 根因是否确认：是；服务边界和内部认证目前完全不存在。
- 涉及文件：`model/claude_gateway_protocol.py`, `gateway/claude_gateway.py`, `gateway/Dockerfile`, `gateway/requirements.txt`, `gateway/start.sh`, `render.gateway.yaml`, `docs/CLAUDE_GATEWAY.md`, `model/model_router.py`, `model/api.py`, `tests/test_claude_gateway.py`, `tests/test_claude_transport.py`；未修改现有 `render.yaml`、数据库、支付、Prompt、前端或采集链。
- 风险：内部接口暴露、签名重放、模型越权、跨区域网络歧义、双层重试导致重复供应商费用、Prompt/附件进入日志。
- 执行代理：单一 Gateway Implementation Agent（Godel）已完成本地实现及两轮最小加固；没有其他代理并行修改相同文件。
- 验证代理：独立 Security Reviewer（Tesla）+ Protocol/Chaos Verification Agent（Ampere）；首轮发现未来时间戳重放、无长度请求内存边界、网络异常原文和响应媒体类型门禁缺口，均退回原实施代理修正；最终安全复核与协议负测均PASS，允许进入单实例Staging部署。
- 修改状态/进度：已实现 `claude-gateway.v1` HMAC协议、current/previous双Key、未来时间戳安全nonce TTL、单实例并发/速率/防重放、请求流式有界读取、严格模型/字段/token/image门禁、raw reasoning丢弃、固定错误码、完整usage envelope与断流 `usage_missing` 审计；主系统保留Local默认，仅显式Gateway模式切换。独立Blueprint只含一个Singapore Starter、单worker、单实例、无数据库/磁盘/Cron/Kimi/S3/业务服务。首次云端日志复核发现Uvicorn默认access log仍记录来源IP和endpoint path，已在同一包增加 `--no-access-log` 并补包装回归；独立安全代理PASS，修复commit `a95ec6a` 已部署。旧实例 `qmdqn` 于08:59:50完成排空；新实例 `rmqhb` 的09:01:21负测日志只出现固定 `gateway_reject code=AUTH_HEADER_INVALID`，没有IP、path、Prompt、body、响应或Secret。
- 验收标准：TLS；HMAC或短期服务JWT绑定 method/path/timestamp/nonce/body hash；重放、过期、越权和超限全部拒绝；无业务CORS/用户Token/数据库连接；非流式、流式、Chat、语义评分均可用；usage envelope 可由阿里云主库准确记账；日志只含固定枚举、计数和哈希关联ID。
- 是否需要用户决定：已确认。2026-07-12 用户批准先创建1个Render Singapore Starter Staging Gateway（增量7美元/月），最多4次合成文本真实Claude Smoke、费用上限人民币20元；正式上线采用2个Starter基础14美元/月，可自动扩容至4个、最高28美元/月。
- 是否涉及真实外部调用：是；本轮获批范围仅为1个Staging Gateway和最多4次合成文本Claude Smoke，不接生产流量，不创建数据库、磁盘、Redis或Cron。
- 是否已部署到 Render：是，单实例Staging范围已闭环。`noteai-staging-claude-gateway` 由独立Blueprint运行于Singapore Starter，最终live commit `a95ec6a`；push与PR两条GitHub CI均PASS，readiness HTTP 200且明确 `single_instance_only`/`memory_instance_scope`/`multi_instance_production_ready=false`，Scaling为1实例且Autoscaling Off，环境变量仅含Anthropic、Gateway HMAC与固定限制项，无数据库/Kimi/S3/Cron/磁盘。负测未签名与错签名均401固定码；真实Smoke使用合成文本3/4次：Haiku非流式200（25 in/13 out）、Haiku流式200（25 in/12 out，事件content→usage→done，同签名重放409）、Sonnet非流式200（22 in/4 out），合计72输入/29输出Token，按`official-2026-07-12`与USD/CNY 7.00估算约¥0.002107，远低于¥20上限；未执行第4次。Smoke为Gateway直测，不写业务数据库且现有Staging仍保持Local transport。最终Web/API/Admin/Gateway健康均HTTP 200；Admin首次超时由Free实例休眠解释，唤醒后连续200。`--no-access-log` 云端复验通过。正式2–4实例仍由 `ARCH-002P` 阻断，不得以本任务VERIFIED代替Production就绪。

### ARCH-002P — Claude Gateway Production多实例安全化

- 状态：**INVESTIGATING**
- 优先级：Critical。
- 问题描述：用户已批准正式上线采用2个Render Starter并可自动扩容至4个；`ARCH-002P-A/B` 已分别闭环Claude终态费用安全与共享原子控制面，但精确Gateway信任/readiness/timeout及真实2–4实例演练仍未完成。
- 证据：Gateway Staging 已返回 `ready_multi_instance`、`shared_control_plane` 与 `dynamodb_shared_atomic`，该字段只证明共享控制面的技术能力；当前Render实际仍为1实例、1 worker。合法HTTPS任意公网hostname、远端readiness、分层timeout与真实滚动/扩缩容矩阵仍由`ARCH-002P-C/D`阻断。
- 根因是否确认：是；A/B根因已修复，剩余根因是主系统对精确Gateway authority/readiness的信任边界不完整，以及尚无平台真实2–4副本/滚动/故障演练证据。
- 涉及文件：预计Gateway专用共享replay/rate store适配、部署配置、精确Gateway hostname绑定/私网解析防护、远端健康监控、timeout预算、partial-stream终止与usage审计测试；不得连接NoteAI业务数据库。
- 风险：共享原子状态已消除已知的nonce/rate/operation跨客户端竞争，但DNS/配置误指向、timeout层级、真实扩缩容/滚动版本漂移、取消与业务持久恢复仍未闭环。
- 执行代理：只读阶段由Repository Explorer（Godel）、Security/Chaos Reviewer（Tesla）和Render/DevOps/Cost Reviewer（Ampere）完成；实施按ARCH-002P-A→B→C→D指定单一Gateway Production Implementation Agent串行执行，共享配置和部署不得并行修改。
- 验证代理：每个子包由未参与实现的Security + Protocol/Chaos + Billing/Cost Verification Agents独立复核；最终完成扩缩容、重放、故障和Key轮换演练。
- 验收标准：2–4实例使用共享原子nonce/rate状态；平台实际副本数与门禁一致；Gateway URL精确绑定并拒绝私网/DNS rebinding；请求发出后的所有不确定终态可审计；部分流失败不再隐式fallback产生重复正文/费用；双Key轮换和回滚演练通过；远端健康与timeout预算可观测。
- 是否需要用户决定：生产2–4个Starter基础14–28美元/月已获批；共享状态已改用获批的AWS DynamoDB按请求计费，不再需要Render Key Value。真实Claude额外调用仍按已批准剩余次数/费用边界执行或另行说明。
- 是否涉及真实外部调用：A/B已使用Render、AWS OIDC/DynamoDB和无AI合成Smoke；最终仍需2–4实例Render受控压力/故障演练，是否使用剩余真实Claude次数在D执行前列明。
- 是否已部署到 Render：部分；A/B已部署到单实例Staging，C/D未实施。不得把`ready_multi_instance=true`当作Production多实例完成证据。

### ARCH-002P-A — Claude调用终态与fallback费用安全

- 状态：**VERIFIED**
- 优先级：Critical。
- 问题描述：流式Claude已经输出部分正文后发生异常时，Router仍可调用Kimi/Haiku fallback并把第二份正文拼接到原流；请求已可能到达供应商但主API未收到headers、以及取消发生在usage前时，usage审计边界也不完整。
- 证据：原实现中`model/model_router.py::stream`与`stream_chat`在主流异常后无条件fallback，Gateway可先提交200 headers再开始迭代provider，dispatch后/usage前取消可能漏审计。2026-07-13实施后，三轮独立fault verification先后发现并退回修复consumer abandonment、未启动body iterator、thinking-only preflight死等、header/body socket send失败四类生命周期缺口；最终独立探针全部PASS。
- 根因是否确认：是；当前状态机只依赖异常类型/HTTP状态，没有签名逻辑operation-id，也没有区分pre-dispatch、provider-started、partial-output和terminal-usage。
- 涉及文件：`model/model_router.py`, `gateway/claude_gateway.py`, `tests/test_claude_gateway.py`, `tests/test_claude_transport.py`, `tests/test_api_contracts.py`；`model/claude_gateway_protocol.py`未修改，协议字段保持兼容。
- 风险：重复供应商费用、两份模型正文拼接、已退款但供应商成本漏审计；错误收紧可能让确定未发出的请求失去安全fallback。
- 执行代理：单一Gateway Protocol Implementation Agent（Godel）完成；没有并行修改共享状态或相同调用链。
- 验证代理：独立Security/Protocol/Chaos Verification Agent（Tesla）执行三轮代码审查和自建故障探针；前两轮FAIL均退回修复，第三轮PASS。主CTO另行复跑定向、全量与Production Readiness。
- 验收标准：只有可证明provider未启动且零正文输出时允许fallback；provider可能启动、已输出任意正文或取消后均不得自动重试/fallback；partial stream以固定安全终态结束；usage或`usage_missing`恰好记录一次；不记录正文、Prompt或异常原文。
- 修改状态/进度：已实现固定pre-provider allowlist（`AUTH_REPLAY`明确不安全）、Claude ambiguous/partial/cancel fail-closed、非流式空响应/超时不重试不fallback、嵌套async iterator显式关闭、Gateway首公开事件preflight、默认175秒thinking-only上限、body iterator与response-level幂等cleanup。部分正文后统一`CLAUDE_STREAM_PARTIAL`；首事件前失败返回固定JSON非2xx；所有日志只含固定code/model/phase。两条旧API合同由“provider可能启动后仍retry/fallback”更新为更严格的一次调用、零fallback断言。验证：相关定向213/213 PASS；全量484 PASS、5 skipped；`py_compile`、`git diff --check`、Production Readiness 48/48 PASS。独立探针覆盖header OSError、连续第1–4个body send OSError、CancelledError、重复aclose、consumer abandonment、未启动body和endless-thinking，provider close与limiter release均恰好一次；未调用真实AI/Render。
- 是否需要用户决定：否；不改变模型选择、计费规则或对外产品语义，只收紧重复调用安全边界。
- 是否涉及真实外部调用：本地fault injection不涉及；最终真实Claude最小验证另行计入获批预算或单独批准。
- 是否已部署到 Render：是，仅现有单实例Staging。用户批准后commit `b5d4b7e`已推送并由Render自动部署，push/PR两条GitHub CI均PASS；Render事件确认该commit live，Gateway/API/Web/Admin最终HTTP 200（Admin首次因休眠超时，唤醒后200），未签名请求返回固定`AUTH_HEADER_INVALID`，新实例日志只有固定错误码，无IP、URL、Prompt、正文或异常原文。未执行第4次真实Claude Smoke。ARCH-002P-B/C/D未完成前不得扩为Production多实例。

### ARCH-002P-B — Gateway共享原子控制面

- 状态：**VERIFIED**
- 优先级：Critical。
- 问题描述：nonce、rate和concurrency均为单进程内存；扩至2–4实例会绕过防重放与全局配额，重启会丢失状态。
- 证据：`gateway/claude_gateway.py` 的`InMemoryNonceStore`、`InMemoryRateLimiter`、`ConcurrencyLimiter`均只在进程锁内原子；Blueprint固定单worker、单实例，readiness明确禁止多实例。2026-07-13 DevOps/Cost与Resilience/Security只读复核确认：Render Key Value单实例、Redis Cloud Essentials/Aiven异步复制和Render Postgres异步HA都不能证明最近nonce/operation claim零丢失；AWS DynamoDB Singapore单Region表在服务内跨3个AZ同步复制，成功写入即durably persisted，支持条件写/ACID事务与99.99% SLA，Render Pro可用自动轮换OIDC凭证直接调用HTTPS endpoint。
- 根因是否确认：是；本子包根因是Gateway缺少跨实例强原子nonce/rate/operation/lease控制面。Alibaba主系统的Kimi/持久队列、结果回放和副作用恢复是独立的`BILL-002`，未被本子包实现或验证。
- 涉及文件：`model/model_router.py`, `model/claude_gateway_protocol.py`, `gateway/claude_gateway.py`, `gateway/control_store.py`, `gateway/dynamodb_control_store.py`, `gateway/requirements.txt`, `gateway/Dockerfile`, `render.gateway.yaml`, `infra/aws/claude_gateway_control_plane.yaml`, `docs/CLAUDE_GATEWAY.md`, `tests/test_gateway_control_store.py`, `tests/test_claude_gateway.py`, `tests/test_claude_transport.py`；未修改`model/api.py`/idempotency/billing/业务数据库，`BILL-002`保持独立串行。
- 风险：Gateway共享控制面当前已安全阻止不确定情况下的新Claude调用，但NoteAI整体的Kimi/持久队列连续服务与业务结果恢复尚未完成；真实2–4实例、滚动发布、OIDC刷新和store断路组合仍由`ARCH-002P-D`验证。
- 执行代理：HA方案只读阶段由Render/DevOps/Cost Reviewer（Ampere）与Resilience/Security Reviewer（Tesla）完成；单一DynamoDB Shared Control Plane Implementation Agent（Godel）完成代码与声明式配置；主CTO串行创建AWS/Render资源并执行云端Smoke，全程未调用真实Claude。
- 验证代理：独立Verification Agent（Ampere）与Security/Chaos Reviewer（Tesla）；本地首轮发现operation TTL、lease exact-expiry、DynamoDB timeout/retry、OIDC、rate与provider deadline阻断，第二轮发现begin复用陈旧时间，均退回最小修正；最终本地及云端证据复审均PASS。
- 验收标准：共享原子nonce、逻辑operation状态、全局rate和可续租concurrency lease；以稳定服务主体而非key-id计配额；DynamoDB Region内多AZ托管可用性；控制面不可达时Gateway对Claude保持零新调用；只保存哈希、枚举、时间和usage摘要；无memory降级。Alibaba主系统的Kimi/queue与持久结果恢复明确不属于本子包，继续由`BILL-002`验收。
- 是否需要用户决定：否；DynamoDB、Render OIDC、AWS SDK与Staging切换均已按批准范围完成。1美元月预算邮件缺收件地址，已拆为`FIN-003`，不阻断本子包的原子性/安全验收。
- 是否涉及真实外部调用：是；已创建AWS DynamoDB、IAM OIDC provider/role并配置Render Staging，执行STS/DDB真实无AI Smoke。未调用Claude、未写业务数据库；生产多实例演练仍归D。
- 是否已部署到 Render：是，仅Staging单实例范围。AWS Singapore CloudFormation Stack `CREATE_COMPLETE`；DynamoDB为Active/on-demand/`pk`/TTL `expires_at`/静态加密/Retain；Render OIDC provider使用官方workspace issuer与`sts.amazonaws.com`，IAM trust精确到当前workspace/default/service、无wildcard，权限仅具体表ARN的Describe/Get/Put/Update/Delete/TransactWrite六动作。Render容器真实凭证method为`assume-role-with-web-identity`且自动token file存在。切换commit `d279caa`的push/PR两条CI均成功，Render 21:09 live；readiness HTTP200并返回`ready_multi_instance`/`shared_control_plane`/`dynamodb_shared_atomic`。未签名请求401固定`AUTH_HEADER_INVALID`；两个独立真实DDB客户端并发nonce/rate/operation各恰好1个winner，无效合成表安全失败，合成记录在finally删除；Claude调用0。独立Verification与Security/Chaos均PASS。Staging仍1实例/1 worker，不能宣称Production 2–4实例已验证。

### FIN-003 — AWS Gateway 1美元月预算告警

- 状态：**VERIFIED**
- 优先级：High（正式流量前成本运营门禁）。
- 问题描述：DynamoDB按请求计费控制面需要可送达的低额异常成本预警。
- 证据：2026-07-13 AWS Budgets 已创建月度成本预算 `NoteAI-Gateway-Control-Plane-Monthly-1USD`，金额US$1.00、无服务筛选、运行正常；两条直接邮件告警为实际成本超过80%与预测成本超过100%。独立FinOps只读复核确认邮箱与用户提供一致，SNS未启用、Actions为0、无Chatbot或自动动作，直接邮件无需订阅确认。
- 根因是否确认：是；缺少收件邮箱的阻断已由用户提供地址后闭环。
- 涉及文件：无仓库代码；仅AWS Budgets通知配置。
- 风险：该预算覆盖全部AWS服务而非只筛选Gateway控制面；有利于早期发现总账异常，但不能单独归因具体资源，后续生产多资源阶段需另建分服务/标签预算。
- 执行代理：主CTO使用AWS控制台；验证代理：独立FinOps Reviewer读取固定预算金额、周期和订阅状态。
- 验收标准：已满足。月度成本预算1美元；实际80%与预测100%向用户指定邮箱发送直接邮件；无自动停机/SNS/Chatbot；独立只读验证通过且未输出账户、邮箱或其他敏感配置。
- 是否需要用户决定：否；邮箱已提供并配置。
- 是否涉及真实外部调用：是；已创建AWS Budget直接邮件通知，未调用AI、未写业务数据。
- 是否已部署到 Render：不适用。

### ARCH-002P-C — Gateway生产信任与readiness边界

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：主系统当前接受任意合法公网HTTPS hostname，不验证精确Gateway authority或连接时解析结果；readiness只做本地配置检查，provider/client/业务timeout层级也未对齐。
- 证据：2026-07-13 commit `0e050f8` 完成 v2 authority/config/key epoch HMAC、严格global-unicast与真实peer pin、签名远端readiness、200-only/no-redirect/no-env-proxy、provider180<HTTP190<business210绝对deadline、readiness single-flight/旧绿隔离、2 running+2 queued有界DNS executor与取消风暴保护。实施前多轮失败合同真实跑红；主控与独立Test/Security复验一致PASS：全量539/539（5 skipped）、Gateway/API218/218、Production Readiness48/48、100次真实取消风暴有界且late resolver的pin/POST/provider/audit均为0。CI-001 commit `c0afbbe` 修复测试依赖后，GitHub push/PR两条CI全部SUCCESS。Render六项运行资源均完成 `c0afbbe` 自动部署/构建；Gateway/API/Admin公开readiness均HTTP200。主控和独立Verification分别在Gateway Shell执行零Claude签名GET：HTTP200，attestation/challenge/nonce/epoch全部匹配，scope=`shared_control_plane`、store=`dynamodb_shared_atomic`。
- 根因是否确认：是；代码、CI与单实例Staging最终验证全部闭环。生产2–4实例扩缩/滚动/故障矩阵仍是独立`ARCH-002P-D`，不属于C的验收范围。
- 涉及文件：最小候选 `model/model_router.py`, `model/claude_gateway_protocol.py`, `model/api.py`, `gateway/claude_gateway.py`, `render.yaml`, `render.gateway.yaml`, `docs/CLAUDE_GATEWAY.md`, `tests/test_claude_gateway.py`, `tests/test_api_contracts.py`；不改业务DB/billing/BILL-002/D扩容。
- 风险：误配或被篡改URL可把Prompt与签名发送到错误域；DNS可解析到私网/保留地址；跨authority转发可泄露请求并触发Claude；旧/错误Gateway可被本地readiness假绿；3xx可冒充成功；timeout倒挂会把仍运行的供应商调用变成不确定费用。
- 执行代理：单一Gateway Trust/Readiness Implementation Agent（Godel）；不得并行修改同一调用链。
- 验证代理：独立Security/Chaos Reviewer（Tesla）+ Test/DevOps Verification Agent（Ampere）。
- 验收标准：唯一批准的规范ASCII authority精确匹配；A/AAAA全部公网且连接固定到已验证地址并保留原hostname TLS/SNI/Host，拒绝混合私网、保留地址和rebind；显式TLS验证、`trust_env=False`、不跟redirect且只接受200；新协议把authority/config epoch/key epoch纳入HMAC，任一不匹配provider调用0；Gateway暴露不含Secret/key-id的签名readiness challenge、server time与epoch，主API只有service/protocol/shared scope/DynamoDB store/challenge/epoch/时钟全部匹配才remote_ready；AI-required时失败/超时/旧绿过期令API503；Gateway模式满足provider180 < HTTP190 < 业务总deadline210，Local timeout保持兼容，SDK retry0且显式有界；真实Claude0次即可验收。
- 是否需要用户决定：否；正式域名/host值在生产资源创建时按实际值注入，不改变用户产品行为。
- 是否涉及真实外部调用：本地实施使用Mock/假DNS；最终仅用Render公开健康GET和签名readiness GET验证，没有消息POST、真实Claude或业务数据库写入。
- 是否已部署到 Render：是；运行时代码 `0e050f8` 随CI-only `c0afbbe` 再次自动部署。Gateway/API/Web/Admin均live，两个Cron为Successful build；签名readiness由主控与独立代理各自执行并PASS。主API仍为Local transport，C的结论不得外推为Alibaba切流或生产2–4实例已验证。

### CI-001 — Blueprint语义测试缺少测试专用PyYAML依赖

- 状态：**VERIFIED**
- 优先级：High（阻断ARCH-002P-C独立验收，不影响当前旧/新Gateway运行时健康）。
- 问题描述：新增测试使用`yaml.safe_load`语义解析两份Render Blueprint；本地环境已有PyYAML，但GitHub Actions只安装`model/requirements.txt`，导致push与PR CI在unit tests报`ModuleNotFoundError: No module named 'yaml'`。
- 证据：历史失败 run `29259436657` 的唯一失败为 Blueprint 语义测试导入`yaml`失败。commit `c0afbbe` 新增 `tests/requirements.txt` 固定 `PyYAML==6.0.3`，CI 在生产依赖之后单独安装测试依赖；`model/requirements.txt`、测试断言和业务代码无diff。Implementation与独立Verification均确认本地全量539/539（5 skipped）、Production Readiness48/48、三份YAML safe_load、Compose与diff check通过；GitHub push run `29262804273` 与PR run `29262808793` 全部步骤SUCCESS。
- 根因是否确认：是；测试依赖声明缺失，不是Gateway代码或Render运行时故障。
- 涉及文件：推荐新增测试专用requirements文件并最小修改`.github/workflows/ci.yml`安装固定版本PyYAML；不把PyYAML加入生产镜像，不改测试断言。
- 风险：不修会让CI持续红；直接把PyYAML加入生产依赖会无必要扩大生产供应链；改回字符串搜索会弱化安全测试，禁止采用。
- 执行代理：单一CI Implementation Agent（Godel）；验证代理：独立Test/DevOps Reviewer（Ampere），结论PASS。
- 验收标准：已满足。GitHub push与PR CI全绿；Blueprint继续用真实YAML语义解析；生产镜像依赖不增加；本地539项、Production Readiness48/48、YAML/Compose均通过。
- 是否需要用户决定：否；用户已明确批准测试专用固定依赖方案。
- 是否涉及真实外部调用：仅GitHub CI和既有Render自动部署；真实Claude0次、业务数据库0写。
- 是否已部署到 Render：CI文件本身不影响运行时；同分支自动部署 `c0afbbe`，Gateway/API/Web/Admin均live，两个Cron均Successful build，独立Render Verification PASS。

### ARCH-002P-D — Render 2→4实例发布与故障演练

- 状态：**IMPLEMENTING**
- 优先级：Critical。
- 问题描述：只有单实例Staging证据，没有2实例基线、自动扩至4实例、滚动发布、共享store中断和回滚演练。
- 证据：Gateway已在Render Singapore真实配置为Starter autoscaling min2/max4、CPU60%、memory70%、shutdown240；Blueprint Auto Sync保持No，主API readiness仍明确`claude_transport=local`，用户业务流量尚未切入Gateway。`22da06a`演练器、`710065f`existing-claim修复、`353ee22`固定枚举诊断、`8b6a0b3`最小IAM修复均已通过本地、独立审查、GitHub CI并收敛云端。两实例同ID已闭环1×200/1×409、FakeProvider总计1、UNKNOWN0；两实例共享速率窗口已闭环30×INVALID_JSON+10×RATE_LIMIT。随后在两个原实例运行受限CPU负载，Render真实Autoscaler事件依次记录扩至3并成功扩至4，未手工设4。四个真实实例均输出不同instance marker、相同commit `8b6a0b3`与相同control marker；四实例下3个不同held operation恰2×200/FakeProvider1与1×429/CONCURRENCY_LIMIT/FakeProvider0；同ID仍恰1×200/1×409；40个共享速率请求仍恰30×INVALID_JSON+10×RATE_LIMIT。负载自然结束后，Render事件于02:02记录开始并成功缩至2；缩容后的两个存活实例再次用同一全新operation闭环1×200/1×409、FakeProvider总计1、UNKNOWN0。其后对同一批准commit `8b6a0b3`执行Gateway Manual Deploy：两个旧实例被两个全新instance marker替换，旧operation在新实例仍固定409/FakeProvider0，新operation在两个新实例仍恰1×200/1×409/FakeProvider总计1，commit/control marker一致；Gateway重新收敛`ready_multi_instance`且主API始终`claude_transport=local`。完整过程真实Claude0次、业务数据库0写。
- 根因是否确认：是；2→4→2共享控制面和平台自动扩缩容已确认，父任务剩余范围为滚动替换、单实例重启、OIDC/HMAC轮换及受控故障/回滚矩阵，不是新的功能根因。
- 涉及文件：`render.gateway.yaml`, Gateway Staging-only演练器、部署/回滚/轮换runbook、健康与指标配置、故障矩阵测试；不修改业务数据库。
- 风险：扩缩容瞬间版本/配置不一致、OIDC刷新或DynamoDB断路造成Gateway拒绝新Claude调用、网络型负载不能及时触发平台autoscale；主系统持续服务仍依赖BILL-002的Kimi/queue与持久恢复。
- 执行代理：ARCH-002P-A/B/C全部独立验证后，由单一Render Deployment Agent串行发布。
- 验证代理：独立Security + Protocol/Chaos + Billing/Cost Verification Agents。
- 验收标准：2实例基线、min2/max4自动扩容与应用全局限流同时生效；跨实例同nonce/operation恰好一次provider；滚动、重启、store中断、Key轮换、2→4→2和回滚矩阵通过；故障时宁可固定码不可用，不重复Claude；日志不含敏感内容。
- 是否需要用户决定：生产2–4个Starter实例14–28美元/月与DynamoDB共享控制面已获批；C及FIN-003前置门禁已完成。执行D前只需按已批准上限列明演练窗口与是否使用剩余真实Claude Smoke次数，不再重复要求批准相同基础费用。
- 是否涉及真实外部调用：是，Render真实扩缩容/故障演练；当前第一阶段固定为真实Claude 0次、业务数据库0写，先完成零调用矩阵。只有零调用矩阵闭环后才评估是否使用既有批准额度内的最小Claude Smoke。
- 是否已部署到 Render：部分。最新commit `8b6a0b3`已完成真实2→4→2、2/4实例exact-once、全局并发2、全局RPM30、缩容后复验与同commit滚动替换后共享状态复验；仍须完成单实例重启、自然OIDC刷新、HMAC轮换及受控故障/回滚矩阵，父任务才可VERIFIED。

### ARCH-002P-D1 — 多实例同 operation 认领竞态

- 状态：**VERIFIED**
- 优先级：Critical（阻断ARCH-002P-D云端exact-once验收）。
- 问题描述：两实例对同一synthetic operation并发演练时，竞争者得到`OperationClaim(state=CLAIMED, created=False)`后仍进入`begin_provider`，真实DynamoDB事务竞争返回`CONTROL_PLANE_OUTCOME_UNKNOWN`。
- 证据：2026-07-14 Staging已部署`22da06a`并真实扩至2实例；首轮零Claude演练中一个实例固定输出HTTP503、`CONTROL_PLANE_OUTCOME_UNKNOWN`、`fake_provider_calls=0`，随即按stop条件停止，未触发4实例负载。两名独立只读代理交叉确认：`gateway/claude_gateway.py::_SharedDispatch.prepare`只检查claim state而忽略`claim.created`；DynamoDB首个Put创建claim，竞争者条件失败后强一致读仍返回`CLAIMED/created=False`，两者可占不同lease槽并竞争同一OP事务。主API云端readiness仍明确`claude_transport=local`，Gateway readiness仍为共享DynamoDB green，用户业务未切流。单一Implementation Agent已按A包只改3文件：生产逻辑仅增加`or not claim.created`；确定性两槽barrier测试锁定1×200/1×409、begin=1、FakeProvider=1、UNKNOWN=0；D/E崩溃边界及after-apply保守语义均有回归。主CTO复验focused111/111、full547通过（skip5）、Production Readiness48/48、py_compile/diff-check全绿；独立Security/Protocol Verification PASS。
- 根因是否确认：是（代码事实100%；与本次云端固定证据匹配约90%，底层DynamoDB cancellation reason按脱敏规则未输出）。
- 涉及文件：`gateway/claude_gateway.py`, `tests/test_claude_gateway.py`, `docs/CLAUDE_GATEWAY.md`；不修改DynamoDB schema、IAM、Cookie、Secret、业务数据库或真实Provider。
- 风险：若把所有TransactionConflict降级成duplicate或增加重试，可能掩盖真实after-apply不确定性并造成重复Claude；若改变claim-before-lease顺序会在无槽时留下永久claim。本包只恢复现有永久at-most-once/fail-closed契约。
- 执行代理：单一Gateway Implementation Agent（Godel）；验证代理：独立Security/Protocol Agent（Tesla）+ 主CTO云端零Claude复验。
- 验收标准：`created=False`无论state是否仍为CLAIMED都释放本次lease、零`begin_provider`、零provider并返回固定409；确定性两槽同ID并发恰1次begin/1次FakeProvider，竞争者409且unknown=0；acquire后claim前可在lease到期后重新执行；claim后begin前崩溃保持永久fail-closed且重试409/provider0；真正begin after-apply不确定仍为`CONTROL_PLANE_OUTCOME_UNKNOWN`且不重试；三个不同ID仍恰2 provider+第三个限流；focused/full/readiness全绿；新commit部署收敛后以全新synthetic ID在两个不同实例复验，绝不复用本次ID。
- 是否需要用户决定：否；属于已批准ARCH-002P-D范围内的最小竞态修复，不新增资源或真实AI费用。
- 是否涉及真实外部调用：实施/本地验证为0；部署后仅零Claude Staging演练和DynamoDB固定控制记录。
- 是否已部署到 Render：是；`710065f`已收敛到2实例Staging，后续`8b6a0b3`也已收敛。IAM前置问题修复后，两个不同真实实例以同一全新synthetic operation在同一未来时刻并发：恰1个winner HTTP200/FakeProvider1、1个loser HTTP409/FakeProvider0、`CONTROL_PLANE_OUTCOME_UNKNOWN`为0、真实Claude0次，完整闭环D1云端验收。

### ARCH-002P-D2 — `begin_provider` 事务固定枚举诊断与根因确认

- 状态：**VERIFIED**
- 优先级：Critical（阻断ARCH-002P-D/D1云端winner验收）。
- 问题描述：真实2实例中的winner在进入Claude前于DynamoDB `begin_provider`/`TransactWriteItems`返回不确定结果；当前`_call`将所有非纯条件异常折叠为无结构`ControlStoreUnavailable`，无法在不泄露敏感信息的前提下区分权限拒绝、表达式校验、事务冲突、超时/传输或after-apply响应丢失。
- 证据：云端新operation winner固定503/`CONTROL_PLANE_OUTCOME_UNKNOWN`/fake0，竞争者已固定409/fake0；表达式中的占位符齐全，`state`已用别名且AWS保留词表中`model`非保留词；当前仓库CloudFormation从最初提交即包含`dynamodb:TransactWriteItems`表ARN权限，但readiness只证明`DescribeTable`可用，不能替代实际运行角色/边界/SCP的当前授权证据。单一Implementation Agent已完成最小诊断包：DynamoDB `_call`只从固定AWS code/reason和本地异常类型映射阶段/原因，ContextVar捕获仅由严格guard后的shell rehearsal私有capability启用；普通HTTP与固定日志不新增诊断。敏感sentinel、纯条件、after-apply单次事务、CancelledError及并发上下文隔离均有回归。Gateway+control聚焦93/93、全量550通过（skip5）、Production Readiness48/48、py_compile/diff-check全绿。
- 根因是否确认：部分。“异常被过度折叠、无法安全定位”的诊断根因已确认；真实DynamoDB begin失败的外部根因未确认，不得猜测为IAM。
- 涉及文件：`gateway/dynamodb_control_store.py`, `gateway/rehearsal.py`, `tests/test_gateway_control_store.py`, `tests/test_claude_gateway.py`, `docs/CLAUDE_GATEWAY.md`；不修改IaC/IAM、DynamoDB schema/事务表达式、重试/fallback、provider、公共HTTP响应或日志语义。
- 风险：异常原文、RequestId、URL、table/role/principal/operation/ARN可泄露控制面详情；若把TransactionConflict或after-apply不确定降级为可重试，可能重复调用Claude。
- 执行代理：单一Gateway Implementation Agent（Godel）；验证代理：独立Security/Protocol Reviewer + 主CTO云端一次性零Claude复验。
- 验收标准：仅通过严格Staging guard的shell rehearsal可读固定stage/reason枚举；公共Gateway对外仍只返`CONTROL_PLANE_OUTCOME_UNKNOWN`且零重试；纯条件失败仍返False，after-apply仍UNKNOWN，`CancelledError`透传；带敏感sentinel的AccessDenied/Validation/TransactionConflict/缺少reasons/throttle/resource-missing/timeout/transport/internal/unknown合成测试证明枚举正确且敏感信息零泄露；focused/full/readiness/CI与独立复核通过；部署收敛后仅用一个全新synthetic operation做零Claude定位，不重试同op ID。
- 是否需要用户决定：否；属于已批准ARCH-002P-D的安全诊断范围，不新增资源或AI费用。
- 是否涉及真实外部调用：实施/本地验证0；部署后仅一次新synthetic operation的Staging DynamoDB控制记录，真实Claude 0次。
- 是否已部署到 Render：是；commit `353ee22` push/PR两条CI全绿并已在2实例Staging live。独立Security/Protocol复跑93/93、Readiness48/48并PASS；云端一次有效全新synthetic operation固定返回`BEGIN_PROVIDER/ACCESS_DENIED`、HTTP503、fake0，未重试该ID、真实Claude0次。一次未注入ACK的命令在guard 403即停，DynamoDB0/AI0。

### ARCH-002P-D3 — DynamoDB 事务 `ConditionCheckItem` 最小IAM修复

- 状态：**VERIFIED**
- 优先级：Critical（阻断ARCH-002P-D/D1 winner 200）。
- 问题描述：`begin_provider` 真实事务在Provider前被AWS IAM拒绝。现有IaC允许`dynamodb:TransactWriteItems`，但AWS交易IAM模型按事务内层动作授权：Update需`UpdateItem`，ConditionCheck需`ConditionCheckItem`。当前已有UpdateItem，唯独缺ConditionCheckItem。
- 证据：`353ee22`云端固定诊断为`BEGIN_PROVIDER/ACCESS_DENIED`，而同一请求的nonce/rate/lease/claim单项DynamoDB读写已先成功，排除整体OIDC失效。AWS官方《Using IAM with DynamoDB transactions》明确规定交易中Put/Update/Delete/Get由底层同名权限管理，ConditionCheck需`dynamodb:ConditionCheckItem`；原CloudFormation action列表缺失该动作。Implementation Agent仅把无效的`TransactWriteItems`替换为`ConditionCheckItem`并增加精确语义测试；独立DevOps/Security复验IaC/Gateway 21/21、Production Readiness 48/48、YAML精确结构与diff-check全绿。主CTO创建并预览CloudFormation change set，确认唯一变化是原Gateway IAM Role的Properties且Replacement=False；执行后Stack为`UPDATE_COMPLETE`，实际策略固定核验为6项、包含ConditionCheckItem且不含TransactWriteItems。云端单winner与两实例同ID并发均通过，真实Claude0次。
- 根因是否确认：是，代码、真实脱敏运行证据与AWS官方授权模型三方一致。
- 涉及文件：最小仅`infra/aws/claude_gateway_control_plane.yaml`、相关IaC/Gateway测试与必要runbook；不修改trust/OIDC、table ARN、数据库/schema、应用事务、重试/fallback、Provider或Render扩容配置。
- 风险：过宽的`dynamodb:*`或`Resource:*`会破坏最小权限；只在线上手改角色会产生CloudFormation漂移。必须先修正仓库模板并验证，再由原Stack更新。
- 执行代理：单一IAM Implementation Agent（Godel）；验证代理：独立DevOps/Security Reviewer（Ampere）+主CTO云端零Claude复验。
- 验收标准：IaC精确表ARN的action集合为Describe/Get/Put/Update/Delete/ConditionCheckItem，不存在通配或无关动作；本地测试/readiness/CI和独立审查通过；原CloudFormation Stack更新收敛且无其他资源变更；一个全新synthetic operation在真实winner路径HTTP200/FakeProvider1，真实Claude0；再用两实例全新同ID验收恰1个winner 200、1个loser 409、provider1、UNKNOWN0。
- 是否需要用户决定：否；属于已批准AWS Singapore Staging控制面的最小权限纠正，不新增资源或费用。
- 是否涉及真实外部调用：是，将更新原AWS CloudFormation Staging Stack的单一IAM action；后续仅零Claude合成验证，不写业务数据。
- 是否已部署到 Render：是；仓库commit `8b6a0b3`已push且PR CI全绿，并已收敛到两个Render Staging实例。原AWS Staging CloudFormation Stack已更新为`UPDATE_COMPLETE`且仅修改精确IAM action。云端全新单winner为HTTP200/FakeProvider1；两实例同一全新ID为1×200/1×409、FakeProvider总计1、UNKNOWN0、真实Claude0次。

### ARCH-002P-E — CLAIMED 崩溃后 fenced takeover 协议

- 状态：**INVESTIGATING**
- 优先级：High（商业连续性增强；不替代当前永久at-most-once安全契约）。
- 问题描述：当前operation claim无owner/fence/expiry且无TTL；创建者在claim后、provider begin前崩溃时，同一operation会永久409。Security Reviewer建议支持严格过期后的fenced takeover，避免单次操作永久卡住。
- 证据：独立架构裁决确认该问题真实，但不是ARCH-002P-D现有“宁可固定码不可用、不得重复Claude”验收；直接加入owner/fence会改变DynamoDB数据模型、旧记录兼容和滚动发布语义，旧实例会忽略新字段，因此不能塞入D1小修或混合版本滚动。
- 根因是否确认：是；属于既有at-most-once设计的可用性取舍，不是D1竞态的同一根因。
- 涉及文件：后续`gateway/control_store.py`, `gateway/dynamodb_control_store.py`, `gateway/claude_gateway.py`, 协议/迁移/故障测试与runbook；可能需要blue/green或full drain，不改业务数据库。
- 风险：错误takeover可能在原provider已开始时触发第二次Claude；legacy CLAIMED、时钟偏移、事务响应丢失和混合版本都必须fail-closed。
- 执行代理：Protocol Designer/Repository Explorer先只读设计；根因与兼容方案审完后才指定单一Implementation Agent。
- 验证代理：独立Security/Chaos + DynamoDB Protocol Verification Agents。
- 验收标准：claim创建与owner/fence/expiry原子绑定；只允许严格过期且无provider-start证据的CLAIMED takeover；begin同时校验OP与global lease owner/fence；provider-start及终态永不takeover；并发恢复恰1 winner、旧owner永久失效；legacy记录默认隔离；精确过期/时钟偏移/after-apply/重启/迁移全覆盖；禁止旧新协议混跑。
- 是否需要用户决定：进入云端blue/green/full-drain实施前需要单列窗口和资源预算；当前只读设计不需要。
- 是否涉及真实外部调用：当前否；未来Staging故障演练需另列范围，真实Claude默认0次。
- 是否已部署到 Render：否。

### CAP-001 — 1000在线用户与商业首阶段100个同时AI任务

- 状态：**INVESTIGATING**
- 优先级：Critical（商业上线容量门禁）。
- 问题描述：商业上线首阶段已由产品负责人确认必须可靠受理100个用户同时提交AI任务，Claude或Kimi均可；未来目标为1000人同时使用AI。这里的“同时使用”表示100个业务任务都能及时受理、持久排队、显示进度、断流恢复并最终得到可审计终态，不要求100个请求在同一毫秒直接冲击供应商。另保留1000在线会话的独立静态/API容量目标，二者不得混为同一验收。
- 证据：当前Staging静态前端由CDN提供；主API为单Starter/单worker并挂载持久磁盘，Render不允许该服务水平扩容；Staging PostgreSQL为Free 256MB/0.1 CPU/100连接；无生产持久队列。Gateway当前全局Claude并发2、RPM30，即使Render扩至4副本也仍只允许全局2个provider lease。一次五Agent诊断通常包含4个专家并行调用和至少1个仲裁调用，单用户操作会消耗至少5个provider leaf，历史真实操作约需数分钟。2026-07-14 Anthropic Console只读核验当前Organization为Scale tier，NoteAI所用Sonnet 4.x与Haiku 4.x各为10,000 RPM、10M ITPM（不含多数cache reads）和2M OTPM，月度消费门禁US$5,000；因此当前第一瓶颈是NoteAI队列/Worker/自设并发与Token实测，不是API Key数量。Kimi真实配额仍须从Moonshot控制台/官方响应头读取，不猜测数值。
- 根因是否确认：是；现有架构首先按功能正确性与安全边界稳定化，尚未建设Alibaba生产主系统的可水平扩容API/worker、供应商无关持久队列、背压、容量SLO及100任务合成压测。
- 涉及文件：Alibaba生产IaC、API/worker拆分、SMQ/MNS队列适配、持久AI job/阶段/终态表、SSE恢复、数据库连接池、限流/排队提示、容量测试与监控；`ARCH-002P-D`只负责Claude Gateway多实例可靠性，不得代替整套系统容量验收。
- 风险：若把在线人数或供应商API Key数量误当吞吐证明，少量同时AI任务即可形成数分钟排队、429或超时；SMQ/MNS为至少一次投递，若缺少数据库claim/fence/idempotency会重复调用AI或重复扣费；直接提高Gateway/Kimi并发还可能触发供应商RPM/ITPM/OTPM、加速限制、费用和数据库压力。
- 执行代理：Repository/Capacity Explorer + Render/DevOps Reviewer；后续单一Capacity Implementation Agent按API/worker/queue分包实施。
- 验证代理：独立Load/Resilience + Billing/FinOps Verification Agent。
- 验收标准：零AI合成验证1000在线会话与100个同时AI任务；100个任务全部在2秒内返回持久`job_id`和已受理/排队状态，0丢任务、0重复provider、0重复扣费；API/worker可水平扩容、持久队列与背压生效、断流/刷新/Worker重启可恢复；Claude/Kimi任一限流或不可用时只对可证明未dispatch的任务安全排队或切换；数据库连接、CPU、内存、5xx、队列深度/最老年龄、受理/排队/provider/端到端P50/P95和逐任务成本均达标；再用严格费用上限的小样本真实模型校准，不以副本数或API Key数量代替端到端容量证据。
- 是否需要用户决定：100个同时AI任务的商业首阶段目标已确认；未来1000个同时AI为扩展目标。仍需在创建付费阿里云资源前确认地域/规格/月预算，在真实AI容量采样前确认次数和人民币上限；自动提高付费规格或供应商消费门禁必须再次获批。
- 是否涉及真实外部调用：当前只读Render/代码审计；后续先零AI合成压测，真实AI容量采样另列次数和人民币上限。
- 是否已部署到 Render：否；Alibaba生产主系统也尚未创建。

### CAP-001A — 供应商无关的持久AI任务控制面

- 状态：**IMPLEMENTING**
- 优先级：Critical（100个同时AI任务的第一实施包）。
- 问题描述：现有Analyze/Generate/Chat长任务由API请求进程和进程内队列直接运行，Claude/Kimi路由、积分claim、SSE与最终结果缺少一个可跨进程/重启恢复的业务job真相；无法先可靠受理100个任务再按受控供应商容量执行。
- 证据：现有`idempotency_requests`已具备request-id、payload hash、一次扣费/退款和保守lease原语，可作为业务入口防重基础；但仓库未发现生产AI job队列、outbox、Worker claim/fence、阶段事件/结果回放或DLQ。阿里云SMQ/MNS提供至少一次投递、最长30秒长轮询、可见性超时续租和死信队列，适合作为唤醒通道，但重复投递要求数据库job claim/fence继续作为唯一执行真相，消息只允许携带无内容的`job_id`。
- 根因是否确认：是；缺失的是API/执行解耦和durable job状态机，不是供应商API Key数量。
- 涉及文件：预计新增`model/ai_operations.py`, `model/task_queue.py`, `model/ai_worker.py`、PostgreSQL/SQLite增量migration、API status/result/SSE replay路由及聚焦并发/故障测试；最小复用`model/idempotency.py`, `model/model_router.py`, `model/billing.py`，不在首包修改支付或Gateway协议。V1先由PostgreSQL `FOR UPDATE SKIP LOCKED`、lease、fence和heartbeat承担权威队列；预留`TaskQueue`接口，后续只有在transactional outbox闭环后才接SMQ/MNS/RocketMQ无内容`job_id`唤醒消息，避免数据库/消息双写丢单。
- 风险：至少一次消息重复投递、claim后崩溃、provider已开始但回执丢失、退款与结果错序、Prompt进入消息/日志、Claude/Kimi不安全fallback。首包必须保持provider调用0，用FakeProvider锁定状态机后再接真实路由。
- 执行代理：单一Capacity Implementation Agent；数据库migration、API/Worker和账务共享调用链必须串行，不与支付Implementation并行。
- 验证代理：独立Database/Concurrency/Billing/Security Verification Agent。
- 验收标准：同一用户/request-id/payload只生成一个job并只扣费一次；100个并发提交全部在2秒内返回job_id；消息仅含job_id/固定枚举，Prompt/正文/图片/Token/Secret为0；重复消息/Worker崩溃/可见性续租/过期lease/DLQ/数据库短断下provider与退款均恰好一次或进入可对账不确定态；结果和安全结构化解释可按owner恢复；SQLite/PostgreSQL、100任务FakeProvider、全量和Production Readiness通过。
- 是否需要用户决定：实现本地状态机和FakeProvider不需要；新增阿里云SMQ/MNS、migration应用、真实Claude/Kimi或改变结果保留期需要。
- 是否涉及真实外部调用：第一代码包否；云端集成会创建SMQ/MNS和数据库记录，真实AI保持0直至独立验证通过。
- 是否已部署到 Render：否；目标运行于阿里云Production，Staging集成环境另行确认。

### CAP-001A1 — 持久AI任务账本与安全claim基础层

- 状态：**READY_TO_VERIFY**
- 优先级：Critical（CAP-001A首个串行代码包）。
- 问题描述：先建立不接API、不调用供应商、不扣费的持久任务状态机与数据库claim/lease/fence基础层，为后续API受理、独立Worker和100任务合成压测提供唯一执行真相。
- 证据：现有PostgreSQL migration最高为`0006_model_usage_records.sql`，SQLite schema由`model/db.py`维护；仓库尚无`ai_operations`、阶段事件、provider attempt或跨Worker安全claim。容量、DevOps和FinOps三路只读审查一致确认应先完成数据库权威任务层，消息系统不得先成为业务真相。
- 根因是否确认：是。
- 涉及文件：最小新增`model/migrations/postgres/0007_ai_operations.sql`、`model/ai_operations.py`、`model/task_queue.py`和聚焦测试；为保持SQLite测试/本地兼容，最小更新`model/db.py`。本包不修改`model/api.py`、`model/billing.py`、`model/model_router.py`、Gateway、前端、支付或部署配置。
- 风险：状态迁移过宽会造成重复执行；lease到期边界、旧fence写入和未知provider dispatch结果若处理错误会产生双调用。本包必须默认保守：旧owner失去fence后不能写终态，provider是否已开始不明时不得自动重新执行。首次独立验证另确认一个High阻断：当持续存在queued backlog时，stale `provider_started`只在无可claim任务时才隔离，可能长期卡在running并阻塞对账；另有调用方自定义operation ID可携带非opaque内容的Medium硬化缺口，均退回本包修复。
- 执行代理：单一Capacity Implementation Agent。
- 验证代理：独立Database/Concurrency/Security Verification Agent，不接受Implementation Agent自证为VERIFIED。
- 验收标准：SQLite和PostgreSQL schema合同一致；100个合成任务可创建且ID唯一；并发claim同一任务只有一个winner；heartbeat只能由当前lease/fence续期；lease过期后新owner取得更高fence，旧owner无法写阶段/结果；状态只允许固定枚举；事件和attempt仅保存固定枚举、哈希/计数/时间，不保存Prompt、正文、图片、URL、Token、Cookie、Secret或异常原文；聚焦测试、全量单元测试及Production Readiness通过。
- 是否需要用户决定：本地代码与一次性测试数据库不需要；向Staging/Production应用`0007` migration必须再次明确确认。
- 是否涉及真实外部调用：否；FakeProvider和数据库并发测试均为本地零AI、零费用。
- 是否已部署到 Render：否。生产空库已应用`0007`，但应用代码尚未部署；Staging部署状态需在push后另行核对。
- 修改状态/验证进度：实现已提交在`199bf5f`，生产空库已应用`0007`。提交前验证曾通过聚焦/全量/Production Readiness，但按唯一账本规则，仍须由未参与实现的Verification Agent针对当前HEAD复核exact diff、SQLite/PostgreSQL合同、测试结果和云端migration/应用部署边界；完成前不得沿用旧聊天结论标记VERIFIED。

### CAP-001A2 — request-id、扣费与持久job原子受理

- 状态：**READY_TO_FIX**
- 优先级：Critical（100任务快速受理与零重复扣费的第二串行包）。
- 问题描述：将现有付费请求`idempotency_requests`与已验证的`ai_operations`安全绑定，使同一user/operation/request-id/payload只产生一个持久job并只扣费一次；API可在不占用provider执行时返回可恢复job标识，同时保持当前Staging SSE兼容边界。
- 证据：`CAP-001A1`已独立验证数据库任务真相、claim/lease/fence；现有`claim_and_charge()`在单事务内完成幂等claim与扣费，但事务提交后才返回，当前API随后仍在请求进程直接运行AI，且`idempotency_requests`没有已确认的job外键/原子enqueue步骤。若简单在函数返回后另行enqueue，进程崩溃会出现已扣费但无job；若先enqueue再扣费会出现无权执行的幽灵job。
- 根因是否确认：是；三路只读调查确认精确原子插点位于`idempotency.claim_and_charge`的唯一owner判定之后、事务commit之前，但当前`ai_operations.enqueue_operation()`会自开事务，且旧SSE路径没有持久输入/结果引用，不能直接enqueue可执行job。最小稳健方案是新增一对一admission link和transaction-aware enqueue/helper，保持旧SSE完全不接队列；版本化202入口留到持久输入/结果与Worker包。
- 涉及文件：待调查`model/idempotency.py`, `model/billing.py`, `model/api.py`, `model/ai_operations.py`, `model/db.py`、下一PostgreSQL migration、聚焦API/并发/账务测试；本包不得顺带接真实provider、消息队列、支付或修改Gateway。
- 风险：跨事务双写造成已扣费无job或无扣费job；重复request-id创建多个operation；202与现有SSE响应不兼容；退款早于unknown对账；用户越权读取他人job；raw request-id或正文进入任务表。
- 执行代理：调查完成、根因与兼容方案确认后指定单一API/Idempotency Implementation Agent。
- 验证代理：独立Billing/Concurrency/API Contract/Security Verification Agent。
- 验收标准：同user/operation/request-id/payload的20并发提交仅一个owner、一个job和一次扣费；相同key不同payload为conflict且不新建job；事务任一点失败均不会留下收费/job半状态；job只保存owner/request摘要与固定枚举；跨用户不可读取；当前Staging旧SSE路径默认行为不变，生产异步受理通过显式配置/版本边界启用；聚焦、全量、Production Readiness和100任务零AI admission基线通过。
- 是否需要用户决定：本地只读调查与代码测试不需要；向任何Staging/Production应用新migration、改变公开API默认响应或真实扣费/AI调用必须再次确认。
- 是否涉及真实外部调用：调查与首轮本地FakeProvider测试否。
- 是否已部署到 Render：否。

### CAP-001A2A — 原子admission账本与transaction-aware enqueue

- 状态：**READY_TO_VERIFY**
- 优先级：Critical（CAP-001A2首个最小代码包）。
- 问题描述：在不接API/Worker/provider的前提下，新增`idempotency_requests`与`ai_operations`严格一对一admission关联，并提供单事务claim、job enqueue、扣费和usage写入原语；现有同步/SSE `claim_and_charge()`保持原行为且不创建job。
- 证据：Repository Explorer确认当前`claim_and_charge()`在`model/idempotency.py`同一短事务内完成唯一owner与扣费，但A1 `enqueue_operation()`自开事务；Test Finder确认现有测试分别证明一次扣费与独立job安全，却没有跨账本原子性；Database/Security Reviewer建议新增`ai_operation_admissions(operation_id PK/FK, idempotency_request_id UNIQUE/FK, created_at)`，避免共享UUID的隐式无约束关联和SQLite存量ALTER复杂度。
- 根因是否确认：是。
- 涉及文件：最小允许`model/migrations/postgres/0008_ai_operation_admissions.sql`、`model/db.py`、`model/ai_operations.py`、`model/idempotency.py`及新建聚焦测试；不得修改`model/api.py`、`model/billing.py`、前端、Gateway、部署或支付。
- 风险：嵌套事务造成半提交；相同key重试未返回相同job；旧legacy idempotency无link被错误补建job；job/扣费锁序与现有subscription/credits锁冲突；把raw user/request-id写入subject或operation字段；异步admission错误激活请求进程ContextVar。
- 执行代理：单一API/Idempotency Implementation Agent。
- 验证代理：独立Billing/Concurrency/Database/Security Verification Agent。
- 验收标准：新helper中同user/operation/key/payload的20并发仅1条idempotency、1个operation、1条admission、1个enqueued event、1条usage和一次积分扣减，所有重复请求恢复同一job_id；同key异payloadconflict且计数不增；job/link/event/charge任一步注入失败均由数据库事务回滚为0半状态且余额/套餐不变；旧`claim_and_charge()`默认仍不创建job；legacy已有idempotency无link不得补建job；100个不同key零AI admission在2秒内完成且provider attempt为0；owner查询只能通过admission join+user_id，返回allowlist且跨用户/不存在不可枚举；SQLite/0008 schema对等、聚焦/全量/Production Readiness通过。
- 是否需要用户决定：本地代码和一次性SQLite测试不需要；应用`0008`到任何Staging/Production、启用公开202或运行PostgreSQL集成测试需要明确批准。
- 是否涉及真实外部调用：否；不调用provider、不扣真实账户费用。
- 是否已部署到 Render：否。生产空库已应用`0008`，但应用代码尚未部署；本包仍未连接公开API/Worker/provider。
- 提交后验证状态：实现已与CAP-001A1一并提交在`199bf5f`。生产RDS只完成`0008`空结构migration，未导入Staging数据、未扣真实账户费用、未调用AI。须由独立Verification Agent对当前HEAD复核事务原子性、100个零AI admission、跨用户不可枚举、全量回归和部署边界后才可标记VERIFIED。
- 修改状态/独立验证证据：已新增`model/migrations/postgres/0008_ai_operation_admissions.sql`和`tests/test_ai_operation_admission.py`，最小更新`model/db.py`, `model/ai_operations.py`, `model/idempotency.py`；没有修改API、billing、前端、Gateway或部署。独立Verification Agent证明SQLite/0008的一对一NOT NULL/PK/UNIQUE/FK/RESTRICT合同对等，NULL、双向重复和父记录删除均被拒绝；20并发同key仅1 job/link/usage/charge且其余19返回同一job；operation失败、job后billing失败、真实wallet扣减及流水写入后的marker失败均完整回滚余额/订阅/流水和五张admission表；legacy无link不补job，新helper不激活ContextVar且旧helper行为不变；owner allowlist/跨用户不可枚举成立。独立100线程同时admission耗时0.6518秒、100/100成功、provider attempt/model usage/model_calls均0。主代理复跑相关69/69、全量570/570（5个未授权PG既有用例skip）、Production Readiness 48/48、py_compile/diff check通过；未应用0008、未调用AI或外部服务。

### CAP-001A2B — 可恢复输入、结果引用与Worker数据边界

- 状态：**INVESTIGATING**
- 优先级：Critical（公开202与独立Worker之前置门禁）。
- 问题描述：A2A只能原子创建摘要job，尚不能让另一个Worker在重启后取得Analyze/Generate/Chat所需的正文、图片/视频引用、session上下文，也不能持久恢复最终结果；必须定义加密、最小化、TTL、owner隔离的payload/result引用合同，且不持久化原始reasoning。
- 证据：三路只读调查确认现有三条pipeline依赖请求内对象、内存队列、chat session和本地/临时多媒体，A1/A2A表故意只保存hash/枚举/计数；Analyze/Generate图片仍为请求内base64，视频只保留单机约6小时JPEG帧与不绑owner的`video_file_id`，Chat仅按session_id恢复且`mem_prompt`不持久，Generate没有durable result，Analyze完整结果与Chat messages/generate_ctx仍存在现有明文业务表。现有`artifact_loader.py`和`boto3`只服务私有模型下载，不是用户payload put/get/delete/KMS抽象。若现在开放202或Worker，会出现job可claim但无输入，或旧SSE与Worker双跑。
- 根因是否确认：是；生产目标应为PostgreSQL元数据 + 阿里云私有OSS密文对象 + RAM Role短期凭证 + SSE-KMS。产品负责人已决定商业V1采用免费的云产品默认服务密钥而非付费客户自管软件KMS；数据库/消息仍只存opaque object id、owner/operation/purpose、hash/size/MIME枚举、schema/encryption mode/key epoch、状态与TTL，对象key不得包含用户/session/filename，消息只含operation ID。入队保存不可变输入snapshot，首次provider前checkpoint动态memory/fact/market/prompt/model版本，终态只保存递归allowlist后的公开结果；原始reasoning/system prompt/provider envelope永不持久化。不得把V1宣传为BYOK、应用层端到端加密或多用途独立客户自管密钥。
- 涉及文件：待调查Analyze/Generate/Chat请求模型与pipeline、chat/session/notes存储、多媒体缓存、OSS/S3配置、未来payload/result metadata migration、storage interface、worker loader和脱敏测试；本调查不修改现有路由或调用provider。
- 风险：明文正文或图片进入队列表/日志；对象URL可枚举；KMS/OSS故障造成不可恢复job；TTL先删除输入但job仍排队；跨用户读取；raw reasoning长期持久化；中国大陆到新加坡Claude跨境数据边界未披露。
- 执行代理：Repository/Data Flow Explorer + Security/Storage Reviewer + Test Finder；根因/合同确认后单一Implementation Agent。
- 验证代理：独立Security/Recovery/Retention/Worker Contract Verification Agent。
- 验收标准：为三类入口列出最小必要输入与禁止字段；小文本与大媒体均只通过加密/私有对象引用恢复，队列表/消息/日志不含正文、base64、URL、Prompt、reasoning、Cookie、Token或Secret；owner与用途绑定、完整性hash、TTL/删除顺序、KMS/OSS失败终态和结果allowlist明确；FakeStore在进程重启、重复load、过期、篡改、跨用户和100job下通过，之后才允许版本化202/Worker实施。
- 是否需要用户决定：是。只读调查与本地FakeStore/interface/serializer/metadata合同不需要；需要产品确认输入/结果/unknown/孤儿对象保留期、Chat snapshot策略、provider成功但结果存储失败的对账/退款语义，以及跨境策略。新增官方`alibabacloud-oss-v2`/credentials依赖、创建OSS/KMS/CMK/RAM/lifecycle/监控付费资源、应用migration或实际上传用户数据需明确批准。
- 是否涉及真实外部调用：调查否；任何OSS/KMS创建或上传另行批准。
- 是否已部署到 Render：否。
- 推荐但待确认的保留期：未完成/孤儿上传24小时；失败/取消输入24小时；成功输入终态后24小时且硬上限7天；`outcome_unknown` 7天；最终公开结果30天；视频抽帧/临时衍生物最多6小时；Prompt、raw reasoning、provider原始request/response为0天。删除顺序固定为DB `delete_pending`立即不可读 → OSS delete/HEAD确认 → DB `deleted` tombstone，不能先删元数据。
- 推荐但待确认的跨境策略：原始图片/视频/base64/EXIF/OSS URL只在阿里云华南由Kimi处理；仅在隐私政策/法务允许的`minimized_text_allowed`模式下，将完成脱敏、最小必要的文本输入/摘要通过Singapore Gateway发送Claude。每个job固定记录跨境枚举，Worker不得临时改变；Claude输出仅保存公开结果与最小usage，不保存reasoning。

### OPS-003 — 商业AI容量、费用监控与升级触发

- 状态：**INVESTIGATING**
- 优先级：Critical（商业上线持续运行门禁）。
- 问题描述：上线后必须同时监控Claude与Kimi的组织/账号配额、实际速率、Token、费用、余额、429/5xx、队列深度和任务延迟；接近或超过门禁时由NoteAI发起有证据的升级建议或工单，而不是静默失败或盲目创建API Key。
- 证据：Anthropic当前真实Scale配额已核验且Console支持Rate Limit/Usage/Cost信息；当前仓库有逐模型usage/cost和部分Admin汇总，但没有统一provider-capacity快照、队列SLO、预测耗尽时间、分级告警或升级Runbook。Kimi配额值尚未取得受控官方证据。
- 根因是否确认：是；缺失持续容量治理和升级工作流，不是单次部署缺陷。
- 涉及文件：未来provider quota采集器、队列/Worker/Gateway指标、SLS/CloudMonitor告警、Admin容量页、升级Runbook与脱敏测试；不得保存API Key、完整请求或供应商异常正文。
- 风险：自动升配造成失控费用；只看RPM忽略ITPM/OTPM/余额；Kimi/Claude一方过载时形成雪崩fallback；告警包含用户内容或Secret。自动化只能告警、排队、降载和执行已批准范围内的实例伸缩，不能自动提高供应商消费门禁或购买新付费规格。
- 执行代理：Monitoring/FinOps Implementation Agent，在CAP-001A指标合同确定后实施。
- 验证代理：独立SRE/FinOps/Security Verification Agent。
- 验收标准：至少采集provider/model维度RPM/ITPM/OTPM或官方可用等价指标、429/5xx/timeout、Token/成本/余额、队列depth/oldest age、active leases、任务四段P50/P95/P99；达到70%持续5分钟Warning、85%持续3分钟High、95%或预测15分钟内耗尽Critical（最终阈值由真实压测校准）；自动生成含当前值/上限/增长率/预计耗尽/建议新上限/费用影响/回滚方案的升级建议；费用或供应商配额提升只在用户批准后执行；Claude/Kimi任一故障时无重复provider和重复扣费。
- 是否需要用户决定：监控与告警实施不需要；告警渠道、自动扩容预算上限、任何供应商/云资源付费升级需要。
- 是否涉及真实外部调用：会持续读取供应商/阿里云非Secret监控数据并发送告警；申请升级或改变付费资源是外部状态变更，必须按授权边界执行。
- 是否已部署到 Render：否；业务监控运行于阿里云，Render Gateway只暴露白名单聚合指标。

### PROD-001A — Adapay 商户准入与三通道能力确认

- 状态：**INVESTIGATING**
- 优先级：Critical。
- 问题描述：用户已选定 Adapay，但公开资料不能确认 NoteAI 的 AI SaaS＋不可提现积分是否准入，也不能确认 PC/H5 同时支持支付宝、微信用户主扫和银联统一收银台。
- 证据：Adapay 官方资料明确企业和个体工商户材料路径、Test/Live Key、支付/退款/查单/账单能力；同时公开禁入说明包含卡密/虚拟交易类，且当前渠道表未明确微信 PC 用户主扫与普通浏览器 H5。
- 根因是否确认：是；属于商户审核和产品权限的外部不确定性，不是代码缺陷。
- 涉及文件：业务说明、套餐页、支付页、用户协议、隐私政策、退款/对账规则及 Adapay 入网材料；不记录身份证、银行卡或密钥内容到仓库。
- 风险：未确认即开发可能最终无法开通所需渠道；错误描述积分可能被归入禁入业务。
- 执行代理：Adapay Vendor Reviewer（Tesla）已完成官方资料复核；后续由用户/商务提交材料并取得合同、邮件或盖章方案确认。
- 验证代理：主 CTO + 独立 Payment/Compliance Reviewer 核对书面确认是否覆盖业务类目、三通道、费率、结算、退款、签名规范、账单和SLA。
- 验收标准：Adapay 书面确认 NoteAI 业务准入、MCC/类目、支付宝PC/H5、微信PC用户主扫/H5、银联H5/统一收银台、费率/限额/结算/保证金、退款、2026签名规范、对账单字段和生产支持。
- 是否需要用户决定：是；需选择企业或个体工商户主体并提供受控申请材料。
- 是否涉及真实外部调用：是；联系/申请 Adapay 会改变外部商务状态，但当前代理未代为提交。
- 是否已部署到 Render：否。

### PROD-001B — 商品合同、支付核心账本与整数金额

- 状态：**TODO**
- 优先级：Critical。
- 问题描述：现有充值/套餐配置可复用，但没有正式支付订单、事件收件箱、交易、权益、现金退款和对账账本；当前套餐自然月边界也不适合直接承载真实购买。
- 证据：只读仓库审计确认 `/billing/topup` 与 `/billing/upgrade` 是测试入口；`payment_ref` 不是支付订单；AI失败返积分不是现金退款；钱包只有汇总余额，不能按原订单退款。
- 根因是否确认：是。
- 涉及文件：预计 `model/billing.py`, `model/db.py`, 新增 `model/payment_service.py`, PostgreSQL `0007` 起的增量 migration、SQLite/PostgreSQL/API/并发测试。
- 风险：重复发权益、金额浮点误差、月底购买周期异常、SQLite/PostgreSQL 漂移和迁移失败。
- 执行代理：Payment Rules/Repository Reviewer（Ampere）已完成只读差距映射；产品合同确认后指定单一 Payment Ledger Implementation Agent。
- 验证代理：独立 Billing/Database/Concurrency Verification Agent。
- 验收标准：服务端商品快照为唯一价格源；金额只用整数分；订单/事件/交易/权益/退款/对账唯一约束齐全；迁移重复执行安全；并发重复事件只能产生一份权益；测试充值在生产保持关闭。
- 是否需要用户决定：是；需确认 V1 套餐周期、是否自动续费、退款窗口和现有套餐价格是否保持。
- 是否涉及真实外部调用：本地与临时PostgreSQL验证不需要；Staging migration 需要批准。
- 是否已部署到 Render：否。

### PROD-001C — Adapay 适配器、下单、验签回调与原子履约

- 状态：**TODO**
- 优先级：Critical。
- 问题描述：需要实现创建/查询/关闭支付、回调验签、状态反查及支付成功后的原子积分/套餐发放；浏览器返回页不能改变支付状态。
- 证据：当前仓库无 Adapay 客户端或 webhook；现有 `topup_credits()` 多步写入不能直接作为回调履约事务。
- 根因是否确认：是。
- 涉及文件：预计新增 `model/adapay_client.py`, `model/payment_service.py`，最小修改 `model/api.py`, `model/billing.py`, env模板、依赖和安全/并发/API测试。
- 风险：伪造回调、错App/环境/金额、重复通知、迟到通知、数据库中断、SDK老旧依赖和5秒回调窗口。
- 执行代理：PROD-001B VERIFIED 后指定单一 Payment Integration Agent；不得与账本/迁移代理并行修改同一调用链。
- 验证代理：独立 Security + Billing/Concurrency Verification Agent。
- 验收标准：验签失败、错金额/币种/App/环境、重复/并发通知均不发权益；有效事件持久化并幂等履约；未知终态主动查单；客户端跳转不能入账；Secret和完整回调不进入日志。
- 是否需要用户决定：新增官方SDK或生产依赖前需要；若采用受审计HTTP实现则需先完成兼容审查。
- 是否涉及真实外部调用：先用固定夹具离线验证；随后只使用 Adapay Test/Mock，禁止真实扣款。
- 是否已部署到 Render：否。

### PROD-001D — 积分批次、现金退款与审批

- 状态：**TODO**
- 优先级：Critical。
- 问题描述：需要把付费积分绑定原支付订单，支持消费归属、失败恢复原批次、退款冻结和原路现金退款，并与现有业务返积分严格区分。
- 证据：当前 `credits.balance` 只有汇总余额，现有 refund 语义是 AI 失败返积分；无法证明某订单仍有多少可退款积分。
- 根因是否确认：是。
- 涉及文件：预计 credit lot/consumption/reversal 增量 migration、`model/billing.py`, payment refund service、Admin审批与权限测试。
- 风险：重复退款、退款后继续消费、普通业务失败误调用支付退款、管理员越权和负余额掩盖。
- 执行代理：单一 Billing/Refund Implementation Agent，必须在 PROD-001B/C 后串行实施。
- 验证代理：独立 Billing/Database/Security Verification Agent。
- 验收标准：累计现金退款不超原实付；退款申请先冻结，成功扣除、失败解冻；重复回调不重复扣积分；AI失败只恢复原消费批次且绝不调用Adapay；现金退款有经办/审批审计。
- 是否需要用户决定：是；需批准最终退款政策、审批权限与负余额处理规则。
- 是否涉及真实外部调用：Test/Mock 阶段；生产最小退款需另行批准。
- 是否已部署到 Render：否。

### PROD-001E — T+1 对账、差错补单与真实财务后台

- 状态：**TODO**
- 优先级：Critical。
- 问题描述：当前管理端收入是估算，无法与渠道支付、退款、手续费和银行结算进行三方对账。
- 证据：现有管理端以有效套餐人数乘当前价格估算订阅收入；仓库没有 Adapay 账单下载、对账批次或差错账本。
- 根因是否确认：是。
- 涉及文件：预计新增 reconciliation service/worker、Admin API/UI、对账脚本/调度和账单夹具测试；正式环境调度位于阿里云，不沿用 Render 全栈 Cron。
- 风险：漏单误补、金额差异被静默抹平、估算收入被误当现金收入、账单格式变化。
- 执行代理：单一 Reconciliation Implementation Agent；必须在支付与退款账本稳定后实施。
- 验证代理：独立 Finance/Data Quality + Security Verification Agent。
- 验收标准：北京时间T+1逐笔核对支付、退款、手续费、净结算和银行批次；补单先查单且幂等；金额/身份差异绝不自动抹平；Critical差错为0才关闭批次；后台收入来自支付账本而非人数估算。
- 是否需要用户决定：需确认对账责任人、日/月关账时点和告警渠道。
- 是否涉及真实外部调用：Test阶段用夹具；生产需下载账单并产生持续任务成本。
- 是否已部署到 Render：否。

### PROD-001F — Adapay Test/Mock、三通道认证与生产切换

- 状态：**TODO**
- 优先级：Critical。
- 问题描述：支付代码完成后仍需在完全隔离的 Test/Mock 环境验证三通道、退款、查单、丢回调、重复回调和对账，再执行受控真实小额认证。
- 证据：Adapay 官方区分 Test/Live Key；部分依赖微信客户端的能力不能由 Mock 完整覆盖。
- 根因是否确认：是；属于外部认证与上线门禁。
- 涉及文件：测试计划、Staging支付配置、生产Secret/回调/DNS配置、三通道验收和回滚运行手册。
- 风险：Test/Live 环境串用、真实资金误操作、回调地址错误、生产停新单时误停回调/退款/对账。
- 执行代理：Payment QA/DevOps Agent 按主 CTO 限额执行；真实资金步骤只由获授权人员操作。
- 验证代理：独立 Payment Release Verification Agent。
- 验收标准：Test Key只写Staging且 `prod_mode=false`；Live Key只写Production且强制 `prod_mode=true`；三通道成功/失败/取消/过期/重复/错签名/错金额/全额与部分退款/对账全部通过；首次真实小额支付退款和首个T+1账单零Critical差错。
- 是否需要用户决定：是；真实小额支付、生产密钥、回调域名和正式开放收费均需再次批准。
- 是否涉及真实外部调用：是，会涉及Adapay Test及最终真实资金。
- 是否已部署到 Render：否；目标生产支付运行在阿里云主系统，不在 Render Gateway。

### PROD-002A — 阿里云华南生产基础设施、域名与监控

- 执行进展（2026-07-14 域名采购批准后）：产品负责人已明确批准按最终采购清单推进，正式主域锁定为 `noteaipro.cn`，并防御性注册 `noteaipro.com`。登录态万网购买前页面再次确认 `.cn`/`.com` 仍可注册，1年实付分别为 ¥38/¥85，自动续费关闭，15元AI建站附加项未勾选，合计 ¥123，未超过5%价格门禁。两份订单尚未提交或付款，账号当前没有可用的域名持有者信息模板；创建模板需提交企业名称、证件和联系人敏感资料，且必须与后续ICP备案主体一致，因此采购暂停在企业信息模板门禁，等待产品负责人在阿里云页面亲自创建并完成实名审核。未产生域名费用，未创建DNS/TLS/备案资源。

- 独立验收（2026-07-16）：阿里云域名列表已确认 `noteaipro.cn` 与 `noteaipro.com` 均注册成功且状态为“正常”，有效期分别为2026-07-16至2027-07-16、2026-07-15至2027-07-15；两行自动续费开关均未显示为开启。域名采购因此从“仅用户自报”升级为云端可核验证据。与此同时发现主体不一致：主域 `.cn` 显示为企业持有者，防御域 `.com` 显示为个人持有者；信息模板页当前还显示“无模板可用”。产品负责人于2026-07-16明确接受该主体差异：`.com` 只作个人持有的防御性占位，不承载生产流量、不参与ICP备案、不作为企业主体一致性的上线门禁；未来如需启用品牌跳转、对外业务或纳入企业资产，再另立过户任务。该风险接受不改变 `.cn` 企业持有、唯一生产主域和ICP备案主体一致要求。未修改DNS记录、未购买企业DNS/TLS/备案资源。

- 企业DNS付款前复核（2026-07-16）：在产品负责人现有阿里云登录会话中进入官方公网权威解析购买页，配置且仅配置 `noteaipro.cn` 一个可绑定域名、企业旗舰版、DNS攻击基础防御、1年，自动续费未勾选。实时应付金额为 **¥1,168.00**，与批准预算一致且未触发5%价格门禁；`noteaipro.com` 未加入购买范围。页面已停留在“立即购买”前交由产品负责人接手，未点击购买、未创建DNS实例、未修改任何解析记录、未产生费用。下一步是由产品负责人完成付款，付款后独立核验实例状态和主域绑定；正式解析记录与DNS切换仍须单独批准。

- 企业DNS购买与主域绑定验收（2026-07-18）：产品负责人完成付款后，主控在阿里云登录态独立核验包年包月实例 `dns-cn-jpu4vjg1501` 为“企业旗舰版 · 防护中”，到期时间 `2027-07-19 00:00:00`，并在已明确授权范围内把 `noteaipro.cn` 绑定到该实例。阿里云提交结果为“绑定成功1个，绑定失败0个”；刷新实例页显示绑定域名 `noteaipro.cn`，公网权威解析页显示该域套餐为企业旗舰版、防护中、状态正常，当前记录数为0。公网交叉核验确认权威NS仍为 `dns15.hichina.com` / `dns16.hichina.com`，根域、`api`、`admin`、`www` 均无公开A/CNAME，不存在需要迁移的在线业务地址。生产解析尚未创建：仓库与云端均没有可安全使用的生产ALB/WAF入口，NAT EIP仅用于出站，Render地址仅为Staging；严禁用占位IP、NAT EIP或Staging域名冒充生产目标。待真实ALB/WAF入口和TLS证书部署完成后，再创建并验证 `@`、`api`、`admin` 记录；`www` 与公开 `gateway` 未获产品/架构确认，不创建。电子邮箱绑定提示按产品负责人指示不纳入本步骤。

- 正式TLS购买、独立性与三证签发验收（2026-07-18）：在产品负责人明确批准接受证书服务协议和手动维护确认后，主控在阿里云登录态分别配置 `noteaipro.cn`、`api.noteaipro.cn`、`admin.noteaipro.cn` 三份 Rapid DV 正式单域名一年订阅；每份均关闭自动托管、归入 `NoteAI Production` 资源组并标记 `project=noteai`、`environment=production`。实时首购优惠为 **¥291/份**，三份采购清单总计 **¥873**，低于原批准的¥1,455预算。操作中发现同页继续添加会把上一域名残留进订单摘要，主控在提交前停止并为 `admin` 使用全新购买页，避免误合并为多域名证书。产品负责人完成付款后，阿里云支付页显示支付成功；SSL证书管理控制台独立显示3个不同订阅实例，分别绑定上述三个域名，且每个均为 `Rapid RSA_2048`、`DV 单域名`，因此购买与实例独立性验收通过。产品负责人随后在阿里云页面亲自选择CA联系人/所在地并依次提交三张申请；自动DNS验证成功。最新SSL证书列表显示三张证书均为 **已签发**，有效期均为2026-07-18至2027-02-02；每张证书由CA同时附带对应的 `www` 名称。订阅有效期2027-07-19不等同于当前证书有效期，必须以2027-02-02为到期门禁，并最迟在2027-01-03启动换发。三张证书当前“已部署”列均为 `--`：购买、申请、DNS验证与签发阶段已闭环，但尚未绑定生产ALB，不能把“已签发”宣称为“生产HTTPS已上线”。下一步是先完成生产后端健康检查与ALB，再绑定证书并对根域、API、Admin分别执行SNI/证书链/HTTPS回归；签发后由阿里云自动清理验证TXT，不手工创建业务A/CNAME占位记录。

- 防御域主体迁移进展（2026-07-16）：产品负责人报告 `noteaipro.com` 已迁移到与 `noteaipro.cn` 相同的公司名下。该报告消除了产品侧的主体差异待办，且不再阻塞生产主线；但按照任务账本的独立验证规则，在阿里云域名列表再次显示两域相同企业持有者之前，本项记录为“用户完成、待只读复核”，不得冒充云端 VERIFIED 证据。即使复核通过，`.com` 首发仍只作防御性占位，不购买第二份企业DNS、不承载生产或备案。

- 补充证据（2026-07-14 正式域名/TLS/备案ECS最终报价）：仅通过阿里云官方文档及已登录控制台/活动页读取结算前价格，没有点击购买、创建证书、提交备案或修改云资源。登录态确认 `noteaipro.cn` 与 `noteaipro.com` 当前均可注册，首年分别 ¥38/¥85、续费分别 ¥42/¥95；推荐 `.cn` 为唯一正式主域，`.com` 仅防御性注册，企业旗舰DNS加基础防御 ¥1,168/年只购买一份用于主域。根域、`api`、`admin` 三个公开入口采用三份 Rapid DV 正式单域名一年订阅，2026-05-06后目录价 ¥485/份、合计 ¥1,455/年；个人测试证书仅90天且官方不建议正式业务使用。一年订阅的单张证书约半年，必须按30/20/15/7天门禁完成换发与ALB部署，暂不购买额外证书托管。备案核心文档要求中国内地包年包月ECS累计大于3个月并有公网带宽，故全新恰好三个月不作为安全资格。登录态官方99计划显示2核2GiB、3 Mbps、40 GiB、¥99/年且新老用户限1台；推荐作为最小化备案专机，支付后仍须在“可备案实例管理”确认资格。若结算时99计划不可用，回退为一台既有API ECS首月后续费3个月并加1 Mbps公网，追加现金参考 ¥916.20、上限 ¥950。正式域名/TLS/备案ECS/DNS这一包首年现金为 ¥2,845；完整首笔预付基线 ¥5,848.52，首月含按量计提参考 ¥6,458.80，持续1 ALB LCU为 ¥6,489.04。完整首年月均规划约 ¥3,850.88，持续1 LCU约 ¥3,881.12；备份不超免费额度可减 ¥36/月。价格或备案资格超出门禁时必须暂停，尚未产生费用。

- 补充证据（2026-07-14 SMQ/MNS/Secret/DNS/备案初步报价，域名/TLS/备案ECS部分已由上方最终报价取代）：仅查阅阿里云官方计费/产品说明和登录态只读页面，没有购买、开通或创建付费资源。SMQ是原MNS的现产品名；华南1队列资源费¥0.50/队列/天，一个工作队列加一个失败/死信队列约¥30–31/月；普通请求每账号每月前2,000万次免费，100消费者30秒长轮询加每月100万任务的保守情景约1,164万次，首发请求费预计¥0。SMQ仅在transactional outbox闭环后传无内容`job_id`，PostgreSQL claim/lease/fence仍是唯一执行真相。免费默认服务密钥不能保存应用Secret；V1使用ECS RAM Role/STS和受限部署注入，增量¥0，软件KMS基础¥2,499/月加最低100个凭据¥249/月、合计约¥2,748/月，继续延期。企业旗舰DNS加基础防御合计¥1,168/主域/年，免费DNS不作为生产目标。该轮形成的不另购备案ECS和活动域名示例价仅为初步方案，已经被登录态确认的99计划备案专机与 `noteaipro.cn`/`.com` 实时报价取代；不得继续引用旧示例价或旧月均总额作为最终采购依据。

- 补充证据（2026-07-14 KMS/WAF/RDS备份-PITR）：仅通过阿里云官方计费/恢复文档和登录控制台进行只读复核，没有购买、开通或创建付费资源。产品负责人已明确选择免费默认服务密钥作为商业V1方案，以控制起步成本：RDS/OSS仍保持云产品服务端静态加密，增量¥0/月，但不得宣称多用途隔离、BYOK、应用层加密或完整客户自管密钥体系。中国内地软件密钥管理实例¥2,499/月已标记为延期升级项，仅在企业/监管合规、BYOK、应用层密码运算、独立密钥域或合同轮换要求出现时重新立项；RDS未来换钥会重启并短暂闪断，OSS换钥只覆盖新对象，历史对象需复制重加密。WAF 3.0按量版为¥0.05/SeCU/小时：空实例0.5 SeCU/小时约¥18/月、存在防护对象的默认核心规则3 SeCU/小时约¥108/月、每小时有且不超过5,000次请求的基础流量约¥36/月、峰值不超过1,000 QPS无QPS峰值费；加上WAF增强版ALB相对已预算标准版ALB的¥59.76/月差额，首发单防护对象规划增量约¥221.76/月。Bot/API安全/自定义规则、异常流量和WAF日志另计，开通前必须设置费用/QPS告警。200 GiB RDS云盘的同地域快照数据+日志备份免费额度为400 GB，超额单价¥0.00025/GB/小时（约¥0.18/GB/月）；推荐每日数据备份、数据与日志均保留14天以获得14天PITR窗口，预算暂按200 GB超额预留¥36/月，跨地域备份和恢复临时实例另计。加入既有OSS/SLS情景、WAF及RDS预留后，当前选定方案约¥3,583.80/月，持续1 LCU约¥3,614.04/月；若备份不超过400 GB可减¥36/月。软件KMS不纳入V1预算，KMS/WAF/RDS/PITR均未创建或启用，未产生费用。

- 补充证据（2026-07-14 OSS/SLS）：官方实时价格页与计费说明已交叉复核，仅进行只读报价，没有创建付费资源。OSS华南1按量付费标准型LRS为¥0.12/GB/月、ZRS为¥0.15/GB/月；同地域ECS内网流出免费，公网流出00:00–08:00为¥0.25/GB、08:00–24:00为¥0.50/GB，PUT/GET首发量级处于月免费请求额度内。首发采用不预购资源包的保守情景：100 GB标准ZRS约¥15/月，加100 GB高峰公网下载约¥50/月，OSS约¥65/月；私有临时上传、模型制品、前端资产三个用途须隔离，SSE-KMS费用另计。SLS按写入数据量模式¥0.40/GB且包含30天保存；只采集固定错误码、计数、阶段时延、队列和资源指标，按1 GB/天、30天估算约¥12/月，100 GB/月压力参考约¥40/月。付费用户与稳定用量尚未形成，当前不购买不可退的年度节省计划。未创建OSS Bucket、KMS/CMK、SLS Project/Logstore、告警或资源包，未产生费用。固定基础费仍约¥3,249.04/月；加入OSS/SLS保守规划情景约¥3,326.04/月，若持续使用1 ALB LCU约¥3,356.28/月；NAT CU、EIP出网、KMS、WAF、备份超额等仍未计入。

- 补充证据（2026-07-14 NAT/EIP）：官方计费文档与登录后的华南1控制台已交叉核验。用户明确批准后，控制台已成功创建独立的 `AliyunServiceRoleForNatgw`；刷新后原角色门禁消失，该角色只供 NAT 网关管理托管弹性网卡等网络资源，不是应用运行时角色。购买页已配置但未提交：公网 NAT 网关 `noteai-prod-nat`、生产资源组与 VPC、可用区 C 应用交换机 `noteai-prod-app-c`（`10.42.10.0/24`），新购 BGP（多线）EIP、200 Mbps 峰值上限、按使用流量计费，标签 `project=noteai`、`environment=production`、`role=egress`。登录账户实时报价为公网 IP 保有费 ¥0.02/小时、NAT 实例费 ¥0.196/小时、NAT CU 费 ¥0.196/CU；前两项按720小时折算约 ¥155.52/月，CU 与出网流量另计。官方深圳 BGP 多线流量参考价为 ¥0.80/GB；200 Mbps 是按流量计费模式的上限峰值，不是固定带宽承诺，也不会按200 Mbps直接收取固定带宽费。未点击“立即购买”，未创建NAT或EIP，未产生实例费用。

- 状态：**IMPLEMENTING**
- 优先级：Critical。
- 问题描述：仓库没有阿里云生产部署清单；需要建设主API、Admin、前端、独立AI Worker、SMQ/MNS、负载均衡/WAF、TLS、Secret管理、日志指标和告警，并承载商业首阶段100个同时AI任务的可靠受理与排队。
- 证据：当前 Dockerfile 可复用，但 `render.yaml` 仅描述 Singapore Staging；`docker-compose.yml` 只是本地方案，不含阿里云负载均衡、WAF、证书或生产监控。2026-07-14 用户已在阿里云创建并截图核验资源组 `noteai-production`、自定义VPC、C/F双可用区六个交换机和API/Worker空安全组；API、Worker、RDS、Tair、标准版ALB、NAT/EIP、OSS、SLS、WAF、RDS备份/PITR、MNS、Secret管理、DNS/备案、正式域名/TLS及恢复演练均已完成未下单报价。2026-07-16独立核验确认两个域名已注册并处于正常状态；产品负责人随后报告`.com`已迁移到与`.cn`相同公司名下，等待云端只读复核但不阻塞主线。2026-07-18 企业旗舰DNS已付款、实例已开通，`noteaipro.cn` 已完成绑定并在公网权威解析页显示企业旗舰版/防护中/正常；业务记录仍为0，等待真实生产ALB/WAF入口。同日三份Rapid DV正式单域名证书已付款、确认实例相互独立并全部通过自动DNS验证完成签发；三张当前均未部署到ALB，生产HTTPS仍未闭环。含首年域名、TLS、99计划备案ECS和企业DNS摊销的目标商业首发月均规划约¥3,850.88，持续1 ALB LCU约¥3,881.12；若RDS备份不超400 GB可减¥36/月。正式域名/TLS/备案ECS/DNS包首年现金¥2,845；完整首笔预付基线¥5,848.52，首月含按量计提参考¥6,458.80。软件KMS、按次恢复演练、NAT CU/EIP出网及按量超额不在固定月费内。备案ECS及其他付费生产资源仍未购买；购买前剩余外部变量包括99计划实际可备案状态、恢复实例当日规格和逐项结算页价格。
- 根因是否确认：是。
- 涉及文件：新增阿里云部署/IaC或受控运行手册、容器配置、健康检查、环境模板、DNS/CORS/回调配置；不提交Secret。
- 风险：单点故障、配置漂移、公开Admin、错误CORS、日志泄密和不可回滚部署。
- 执行代理：Architecture/DevOps Explorer 已完成差距审计；资源规格确认后指定单一 DevOps Implementation Agent。
- 验证代理：独立 Cloud/DevOps + Security Reviewer。
- 验收标准：环境隔离、跨可用区最小2个API和2个Worker执行单元、PostgreSQL权威任务账本、SMQ/MNS/RocketMQ唤醒队列与DLQ、生产PostgreSQL/OSS、最小权限、TLS/WAF、Admin访问保护、Secret轮换、健康/指标/告警、灰度/回滚和100任务FakeProvider容量基线通过；主系统仅通过Render Gateway调用Claude并在阿里云内调用Kimi；任一供应商故障时任务仍可恢复且不重复扣费。
- 是否需要用户决定：是；两个域名已付款并注册成功，主域企业旗舰DNS已付款且完成绑定，产品负责人报告两域现已迁移到同一公司名下，后续只需只读复核，无需再次进行产品取舍。正式业务记录切换必须等待真实ALB/WAF目标和TLS完成后按已授权上线流程实施；不能以NAT EIP、占位IP或Render Staging代替。地域采用华南1（深圳，`cn-shenzhen`）；三份Rapid DV、¥99/年备案专机、免费默认服务密钥保持已批准方案，软件KMS延期且不纳入V1预算。
- 是否涉及真实外部调用：是；会创建付费云资源和DNS变更，实施前逐项批准。
- 是否已部署到 Render：不适用；目标部署到阿里云。

### PROD-002A1 — 生产后端运行节点、健康检查与 ALB/TLS

- 状态：**IMPLEMENTING**
- 优先级：Critical。
- 问题描述：按产品负责人 2026-07-18 指令建设生产后端运行节点和健康检查，再创建 ALB 并绑定三张已签发证书。只读云端核验确认华南1当前 ECS 与 ALB 均为0；直接购买空 ECS 无法形成可验收的生产后端。
- 证据：仓库 `Dockerfile`/`scripts/docker_entrypoint.sh` 的 API 默认监听8000并提供 `/health/live`、`/health/ready`；Admin 由 `PORT` 控制，目标端口为8001。生产 readiness 必须验证 PostgreSQL和模型制品，不能以本地SQLite返回200冒充生产就绪。独立DevOps复核确认Worker公开任务链尚未闭环，因此本包不购买2台Worker空节点。三张Rapid DV证书均已签发且未部署，可在后端通过ready检查后分别作为根域默认证书及API/Admin SNI证书绑定。2026-07-18 产品负责人支付一个月期RDS；阿里云控制台独立核验实例 `noteai-prod-postgres`（`pgm-wz9m8tdck1v06672`）为“运行中”，PostgreSQL 16.0、高可用系列、4 vCPU/16 GiB、生产私网，创建时间2026-07-18 14:53:06、到期时间2026-08-19 00:00:00，包年包月且未开启自动续费。这是一套高可用逻辑实例，内部主C/备F，不是两套独立RDS；按一个月期、后续逐月手工续费，不按年费或第二套RDS计入已采购。同日独立核验 `noteai-prod-tair` 为“运行中”，Redis 7.0、云原生标准架构2 GiB、主C/备F、生产私网、包年包月，到期时间同为2026-08-19。VPC级SNAT `noteai-prod-snat-vpc` 状态为“可用”，使用既有EIP为生产VPC内ECS提供主动公网出站，不开放公网入站。本地发布候选预检通过Production Readiness 48/48、相关单元测试186/186、Python编译和Docker Compose配置；但本机Docker daemon未运行，且工作区包含多批未提交变更，不能把当前目录直接冒充可追溯的不可变生产镜像。产品负责人批准API-F因库存差异增加¥90.69/月，两台ECS最终合计¥655.49并完成付款。控制台独立核验两台均于2026-07-18 16:50创建并为“运行中”：API-C `noteai-prod-api-c`（`i-wz9j36od3nf2b1uw7bvg`）位于C区、`ecs.u2a-c1m2.xlarge` 4 vCPU/8 GiB、私网IP `10.42.10.44`；API-F `noteai-prod-api-f`（`i-wz9bgztwf1tiakww2ops`）位于F区、`ecs.u2i-c1m2.xlarge` 4 vCPU/8 GiB、私网IP `10.42.11.166`。两台均为Alibaba Cloud Linux 4 LTS、40 GiB ESSD、0 Mbps且无公网IP、包年包月到期2026-08-18 23:59:59、未开自动续费，均绑定API安全组 `sg-wz98p0xa5040vpnyvgys`；安全组当前入方向规则为0。2026-07-18 生产纯结构migration已按批准范围闭环：官方 `DescribeAccounts` 只读核验实例只有 `noteai_admin`（Available/Super）和 `noteai_app`（Available/Normal）两个受管账号，数据库原所有者 `aurora` 不是受管RDS账号；随后仅把 `noteai` 数据库 `DBOwner` 授予 `noteai_admin`，未提升 `noteai_app`。DMS内部复核显示当前用户与数据库所有者均为 `noteai_admin`，数据库和 `public` schema 的CREATE权限均为真。迁移使用单个原子DO块执行0001—0008，事务内将search_path限定为`public`，安全审计确认0条DROP/TRUNCATE/DELETE，DMS报告1/1语句成功（88ms）。独立查询确认30张public表、8条migration、缺失版本0；`users`、`notes`、`usage_records`、`subscriptions`、`ai_operations`均为0，未导入Staging数据，也未运行Prompt基线写入。生产应用、Secret注入、ALB创建和证书绑定仍未执行。
- 根因是否确认：是；数据库原所有权属于不可直接登录的内部账号 `aurora`，导致迁移账号最初无CREATE权限；该权限阻断已通过最小范围DBOwner授权解决，纯结构migration已落地。当前剩余阻断为可追溯不可变镜像、运行时最小权限账号、Secret注入、节点部署与ALB/TLS，已不是数据库结构问题。
- 涉及文件：`Dockerfile`、`scripts/docker_entrypoint.sh`、`model/api.py`、`model/admin_api.py`、`model/db.py`、生产部署/IaC或受控运行手册、环境变量模板；不得提交Secret。
- 风险：购买空置节点、SQLite误判健康、首次启动隐式migration、Secret泄露、Admin公网暴露、双节点状态漂移、证书绑定到无健康后端。ALB不得使用要求Claude Gateway在线的AI readiness；Gateway故障只允许Claude能力降级，不能把两台Alibaba业务节点同时摘除。视频帧仍为节点本地/内存状态，完成对象存储前不宣称视频流程可横向扩展。
- 执行代理：主CTO编排；生产前置闭环后由单一DevOps Implementation Agent创建API节点与ALB，不并行修改同一部署链。
- 验证代理：独立Render/DevOps Reviewer已完成前置审计；实施后由独立Verification Agent检查云端配置、健康检查、TLS、回归和费用证据。
- 验收标准：C/F双可用区至少2个API执行单元使用同一不可变镜像摘要；API 8000和Admin 8001均从阿里云PostgreSQL启动，`/health/live`与`/health/ready`连续通过且证明数据库后端不是SQLite；节点无公网IP，运行时Secret不进入镜像、Git、cloud-init或消息；标准型公网ALB跨C/F，API Host仅转发到健康API组，Admin在来源限制落实前不得公开，根域在前端落点明确前不得用占位后端；HTTP跳转HTTPS；三张现有证书通过SNI正确匹配且不重复购买；不创建www/gateway解析；独立Smoke和回滚检查通过。
- 是否需要用户决定：是；API-F增量费用、两台ECS和生产纯结构migration均已批准并完成。数据库密码已由产品负责人直接输入且未进入聊天。后续仍需在实施前确认 `noteai_app` 最小运行权限包、Secret注入方式；Admin仍需固定办公IP/VPN/堡垒机访问方案，根域仍需确定生产前端落点。
- 是否涉及真实外部调用：是；涉及付费RDS/Tair/NAT/EIP/ECS/ALB创建、生产migration和证书部署。RDS、Tair、VPC级SNAT及C/F两台ECS已独立核验为运行中/可用，生产纯结构migration已执行并独立验证；应用部署、ALB和证书部署尚未执行。
- 是否已部署到 Render：不适用；目标为阿里云生产，Render Singapore仅保留Claude Gateway。

### PROD-002B — 生产 PostgreSQL、备份/PITR 与迁移恢复演练

- 状态：**IMPLEMENTING**
- 优先级：Critical。
- 问题描述：Render Free PostgreSQL 不可承载正式数据；阿里云生产数据库、备份、PITR、迁移和恢复演练尚不存在。
- 证据：现有 Staging DB 无生产级备份；当前 migration 工具和 PostgreSQL抽象可复用。2026-07-14 官方只读核价确认：200 GiB云盘RDS使用快照备份，数据备份与日志备份合计免费额度为400 GB；华南1超额部分按¥0.00025/GB/小时（约¥0.18/GB/月）计费。推荐每天数据备份、数据与日志均保留14天并启用日志备份，以取得14天PITR窗口；预算暂按200 GB超额预留¥36/月。按时间点/备份集恢复会创建隔离的新实例并按实际存续时间收费，不覆盖原库；标准恢复未发现另收一次性恢复费。生产包月参考价¥1,530折合约¥2.10/小时，但按量价以恢复页为准；按2倍安全系数和零碎预留，首次4小时数据演练上限¥30、24小时完整回归上限¥120、单次硬上限¥200，超过即停止并重新确认。2026-07-18 一个月期生产实例 `noteai-prod-postgres` 已支付并为运行中，到期时间2026-08-19、自动续费未开启。静态审计确认 `model/migrations/postgres/0001` 至 `0008` 均为结构migration，无DROP/DELETE/TRUNCATE/COPY或业务数据导入；本地聚焦单元测试34/34与Production Readiness 48/48通过。为避免 `scripts/render_predeploy.py` 附带Prompt基线写入，本次仅执行等价的事务性纯结构路径。普通运行账号 `noteai_app` 为Available/Normal，数据库 `noteai` 为Running/UTF8，白名单精确限定API-C `10.42.10.0/24` 与API-F `10.42.11.0/24`并保留阿里云健康诊断白名单；未开放公网。官方 `DescribeAccounts` 独立复核仅有 `noteai_admin`（Available/Super）和 `noteai_app` 两个受管账号，数据库原所有者 `aurora` 不在受管账号列表。授权API已把 `noteai` 的DBOwner赋予 `noteai_admin`，DMS内部验证数据库所有者已变更且数据库/public schema CREATE权限为真；`noteai_app`未被提升。0001—0008随后以单个原子DO块执行成功，事务内search_path固定为`public`，执行前安全审计确认0条DROP/TRUNCATE/DELETE。独立验证结果为30张public表、8条migration、缺失版本0，关键业务表 `users`、`notes`、`usage_records`、`subscriptions`、`ai_operations`记录均为0；未导入Staging数据、未删除数据、未写入Prompt基线。纯结构migration子阶段达到验收标准，但备份/PITR配置和隔离恢复演练尚未闭环。
- 根因是否确认：是。
- 涉及文件：PostgreSQL部署/参数/备份策略、`scripts/render_predeploy.py` 的云无关化或新生产predeploy、migration/恢复运行手册及数据库兼容测试。
- 风险：数据丢失、迁移漂移、支付与积分账本损坏、恢复时间不可控；当前尚无已验证的生产PostgreSQL连接池、连接预算、主备切换恢复和隔离PITR演练。
- 执行代理：单一 Database/DevOps Implementation Agent；支付 migration 与生产迁移必须串行。
- 验证代理：独立 Database Recovery Verification Agent，在一次性环境实际恢复备份并对账。
- 验收标准：自动备份与PITR启用；RPO/RTO明确；所有migration幂等；备份恢复到隔离实例后用户、支付、积分、usage、Prompt和趋势关键计数一致；回滚手册演练通过。
- 是否需要用户决定：部分已完成；生产纯结构migration窗口与范围已批准并执行，密码由产品负责人直接输入且未进入聊天。备份保留期、正式RPO/RTO和隔离恢复演练费用仍需在后续阶段确认；`noteai_app` 最小运行权限必须作为独立权限包审查后实施。
- 是否涉及真实外部调用：是；付费数据库已创建，生产纯结构migration已按明确批准执行；备份/PITR变更和付费隔离恢复演练尚未执行，仍需单独批准。
- 是否已部署到 Render：否。

### PROD-003A — 对象存储、视频缓存与 Worker 生产化

- 状态：**TODO**
- 优先级：High。
- 问题描述：当前视频帧依赖 Render 单实例磁盘，市场时机和 tracking 依赖 Render Cron；目标架构要求迁入阿里云并明确对象存储、缓存生命周期、Worker并发和失败恢复。
- 证据：现有 Render API 挂1GB磁盘且不能零停机横向扩展；仓库没有阿里云OSS/任务队列生产配置。
- 根因是否确认：是。
- 涉及文件：视频缓存/对象存储适配、Worker调度、生命周期与监控配置及相应测试。
- 风险：素材丢失、隐私保留超期、重复任务、Cron中断和容量耗尽。
- 执行代理：架构设计完成后指定单一 Storage/Worker Implementation Agent。
- 验证代理：独立 QA/DevOps Verification Agent。
- 验收标准：对象生命周期和访问权限明确；重启/扩容后视频流程可恢复；Worker幂等、失败告警和追踪审计通过；不依赖Render业务磁盘/Cron。
- 是否需要用户决定：对象存储、队列和持续成本需要确认。
- 是否涉及真实外部调用：需要阿里云资源与受控媒体/Worker Smoke。
- 是否已部署到 Render：否。

### COMPLY-001 — 中国商业上线与跨境数据合规清单

- 状态：**TODO**
- 优先级：Critical。
- 问题描述：面向中国用户收费上线需要完成主体、备案/许可适用性、用户协议、隐私政策、退款条款、数据保留和 Claude 跨境数据边界的专业确认。
- 证据：目标架构会把部分用户Prompt/正文/聊天上下文从阿里云传到新加坡Claude Gateway；当前 Chat 还可能把图片base64交给Claude，扩大跨境数据范围。
- 根因是否确认：是；合规文件和数据边界尚未按目标拓扑审计。
- 涉及文件：数据地图、隐私政策、用户协议、退款规则、第三方处理者清单、Cookie/日志/留存策略和跨境数据评估记录；不在代码仓库保存用户材料。
- 风险：用户告知不足、超范围传输、敏感/个人信息跨境、支付入网受阻和监管风险。
- 执行代理：后续指定只读 Security/Privacy/Compliance Reviewer；法律结论由中国执业律师或合规顾问确认，代理不替代法律意见。
- 验证代理：主 CTO 核对技术实现与最终法律/商务文件一致。
- 验收标准：完成数据流和最小化清单；默认不把图片/base64送Claude，除非单独批准；协议/隐私/退款/第三方处理者与实际实现一致；备案、资质和跨境路径取得专业确认。
- 是否需要用户决定：是；经营主体、域名、合规顾问与最终数据策略均需决定。
- 是否涉及真实外部调用：可能涉及备案、律师/顾问和外部平台申请。
- 是否已部署到 Render：否。

### RELEASE-001 — 生产灰度、回滚与正式收费验收

- 状态：**TODO**
- 优先级：Critical。
- 问题描述：需要把全部上线子任务转化为一次可回滚、可审计的生产切流和正式收费验收，避免以“页面可访问”代替上线完成。
- 证据：当前只有 Staging 实际验收，没有阿里云生产、Gateway、Adapay和生产恢复证据。
- 根因是否确认：是。
- 涉及文件：上线清单、变更窗口、DNS/流量切换、回滚、Smoke、财务和安全验收记录。
- 风险：一次性全量切换、支付或AI故障、数据不可恢复、客服和财务无应急流程。
- 执行代理：主 CTO/TPM 编排；各系统实施代理不得自行宣布上线。
- 验证代理：独立 Release Verification Agent，必须检查diff、CI、生产健康、真实最小支付退款、账本、备份恢复、Gateway和用户核心流程。
- 验收标准：先内部/白名单灰度；停止新下单开关不影响回调/退款/对账；核心流程、账本和告警通过；回滚演练成功；所有Critical=VERIFIED且High有明确接受或关闭证据。
- 是否需要用户决定：是；最终切流和开放真实收费必须由产品负责人批准。
- 是否涉及真实外部调用：是；生产DNS、真实AI、最小真实支付/退款和真实数据写入。
- 是否已部署到 Render：否。

商业上线实施依赖顺序：`ARCH-001 → ARCH-002 → PROD-002A/002B → PROD-003A`；支付线按 `PROD-001A + 产品规则确认 → PROD-001B → PROD-001C → PROD-001D → PROD-001E → PROD-001F` 串行推进。`BILL-002` 必须在跨区域生产灰度前闭环；`PERF-001`、`SEC-004`、`OPS-002` 保留为既有未完成/持续运维任务；`COMPLY-001` 与技术建设并行，最终共同汇入 `RELEASE-001`。

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
- 优先级：Critical；当前最高优先级调查项。
- 问题描述：自然 Cron 的 `search_result` 与 `search_recommend` 持续为0；累计 freshness 仍可能满足，但最新单轮明确 degraded。
- 证据：自然 run `19a8c433-923e-4a06-a26f-d1c5aa506d37` 首目标进入 challenge 后熔断11个目标，09:05 run `5a22df29-373f-4ec5-8291-ad85541d95ff` 在6小时 cooldown 中安全跳过12/12搜索目标。冷却后曾有五个连续自然健康轮次；但 2026-07-13 最新自然 run `47d75364-0071-4d8f-b35c-b2975ddd138d` 的公开 readiness 再次显示 degraded：evidence 124，homefeed52/search_result0/search_recommend0/hot_search72，固定错误码 `latest_run_search_sources_missing`，action_required=true，累计 freshness 仍为 true。产品负责人随后提供平台系统消息截图：处罚时间为 2026-07-13 23:49:31，违规分类明确为使用第三方工具或脚本（如AI）自动浏览、查看或发布内容，显示结束时间为 2026-07-21 01:15:12。仓库确认 NoteAI 当时确实使用 Playwright 无头浏览器自动浏览、搜索、滚动并解析网络响应，但没有自动发布、点赞、评论、关注或私信；平台未公开具体命中信号，因此不能把处罚归因于频率、IP、时间或某一个请求。23:49不符合自然Cron的`:05`启动时间，更可能是延迟风控处置而非该时刻单次运行直接触发。
- 2026-07-16只读复查：管理端截图显示连续两轮按行业分化退化。`latest_run_search_result_missing` 表示本轮该行业仍有合格新证据且推荐来源非零，但真正搜索结果为0；`latest_run_search_sources_missing` 表示本轮仍有新证据，但搜索结果与推荐均为0；`session_or_access_unavailable` 表示本轮该行业新增合格证据为0，而Cookie元数据仍显示已配置、认证Cookie存在、静态到期时间未过，且未被诊断为challenge/cooldown。截图“证据”列来自当日累计去重数，不是本轮新增数，因此会出现“证据17但failed”。随后公开 Staging `/health/ready` 于北京时间约22:12显示新自然 run `6f932e77-64af-4155-b138-f4223ad6dcfe` 已扩大为整轮0证据：homefeed/search_result/search_recommend/hot_search/other全部为0，固定错误码 `latest_run_no_evidence`，累计 freshness 仍为true且API非阻断ready。API/Admin/数据库/模型 readiness 正常，XHS运行代码自 `4667d71` 后无新提交，故高置信度排除整体服务/数据库宕机和7月16日新代码回归；当前更像XHS访问/服务端会话/平台挑战或采集异常范围扩大，但公开接口未暴露 `scrape_once_failed`、challenge/circuit、endpoint、schema与过滤计数，不能把Cookie完全失效或某一解析器缺陷写成已确认根因。只读QA以临时数据库完整复现累计证据与本轮状态分离，XHS测试42/42通过、无外部调用。
- 根因是否确认：**是（针对采集复发），处罚命中机制仅确认到行为类别**。产品负责人确认该XHS账号于7月12日收到违规预警，平台于7月13日23:49作出处罚，随后账号被强制退出，且发布、互动、流量曝光和商业权益受到限制；这与后续部分行业逐步归零并扩大为整轮全来源归零吻合。采集失败的直接外部根因是平台终止账号会话，不是NoteAI解析器、API或数据库故障。平台处罚的直接行为类别是第三方脚本自动浏览/查看；当时的固定小时调度、最多10个频道页+12个搜索目标、每目标独立无头浏览器、固定设备参数与重复操作序列均是可能相关信号，但没有平台证据证明哪一项单独触发。内部次生根因是当前只检查Cookie存在性/静态到期时间，没有把服务端登录页/提前注销识别为明确的会话失效，也没有在累计freshness仍为true时让Cron因最新整轮0证据而失败告警。
- 涉及文件：`model/scheduler_a.py`, `model/xhs_acquisition.py`, `tests/test_xhs_acquisition.py`, `tests/test_render_deployment.py`；不改 Cookie、UA/viewport、频率、challenge绕过或数据库。
- 风险：最新单轮搜索证据缺失会降低市场时机判断覆盖，累计 freshness 为 true 只能维持非阻断 readiness，不能宣称最新来源健康。静态审查发现的generic_json候选隔离及推荐路径变体边界已分别由BUG-002E/F修复、独立验证并部署；若出现unknown_schema或正式推荐路径不再使用sug_items，只能依据新的固定结构证据另建解析包，禁止凭猜测修改。
- 执行代理：Repository Explorer + QA Investigator + Test Finder（只读）；验证代理：独立 Render/DevOps Reviewer，结论 PASS。
- 验收标准：重新打开。固定分类继续区分真正note_result与普通JSON；先解释最新 run 的归零阶段，再按确认根因制定最小修复和独立验证。不得以历史五个健康轮次覆盖本次新失败。
- 是否需要用户决定：否；脱敏诊断修正不改变产品策略。若要改变challenge策略、采集频率或账号操作则需要。
- 是否涉及真实外部调用：仅只读观察自然Cron与公开readiness；未手工触发、未改变频率、Cookie、指纹、重试或challenge策略。
- 是否已部署到 Render：历史修复均已在线；但最新自然轮次再次退化，因此父任务不再视为 VERIFIED。当前不部署新代码，等待只读根因证据。

### BUG-002G — XHS 服务端强制注销识别与合规停采

- 状态：**READY_TO_VERIFY**
- 优先级：Critical。
- 问题描述：XHS账号被平台采取限制并强制退出后，存储Cookie仍存在且静态到期时间未过；采集器把服务端注销归为宽泛 `session_or_access_unavailable`，没有立即停止整轮剩余目标。累计freshness仍为true时，Cron还可能以基线/部分模式完成，不能形成明确的运维失败通知；管理端“证据”列只显示当日累计，容易让非技术用户误解为本轮仍采集成功。
- 证据：产品负责人提供平台限制和强制退出事实；公开Staging run `6f932e77-64af-4155-b138-f4223ad6dcfe` 最新整轮五类来源全部为0，但API仍因累计freshness保持ready。代码中 `_classify_final_page()` 已能识别 `/login`，外层熔断只对challenge生效；`record_scrape_freshness()` 只用Cookie静态元数据区分过期，`market_timing_worker.run_once()` 的hard-fail只基于累计overview，管理端Health表只展示累计 `evidence_count`。
- 根因是否确认：是。外部根因是平台强制注销；内部根因是服务端会话失效没有进入专用固定错误码/停采/最新轮次hard-fail链。
- 涉及文件：最小范围预计 `model/scheduler_a.py`、`model/xhs_acquisition.py`、`model/market_timing_worker.py`、`model/admin_server.py`、`model/admin.html`、`model/api.py`、`tests/test_xhs_acquisition.py`、`tests/test_render_deployment.py`、`tests/test_api_contracts.py`、`render.yaml`；`model/api.py` 与 API 合同测试只允许补齐公开 readiness 的固定白名单 `access_status/access_error_code`，`render.yaml` 只允许为 Staging XHS Cron 增加默认停采开关，不修改Cookie值、UA、viewport、频率、重试、验证码、平台挑战绕过或数据库schema。
- 风险：若误判普通匿名页为登录失效，可能暂停合法采集；若继续沿用宽泛错误，则会在账号被平台退出后继续访问并延迟人工处置。错误码、日志与管理端只允许固定枚举和计数，不记录账号处罚详情、URL/query、Cookie、正文、标题或异常原文。
- 执行代理：单一 XHS Safety Implementation Agent；不得与其他代理并行修改同一调用链。
- 验证代理：独立 QA/Test Verification Agent + Render/DevOps Reviewer。
- 验收标准：服务端登录页/强制注销由固定脱敏码识别；当前轮立即停止剩余目标且不启动新浏览器目标；跨Cron保持安全暂停，管理员状态明确为需人工处理/重新认证，不能误报Cookie已验证；最新整轮0证据、会话失效或显式停采在hard-fail开启时令Cron非零退出，即使当天累计freshness仍达标；管理端同时显示当日累计与本轮新增；Staging 默认停采且不访问XHS；challenge/cooldown、正常note_result和历史兼容不回归；本地XHS/Render/全量测试及Production Readiness通过。账号限制解除前不手工触发采集、不换号、不改指纹、不绕过平台措施。
- 是否需要用户决定：安全停采和准确告警不需要；只有产品负责人通过XHS官方流程确认限制已解除后，才可由用户亲自重新登录并批准恢复Staging会话。
- 是否涉及真实外部调用：本地实施不需要；部署到Staging后保持停采状态，不执行手工采集。未来恢复验收只等待一次自然Cron。
- 是否已部署到 Render：否；实现已提交在`0ccf3f6`，尚未push/部署。本地组合回归已通过，但仍须独立核对exact diff、固定错误码/脱敏、停采默认值、无XHS外部访问和部署结果；在此之前不得标记VERIFIED。

### BUG-002D — 搜索响应结构诊断真实性

- 状态：**VERIFIED**
- 优先级：Critical（BUG-002 当前最小修复包）。
- 问题描述：`search.response_seen/json_ok/json_failed` 使用宽泛 URL 字符串匹配，无法区分真正的笔记搜索结果、普通 API JSON 与 challenge 辅助流量；导致 `json_ok>0/title_count=0` 被误解为搜索结果 schema 改版。
- 证据：`model/scheduler_a.py` 的 broad matcher 对搜索目标上任意含 `search`/`api` 的响应计数；35=27 JSON成功+8失败是 broad response 完整分区。标题解析器仅递归接受字符串 `display_title/title`，且自 commit `dd7cfad` 后未改、同一解析器此前曾真实产出搜索来源。run `19a8c433` 在首目标 challenge 时没有进入正常输入/等待结果链，过滤、去重、趋势查询和落库均因 title_count/phrase_raw=0 而尚未发生。
- 根因是否确认：是，诊断统计误分类根因已确认；外部平台 schema drift 未确认，不属于本包宣称。
- 涉及文件：最小范围 `model/scheduler_a.py`, `tests/test_xhs_acquisition.py`，如安全诊断白名单需要才最小涉及 `model/xhs_acquisition.py`；不改候选解析业务语义、Cookie、浏览器指纹、重试、Cron、数据库或熔断策略。
- 风险：结构分类过细可能泄漏平台响应或错误地绑定易变端点；只允许固定枚举与计数，禁止 URL/query、key集合、正文、标题、关键词、seed、Cookie和异常原文。应先并行保留旧总计数，避免突然破坏监控兼容。
- 执行代理：单一 Implementation Agent，仅修改 `model/scheduler_a.py` 与 `tests/test_xhs_acquisition.py`；验证代理：独立 Verification Agent，结论 PASS。
- 修改状态/进度：新增固定白名单 `search_response_class`（generic_json/note_result/empty_result/unknown_schema/business_error/non_json）与 `search_target_outcome`（endpoint_not_seen/challenge_before_target_payload），保留旧 response_seen/json_ok/json_failed/title_count；不猜测 endpoint URL，只用支持结构判断目标 payload。独立验证：XHS 39/39、XHS+Market Quality+Render 64/64、全量 unittest 383/383（5 skip）、Production Readiness 48/48、py_compile、diff check 全部通过。commit `aa1f866` 两条 GitHub CI 均通过；Render API/Admin 已 live、Web 已部署、两个 Cron 为 Successful build；API/Admin readiness 与 Web 均 HTTP 200。
- 验收标准：generic/challenge API JSON 不再冒充“笔记结果JSON成功”；已知 `data.items[].note_card.display_title/title` 结构可识别；empty items、candidate container但unknown schema、business error、non-JSON、endpoint未出现均有固定脱敏分类；challenge首目标得到 `challenge_before_target_payload` 且跳过11；旧漏斗字段兼容；日志/health不含敏感内容；XHS/Render/全量/Production Readiness通过。
- 是否需要用户决定：否；只修诊断真实性，不改变外部采集行为。
- 是否涉及真实外部调用：本地实施不需要；部署后只观察自然half-open Cron，不手工触发。
- 是否已部署到 Render：是，commit `aa1f866`；最新自然轮次 `6a686edd-…` 的固定分类为note_result14、unknown_schema0、challenge_before_target_payload0，搜索结果206、推荐75，云端结构分类验收完成。

### BUG-002E — 普通搜索辅助 JSON 候选隔离

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：BUG-002D 已把 `generic_json` 与 `note_result` 分开统计，但搜索响应处理仍会对所有宽泛命中的JSON递归提取任意 `display_title/title`；普通辅助JSON若带同名字段，仍可能污染 `search_result` 并造成健康假阳性。
- 证据：只读静态审查与最小合成探针确认 `{'data': {'status': {'title': '辅助页面标题'}}}` 被分类为 `generic_json`，但旧候选提取结果仍为1。最新自然轮次已有真实 `note_result=14`，所以该缺口不是本轮恢复的阻断原因，而是独立正确性风险。
- 根因是否确认：是；分类结果只用于计数，没有同时约束搜索候选提取边界。
- 涉及文件：最小范围 `model/scheduler_a.py`, `tests/test_xhs_acquisition.py`；不改homefeed、Cookie、指纹、频率、重试、Cron、数据库、熔断或已知note_result结构。
- 风险：修复会剔除不应进入候选的辅助标题，搜索数量可能下降但真实性提高；必须证明已知 `data.items[].note_card.display_title/title` 仍正常。
- 执行代理：单一 Implementation Agent；验证代理：独立 QA/Test Verification Agent。
- 修改状态/进度：最小修复仅在搜索JSON完成固定分类后增加候选门控，只有 `search_discovery + note_result` 才递归提取标题；homefeed与recommend/trending独立分支保持原逻辑。先失败证据确认generic/business/empty/unknown四类旧逻辑各产生10–11条虚假search_result；修复后各类title_count/phrase_raw/cleaned/final均为0，已知display_title/title正常。Implementation定向40/40、相关26/26；独立Verification PASS：XHS40/40、Render+Market+Composite28/28、全量unittest424/424（5 skip）、Production Readiness48/48、py_compile/diff check通过，真实外部调用0。
- 验收标准：generic_json、business_error、empty_result、unknown_schema、non_json均不能贡献搜索title/phrase/final；已识别note_result正常提取；homefeed与推荐语义不变；固定枚举/计数兼容且不记录敏感内容；XHS、Render、全量单元测试和Production Readiness通过。
- 是否需要用户决定：否；属于诊断分类与候选边界一致性修复，不改变采集策略。
- 是否涉及真实外部调用：本地mock足够；部署后只观察自然轮次，不手工高频采集。
- 是否已部署到 Render：是；commit `2c39008` 随最终批次 `4548304` 部署，API deploy `dep-d99nkaks728c73ds65t0` live，市场时机Cron build succeeded。部署后未手工触发采集，等待下一自然轮次验证收紧后的候选计数。

### BUG-002F — 推荐路径分类与 `sug_items` 解析一致性

- 状态：**VERIFIED**
- 优先级：Medium。
- 问题描述：推荐响应分类支持四种既有路径形态，但 `sug_items` 专用解析只进入其中一种精确路径；若平台切换到其余已支持形态，可能出现recommend json_ok>0但items_raw=0。
- 证据：只读合成探针确认四种分类均为recommend，但只有精确 `search/recommend` 进入专用解析，其余三种无法提取 `data.sug_items`。最新自然轮次recommend responses17/items_raw170/final75，当前线上未触发该退化。
- 根因是否确认：是；分类helper与专用解析分支使用了不同的路径判断。
- 涉及文件：预计最小范围 `model/scheduler_a.py`, `tests/test_xhs_acquisition.py`；必须在BUG-002E完成后串行实施。
- 风险：错误放宽路径可能把非推荐响应误归类；只允许复用现有固定response kind，不新增URL猜测或字段猜测。
- 执行代理：待BUG-002E闭环后指定单一Implementation Agent；验证代理：独立QA/Test Verification Agent。
- 修改状态/进度：单一Implementation先把四种已分类recommend路径统一复用 `data.sug_items` 解析；首次独立验证发现既有子串分类会把suggestion/suggest-unknown/search_recommend_extra/search/suggested近似路径误接纳，判定FAIL并退回。修正版仅用URL path完整段尾匹配四种正式形式，query不参与，未知/近似/query-only路径全部拒绝；未改HOT通用分支或采集行为。最终独立Verification PASS：正式路径与query正向、近似和query-only负向均通过；XHS42/42、Render+Market+Composite28/28、全量unittest426/426（5 skip）、Production Readiness48/48、py_compile/diff check通过，真实外部调用0。
- 验收标准：四种已支持recommend路径均使用同一 `sug_items` 解析并归入search_recommend，不落hot_search；未知路径仍不解析；旧精确路径、固定计数和脱敏约束不回归。
- 是否需要用户决定：否。
- 是否涉及真实外部调用：本地mock足够；最终只观察自然Cron。
- 是否已部署到 Render：是；commit `4667d71` 随最终批次 `4548304` 部署，API deploy `dep-d99nkaks728c73ds65t0` live，市场时机Cron build succeeded。部署后未手工触发采集，等待下一自然轮次完成云端功能验收。

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

### OPS-002 — XHS Cookie/session 持续有效性

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

- 状态：**VERIFIED**
- 问题描述：`actual_model_cost_rmb=0`，当前 `cost_rmb` 是操作级固定估算。
- 当前现象：Token 数已记录，但 Render 未配置 Claude/Kimi 单价与汇率变量。代码实际固定使用 `claude-haiku-4-5-20251001`、`claude-sonnet-4-6`、`kimi-k2.6`、`moonshot-v1-32k-vision-preview` 四个模型；现有部署文档只列 provider 级变量，不足以区分四种价格。
- 预期结果：诊断/生成/对话的真实 Token 成本大于 0，前后台汇总一致，可用于毛利分析。
- 风险级别：Critical；原有商业配置缺口。
- 涉及模块：`model/billing.py`, `model/.env.example`, Render API env, admin usage。
- 根因：已确认；Render 缺少价格变量只是第一层。父 `usage_records` 只保存聚合 Token/模型名，无法逐模型与缓存维度复算；任一已计价调用即可把整笔误标 `actual`，后续缺价不会降级；Kimi `cached_tokens` 和 Claude 缓存维度未按各自价格保存；Multi-Agent 并发 SELECT→UPDATE 还可能覆盖 `cost_rmb/model_names`。
- 修改状态/进度：2026-07-12 官方目录价与 USD/CNY=7.00 已获产品确认。新增 `model_usage_records` SQLite/PostgreSQL 子表与 0006 migration，逐调用保存普通/缓存 Token、精确价格/币种/汇率/版本快照、已知成本和完整性，不保存 Prompt/正文/reasoning/request-id；父锁、插子行、重算在同一短事务内。Kimi 顶层及 `choices[0].usage` 两种流式结构统一解析，缺 cached 降级；Claude cache read/write 拆分，TTL 不明降级；provider generic、未知模型、缺价、非法/零价不得授予 `actual`；退款保留供应商成本。管理端新增 by_model/cache/coverage，覆盖不完整时禁止宣称实际毛利。独立审查先后发现并闭环显式0价格误标 actual、Kimi 官方 nested stream usage 漏读两个 blocker。最终本地：全量 unittest 400/400（5 skip）、Playwright 16/16、Production Readiness 48/48、py_compile/Compose/diff check 通过；全新 PostgreSQL 18 首次 migration 6、二次0，既有5项PG并发、20路模型明细并发与退款保留全部通过；一次性容器删除且 Colima 已停止。commit `2776d7c` 两条 GitHub CI 均通过；Render pre-deploy 成功应用 `0006_model_usage_records.sql`，API/Admin PostgreSQL readiness 200。Staging 真实 Analyze、Generate、Chat Rewrite 三条记录均在结算窗口后成为严格 `actual`，覆盖 Claude Haiku/Sonnet；单张仓库自有图片 Kimi Vision OCR 返回 200，产生一条 `actual`、1 个逐模型子记录、1301/81 input/output tokens、¥0.008125 成本，证明 Kimi 缓存维度与精确模型价格满足严格完整性门禁。管理端新记录覆盖从 0/31 提升至 3/34；独立 Kimi 用户账本再确认第4条严格记录，历史31条继续保守标为不可复算，没有伪造回填。
- 下一步：FIN-001 不再修改。历史31条保持 `legacy_unverifiable_actual`；后续只有新供应商/模型或官方价格变化时新增价格版本并重新做最小真实 Smoke。
- 执行代理：单一 FIN-001 Implementation Agent；不得修改积分价格、扣费顺序、幂等键语义、模型选择、Prompt 或旧 API 字段。
- 验证代理：独立 Billing/Database Verification Agent；必须检查 diff、SQLite/PostgreSQL migration 二次、20 并发、退款/幂等、四模型价格/缓存、管理端汇总、全量测试和 Production Readiness。
- 验收标准：已满足。三个最小文本操作及一条 Kimi Vision 操作均有逐模型明细和严格实际成本；汇率、Token、缓存门禁、操作成本与后台汇总可复算；积分语义未修改。
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

### BILL-002 — SSE 持久结果恢复、租约接管与副作用/退款一致性

- 状态：**INVESTIGATING**
- 优先级：High。
- 问题描述：现有 request-id 只能阻止重复执行，不能在客户端断流、API 进程重启或完成响应丢失后回放已完成结果；Analyze/Chat 还可能在付费终态之前写入业务数据，形成“业务结果已存在但请求被退款/标记失败”的不一致。
- 证据：PERF-001 三路只读设计调查确认：Generate 结果只存在于 SSE；Analyze 可在 `complete` 前写入 notes/saved_diagnoses；Chat 可在 canonical/done 前写 note/session；硬重启可留下长期 `running`，当前 claim 不做 stale lease 接管，同键重试只返回 409 状态而不回放结果。
- 根因是否确认：部分确认。缺少 durable result/status 查询和 replay 是确定事实；各崩溃窗口的业务副作用、usage、refund 一致性需用故障注入与 PostgreSQL 事务边界进一步枚举，尚不能直接进入实施。
- 涉及文件：预计 `model/api.py`, `model/billing.py`, `model/db.py`, `model/migrations/postgres/`, 前端 SSE consumer 与相关 SQLite/PostgreSQL/故障注入测试；具体文件在根因调查后收窄。
- 风险：Critical 账务与数据一致性风险；可能需要 migration、结果保留/清理政策和并发 lease 语义。不得以自动重试或新 request-id 掩盖不确定终态，不得把 AI 调用包进长数据库事务。
- 执行代理：待 Repository/Database Explorer 只读调查完成后，指定单一 Implementation Agent。
- 验证代理：独立 Billing/Concurrency Verification Agent，必须覆盖 SQLite、真实 PostgreSQL 并发与崩溃窗口。
- 验收标准：同键可查询并安全回放已完成结果；stale running 有明确、审计可见且不会双执行的接管/终止规则；Analyze/Generate/Chat 在已枚举断点下业务副作用、主 usage、退款和幂等状态一致；跨用户隔离；结果保留和清理不暴露正文/reasoning；旧客户端仍兼容。
- 是否需要用户决定：进入 migration 或确定结果保留期限前需要；只读调查与本地故障注入设计不需要。
- 是否涉及真实外部调用：本地 mock 不需要；最终 Staging PostgreSQL migration 与最小真实 AI 故障恢复 Smoke 需要单独说明样本和费用。
- 是否已部署到 Render：否；`0006_model_usage_records.sql` 属于 FIN-001 成本审计，不是 BILL-002 的持久结果回放/租约/副作用一致性实现。

### PERF-001 — 阶段耗时、SSE stall timeout 与 P50/P95

- 状态：**INVESTIGATING**
- 问题描述：当前只有进度阶段和零散模型调用日志，没有统一阶段耗时、总耗时或可复算的 P50/P95；前端对 SSE 静默/断流缺少明确 stall timeout，用户可能无限等待。
- 预期结果：诊断/生成主要阶段有单调递增时间戳和耗时；SSE 静默达到安全阈值后给出可恢复错误，按钮与任务状态一致；离线工具可从受控样本计算 P50/P95，且不伪造样本量。
- 风险级别：High；错误 timeout 可能中断仍在运行的付费任务，过度日志可能泄露内容或增加存储成本。
- 涉及模块：`model/api.py`, `model/model_router.py`, `NoteAI_Pro_Demo_Framer.html`, usage/日志与相关 tests。
- 根因：部分确认；`_emit_progress()` 未附带阶段时间，外部模型只记录零散 elapsed 日志，前端没有统一 SSE stall 计时器。实际各阶段瓶颈占比尚未确认。
- 修改状态/进度：`PERF-001A` 已完成统一 timing envelope、保守 stall 告警和离线统计基础；三路只读设计调查进一步确认：成功终态后继续读 EOF 可被后续 transport error 覆盖；Analyze/Generate 不消费 EOF 尾 buffer；Chat 草稿/正式版本在不同断点可能错位；timing envelope 还会以 `sse.v1` 覆盖业务 `process.v1`，导致前端安全解释事件可能被丢弃。2026-07-12 Staging 真实 Smoke 又稳定复现：Analyze 后台阶段持续推进并最终落账，但前端长期停在34%；Generate 阶段持续推进并最终出报告，但前端长期停在0%；Chat 已收到正式重写内容后输入框仍短暂禁用，约20秒后才恢复并落账。低风险客户端/协议修复拆为 `PERF-001B`；持久结果回放、副作用/退款一致性和 stale lease 归 `BILL-002`。
- 下一步：`PERF-001B` 已完成设计、待单独实施；真实 P50/P95 样本数量和费用仍需另定预算，不在本轮推定。
- 验收标准：所有主要事件包含可验证的总耗时/阶段耗时且保持向后兼容；mock SSE 静默和断流能恢复 UI、不重复扣费；统计工具对固定样本准确输出 P50/P95；真实指标只在样本量、费用和数据范围获批后发布。
- 真实外部服务：本地 mock 不需要；真实 P50/P95 需要受控 Claude/Kimi 样本并会产生费用。
- 费用/数据：当前调查无费用、不写远程数据；真实采样前必须说明样本数、预计费用和 Staging usage 影响。

### PERF-001B — SSE 终态完整性与不确定态 UX

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：Analyze/Generate/Chat 收到成功终态后仍继续读取 transport；后续断开可能覆盖成功。分帧未统一覆盖 CRLF、任意字节切片、EOF 尾 buffer；无终态断流只有泛化错误。timing envelope 覆盖业务 `process.v1` 亦会令可解释 Agent 事件被前端丢弃。
- 证据：Explorer、QA、Test Finder 已核对三条 SSE consumer、`_timed_sse_stream` 与现有 stall/idempotency tests；定向 182/182、现有 stall/canonical Playwright 5/5 通过，但均不覆盖终态后断网、尾 buffer、CRLF和组合 schema。
- 根因是否确认：是；前端三套 SSE parser 重复且把 transport EOF 当作终态的一部分，envelope 复用 `schema_version` 覆盖业务事件版本；现有 stall guard 只负责告警，无恢复状态机。
- 涉及文件：`NoteAI_Pro_Demo_Framer.html`, `model/api.py`, `tests/e2e/sse-stall-guard.spec.js`, `tests/e2e/chat-delivery-consistency.spec.js`, `tests/test_api_contracts.py`；不改 DB、billing、idempotency transaction、模型 timeout 或真实 P50/P95。
- 风险：不能把本包描述为“完整断流恢复”；没有 durable result/status 时只能避免误判并显示 `outcome_unknown`。主动 timeout/abort 会放大付费副作用风险，禁止加入。
- 修改状态/进度：单一 Implementation Agent 已完成共享 SSE parser，统一覆盖 Analyze/Generate/Chat 的 CRLF、UTF-8任意字节切片、`data:`前缀拆分、多事件与EOF无尾换行；首个complete/done/error后立即停止，终态后transport错误不覆盖成功。timing envelope保留业务`process.v1`并新增`transport_schema_version=sse.v1`；终态前断流统一固定`outcome_unknown`文案，不回显异常、不自动重试或换key；409四状态使用固定脱敏文案；Chat草稿不写正式DOM/localStorage，只有note_update/canonical_response可落正式快照；Analyze恢复安全process解释卡。未修改DB、billing、幂等事务、模型timeout、Prompt、Agent数或真实P50/P95。Implementation全量unittest402/402（5 skip）、Playwright33/33、Readiness48/48；独立QA/Protocol Verification PASS，额外确认Chat409请求1次/重建0次、complete后source异常或aclose仍completed且退款0、旧thinking事件继续忽略且raw/reasoning/HTML不进入解释卡。真实API/AI/积分调用0。
- 执行代理：2026-07-12 单一 Implementation Agent；验证代理：独立 QA/Protocol Verification，结论 PASS。
- 验收标准：业务 `schema_version=process.v1` 保留，transport 版本使用独立字段；complete/done/error 仅处理一次并立即停止消费，终态后 transport error 不覆盖结果；CRLF/任意切片/末尾无换行可解析；终态前断流显示结果确认中、不自动重试或生成新 key；Chat 草稿不成为正式版本，localStorage 只写 canonical/note_update；409 四状态显示固定安全文案；请求数仍为1。
- 是否需要用户决定：否；只做客户端/协议完整性，不改变计费或数据模型。
- 是否涉及真实外部调用：本地 mock 足够；最终 Staging 仅无付费 Smoke。
- 是否已部署到 Render：是。业务 commit `2579c08`、CI 隔离修正 `f8b98b4`；两条 GitHub CI 均通过。Render API deploy `dep-d99jqimk1jcs73fctrvg` 于 15:10 live，pre-deploy `migrations_applied=0`，API/Admin readiness 200，Web 已包含共享 parser。Staging 无付费合成字节流验证通过：CRLF、拆分 `data:` 前缀、process+complete 多事件得到 `success`，终态只处理一次，页面脚本错误 0；真实 AI/积分调用 0。

### OPS-001 — 长请求期间 Render health check 瞬时超时重启

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：Render API Events 曾形成稳定小时级 health timeout：18:09、19:10、20:09、21:10、22:09 均出现5秒健康检查超时；OPS-001A/B 分别消除Cron N+1连接风暴和同步重型readiness。
- 证据：修复后23:05、00:05及其后自然轮次持续成功；最新09:05:02–09:09:03 run `5a22df29-373f-4ec5-8291-ad85541d95ff` 成功采集272词，压力期readiness连续200、约0.82–1.12秒，09:09后仍200。API Events 顶部自commit `918a488` 23:58 live后无新实例失败/自动恢复，页面仅保留修复前5次历史timeout。
- 根因是否确认：是；Cron N+1 PostgreSQL连接风暴与同步重型readiness是两个叠加放大器，均已修复并获真实PostgreSQL、连续自然Cron及Render Events证据。
- 涉及文件：`model/hot_keywords.py`, `model/scheduler_a.py`, `model/api.py`, `model/db.py` 及对应测试；未修改 Render 资源规格或放宽平台 health check。
- 风险：本轮已消除两个确认的放大器；未来数据库或外部依赖出现新的长阻塞仍需按 readiness 延迟与 Render Events 独立监控，不能把本结论外推为永久无故障。
- 执行代理：单一 Implementation Agent 分别实施 OPS-001A/B；验证代理：独立 QA/Test Finder/Render Reviewer，父任务由第三个自然窗口闭环。
- 验收标准：至少连续 3 个小时任务窗口与受控长请求期间 readiness 均持续成功，或确认并修复可复现的共享依赖阻塞；不得仅靠放宽健康标准掩盖数据库/事件循环问题。
- 是否需要用户决定：若需升级 Render 资源或产生持续费用，则需要；只读调查与本地复现不需要。
- 是否涉及真实外部调用：调查 Render 指标需要只读云端访问；额外付费 AI 样本需沿用已批准的小样本范围并单独计数。
- 是否已部署到 Render：是；OPS-001A commit `02dd0d0`、OPS-001B commit `918a488` 已部署，父任务以第三个自然 Cron 窗口和 API Events 完成云端验收。

### OPS-001A — Market Cron 趋势计算 N+1 PostgreSQL 连接

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：Market Cron 在结果构建阶段对每个候选关键词逐个调用 `compute_trend_dir()`，每次都新建/关闭 PostgreSQL 连接；五个 18:09–22:09/10 API health timeout 与该阶段 5/5 重合。
- 证据：18–22 点 Cron 均 05:02 启动、约 10:28–10:46 才输出 Scraped，API 在 09/10 分超时并紧邻该阶段结束恢复；代码路径 `scheduler_a.scrape_once()`→`compute_trend_dir()`→`hot_keywords._db_conn()` 已确认 N+1。最终 homefeed 结果每轮 101–121，过滤前理论上最多 10×300 个候选；22:09:48–49 PostgreSQL 日志两秒内至少 12 次授权连接，无 ERROR/FATAL/死锁。
- 根因是否确认：是；N+1 连接风暴已确认。它与 readiness 多连接共同造成 timeout 的因果置信度约 85%，但本包只消除已确认的 Cron 放大器，以自然轮次验证因果。
- 涉及文件：`model/hot_keywords.py`, `model/scheduler_a.py`, `tests/test_market_timing_keyword_quality.py` 及必要的采集回归；不改 API readiness、schema、Cron 时间、Cookie、selector 或资源规格。
- 风险：批量查询若改变最近四次快照的排序/去重，会改变趋势方向和最终排序；必须保持 SQLite/PostgreSQL 兼容并限制 SQL 参数规模。
- 执行代理：单一 Repository Explorer；验证代理：独立 QA/Test Finder。
- 修改状态/进度：最小实施、本地独立验证与云端独立验证均完成。新增批量趋势方向查询，800 参数分块、窗口函数每关键词仅取最近4条、所有分块共享同一连接；单关键词函数保持兼容并委托批量实现；Scheduler 在候选循环前一次去重预计算。首个失败证据为批量 API/SQL 构造器不存在的3项 ERROR及 Scheduler 预计算 0!=1。独立验证：SQLite 边界与3000词连接预算通过；全新 PostgreSQL 18 以15,000条快照/3,000词真实执行，结果与独立逐词算法全量一致，3000词1连接/4 SELECT、100词1连接/1 SELECT；market+XHS+Render+API 209/209、全量 unittest 359/359（5 skip）、Production Readiness 48/48、py_compile/Compose/diff check 全部通过。Render 23:05:02–23:09:39 采集235词、00:05:02–00:09:27 采集252词，两个连续窗口成功且API无实例失败，满足本子任务2个自然窗口验收。父OPS-001仍单独等待第3窗口。
- 验收标准：批量结果与旧算法逐词结果一致；100–3000 个候选仅使用常数级连接（目标 1 个，允许同一连接内分批 SQL）；采集来源/数量/排序语义不回退；本地全量通过；部署后连续 2–3 个自然 `:05–:12` 窗口 API 无 health timeout 且 Cron 成功。
- 是否需要用户决定：否；不改变产品行为或付费资源。
- 是否涉及真实外部调用：本地实施不需要；最终只观察自然 Cron，不手工追加采集。
- 是否已部署到 Render：是；commit `02dd0d0`，Market Cron 构建成功；23:05 与 00:05 两个连续自然窗口通过。

### OPS-001B — Render readiness 轻量化与有限 DB 超时

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：`/health/ready` 将 Market Timing 标为 nonblocking，但仍同步建立约 11 个 PostgreSQL 连接并执行约 14 条查询；单连接延迟约 520ms 时，本地 PostgreSQL 路径 Mock 可把 readiness 拖到 5.251 秒。
- 证据：`api._readiness_payload()`、`hot_keywords.db_status()`、六行业 `freshness_status()`、access/cooldown/latest health 串行调用链已核对；Admin 的轻量 readiness 未出现同类小时级失败。OPS-001A 首个自然窗口公开 readiness 全部返回 200，但 23:09:22 单次总耗时 5.94 秒，继续证明当前实现没有足够的 5 秒安全余量。
- 根因是否确认：是；readiness 自身是连接/延迟放大器。OPS-001A 首个自然窗口隔离出残余风险：即使 Cron 已消除 N+1，公开 readiness 仍出现 5.94 秒峰值。只读 QA 另以 `db_status` 与 `freshness_overview` 各延迟 1.1 秒复现 `_readiness_payload()` 同步阻塞 2.205 秒。
- 涉及文件：最小范围限定为 `model/api.py`, `model/db.py`, 新增聚焦 readiness tests 及既有 API/Render 回归；不改业务 `get_conn()` 默认超时、不改 schema/migration/Cron/Render 规格，不改 `/market-timing/freshness` 的实时质量门禁。
- 风险：过度轻量化可能把数据库或模型真实故障误报为 ready；必须保留单次 DB ping、模型加载和 AI 配置检查，并维持公开响应兼容或明确缓存时间。
- 执行代理：单一 Repository Explorer；验证代理：独立 QA/DevOps（PASS）。
- 修改状态/进度：三路只读调查及三轮最小实施完成。第二轮独立复验已确认 SQLite close、market 双-generation 有界恢复、旧 bool 类型、硬门禁合同及底层 PostgreSQL statement timeout/普通连接隔离全部 PASS；唯一残余的 libpq pause 约2.04秒问题已用 API 层 wall-clock 协调器修正。新协调器每个请求最多等待1.5秒，20并发共享单个在途探针，hard-age 3秒后最多允许1个替代 generation，总 live daemon≤2，旧 generation 不覆盖新结果；超时返回安全503，并保留底层health-only超时。第三轮首失败为新增6项全部 ERROR（协调器不存在）。最终独立复验 PASS：一次性PG18 pause后 internal/public共6次均503且不假绿，耗时1.511/0.528/0.000/0.002/0.000/0.002秒，unpause后0.3秒首轮恢复200；250ms statement timeout真实中断pg_sleep，普通get_conn无外溢；20并发正常与超时均仅1次collector。定向169/169、全量unittest381/381（5 skip）、Production Readiness48/48、py_compile/Compose/diff check通过；临时资源已清理。Render 部署与首个自然Cron压力窗口同样通过，现标记 VERIFIED。
- 验收标准：受控慢市场 collector 下 readiness <2 秒且绝不超过5秒；冷缓存立即返回 unknown，fresh/stale 状态清晰且旧绿色不能无限保留；20 并发探针最多一次市场刷新；稳态每次 readiness 主路径仅 1 个 blocking DB ping；DB 连接/查询失败有限时间内返回结构化 503；数据库、模型、Staging 必需 AI 配置继续真实阻断；旧响应字段为新响应子集且不泄露 Cookie/URL/异常正文；定向、全量、Production Readiness、py_compile、Compose 与一次性 PostgreSQL 验证通过。
- 是否需要用户决定：若要升级资源需要；代码轻量化不需要。
- 是否涉及真实外部调用：本地 Mock/临时 PostgreSQL；部署后只读观察。
- 是否已部署到 Render：是；commit `918a488` 于 23:58:16 live，pre-deploy `migrations_applied=0`。部署后内部5秒探针连续200；00:05自然Cron压力期公开采样全部200、约0.79–1.04秒，00:11仍200；API Events无新增实例失败。

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

- 状态：**VERIFIED**
- 优先级：Critical。
- 问题描述：最新手工轮次 12 个搜索目标全部进入 challenge 页面，导致搜索输入、标题和推荐来源归零；首页/热搜仍工作。
- 证据：navigation 12/12 成功、final page challenge 12/12、input 0/12、recommend endpoint 0、search title 0；session configured 且 auth cookie 未过期。已排除空 seed、普通导航失败、数据库去重和 Cookie 完全失效为单一原因。
- 根因是否确认：是；搜索链路受到访问挑战/反自动化退化。最小安全方案为 challenge 感知的单轮熔断、6 小时跨轮次冷却与半开探针，禁止绕过 CAPTCHA 或平台安全控制。
- 涉及文件：`model/scheduler_a.py`, `model/market_timing_worker.py`, `model/xhs_acquisition.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`, `render.yaml`, `tests/test_xhs_acquisition.py`, `tests/test_api_contracts.py`, `tests/test_render_deployment.py`；不改 selector、Cookie、UA/viewport 或验证码处理。
- 风险：继续高频搜索会增加 Cron 成本并加重挑战；激进指纹规避可能违反平台安全边界。
- 执行代理：Repository Explorer（单一 Implementation Agent）；验证代理：独立 QA/Render Reviewer。
- 修改状态/进度：最小修复已实施并通过独立验证。首轮验证发现 `/admin/xhs/health` 删除既有 `error_summary/details` 且可能清空安全错误码；修正为保留旧字段结构、固定摘要映射和严格 details 白名单。最终本地证据：相关 194/194、全量 unittest 311/311、前端静态 16/16、Python 编译、Compose 和 diff check 均通过；HTTP 200 challenge 首目标熔断、homefeed 保留、冷却零搜索浏览器、6小时边界、隐式首目标探针和默认兼容均通过。commit `878787b` 已部署。早期自然轮次先按设计明确degraded，冷却结束后 `478f3783-…`、`5559f473-…`、`ce83808b-…`、`6a686edd-…` 连续四轮恢复。最新完整轮次challenge=0、circuit closed、search_result206、search_recommend75并成功结束；独立Render Reviewer确认PASS。严格代码状态没有名为half-open的枚举，实际是cooldown结束后回到closed并以首个搜索目标作为隐式探针；账本统一使用这一真实描述。
- 验收标准：不绕过安全控制；挑战出现时及时停止/退避并给出稳定状态；若采用安全恢复策略，至少连续 2–3 个自然轮次恢复 search/recommend 健康阈值，否则明确降级而不浪费全轮成本。
- 是否需要用户决定：技术默认采用 Staging 6 小时冷却、Cron 继续成功但明确 degraded；不自动重新登录、不减少长期行业覆盖。如后续要改 hard fail 或每行业 seed 数再单独决策。
- 是否涉及真实外部调用：只读观察自然Cron；没有追加手工触发。
- 是否已部署到 Render：是；commit `878787b`，连续四个自然健康轮次已满足云端验收。

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

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：Generate 报告和 Chat Markdown 存在将模型自由文本写入 `innerHTML` 的路径；Analyze/Generate 响应与持久化还包含专家 `raw`/原始 XML，扩大模型输出注入和不必要数据暴露面。
- 证据：三路只读调查完成。本地无网络 Chromium sentinel 已让 Chat `chatMD`、实时 `addBubble`、Generate 专家/标题区域的 `<img onerror>` 实际执行；raw HTML link 也可形成可点击节点。`_normalize_expert_opinion`、Analyze/Generate JSON/SSE complete 仍公开 `raw`，Analyze 将完整响应写入 `saved_diagnoses`，历史详情原样返回。Render 静态响应无 CSP，不能依赖浏览器策略缓解。
- 根因是否确认：是。模型/外部内容经 raw XML 或最终文本进入未转义 `innerHTML`；内部仲裁结束后缺少统一 public expert 白名单投影，使 raw 继续进入响应、浏览器和诊断历史。
- 涉及文件：最小范围 `model/api.py`, `NoteAI_Pro_Demo_Framer.html`, `tests/test_reasoning_safety.py`, `tests/test_frontend_report_static.py`, `tests/e2e/reasoning-safety.spec.js`，必要时最小补充 API contract 安全断言；不改 DB schema、auth、billing、模型路由或 Prompt。
- 风险：High；可执行 DOM XSS 可能读取同源页面状态，且用户 token 位于 localStorage；raw 长期保存扩大 Prompt Injection 与不必要数据暴露。修复若过早删除内部 raw 会破坏仲裁质量，必须只在最终公开/持久化边界投影。
- 执行代理：Security Reviewer + Repository Explorer + QA Investigator（只读完成）及单一 Implementation Agent；验证代理：独立 Security/Browser Verification，结论 PASS。
- 修改状态/进度：后端新增 expert public projection，raw 仅保留在内部仲裁，Analyze/Generate JSON与SSE、新诊断保存、历史读取及 Chat context 均输出结构化白名单；前端 `addBubble` 改安全 DOM/textContent，`chatMD` 先转义再保留有限 Markdown，Generate 标题/专家卡和 Analyze role 全部转义。主审补回兼容字段 impact/evidence_binding。独立验证：定向 180/180、Playwright 11/11、全量 unittest 387/387（5 skip）、Production Readiness 48/48、py_compile、diff check及精确复制探针全部通过。commit `714a755` 两条 GitHub CI 通过；Render API/Admin live、Web Deployed，三项公开健康请求 HTTP 200；线上静态文件确认安全 DOM、HTML 先转义和结构化专家字段已生效。
- 验收标准：`<script>`、`<img onerror>`、`<svg onload>`、事件属性、raw/Markdown HTML link 与未知标签只能作为字面文本显示且 sentinel 不执行；Chat `**粗体**`、行内 code、换行/列表保留；Agent 名称、意见、理由、证据、建议、置信度保留；Analyze/Generate JSON与SSE、new saved diagnosis、历史详情和 Chat 上下文均无 raw/XML/provider内部字段；全量/Playwright/Production Readiness通过。
- 是否需要用户决定：否；属于安全修复，不改变产品功能。
- 是否涉及真实外部调用：本地 sentinel 与浏览器测试不需要；最终 Staging 仅需无付费 Smoke。
- 是否已部署到 Render：是，commit `714a755`；Staging Smoke 未调用真实 AI、未上传内容、未写业务数据。

### SEC-004 — 历史原始 reasoning 与内部模型载荷清理

- 状态：**INVESTIGATING**
- 优先级：High。
- 问题描述：SEC-002/SEC-003 已阻止新的 provider 原始 reasoning/raw 进入公开响应与长期持久化，但 Staging 历史 `chat_sessions.messages_json` 及历史诊断数据中可能仍保留旧 reasoning/内部 raw 字段。
- 证据：SEC-002 已确认旧 Chat 会持久化 `reasoning_content`；SEC-003 已确认旧 saved diagnosis 曾保存 expert `raw`，当前仅在读取时投影净化，未执行数据库批量清理。尚未读取任何历史正文或 reasoning 内容。
- 根因是否确认：是；新写路径已修复，剩余风险来自修复前已持久化记录。受影响行数、表范围和可回滚策略尚需只按结构/键名统计确认。
- 涉及文件：预计只读统计/清理脚本、`model/db.py` 或独立受控运维工具及测试；不修改公开解释事件、模型 Prompt、计费或用户正文语义。
- 风险：High 隐私与恢复风险；直接 JSON 重写可能误删安全结构化解释或损坏历史会话。禁止读取/输出正文、reasoning 原文、Prompt 或完整 JSON；禁止无备份、无 dry-run 的批量更新。
- 执行代理：Security/Data Migration Explorer 先只读统计；方案批准后单一 Implementation Agent。
- 验证代理：独立 Security/Migration Verification Agent，核对 dry-run、备份/回滚、字段白名单和行数一致性。
- 验收标准：只用键名/固定枚举统计受影响行数；形成可回滚 dry-run；清理仅删除 provider 原始 reasoning、raw XML/内部载荷，保留 `process.v1` 结构化解释和用户正式内容；清理前后行数、JSON 可解析性、用户隔离与历史页面回归通过；日志不含原文。
- 是否需要用户决定：执行 Staging 批量清理前需要确认备份/回滚窗口；本轮只读统计不需要。
- 是否涉及真实外部调用：只读 Staging PostgreSQL 统计与后续受控 migration；不调用 AI。
- 是否已部署到 Render：否。

### SEC-005 — 跨账号 Chat 本地缓存泄露

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：同一浏览器中，账号 B 登录/注册后进入“对话优化”，前端可能直接展示账号 A 在 `localStorage` 中遗留的笔记快照；后端会拒绝异账号会话请求，但内容已在浏览器 UI 暴露。
- 证据：2026-07-12 Staging 新建隔离测试账号复现旧笔记快照，发送时后端固定返回无权访问且未扣费。只读 Security Reviewer 确认 `noteai_chat_session` 为全站唯一键，保存 session/note 标识、标题、正文、评分与版本，恢复时不校验 owner；`doAuth` 不清旧状态，认证恢复用固定1.2秒延迟而不等待 `/auth/me`。正常完整 logout 是降低概率的负对照，但不能覆盖 token 失效、网络慢/失败和同页身份覆盖。
- 根因是否确认：是。前端持久缓存未绑定用户且认证恢复存在竞态；后端 `chat/start`、`chat/message`、`chat/select-plan` 所有权检查目前在计费/写入前成功阻断，尚无服务端越权证据。
- 涉及文件：`NoteAI_Pro_Demo_Framer.html`、相关前端静态/Playwright tests；防御纵深可最小涉及 `model/api.py` 与 chat ownership contract tests。不得读取或记录旧正文、Prompt、reasoning、Token 或完整 session ID。
- 风险：High 机密性风险；同一设备多账号、共享电脑、token 失效或 Render 冷启动/慢认证时可泄露缓存内容。后端当前阻止修改与扣费，但不能作为允许前端泄露的理由。
- 修改状态/进度：单一 Implementation Agent 已完成最小前端修复：`noteai_chat_session` 写入 owner ID；只有 awaited `/auth/me` 成功且 owner 匹配、时间有效且不超过24小时才恢复；旧格式、异账号、非法/未来/过期缓存删除。登录/注册身份变化、认证失败、logout 和 Chat start/message/select 401/403 统一清 Chat storage、session/note/version runtime、消息与当前笔记 DOM、评分、附件、输入及进行中请求；epoch/owner guard 阻止异步 FileReader 和迟到响应重新写回旧账号。未修改 reasoning 展示、后端权限、billing、DB、Prompt 或模型。Implementation 自测新增12/12、全量Playwright28/28、frontend static18/18、ownership-before-billing 1/1、Readiness48/48。独立 Security/Browser Verification PASS：定向22/22、全量unittest400/400（5 skip）、Playwright28/28、Readiness48/48、py_compile/diff check通过；两个合成账号全部 route-mock，真实 API/AI/积分写入0。
- 执行代理：单一 Implementation Agent；先前端统一 account-scoped state reset 与 owner 校验，确有必要再做后端带 user_id 的严格加载。
- 验证代理：独立 Security/Browser Verification Agent。
- 验收标准：账号 B 的 DOM、storage 和运行时状态均不出现账号 A 的脱敏哨兵；账号 A 经 `/auth/me` 验证后仍可24小时内刷新恢复；登录/注册身份变化、认证失败、logout 和 chat 401/403 均清缓存、全局 ID、DOM/附件；不扣费、不重试、不重建他人 session；常规 start/save/reload 不回归。
- 是否需要用户决定：否；属于最小安全修复，不改变产品功能或计费语义。
- 是否涉及真实外部调用：本地 route-mock 足以实施；最终 Staging 只需两个合成账号的无 AI/无扣费 Smoke。
- 是否已部署到 Render：是；commit `513675d` 已推送，PR两条GitHub CI通过，Render API pre-deploy `migrations_applied=0`、startup/readiness 200并 live，Staging Web 已包含 owner恢复门禁。云端双账号 Smoke：仅账号A有一条脱敏手工笔记并建立空Chat session；退出A后DOM/消息/会话清空，登录B后A哨兵在笔记与消息区均不存在且显示无会话。两个账号前后 usage_records=0、total_credits=0、credit total_used=0；未调用Chat message/Analyze/Generate/AI，未扣积分；临时密码已旋转、临时Token已撤销。验收标准全部满足。

### SEC-006 — Render Blueprint Sync Hook 潜在暴露与轮换

- 状态：**INVESTIGATING**
- 优先级：High。
- 问题描述：在ARCH-002P-D核对Blueprint设置时，操作端自动化页面快照意外包含了一个真实Blueprint Sync Hook值。该值不得再次读取、输出、复制或记录，需按潜在泄露处理。
- 证据：值曾出现在受控工具输出中；本账本只记录事件和受影响的凭证类型，不记录值。目前已确认Blueprint Auto Sync为No，但这不替代Hook轮换。
- 根因是否确认：是；Render设置页把Hook作为可见值渲染，而页面自动化快照未在读取前对该字段脱敏。尚未找到Render官方针对Blueprint Sync Hook的明确自助轮换入口。
- 涉及文件：不涉及仓库代码；Render Blueprint凭证与运维runbook。
- 风险：未授权的Blueprint同步触发或部署/配置干扰；直接断开或重建Blueprint又可造成服务配置漂移，不得擅自执行。
- 执行代理：Render/DevOps Reviewer（只读查明轮换路径）；若必须联系Render Support或重建Blueprint，由主CTO列明影响后再执行。
- 验证代理：独立Security/DevOps Reviewer。
- 验收标准：旧Hook失效、新Hook不出现在对话/日志/仓库；Blueprint绑定、Auto Sync=No、Gateway min2/max4及现有环境配置不回退；受控手工sync与回滚能力保留。
- 是否需要用户决定：若Render支持无损自助轮换，作为安全处置可按最小变更执行；若只能断开/重建Blueprint或联系Support，需先告知用户影响。
- 是否涉及真实外部调用：是，Render凭证轮换或Support联系；不涉及AI、支付或数据库。
- 是否已部署到 Render：不适用；当前未执行轮换。

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

- 状态：**VERIFIED**
- 问题描述：自动化浏览器安全策略不允许选择本机文件，后端链路通过但 UI 文件选择未完成本轮人工验收。
- 当前现象：真实 9 图与视频主清单、用户列表/详情/筛选及用量分析已执行；由清单发现的余额提示、管理端聚合、多图状态、视频状态与逐笔账本均已分别闭环。
- 预期结果：真实浏览器操作与后端结果一致，无装饰性控件和状态错位。
- 风险级别：Medium；验证缺口，尚未确认产品缺陷。
- 涉及模块：`NoteAI_Pro_Demo_Framer.html`, `model/admin.html`, API。
- 根因：五个独立缺陷已分别由 QA-003A/B/C/D/E 确认并修复；不再以浏览器扩展限制作为未闭环理由。
- 修改状态/进度：真实 9 图、视频、管理端用户/筛选/详情/用量分析清单已完成，发现的问题均拆为QA-003A/B/C/D/E并完成修复、独立验证和Staging Smoke。2026-07-12 用户再次要求处理“剩余UI问题”后，独立QA重新核对当前HEAD `87d679f`：四组QA-003专项Playwright 20/20、前端静态/管理端聚合/成本合同34/34通过，全部route-mock，真实API/AI/积分写入0；未发现新的最小失败用例，确认QA-003没有剩余修复包。
- 下一步：不重复付费主清单；后续媒体/管理端变更按 C/D/E 专项回归。
- 验收标准：9 图全部完成状态后可提交；视频进度正确；余额不足不发起付费操作；管理端账本一致。
- 真实外部服务：UI 主链路会调用真实 AI。
- 费用/数据：会产生少量费用和 Staging 测试数据；先说明样本数量。

### QA-003A — 管理端用量分析 PostgreSQL 聚合失败

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：Staging 管理端“用量分析”Top10 为空，四块图表无法获得完整数据，console 显示 `Internal Server Error` 被当 JSON 解析。
- 证据：真实只读 UI 复现；`GET /admin/usage-stats` → `build_usage_stats_payload()` 的 Top10 SQL 只 `GROUP BY r.user_id` 却选择 `u.username`，SQLite 宽松通过、PostgreSQL 必须同时分组。前端 `loadUsage()` 未检查 `r.ok/Content-Type` 直接 `r.json()`，把 500 二次表现为 JSON 解析错误。
- 根因是否确认：是。
- 涉及文件：`model/admin_server.py`, `tests/test_billing_token_cost.py`；仅确有必要时最小涉及 `model/admin.html` 错误态。不改 schema、成本口径或数据。
- 风险：财务展示不可用；SQL 修复低风险，但与 FIN-001 共享管理端调用链，必须串行。
- 执行代理：FIN-001 完成后指定单一 Implementation Agent。
- 验证代理：独立 QA/PostgreSQL Verification Agent。
- 验收标准：SQLite/PostgreSQL `top_users` 正确；Staging `/admin/usage-stats` 200 JSON；有消费数据时 Top10 非空；4 图无 NaN、console 无 JSON 解析错误；无管理员写操作。
- 是否需要用户决定：否。
- 是否涉及真实外部调用：最终只读 Staging 管理端复验。
- 是否已部署到 Render：是；commit `2776d7c`。SQL 已按 `r.user_id,u.username` 分组，`loadUsage()` 增加固定脱敏失败态；独立本地验证相关44/44、全量400/400、Playwright16/16通过。Staging `/admin/usage-stats` 已恢复200 JSON，Top10显示真实聚合数据，4块图表渲染且不再出现500文本JSON解析错误。

### QA-003B — 余额不足 UI 一致性与 Chat 恢复边界

- 状态：**VERIFIED**
- 优先级：Medium。
- 问题描述：OCR 402 仅 toast/图片失败，不显示统一积分弹窗；Chat 首次 404 重建 session 后第二次若返回 402，会显示通用服务器错误。
- 证据：只读代码调查确认 Analyze/Generate/Chat 初始 402 主路径已有统一弹窗；`/extract-screenshot` 402 未解析 quota detail 或调用 `showQuotaExceededModal()`；Chat 404→start→retry 分支未重新执行 401/402 处理。现有 Playwright 无 402 UI 断言。
- 根因是否确认：是。
- 涉及文件：`NoteAI_Pro_Demo_Framer.html`, `tests/e2e/quota-ui.spec.js`；不改后端计费、价格、退款或认证。
- 风险：Medium；错误提示会误导用户，但修复不得自动重试、发起付费或改变图片失败门禁。
- 执行代理：待 QA-003A 后指定单一 Implementation Agent。
- 验证代理：独立 Browser Verification Agent。
- 验收标准：Analyze/Generate/Chat/OCR 模拟 402 均显示功能名、余额和所需积分；取消停留当前页、确认仅进入价格页；OCR 保持失败且不重试；Chat 404→重建→402 正确显示积分不足；全程 route mock、真实 API/AI/积分调用为 0。
- 是否需要用户决定：否。
- 是否涉及真实外部调用：否；纯本地 route-mock。
- 是否已部署到 Render：是；commit `2776d7c`。OCR同批402只弹一次且保持失败门禁，Chat 404→start→402 进入统一配额提示；纯 route-mock 5/5、全量Playwright16/16，真实调用0；Staging Web 已确认部署新的统一处理代码。

### QA-003C — 多图识别总完成态提前显示

- 状态：**VERIFIED**
- 优先级：Medium。
- 问题描述：9 图识别进行到 2/9、7/9 时总状态曾提前显示“AI识别完成”，虽然诊断按钮仍保持禁用；文案与真实批次状态不一致。
- 证据：QA-003 真实 Staging 9 图人工清单；最终 9/9 成功且按钮门禁正确。
- 根因是否确认：是。新增图片时仅清空聚合数据，没有重置可见结果卡；`_validateAndMergeOcr()` 无批次 revision/图片快照校验，旧 validate 回调可在新图片加入后回填过期聚合结果和“完成”文案。工具栏与提交门禁使用最新计数，因此目前没有提前付费提交。
- 涉及文件：最小范围 `NoteAI_Pro_Demo_Framer.html`、新增/扩展截图状态 route-mock Playwright test；不改后端、OCR API、调用次数、计费或诊断门禁。
- 风险：过早提示会误导用户；修复不得改变逐图 AI 调用次数、费用或最终提交门禁。
- 执行代理：单一 Implementation Agent；验证代理：独立 Browser Verification Agent。
- 修改状态/进度：已在最小范围实现截图批次 revision、selection token、图片快照校验、过期 FileReader/extract/validate/merge 回调失效、总状态按当前 pending/failed/validating/merging 优先渲染、同 revision 合并去重。首次独立验证发现“FileReader 延迟期间 reset 后旧选择仍加入并触发 extract”的阻断竞态，已退回修正；第二轮独立验证 PASS：delayed read→reset 为图片0/cache0/extract0，旧选择被新选择取代仅保留新图/extract1，同批3文件 extract3/validate1；专项6/6、quota5/5、frontend static18/18、全量Playwright39/39，先前同业务diff的unittest402/402（5 skip）和Readiness48/48有效。未改后端、按钮门禁、API 或计费，真实外部调用0。待批量部署后的 Staging 增量 Smoke 再标 VERIFIED。
- 验收标准：0–8/9 只显示进行中/失败计数；仅全部进入成功或失败终态后显示批次完成；诊断按钮仍只在既有素材门禁满足时启用；无新增 AI 调用。
- 是否需要用户决定：否。
- 是否涉及真实外部调用：调查阶段否；最终优先 route-mock，必要的单次 Staging UI 复验另行计数。
- 是否已部署到 Render：是，commit `9eebc8c`，随 `bf0c4be` 批次部署；Staging 合成状态验证为1/2时显示“1/2张已识别”、按钮禁用、无完成文案，页面错误0，真实API/AI/积分0。

### QA-003D — 视频上传进度与诊断前置门禁

- 状态：**VERIFIED**
- 优先级：Medium。
- 问题描述：视频进度只显示静态 `0.0 MB`，且未选择/上传视频前诊断按钮未禁用，页面状态可能诱导无效提交。
- 证据：QA-003 使用 2 秒/1 帧合成视频完成真实 Staging 上传，未触发诊断；已复现上述两项 UI 状态。
- 根因是否确认：是。`updateDiagnosisSubmitState()` 没有视频分支；提交函数虽有 `_diagVideoFileId` 二次拦截，但按钮状态错误。上传逻辑没有独立预检/上传/成功/失败状态，只在请求前后写静态 MB，且旧请求可覆盖后选文件/移除操作。
- 涉及文件：最小范围 `NoteAI_Pro_Demo_Framer.html`、视频上传 route-mock Playwright test；不改 upload API、后端、AI 或计费。
- 风险：按钮门禁修改可能误伤纯图文流程；进度文案不得伪造网络百分比。
- 执行代理：QA-003C 验证完成后指定单一 Implementation Agent；验证代理：独立 Browser Verification Agent。
- 修改状态/进度：已最小实现视频专属 idle/preflight/uploading/ready/error 状态、attempt token、真实 B/KB/MB 文件总大小和阶段文案；仅当前模式为视频时要求 ready+file_id，手动/截图沿用原门禁，startDiagnosis 二次保护保留。首次独立验证发现上传中切换模式后迟到响应仍回填，已退回修正；现在离开视频模式会使 preflight/uploading attempt 失效，但已ready视频往返仍保留。第二轮独立验证 PASS：视频7/7、QA-003C6/6、quota5/5、组合18/18、frontend static18/18；ready后 upload1/analyze1，payload input_mode=video/file_id正确。全量Playwright首轮45/46，唯一既有Chat stall时序用例单独重跑1/1通过，判定与本包无关。真实API/AI/积分0。待 Staging Smoke。
- 验收标准：无所需素材时不能发起视频诊断；选择、上传、成功/失败状态一致；只展示浏览器可真实测得的字节/阶段，不伪造上传百分比；不触发额外 AI 或扣费。
- 是否需要用户决定：只有产品允许“无视频也可走通用诊断”时需要；先从现有产品上下文判断。
- 是否涉及真实外部调用：调查阶段否；最终优先 route-mock。
- 是否已部署到 Render：是，commit `3041d87`，随 `bf0c4be` 批次部署；Staging 合成验证为空态禁用、ready启用、3字节显示`3 B`、手动填写仍启用，页面错误0，真实上传/API/AI/积分0。

### QA-003E — 管理端逐笔 usage/credit ledger 展示

- 状态：**VERIFIED**
- 优先级：Medium。
- 问题描述：管理 API 已返回逐笔 usage 与 credit transactions，但用户详情 UI 未渲染，管理员无法在页面完成操作、模型成本、积分扣退的逐笔对账。
- 证据：QA-003 管理端人工清单；用户搜索、筛选、详情与聚合图表已通过，但逐笔数组没有对应 DOM 表格/列表。
- 根因是否确认：是。`GET /admin/users/{id}` 已由管理员依赖保护并返回最近20条 `recent_usage`、20条 `credit_txns`；`showUser()` 只渲染基本信息/月聚合，完全忽略两个数组。
- 涉及文件：最小范围 `model/admin.html`、管理端 ledger route-mock/合同/负向授权 tests；无需修改 `model/admin_server.py` 业务、数据库、billing 或 migration。
- 风险：管理端可能展示不应暴露的 prompt、正文、token 或内部错误；只允许审计所需的固定字段并做 HTML 转义。
- 执行代理：QA-003D 验证完成后指定单一 Implementation Agent；验证代理：独立 Admin UI/Security Verification Agent。
- 修改状态/进度：最小范围只改 `model/admin.html`、管理端ledger E2E与既有合同测试；增加两张独立最近20条表、非一一对应/非完整历史说明、固定枚举/数值/时间格式化、空态及逐字段转义。`payment_ref` 与注入的prompt/body/reasoning/error/request_id均不读取/渲染；无token/普通token详情请求403。首次独立安全验证发现普通对象枚举会让constructor/toString/__proto__命中原型字段，已退回改为own-property helper并补原型键/Symbol/null等负向覆盖。最终独立PASS：ledger2/2、相关45/45、同业务diff全量unittest403/403（5 skip）、Playwright48/48、Readiness48/48、py_compile/diff通过；详情GET1次、写请求/AI/积分0。待Staging Smoke。
- 验收标准：管理员详情可按时间查看操作、模型、积分变动与脱敏成本；与 API/聚合账本一致；无用户正文、prompt、reasoning、Secret 或异常原文；普通用户不可访问。
- 是否需要用户决定：若需新增审计字段或改变成本展示口径则需要；仅渲染既有安全字段不需要。
- 是否涉及真实外部调用：调查与 route-mock 否；最终只读 Staging 管理端复验。
- 是否已部署到 Render：是，commit `bf0c4be`；Staging Admin 已包含own-property枚举helper与两张账本。合成route仅1次GET，原型键均显示固定未知标签，敏感哨兵不进DOM，恶意HTML元素0，真实管理端写入/AI/积分0；Admin readiness 200。

### QA-004 — 管理端系统状态跨服务与字段契约漂移

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：Dashboard 把实际已配置且健康的 Kimi/Moonshot、Claude 显示为“未配置”，并显示 `undefined` 与 `undefined MB`；会误导管理员判断AI和数据库故障。
- 证据：2026-07-12 截图与Staging只读复现一致。API `/health/ready` HTTP 200且 `claude_configured=true/moonshot_configured=true`、数据库 `ok=true/backend=postgresql`；管理页仍显示两项未配置。线上HTML仍读取 `s.kimi_key_prefix` 和 `s.db_size_mb`，但Admin `/admin/overview` 已不返回这两个字段，只返回configured布尔、模型状态、`database_backend` 与时间。
- 根因是否确认：是。AI配置状态错误地读取Admin容器自身环境变量，而Render只把AI Key注入实际调用模型的API服务；另外Render/PostgreSQL迁移提交 `f2b1c3b` 安全删除Key前缀与SQLite文件大小字段并新增 `database_backend`，前端未同步。
- 涉及文件：`model/admin_server.py`, `model/admin.html`, `render.yaml`, `tests/test_admin_system_status.py`, `tests/test_render_deployment.py`, `tests/e2e/admin-system-status.spec.js`；只读消费API readiness安全状态，不改Render Secret值。
- 风险：High运维误报；修复不得恢复Key前缀或把Secret复制到Admin服务，也不得把“Admin容器无Key”解释为实际API不可用。PostgreSQL大小若未安全查询应显示后端类型/健康，不得伪造MB。
- 执行代理：QA-004 单一Implementation Agent；验证代理：独立QA/Security/Render Verification Agent，结论PASS。
- 修改状态/进度：已先得到7个错误与2个失败的失败合同，再最小实现。Admin通过非Secret `NOTEAI_API_READINESS_URL` 只读取公开API readiness中固定 `checks.ai.ok/claude_configured/moonshot_configured`；HTTP 200及强制AI Key门禁返回的503均进入同一白名单解析，其他状态、字段缺失、结构矛盾、超时或异常统一返回固定 `unavailable`，不返回URL、上游正文或异常；旧configured布尔键保持兼容。Dashboard改用显式三态和 `database_backend/database_ok`，不再读取Key前缀或本地数据库MB；Render只给Admin配置公开readiness URL，未复制AI Key。独立验证首轮发现503有效状态被错误降级为unavailable，已先补fetch层503正负合同并只将允许解析状态扩为 `{200,503}`。最终独立PASS：对抗探针10类、核心7/7、相关70/70、全量unittest435/435（5 skip）、Admin Playwright7/7、Production Readiness48/48、py_compile/Compose/diff check通过。commit `0bda1f8` 已随 `c0a39ff` 推送；Push/PR GitHub CI `29193581641`/`29193582630` 均通过。登录后Staging Dashboard只读Smoke确认Kimi/Claude均显示“API 服务已配置”、来源均为API readiness、数据库为“PostgreSQL 正常”，不存在未配置、undefined、undefined MB、NaN或Key前缀，浏览器console error为空。Web/API/Admin均HTTP 200；真实AI、业务写入和Secret访问均为0。
- 验收标准：实际API readiness配置正常时显示Kimi/Claude已配置；API不可检测时显示固定“不可检测”而非未配置；数据库显示PostgreSQL/SQLite后端与健康状态，缺失字段不出现undefined；不返回/显示任何Key前缀；API/Admin/Web健康、合同与Playwright测试通过。
- 是否需要用户决定：否；属于状态真实性和安全字段兼容修复。
- 是否涉及真实外部调用：本地route-mock足够；最终只读Staging health/UI Smoke。
- 是否已部署到 Render：是；新管理端bundle、公开健康检查及登录后系统状态UI均已通过。

### FIN-002 — 毛利覆盖口径与历史不可复算说明

- 状态：**VERIFIED**
- 优先级：Medium。
- 问题描述：收入/用量页正确阻止不完整成本数据宣称“实际毛利”，但“严格实际4/35”和“历史不可复算31”的含义不直观，用户容易误解为模型配置或价格缺失。
- 证据：Staging最近30日 `total_records=35`、`strict_actual_records=4`、`legacy_unverifiable_records=31`，partial/unpriced/usage_incomplete均0，严格覆盖11.4%。4条为FIN-001上线后真实Analyze、Generate、Chat Rewrite与Kimi Vision父操作；31条为0006逐模型表上线前记录。
- 根因是否确认：是。31条历史父记录只有聚合Token/模型名/旧成本，没有逐调用模型、普通/缓存Token、缓存TTL、精确单价、币种、汇率与价格版本快照，无法可靠复算；系统故意不伪造回填。`actual_margin_ready` 仅在total>0且strict==total时为true。
- 涉及文件：`model/admin.html`, `tests/e2e/admin-cost-coverage.spec.js`；未修改 `model/admin_server.py`、SQL、billing、数据库或聚合定义。
- 风险：财务口径风险。当前API成本是4条严格实际+31条旧估算的混合值；订阅收入也是有效套餐人数×套餐价估算，不是支付流水。不得为显示百分比而放宽门禁或伪造历史成本。
- 执行代理：单一Implementation Agent；验证代理：独立Billing/Data/Browser Verification Agent，结论PASS。
- 修改状态/进度：单一Implementation仅修改 `model/admin.html` 与新增route-mock覆盖测试，不改SQL/API/billing/DB或门禁。Dashboard明确“本月”，收入/用量明确“最近30日”；显示严格实际操作记录、覆盖率及legacy/partial/unpriced/usage_incomplete，并解释严格实际为完整逐模型用量与价格证据、历史不可复算为审计上线前缺少明细且系统不伪造回填；订阅收入明确为有效套餐人数×套餐价估算、非支付流水。独立首轮发现前端round/clamp可把损坏计数伪造成100%及解释不足，已退回收紧：六个计数字段必须为原生非负SafeInteger，strict<=total且五类合计=total，否则固定unavailable；最后才允许后端`actual_margin_ready=true`且total>0、strict=total显示实际毛利。最终独立PASS：FIN专项13/13、单worker全量Playwright66/66、相关Python66/66、全量unittest435/435（5 skip）、Production Readiness48/48、node/py_compile/Compose/diff check通过；无undefined/NaN/XSS/敏感字段或写请求，QA-004不回归。commit `f58c885` 已随 `c0a39ff` 推送；Push/PR GitHub CI `29193581641`/`29193582630` 均通过。登录后Staging只读Smoke确认Dashboard本月、收入/用量最近30日均为严格4/35（11.4%）、历史31、其余分类0，4+31=35；覆盖不足不显示毛利百分比并明确不可宣称实际毛利。收入¥598明确标注为有效套餐人数×套餐价估算而非支付流水；严格证据与历史不伪造回填解释均已显示，三页无undefined/NaN且console error为空。
- 验收标准：页面明确“最近30日、4条操作具备完整逐模型证据、31条为审计表上线前历史”；分类之和等于总数；覆盖不足仍不得宣称实际毛利；若展示新口径cohort，必须与全窗口混合估算并列且标注样本量/起始时间。
- 是否需要用户决定：只增加解释文案不需要；若现在新增独立“新口径实际毛利”指标，需要产品确认口径。
- 是否涉及真实外部调用：否；使用合成聚合与现有只读Staging数据。
- 是否已部署到 Render：是；说明优化、实时分类一致性与严格财务门禁均已通过登录后Staging只读UI验收。

### PROMPT-001 — Prompt 管理源与 V0.4 行业运行时漂移

- 状态：**VERIFIED**
- 优先级：High。
- 问题描述：Staging Prompt 管理列表/编辑器仍把“v0.3模型、10万+训练样本、CES、固定权重”作为当前基础 Prompt 展示；用户预期为 V0.4 且可审计的分行业策略。
- 证据：2026-07-12 只读 Staging UI 核对确认12项仍为旧标签/正文，当前示例 `agent_growth_system` 为v4修订号但正文仍是V0.3。仓库 `model/prompts.json` 12/12含v0.3，11/12含完整旧标题；文件自初始commit `906432d`后未升级。管理API直接返回PostgreSQL `managed_prompts.content`，前端原样展示。
- 根因是否确认：是。此前完成的是 `model/api.py` 的 V0.4运行时最高优先级覆盖、旧词中和、统一质量契约及按domain动态行业brief，没有迁移 `prompts.json` 或 `managed_prompts`。`init_default_prompts()` 对已存在key直接continue，Render持久库因此永不自动升级。管理页修订号v4/v5不是模型V0.4版本。
- 涉及文件：`model/prompts.json`, `model/prompt_baselines.py`, `model/prompt_composer.py`, `model/prompt_manager.py`, `model/api.py`, `model/admin_server.py`, `model/admin.html`, `scripts/render_predeploy.py`, `scripts/migrate_managed_prompts_v04.py`, `Dockerfile` 及Prompt/Render/UI测试；没有新增数据库schema migration。
- 风险：High。当前线上AI并非整体退回V0.3，因为运行时会前置V0.4规则和行业brief；但管理端无法审计最终有效Prompt，旧内容继续消耗Token并产生冲突。现有替换仅覆盖无空格`v0.3模型`，旧正文中的`v0.3 模型`可能仍进入实际Prompt。
- 执行代理：用户已确认采用推荐的“12条基础Prompt+行业有效模板预览”，指定单一 Implementation Agent；验证代理：独立 Prompt/Data Migration + QA/Security Verification Agent。
- 修改状态/进度：Implementation已完成12条V0.4基础契约、精确旧seed版本+SHA manifest、事务升级/history/idempotent/custom-skip/dry-run、完整hash+version+metadata+marker安全回滚、共享composer、API接入、Admin 7行业effective_template预览、Render predeploy和镜像内受控迁移脚本。两轮独立验证先后发现并闭环新增行未回滚、迁移脚本未打包、Prompt key存储型Admin XSS、元数据变化未阻断回滚、损坏/重复marker未收口五项阻断；真实PostgreSQL空库并发又发现主键竞争，已用apply/rollback共享的事务级advisory lock最小修复，未加重试/schema/表锁。最终本地全量unittest423/423（5 skip）、Playwright49/49、Readiness48/48、py_compile/diff/sensitive scan通过。一次性PostgreSQL 18由主控和独立验证代理分别通过空库、首条缺失、12旧seed、4路并发、实际4路predeploy、幂等和完整回滚；独立定向31/31，测试数据、容器和Colima均已清理。commit `87d679f` 两条GitHub CI均通过；Render deploy `dep-d99lhrr7uimc73f22slg` 已live，predeploy固定审计为missing=0/eligible=12/current=0/skipped=0，实际updated=12且无schema migration。Staging API/Admin/Web健康检查均为HTTP 200。管理端只读Smoke确认列表12/12均显示V0.4，抽查当前基础Prompt无V0.3/CES/固定权重，7个行业effective_template均等待刷新完成后与所选行业一致、包含V0.4运行时覆盖且不含V0.3/CES；旧V0.3仅保留在历史版本中用于审计/回滚。未保存Prompt、未调用AI、未产生积分或AI费用。独立验证证据完整，任务标记VERIFIED。
- 验收标准：已知旧seed按内容指纹/版本安全迁移并写history，管理员自定义不覆盖，重复执行幂等；基础Prompt不再含v0.3/CES/固定权重旧目标；七行业effective prompt差异可验证；管理端明确区分“基础可编辑Prompt”“V0.4运行时层”和Prompt修订号，并能按行业预览最终有效组合；SQLite/PostgreSQL/Render Staging一致。
- 是否需要用户决定：否；2026-07-12 用户已批准推荐方案，并确认管理员未手工修改过任何Prompt。机器迁移仍保留精确hash门禁，不因口头确认而放宽。
- 是否涉及真实外部调用：是；已执行一次性本地PostgreSQL 18并发验证、GitHub CI、Render Staging predeploy及只读管理端Smoke。Staging写入仅限12条已知旧seed升级及对应history；未调用AI、未扣积分、未改用户数据。
- 是否已部署到 Render：是；commit `87d679f`，deploy `dep-d99lhrr7uimc73f22slg` 已live，API/Admin/Web均已核验。

### PROD-001 — 正式支付订单/回调/对账

- 状态：**INVESTIGATING**
- 问题描述：已选定 Adapay 作为 V1 聚合支付方向，但商户准入、正式账本、下单、回调验签、原子权益、现金退款与日对账尚未闭环；由 `PROD-001A` 至 `PROD-001F` 分包实施。
- 当前现象：套餐/积分业务逻辑存在，但不能证明已收到真实款项。
- 预期结果：支付与积分发放强一致，可审计、可退款、可对账。
- 风险级别：Critical；仅生产商业上线需要。
- 涉及模块：payment、billing、auth、database、admin。
- 根因：已确认；此前只有积分业务账本和测试充值入口，没有真实支付事实账本。
- 修改状态/进度：供应商方向和内部退款/对账规则设计已完成只读审计；尚未提交 Adapay 申请或修改代码、数据库和云资源。
- 下一步：并行完成 `PROD-001A` 商务准入确认和 `PROD-001B` 产品合同确认，随后严格串行实施支付包。
- 验收标准：签名验证、幂等、金额校验、退款、异常补单、对账、审计测试全部通过。
- 真实外部服务：需要支付沙箱，生产切换另行批准。
- 费用/数据：可能产生支付/沙箱费用；严禁真实扣款测试未授权用户。

### PROD-002 — 生产数据库、备份、域名与恢复演练

- 状态：**INVESTIGATING**
- 问题描述：目标已改为阿里云华南完整生产主系统；生产基础设施、数据库、备份/PITR、域名、监控与恢复演练由 `PROD-002A/B` 实施。
- 当前现象：适合测试，不符合商业生产可恢复性。
- 预期结果：付费 PostgreSQL、备份/PITR、监控、域名/TLS、恢复演练完成。
- 风险级别：Critical；Render 环境限制。
- 涉及模块：Render DB/Web、DNS、migration、runbook。
- 根因：已确认；当前只有 Render Staging 测试规格，仓库无阿里云生产部署工程。
- 修改状态/进度：目标拓扑和代码差距只读审计完成；尚未创建阿里云资源或迁移数据。
- 下一步：确认华南具体地域、域名、预算、RPO/RTO与初始容量，再建设隔离生产环境。
- 验收标准：备份可恢复、迁移可回滚、域名/CORS/回调地址正确、故障演练通过。
- 真实外部服务：需要 Render/DNS。
- 费用/数据：持续付费并涉及真实数据迁移，必须单独批准。

### PROD-003 — 视频缓存横向扩展与零停机

- 状态：**TODO**
- 问题描述：API 挂载单实例磁盘，Render 挂盘服务不能无缝横向扩容/零停机。
- 当前现象：Staging 单实例满足短期测试。
- 预期结果：生产按真实流量决定对象存储/任务队列或保持单实例的可接受方案。
- 风险级别：Medium；仅高并发生产明显。
- 涉及模块：视频上传/缓存、部署拓扑。
- 根因：当前最小成本架构选择。
- 修改状态/进度：目标生产架构已确认迁出 Render 业务磁盘/Cron；具体对象存储、缓存和Worker方案由 `PROD-003A` 实施。
- 下一步：在阿里云基础设施规格确认后设计最小对象存储与Worker方案，不等待正式流量才处理生产阻断项。
- 验收标准：缓存可恢复、并发和重启行为可预测、成本明确。
- 真实外部服务：可能需要对象存储/队列。
- 费用/数据：可能新增持续费用；必须批准。

## 6. 已知问题与风险

### Critical

- **原有/商业上线**：`PROD-001` 正式支付闭环未确认。
- **生产环境**：`PROD-002` Free PostgreSQL 无备份且会到期，不能承载正式用户数据。
- **长期安全**：任何 Secret/Cookie 泄露到 Git 或日志都会造成账号与费用风险；当前 tracked files 检查未发现 `.env` 或 XHS session 文件。

### High

- **跨账号缓存防回归**：`SEC-005` 已修复并以双合成账号在 Staging 独立验证；仍保留为认证/本地缓存改动的回归项。
- **SSE 持久恢复边界**：`PERF-001B` 已修复客户端终态/分帧/不确定态；断线后的 durable result replay、stale lease 与副作用/退款一致性仍归 `BILL-002`，不得宣称完整恢复。
- **持续运维**：`OPS-002` XHS Cookie 可能自然失效；提醒机制已部署但仍需人工更新。
- **原有结构**：前端手工 payload 与后端 Pydantic 模型可能漂移；行为修改需 contract/e2e 双验证。
- **权限**：用户 auth 与 admin auth 均能影响积分/配置，任何修改都必须负向权限测试。

### Medium

- **媒体/管理端 UI 防回归**：`QA-003C/D/E` 已在 Staging 闭环；后续需防止多图旧批次回填、视频迟到响应、账本敏感字段/原型键回归。
- **Render 特有**：管理端 Free 服务可能冷启动；不等同于 API 故障。
- **架构选择**：`PROD-003` 视频缓存依赖单实例盘，部署有短暂中断。
- **模型质量**：通过 V0.4 分数不自动代表自然度长期稳定，仍需持续 golden/人工抽检。

### Low

- 无独立 lint/typecheck script；当前依赖 py_compile、unit、static/e2e 和 CI gate。
- 本机缺少 Git LFS filter 时三份 `.lgb` 会显示 modified；这是工作树表现，不是业务改动。不得 stage、revert 或重新生成这些文件，先安装/恢复 Git LFS 环境再处理。

## 7. 测试基线

### 7.1 本轮实际重新运行或真实执行

- 本地全量 unittest：403/403 passed，5 skipped；全量 Playwright：48/48 passed；Production Readiness：48/48。QA-003D 验证中曾有1次既有Chat stall时序波动，原用例单独重跑通过，最终全量证据为48/48。
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
- GitHub Actions：`bf0c4be` 两条 CI 检查通过；包含 py_compile、artifact check、全量 unittest、quality gate、production readiness gate、Docker Compose config。
- Playwright/e2e：既有内容意图与约束链路门禁通过；本轮未重新跑文件选择。
- SQLite 模式：通过既有单元与本地开发测试。
- PostgreSQL 模式：Render API/Admin/Cron 真实运行及 migration/readiness 通过。
- Docker build/API container：Render build 与容器启动通过；本轮未重复本地构建。

### 7.3 尚未运行或需要条件

- `QA-003C/D/E` 已完成，不重复真实媒体/AI验证。
- P50/P95 性能剖析：`PERF-001`，真实样本数与费用预算尚未确认。
- `SEC-005` 已完成，不重复真实双账号验证。
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
4. `PERF-001B` 与 `QA-003C/D/E` 已完成本地独立验证、CI、Render部署和无付费Staging Smoke，禁止重复修改。
5. `STG-001`、`BUG-001`、`BUG-002`、`BILL-001`、`FIN-001`、`QA-001`、`QA-002`、`QA-003A/B/C/D/E` 已完成，禁止重复大范围修改或重复付费验证。
6. `SEC-005` 已由独立 Security/Browser Verification Agent 与Staging两个合成账号闭环，禁止重复真实验证。
7. 商业上线第一代码包为 `ARCH-001`；只收口 Claude Transport 和旁路，不在同一包创建Gateway、修改支付或部署阿里云。
8. `PROD-001A` 商务准入与 `COMPLY-001` 可并行推进；payment/billing/database/共享调用链的写入必须按账本严格串行。
9. `SEC-004` 仅做结构统计，执行历史清理前必须确认备份/回滚窗口；`BILL-002` 必须在跨区域生产灰度前闭环。
10. 每个修复包完成后更新本账本、独立验证、记录部署环境和剩余风险；付费资源、生产数据、真实支付、DNS切流和最终上线仍需用户明确批准。

## 11. Do Not Touch Without Approval

- `model/billing.py` 及套餐/积分/退款语义。
- `model/auth.py`、`model/admin_auth.py`、权限依赖与管理员接口。
- `model/db.py`、`model/migrations/postgres/`、任何数据库写迁移。
- `render.yaml` 中付费规格、数据库、磁盘、Secret 与生产域名。
- S3 IAM、对象删除/覆盖、模型 manifest/registry 与发布产物。
- XHS Cookie 值、授权账号和大规模采集参数。
- 支付、生产环境、生产数据、DNS 和回调地址。

## 12. Checkpoint 记录

- 2026-07-12 commit `2776d7c` 已推送并部署 Render Staging；两条 GitHub CI 通过，API/Admin readiness 200，pre-deploy 应用 `0006_model_usage_records.sql`。
- `FIN-001` 已用 Analyze、Generate、Chat Rewrite 与 Kimi Vision 四条真实 Staging 操作闭环严格逐模型成本；历史31条不伪造回填。`QA-003A`、`QA-003B` 已本地独立验证并完成云端复验。
- 真实 Smoke 同时为 `PERF-001B` 提供 Analyze 34%、Generate 0% 和 Chat 终态延迟证据；`SEC-005` 跨账号本地缓存泄露已修复并由后端计费前阻断、前端owner隔离和双账号云端Smoke三层闭环。
- 2026-07-12 `SEC-005` commit `513675d` 已通过两条GitHub CI、Render部署与双账号无AI/无扣费Staging Smoke；本地任务账本补充云端证据但暂不再次提交，避免仅文档触发第二次部署。

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
