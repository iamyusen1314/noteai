# NoteAI Render Staging 正式交接

更新时间：2026-07-12（Asia/Shanghai）

本文件是当前阶段唯一 handoff。历史聊天记录不是事实来源；后续会话必须重新核对 Git、Render 和测试状态。

## 1. 项目当前阶段

- NoteAI 已部署到 Render Staging，正在进行功能检测、缺陷修复和回归验证。
- 当前不是正式生产上线阶段；不得把 Staging 通过等同于商业上线完成。
- AI 诊断、爆文生成、对话优化、截图/视频理解、事实源、积分账本和管理端已完成受控的真实 Staging 验证。
- 正式支付订单、回调签名、幂等、退款与对账流程尚未确认，是独立的生产阻断项 `PROD-001`。
- `BILL-001`、`FIN-001`、`SEC-005`、`PERF-001B`、`QA-003A/B/C/D/E` 与 `BUG-002` 已闭环；BUG-002 由四个连续自然健康轮次完成验证，未追加手工高频采集。生产事项仍保持延期。

## 2. 当前环境与版本

### 2.1 Git

- 仓库：`iamyusen1314/noteai`
- 当前分支：`codex/quality-stabilization-real-chain`
- 当前业务代码基线：`87d679f0c972f100c884a8f6f6bcdcb66d55da77`（`fix: migrate managed prompts to v0.4`）；QA-003C/D/E 分别包含于 `9eebc8c`、`3041d87`、`bf0c4be`。
- Render Staging Web/API/Admin 已包含 `87d679f`；API deploy `dep-d99lhrr7uimc73f22slg` 已 live，pre-deploy `migrations_applied=0` 且12条Prompt基线已为current。新会话仍必须重新核对 Render Events 中的 live commit。
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

- 状态：**VERIFIED**
- 优先级：Critical；当前最高优先级调查项。
- 问题描述：自然 Cron 的 `search_result` 与 `search_recommend` 持续为0；累计 freshness 仍可能满足，但最新单轮明确 degraded。
- 证据：自然 run `19a8c433-923e-4a06-a26f-d1c5aa506d37` 首目标进入 challenge 后熔断11个目标，09:05 run `5a22df29-373f-4ec5-8291-ad85541d95ff` 在6小时 cooldown 中安全跳过12/12搜索目标。冷却后连续四个自然轮次 `478f3783-…`、`5559f473-…`、`ce83808b-…`、`6a686edd-…` 均恢复四来源且非手工触发。最新完整轮次 `6a686edd-d1e2-49bf-a072-e8d8e6b5b136` 于18:05开始、18:13成功结束，采集520条（homefeed119/search_result206/search_recommend75/hot_search120），质量处理后405条且四来源无缺失；固定分类为note_result14/generic_json964/unknown_schema0/empty_result0/business_error12/non_json123，challenge_before_target_payload0、diagnostic_error_codes空、circuit closed。19:05自然轮次已启动但未用作成功证据。
- 根因是否确认：是。来源归零直接原因是短暂 XHS challenge 与随后6小时 cooldown；熔断/冷却按设计工作并自然恢复。BUG-002D 已把普通辅助JSON与真正note_result分开，连续健康轮次均出现真实note_result且unknown_schema=0，没有证据支持平台schema改名或继续修改解析器。
- 涉及文件：`model/scheduler_a.py`, `model/xhs_acquisition.py`, `tests/test_xhs_acquisition.py`, `tests/test_render_deployment.py`；不改 Cookie、UA/viewport、频率、challenge绕过或数据库。
- 风险：平台挑战仍可能未来复发，现有策略会安全降级而不是绕过。静态审查另发现generic_json候选隔离及推荐路径变体的防御性边界，但最新轮次note_result>0、recommend items_raw>0，未触发这两个条件；若后续出现note_result=0但search_result>0或recommend json_ok>0但items_raw=0，再分别建立独立修复包，禁止凭猜测修改。
- 执行代理：Repository Explorer + QA Investigator + Test Finder（只读）；验证代理：独立 Render/DevOps Reviewer，结论 PASS。
- 验收标准：已满足。固定分类可区分真正note_result与普通JSON；冷却后连续四个自然轮次search_result/search_recommend均非零，最新轮次challenge=0、unknown_schema=0、错误码空且成功结束。
- 是否需要用户决定：否；脱敏诊断修正不改变产品策略。若要改变challenge策略、采集频率或账号操作则需要。
- 是否涉及真实外部调用：仅只读观察自然Cron与公开readiness；未手工触发、未改变频率、Cookie、指纹、重试或challenge策略。
- 是否已部署到 Render：是；熔断/冷却commit `878787b` 与诊断分类commit `aa1f866` 均已在线，四个连续自然健康轮次完成云端验证。

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
- 是否已部署到 Render：否。

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
- 是否已部署到 Render：否；本地独立验证已完成，待与BUG-002E批量推送后部署，避免两次连续Render构建。

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
- 是否已部署到 Render：是；commit `2776d7c`，pre-deploy 已应用 0006，API/Admin ready，真实成本 Smoke 已闭环。

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
5. `STG-001`、`BUG-001`、`BUG-002D`、`BILL-001`、`FIN-001`、`QA-001`、`QA-002`、`QA-003A`、`QA-003B` 已完成，禁止重复大范围修改或重复付费验证；`BUG-002` 父任务仍等待自然观察。
6. `SEC-005` 已由独立 Security/Browser Verification Agent 与Staging两个合成账号闭环，禁止重复真实验证。
7. `QA-003C/D/E` 不得合并为一个修复包或并行修改共享前端文件；`SEC-004` 仅做结构统计，执行历史清理前必须确认备份/回滚窗口；生产事项继续延期。
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
