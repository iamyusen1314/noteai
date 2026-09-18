# Item33 当前本地准备 — 2026-09-15

## September18 当前：源码94d已在原F暂存，唯一续执行已核实

源码checkpoint `94d101b2cd48a3c5d83235083cc715de245b3e34`补齐安装后、正式周期前的独立恢复。
旧`b291bd2`私有包封存未使用；最后恢复检查发现完整catalog失败会阻断原拆除，修复只允许精确
原activation/body/28trigger撤销，并保留NOWAIT/0run/0admission/无在途及UNKNOWN限制。
35项teardown/outer测试通过（含8项真实PG）、新增3项IO恢复测试通过；独立审查无阻断。
初始fixture时钟/输入错误修正后通过，未放宽真实验收。正常terminal仍要求完整catalog、seal、
3连接关闭、拆除和normal handoff。Item32八份accepted业务源码和执行器未改。

私有`source-package-94d101b`在无Git、无psycopg、network-none/readonly/tmpfs环境逐字校验，
19固定模块和原依赖loader通过。原F43条唯一暂存命令成功、无重发，56源码/11运行文件核验通过；
archive486607B/SHA`42764f02849f5405d02fdeb3c1a7a524a59db1e91707c5cc46ceab71d81785e5`，
source manifest6652B/SHA`f89077be2a5065fe8c87bb5ce51649ccdefbbc17baadb1897074360854de41c7`。
stage为`/var/lib/noteai/item33-source-staging-20260918-94d101b`，实际原回执999B/SHA
`f7c7b71ba786f477db337e6487fdc4bbffa19a406f3f1f0d8dc97b752939622e`已一次只读取回repo
`deploy/production/evidence/production-item33-source-staged-20260918.json`。
**仅源码暂存：供应商0、DB操作0、unit不变、collector未启动，Item33尚未通过。**

当前plan2939B/SHA`50c2ff3ce72eaefec407c3e32206d59b5de9b264fb4389497b6585cbd7acbb79`，
recorded_at13:21:15.928096UTC；原私有13:04计划保留历史，同activation未执行。
既有Item33接续授权下，唯一窗口 **Sep19 01:00–02:30UTC／北京09:00–10:30**，
启动严格早于 **01:35UTC／09:35**，准备从00:45UTC／08:45开始。现场必须fresh0/34，
最多2初始化＋34采集、零自动重试。Sep18的Item32消耗34不能因DBtoday0而重置。

唯一heartbeat `noteai-item33-sep19`已于13:41:47.873UTC创建ACTIVE，绑定原线程；工具view及
原配置2984B/SHA`db366d9ec588ad949da892917f63de26d70e3c544d07348547795cfcf8fe5ee5`读回核实，
其他3项均PAUSED。安全投影在`production-item33-continuation-scheduled-20260918.json`。
原应用纯调度函数算得Sep19 00:45UTC／北京08:45唯一唤醒，无jitter；未读取内部nextRunAt，
未声称已触发。保持本机和Codex运行；晚于截止不启动、不自动改期，终态/失窗暂停该任务。
本机源码桥已关闭，原F与DMS会话保留；原支付SQLConsole、H5 scope及所有正式服务不变。

### 同一受控入口的实际操作顺序

固定入口为`/var/lib/noteai/item33-trends-promotion/source/tools/run_item33_trends_promotion.py`，
每次带`--source-manifest-sha256`实际固定值；只用原F和原DMS已登录noteai_admin会话。

1. 核真实时钟、固定源码、原Item32封存与七锁、原3ed7 suspended unit/18f72会话、无旧在途。
   00:45前只读准备；`prepare-install`只导出SQL和真实catalog，不执行DDL或供应商请求。
2. 在独立DMS SQLConsole执行**原install.sql完整事务一次**，保留实际执行记录/成功COMMIT与
   操作开始和完成观察时刻；未知不填写COMMITTED或重发。将实际回执O_EXCL保存为
   `capture/operator-install-execution.json`，再运行`finalize-config`。
3. 到01:00且严格早于01:35时仅运行一次`rehearse`，云助手外层超时应容纳35分钟及恢复。
   collector READY及实际fresh0/34后才promote；本周期最多2初始化＋34采集，物理HTTP和admission
   独立记录、零自动重试。真实source/质量/SQL/事务journal及单例rollback/reapply全部满足才向下。
