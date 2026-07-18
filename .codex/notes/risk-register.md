# Risk Register

Last updated: 2026-07-18

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
- 2026-07-14进展: 商业V1已选择免费默认服务密钥保护RDS/OSS静态数据，但该能力不能保存第三方Secret。起步方案使用ECS RAM Role/STS和受限部署注入，阿里云增量¥0；软件KMS加最低凭据配额约¥2,748/月延期。正式部署前仍须验证root-only权限、进程环境暴露面、日志脱敏、两节点分发、轮换和撤销runbook，因此风险未关闭。

### Real payment integration is not confirmed

- 风险描述: Adapay 已被选为 V1 方向，但 Billing/topup/upgrade 仍只有业务积分和测试入口；正式订单、回调、权益、现金退款、积分批次和对账尚未实现，且商户准入与三通道网页能力尚待书面确认。
- 涉及文件: `model/api.py`, `model/billing.py`, `model/db.py`, frontend pricing/credit UI.
- 可能后果: Users may receive credits without real payment, or paid launch cannot legally/financially reconcile transactions.
- 建议验证方式: Locate/implement payment provider flow only after approval; test order creation, callback signature verification, idempotency, refunds, reconciliation.
- 是否需要用户确认后才能修改: yes.

### Alibaba production topology is not deployed; Gateway Staging is single-instance only

- 风险描述: 目标为阿里云华南完整生产主系统、Render Singapore 仅 Claude Gateway；ARCH-001已收口runtime调用，ARCH-002单实例Gateway已在Render Singapore Staging完成云端验证，但现有全栈Staging仍使用Local transport，阿里云主系统、2–4实例Gateway安全化和生产切流均未完成。
- 涉及文件: `model/model_router.py`, `model/api.py`, `model/billing.py`, `render.yaml`, deployment scripts and future Gateway service.
- 可能后果: 阿里云主系统无法按目标拓扑上线；部分请求仍直连 Claude；跨区域重试导致重复供应商费用；逐模型 usage/cost 漏记；未鉴权 Gateway 被滥用。
- 建议验证方式: 生产前完成共享原子防重放/限流、精确主机绑定、远端健康、timeout与partial-stream费用边界，然后建设阿里云并执行灰度/回滚；持续证明Gateway无业务数据库和持久内容。
- 是否需要用户确认后才能修改: transport 收口不需要；创建付费 Render/Alibaba 资源、真实 Claude Smoke 和生产切流需要。

### Claude Gateway shared control plane is verified on single-instance Staging, not Production scale

- 风险描述: ARCH-002P-A/B已在单实例Staging闭环；commit `d279caa`使用AWS Singapore DynamoDB与Render OIDC运行共享nonce/rate/operation/renewable fenced lease，真实credential method、TTL/IAM边界和双客户端单赢家均已无AI验证。但精确Gateway host/readiness/timeout、Render真实2–4实例、滚动/扩缩/崩溃/OIDC刷新/store断路组合尚未验证，Alibaba主系统的Kimi/queue与持久结果恢复也未完成。
- 涉及文件: `gateway/claude_gateway.py`, `model/claude_gateway_protocol.py`, `model/model_router.py`, `render.gateway.yaml`, `infra/aws/claude_gateway_control_plane.yaml`, ARCH-002P-C/D和BILL-002相关实现与测试。
- 可能后果: 当前共享状态不会在已测并发下重复claim，但生产切流仍可能因错误host、timeout层级、配置漂移或控制面中断导致Gateway拒绝新Claude调用；若Alibaba恢复链未完成，用户操作可能不可用或停在不确定态。
- 建议验证方式: 串行闭环C、BILL-002和D；执行精确authority/DNS/TLS/readiness/timeout合同，再做2→4→2、store全断、滚动、重启、取消和Key轮换矩阵。控制面不可达时Gateway继续保持零新Claude调用，Alibaba仅对可证明未dispatch的operation安全Kimi/排队。
- 是否需要用户确认后才能修改: C与FIN-003已验证；D的2–4实例基础费用已获批准，执行前只需列明演练窗口及是否动用剩余真实Claude次数。生产切流仍需单独确认。

