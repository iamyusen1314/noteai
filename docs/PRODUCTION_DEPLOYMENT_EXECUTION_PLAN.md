# NoteAI Production Deployment Execution Plan

Status: `LOCAL PREPARATION VERIFIED / PRODUCTION APPLICATION NOT AUTHORIZED`

Date: 2026-09-07 (current scope below; July sections retained as history)

Task: `PROD-DEPLOY-PLAN-001`

This document is a read-only release plan. It does not authorize an ACR
access, image pull, container/service start, database write, Alibaba Cloud
mutation, provider call, ALB/TLS/DNS change, or production traffic.

## Item34 当次最小生产实施申请 — 2026-09-07

本节是下一次一次审批的具体范围，覆盖正常执行、结果读回、已知失败处置及
Evidence 保存。**目前全部生产动作仍未获批、未执行。** 本轮仅进行了本地
Docker/Colima、隔离构建及 PG16 验证；没有生产 Secret、业务连接、供应商请求、
push、镜像上传、新计费资源或自动化恢复。本节取代下方七月整套发布顺序，
不要求先重建全部角色、更新 API、部署 Payment 或完成 ALB。

### 0019 的实际 SQL、身份与确认

仓库外既有文件已经逐字读取并核对；为恢复保存的副本放在已有
`scripts/postgres/`，不是另一套迁移。执行时先逐字比较两处并校验以下 SHA256：

| 阶段 | 原实际文件位置；仓库恢复副本同名 | SHA256 |
|---|---|---|
| preflight | `/private/tmp/item34-0019-preflight.sql`；`scripts/postgres/item34-0019-preflight.sql` | `dbfac34fe06bbec9e81bd0cad0e33131f7ba1ff25575d447c82adc1013869d41` |
| apply | `/private/tmp/item34-0019-apply.sql`；`scripts/postgres/item34-0019-apply.sql` | `4ace3f3591a4e922fec7917664bd1e5f1fd7193901b1a8ef93b6375a940a5cca` |
| verify | `/private/tmp/item34-0019-verify.sql`；`scripts/postgres/item34-0019-verify.sql` | `00f85944d37be8ff4b6e89478b56df35302fa2d16950203dfe9e2e0ba65bfa7a` |

verify 原 hash `2c14d2340b862a9e321df319cc1009dee4e4bcc454c83ff94d711b2657f76bf9`；
本次唯一修正是在其只读事务内补 `SET LOCAL ROLE noteai_admin`，两处副本一致。
preflight/apply 内容未变。canonical `0019_xhs_tracking_runtime_config.sql`
仍为 `bad6b9df591aba93a6f636c3185d955062a878ce9ed2a92d6c1dff5e5c267a6f`。

对象是现有 PG16 `noteai-prod-postgres` 的 NoteAI 数据库；实际数据库名应从
既有注册实例确认，不能凭别名新建或猜测。执行会话须使用**已有能够
SET ROLE noteai_admin 的数据库身份**，且 settings 与 ledger 的 owner 都应为
noteai_admin。preflight 检查身份、search_path、RLS 开启且不 FORCE、无同名
policy/0019 ledger。apply 用 SERIALIZABLE、限定超时、迁移 advisory 事务锁，
只创建 `noteai_xhs_tracking_config_read_v1` SELECT policy 并插入一行0019账本；
不更改 Secret、表结构、角色 membership 或运行开关。policy 只允许 Tracking
读取非 Secret 的 `crawler_config`、`xhs_collection_safety`。verify 应返回 owner、
正确 search_path/RLS、精确 ledger=1、policy=1，并核对实际 qual 与 canonical SQL。

DMS 的 `AliyunDMSDefaultRole` 是**阿里云授予 DMS 服务的 RAM 角色**，只能解除
当前 DMS 云资源访问授权提示。MFA 完成不产生 PostgreSQL owner 权限。若选择
DMS 路径，owner 在 **RDS → noteai-prod-postgres → 登录数据库/DMS → 当前
AliyunDMSDefaultRole 授权提示**中授权给 DMS 服务，并在实际要求时本人完成
MFA；之后仍须在该实例的 DMS SQL 窗口使用上述已有数据库执行身份。若已有
另一条合法 owner 会话可完成同样 SQL，DMS 授权不是强制前置。不通过给 app
迁移权限、新建账号或在聊天中传递连接串来绕开它。

已用真正隔离 PG16.15 执行三份 SQL：正确 owner 应用/只读验证成功，重复 apply
被拒且结果不变，owner 不匹配时 policy 与 ledger 均无落地。它证明脚本行为，
不证明当前生产 owner 会话已可用。

### 已定位的最小执行器权限缺口

现有 `execute_item34_tracking.py` 的 snapshot/bind 强制 `noteai_app`，会读取
`tracking_provider_attempts`；现有 ACL 仅给 Tracking 此表权限，0019不会修复。
隔离 PG16 已复现 app SELECT 被拒、临时 grant 后可读、revoke 后权限恢复。
下一次批准需明确包括：由上述 owner **仅临时 GRANT SELECT ON
public.tracking_provider_attempts TO noteai_app**，以及恢复原 ACL。先保存原
ACL/有效权限；已有授权绝不能在结束时误撤。此 grant 对所有 noteai_app 会话
生效，暴露该 attempts 表的读取能力，非仅某个容器或 UUID；不授写权限、
迁移账本权限或角色 membership。

