# Item35 专业审核包 — 2026-09-03

状态：READY_FOR_PROFESSIONAL_REVIEW；所有专业批准均 PENDING。Readiness不计分。
基准：Item30 terminal `429b55a7bf652c8a9b4b5f47ca769ea5cba8ef29`；支付审核目标已于2026-09-04更新为微信支付直连和支付宝直连。审核对象以文末文件哈希为准，修改后需重新核对受影响结论。
审核包冻结时间：2026-09-06T20:11:37+08:00

## 已证明的技术范围

- 当前生产API为已接受b55运行态；支付callback runtime被接受时处于disabled。微信支付直连和支付宝直连是owner指定的正式生产目标；ICP备案、两家商户/产品审批、生产凭据注入和真实闭环尚未完成。这些运营审批属于Item31外部依赖，可作为本包背景材料引用，但不重复构成Item35专业批准信用。Ping++ TEST准备仅为历史记录，不构成当前provider或Item31信用。
- 数据用途、存储、外发、导出与留存字段表见数据契约。免费归档7天＋恢复7天；付费创建归档在账户存续期间无产品到期。注销主库≤24h、备份≤30天是既有产品契约；法定财务、安全和幂等记录保留期限仍需专业确定。
- 已接受对象存储证据为私有OSS、禁止公开访问、ECS RAM Role、AES256服务端加密。不得对外声称该证据证明SSE-KMS/BYOK。
- 付费方案为非自动续费30天、固定服务积分目录；Studio为单账户。V1自动退款仅支持一笔未使用权益的全额原路退款；部分退款、已使用和矛盾状态转人工处理。
- 跨境设计：中国阿里云→Render新加坡Gateway→Anthropic，仅必要文本。Gateway地区不能代表Anthropic全部处理地区。Gateway不接业务DB或付款状态；AWS DynamoDB存哈希、状态、时钟和数值usage，terminal TTL默认30天，不存正文。
- Item30证明Claude/Kimi/Amap/Meituan各一次真实技术调用成功，使用合成AI输入/公共事实，无用户内容；该证据不等于合同许可。XHS趋势/自有笔记流程使用现有非官方接口和登录session，尚未形成专业许可结论。
- 当前法律接口仍为`product_contract_implemented_legal_review_pending`。在批准和必要修订完成前不得改为已批准或向用户宣称审查完成。

## 需专业人员逐项填写的结论

| 审核项 | 需回答的具体问题 | 当前结论 |
|---|---|---|
| 隐私 | 确认运营主体、联系渠道、必要/可选数据、目的、第三方、用户权利办理方式；批准或修订字段地图与留存/删除承诺；明确注销后财务、安全、幂等记录各自保留期限。 | PENDING |
| 服务条款 | 批准或修订收费、30天权益、AI输出使用与限制、账户停用/终止、争议处理与责任文字；填正式主体、联系渠道、版本及生效日；确认已有用户是否需重新同意。 | PENDING |
| 退款 | 律师确认自动退款条件、人工例外、申请渠道、处理时限及拒绝理由；微信支付与支付宝的直连商户产品准入、异步通知、原路退款及账单对账能力由Item31真实闭环单独验收。 | PENDING |
| 跨境数据流 | 逐一确认Render、AWS DynamoDB、Anthropic等境外接收方、地区、字段、目的、留存、转委托、用户告知/单独同意与适用传输机制；不能只审核新加坡Gateway。 | PENDING |
| Provider | 对Claude、Kimi、Amap、Meituan分别确认商用SaaS、输入数据、展示/缓存/保留限制；对XHS明确非官方接口、session、自有笔记和趋势访问的许可/规则风险结论。微信支付与支付宝商户/产品准入归Item31。 | PENDING |

技术问题由CTO处理；以上法律或provider许可结论须由有实际专业身份/权限的人给出。

## 签署记录（每类填写一份，可引用真实签章文件）

以下两类结论必须由对应专业或授权主体分别作出，并形成两份独立签署材料，不以一份笼统签字互相替代：

| 必需签署类别 | 最低覆盖范围 | 当前状态 |
|---|---|---|
| 法律/隐私专业审核 | 隐私、服务条款、退款文字、跨境数据流及适用留存期限 | PENDING |
| AI、地图、本地生活及XHS provider结论 | 各provider商用范围、数据用途/留存以及XHS非官方接口和session风险 | PENDING |

微信支付和支付宝两份商户/产品授权仍是Item31不可缺少的真实外部材料；本表不重复把它们作为Item35签署类别计分。

- 审核类别：待填
- 审核文件版本及SHA-256：待填
- 签署人、机构及专业/授权身份：待填
- 签署日期：待填
- 结论（批准/附条件批准/拒绝）：待填
- 适用范围与条件：待填
- 条件关闭材料和日期：待填
- 原始签署材料路径：待填

本包没有发送给任何外部人员，也没有代签。真实签署文件应另存为Evidence引用；不得填Secret、客户订单或登录资料。Item35仅在全部相关批准、文字修订及条件关闭后才可terminal。

## 审核文件冻结清单

| 文件 | SHA-256 |
|---|---|
| `NoteAI_Pro_Demo_Framer.html` | `341f0eb030791c706dde94ec46680c9e70c0211f27002cb25924e88e2ffae06e` |
| `docs/FIRST_LAUNCH_DATA_AND_SECURITY_CONTRACT.md` | `ba62f943c9bb24e7a11527caf87284f3fc89aed67e01ea3c7abc23415f273277` |
| `docs/FIRST_LAUNCH_UI_ADMIN_CONTRACT.md` | `02ccd4a5cf23a349704a7796fbe8b27b69dee8f1169a886743003bcde2369c15` |
| `docs/PAYMENT_PRODUCTION_CONTRACT.md` | `25638628d236970484a4a9d49e8f5bcff444b70e615dbd075baf22eba650e7fc` |
| `docs/CLAUDE_GATEWAY.md` | `c8ff40ee79d085d0bed6f738301ca3b11f013656c80f7a5fcf16c726a0552580` |
| `docs/XHS_TRENDS_PRODUCTION_CONTRACT.md` | `11d6415c200afddbcbc604cba6e8f34fba2c04f16aa5ea436f851c221d998eb0` |
| `docs/XHS_TRACKING_PRODUCTION_CONTRACT.md` | `da31ca00b1f7b47acf7e1e2081f9b88cde95ce26019e3ab3ed55da6dc7563e7a` |
| `docs/PRIVATE_STORAGE_AND_RECOVERY_CONTRACT.md` | `8f1a21cacdb76a0755b927ecd249f4288058e0d5dc0b42c7a443431af85bf3df` |
| `deploy/production/evidence/production-private-storage-runtime-verified-20260729.json` | `28e4647b07c998154c8caa9767b7b3f709a4cc93e31f1e0b73ca1b40000ecbc7` |
| `deploy/production/evidence/production-real-ai-provider-chain-verified-20260824.json` | `6b8fdf9fd574e757e71cc0313d3b5f9c04c9a424836486dc9fe1c964dfea423a` |
