# Item36：原双区 ALB＋双 EIP 费用与执行方案

状态：**原方案、当前报价及实际持续费用已获 owner 批准；未购买、未创建、未改生产，Item36 仍未验收。**

最新执行决定（2026-09-15）：仅在真实 Item33 前置满足且确需实施时创建。
Owner 不批准 ¥300 硬上限或管理预算，也不批准 80%／90% 费用阈值及自动停增流／停服务措施。
按实际使用持续计费，记录与报告真实费用；不能因本文件的历史建议中断已提供的服务。

核对日期：2026-09-15，最新浏览器核对约 12:36 UTC／20:36 北京时间。
本文件由新窗口 Item36 子任务独占编写。它补充 CURRENT EXECUTION CONTROL，
不激活历史调度，不修改现行 DoD，不接管旧窗口唯一 `noteai-5ce` 账单执行。

## 1. 已确认的费用决定

本次已取得四项当前计价依据：标准 ALB 实例费、LCU、两个 EIP 保有费、CDT 公网流量。
中国站价格包含增值税的官方依据也已补齐。此前的 ¥149.04 只是
720 小时＋持续 1 LCU＋两个 EIP 的无流量情景，不能称为固定月费或完整上限。

本次是当前账户购买表单报价，**没有锁价期或合同折扣承诺**。表单明确提示实际优惠以下单页为准。
因此下面同时列出当前显示折扣价与官方目录价情景。未来临执行仍读回当时价格与适用条件；
如发生实际单价或产品配置的实质变化，说明精确差异，不将目录价参照冒充已确认的当前报价。
没有锁价承诺这一事实不再作为重复询问同一原方案费用授权的理由。

Owner 已明确批准下述唯一原方案及当前报价的实际持续费用，费用授权已具备。
正常模型测试授权继续独立；不得恢复旧 ¥50／¥100 模型金额门槛或将 ¥300 设为本资源预算。

## 2. 原方案与当前公开网站的关系

| 项目 | 当前实际／拟用范围 |
|---|---|
| 当前公开入口 | 已公开的 `noteaipro.com`、API、Admin 使用既有 API-C/nginx 路径；沿用真实部署 API `f070ed6`、前端 `0590286`、Admin `4870b4b` 的最近核实记录，本次未重新连接主机 |
| ALB | 原深圳 `cn-shenzhen`，1 个 IPv4 公网标准版 ALB，原生产 VPC；不换成扩展版、公测方案或 WAF 增强版 |
| 区域映射 | 原 C/F 两区，各使用 `noteai-prod-alb-c`、`noteai-prod-alb-f` 专用交换机；本次购买表单均能选择 |
| 公网 IP | 每区自动分配 1 个按使用流量计费 EIP，共 2 个；BGP 多线、默认防护，不加入共享带宽 |
| 原后端 | API-C/F 原私网地址的 8000 端口；C 当前候选保留 nginx 所需 loopback。F 当前仍是原镜像，接入前须按现行发布／健康／回滚契约完成版本与运行状态验收 |
| 入口职责 | HTTPS/TLS 终止、按实际域名和路径转发、后端健康摘除、受控滚动发布；避免 API 入口只依赖单台 C |