每阶段完成 postflight、配置恢复读回、必要失败安全处理、worker 清理及证据
固化后立即撤回本次新增 grant；3d 前允许在**同一次批准**内再次临时授予及
撤回。撤权前须完成需要 snapshot 的 reconciliation，不能在 worker 一退出
就撤。UNKNOWN 不允许重放，也不允许无限保留临时权限。其余所需 app SELECT
为 settings/tracked_notes/crawler_events/growth_records/user_memories；源码
ACL 已覆盖，生产执行前只查当前权限布尔值，任何额外缺口停下报告，不扩权。

### 合法 managed row 与既有 API

目标固定为 `https://www.xiaohongshu.com/explore/6a7954010000000026034707`。
唯一创建入口是现有 NoteAI API 的 **POST /notes/track-url**（已登录用户页面
发起；内部调用必须携带同一合法用户身份）。owner 需在 NoteAI 页面登录其
现有账户并选定确实属于自己的跟踪对象；若现有会话有效，可直接沿用。
不猜 user_id，不创建诊断身份，不直接 SQL INSERT managed row。

合法请求使用实际 source_note/version/session（若提供则验证所属关系）、
标题和发布时间事实。平台仅有“08-10”不构造 ISO 时钟；未知 published_at
可依原接口传 null，服务端真实提交时间照常保存，随后走既有 bind 调度。
认证副作用须计入执行范围：有效会话查验是 SELECT；过期 token 校验可能
DELETE user_sessions；必要的正常登录可能写 auth_login_limits、更新
users.last_login、INSERT user_sessions。请求本身在写入围栏/重复检查后
INSERT 一行 tracked_notes（服务端 submitted_at/next_check_at）；无供应商调用。
请求超时先按该合法用户与固定对象读回，不能盲目重提；409读回已有行而不造新行。
之后仅由现有 wrapper 的 bind 更新该行 next_check_at，保留真实 submitted_at，
不倒填发布时间、观测时间或 Evidence。认证附带写入单独如实保存在原执行记录，
不能冒充 Item34 核心7表之外零业务活动。

源码审查确认已部署 b55 API 的 TrackUrlInput、track_url、身份/所有权/写围栏
相关函数与当前源码相同；Item34 无需先升级 API 或 Payment。该结论不把旧
API 当成已整合 Item30 Kimi 的全产品候选。

### 必要候选产物及发布对象

仅需 `xhs-http-runtime`，承载已有 wrapper、checkpoint、Tracking worker 和
provider-free healthcheck。实际入口保留 `/app/scripts/docker_entrypoint.sh`。
本地已生成 `noteai-local/item34:b8ae59c`，OCI revision 为完整
`b8ae59cbf1c8423b832dab385eb3f0d367298b71`，关键源码与本次代码 checkpoint
没有漂移。该镜像在隔离运行中实测 Python3.11.15、linux/amd64/x86_64、UID999、
8个 source SHA 一致，cryptography50.0.0、psycopg3.3.4，pip check 通过。
可传输的本地 Docker 产物已保存为
`/private/tmp/noteai-prep-20260907/item34-xhs-b8ae59c-linux-amd64.docker.tar.gz`，
377806447 bytes，SHA256
`79ba76c546bf20d71b8e2c1f27ce95805b93d70cfbf663f9cf105e9401b7d6eb`。
本地 OCI manifest/image identity
`sha256:cb17d276d79a0b6b8bc0ad64a11a5ef0aa8e23bd8b9b00bd35ce62eca42f0a27`
**不是 ACR 发布凭据**。ACR digest 必须在真正 push 后读回并与所发布内容核对，
当前未填造，也不阻断本地准备。

旧 v2 `/Users/openclaw/Desktop/noteai-item34-xhs-overlay-20260906-v2.tar.gz`
的112个源码文件与当前版本完全匹配（archive SHA
`f7e5fbe5718578ac810daa3a01fe92dd4a63f93051ece833b8e75a96d61c2788`），
不能错用 `/private/tmp/noteai-item34-xhs-overlay-20260906` 的旧v1内容。
v2继承旧base的cryptography48.0.1，当前要求50.0.0；因此本次选择上面的已构建
候选供发布，保留原v2作为比较对象。本次只构建此必要角色，没有重建全角色。
本地 Colima `noteai-prep` 为无主机挂载/无agent转发/无端口转发的独立环境，
使用QEMU运行amd64；它提供候选平台验证，不是生产宿主验收。

发布目标是**现有** ACR 私网实例的 `noteai/app`，使用既有 API-F 私网连接，
发布一个绑定本候选的新 immutable tag（预定 `item34-20260907-b8ae59c`，先核实
不存在，不覆盖旧tag）。上次一次 manifest 请求为 UNAUTHORIZED/ACCESS_DENIED；
凭证过期还是权限原因仍未定位，不再重复同一拒绝请求。下一次批准可包含
使用既有合法主体完成一次 ACR 认证恢复和发布；若需要人工登录，owner 到
**容器镜像服务 ACR → 当前深圳私网实例 → 访问凭证/仓库 noteai/app 操作指引**，
在受控主机完成现有身份的认证，不在聊天中交出密码。不重置凭证、扩RAM权限、
开放公网或新增Builder；现有权限仍拒绝则保留脱敏错误并停止。

