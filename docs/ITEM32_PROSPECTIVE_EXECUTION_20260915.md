# Item32：新的只读 Trends 执行提案

状态：**AUTHORIZED_AWAITING_WINDOW_AND_FRESH_PREFLIGHT / 已获本次具名授权，尚未派发**。

Owner确认首次时间读回为2026-09-15T13:11:36+00:00，明确批准下述9月15日14:00–15:00UTC、
dispatch严格早于14:40的一次范围及必要恢复；真实终态满足后接续Item33。
当前批准包已在API-F准备并通过主机纯读取验证，不能提前执行或跨窗启动。

13:33UTC前准备完成：源码commit `79e1e35`，十文件包177406bytes，SHA
`2d3e2d49c2f2e67d987544b885c6411bf12e71195fadff18db48c8a3e1b6c124`。
私有OSS上传及原F角色internal Get成功，host目录
`/var/lib/noteai/item32-successor-package-20260915-79e1e35`；原unit/前驱未变、successor root不存在。
主机Python3.11.6与approved `_load_plan`通过，尚无provider请求/DB连接。
窗口内唯一入口为该目录`dispatch-once.py`（SHA8556e082…4916f1），用`python3 -E -B`，
带O_EXCL的started/child/done及0600日志；它不替代原executor唯一admission。
断线只读原日志/结果/PID，不再次提交；退出0仍要四份真实Evidence通过原validator。
本机私有包/入口/回执位于`/Users/openclaw/.codex/tmp/noteai-item32-prospective-20260915/`。

这是新窗口的执行范围与时间提案，不是可运行 JSON、生产调度或新 admission。
本次只读核查基于工作树 HEAD `3eeb84a7edda7334c214c07bb735f6d0a3362bcc`；
不改变 Readiness 31/37、旧两身份、原 Sep7 plan 或任何既有生产状态。

## 1. 已有授权与本次确认

- 本次 owner 新窗口接管明确授权继续普通工程和既有范围内的本地准备，
  并要求先核对生产授权、在确实缺失时集中给出完整范围与时间。
- `AGENTS.md` 的 September13 授权覆盖既定产品实现、必要真实验证、受控发布与恢复，
  不恢复旧 50/100 元临时模型金额门槛。
- 但当前 `.codex/handoffs/current-task.md` 的 CURRENT EXECUTION CONTROL 明确将
  Item32 列为“需新生产授权与未来 prospective plan”，并单列待决定的唯一只读
  Trends successor；`internal-deployment-readiness.json` 的 `real_xhs_trends`
  使用相同约束。因此不能用一般授权推定已批准本轮 34 次新生产请求。
- Sep6 历史批准的是 Sep7 UTC 桶、23:40Z 前 dispatch、Sep8 UTC 前结束。
  该窗口已经过期，历史“立即继续”不再调度本次工作。

下文一个窗口、一轮请求、现有隔离执行和安全恢复现已获owner明确确认；
前述“缺少具名授权”是批准前事实，不再阻断此范围。无需再逐技术步骤请求批准。

## 2. 可确认的窗口

| 字段 | 本次提案 |
|---|---|
| 最早开始 / `not_before_utc` | 2026-09-15T14:00:00+00:00，北京时间 9 月 15 日 22:00 |
| UTC 配额桶 / `bucket_date_utc` | 2026-09-15 |
| dispatch 截止，严格早于 | 2026-09-15T14:40:00+00:00，北京时间 22:40 |
| 必须完成，严格早于 | 2026-09-15T15:00:00+00:00，北京时间 23:00 |
| 实际 collection 最长等待 | 沿原 executor 的 900 秒超时，余量用于原结果读回与清理 |

该窗口在提案时留出至少一小时供 owner 确认及本地绑定准备，并在原唯一微信
`noteai-5ce` 的 2026-09-16T02:01:30Z 前结束。若确认或准备晚于 dispatch 截止，
本提案失效；不自动移到次日、不自动换桶、不创建第二次调度。