### Alibaba production infrastructure exists, but application and recoverability do not

- 风险描述: 生产VPC、C/F两台私网API ECS、一套跨可用区高可用RDS、一套高可用Tair和VPC级SNAT/公网出站已付款并运行；但ACR不可变镜像、生产应用、ALB/TLS绑定、业务DNS、备份/PITR、对象存储、Worker、监控和恢复演练尚未闭环。
- 涉及文件: future Alibaba deployment/IaC or runbooks, database predeploy/migrations, storage/worker adapters, DNS/CORS/payment callback configuration.
- 可能后果: 正式用户数据丢失、服务单点、无法恢复、回调不可达或配置漂移。
- 建议验证方式: 隔离生产环境部署；备份恢复到一次性实例并逐表对账；灰度、故障、容量、监控和回滚演练。
- 是否需要用户确认后才能修改: yes，涉及持续云成本、域名和生产数据。
- 2026-07-16进展: SMQ（原MNS）两队列目标约¥30–31/月、主域企业DNS加基础防御¥1,168/年、基础ICP备案服务¥0、恢复演练临时实例建议4小时上限¥30/24小时上限¥120/单次硬上限¥200，均已完成未下单报价。产品负责人已购买 `noteaipro.cn` 与防御性 `noteaipro.com`；独立云端核验确认两域名均为“正常”且有效至2027年7月，自动续费未显示开启。主域`.cn`为企业持有者；`.com`为个人持有者且仅作防御性占位。产品负责人已明确接受该差异，`.com`不得承载生产/备案，企业过户记为未来可选项而非上线门禁。根域/API/Admin三份正式Rapid DV为¥1,455/年；免费测试证书90天且不用于正式业务。备案核心文档要求ECS累计大于3个月；优先选择官方99计划2核2GiB/3 Mbps/40 GiB、¥99/年备案专机，并在购买后验证“可备案实例”，否则回退既有API节点续费3个月加1 Mbps、追加¥916.20。正式域名/TLS/备案ECS/DNS包首年规划¥2,845，完整月均规划¥3,850.88，首月含按量计提参考¥6,458.80。除两个域名外，其余资源仍未购买；99计划资格、证书换发、备案实际通过、恢复演练和最终DNS切换仍是生产上线门禁。
- 2026-07-16企业DNS付款前复核: 官方购买页已按 `noteaipro.cn` 单域、企业旗舰版、DNS攻击基础防御、1年配置，自动续费未勾选，实时应付¥1,168，与已批预算一致；页面停留在“立即购买”前，未产生订单或费用。付款后需独立核验实例与主域绑定，正式解析记录和DNS切换仍保持独立门禁。
- 2026-07-16防御域主体迁移: 产品负责人报告 `noteaipro.com` 已迁移到与主域相同公司名下，主体差异不再阻塞生产主线；等待阿里云域名列表的后续只读复核后再补云端 VERIFIED 证据。`.com`仍只作防御性占位，不购买第二份企业DNS、不承载生产或备案。
- 2026-07-18当前事实: 生产空库已完成`0001`–`0008`结构migration，未导入Staging数据或Prompt基线；企业DNS已绑定主域，根域/API/Admin三张正式证书已签发但未绑定。历史“未购买”报价只保留作决策证据，不再代表现状。生产应用、ALB、业务DNS和恢复能力仍未完成，因此不得宣称已上线。

### Commercial V1 cannot yet admit 100 simultaneous AI jobs

