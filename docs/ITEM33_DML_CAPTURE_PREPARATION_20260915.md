# Item33 八表 DML 部件 — 2026-09-15

## September18 当前增量

现已补齐writer真实BEGIN/事务身份登记、计数提交通知、持续LISTEN、fsync journal、start/end
barrier、封口后的独立catalog及连接/线程关闭证明，并新增仅本次activation的安装/拆除和
PRE_CYCLE恢复SQL。94d101b已补齐完整catalog拒绝时仅撤销本activation的独立恢复，
35项teardown/outer及3项IO恢复测试通过。原F仅暂存56源码/11运行文件，未安装捕获或执行业务；
唯一Sep19 08:45北京续执行已核实，09:00–10:30周期且启动<09:35，现场fresh和原验收仍待证明。
八份accepted Item32业务源码不变，额外两份hook及launcher独立绑定。
实际实现、定向测试及仍未执行的生产边界以
`docs/ITEM33_CURRENT_PROMOTION_PREPARATION_20260915.md`顶部为准。
本地通过不等于真实八表写入/正式Item33通过；没有触碰Item31/5ce或Item34。

以下September15内容保留当时边界，未实现的表述不再代表最新本地实现。

## September15 已完成范围

新增 `tools/item33_trends_dml_capture.py` 与对应测试，提供纯 SQL 生成、真实事务通知记录的
去重/聚合和原 Item33 八表/atomic-publish 合同子集检查。模块没有连接选择、生产 CLI、
自动安装、后台 listener 或服务操作；没有加载 Item31/5ce collector，也未修改原 controller/gate。
这是一份可独立验证的接线部件，未安装生产，不增加 readiness 分数。

- 只使用独立的 `noteai_item33_*` 函数、trigger、channel 和事务设置名。
  `CREATE FUNCTION/TRIGGER` 不采用 replace/if-not-exists；重装会报错，不覆盖现有对象。
- 生成前必须有八表准确主键和六个禁止写入组的定向表清单；额外表只能归到禁止组或
  `out_of_contract`。安装前 SQL 检查真实 public 普通表与主键列，缺表、分区表、主键变化均失败。
  清单和 key-shape 检查不代替真实 ACL/trigger/rule/FK 可达范围核对。
- 精确 `session_user=noteai_xhs_trends` 的写入必须带该 activation 与当前事务绑定；缺失即 SQL 失败。
  该角色导致的嵌套触发器写入也按 session_user 捕获。实际运行必须证明身份和角色权限匹配，
  本地测试授予的宽权限仅用于构造 DELETE/TRUNCATE/禁止表负例。
- 每个通知含真实 `pg_backend_pid()`、`pg_current_xact_id()`、独立 event UUID、稳定主键摘要和
  操作类型。原始 run ID、关键词、snapshot、details 等内容不进入通知/聚合结果。
  行摘要为 activation + 表名 + 按主键列顺序排列的 JSON 值之 SHA256；同一业务行多次 UPDATE
  保留 mutation 次数，但 distinct-row 只计一次。主键变更计入两个身份并标记越界。
- `xhs_trends_runs`、attempts、snapshot 的 run 归属在数据库内与已绑定原 run ID 的 SHA256 比较；
  run-success 仅记录实际 UPDATE 从非 succeeded 到 succeeded 的布尔事实。
  business pack 五表与 run success 必须只出现于同一真实 txid，attempt audit 必须在其外。
- NOTIFY 在提交后才交付；SAVEPOINT 回滚/整事务回滚不产生已丢弃行事件。
  DELETE、TRUNCATE、禁止组写入、其他越界写入均保留实际次数，不能用净增量抹去。
  未注册 sender、错误 txid/nonce/context、重复 event、终态缺失或终态后事件均为 UNKNOWN。

## 明确剩余接线

输出状态固定为 `ROW_CAPTURE_AGGREGATED_NOT_TERMINAL` 或 `UNKNOWN`，`readiness_credit=false`。
`cycle_contract_errors()` 只检查已有八表/事务合同的可计算子集；返回空列表仍不代表 capture 或 Item33 完成。
模块不填 `ddl_count=0`，也不构造完整 `production_write_set`。以下真实事实仍必须取得：