日配额所需 `used=0 / remaining=34` 是**运行前必须重新证明的条件**，
本次本地只读核查没有连接生产数据库，不能声称已经 fresh 实测可用。

## 3. 请求、费用和数据范围

1. 仅原 API-F 主机上的既有 Trends 隔离路径，一轮 `market_timing_worker.py --once`。
   沿用现有合法会话和固定 signer/User-Agent，不新建或更换 XHS 账户；遇到实际
   登录失效、challenge、访问拒绝或限制就停止并说明具体情况，不绕过。
2. 一轮和 2026-09-15 UTC 桶均**最多 34 provider admissions**；固定顺序为
   `homefeed` 10 次，之后 12 组 `search_recommend` + `search_notes` 共 24 次。
   原六领域为美食、旅行、穿搭、美妆、家居、健身，每领域 2 个既有检索种子。
   这是既有 Trends 六领域采样，不能混同产品的七行业 Prompt。
3. 自动重试 0。完整通过要求实际 34 次均成功、UNKNOWN 0；提前失败时保留较少
   的实际 admissions，不通过补调用凑满 34。两条封存历史请求各 1 次、合计 2 次，
   保持原日期和结果，不作为新桶已用数或重放对象。
4. 最多 90 个关键词；六领域各至少 12 个合格真实来源，且每领域同时有合格检索
   和推荐来源。`industry_baseline` 仅可补展示行，不计真实来源通过数。
5. 采集容器仅持会话和隔离 `/task` SQLite 结果，**不接收 `DATABASE_URL`**。
   三个经审核源码 overlay 只读挂载，只有任务目录可写；容器 rootfs 只读、
   0.5 CPU、512 MiB RAM，沿用既有镜像，不启动新计费云资源。
6. 前后两个短命数据库 probe 使用既有账号和 `BEGIN READ ONLY`、
   `default_transaction_read_only=on`，仅读取服务器/会话身份哈希、Trends 活动与
   blocked 计数、当日 attempts 计数及本事务写统计，再 `ROLLBACK`。
   不授予权限、不改 schema/ACL、不写生产业务表、不改变用户/支付/积分。
7. 现有源站请求/网络的实际增量费用尚无本轮账单，**不能宣称免费或给出虚构上限**。
   本轮没有 Claude、Kimi、豆包推理，没有新订阅、充值或长期资源。
   保留历史成本/未知费用，按实际可得记录归集；若需新购买或账号付费升级则停止另决。
   模型费用授权不挪作 ALB 费用。
8. 只保存既有私有运行结果、脱敏 receipt 和四份既有 Evidence；Secret、Cookie、
   连接串与用户素材不进入 Git/公开包。无内容发布、无用户素材上传或支付动作。

## 4. 授权后原路径的实际前置检查与执行

### 本地绑定准备

当前恢复包实际校验通过：

`/Users/openclaw/.codex/tmp/noteai-item32-current-source-20260915/noteai-item32-current-source-1be2fde.tar.gz`

SHA256：`2e597b9e8c585446d900a5632f34459d6bd40add94d5d316df23025859313797`。

初次接管核查时源码与 `1be2fde159d944e8ae301f6bd3ff7965151c4e9f` 一致；
该原包及原 90 项 PASS 是保留的恢复基线。后续本地准备已在相同 executor/terminal
validator 修复时间绑定；该旧包没有被覆盖，也不能当成包含本轮改动的新执行包。

当前已在本地完成的**现有**机制：

- 保留 Sep7 plan 原文件和历史 SHA 不变，增加固定 canonical 文件
  `deploy/production/plans/item32-readonly-successor-prospective.json`，schema v2；
  原 executor 拒绝旧 v1 plan，现有 terminal validator 指向新的 prospective 文件。
- 四个时间字段唯一来自该 plan；executor 和独立 terminal 检查 UTC 格式、同桶、
  开始/截止/结束排序及至少 20 分钟结束余量，不再每次改代码中的日期常量。