### 时间与一次批准的有序动作

直接沿用 canonical Evidence 的 latest_owner_amendment/observation 和
`docs/XHS_TRACKING_PRODUCTION_CONTRACT.md` 的 later-binding条款，以及
`validate_item34_tracking_evidence`：起点2026-09-04 22:30:38+08仅证明真实初始
4/2/2快照。24h允许区间为 **[2026-09-05 22:30:38+08, 2026-09-07 22:30:38+08)**；
3d为后一个边界起且晚于24h，attempt完成不晚于对应snapshot。没有新增±误差、
两样本间48h最低间隔、3d最晚截止或managed row/服务覆盖整72h的要求。

实测时钟2026-09-07 12:40:25北京时间，canonical两checkpoint仍null、attempts空，
最近生产只读记录为10:53:57目标行0；本轮没有新生产/供应商Evidence。
状态 **UNPROVEN**，旧窗口此时仍可实施，前提是全部前置及24h真实完成/快照
均在当晚22:30:38之前。若到执行时已错过且没有原有有效Evidence，停止本方案
的24h执行并报告不相容；不补采倒填、不改DoD、不自动重启。

1. **准备执行入口**：确认既有owner数据库会话和API-F原服务/权限状态；按上文
   有需要才完成DMS默认服务角色授权及既有ACR认证。一次受控传输本地候选至
   API-F、load、push到既有ACR、读回实际digest；核验平台/Python/8个源码hash，
   后续仅用 `私网仓库@sha256:真实digest`。资源不足或auth继续拒绝就停止。
2. **0019及最低读权限**：执行既有preflight→apply→verify；保存owner/ledger/
   policy结果及原ACL。每阶段按上文临时授予app对attempts的SELECT。
3. **真实用户创建与绑定**：合法POST创建/确认唯一managed row，现有wrapper
   bind只改next_check_at。确认无既往attempt、目标唯一、全局无started/unknown，
   既有Tracking session/signer就绪；只记录非敏感布尔值/hash，不读取Secret值。
4. **24h then 3d**：各一次现有 `execute_item34_tracking.py` / checkpoint流程，
   每次只启动 `python crawler_worker.py --once --limit 1`。两阶段合计最多2个
   provider admission，0自动重试；先读真实配额和共享session stop。暂时激活
   crawler_config，按CAS恢复原值/时间；24h后仅schedule同一目标至3d边界。
   单次结束完成结果读回、stop/cleanup、Evidence保存及临时SELECT撤回。
5. **Item34自身的必要验证**：在API-F保留原Tracking unit/image/enabled/active
   精确状态，只对Tracking unit绑定真实新digest，保持显式suspended、Restart=no，
   人工有界start→provider-free healthcheck→stop及恢复演练；核对singleton、
   资源/restart/log/alert控制，将managed验证绑定已经完成的一个attempt，
   不产生第三次供应商调用。只恢复先前批准状态，不enable定时服务/自动化。
   若现有managed promotion实现不能证明某字段，按真实缺口保持incomplete，
   不把静态renderer或suspended进程存活当成全部PASS。

必要结果读回与失败处置已经包含在此一次申请内，不在获批后逐条重复询问。
明确失败在COMMIT前回滚SQL；COMMIT回包丢失为UNKNOWN，先owner verify，绝不
直接重放apply。已提交0019在后续失败时保留为dormant additive migration，
不删policy/账本。provider start/result不明先停止精确任务容器并用原
reconcile/readback恢复判定；reconcile可能stop容器，**不是纯只读动作**。
已知challenge/logout按原代码可写一行xhs_collection_safety停止旗标。
配置恢复使用原值/时间CAS，失败不强盖并发修改；保留attempt、失败记录、
原镜像及SQL状态，终止后续采样，撤回本次新增临时读取权，不删业务数据。

核心批准写范围仍是现行7表9个distinct rows（schema_migrations1、tracked_notes1、
tracking_provider_attempts2、growth_records1、user_memories1、crawler_events1、
system_settings2）；同一row的claim/finalize/config多次UPDATE并不等于仅9次DML。
另外明确纳入必要认证写入、policy DDL、临时grant/revoke和安全失败写入范围，
如实记录，不能为凑终态隐藏副作用。若认证附带写入与现有批准的总写范围不相容，
保持incomplete并报告，不能仅通过拆分日志宣称out_of_contract=0。
Evidence仅写既有canonical路径/原workdir，
完全满足批准DoD及validator后才计分。

**影响/费用边界：**使用现有ECS/RDS/ACR容量，没有新云Builder/计费资源、
无支付、无模型批次。两个XHS HTTP读请求的adapter没有单次付费API价目，
现有网络/ACR存储计费增量不能捏造为精确0元；批准对象是一个已构建镜像的
现有实例传输/存储及两次请求，数据库DDL有限定锁等待，Tracking有界验证使用
既有CPU/内存。若服务要求购买/扩容/新账单项或给出新增固定费用，停止，
不将该费用隐含进本次申请。本机下载构建和PG16测试无需云Builder报价。