- 风险描述: 产品负责人已确认商业上线首阶段必须可靠受理100个同时AI任务（Claude或Kimi均可），未来扩展到1000个；当前API/AI执行仍耦合于请求进程，Claude Gateway自设全局并发2/RPM30，Kimi真实账号配额未核验，且没有供应商无关持久job、独立Worker、队列SLO或升级监控。V1必须先用PostgreSQL权威任务账本和安全claim/lease/fence闭环，消息队列只能在outbox之后作为至少一次唤醒通道。
- 涉及文件: `model/api.py`, `model/idempotency.py`, `model/model_router.py`, `model/billing.py`, future `ai_operations/task_queue/ai_worker`, PostgreSQL migrations, Alibaba SMQ/MNS/RocketMQ/IaC, SLS/CloudMonitor/Admin monitoring and `CAP-001/OPS-003` tests.
- 可能后果: 峰值任务被429/超时、断流后丢结果、Worker崩溃重复调用或重复扣费、Claude/Kimi雪崩切换、余额/Token配额耗尽后商业服务中断。
- 建议验证方式: 先以FakeProvider证明100任务均在2秒内持久受理，重复消息/崩溃/数据库短断下0丢失、0重复provider/扣费；再用小样本真实Claude/Kimi校准leaf时长、Token和成本，按队列深度/最老年龄及provider/model配额设置分级告警和升级Runbook。
- 是否需要用户确认后才能修改: 本地状态机、测试和监控合同不需要；阿里云付费资源、migration、真实AI样本、自动扩容预算及任何供应商/消费门禁升级需要。
- 2026-07-18进展: `CAP-001A1/A2A`实现已提交于`199bf5f`，生产空库已应用`0007/0008`，但提交后独立diff/回归/部署边界验证尚未闭环，故两任务为`READY_TO_VERIFY`。公开202、CAP A2B、独立Worker、Tair接入、队列/背压、持久结果和退款对账仍不存在；100个同时AI任务能力尚未达到。

### ALB health semantics could turn a Gateway outage into a whole-site outage

- 风险描述: 若ALB使用要求Claude Gateway在线的AI readiness作后端健康检查，Gateway或新加坡链路故障会同时摘除两台仍可提供登录、账务、历史结果、Kimi或排队服务的Alibaba API节点。
- 涉及文件: `model/api.py`, `model/admin_server.py`, ALB健康配置、Claude readiness tests和生产runbook。
- 可能后果: 单一AI供应商故障被放大为全站不可用。
- 建议验证方式: ALB仅探测进程、PostgreSQL和必需本地模型；以Gateway全断场景证明两API节点仍健康且Claude不会被不安全重试。
- 是否需要用户确认后才能修改: 本地合同不需要；真实ALB配置或生产故障演练需要批准。

### Cross-border Claude data boundary and China launch compliance are unresolved

- 风险描述: 阿里云主系统通过新加坡 Gateway 调用 Claude 时，Prompt、正文和聊天上下文会跨区域；当前 Chat 多模态路径还可能传递图片/base64。用户告知、数据最小化、备案/许可适用性、隐私/退款条款和第三方处理者清单尚未按目标拓扑完成专业确认。
- 涉及文件: Claude transport/Gateway, Chat multimodal routing, privacy policy, user agreement, refund policy, data retention and compliance records.
- 可能后果: 超范围传输、用户告知不足、支付入网受阻或监管风险。
- 建议验证方式: 建立字段级数据地图；默认在阿里云用 Kimi Vision 转文本后只发送必要文本；由中国执业律师或合规顾问确认最终文件和路径，技术验收核对实现一致。
- 是否需要用户确认后才能修改: yes for final product/data policy; safe minimization tests and documentation inventory can start read-only.

## High Risks

### Production secret storage and Admin logs need a second redaction boundary

- 风险描述: XHS Cookie设置虽标记`is_secret`仍以明文JSON落库；Admin日志接口可返回底层日志尾部，尚无独立allowlist/redaction保证。
- 涉及文件: `model/runtime_settings.py`, `model/admin_server.py`和SEC-007测试/迁移。
- 可能后果: 数据库、备份或日志暴露Cookie、URL/query、正文、Prompt、Token或异常原文。
- 建议验证方式: 建立SEC-007，先证明现状，再做可回滚密文迁移和固定枚举/计数日志；全程不打印真实值。
- 是否需要用户确认后才能修改: 本地测试/日志脱敏不需要；生产migration或Cookie轮换需要批准。

