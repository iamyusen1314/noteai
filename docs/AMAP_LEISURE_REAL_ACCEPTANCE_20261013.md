# NoteAI 修复版真实验收进展与发布交接（10月13日）

记录时点：北京时间2026-10-13 00:12，后续更新见下方当前控制。**真实验收未完成，当前不能给出满足上线条件的结论。** 本窗口没有部署、供应商检索、付费模型调用或生产数据库连接。

## 最新交付决定与生产职责（覆盖此前安排）

Owner先明确旧版小修复优先，不等待大版本；随后直接将代码核对、隔离真实验收、部署及上线后验证的完整交付转给**本窗口**。原“启动NoteAI授权续期发布”只继续后续大版本隔离开发测试；本次不含App86/H5f185切换或0032–0041。

已向核实的原窗口发送明确生产交接请求。**2026-10-12T16:31:37.340382Z（北京00:31:37）收到明确确认**：对方核实人类原消息、无未结束生产操作，本窗口独占生产变更，原窗口暂停部署/迁移/切换/RAM附加及冲突操作，只继续新版隔离工作。[正式无秘密交接回执](/Users/openclaw/.codex/private/noteai-host-path-owner-20260930/safe-owner-production-handoff-20261013.receipt.json)已读；最后源码安装已终态Success0/Dropped0，未产生新维护或业务改变。当前生产仍须新鲜只读检查，不能把15:03时的zero-inflight沿用为当前门禁。不复用已消费维护T0，不中断在途恢复。上线验证后实际源/module/image/static/config delta及真实结果交回原窗口为新版新基线；小修复失败先恢复已知旧版并保留新业务数据，不转大升级。

最新有效旧版代码为 `d3d9edbaca5a4348e080522c2fe6c1ca6b1fab38`，仅追加休闲医学边界与分句否定校验及其专属回归；17项行业方法通过。下方d81/7e表是前序checkpoint，现已包含在d3，旧版基线仍d28。新增代码不改变共享配额/PG结构/Prompt装配，已完成PG24与公共框架审核适用范围复用，不从头重复。

## 验收对象与实际运行状态

| 对象 | 精确版本与证据 | 当前结论 |
|---|---|---|
| 首个已上线版本 | 历史源 `d28f79c1702860a54e2e5174b7a569bdcd5707c8`，API image `sha256:35a61b6c37c06539e0053340b17f187458cdb9d912b11302a949c45e315b428c`，静态构建 `generation-recovery-d28f79c17028-s2`；发布窗口10月12日15:03UTC恢复读回仍为旧API/旧路由 | 两项问题受影响；当前运行Key/月桶尚未新鲜核实；恢复不等于新版上线 |
| 旧版独立修复源 | `d81fe6ef0db1db8f84a1b4d4288dcf0cf767dad6`，分支 `codex/amap-leisure-repair-20261012`；行业运行源来自 `7e478b0d71404aa84acb0cd1697519feaf5b0d24` | 源码修复及隔离PG通过；尚无加载真实依赖的应用build/runtime |
| 独立候选适配源 | base `4bdb58b0aa650840f167ad1797d055d8caa06f14` → 原修复 `18e46e8` → 新项目绑定 `3122775` → PG测试 `7df7b8a879d997aac02a5d8e2f6000f8c39689d8`；无冲突/clean | 保留原durable fence及候选变更；25项受影响回归通过；不是发布窗口候选产物 |
| 原发布目录与目标 | `shared-account-main-integration` 最新只读观测控制源 `efa4f50658402f626bdcfd0277820caa2cc9b26d`，最后变动是恢复测试；目标应用 `86ff10d`、H5 `f18584d`未变 | 发布方明确18e尚未纳入，未有新修复产物/运行版本；最新7df纳入待确认 |

没有用旧版运行结果证明修复有效。需要由原发布窗口提供隔离环境实际源码/module SHA、API image、原H5静态SHA、进程载入路径与生效配置，才能启动真实修复版业务验收。

## 四类证据分别记录