双 EIP 是该双区公网 ALB 的两个公网接入地址；官方要求多区地域至少选两个区，公网模式每区配置 EIP。
它们不是给两台 ECS 各增配一个公网地址。标准版选择服务于原有自定义 TLS、优雅连接处理和高级路由需求。
这些用途与当前“已有公网网页能打开”是不同的能力层次。[ALB 创建与版本说明](https://help.aliyun.com/zh/slb/application-load-balancer/create-and-manage-alb-instances)

ALB 的双区能力不会自动使当前单点 Admin、静态文件、F 的旧应用版本获得相同的可用性。
实施仍须使用现有域名／证书／后台权限契约；购买 ALB 本身不证明全产品双区，也不要求此刻切 DNS。
已公开的 `.com` 入口保持原样，不能把旧 `.cn` 证书记录当成覆盖当前 `.com` 的证据。
后续只绑定真实覆盖所用主机名的现有有效证书，精确核对 SNI、Host 和证书链。

Item36 是原版本商业入口验收的一部分，不是当前公开网站正常工作的新增前提。
本次费用准备可以独立完成；其终态仍依赖真实 Item33，capacity100 和 Item34 generation2 已完成并保留。

## 3. 当前完整计费组成

单位均为人民币；ALB 为 1 个实例，EIP 为 2 个地址。

| 计费项 | 本次依据 | 当前计价方式 |
|---|---|---|
| 标准 ALB 实例 | 已登录购买表单：¥0.125／小时；提示目录价 ¥0.147／小时 | 自创建至释放按小时收取；不足一小时按一小时 |
| ALB LCU | 已登录购买表单：¥0.042／LCU·小时；官方目录价 ¥0.049 | 按真实容量使用计费；不是固定购买 1 LCU |
| EIP 保有费 | 已登录深圳 BGP／默认防护／按使用流量购买页：¥0.020／IP·小时 | 两个地址合计 ¥0.040／小时；绑定 ALB 不享受直接绑定 ECS 的保有费豁免 |
| EIP 公网出流量 | 本次 EIP 表单选中 CDT；官方大陆阶梯见下表 | 两 EIP 的实际出方向 GB 合计，按账户所属阶梯结算；入方向不收 EIP 流量费 |
| 税 | 中国站官方说明：产品与服务价格包含增值税 | 下表按页面人民币含税价格计算，不自行额外加 6%；实际发票税目／税率以开票页为准 |
| 折扣与有效期 | ALB 明细：官网折扣价，实际优惠以下单页为准 | 无价格锁定截止时间；不承诺本月或未来每月始终享有此折扣 |

LCU 每小时先对**每个监听**的连接峰值、并发连接峰值、请求及响应数据量和规则评估量分别换算，
取该监听最大值，再将各监听 LCU 相加。1 LCU 对应 25 新连接／秒、3000 并发连接、
1 GB／小时处理数据或 1000 规则评估的相应换算基数。素材上传即使不产生 EIP 入流量费，仍可计入 ALB 数据处理量。
因此下文“平均 1 LCU”是情景假设，不能从用户数、HTTP200 或当前 readiness 分数推算。
[ALB 计费规则](https://help.aliyun.com/zh/slb/application-load-balancer/alb-billing-rules)

| CDT 大陆 BGP 月度收费流量阶梯 | 单价 |
|---|---:|
| 0–10 TB | ¥0.80／GB |
| 10–50 TB 的部分 | ¥0.75／GB |
| 50–150 TB 的部分 | ¥0.70／GB |
| 超过 150 TB 的部分 | ¥0.65／GB |

CDT 按账户及计费地域合并累计；中国内地 20 GB／月免费额度是账户共享额度，
不是每个 EIP 或每个 ALB 一份。本次没有读取账户当月剩余额度，因此所有情景按不抵扣免费额度计算。
只有真实账单证明本资源获抵扣时才减少实际成本。两个 EIP 并不把同一请求的出流量自动乘二，
以两者分别实际传出的总字节为准。[CDT 公网流量](https://help.aliyun.com/zh/cdt/internet-data-transfers/)

EIP 的按使用流量模式按小时结算，独立公网保有费继续发生，未绑定后端不等于停费。
普通 EIP 的按使用流量带宽峰值是限制／参考值，不是保证带宽，也不能理解成包月流量。
ALB 表单显示双区默认 400 Mbps，这不是现金费用上限。[EIP 按量计费](https://help.aliyun.com/zh/eip/pay-as-you-go)

中国站与国际站采用不同税务价格口径；本方案使用 `aliyun.com` 中国站人民币报价。
[中国站与国际站计费税务说明](https://help.aliyun.com/zh/account/aliyun-vs-alibaba-cloud)

## 4. 720／744 小时情景成本

设 H 为计费小时，L 为各监听合计的每小时 LCU 的月平均值，G 为两 EIP 合计出流量 GB。
下表 G 均不超过第一阶梯，使用 ¥0.80／GB；未抵扣共享免费额度或折扣券。

```text
当前显示价格：C = H × (0.125 + 2 × 0.020) + H × L × 0.042 + G × 0.80
目录价参照：  C = H × (0.147 + 2 × 0.020) + H × L × 0.049 + G × 0.80
```

| 使用情景（非流量预测） | 平均 LCU | 出流量 GB | 720h 当前价 | 744h 当前价 | 744h 目录价参照 |
|---|---:|---:|---:|---:|---:|
| 无请求／无 LCU 的纯保有理论值 | 0 | 0 | ¥118.80 | ¥122.76 | ¥139.13 |
| 轻量 | 0.1 | 10 | ¥129.82 | ¥133.88 | ¥150.77 |
| 1 LCU／10 GB | 1 | 10 | ¥157.04 | ¥162.01 | ¥183.58 |
| 1 LCU／100 GB | 1 | 100 | ¥229.04 | ¥234.01 | ¥255.58 |
| 1 LCU／500 GB | 1 | 500 | ¥549.04 | ¥554.01 | ¥575.58 |
| 中等容量比较 | 2 | 100 | ¥259.28 | ¥265.26 | ¥292.04 |
| 流量上升 | 2 | 500 | ¥579.28 | ¥585.26 | ¥612.04 |
| 5 LCU／10 GB | 5 | 10 | ¥278.00 | ¥287.00 | ¥329.41 |
| 5 LCU／100 GB | 5 | 100 | ¥350.00 | ¥359.00 | ¥401.41 |
| 5 LCU／500 GB | 5 | 500 | ¥670.00 | ¥679.00 | ¥721.41 |
| 较高使用 | 5 | 1000 | ¥1070.00 | ¥1079.00 | ¥1121.41 |

其中固定保有部分是 720h 的 ¥90.00＋¥28.80，或 744h 的 ¥93.00＋¥29.76；
LCU 与流量均为变量。持续 1 LCU、0 GB 的原 ¥149.04 对应 720h，744h 为 ¥154.01。
24 小时、平均 1 LCU、10 GB 出流量的演练情景为 ¥12.97。当前费用授权已具备，
此数字仅作费用比较，不授权提前创建或另开一轮无必要演练。

这些数字是**所列负载假设下的新增入口资源成本**，不含既有 ECS、RDS、Tair、NAT、
模型／Render／AWS、OSS 或现有 DNS／证书费用。它们不是全系统月费，也不能拿历史全栈估算替代。
本方案未选择 WAF 增强版、共享带宽、精品 EIP、资源预留、额外证书采购或新日志资源；
以后新增上述任一服务，须先取得其真实增量报价。现有模型出向 NAT 路线继续独立计费。

## 5. 当前 owner 授权与明确排除

| 项目 | 最新决定 |
|---|---|
| 已批准资源 | 原深圳生产 VPC 内 1 个双区 IPv4 公网标准 ALB＋2 个自动 EIP，原 C/F ALB 交换机；BGP 多线、默认防护、按流量 CDT、无共享带宽 |
| 已批准费用 | 当前显示 ¥0.125／ALB·小时、¥0.042／LCU·小时、¥0.020／EIP·小时及上述 CDT 阶梯，按实际使用持续计费；表格不是固定月费承诺 |
| 创建时机 | 真实 Item33 前置满足且确需实施时才创建；准备完成或恢复 checkpoint 不代表立即采购 |
| 费用行为 | 保留实际账单、LCU、双 EIP 合计流量记录与事实报告；没有 ¥300 硬上限或管理预算，没有按 80%／90% 自动停增流、停服务或释放资源 |
| 原技术恢复 | 配置错误、真实健康故障或 UNKNOWN 仍按既有发布／回滚语义处理；这不等同于费用阈值停服务 |
| 范围外 | 未选 WAF、共享带宽、精品 EIP、新 VPC、额外证书或日志资源；不得以本次批准新增这些产品 |

历史建议的 ¥300／自然月管理预算与 80%／90% 告警／停止增流方案已被 owner 明确否决，
保留此句记录其 superseded 状态，任何旧段落或旧证据格式都不得重新激活它。

## 6. 临执行必要检查与原实施顺序

以下沿用现有 Item36，限定当前尚缺的真实材料；不重做素材验收、历史部署或 Item34 观察。

### 6.1 已完成的本地兼容与剩余 F 准备

- **费用证据格式已兼容：**`tools/internal_deployment_readiness_gate.py` 保留原 Item36 v1，
  新增本轮 v2 报价／持续费用授权。`authorization_mode=ACTUAL_USAGE_CONTINUING` 时省略
  `approved_monthly_ceiling_cny`、`approved_variable_egress_ceiling_cny`、`quote_valid_until`，
  报价省略 `valid_until`，显式记录 `CURRENT_DISPLAY_NO_LOCK`；加入这些旧字段仍会拒绝。
  授权必须记录 `cost_triggered_service_actions=NONE`，不会将本轮批准变成按费用自动停服务。
  原授权、报价和临购同价同配置读回均绑定可审查来源路径／SHA，仍严格核验四项真实账单、资源身份、
  时间顺序和各费用合计；费用超过旧表格情景也可如实验收，不虚构预算或账单零费用。
- **当前主机名已兼容：**本轮 actual-use 授权绑定 `api.noteaipro.com`，同时验证证书、SNI、Host；
  原 `ITEM36_API_HOSTNAME=api.noteaipro.cn` 和 v1 历史格式保持兼容。
  不靠额外 DNS 切换或将 `.cn` 证书当作 `.com` 来满足旧常量。
- **C/F 版本差异：**使用 `tools/prepare_item36_private_bind.py` 原 renderer、现有 C/F fixture 与
  `/Users/openclaw/.codex/tmp/noteai-item36-current-api-c-f070ed6/` 候选／rollback。
  本地兼容修改只运行对应必要检查；已过的 17 项历史 renderer 检查仍保留，不当作未来生产结果。

本轮 v2 使用 `noteai.item36.recurring_cost_approval.v2` 与 `noteai.item36.aliyun_cost_quote.v2`，
原 terminal／billing v1 外层不变。quote 和 approval 共同绑定原 VPC SHA、C/F、Standard、IPv4、公网、
2 EIP、BGP、按流量、无共享带宽及当前 API 主机名。quote 保留含税、720／744h、实际 LCU 情景、
完整 CDT 阶梯与不假定免费抵扣的口径；`purchase_readback` 只保存购前真实同价／同配置确认，
不是新的 owner 批准。原 `estimated_monthly_cny` 保持历史的 ALB＋LCU＋EIP 小计语义，
新增入口总情景费仍须加 `estimated_variable_egress_cny`，如 744h／2 LCU／100GB 为 ¥185.256＋¥80。
这仅定义证据的兼容表示，未生成任何生产 terminal、价格锁定承诺或新的人工签署要求。

最近已核实的差异如下，本次只是读取原私有记录，没有重新连接主机：

| 范围 | API-C | API-F |
|---|---|---|
| 私网 IP | `10.42.10.44` | `10.42.11.166` |
| 当前镜像 | `f070ed6`／image `6733bb5fe842502204cebb480ac8a51461ef5d5c05961754decc17428e5b8be0` | 原 manifest `612a7e57b8a4226e4c23be6267ee60fb79677cae9eb46ea1843aed11fc517620`／image `dd955f9e736fc00df471f39de6e483ed0873f5855cc0ffffc074823845fefd53` |
| 单元与配置 | 原 base unit 加当前 `public-product.conf`；有效 PGOPTIONS 为只读 off、statement 10000、lock 5000 | 独立原 F unit、无 drop-in；原 PGOPTIONS 为只读 on、statement 5000、lock 1000 |
| 当前监听 | loopback 8000，nginx 使用中；候选再增加 C 私网 8000并保留 loopback | loopback 8000；不能直接接作当前正式产品后端 |
| Payment | disabled／inactive，容器不存在 | unit／容器不存在 |

C 候选 SHA `6bc99fdeb3cc41029ad253228613fcc03f841b9875ff5905646c1b3e7eec8bee`，
对应 rollback（原 drop-in）SHA `83a570ff3e67a03c32c43b3cfad3cb02172ff296301fcb8b8bfd47d023046643`。
原 F unit SHA `f591f43b0377402dbc026c4e7f5eee08bc8b884fd9e3523fe775fa5a8f0bb936`。
如果临执行有合法后继，重新绑定实际内容；不恢复这些历史 SHA 来强行应用旧候选。

F 需要补齐同一正式产品候选镜像、合法现行配置和有效数据库会话语义；仅改私网端口不够。
不能将 C 专用 drop-in 原样复制到 F，也不能以复制 Secret、扩大 DB 角色权限或自动跑迁移代替配置核对。
如真实角色权限不足，指出具体缺失操作及作用域；既有受控部署授权能覆盖的最小配置修正直接推进。

### 6.2 只在临执行读取一次的真实输入

1. 读取原 Item32 terminal＋Item33 managed promotion/internal rollback 结果，确认 Item33 前置真实满足。
   沿用已 VERIFIED 的 capacity100 与 Item34 generation2；不重跑 24h／3d，不重建 T0。
2. 通过旧线程或其唯一结果确认 `noteai-5ce` 未处于 prepare→close/final-readback 占用期。
   如已 prepare，保持本地准备／只读直到原 close 确认；不创建第二条对账。
3. 读取当前 ALB 列表、原 VPC/C/F 交换机及精确现价；防止其他合法后继已创建后重复购买。
   核对账户现有现金状态与实际拒绝信息，不查看或打印凭据，不自动充值。
4. 读取两台当前 IP、unit/drop-in SHA、不可变 image、CID、绑定端口、enabled/active、Job、
   NeedDaemonReload 和 Payment 状态；保存逐节点精确 before-state。只读实际所需配置字段，不导出 env Secret。
5. 核对当前精确 SG、现有 TLS 证书覆盖／有效期／链、server group／HTTPS listener 方案。
   `.com` 当前记录及 nginx before-state用于保留已公开入口与恢复，不以旧“DNS为空”历史记录执行。

### 6.3 原部署、SG、TLS、listener 与验证

1. 在已确认的原 VPC／两交换机创建唯一标准公网 ALB，取得真实 ALB／两 EIP 身份，
   使用原服务器组、HTTPS443、现行 API 主机名和有效证书的精确绑定。
   只登记两台合法当前 API 后端的私网 8000；未验证后端不放入接收用户流量的状态。
2. 执行前核实 API SG 仅向**真实 ALB 后端连接来源**开放 TCP8000。
   原 ALB 子网为 `10.42.0.0/24`、`10.42.1.0/24`，不是 app 子网 `10.42.10.0/24`／`10.42.11.0/24`；
   临执行按真实 ALB 来源及既有最小范围规则应用、读回，不增加公网 0.0.0.0/0 的 8000 授权。
3. 沿原有 C→F 有界滚动顺序，一台通过后再推进另一台；始终保留已验证入口的恢复条件。
   C 保留 nginx loopback并增加原私网映射；F 使用自身单元与正式候选，核对生效角色及数据库连接语义。
   不能用“F原API active”替代其当前正式版本验收，不能把尚未验收的 F 当成已可承接流量的冗余。
4. 若执行当时 Payment 已启用，替换 API namespace 前按原流程停其关联服务，API 通过后
   明确在新 namespace 重建／恢复原启用状态；如仍 disabled／absent则保留，不因 ALB开启支付。
   `BindsTo`／`PartOf` 不代表容器自动恢复。Admin与静态内容不因接入API后端自动复制或变更。
5. 每节点核对新 CID、私网／loopback socket、`/health/live`、`/health/ready`及原重复健康读回。
   ALB健康仅检查进程、必要DB／模型资产，不新调微信、XHS、Claude或素材供应商。
   读回两个后端、SG、TLS/SNI/Host及当前listener；保留正式SSE所需现有超时／代理语义。
6. 按原规则形成 post-activation 健康与 API-F 三个准确命名单元的 NDR读回，
   不重放 `production-item36-ndr-convergence-20260904.json` 中旧 mask7→0 操作。
   用更新兼容后的**原** Item36 validator验真实身份、顺序、结果、账单和授权来源；通过才写 terminal／计分。
   流量仍是受控 provider-free 探针，完整商业链和实际 ingress/ramp 留给既有 Item37／38。

### 6.4 原恢复范围

已知技术失败按原节点 before-state 恢复精确 unit/drop-in、image、端口和 Payment 原状态，读回确认；
UNKNOWN先只读查明，不猜成功、不自动重复创建／应用。保留原镜像、数据库与所有历史证据。
任务创建资源的技术回滚只使用已返回的精确ID及原记录，恢复既有入口后依原授权处置，
不删除其他资源、不清库、不回放付款／退款／回调。

费用高于表格场景不触发这套技术回滚。Owner已选择实际持续费用，
没有金额自动停机、停增流或释放动作。Item37／38在真实依赖满足后继续，不重复已完成DNS发布。

## 7. 高德的独立外部办理项

本次现有账号信息页仍显示**认证个人开发者、未获得技术服务使用许可**。
没有读取、替换或索要现有 Key；历史成功记录不变，不自动购买许可。

- 当前认证入口：[控制台 → 账号中心 → 账号认证](https://console.amap.com/dev/user/permission)。
  账号信息页的“升级企业认证”是现成操作入口。
- 适用许可与价格入口：[高德服务升级／技术服务许可](https://lbs.amap.com/upgrade#business)。
- 实际使用场景或认证主体需要澄清时：[高德工单](https://console.amap.com/dev/ticket/list)。
  提交需 owner 具体授权；本次没有发工单或联系第三方。

高德官方说明企业认证可走企业支付宝授权、组织授权或对公打款等渠道；认证材料由相应主体提供。
[企业认证说明](https://lbs.amap.com/faq/account/certification/40342)
现有个人账号拟为企业取得许可，需先完成适用企业认证；许可另受实际场景和服务协议约束。
[技术服务许可协议](https://lbs.amap.com/pages/authorization/)
此项费用与身份办理独立，不阻断无关工程或 ALB 报价；不把已有 Key 缺失当成新的问题。

## 8. 本次核对与留存边界

- 阅读适用 AGENTS、Handoff CURRENT、architecture/risk 顶部及 Item36 定向索引、现行 readiness。
- 沿用私有原材料 `/Users/openclaw/.codex/tmp/noteai-item36-current-api-c-f070ed6/`；
  没有读取七条受保护文件内容，没有修改 Handoff 或其他 agent 文件。
- 本次 Chrome 报价表单：ALB tab `1637491928`，EIP tab `1637491931`；
  核对的是选项、可用交换机与当前展示价格，未保存配置清单、未点击立即创建、未接受协议。
- 原高德 tab `1637491694` 只读账号认证状态与链接；本文件不保存个人身份、手机号、邮箱或账户凭据。
- Decimal 独立计算全部情景与固定／变量分项；`git diff --check` 检查本文件及本轮 gate／测试修改。
- 尚未发生 ALB/LCU/EIP 新用量，表格没有把预测标成账单；不存在新 Item36 terminal 或 readiness 计分。
- 最新owner决定后的修订仅使用现有文件／已留存读回，未再次访问云端、高德或其他外部接口；
  修改本文件、`tools/internal_deployment_readiness_gate.py` 的 Item36 段、
  `tests/test_item35_item36_evidence_gate.py` 的 Item36 测试，未 commit，未写 Handoff，未改生产／候选配置。
- Python3.11、禁用 socket、临时合成夹具中 28 个 Item36 测试通过，覆盖旧 v1、当前 `.com`、
  720／744h／LCU情景、超过旧预算的真实四项账单、来源篡改、过期／错时购前读回、旧字段降级、
  错域名／证书、错误 VPC／版本／税／免费额度／流量阶梯。不存在真实外部请求或费用。
- 对照本次基线的 30 个 Item32 函数／常量 AST 均未改变；同文件 Item33 由另一子任务独占修改。
