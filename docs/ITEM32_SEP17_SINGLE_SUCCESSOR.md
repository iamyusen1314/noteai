# Item32 — September17 唯一后续执行

## 当前状态

**唯一执行已结束：HOLD；调度PAUSED，不得再执行下方历史默认入口。**
实际run `run-arx52z4k`，admission01:02:42.067456UTC，outer exit2于01:03:05.214892UTC。
前置真实fresh0/34通过，第一DSL初始化01:02:43.314614发出，约20秒后记录network_error/unknown，
没有收到HTTP响应或业务码。总物理请求1（初始化DSL1、session0），采集admissions0，
初始化UNKNOWN1、采集UNKNOWN0、自动重试0。未到homefeed/推荐，不推断账号冻结/登录过期。
observation_complete=true仅表示dispatch→unknown有完整记录，不表示请求结果已知。
原PG前后强制只读、0写入、无xid、ROLLBACK均完成。最终01:06:56UTC已恢复清尾，
01:07:56UTC原host封存摘要读回一致：6794bytes，SHA
`163eeaca405359bfd20afaf0186133c8be14f71609df41788131d5a3b466d3d1`。
原字节：`deploy/production/evidence/production-item32-v5-hold-final-readback-20260917.json`；
host为新work下`hold-final-readback.json`，包含原十份文件摘要、实际安全receipt/计数及PG证据。
unit/会话/20前驱文件不变，三个任务label与固定容器空，本周期runtime已清。
Sep16原session-transfer目录保留未读，不作为本次临时目录删除。费用UNKNOWN。

本次一次性授权已经使用，虽然采集0/34，不能再用它启动。无新后继或自动重试；
后续真实诊断/执行须另有明确有限范围及有效窗口。只读原结果命令仍适用，缺candidate的
UNKNOWN_HOLD不替代实际初始化UNKNOWN1。Readiness仍32/37；33/36/37/38依赖未关闭。

## 历史准备状态与执行规范（默认dispatch已使用，禁止重放）

Sep16 15:10UTC 已读取原F合成回执：`SOURCE_PACKAGE_STAGED_NOT_EXECUTED`。
15成员全部匹配，原11份前驱、Sep16新9份原件、原host final seal及会话摘要通过wrapper预检。
新work root及四个dispatch标记不存在；本次暂存供应商请求0、生产数据库操作0。
这不代表明日fresh配额、供应商可用性或Item32验收通过。15:12:37.218UTC专用工具已创建
唯一heartbeat `noteai-item32-sep17`，ACTIVE、一次、归属当前任务。工具view与已保存配置核实，
本机CST+0800下对应Sep17 09:00BJT/01:00UTC；这是规则/配置核验，不是scheduler内部nextRunAt读回。
当前只有此一条活动Item32；本地执行需要电脑开机、Codex运行及原控制台会话可用。

原source92dad86的Sep16周期仍HOLD：11collection+2初始化=13物理HTTP；10homefeed成功，
第11collection在search_recommend HTTP200/success=true/code1000被本地统一code0限制拒绝。
原建议内容有效性UNKNOWN，不事后改判成功或归因账号冻结。原前后PG强制只读、0写入及
14:40:08UTC停机清尾证明完整保留。Sep16生产attempt0不清除本机隔离11次用量。

## 唯一窗口及授权

- 时间：**2026-09-17 01:00–02:00UTC / 北京时间09:00–10:00**；启动严格早于01:40UTC/09:40。
- 原owner接续消息时间：2026-09-16T02:17:00.658Z；原消息SHA
  `86705210def8939b2eac3a19bf713a00e741fdcde13829ef33c283d13ab63fd6`。
  原授权允许登录恢复后有限真实验证，并在本日不fresh时安排唯一有效后续窗口；不伪造新确认。
- 执行前实际同UTC桶fresh0/34，最多34次collection admissions；DSL/session各一次冷初始化
  单独记账，总物理HTTP上限36。零自动重试，无额外diagnostic、模型请求、订阅或云资源。
- 原数据库只读probe、隔离store、本轮结果和必要恢复沿既有执行器。网络/请求费用按真实结果记录，
  未取得依据保持UNKNOWN。保留此前累计14collection和另2初始化，不清零、不重放旧身份。
- 过窗、明确限制、再次失败或UNKNOWN：停止受影响调用，仅读原结果和必要恢复；不补跑余量、
  不自动改期或新建另一个successor，不自动登录/换号/绕过安全验证。

## 固定来源与入口

唯一主机：原API-F `noteai-api-f`，ECS实例 `i-wz9bgztwf1tiakww2ops`，深圳。
复用Chrome原云助手页面：
`https://ecs.console.aliyun.com/server/i-wz9bgztwf1tiakww2ops/command-invocation-list?regionId=cn-shenzhen`。
现有登录若失效，只恢复原账号正常登录，不要求聊天提供任何凭据；不得越过启动截止。