| 证据类别 | 已执行与结果 | 尚未证明 |
|---|---|---|
| 浏览器 | Chrome真实高德配额页显示基础搜索月额度50000、各搜索当月/当日显示用量0、QPS30；美团官网显示已登录，进入AI Hub只读页 | Key/Token运行绑定；实际检索HTTP；修复版PC/H5真实用户流程；美团API授权。登录不等于Token有效 |
| 数据库 | 实际隔离PostgreSQL16.15，24/24 PASS、0skip，事务/角色/只读/锁/并发/续期/恢复/CLI真实执行 | 生产当月桶和Key；生产续期；完整业务报告/扣分数据库链。材料和Key为隔离fixture |
| 真实供应商检索 | 0次；没有冒充成功结果、缓存或RAW_JSON | 高德正常检索/真实月度续期后查询；美团授权、候选可执行路径和业务事实采用 |
| 真实模型 | 0次；已完成60个源码装配捕获及Prompt框架比较，均在transport前停止 | 实际DB模板加载、真实视觉、生成/诊断输出、最终报告保存/重开和准确扣分 |

前轮本地UI1440×900/390×844与mock模型结果仍只作为离线回归。390×844是手机尺寸模拟，真机未执行。当前没有新修复版页面真模型验收结果。

## 高德真实控制台观察及安全绑定

原页面：`https://console.amap.com/dev/flow/manage`；产品选择“基础服务”，表项“基础搜索服务”。同一登录首页此前显示企业认证为易事快（广州）咨询服务有限公司，但配额截图自身没有Key身份。截图/AX原件捕获文件时间为2026-10-12T16:00:11Z（北京10月13日00:00:11），**不是供应商统计刷新时刻**。

- [真实配额截图](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/browser/amap-console-october-observation.png)，SHA256 `b250e277d7655197bca04445a14e4b6444a71eb4b9920e58321bac92cc993115`。
- [真实页面AX](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/browser/amap-console-october-observation.txt)，SHA256 `6faaf5a697c005fe05abc972f22186d35ac146924a51321f561acb84fd58b00f`。

不能把50000复制到隔离DB后直接查询，否则会分裂同一账户配额。原发布方须在既有秘密通道内仅内存比较实际API进程Key与保留 `noteai-rot-0902` 来源，输出相等布尔、账户/服务类型及核对时刻，不输出Key或指纹；随后结合原共享账本admissions/denials和真实DBclock，由其统一安排当月真实材料plan/apply/readback。当前观察没有被本窗口入库。

完整原因链与月度运营闭环见 [原修复记录](AMAP_LEISURE_REPAIR_20261012.md)。证据支持缺少月度观察续期闭环，不支持Key失效/耗尽/高德故障的推断。修复保持安全停高德、UNKNOWN不回退及事实缺失不编造；实际当月恢复仍待验证。

## 实际PostgreSQL结果与异常测试范围

新增测试提交 `d81fe6e` 仅修改 `tests/test_amap_quota_real_postgres.py` 和 `tools/run_amap_postgres_acceptance.py`；0031迁移SHA保持 `58673d89e80331c56b9561f1cbb61b6dd7f2448ee6e89b4937df3fa2a35de445`。

2026-10-12T15:41:14Z–15:41:16Z，实际PG16.15，原quota13+ACL2+新增renewal9=24/24通过。验证真实角色写入拒绝、READ ONLY、账户advisory锁、12并发续期仅1追加/11NOOP、20并发请求仅10准入、刷新失败rollback、当前月恢复、同月冲突/幂等、实际CLI plan/apply/noop。新续期用真实 `clock_timestamp()`；原月界测试保留原有历史mock业务时钟，没有改变操作系统/生产时钟。

正常/过期/配额不足/授权限制及跨月保留/刷新失败/恢复/幂等在隔离fixture验证；并未耗尽真实额度或破坏有效凭据。提交响应丢失UNKNOWN等前轮专项是mock故障测试，不升级为供应商或真实网络故障证明。

- [24项原日志](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/postgres/run4/tests.txt)
- [实际测试回执](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/postgres/run4/receipt.json)
- [版本、源码与清理清单](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/postgres/runtime-and-cleanup-manifest.json)

运行时来自官方Homebrew/core免费bottle，仅提取到本任务tmp目录；无全局安装、无服务启动、无TCP监听。自己的唯一Unix-socket cluster/数据库/进程已清理；原两Colima保持Stopped，生产连接/供应商请求0。准备阶段三次失败原件保留：两次本地bottle路径问题；第三次锁观测测试缓存了PG统计视图，仅测试用 `pg_stat_clear_snapshot` 修正，业务锁没有改变。