### PostgreSQL connection/recovery and node-local video recovery are unproven

- 风险描述: RDS已运行且空结构migration完成，但无确认的生产连接池、连接预算、故障重连或PITR恢复演练；视频恢复仍依赖单节点六小时本地缓存。
- 涉及文件: `model/db.py`, `model/api.py`, PROD-002B/PROD-003A/CAP-001A2B及恢复测试。
- 可能后果: 连接风暴或主备切换后应用不恢复；跨节点、重启或发布时视频任务丢输入。
- 建议验证方式: 上线前验证连接池/断连退避和一次隔离PITR；视频改为owner绑定的私有对象引用并通过跨节点/重启/过期测试。
- 是否需要用户确认后才能修改: 本地合同不需要；真实恢复实例、OSS或production migration需要批准。

### Render Blueprint Sync Hook may require rotation after controlled-tool exposure

- 风险描述: ARCH-002P-D核对Render Blueprint设置时，受控页面自动化快照意外包含真实Sync Hook值。本账本不保存该值，但必须按潜在泄露处理并由`SEC-006`跟踪轮换。
- 涉及文件: 不涉及仓库文件；Render Blueprint凭证与运维runbook。
- 可能后果: 未授权的Blueprint同步触发、部署或配置干扰；盲目断开/重建Blueprint又可以造成服务漂移。
- 建议验证方式: 仅通过Render官方自助入口或Support轮换，证明旧Hook失效；不读取/打印新值；复核Auto Sync=No、Gateway min2/max4、环境配置和手工回滚能力未变。
- 是否需要用户确认后才能修改: 无损自助轮换可作为最小安全处置；若需断开/重建Blueprint或联系Support，须先告知用户影响。

### Cross-account Chat cache can expose a previous account's note snapshot

- 状态: Mitigated and verified on Render Staging by commit `513675d`（2026-07-12）；保留本条用于防回归。
- 风险描述: 前端使用未绑定用户的全局 `noteai_chat_session` localStorage；登录/注册和慢/失败 `/auth/me` 恢复链可能把账号 A 的标题、正文、评分、版本及 session/note 标识展示给账号 B。
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, Chat/auth 前端 tests；防御纵深可能涉及 `model/api.py` Chat session ownership load。
- 可能后果: 共享设备、token 失效或同页账号切换时发生跨账号机密性泄露。后端当前在计费和写入前拒绝异账号 session，但不能阻止缓存内容先显示。
- 建议验证方式: 两个合成账号脱敏哨兵 E2E；覆盖慢/失败认证、注册/登录身份变化、logout、403 清理、同账号刷新恢复；API 继续验证所有权检查先于计费/写入。
- 是否需要用户确认后才能修改: no，最小安全修复不改变产品、计费或数据保留政策。

### SSE progress and terminal recovery can leave successful paid work looking stuck

- 状态: 客户端/协议部分已由 `PERF-001B` 在 Render Staging 验证（commit `2579c08`/`f8b98b4`）；持久回放、stale lease 与副作用/退款一致性仍由 `BILL-002` 跟踪。
- 风险描述: 真实 Staging Smoke 中 Analyze 阶段继续推进但百分比停在34%，Generate 停在0%，Chat 正式内容返回后输入框仍延迟恢复；当前客户端 parser/终态状态机和 durable replay 边界不完整。
- 涉及文件: `NoteAI_Pro_Demo_Framer.html`, `model/api.py`, SSE/Chat e2e 与 contract tests；持久回放另涉及 billing/db/migration。
- 可能后果: 用户误以为付费任务失败、重复提交或离开页面；断流/重启窗口可能出现结果、usage、退款和幂等状态不一致。
- 建议验证方式: `PERF-001B` 不重复实施；下一阶段仅以 `BILL-002` 做 PostgreSQL 故障注入、stale lease 和 durable result replay 验证。不得自动重试付费 AI。
- 是否需要用户确认后才能修改: 客户端/协议兼容修复不需要；migration、结果保留期限和真实故障 Smoke 需要。

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
