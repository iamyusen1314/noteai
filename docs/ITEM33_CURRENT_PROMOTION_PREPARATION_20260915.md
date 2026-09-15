# Item33 当前本地准备 — 2026-09-15

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