4. `prepare-teardown`只导出原SQL；DMS实际执行29项精确DROP事务后保存原回执
   `capture/operator-teardown-execution.json`，再`finalize-teardown`。确认3连接关闭、collector无残留，
   才`normal`交接同八源码的正常daemon；同桶只读skip，不多采一轮。
5. 保存host生成的13份原件和terminal candidate原字节，逐份bytes/SHA验证并运行原Item33 gate。
   `TERMINAL_CANDIDATE_ASSEMBLED_NOT_GATE_CREDITED`不是Item33通过；真实通过后才更新canonical分数。

### 安装后前周期失败的独立恢复（94d已验证）

`prepare-recovery`只允许原COMMITTED安装回执及SQL绑定、实际unit已停/worker0/collector0，
读取真实`recovery-before` catalog，导出`outer/pre-cycle-recovery.sql`；原失败记录保留。
SQL只对本activation的函数/body及28个trigger做精确核对、NOWAIT锁、原桶run/admission0和全局无
running/UNKNOWN检查，29项DROP无CASCADE、无业务DELETE/ACL改变。其他ACL/FK不合验收不阻断撤销本对象。
任何对象身份漂移、活动或未知不伪造清理成功。恢复可跨日，真实观察日期与原activation桶分别保留。

DMS真实成功后回执为`capture/operator-pre-cycle-recovery-execution.json`，schema
`noteai.item33.pre_cycle_recovery_execution.v1`、status COMMITTED、activation_identity_sha256、
operator_role、sql_sha256、真实started_at/committed_at、control_plane_ddl_count29、outcome_unknown_count0。
`finalize-recovery`读取独立after，要求实际catalog等于before去掉本capture对象，才记
`PRE_CYCLE_CAPTURE_REMOVED`且readiness_credit=false；存在恢复marker即不得再走rehearse/normal。
已经开始过业务周期而没有完整seal的失败不适用零采集恢复：只读原action/IO/数据库与实际停态，
处理具体未决状态，不重跑周期或冒充终态。一般UNKNOWN只用`readback-only`及原件读取。

## September18 12:50UTC工程收口（仍未生产安装/采集）

Item32原件与`834eb09`恢复点复用，Readiness仍33/37。Item33完整主机入口及源码包正在收口；
**尚未创建定时续执行，尚未安装捕获、promotion、生产写入或供应商请求。** 今日剩余34额度为0，
新的正式周期只能在Sep19或更晚UTC fresh桶。未来计划时点不等同已经安排或启动。

已完成并定向验证的组件：

- Controller/host/actions/teardown：V5真实来源继承、原子单例切换、一次rollback/reapply与同桶
  normal handoff；66项组合通过，后续stdlib拆除改稿11项通过（含4真实PG和无site-packages加载）。
  原F系统Python3.11.6确实无psycopg，纯验证已消除该主机依赖；数据库检查复用原6d5镜像。
- 事务捕获与catalog：36项组合通过；后补线程存活/已知失败清尾拒绝，禁止以seal替代close。
  只在无表/列写权限、无直接EXECUTE的禁止表上保留既有不可达保护trigger；八张可写表的
  trigger/函数/FK/表达式路径仍严格核验。单列INSERT权限反例真实PG通过，未更改任何生产ACL。
- Preflight8项及DB周期读回9项真实PG通过；物理HTTP reader11项、Item33 gate合计57个不同
  用例通过。HTTP与实际34条admission绑定，初始化独立计数；Item32函数AST未改。
- Collector service8项、真实事实组装14项通过；before READY先验证实际catalog，封口后必须
  3连接关闭/无线程未知/无failure文件/collector容器0。pure terminal assembler7项通过原Item33
  gate的完整合成证据用例；这些仍是本地测试，不是生产验收。
- Container IO15项加安全失败保留2项通过，并实测Linux memfd seals；仅原Trends DATABASE_URL
  在内存传给检查/collector，不传Cookie或SSK，不落日志。Docker行为为注入测试，未在F运行。