- 该 plan 的 `authorization` 已由真实owner确认改为 `AUTHORIZED`，
  `confirmed_at_utc` 记录首次确认时间读回，`approved_scope_sha256`绑定既定范围。
  实际执行须先通过它，才允许创建 work root、
  接触 host/Secret、容器或 admission；terminal 也拒绝 PENDING。
  真正收到 owner 确认后才记录确认时间和批准范围 SHA。SHA 绑定除 authorization
  以外的整份计划，防止改日期、来源或范围后沿用旧批准；它不是 owner 数字签名。
- 保留原 admission 前时间检查，并在最后两项 host 检查后、真正启动前再次确认
  时间；若期间越过截止，已写 admission 保持 HOLD，启动次数 0，不允许重放。
- 实际 collection/attempt 时间及 terminal 必须落在批准区间，不能仅凭仍在同一
  UTC 日接受超出 15:00 的结果。停止或过窗后的必要安全清理仍应完成。
- frozen image 的原三源码 SHA 与 effective overlay 来源继续分开；Item33 legacy
  release 常量、34/UTC 日、0 retry、原 work root/前驱/结果恢复保持原机制。

实际确认后只补真实授权字段及最终 plan/package SHA 绑定，按 allowlist 保存/上传
匹配源码并做 fresh preflight；不需要重建/切换 API、Admin 或 public web 镜像。
若窗口失效，保留真实授权与原窗口记录并停止启动；另行提出未来窗口，不能倒填或自动改期。

### fresh 生产前置与唯一启动

- 先确认旧微信任务尚未进入 prepare。若已进入，等待它的原 close/final-readback
  完成；期间不改 API/Admin/Payment/public web/nginx、schema/ACL 或其绑定文件。
- 在**相同** `/var/lib/noteai/item32-readonly-successor` 路径读取现有 admission、
  export、隔离 stores 和容器状态，确认没有已 dispatch/未读回结果；有任何留存就
  先做原结果恢复，不新建 work root 掩盖它。
- 保持两个 predecessor 的 admission/store/result/HOLD digest 不变，取得既有锁。
- 核对原 Trends 单元 inactive/dead/disabled，固定 Trends 容器不存在；固定 image、
  unit、manifest、signer 和三 overlay 的实际来源与 SHA 匹配。
- 原 runtime readback 距启动不得超过 15 分钟；前置 probe 证明 active/manual=0、
  session blocked=0、当日 production attempts=0，并与前驱日期及隔离 store 一起
  证明本次桶 `used=0 / remaining=34`。不重置、删除或修饰任何旧计数。
- 只有所有条件满足并仍在批准窗口内，才由原 executor 写入一次 `O_EXCL` durable
  admission，然后执行一次 `docker start --attach`。批准本提案允许这一单次新
  admission；本地提案阶段没有创建它。

## 5. 结果、停止与恢复

- 已开始后超时、失败、UNKNOWN、掉线或导出中断均不得二次 dispatch。
  原 executor 先按登记的容器 identity 安全停止/移除，确认任务 label 集合为空，
  清理临时 Secret/runtime 文件；保留 admission、私有 SQLite、worker receipt、
  历史结果和供原路径只读恢复的隐藏 candidate。
- 回来时使用原 executor 的 `--readback-only` 和原保留记录核对；结果缺失/不可读
  就保留 UNKNOWN/HOLD，不当成 0 次请求，不恢复为“未开始”。仅继续确切未完成的
  安全清理，不创建新身份或调用供应商补证据。
- 成功后仍需前后 probe 的零写证据、完整真实来源、两前驱未变、清理完成及现有
  terminal validator 通过，才更新 Item32。HTTP 200 或关键词数量本身不计通过。
- 使用既有四个 Evidence 名称：`production-item32-xhs-trends-attempt-audit.json`、
  `production-item32-xhs-trends-snapshot.json`、
  `production-item32-database-zero-write-proof.json`、
  `production-item32-xhs-trends-readonly-verified.json`；不预先制作通过结果。