## Paused preparation update — 2026-09-07

This section describes current local preparation. The historical image table
below belongs to its dated release and is not the next candidate. The owner's
subsequent confirmation authorized the bounded readbacks recorded in the current
Handoff. It did not authorize production writes, publication, service changes,
provider requests, payments, DNS, role grants or paid resources. Those remain
PAUSED. This document itself grants no execution permission.

### Candidate source and affected regressions

The recovery starts at `58859ce737337446698dd0a72a218718633953e9`, whose parent
is accepted Item30 `429b55a7bf652c8a9b4b5f47ca769ea5cba8ef29`.
`model/model_router.py` already contains the Item30 Kimi usage compatibility
change, and `Dockerfile` copies that source into the runtime. The old b55 API
image did not receive the temporary Item30 probe overlay. A future authorized
build must bind the final preparation commit and actual role-image contents;
neither an old image nor the historical Item30 PASS proves the new release.
Use `test_model_usage_audit` and `test_item30_real_ai_provider_chain` as mocked
current-source regressions, plus affected payment/API/runtime checks. They do
not replay the accepted provider chain. The September7 minimal Item34 image build above supersedes the earlier no-build
statement. No image has been uploaded.

The persisted offline launcher is `scripts/run_paused_local_checks.py`. Invoke
it with `env -i PATH=/usr/bin:/bin:/usr/sbin:/sbin .venv/bin/python`, followed by
the script and explicit `tests.test_*` module names, or `--readiness` for the
existing static ledger. It disables dotenv/network/PostgreSQL, uses temporary
SQLite and rejects protected paths. These are Python process guards, not a
substitute for an OS sandbox or production image validation. Do not use test
discovery across the seven protected paths. Local takeover checks used
Python3.14.4; future release checks must cover the actual Python3.11 image.

### Item31 bounded DML and callback preparation

September7 local implementation: `tools/collect_item31_canary_dml.py` now
provides the selected minimal source: temporary, canary-predicate AFTER ROW
triggers emit transactional `pg_notify`; one dedicated LISTEN connection
persists only operation/table/transaction and identity hashes in the existing
canary work directory. No audit table, general logging service, new dependency,
production installer or automatic provider path was added. Each provider's
existing canary uses its own activation/target mapping; API and Payment writers
for that canary share the same capture. Do not combine two different orders
under one single-value target mapping.

The explicit integration order is: review reachable writer tables/ACLs and
trigger/rule/FK effects; render `installation_sql(activation, targets)` with
existing known canary IDs; owner applies temporary DDL only under later Item31
approval; create `CanaryCapture` with the same activation/targets/provider;
inside each writer's explicit BEGIN call `bind_transaction`, synchronously
`capture.register` before admitting DML, perform the existing canary action,
call `transaction_complete` in that SAME transaction, then COMMIT. After an
explicitly confirmed ROLLBACK call `rolled_back`; a lost COMMIT reply is not a
rollback. Close admission to all writers before `finish(admission_closed=True)`.
Capture calls are serialized by the existing orchestrator. Read retained data
with `read_journal(path, **capture.context)`; output maps into the existing
`write_mutations_by_table` / `write_ledger_readback_sha256`, never terminal DONE.
Use `removal_sql` to remove only those exact temporary triggers/function after
live closure; no cascade and no permanent role expansion.

True isolated PG16.15 plus the candidate's Python3.11 passed11 collector tests:
separate API-like/Payment-like writer processes, committed multirow and nested
trigger/cascade effects, duplicate UPDATE versus ON CONFLICT/zero-row no-op,
SAVEPOINT and outer rollback, wrong target, changed transaction, listener loss,
in-flight tail, fsync failure and persisted binding mismatch. These are
synthetic PostgreSQL transactions, not real paid canaries or proof that all
production API/Payment writers are already instrumented. The collector binds
activation/provider/coverage hash and backend PID/transaction/nonce, records no
row values, cannot resume a disconnected stream, and leaves incomplete results
UNKNOWN. Trigger notifications discarded by rollback are not counted.

Remaining live integration is concrete: install/remove this temporary DDL only
for reviewed canary scope and register **every** API/Payment transaction before
any DML; include forbidden-table sentinels for all reachable out-of-contract
writes. The current source supports INSERT/UPDATE/DELETE; TRUNCATE, missing
writer registration, absent trigger coverage, unknown trigger/rule/FK effects
or an interrupted listener preclude complete DML evidence. Do not infer all
other tables had zero writes. This Item31 DDL/integration and real funds are
outside the Item34 one-time application above.


Use the existing canary action journal and canonical Item31 Evidence, without
adding a global audit service, receipt schema or wider long-lived Payment role.
The real collector must cover each actual transaction in the two 1200-fen
canaries; preserve failed/UNKNOWN evidence and stop rather than replay.