- Runtime CLI8项通过，含2项真实隔离PG安装/失窗事务回滚；单次cycle最多61次只读状态观察，
  每30秒一次，成功后读原周期，失败/needs_manual/多run即停。这些是DB观察，不是业务重试。
  测试先有重复模块类型、已有crawler_events fixture冲突，修正测试接线后通过；没有生产重试。

原F仅增加一次host依赖只读probe：`12:42:25.716046UTC`、Python3.11.6、psycopg=false，
供应商0/DB0/服务变更0，原件投影见`production-item33-host-python-readonly-20260918.json`。
加上原DMS两条catalog SELECT，仍没有DDL/ACL/业务数据变更。所有本任务隔离PG容器与卷已清理。

生产源码包只带Item33代码及两项已接受依赖的有限原件；本地原rollback Git单项校验errors=[]已
固定成`item33-dependency-validation.json`（SHA1dd9cc4a…18d039），F逐字重核原证据/validator/source，
Item32仍运行原四artifact语义校验。不会在F复制整个仓库、Git历史或重跑全部37项。

安装后任何前周期失败都有精确activation/body/trigger guard的PRE_CYCLE拆除SQL，要求run/admission0；
正式周期后只有真实seal/catalog/close证明才能生成终态拆除。控制面安装/拆除DDL单独计数，
不得混入业务DDL0；其他支付/媒体保护及普通用户服务保持。

## September18 12:05UTC阶段历史（工程进行中，未启动生产周期）

Item32已在source `e7f3345`、原F/6d5镜像/八overlay上真实通过，原终态SHA
`1456a938acba00a12a9b547dd13e4054ef89b4bca05597363808007be28eb584`，checkpoint `834eb09`。
今日Sep18隔离采集消耗34，即使生产DB今日0也不能再次称fresh。Item33需更晚UTC桶，
最早Sep19 00:00UTC仅为下界；当前没有可执行完整CLI、生产排程或新增周期。

已完成本地组件：

- V5 controller/host actions：绑定原accepted终态、6d5/87b9镜像及八份源码；验收activation
  与daemon首次INSERT时生成的真实run身份分开。保留原入口allowlist及原3ed7 suspended unit
  CAS恢复，旧legacy分支保留。39项隔离测试通过，独立源码审查未发现阻断。
- 真实PG16 preflight：专属角色/表列序列ACL、外schema写权限、UTC fresh ledger及server-enforced
  readonly/noXID/rollback；8项真实PG16隔离测试通过。capture范围与业务DDL证明仍单独处理。
- 真实PG16 cycle reader：同一REPEATABLE READ READ ONLY事务核对真实run/34attempt identities、
  snapshot原字节摘要及原六域质量/两来源规则，输出实际health/freshness和ledger；缺失物理HTTP、
  DML、DDL、重试证据不填0或true。9项真实PG16测试通过（含非UTC会话还原），测试资源已清理。
- V5 gate原29项＋新10项局部测试通过，仍在接真实journal/seal；此局部结果不是最终gate放行。

仍在实施：writer BEGIN后登记/ACK、持续LISTEN与fsync journal/count封口、真实触发器/规则/FK
可达范围核对、安全HTTP日志投影、实际host/DB/collector callbacks及终态组装。instrumented unit
仅限验收UTC桶；必须在封口及同桶rollback/reapply后，以同镜像/八源码恢复正常launcher并真实读回，
才能作为长期managed服务交付，不把验收临时hook跨日拒绝当作正式服务完成。

原DMS现有登录读到DB时刻20:05:09.668902+08／12:05:09.668902UTC，执行唯一系统catalog SELECT成功：noteai_admin、PG160013、
public CREATE=true、八表owner成员可管理、已存在Item33函数0。安全准备证据在
`deploy/production/evidence/production-item33-control-plane-readonly-preparation-20260918.json`。
无DDL/ACL/业务数据修改、无供应商调用；这不证明runtime角色fresh、capture安装或Item33终态。
原支付SQLConsole保留，使用独立新SQLConsole 1；正式微信/高德/报告/权益与H5 worktree均未改动。
后续第二次只读函数目录查询发现两份既有媒体保护trigger函数；body摘要与原迁移0026/0028逐字一致，
security-definer=false。其原代码只校验NEW/OLD、无DML；正式catalog仍需核真实绑定/返回类型及可达性。
不因这些已知保护函数而移除权限、停用保护或把全库重审加为新门禁。实际安全元数据同上证据。