## Prompt框架审核与新增修复

基准为现有美食/旅行/健身的代码、managed基线与保留的RQS历史验收文档。项目确有统一框架：12个managed键和请求snapshot，公共composer/质量/治理层，生成三专家与仲裁、诊断四专家与仲裁、独立正文整形、标题/正文/话题解析和终态质量门禁。新行业沿用它们，不另建第二套基本Prompt。

合理差异是五类项目的真实空间/流程/服务/套餐/预约/作者感受槽位、决策信息/体验/取舍三方向及医学功效限制。洗浴、汤泉、水疗/SPA、按摩、足浴/足疗共享canonical行业；具体服务仍必须来自本次素材/事实。图像不能证明水温、卫生、技师资质、价格、包含项目或疗效。实际无事实或失败应保留明确缺失。

源码审核发现并修复三个反例：源按摩60/水疗90被写成按摩90；源足浴45被写成足浴90；套餐A含按摩/B不含被写成B含。`7e478b0` 在 `model/api.py` 将项目+时长/单位及套餐scope+服务+正否+包含/赠送条件绑定，新增 `tests/test_leisure_industry.py` 反例；16方法通过，95分也不放行硬事实错误。普通金额/池温规则仍有限，不声称任意自然语言事实已形式化验证，实际输出需要逐项对照来源。

[逐项框架审核](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/prompt-audit.md) 与 [60个装配指纹](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/prompt-assembly-manifest.json) 明确：内存文件基线snapshot，transport前停止，不连接生产managed表、不调用真实模型。诊断部分专家的显式factsafe追加与美食不完全相同，新行业走通用source_policy+行业知识，仲裁再次加事实安全；不把预览或文本相似性当作完整生效验证。

## 最小真实批次、预算与授权素材

未执行的完整准备矩阵是5次生成、13次真实extract、1次九图included_merge、1次新的正常诊断；约20个业务主请求，报价按当前源码为52.5积分。服务实际quote读回优先，未调整价格/余额/资质。九图只能合并同一笔记本人已完成的9个OCR来源；纯B照片合并0模型，必须标本地处理。含真实A/C文字且合并正文≤24000字符才会一次真实语义合并，不能伪造OCR结果。

| 项目 | 条件化准备上界 | 状态 |
|---|---|---|
| 全部模型admissions | 5gen408+13extract+1merge+1diagnosis81=503；包含内部评分/整形/标题压缩 | 未执行；诊断标题pool数量及并行启动前守卫必须实际验证 |
| 模型费用 | 源码默认价卡/FX7及有限总输入/输出条件下约133.37元，拟本批150元预留 | 提案，非已批准费用/技术硬上限；active价卡、override、gateway、无隐藏SDK retry尚未知 |
| 高德 | 最多5真实物理HTTP；若诊断auto再次检索则7；同一账户串行准入 | 原共享额度内，无购买/超额；费用未知，未调用 |
| 美团 | 最多1只读query | 真实授权/内部HTTP/费用未知；候选durable fence当前阻止CLI，不能绕过 |

有请求计数不代表物理HTTP计数。`NOTEAI_PUBLIC_PRODUCT=1`限制外层尝试并禁fallback，直接Anthropic SDK默认内部重试与gateway下游实际行为仍须核实。必须先验证每物理调用的原子最坏费用预留，原完整输入超出计划则停该case，不能截断素材/降低质量来凑预算。UNKNOWN/timeout/authdeny保留原请求，仅只读核对，停止后续，禁止自动重试/换模型。供应商/记忆等未知费用不按0计入模型小计；不创建订单或触发支付。

用户本轮直接授权复用**今天新建的“水石清池汤泉生活”两条报告：一条9图，一条视频**及素材。原ID、创建时间、账号归属、原媒资安全引用还未读回；仅在修复隔离环境创建新验收请求，保留原报告和原扣分。9图可提供真实汤泉单/九图用例，不能当SPA/按摩/足浴素材；这些代表类别仍需真实对应素材。视频重处理未计入上述最小预算，不默认执行。现有素材授权不等于修复runtime可用或新增费用已批准。

