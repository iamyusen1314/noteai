# Item31 微信 Native 原单终态证据 — 2026-09-16

原 Sep15 微信交易的支付、自然重复回调、全额原路退款和 Sep15 账单已完成。
本次仅组装既有真实证据；没有新订单、支付、退款、回调、账单请求或数据库写入。
私有候选首次运行现有 `validate_item31_payment_evidence` 返回 `errors=[]`，
代码独立复核无阻断；五份 JSON 按已验证原字节落入现有 evidence 目录。
Item31 的完成不代表 Item32、33、36、37、38 已完成，也不自动开放公众收款。
支付宝仍为 DEFERRED/DISABLED；Item34 generation2 与 Item35 NOT_REQUIRED 不变。

## 原链与计数语义

- 实收本金 1200 分，原路退款 1200 分，净本金 0。新增供应商费用 **UNKNOWN**；
  净本金为 0 不代表费用为 0。原账单为 4 行、`matched`、差异 0。
- 5 次应用级操作分别为 create、query-payment、submit-refund、query-refund、
  reconcile-bill 各一次；这不是 HTTP 次数，入站回调投递另计。
- 自动重试 0；原五项结果均已知。退款提交曾为已接受的 pending，原退款查询随后确认
  succeeded/refunded/reversed；不是把缺失字段默认成 `outcome_unknown_count=0`。
- 首次签名验证后的自然回调处理成功、ACK503；供应商自然重复投递处理成功、ACK200。
  同一事件与语义身份，保留第一份完整 payload/signature-input 配对；没有回放回调。
- `cash2` 是收款 +1200 和退款 -1200 两行；`entitlement2` 是授予 +30000 和撤销
  -30000 两行，单位为 millicredits（30 积分），不是 30000 用户积分。
  原首次 grant 为 1，duplicate callback 为 1，duplicate grant 为 0。
- 数据库支付状态真实拼写为 `succeeded`，沿既有 schema 兼容它和旧 `paid`。
  refund 的 evidence 值 `refunded` 是既有终态归一化：原签名查询 `refund_status=succeeded`、
  `order_refund_status=refunded` 和实际 1200/1200 账务及账单共同支持，不冒称上游原始字段拼写。
- canonical `observed_at=2026-09-16T13:44:11.681671+00:00` 是本次材料组装观察时刻；
  原链结束于 `13:19:16.463166+00:00`。这些时间不表示跨日持续捕获。

## 两份独立捕获与来源清单

| 原捕获 | 原 journal SHA256 | 真实提交行变更 |
|---|---|---|
| trade | `b5599c09ac1840b814abedd4cd9737d8bad29b9392a5656e51463f8446ceae93` | 8 表、29 次 |
| Sep15 bill | `63d9b3ccf6f52a4e754b522e8895163dbcaa4e513502c183ac0c085129fc9b90` | `payment_reconciliation_runs:1` |

trade 分表计数：`credit_transactions:2`、`credits:2`、`payment_cash_ledger:2`、
`payment_credit_positions:2`、`payment_entitlement_ledger:2`、`payment_events:9`、
`payment_orders:6`、`payment_refunds:4`。加上 bill 后合计 9 表、30 次提交行变更，
不是 30 个不同对象、请求或订单。两次原 collector 均完成其事务绑定、闭合、行身份及允许范围检查；
`out_of_contract_row_mutations=0` 来自这两份原范围证明，不是新增全库审计。

来源清单明确 `write_ledger_readback_kind=MULTI_CAPTURE_MANIFEST`，分别保留两个原摘要和计数。
清单 SHA `a5fc8fdb52f36ca2071da59abf9d6125dfba2b25cbac18a0684348f36a5546a3`
是该 JSON 的真实 canonical 文件摘要，**不是任何原捕获摘要**。没有合并 journal 或制造新捕获。
校验器验证文件摘要、阶段顺序、身份、原摘要不同、正整数/允许表及合计，保留旧单捕获分支。

## 商户能力与时间边界

官方首次批准日期未知，`approved_at=null`。采用
`AUTHENTICATED_LIVE_CAPABILITIES`，将四项能力分别绑定同一原链的 create response、
已验签 callback payload、refund response、reconciliation readback 摘要。
这不是新增批准函、内部签署或供应商审批结论。

真实配置身份只读于 `2026-09-16T13:41:30.818160+00:00`：原配置和原交易 App 绑定均匹配，
merchant/App 仅保留非 Secret 身份摘要。`verified_at` 使用该实际读回时刻，位于原链结束后、
canonical 观察前；没有倒填历史批准日期。原只读结果的无 Secret 投影以 canonical JSON 保存，
以下 SHA 属于该投影文件，不冒称原环境文件或云助手输出字节的 SHA：
`cc3ad903106ca5d766793632ad1339699e7d2bbf7fd8de5e6a309a37e4ce1c46`。
Owner 原 Native/AppID 确认与执行授权继续保留，但不替代未知的官方审批时间。