以下旧日期状态保留历史，由本节与Handoff CURRENT覆盖。

## September17 16:30UTC定向依赖核对（未启动Item33）

Item32 source1136898已完成36响应/34采集，但本地来源/数量验收失败，原件已封存HOLD；
它**不是**Item33可用的accepted terminal。后续运行版本应绑定真正通过的来源和八份候选overlay，
不能把本地修复、网络恢复或当前1136898当作Item32通过。当前仅完成以下只读准备，未改Item33源码/生产：

- Item33 gate仍明确拒绝v3，controller/renderer仍旧a78镜像与三overlay；未来需要独立V5分支，
  精确绑定实际accepted terminal、6d5镜像、实际overlay集合和managed-unit摘要；保留旧分支历史。
- 现有`publish_transaction`已把关键词、snapshot、health、freshness、snapshot evidence与run成功
  放在同一事务；attempt记录在外，可复用。`claim_daily_run`在事务中首次INSERT前才生成run ID，
  所以writer注册不能只依赖之后才设置的active lease。
- 八表DML部件已有SQL与非终态聚合，仍缺真实writer事务注册、连续LISTEN journal、关闭封口及
  CLI实际callback连接；额外instrumentation来源必须单独绑定，不能冒称在Item32 overlay里。
- 真实前置保持：较Item32通过日更晚UTC的fresh0、unit suspended/无在途、实际最小ACL/trigger/可达表
  核对、journal覆盖所有目标事务和八表distinct rows、rollback/reapply没有第二周期。它们是工程
  依赖和事实证明，不是新增owner审核体系。Item36资源创建继续等Item33等必要前置，避免空转计费。

## September15后续本地进展

八表SQL生成与distinct-row/真实txid聚合部件已实现，13项真实PG16隔离测试及独立review通过。
详见`docs/ITEM33_DML_CAPTURE_PREPARATION_20260915.md`。这补充下文“尚未实现collector”的
部分工作；仍没有生产listener/事务hook/持续journal与封口，不将聚合部件当完整collector。
实际writer/source绑定、fresh覆盖和DDL事实仍缺，不连接生产或复用5ce。

## 当前结论

本轮完成原 Item33 controller 的 unit renderer、三个实际宿主动作 callback 和对应隔离测试。
这是**局部本地准备**：没有生产 CLI、完整 DB/cycle/DML capture readers 或真实运行身份，
没有启动服务、创建 admission、读 Secret、连接生产或增加 readiness 分数。
owner 已授权在真实 Item32 terminal 和原 internal rollback 满足后接续 Item33 及必要实施/恢复；
当前缺口是实际前置和生产接线，不能以重复审批或手填 `verified: true` 代替。

## 已实现的最小改动

- `tools/execute_item33_trends_promotion.py` 继续使用原依赖校验、fresh 5 分钟 preflight、
  不同 UTC 桶、最多 34 provider admissions、零自动重试，以及一次 promote→cycle→rollback→reapply。
  renderer 只给原 singleton 增加三份只读来源挂载并解除 suspended；不直接调用 `--once`。
- `tools/item33_trends_host_actions.py` 仅实现 promote/rollback/reapply。
  每次动作先校验真实 canonical 依赖和较晚 UTC 日；动作内通过现有 IMDSv2 模式精确绑定
  API-F `i-wz9bgztwf1tiakww2ops`，再检查 unit fragment、无 drop-in、来源文件和宿主权限。
  不以文件 hash 代替主机身份。
- 固定动作目录 `/var/lib/noteai/item33-trends-promotion`，root:root 0700；
  原 rollback 字节及各阶段 `STARTED_UNKNOWN`/applied 文件均 O_EXCL。
  文件 fsync 后同步父目录，首次建目录也同步父目录；动作异常保留原记录，不自动重放。
  unit 采用前后 SHA compare-and-swap。每次 `daemon-reload` 后、紧邻 `enable --now` 前再次校验
  原授权/原 promotion UTC 桶；跨桶保持 UNKNOWN 且不启动，安全 rollback 可以跨日。