本窗口自己的Chrome只读页 `https://noteaipro.com/` →“报告”实际显示“登录后查看报告历史”和“查看不会重新生成或扣分”。没有使用其他窗口的页、导出Cookie或读取密码；已请求Owner在独立报告页自行正常登录。导航首次等待超时后只读绑定同一已创建tab，页面加载完成；未重复提交业务请求。[登录缺项截图](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/browser/noteai-report-read-auth-required.png)，报告ID读取0、模型0、扣分0。

随后Owner回复已登录，本窗口只读重新打开两个原报告：九图ID `762270cc-51f6-427d-b27b-687a9a260f88`、页面时间2026-10-12 11:28；视频ID `77ede81c-a33a-4dd1-8ac5-b98d63967400`、12:18，两者存为美食。Owner进一步确认：九图是包含洗浴、水疗及自助餐的大型休闲项目，餐饮素材是真实组成，不能一概排除；视频是因为旧UI没有合适本地生活体验选项而手动选择餐饮，**不能归因为模型自动误分类或用户错误**。缺口是通用行业选项与适用整体场景的行业框架。九图专家的“喝汤/必点汤品”是否适用应逐项核实，不能拿真实buffet推定这些具体项目；用餐建议本身不等于无关。新行业须兼顾整体休闲体验和真实自助餐，不把有效食物图丢弃。

九图有主图+其余8张保存观察；视频31秒的保存观察含SPA、推油按摩与白色热敷包等动作。它们是未来对应素材的线索，原像素/brief仍未取得，不当本次视觉模型验收。两原报告正常重开，4040.5积分显示前后未变，8分receipt是原历史展示，不是新请求收费；笔记库原笔记/历史版本存在，未点会创建对话的继续优化按钮。

原报告DOM：[九图](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/browser/authorized-nine-report-read.txt)、[视频](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/browser/authorized-video-report-read.txt)。页面素材清单只有产品logo/favicon，没有原9图/视频像素，仍需既有安全媒资读取通道。原brief尚未取回，不能因此认定作者从未提供个人感受；d3只补明确症状适用/医学结果断言，营销名称“理疗师/理疗床”不会一概排临床，也不泛化新NLP。

## 必要环境依赖与后续顺序

1. 原发布窗口确认隔离修复build/image/static/module SHA，提供原合法sealed配置通道；本地当前进程仅检查变量存在性，实际AMAP/Meituan/Ark/gateway/DB变量均缺，未读取保护的.env/秘密文件。
2. 既有获准正常测试账号session、独立业务DB/对象前缀及两条授权报告的安全素材引用；实际quote/credits/用量和report terminal可读。不得复用旧任务ID来重新计费。
3. 同一高德账户级准入、当前Key绑定/官方材料/桶/DBclock；生产月桶apply由原发布方决定，不能另设5万额度。
4. 原合法模型gateway、active模型ID/价卡/计数/重试的证据，以及12个managed模板DB版本/SHA和trend配置。新域缺趋势时原503规则保留，不能伪造新行业benchmark。
5. 候选美团安全可执行路径、实际Token授权与一次未知费用是否在原范围内；无路径时按失败/未支持报告，不删fence。
6. 条件满足后串行运行真实PC与390×844流程，记录provider/model请求ID和脱敏结果，事实逐项对照，保存/重开/扣分核对；真机另列。异常仅隔离安全注入，真实供应商结果另列。

## 跨窗口交接与上线安排

已核实目标标题“启动NoteAI授权续期发布”、ID `01a0f7cb-70cc-71d3-bd42-2cc75bdae2d3`。发布方已经明确旧修复18e尚未纳入，生产安全恢复已完成但没有新版业务上线；本窗口本轮完整新增代码、真实PG、Prompt审核、材料授权、预算与依赖清单已发送，**最新7df是否实际纳入候选构建仍待对方回执**。发送成功不等于纳入，纳入不等于部署/生效。

此前两种发布安排的比较保留在原修复报告中作为历史。**Owner现在已决定旧版先发，并由本窗口交付；不再等待大版本或要求重复选择。** 当前安全恢复优先，这不是要求未经交接或关键验证立即改动生产。仍需原维护流程、可用恢复与实际build绑定，不把补丁混入已完成的安全恢复。没有承诺上线时间。

完整脱敏证据索引：[acceptance-evidence-index.json](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/acceptance-evidence-index.json)。跨窗口消息及成功发送回执：[交接全文](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/release-handoff-message.txt)、[工具回执](/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/release-handoff-send-receipt.json)。