- Item33 只能在实际 Item32 terminal 和 internal rollback 满足后接续，且不得在
  Item32 消耗完的同一 UTC 桶 dispatch。Owner当前确认支持按原范围接续Item33；
  此窄窗只运行Item32。Item33真实日期、fresh配额及原依赖另按实际核对，
  不在本轮暗中并入第二轮请求；本地host callbacks仍缺完整真实DML capture来源。

## 6. 已获确认的原范围文本

> 我授权在 2026-09-15 14:00–15:00 UTC（北京时间 22:00–23:00），最晚严格早于
> 14:40 UTC dispatch，按本提案在原 API-F 执行唯一一轮 Item32 只读 Trends
> successor。先证明 fresh used0/remaining34，单轮及当日最多 34 admissions，
> 0 自动重试，复用既有合法会话、隔离 SQLite 与生产 DB 前后只读零写证明。
> 允许匹配本窗口的既有 executor/新计划/原 terminal validator 本地绑定、必要回归、
> 私有包上传与一次 admission/启动，以及原结果读回和安全清理；保留真实费用/未知
> 费用，不新增资源、订阅、充值、账号或新请求重放。失窗或前置失败停止，不自动改期。

## 本轮本地验证

- Python 3.11 缓存容器、`--network none`、仓库只读、只给 `/tmp` 临时写入；
  不传生产 env/Secret，不调用远端 Docker 或供应商。
- 最初启动器沿缓存镜像默认 ENTRYPOINT 改变工作目录，5 个模块均报
  `ModuleNotFoundError: No module named 'tests'`，实际用例未开始；这是保留的启动器
  失败，未据此改业务源码。改为明确 Python entrypoint 和 `/workspace/tests` 路径。
- 修正后 99/99 PASS；新增未来确认时间负例后，最终 **100/100 PASS**，包含
  Item32 successor executor、execute flow、terminal evidence，以及 Item33 promotion
  executor/evidence 两组既有回归。测试输出的 HOLD/provider_calls 都是隔离 mock，
  不能当作生产调用或真实结果。
- 覆盖 PENDING 在所有状态/host/Secret/admission 前拒绝、v1 旧计划拒绝、批准范围
  修改失效、未来确认拒绝、UTC/跨日/余量、窄窗口起止、最后 host 检查耗尽窗口时
  start=0 且 admission HOLD/不重放、零写/来源绑定/清理未知，以及 Item33 次桶约束。
- `git diff --check` 通过。旧 Sep7 plan SHA 不变；未修改两个 predecessor 或七保护路径。
- 当前 executor SHA256：`b7a1060062a4500841de3c9b7ac17c492b804acff6411230b216221bb7eba8b6`。
  PENDING plan SHA256：`e616804fa38afe923c6b141cd0afd22c62cde0d41ef12d6515c008b1e5ace039`。
  terminal validator SHA256：`7839830eb5d86524447a358a34f4e0265ec2ffe9f5fed449801e138520a5eaab`。

## 核查依据

- `.codex/handoffs/current-task.md`：CURRENT EXECUTION CONTROL / Item32 待决定 / 详细依据索引。
- `docs/PRODUCTION_DEPLOYMENT_EXECUTION_PLAN.md`：September15 source1be2fde，
  及 September9 recovery 的 prospective rebind / no-replay 说明。
- `tools/execute_item32_readonly_trends_successor.py`：`_load_plan`、
  `_admission_budget`、`_assert_dispatch_window`、`_run_db_probe`、
  `_create_collection_container`、`_snapshot_quality`、`_execute_locked`、
  `read_retained_result`。
- `tools/internal_deployment_readiness_gate.py`：Item32 canonical plan binding、
  effective runtime source binding 和 successor terminal 检查。
- `deploy/production/plans/item32-readonly-successor-20260907.json`：封存历史计划，
  当前 SHA256 `f74b053b6647d47a0f8061462d0d87dd181c3a11c8b5fa59c7369fd4f4ad27a3`。
