# 高德正式业务共享额度接线 — 本地准备结果

日期：2026-09-15。本文记录本轮本地实现；不是生产迁移、Key 绑定、供应商调用或实际产品验收结果。

## 现有决定与实际观察

Owner 已决定对正常权益用户正式启用高德，使用现有账户月额，不购买技术服务许可、流量包、并发包、订阅或充值，不产生自动超额费用。没有新增白名单、Beta 或按月重新审批。Owner 已确认此账户仅 NoteAI 使用；两把既有 Web 服务 Key 属于同一 NoteAI 应用，不能各算一份额度。

本轮控制台观察为企业开发者、尚未取得技术服务使用许可；基础搜索共享月额 50,000、关键字搜索当月使用 1、其他相关搜索 0、每接口 30 QPS。Sep1–Sep15 账单观察为基础搜索计费用量 1、金额 0；只代表已观察周期，不推定今后费用为 0。

来源及边界：

- [高德搜索接口调整](https://lbs.amap.com/news/search-interface-adjustment2/)：v3/v5（2.0）搜索、ID 查询调用量合并。
- [高德基础服务计费](https://lbs.amap.com/pages/base_service_price)：超额可能消耗流量包或余额，不能以供应商会自动拒绝作为防超额手段。当前账户配额来自本轮控制台真实观察，不由代码常量推导。
- [高德 Web 服务错误码](https://lbs.amap.com/api/webservice/guide/tools/info)：保留原业务代码；鉴权/权限或账户限制持久暂停影响范围，瞬时 QPS 限制只作临时暂停。没有供应商自动重试或轮换 Key。

## 实现与数据合同

- `model/amap_quota.py`：`admit(endpoint, storage=...)`、`finish(admission, ...)` 与只读 `read_status(storage=...)`。账户范围固定为不含 Key 的 `noteai-primary-amap-account`，服务组 `basic_search`。只有 `text` 与 `detail` 两个既有接口。
- `0031_amap_shared_quota.sql`：增加 `amap_quota_buckets` 与 `amap_quota_attempts`；迁移不插入额度，不启用任何服务。SQLite 本地初始化复用同一模块的本地 schema。
- `fact_enrichment.py`：每个实际 HTTP 前先提交一次共享 admission；正常查询最多一个 text 与同一 POI 的一个 detail。详情不可用时保留已取得的基础事实与明确 partial 原因；不同 POI 不合并。超额/记录待核实/访问限制通过既有结果和 Prompt 的中文 reason 解释，其他功能及已有资料可继续使用。
- 同账户所有实例使用相同 PostgreSQL advisory transaction lock，随后锁当前 bucket；SQLite 用现有 BEGIN IMMEDIATE。QPS 由数据库锁后的实际时钟与过去一秒 admission 统计，text/detail 各 30。计数不按 Key、进程或实例分拆。
- `official_used` 是固定官方基线；`admitted_count` 是基线之后本地保守占用。当前剩余为 `quota - official_used - admitted_count`。quota 来自 operator 绑定的有效正整数，当前首次应准确绑定 50,000。
- Admission 提交失败或提交确认未知时不发 HTTP；已经提交而超时/崩溃/结果未知的调用永不自动返还。保留 reserved/unknown 并计入额度。同一个 admission ID 不重放，terminal 结果不重写。
- 新月份必须有明确官方 period/start/end/observed_at/source/hash 的新 snapshot。旧月过期不会自动猜测重置。Owner 的原正式授权时间持续有效，可以早于新月份；新月观察不要求重新决定启用。
- 旧月份的持久 account/text/detail 限制继续参与新月检查；新额度不等于已恢复接口权限。只有按真实恢复依据处理原限制，才能清除；runtime 没有自动清除路径。
- 同月官方基线不可覆盖，防止官方新观察已经包括本地请求后再次相加而重复扣减。当前实现保持保守旧基线；若需同月重基线，必须先明确对应 admission 截点与原记录，不能直接改 `official_used` 或减小 admitted_count。

Admin `read_status` 只有 SELECT（含查旧月限制），不初始化、不调用供应商、不认定正式 API 已启用。状态为 ready/access_restricted/quota_exhausted/snapshot_missing/snapshot_expired/snapshot_not_current/unavailable。旧月或无效记录的当前 remaining 为未知；保留官方观察时间。正式 API enabled 与 quota 可用性分栏。

可选 `billing_observation_json` 与同一官方 snapshot 保存在同一表，字段为 period_start、period_end、usage、cost_cny、observed_at、source=`amap_console_bill`、scope=`observed_period_only`。未提供便未知，不从额度推导金额。

## 权限

两表先撤销从 owner 默认 ACL 继承的所有非 owner 表授权，仅针对新建两表；不改变旧表或 default ACL，不使用 CASCADE。然后精确授予：

- API：两表 SELECT；bucket 仅 admitted_count 与六个 block 字段 UPDATE；attempts 的七个 admission 字段 INSERT 与四个 outcome 字段 UPDATE。
- Admin runtime：两表 SELECT，无写权限。
- API 无官方基线 INSERT/修改、无 DELETE/TRUNCATE/DDL；Admin 不获得 admission 能力。触发器阻止计数下降和终态重写。

## 本地验证与失败历史

使用现有 Python3.11 测试镜像和 PostgreSQL16.14，network=none、代码只读，仅一次性 Unix socket 测试库。没有生产 DSN、供应商请求、真实 Key 或业务资料。

最终组合：`tests.test_amap_quota` 28 项与既有 `tests.test_fact_enrichment` 24 项，**52/52 PASS，3.213s**。包含 13 项实际 PG、10 项 SQLite、5 项 HTTP MockTransport/失败处理；覆盖 32 个独立连接抢最后一个额度、40 并发的共享 QPS、4 个进程争用 5 个额度、新月持久授权/限制、未知提交不派发、超时不重试、不返还、实际数据库时钟、只读 Admin 与 baseline/终态权限边界。

独立 ACL agent 的 `tests/test_amap_quota_acl.py` **2/2 PASS，0.746s**：clean defaults 与 PUBLIC + 8 runtime + 额外 grantee 的默认 ALL 两组，逐项验证表级7种权限、列级4种权限、GRANT OPTION、PUBLIC及零初始记录；旧 sentinel 表 ACL 与 owner default ACL 均保持原样。其发现已促成上述新表默认授权撤销修复。

失败历史如实保留：第一轮测试导入现有 db 模块会默认初始化 SQLite，在只读代码目录失败；测试改为只导入 Transaction 所需的无连接模式。下一轮新额度 26 项全过，但 4 个既有美团临时 CLI fixture 因 `/tmp` 默认 noexec 失败；仅将隔离 runner 改为 `/tmp:exec` 后通过，未修改美团业务逻辑。独立 ACL 污染测试曾证明旧版0031遗留其他默认 grantee 授权，迁移已按新表范围最小修复。

## Root 在已授权部署范围内的剩余动作

1. 等待 Item32 真实执行及必要读回结束，并继续避开原 noteai-5ce prepare 到 close/final-readback 的绑定资源变更时段。
2. 固定最终来源与双角色镜像；在实际 schema/ACL 上应用0031并读回（不触碰封存旧 V5 schema 清单）。确认所有 NoteAI 高德调用路径及未来 F 入口都接同一 guard；旧 F 未绑定无 guard 的可活动高德入口。
3. 由 operator 在暂停高德请求的情况下绑定真实官方当前 snapshot：period 明确为2026-09及北京时间月界、quota=50000、official_used=1（如期间实际变化必须重新核实）、确切 observed_at/source/hash、原 owner_authorized_at、企业认证/未购许可/风险接受/仅 NoteAI 标记与原账单观察。本文和 fixture 不提供实际生产观察时点替代值；迁移和 Admin 都不会代填。
4. root 已定位 C `/etc/noteai/api.env` 内现有 `AMAP_WEB_KEY`；仅在 guard 与 snapshot 就绪后内存绑定至正式 `public-account.env`，移除过期等待许可 reason。无需读取/重传/轮换 Key。
5. 正式服务读回与必要真实验证由 root 按既有 owner 授权完成。回滚若使用无 quota guard 的旧镜像，应同时恢复旧的无 Key 正式环境；不能保留已启用 Key 让旧 runtime 绕过账本。保留0031表和原 admission 记录，不能回收未知调用。

以上不是新的 owner 审批体系，也不是提前批准生产已完成。原微信任务、Item34、Item35与Item36前置不变。