| Action | Existing source and rows to account for | Evidence limitation to close |
|---|---|---|
| Create and admit order | `payment_contract.create_order`, `admit_payment_submission`, response-state update; `payment_orders` | Bind the fixed canary order/request digest and count actual committed INSERT/UPDATE effects, including a timeout-state transition. |
| Authenticate callback/query | `process_authenticated_callback`, `_record_event`, `_finish_event`; `payment_events`, order, cash, credit position, entitlement, credits and credit transactions | Bind verified provider event and payload digests to committed rows; never retain raw callback/signature/checkout values. |
| Duplicate notification | `_record_event` increments `duplicate_delivery_count` | One event UPDATE is a real mutation even when the table row count is unchanged; there must be zero second cash/entitlement grant. |
| Full unused refund | `prepare_full_refund`, admission and authenticated refund query/callback | Bind the same order/refund to one cash reversal, position reversal, credit transaction and entitlement reversal. Submission alone is not refund success. |
| Reconciliation | Existing provider bill/query boundary and reconciliation tables | Match original order, authenticated notification, refund and ledgers; report discrepancies, not inferred success. |

`tests/test_payment_query_financial_evidence.py` now exercises real SQLite
statement rowcounts and committed-transaction boundaries for the duplicate
notification path. It proves the offline distinction between DML and final
state, not PostgreSQL trigger coverage or production provenance. At that earlier stage, production
DML capture lacked an established source covering both API and Payment
processes. The local collector above now closes source semantics, while live
writer integration and coverage remain incomplete. Before live funds,
obtain an authorized, narrowly scoped metadata readback of the available RDS
DML-audit mechanism and its rowcount/commit semantics; do not enable broad SQL
logging, record parameters, or claim SELECT snapshots reconstruct DML. If no
suitable existing source exists, prepare only a canary-scoped collector after
that finding. Missing capture means Item31 stays incomplete; best-effort
create/callback logs and `pg_stat_*` aggregate deltas cannot close it.

Authorized September7 readback narrowed this gap. The existing PG16 instance's
SQL-insight page shows `开启审计日志`. A server-enforced read-only API session
returned `log_statement=ddl` and no installed `pgaudit` among the requested
extension names; no audit function was enabled. The same session cannot SELECT
the migration ledger or tracking attempts, and must not be granted broad rights
just to make evidence convenient. Query visibility is not historical DML proof.