## 清理与恢复

原账单于 Sep16 13:17:29UTC 匹配；13:19:16.463166UTC 最终状态
`BILL_MATCHED_RESTORED_COLLECTOR_REMOVED`，host 原 final-readback SHA
`0902054f84a2311e5d0a28f6a9d21ee54a6f9be0339cd05a3455a53dbc1e1ef3`。
Payment inactive/dead，任务容器已移除，原 owner 撤除临时 15 triggers 及 function。
当时 API c853/image cc1da220/CID11b49de9、正确0902配置、Admin6c8及现有报告网页均保持。
唯一原任务 `noteai-5ce` 已删除，无下次触发；旧线程已交回结果并释放共享配置避让。
原失败、独立捕获和恢复记录保留，不再运行原任务或建立替代调度。

## 已落盘产物

以下路径均位于 `deploy/production/evidence/`，无 Secret 或原始供应商身份：

| 文件 | 原字节 SHA256 |
|---|---|
| `production-item31-direct-payment-chain-verified.json` | `98ee14a80fd9faeacb765d5e557214c73176800aa061577d870ab49b00aa2787` |
| `wechatpay_direct-canary-audit.json` | `4c71bdef0ba87ae7d211821c96b436c944509725f519e1fdb1e45e559336e24b` |
| `wechatpay_direct-merchant-approval.json` | `150061155097c22faa5d825a92d6960b428b7d84c2366ead3dec90da034c3284` |
| `wechatpay_direct-original-configuration-identity-20260916.json` | `cc3ad903106ca5d766793632ad1339699e7d2bbf7fd8de5e6a309a37e4ce1c46` |
| `wechatpay_direct-write-capture-manifest-20260916.json` | `a5fc8fdb52f36ca2071da59abf9d6125dfba2b25cbac18a0684348f36a5546a3` |

## 私有来源索引

下列十份原文件保留在 `/Users/openclaw/.codex/tmp/noteai-native-identity-9d62f98/`。
表中是各完整保留文件的摘要，不能替代其内部的请求、响应或捕获摘要。

| 原文件 | SHA256 |
|---|---|
| `bill5ce-final-readback.json` | `4ce86b66653ed207b2ba0881906db5b3b1b6e9853354a455f66817773191189e` |
| `bill5ce-operation-readback.json` | `2e2bbbfc273c431b1d0a5c91940258910428a667091e7fadbb2a8a2cdd1a585a` |
| `bill5ce-original-create-readback.json` | `b7299368a5e85c3195a601a710b8d5671f804af0d49755bc5a28344c0b1e3599` |
| `bill5ce-ledger-dms-expanded.txt` | `f642b103fdc9d0b45b5fe0fc9f271405fcea6de5ba284f609406c309c967c657` |
| `paid-order-dms.txt` | `9ad412d5e2d4f8f6a23e67bd1f63f61947269b557aa89b5ccc23b09ebc24c052` |
| `refund-order-dms.txt` | `1c63cd0fa0a0d3dc339557e8cf38d498a78d702bb678b9140150f1056bbdc2ae` |
| `paid-callback-readback.json` | `375376ca6587604d29e4930af53ddc28262ec184eb8c4cc114363cbfcdfd84c7` |
| `operators-final.json` | `f0f3b9b434703cba4341eebf758ff37cb5547510b56a70c65039e15983a242c2` |
| `paid-capture-closed.json` | `118a930a7a286c20438d54bee81187a35e81ab65fc1200b4474f61b8931814d1` |
| `paid-final-runtime-result.txt` | `3135bfa1eb52227a1bfe01287e63b44381b4c2fe603bb83bae3535180d152901` |

原 host 索引：`/var/lib/noteai/native-9d62f98/trade-web2dfd4d2` 和
`/var/lib/noteai/native-9d62f98/bill-20260915`，各自原 work/journal、operator、close/final-readback 独立保留。
私有组装目录：`/Users/openclaw/.codex/tmp/noteai-item31-terminal-assembly-20260916/`；
其 `SOURCES_AND_GAPS.md` 是组装前字段映射历史，旧 UNKNOWN/null 草稿由已验证 candidate 取代。
没有将私有原文件、用户素材或环境备份复制进 Git。

## 验证范围

原 Item31 用例及必要兼容反例共 26 项在 Python3.11、network-none、仓库只读容器通过；
独立审查确认原批准时间分支、单捕获格式、1200 分、5 应用操作、零重试、净本金零和真实 DML 要求保留。
真实 candidate 首次现有单项校验 `errors=[]`，原业务字段与组装前映射一致。
落盘后唯一一次既有 `build_report` 整体一致性检查通过：`manifest_valid=true`，
`verified=32/total=37`、`remaining=5`、`blocked=1`；公众完整发布仍未通过。
只更新 `real_payment_chain`，其他 control 保持原样，没有重新执行产品业务或全产品测试。