- action receipt 的 `provider_calls=0` / `production_database_writes=0` 只表示该 unit callback
  自身的直接操作；daemon 的真实请求/写入必须由独立 cycle/capture readback 证明。
- readiness gate 的 Item33 小范围兼容由另一位 agent 独立维护：当前 release 保留原七字段并增加
  `image_source_sha256`、`runtime_overlay_sha256`、`item32_terminal_sha256`，绑定真实 accepted Item32；
  legacy 七字段/旧 unit 仍保留历史，但不能搭配当前 effective Item32 来源。
  供应商费和增量云费允许实际非负金额或 `UNKNOWN`，未知不能填 0。

精确来源与恢复：

| 对象 | SHA256 / 固定路径 |
| --- | --- |
| 冻结 XHS image | `a78f4753591fd824ef3e4cfd8ed229c32542d1ac50d3c8c03b529e71fd01f8ec` |
| 原 suspended unit / 原字节 rollback | `3ed7e555d61c8286ab6d1116d99171d23d073b6a318dbd4890ce3106b976e3b6` |
| 当前三挂载 managed unit | `0a1c100462e62e9043ef0b73d81a8b12b85bd684b90c9e1d3a24e0a705fb88ff` |
| legacy flag-only promoted unit（历史） | `13d777c7705cc1dbc539c3dad3e034ba0ce5226b038e355d91bd3a440e565f8c` |
| 正式只读 overlay 目标目录（存在性待 fresh 读回） | `/var/lib/noteai/xhs-trends-runtime/1be2fde/model/` |
| `spider_xhs_http.py` | `360a43f781e55e2c529387e70ef7be3b5f47a716bf6ede56d3daaaefa9b6bea1` |
| `security_redaction.py` | `c5fc02966035a01012a1a35b7005f3a62a72602c042e98dbad707029ca56f451` |
| `hot_keywords.py` | `77ff2a7e6b279d35a65f1dc497d32c92cc3bf46c061f0e42229dc42e3b81fc6d` |

正式 overlay 两级目录要求 root:root 0700；三文件要求 root:root 0444、普通文件且 nlink=1。
不能把 Item32 临时运行目录直接挂成长期运行来源，也不能覆盖两份前驱或 Item32 固定 WORK_ROOT。
若后续真实 capture 必须增加事务 hook/来源，须审查并重新绑定实际源码及 unit；不冒充仍只有这三份来源。

## 生产前必须取得的 fresh 事实

1. 实际 canonical Item32 terminal 完整校验通过、精确 SHA/UTC 桶/五份 effective source；
   原 `production-internal-failure-rollback-verified-20260814.json` 及 manifest binding 有效。
   Sep15 Item32 计划/包存在不等于 terminal 已通过。
2. 唯一 API-F 身份、systemd manager/fragment/drop-ins、上述原 unit、冻结 image、实际 module 来源；
   原 unit 必须 inactive/dead/disabled/suspended，formal container=0；action 根目录不存在旧 UNKNOWN。
   同时记录其他 NoteAI units 状态以供最终原样读回；本工具只操作 Trends。
3. 生产角色确为 `noteai_xhs_trends`；fresh 角色属性、继承、表/列/sequence ACL、相关 trigger/rule/FK
   与原合同相符，禁止 DELETE/TRUNCATE/DDL；不重跑迁移或全量重审角色。
4. 当日配额 used=0 / remaining=34；active run、同桶 run、unknown outcome、unlinked attempts 均为 0。
   这些值必须来自真实 ledger 和前驱状态，不能由计划或本地 fixture 推定。
5. 完成真实只读 preflight/cycle/promoted/rollback/final readers；readback 本身无 provider 调用。
   cycle 必须由原 daemon 自行 claim 唯一 daily lease，30 分钟内同桶完成，1 cycle、请求全部已知，
   六行业每行业 12–15 个真实关键词，总计 72–90；最终 health/attempt/lease/恢复均需实际读回。