The [official PostgreSQL audit description](https://help.aliyun.com/zh/rds/apsaradb-rds-for-postgresql/sql-insight-or-audit)
says audit uses database-kernel SQL capture, excludes PgBouncer SQL, and records
failed SQL in error logs rather than audit logs. Enabling changes log_statement
to all. The [PG-supported detail API](https://help.aliyun.com/zh/das/developer-reference/api-das-2020-01-16-getdassqlloghotdata)
has separate UpdateRows, ReturnRows, TransactionId, ThreadID and State fields;
their presence does not establish committed INSERT/UPDATE/DELETE effects after
rollback/savepoint or trigger-internal effects. The documented
[transaction analysis](https://help.aliyun.com/zh/das/user-guide/transaction-analysis)
prerequisites list MySQL engines, not this PostgreSQL instance. Do not infer
PG support from a generic DAS transaction-analysis description.

Audit enablement is both a configuration and charging change, outside the read
authorization. [Official V3 mainland pricing](https://help.aliyun.com/zh/das/product-overview/billing-details-of-the-previous-version)
lists log import CNY0.24/GB, optional index0.24/GB and insight0.08/GB, plus
retention/query-dependent costs; security audit has a separate minimum charge.
Actual selected version/options/volume are unknown, so there is no instance
quote. Do not buy or enable it as the default answer to the Item31 gap.

The local fixture observer now handles the contract's literal SAVEPOINT,
ROLLBACK TO SAVEPOINT and RELEASE forms. A real entitlement-write-then-fail
case commits cash1/order1/event2 affected rows and rolls back all entitlement
effects. This is why summing successful rowcounts at outer COMMIT is insufficient.
It is a correction to offline counting, not to the production rollback code.
Any later canary-scoped capture must distinguish attempted and committed effects,
retain transaction/savepoint boundaries, classify disconnects UNKNOWN, and cover
both API and Payment paths. Enabled trigger/internal-rule effects and durable
readback remain unproven. Keep using the existing canary action journal and
Evidence fields; do not add a global logging platform or new approval gate.

The fixed real notification endpoints are:

- `https://api.noteaipro.cn/payments/wechat/callback`
- `https://api.noteaipro.cn/payments/alipay/callback`

The provider must resolve that hostname and reach valid TLS on port 443.
A developer hosts entry, `curl --resolve` or an ALB pre-DNS probe cannot make
provider callbacks reach NoteAI. API forwards only those exact paths and
allowlisted headers/body to the co-located Payment namespace on 127.0.0.1:8002.
The normal ordering routes remain fenced until merchant approvals and capped
canary activation are ready. There is therefore a real sequencing decision:
the owner must approve a bounded, provider-reachable callback ingress before
Item31 Live funds while preserving the separate Item38 public-launch decision,
or explicitly change the launch sequence. This document does not authorize
DNS, opening other business routes, a different callback domain, or a
single-channel launch. The existing two-provider requirement remains unchanged.

### Item36 local implementation, health and rollback

These are three separate implementation actions, not interchangeable completion:

| Action | Actual local result / next implementation | Genuine dependency |
|---|---|---|
| Candidate API image update | Current source contains Item30 Kimi repair; deployed b55 does not. This turn built XHS only. API candidate build/content regressions and exact digest replacement remain separate release work. | An old healthy API or an updated XHS image cannot prove API candidate deployment. No Payment/ALB prerequisite for the Item34 track-url route. |
| Private API binding | Existing pure renderer and rollback bytes are prepared; actual API-C/F unit bytes and exact source hash must be read and bound before apply. | Requires approved network scope and exact host input. Does not require Payment first activation merely to change a bind, but must preserve any previously active callback namespace. |
| Payment first activation | C was disabled/inactive and F unit not-found at last readback. First installation/configuration, immutable image, shared API container namespace, service start, health and public callback verification remain real actions. | Merchant/canary authorization and provider-reachable callback ingress before live funds. Keeping disabled state is rollback preservation, not first activation or full deployment. |

Do not start any of these three as an implicit Item34 dependency. Item36
terminal dependencies on33/34 remain; its local preparation can run separately.


Fresh September7 service/container metadata shows both APIs on the old b55
image and loopback8000. Payment is loaded/disabled/inactive on API-C; its unit
is not-found on API-F, and neither exact-name container inspection succeeded.
No shared Payment/API namespace or new live health probe is therefore proven.
Both API unit FragmentPaths were read, but current unit bytes were not exported
or rendered. A future application must first bind those exact reviewed bytes;
template similarity and a stored Docker `healthy` state are insufficient.

`tools/prepare_item36_private_bind.py` is a pure local renderer with no apply,
cloud, subprocess, database or environment-loading path. Given a reviewed
Secret-free API unit copy, its exact SHA-256 and that node's confirmed RFC1918
IPv4 address, it changes only the single loopback 8000 mapping and writes a
candidate plus byte-identical rollback. It rejects source drift, extra ports,
public/loopback target addresses, shell expansion and mutable image identities.
Synthetic tests do not prove that either current host unit matches its input
contract. No actual host unit has been fetched, rendered or applied this turn.
Production Compose now defaults API binding to loopback; a future reviewed
private binding must be explicit.

For a future authorized application, retain the current API/Payment unit bytes,
immutable image refs, container identities and prior enabled/active/callback
states on each node. First verify the exact ALB-source TCP8000 security-group
rule and zero wider ingress. Then process API-C followed by API-F, keeping the
other accepted node available. On each node:

1. Stop an enabled Payment callback service before replacing its API namespace;
   retain the prior disabled state if Payment was not enabled.
2. Apply only the reviewed private-bind unit, start that API, and verify the new
   container identity, private socket, `/health/live` and `/health/ready` with
   the existing repeated healthy-readback contract.
3. If Payment was enabled, explicitly recreate/start it in the new API container
   namespace and verify loopback 8002 readiness and matching provider identity
   summaries. `BindsTo`/`PartOf` stops the old container; it does not prove that
   a stopped Payment service has automatically returned. Compose `depends_on`
   alone is likewise not recovery evidence.
4. Only after the node passes may the next node proceed. For known failure,
   restore the captured original API unit/image and original callback state;
   if previously enabled, recreate Payment in the restored namespace and verify
   again. UNKNOWN stops progress pending readback. Do not delete databases,
   audit history, prior images or unrelated cloud resources.

ALB readiness is a provider-free GET of `/health/ready`; payment, XHS and model
supplier calls are not health dependencies. Validate both backends, exact
SNI/Host against the actual ALB endpoint, TLS/certificate binding and a fresh
post-bind three-unit NDR readback. Retain before-state for only known
task-created resource rollback. Emit the existing canonical Item36 Evidence
only after genuine provider readbacks and its validator pass.

Item36 terminal still depends on Items33+34, capacity100, fresh provider quote
and explicit fixed/variable cost approval. Private-bind and health preparation
can proceed independently of those terminal dependencies. No current quote,
cloud wrapper or live execution is implied. The old monthly estimate and
preparation-only NDR mask0 record remain LAST_KNOWN/reference-only.

## 1. Immutable release set

All production pulls must use the private VPC registry hostname and the exact
manifest digest. Tags may be displayed for operators, but may not be used as
the deployed identity.

| Role | Private immutable image |
|---|---|
| API | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:17706e1802afc136ac8f9a621d4199a7f9749da733290e923e42268eff42e0d1` |
| Admin | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733` |
| XHS HTTP | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:452c2faf7853ce58d93e43c05fb6217a9a6cc1e4c81345d8cef2f50acabd79af` |

Every image must report `linux/amd64`, application/OCI revision
`a635692a899ee02c6905cd694611c14e0da4594a`, source
`https://github.com/iamyusen1314/noteai`, version
`git-a635692-amd64-r1`, non-root user `noteai` / UID/GID `999`, and its
expected `api`, `admin`, or `xhs-http` role marker. Local Docker image IDs are
not registry digests.

## 2. Proposed first-release placement

| Host | Initial service | Initial exposure |
|---|---|---|
| API-C | API canary, then accepted API; Admin only after both APIs pass | API canary on loopback; Admin loopback-only until a later ALB approval |
| API-F | API canary, then accepted API; XHS services only after separate XHS/DB-write approval | API canary on loopback; XHS exposes no HTTP port |

API-C is deployed and accepted first. API-F is never deployed merely because
API-C succeeded; it has its own digest/config/readiness acceptance. Admin is
single-instance for the first internal release and remains unreachable from
the public Internet. The XHS image supplies two process roles,
`xhs-trends` and `xhs-tracking`; both stay stopped until their separate gate.

This placement uses existing paid ECS capacity and does not create a Worker
host. CPU, memory, disk and failure-domain suitability must be rechecked before
execution. If either host lacks headroom, stop and request a capacity decision;
do not silently colocate more roles or buy capacity.

## 3. Blocking findings before any deployment

1. `PROD-DEPLOY-ENV-SPLIT-001` closes the original repository-side shared
   env-file defect. The later Tracking contract further splits Trends and
   Tracking, so API, Admin, Trends and Tracking now use four distinct inputs;
   `scripts/validate_production_env_files.py` rejects unknown, duplicate or
   cross-role Secret key names without printing values. The live files and
   their permissions still require read-only verification on API-C/API-F.
2. API-C/API-F Docker, disk, current containers, service definitions, ports,
   private ACR DNS, registry-auth method and runtime-env metadata are not
   currently re-observed. A read-only node audit is mandatory.
3. RDS current availability, backup/PITR state and schema versions `0001`-
   `0008` need a fresh read-only check. Ordinary API/Admin start must not run
   migration. `scripts/render_predeploy.py` also writes the managed Prompt
   baseline and is therefore excluded without a separate database-write
   approval.
4. The Admin listener placement is intentionally loopback-only for this
   internal stage. Public/private ALB exposure requires a later listener,
   security-group and authentication review.
5. `NOTEAI_XHS_COLLECTION_SUSPENDED=1` prevents real XHS collection, but the
   market worker can still write baseline/freshness state to PostgreSQL and a
   local snapshot. XHS service start therefore needs an explicit bounded
   production-write approval even while external collection remains suspended.
6. ALB, TLS binding, DNS cutover, real provider checks, payment and public
   traffic are outside this plan.

## 4. Serial rollout gates

### Gate 0 — read-only production preflight

- Reconfirm exact host IDs/names and that only API-C/API-F are in scope.
- Record Docker/Compose versions, architecture, free disk/memory, current
  container/image/service state, bound ports and existing release paths.
- Hash current deployment definitions and record current immutable image refs;
  do not output environment values.
- Verify each role env file is root-owned `0600`, contains only allowlisted key
  names, and has no unknown/duplicate names. Do not print values.
- Resolve the private ACR hostname from both nodes and verify intended VPC
  routing. No registry login, manifest request or pull in this gate.
- Read RDS availability, schema-migration versions, backup/PITR metadata and
  connection limits without changing data.
- Run `tools/collect_production_database_preflight.py` only through an
  authenticated least-privilege metadata credential/session. Inject its DSN
  through a hidden protected process environment; never place it in command
  arguments, evidence or logs. Require connection- and transaction-level
  read-only mode, bounded timeouts, aggregate-only source checks, rollback and
  close.
- Reduce the observation to a Secret-free JSON artifact and require
  `tools/production_readonly_preflight_gate.py` to pass. Do not record host
  IDs, IP addresses, connection values, user rows or long logs.
- Stop on any unexpected running application, public listener, mutable image
  ref, Secret exposure, low disk, architecture mismatch or unrecorded change.

### Gate 1 — deployment-template closure

- Confirm the completed role-specific env-file inputs for API, Admin and XHS.
- Run the key-name validator against all three external files before Compose
  resolution; reject unknown, duplicate or cross-role Secret names.
- Preserve UID/GID `999`, read-only root, `cap_drop: ALL`,
  `no-new-privileges`, bounded `/tmp`, no devices, no privileged mode and the
  single bounded data mount.
- Resolve the Compose file offline and verify every image matches
  `repository@sha256:<64 lowercase hex>`.
- Run the production hardening, readiness and production-readiness tests.
- Create a `[skip render]` deployment-control commit. This commit is not an OCI
  revision and does not require an image rebuild.

### Gate 2 — API-C canary and promotion

- Capture the current service/config/image state and rollback command before
  any pull.
- Authenticate only to the private VPC registry using a temporary,
  least-privilege mechanism; never reopen the public ACR endpoint.
- Pull only the exact API digest, then immediately verify RepoDigest,
  `linux/amd64`, OCI revision and role marker.
- Start a loopback-only canary on an unused port with the production runtime
  constraints. Do not run migration or any real provider call.
- Require `/health/live` HTTP `200` and `/health/ready` HTTP `200` three times
  over at least 60 seconds. Readiness must contain only healthy PostgreSQL and
  required local-model checks.
- Inspect bounded, redacted logs and prove no migration, supplier request,
  billing mutation or Secret output occurred.
- Only after independent acceptance may the same digest/config replace the
  inactive API-C production service. Keep it outside ALB.

### Gate 3 — API-F canary and promotion

- Repeat Gate 2 independently on API-F; do not copy API-C's result.
- Confirm digest and role/config parity with API-C.
- Require repeated zero-AI readiness and retain API-C as the rollback-safe
  accepted node.
- Keep API-F outside ALB until independent acceptance.

### Gate 4 — Admin internal deployment

- Pull only the exact Admin digest on API-C and verify its registry/OCI
  identity before start.
- Require the dedicated `noteai_admin_runtime` database role and the accepted exact
  session/read-only operational permission matrix. Do not reuse `noteai_app`
  or the managed RDS administrator named `noteai_admin`,
  and do not force the entire connection read-only: login/logout require only
  `admin_sessions` `SELECT, INSERT, DELETE`, while all business mutations are
  denied independently by application capability gates and database ACL/RLS.
- Start loopback-only. Require `/health/live` HTTP `200` and
  `/health/ready` HTTP `200`; Admin readiness blocks only on PostgreSQL and a
  configured Admin credential.
- Prove one login, authenticated `/admin/capabilities` read, masked user/queue
  views, logout and token invalidation without business writes. Every mutation
  endpoint must return HTTP `409` before database/file/process work.
- Do not mutate Prompt/configuration, expose the port publicly or add it to ALB
  in this gate.

### Gate 5 — XHS HTTP processes

- Keep both processes stopped until separately approved.
- When approved, pull the exact XHS digest on API-F and verify identity.
- Start `xhs-trends` before `xhs-tracking`, never together.
- Keep `NOTEAI_XHS_COLLECTION_SUSPENDED=1`, leave snapshot upload disabled,
  keep crawler configuration disabled, and make no real XHS request.
- Trends has no healthcheck. Tracking uses only its provider-free read-only
  schema/role healthcheck and `restart: "no"`; a failed round stays stopped
  for evidence review instead of automatically retrying. Acceptance also
  requires the expected non-root process command, bounded redacted logs and
  proof of zero external collection.
- Any database/snapshot writes must match the separately approved bounded
  list. Do not use a browser fallback, proxy rotation or challenge bypass.

### Gate 6 — later network release

ALB creation, backend registration, TLS binding, DNS cutover, public smoke and
real supplier calls are separate tasks with separate cost and production-impact
approval. No earlier gate implies approval for Gate 6.

## 5. Health and acceptance contract

| Role | Liveness | Readiness / acceptance |
|---|---|---|
| API | `/health/live`: process-only HTTP `200` | `/health/ready`: HTTP `200` only when PostgreSQL and the required local model are healthy; HTTP `503` otherwise |
| Admin | `/health/live`: process-only HTTP `200` | `/health/ready`: HTTP `200` only when PostgreSQL and Admin credential presence are healthy; HTTP `503` otherwise |
| XHS Trends | No HTTP listener or Docker healthcheck | Process/command identity, runtime constraints, suspension state, bounded logs and zero external collection |
| XHS Tracking | No HTTP listener; provider-free read-only Docker healthcheck | Exact role/schema readiness, stale/unlinked-attempt failure, suspension state, bounded logs and zero external collection |

Claude, Kimi, Amap, Meituan, XHS, market freshness, crawler and payment are not
load-balancer health dependencies and must not be called by these probes.

## 6. Rollback

- Never delete the prior image, release directory, environment metadata or
  evidence during rollout.
- A canary failure rolls back by stopping/removing only the new canary and
  restoring the recorded inactive state.
- API-C promotion failure restores its prior service/config. API-F failure
  stops API-F and retains accepted API-C.
- Admin failure stops only Admin and leaves both APIs unchanged.
- XHS failure sets/keeps collection suspended and stops only the failing XHS
  process. Do not fall back to Playwright/Chromium.
- No schema migration is included, so application rollback does not perform a
  database downgrade or destructive cleanup.
- Registry image deletion, production-data cleanup and cloud-resource deletion
  are never automatic rollback actions.

## 7. Cost and duration

- No new cloud resource is required by this plan.
- Existing fixed ECS/RDS/Tair/ACR/NAT charges continue whether deployment
  occurs or not.
- Worst-case unshared image transfer for two API copies plus one Admin and one
  XHS copy is about `4.18 GB`; shared layers should reduce actual transfer and
  disk consumption. Use only the private VPC registry path. Registry/network
  billing must be rechecked before execution.
- Reserve at least `12 GiB` free Docker storage per participating node so the
  accepted prior image/config can remain available for rollback.
- Expected operator window after all blockers close: read-only preflight
  20–30 minutes; API-C 20–30 minutes; API-F 20–30 minutes; Admin 15–20
  minutes. XHS activation is a separate window. Stop rather than compressing
  observation periods.
- No AI, map, Meituan, XHS or payment usage cost is permitted in the zero-AI
  rollout.

## 8. Approval sequence

1. `PROD-DEPLOY-ENV-SPLIT-001` — repository-only env-file separation,
   key-name validation and `[skip render]` deployment-control commit.
2. `PROD-DEPLOY-PREFLIGHT-001` — next approval: read-only
   API-C/API-F/RDS/private-network
   audit; no ACR access or production writes.
3. `PROD-API-C-ROLL-001` — exact-digest private pull, loopback canary and
   zero-AI API-C acceptance.
4. `PROD-API-F-ROLL-001` — same independent API-F rollout.
5. `PROD-ADMIN-ROLL-001` — loopback-only Admin rollout.
6. `PROD-XHS-ROLL-001` — separately bounded XHS process start and allowed
   database-write list while external collection stays suspended.
7. ALB, TLS, DNS and public/real-provider smoke remain later approvals.