| 对象 | 固定值 |
|---|---|
| Git source | `84f2e6e6ff97e0559335f3ebadfdccabb9ccd280` |
| stage | `/var/lib/noteai/item32-v5-package-20260917-84f2e6e` |
| 新work | `/var/lib/noteai/item32-v5-successor-20260917` |
| 唯一wrapper | 上述stage下`dispatch-once.py`，14975 bytes |
| wrapper SHA256 | `6e6d59510fd1c61e1c426f85d81f32c9ba050a5f3a1232af7b7d5ecb53c96471` |
| 源码包 | `item32-v5-source.tar.gz`，153789 bytes |
| 包 SHA256 | `188caa1e14530edee8cb7fa1c14456a5197efa93c992895a310c3eda35ff7d29` |
| manifest SHA256 | `301e4aa27b9805c5f77cc1b7bf76c0b829e20a3de84a855bd02ada1fc162f939` |
| plan | `deploy/production/plans/item32-v5-sep17-successor-prospective.json` |
| plan SHA256 | `f51e926151cdee075a6f9eefe6f22ee23e0305e3dc29dae5910580934839076a` |
| executor SHA256 | `66bc5ceebe13dcc83fe5322e3f1996e7c614369b191bd036a4b2f71848952d5d` |
| gate SHA256 | `35166500b3cbb945b4395503755cda8576252628eafaa6a86cb0574061705b6d` |
| 当前会话env SHA256 | `18f72f26971be0f578342ea7f8ae6336c7ee66ea67f6e7246b2b7d3866d26f6a` |
| 原unit SHA256 | `3ed7e555d61c8286ab6d1116d99171d23d073b6a318dbd4890ce3106b976e3b6` |
| 现有image | `sha256:6d5dcf058c5a0990ba7df3103f63e414de69b62b0ec3481c08490d66ae30b703` |
| 暂存原回执 | stage下`source-staged-result.json`，534 bytes，SHA `1ac3e47203faa30a85e8d866968429052022f8a5e4edbb0a67b1f0e1e673f422` |

本地私有准备目录：`/Users/openclaw/.codex/tmp/noteai-item32-session-recovery-20260917/`。
原inventory是复用来源，非新fresh证明。包仅14个Git来源文件+manifest；不含env、Cookie、
用户素材、运行数据库、模型资产或七个受保护路径。六个runtime overlay以plan逐字摘要为准。

## 到时执行及原结果读取

先读当前AGENTS与Handoff CURRENT，核实际UTC、任务/四marker、新work、原前驱、unit及会话摘要。
任何既有dispatch标记或work都意味着先读原结果，不得再次运行默认入口。确认wrapper实际字节SHA
一致后，在窗口内仅一次运行：

```sh
python3 -E -B /var/lib/noteai/item32-v5-package-20260917-84f2e6e/dispatch-once.py
```

云助手使用原立即执行入口，超时保留1800秒；不额外加会在清理前杀掉执行器的外层timeout。
wrapper自身先查窗口，二次校验会话后唯一Popen；执行器在原共享锁保护下完成实际镜像overlay
断网preflight、前PG只读fresh probe、唯一admission和最多900秒采集、后probe与恢复。
第一次homefeed无有效数据即停止；推荐code1000仅在success=true、data.sug_items实际可用且
没有受限/安全错误时接受。原HTTP状态、业务码、安全诊断、阶段及实际建议计数贯穿原receipt。

失联或任何不确定结果都只读回原记录；以下命令不启动采集：

```sh
python3 -E -B /var/lib/noteai/item32-v5-package-20260917-84f2e6e/dispatch-once.py --readback-only
python3 -E -B /var/lib/noteai/item32-v5-package-20260917-84f2e6e/tools/execute_item32_readonly_trends_successor.py --v5-sep17-readback-only
```

旧`--v5-readback-only`明确保留Sep16身份，不能用于Sep17。readback枚举UNKNOWN_HOLD可能仅是
没有candidate；供应商UNKNOWN计数必须读取原admission/store/worker receipt另行确认。
从实际run读取原前后DB proof、HTTP observations、隔离store计数及candidate，不制造缺失证据。
最终另核原unit inactive/dead/disabled/PID0、三类任务容器及临时runtime清尾、env摘要不变。
只清理由本轮明确拥有的临时对象；原历史和恢复材料保持，凭据/原始响应不输出。

## 完成条件及依赖

只有原34次终态、完整领域/有效数据/来源质量、原前后PG只读证明、完整物理请求计数、
原前驱封存和恢复均满足，才导出原四个安全证据文件，并以固定新版validator校验。
零写入、HTTP200、登录成功或离线测试均不单独计分。失败不能制造VERIFIED产物或升级readiness。
原四产物名由执行器固定：attempt-audit、trends-snapshot、database-zero-write-proof、
xhs-trends-readonly-verified；仅真实原件可进入canonical路径。私有store/raw内容不打包公开。

当前Readiness32/37。成功后才按实际依赖继续Item33；若本次在Sep17完成，其新fresh managed
周期最早Sep18 UTC，还须原internal rollback及实际V5 unit/overlay/DML capture绑定满足。
Item36仅按已批准原VPC双区Standard公网ALB+双EIP并在33及必要前置满足时核价创建；37/38继续原链。
原微信5ce已完成/清尾/删除调度，不重建。Item34 VERIFIED、35 NOT_REQUIRED保持。
高德正式启用、a474原业务及德厨报告恢复复用；支付宝/封面生成继续延期。

本次一次性调度完成、失窗或遇不可恢复阻断后删除或暂停自身；不创建后续自动重试。
只在完成、失败、实际阻断或需要本人正常登录/安全验证时合并通知；不发布无变化状态消息。