6. 在任何相关 schema/ACL/绑定文件或服务变更前，确认原 noteai-5ce 旧窗口任务未处于
   prepare→close/final-readback；不触其 collector、订单、回调、退款、任务或结果目录。

## 八表 DML 捕获是真实剩余工作

原 gate 要求**实际不同业务行的写入数**和事务边界，不是表行数净增量：

| 表 | 应触及的不同业务行 |
| --- | --- |
| `xhs_trends_runs` | 1 |
| `xhs_trends_service_state` | 1 |
| `xhs_trends_provider_attempts` | 实际 request_count，最多 34 |
| `hot_keywords` | 实际 keyword_count，72–90 |
| `keyword_snapshots` | 同 keyword_count |
| `xhs_crawler_health` | 6 |
| `xhs_freshness_ledger` | 6 |
| `xhs_trends_snapshot_evidence` | 1 |

还须实际证明 out-of-contract/delete/truncate/DDL 为 0，六个禁止写入组
`system_settings/crawler_events/tracking/authentication/billing/payment` 均无写入，
业务 pack、snapshot 与 run success 同事务提交，provider attempt audit 在该事务之外。
前后 COUNT(*)、最终快照或源码看似原子不能证明上述事实；UPDATE/先删后增/重复写都可能被净值掩盖。

最小后续方案是沿既有提交后通知、实际 writer/transaction 绑定、持续监听和 fsync journal/seal 的
捕获方式，按 fresh 可达表/触发器范围做 Item33 定向接线。现有 `tools/collect_item31_canary_dml.py`
是 Payment 专用：不能直接改 provider 名称、复用 5ce 激活身份/监听/触发器或把它当作已可用的 Trends collector。
必须保留真实 txid 和不含用户内容的稳定行标识，覆盖可能的间接写入；断连、丢事件、无法证明写事务归属或
capture 未封口均 UNKNOWN。临时捕获安装/拆除的控制面 DDL须单独如实记录，不混成业务 cycle 的 DDL=0。
本轮尚未实现或安装这个 collector；待真实 Item32 结果后完成必要接线与对应本地验证，再启用生产 daemon。

## 实际窗口和恢复

若 Item32 在 2026-09-15 UTC 桶完成，Item33 只能在 Sep16 或更晚的不同 UTC 桶开始。
Sep16 00:00UTC 只是数学下界，不是当前派发时间；实际窗口尚未选定。
优先等待旧 noteai-5ce 的 Sep16 02:01:30UTC 任务完成 close/final-readback，并在 capture/host 前置齐备后
选择当天能容纳 30 分钟 cycle、读回及恢复的窗口。不能拿旧 Sep7 或本地 synthetic 时间直接运行。

原控制器保留一次 rollback/reapply 演练；reapply 只在原 promotion 同 UTC 桶进行，依赖原 daily-run
完成事实避免第二轮请求。任何 UNKNOWN 保留动作/业务身份，仅按原结果只读恢复；不自动重试或造新身份。
跨日启动被拒绝后若 unit 文件已变更，必须读取该原 UNKNOWN 记录和实际 unit/容器再安排恢复，不能重跑 promotion。

## 验证与文件归属

本 agent 修改 controller、新增 host callbacks、本文件及 `tests/test_item33_trends_promotion_executor.py`；
另将 Item32 的 PENDING 负例改为临时 synthetic 副本，避免真正获批的 canonical plan 使测试错误失败。
未修改已绑定 Item32 executor/plan、共享 Handoff、生产状态或七个受保护路径；没有自行 commit。

最终聚焦验证：原 Python 3.11 镜像 `noteai-media-tests:py311-sdk`，`--network none --read-only`，
源码只读 bind、仅 `/tmp` 可写，显式 `--entrypoint python` 和测试/tools PYTHONPATH。
Item32 三组及 Item33 两组 **115/115 PASS，4.041 秒**；包含 promotion/reapply 在 reload 期间跨桶不启动、
错误 API-C 主机在文件/服务动作前拒绝、file→directory fsync、依赖拒绝和 UNKNOWN 不重放。
本阶段首轮 111/111 通过，三项审查修正后 115/115 通过；没有新的失败测试。
日志中的 HOLD/UNKNOWN 来自隔离负例，不是真实生产结果。