1. 在每个实际 writer 的显式 BEGIN 后、首次业务 DML 前执行事务绑定，从数据库读出 pid/txid，
   向持续运行的 collector 完成 durable registration 后才允许 DML；提交前发送绑定 completion。
   nonce 本身或 caller 字典不证明注册完成。本部件不包含 daemon 的这些 hook。
2. receiver 必须从 PostgreSQL Notify 对象取得 `sender_pid`，不能信任 payload 自报；持续监听、
   start/end barrier、admission closure、fsync journal/seal、断连/提交响应 UNKNOWN 的处理仍需接线。
   不能删除 UNKNOWN 并恢复 LISTEN 或重放旧业务。纯聚合无法发现被整体遗漏的已提交事务，
   也无法发现少掉一条重复触及同一行的 mutation。针对性用例保留了这种“计数仍符合、捕获仍未证明”的边界。
   sender PID 校验不能识别已绑定 backend 自己伪造的 `pg_notify`；真实 writer SQL/source 绑定及禁止
   在业务路径另发伪造 capture 通知仍须接入持续采集证明，不能声称全部伪造均可由聚合识别。
3. fresh schema、精确 session role/ACL、trigger/rule/FK 可达表和六组映射核对；尚未知道的表不能猜测。
   schema guard 只证明列/主键存在，不证明触发器无法被绕过、全覆盖或无其他 writer。
4. 业务窗口 DDL=0 必须由实际权限/变更捕获与执行边界证明。临时 collector 安装/移除的控制面 DDL
   另行如实记录，不混为业务零 DDL。移除前需核对已安装定义和原 activation，纯 removal SQL 本身
   不是生产恢复入口。
5. 真实 writer hook 可能改变 `trends_contract`/事务路径，需要按实际修改重新绑定 accepted source、
   overlay 和 unit；不能继续声称只有现有三份 overlay。没有为此新增审批门禁。

生产接线及安装沿用既有授权，但仍等待真实 Item32 terminal、原 internal rollback 与 Item33 fresh 前置；
Item32 本次 pre-admission 失败不满足 terminal。不得与原 noteai-5ce prepare→close/final-readback 并发
更改相关 schema/ACL/服务/绑定文件，不能复用其 activation、监听、trigger 或恢复目录。

## 本地验证与恢复

测试仅连接固定 Unix socket `/var/run/postgresql` 上的 `noteai_item33_local`，显式环境开关
`NOTEAI_LOCAL_PG16_ITEM33_TEST=1` 才启用；进一步检查 PG16、`inet_server_addr() IS NULL` 和数据库名。
测试加载原 `0003_market_timing.sql`、`0004_xhs_freshness.sql`、`0011_trends_execution_contract.sql`，
构造完全 synthetic 的72关键词、1 admission、六行业八表写入，未读取生产 DSN/Secret/数据库。

首轮 **12/12 PASS，0.907 秒**。包含 distinct 行与 mutation 的差异、同事务发布/拆分发布、attempt
错误内置、savepoint/整事务回滚、嵌套禁止表、改主键/delete/truncate、绑定缺失、重复安装、schema
主键缺口、丢失/重复/伪造记录。该新增部件的首轮没有失败用例；Docker 的 amd64/arm64 提示不影响运行。
独立 review 后补充缺失单条重复写事件的非终验边界用例及精确说明；最终 **13/13 PASS，1.046 秒**，
没有新增失败。review 在本部件明确的 render/非终验聚合范围内未发现剩余 blocking。

运行用既有 `postgres:16.14` 与 `noteai-media-tests:py311-sdk` 镜像；两容器均 `--network none
--read-only`，PG 数据在 tmpfs，只有新建 Item33 本地 socket volume 共享，源码只读，未下载依赖。
已停止并自动移除专用 PG 容器 `noteai-item33-dml-local-pg-20260915`，已删除专用 socket volume
`noteai-item33-dml-local-socket-20260915`；没有生产恢复动作。

文件归属仅本新增模块、测试和本说明；无 commit、共享 Handoff 修改或受保护路径操作。
