# NoteAI 小红书封面功能交接 — noteai-xhs-cover-20261019

交出日期：2026-10-19（北京时间）。状态：交接和独立工作区已准备；封面产品代码、付费评测、生产发布均未执行。本文是此任务唯一交接入口；配套 `NOTEAI_XHS_COVER_20261019_BASELINE.json` 记录可机器核验的基线和证据摘要。

## 1. 归属、范围与授权

- 新窗口“NoteAI 小红书封面功能”：独立开发、定向验证、形成可集成的功能交付；本窗口不并行开发封面。
- 本窗口“修复高德检索与休闲娱乐行业”（thread `01a13080-d8a9-7c50-88c0-09ffcebbef61`）：基线答疑、后续统一集成发布。生产切换保持唯一执行者，不由封面窗口自行部署。
- 既有“启动NoteAI授权续期发布”窗口（`01a0f7cb-70cc-71d3-bd42-2cc75bdae2d3`）大版本保留原状态，最近实际ACK仍暂停生产；没有因此恢复其部署、迁移或纳入其候选。
- 本窗口此次只准备工作区和文档。用户本次第6项明确新窗口负责开发、定向验证和功能交付；这一分工不等于批准所有建议、立即生产部署、新权限、新资源或新的付费测试预算。旧修复150元预算不是封面预算；已记录累计114.234888元、余额35.765112元独立保留，不挪用、不重置。
- 不重审全项目、不重跑未受影响的高德、美团、微信支付、历史九图或大版本迁移；不得重放旧T0/RunCommand/付款/UNKNOWN请求。不改旧修复、主目录或大版本工作树。

## 2. 决策状态：哪些已确认，哪些只是建议

讨论依据依次为：①用户原始六点需求；②本窗口首轮方案；③用户粘贴Astra建议并询问意见；④本窗口评议并修正原方案。用户尚未逐项批准③④的实现默认值。本次第6项指定新窗口接续开发职责，不把这些建议自动升级为产品批准；仅针对未决定的实质产品选择形成具体合同，不重问已确认目标。

用户原始需求原文要点：在报告“视觉专家”栏目增加“一键生成笔记封面”；“根据视觉专家建议优选用户上传的图片”；“结合笔记标题以及可选标题、专家建议，优选图片”等；“选用用seedream最新模型”；统计成本积分；最小版本改动；前端与后台同步；“先……讨论方案，我确定后再执行”。不要再让用户重述这些已确认目标。

| 项目 | 用户已确认 | Codex/Astra建议（不是批准） | 尚未决定 |
| --- | --- | --- | --- |
| 入口 | 报告输出后，在视觉专家栏提供封面功能 | 诊断/生成报告共用入口；最终标题旁可有同一入口 | 是否同时覆盖两类报告；是否加第二入口 |
| 选图 | 依据视觉专家建议，优选本人上传图片 | 联合考虑主题、清晰度、裁切、主体、文字空间；设计必须能看图片；用户可换图 | 选图算法与模型调用边界 |
| 标题和排版 | 综合正式标题、备选标题和专家建议 | 封面文案与发布标题配合，可少字/无字；结构化方案含图片ID、裁切、文字/字号/位置、字体、保留事实与制作路径 | 默认风格、轻操作数量、是否允许用户自改文案 |
| Seedream | 使用最新Seedream作为图片生成模型方向 | 本地生活实拍优先，按需要调用Seedream；不能改造真实门店/菜品/人物；拼图不冒充连续空间 | 是否接受某些封面仅实拍排版、不调用Seedream；不得悄悄用此建议取消用户模型要求 |
| 模型/尺寸 | 尚未确认具体变体和尺寸 | 5.0 Pro作质量基准；比较实拍排版/Flash/Pro，默认一张3:4竖图；2K是初始建议 | 最终变体、固定版本ID、分辨率、账号实际开通情况 |
| 设计/质检 | 尚未确认具体Agent架构 | 现后端固定流程：设计→制作→看成品质检→有限修正；不接Managed Agents或多Agent平台 | 设计/QC具体模型、调用数、单任务费用硬上限、是否允许一次付费重绘 |
| 字体/分层 | 尚未决定 | 系统准确排字，保存底图、独立文字/装饰及版式参数；模型直接出字仅对照评测；不默认先生成再付费拆图层 | 最终出字路径、字体授权与范围 |
| 报价/扣分 | 用户已确认通用原则：先完成交付，再最终结算；需统计封面成本与扣分 | 封面独立报价、预留→可用成品保存→唯一扣分；点击直接启动；重开/下载不收费 | 每张积分数、制作路径是否同价、免费修改范围；不存在已批准“4积分”等价格 |
| 保存 | 需要形成可交付封面 | 原图组合/底图、版式、最终图片同期限；建议90天，素材到期允许补传 | 保存期、删除/到期告知政策；90天未获批准 |
| 修改/重生成 | 尚未确认细则 | 改字、断行、移位等不调用模型的导出可免费；主动重新设计另报价；失败不覆盖上一张成功封面 | 换主图/换排版是否算新任务及计价边界 |
| 效果反馈 | 尚未确认指标/评测规模 | 先少量筛路线，再约30组调试/独立盲评；记录采用、下载、修改、重生成、耗时及合格交付成本 | 首批素材权利、独立评审、费用预算；不保证点击率提升 |

建议首版闭环：报告/本人素材→联合选图与设计→程序制作或Seedream→程序检查+视觉质检→至多一次针对性修正→私有保存→一次结算→报告内重开/下载。内部一套主设计，必要时两套低成本排版择优，不固定先付费生成三张。

成品检查分级：错字漏字、文字溢出、关键主体被裁掉、事实虚构、文件无效应修正/失败；一般配色或风格偏好用于择优，不做无依据严控。独立QC调用不等于独立效果验收，最终还要人工盲评。确定性排版问题不应重绘整图。

费用规则建议：明确限定设计、QC、生图、复检的调用次数和总预算；已发送结果UNKNOWN保留原请求与供应商成本状态，不能自动重发或当作零成本。可设计等待上限后释放用户预留、平台承担未明成本，但这仍需写入明确合同；不能让用户无限挂账。用户积分最终收费与供应商实际费用分别记账。

## 3. 模型资料与成本依据（文档事实，不是账号验收）

2026-10-19已读取官方文档：[图片生成API](https://www.volcengine.com/docs/82379/1541523?lang=zh)、[模型价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=zh)。

- 当前文档有Seedream 5.0 Pro/Flash；支持参考图生成、定位编辑、图层拆分。Pro/Flash单次生成单图，不支持组图/联网搜索/流式输出；前端只能展示真实阶段，不能伪造百分比。
- Pro单图输出≤261万像素0.30元、>261万像素0.60元；首张输入图免费，第2张起0.02元/张。Flash输出0.12元/张。为文档公开价，非当前账号实际报价/账单核验。
- Pro文档示例ID `doubao-seedream-5-0-pro-260628` 只是已见版本线索，实施前核实际可用版本；不能用“latest”别名悄悄变更生产模型。
- 官方图片URL有效24小时，必须及时转存。拆分图层单独计费，图像文字层不等于可编辑文字对象，首版不以此作为默认编辑方式。
- 完整成本=设计/选图+所有生图尝试+QC/复检+失败成本+存储/传输。合格交付均摊成本=全部尝试成本÷合格交付数量。不要用代码`CREDIT_VALUE=0.30`冒充每分实收，不据此承诺毛利。
- 官方有Agent基础设施不意味着已有可直接接入的完整小红书封面Agent。本任务建议沿现后端，不顺带换任务平台。素材/案例需有使用权，不抓取未授权图片充当自有训练集。

## 4. 生产组合基线及新工作区

本轮只核验本地保存的实际发布回执、独审和原发布窗口最新ACK，并核源码哈希；没有新发云命令、查生产DB或重新测健康。以下是截至本轮可核验的最新实际记录，不冒称2026-10-19新做了一次线上验收。

| 组件 | 实际版本/状态 |
| --- | --- |
| API-only | `f3e5ed18c80fd307b6bad600e722a2a88f95a1ce`；镜像`sha256:9be6daa8b84a59842b7de7d97dc25e8254b5814648356c8833a64bce87e4e141` |
| Pay/Admin/兼容bridge | `39d85f2809597ff1958a9c0c23978eecf3229e48`；Pay镜像`3f779b9f08f1726ccdfe4bdbeecfb09052e7a13b5c891f87bf72bdecd5286bbf`；Admin镜像`fbafe98f1e9e0e3c3d32c428991a40474907a285491599bd0d33029c5c023517` |
| Public | `c4a2bba919e38928a23befde06149a732af98e1a`，2026-10-18 23:50:37北京实际上线；只index/app变更，另9个regular+2个absence沿实际b0保留，不能整份发布工作树assets |
| 数据/配置 | schema31；`NOTEAI_POSTDELIVERY_SETTLEMENT=1`；同预付费4核8GB API-C；既有同EIP峰值10Mbps。未执行0032–0041，无新权重 |

当前静态指针：`/var/www/noteai-public/current` → `/var/www/noteai-public/h5-remove-global-status-c4a2bba-d56170b621247b7c1b7490c4714b9738`。不能把c4a或f3e HEAD等同整仓各组件都上线。

- **新工作区**：`/Users/openclaw/.codex/worktrees/noteai-xhs-cover-20261019/noteai`
- **分支**：`codex/noteai-xhs-cover-20261019`；任务编号同本文件。已查同目标本地分支/工作树和已列出对话，无同名开发任务；未另建或启动Codex对话，用户自行打开新窗口。Astra封面优化对话只是讨论参考。
- **源码基线**：`c4a2bba919e38928a23befde06149a732af98e1a`，来自候选检查工作树的已提交代码。c4a→f3e→b0→94b20c1→39d85f2；包含a11及后续physical计量释放、UI终态、直接启动、后结算、上传复用、诊断上下文、横幅清理等有效修复。
- 旧操作文档工作树`amap-leisure-repair-20261012/noteai` HEAD `043559b95f5fc624e5f6454533294096d5a274c1`不是完整产品代码基线；与c4a共同祖先仅88e1b11，不能从该文档HEAD另做功能。
- **必要产品补丁清单：空。** 上述有效修复已在c4a祖先内，不重复cherry-pick。四关键API文件与正式回执哈希相同，详见BASELINE.json。39→f3e的model差分仅api.py；f3e→c4a仅原HTML及相关测试。
- W2仅有未提交`.codex/handoffs/current-task.md`，没有复制。新工作区初始干净，无`.env`、`model/.env`、`.venv`、`node_modules`；未复制生产密钥、配置、连接串或用户数据。保留仓库原有`.env.example`模板。此次只增加交接文档与新工作区的CURRENT指针。

## 5. 精简模块索引（行号以c4a基线为准，改后按函数名定位）

路径相对新工作区；这是接点索引，不是要求重构全部模块。

| 模块 | 文件/函数或基线行号 | 封面需要注意 |
| --- | --- | --- |
| 上传/身份 | `model/api.py:19571 upload_image`，19573 `get_current_user`，19587流式临时上传 | 单文件10MB、格式/尺寸校验；规范化JPEG，非原文件逐字保留。沿现鉴权，不跨用户取图 |
| 原图权限/到期 | `model/private_storage.py:35 MEDIA_TTL_SECONDS`；1087 `store_media_bytes`；1207 `lock_ready_media_refs`；1287 `load_media_bytes` | 默认24h，到期拒读；现临时媒体TTL上限30天，不可直接承诺90天成品。本人subject hash/用途/状态必须保留 |
| 素材引用 | 同文件1238 `link_media_refs_in_transaction`、1254 `media_refs_for_operation` | durable基础有附件关联，不等于当前普通报告已保存九图。新任务选中/参考原图需明确关联及生命周期 |
| 诊断原输入 | `model/api.py:17768 original_input`、17770 `cover_media_ref`/17771 `video_media_ref` | 可有单封面UUID，没有完整额外图片列表。报告保存不会延长素材TTL |
| 诊断保存/重开 | `api.py:17697 _persist_postdelivery_diagnosis`；15872 `get_diagnosis`；2799 `_INPUT_DIAGNOSTICS_SCHEMA`及`_PERSISTED_DIAGNOSIS_SCHEMAS`；3032 `_sanitize_persisted_diagnosis` | 保存和GET均再次白名单清洗。现仅允许原封面/视频ref、观察、意见等；新成品附件/版式/整组图片字段不会凭写入JSON自动返回，必须明确扩展公共契约 |
| 生成结果/重开 | `api.py:6600 GenerateResponse`；15904 `_generation_report_result`；15934 `_saved_generation_reports`；16076/16088 reports | **现有生成报告没有保存整组`cover_images`引用。** 重开仅投影公共白名单，不暴露prepared输入/messages；新字段须入schema/响应及重开投影或用独立本人附件接口，不可放宽为任意JSON透传 |
| 报告身份/保存 | `api.py:19831`→`model/task_clarification.py:398 save_result`（433笔记/444身份/446结算/448任务result） | 以本人`report_type+report_id`关联，不能按同名品牌/标题猜报告；旧报告缺图允许补传，不依观察文字还原照片 |
| 视觉建议/前端 | 原`NoteAI_Pro_Demo_Framer.html:8238 populateGenerateReport`，8396视觉分析师；8492 `renderAgentResults`诊断视觉专家 | 共用一个封面业务入口，绑定当前报告及标题。保留c4a横幅清理和既有UI；生成/诊断原链不重跑 |
| 模型/供应商 | `model/ark_media.py:141 chat`/310；`model/model_runtime_config.py:16 TASKS/20 MODELS/106 resolve`；`public_product.py:684 _reserve_payload`/740 | Ark现为图→文，不是产图。当前resolver未知task会落semantic，provider映射会把未识别型号落Kimi；Seedream需明确图像路由、供应商、版本，不仅添加下拉项 |
| 排队/取消 | `model/public_product.py:155/182 model_admission`、209 `media_worker_slot`、255 `queue_status`、272 `request_cancel`；`model/model_admission.py:101 FairQueue/312 Admission` | 复用公平准入但核图片供应商额度；保护原报告容量。当前生产operation10/每用户1/物理2/视觉2/Claude30RPM/pending64/queue1800/noProgress300不是Seedream容量证明 |
| 幂等/后台任务 | `api.py:967 _paid_request_claim`、870 `_timed_sse_stream`；22778 `_submit_durable_ai_job`；`model/ai_operations.py:22/43`及PG0007 CHECK | 普通SSE链与durable入口分清。`model/idempotency.py:130 admit_operation`尚未连API，不能只见模块就宣称已可靠后台执行。durable类型仅analyze/generate/chat_rewrite，provider仅Claude/Kimi，选用时须兼容扩展 |
| 预留/交付后结算 | `model/postdelivery.py:105 reserve_claim`、200 `_assert_saved`、216 `finalize_in_transaction`；`model/billing.py:671 get_operation_quote` | 后扣现只认generate/analyze且校notes/diagnosis。**cover_generate应独立操作、报价、成品合同，不能冒用原8分生成或6分诊断。** 供应商URL不是NoteAI已保存成品 |
| 成本计量 | `model/billing.py:1196 record_model_usage`、1329；`model/db.py:980 model_usage_records` | 现以token/cache/audio计价；手填费用是manual不是exact。须记录输入/成功/计费张数、像素档、单价币种/版本、未知状态和整单成本，不清理旧UNKNOWN |
| 后台配置/成本 | `model/admin_server.py:980/988 admin_model_config`，294/306 `_model_cost_audit_*`，1242 `admin_usage_stats`；`model/admin.html:1768 loadModelConfig` | 可复用草稿/发布/恢复revision框架；补图片功能开关、模型/尺寸/报价/调用预算/状态和按张费用显示，保持原文本配置兼容 |

## 6. 可复用证据与定向补测

证据根目录E：`/Users/openclaw/.codex/tmp/noteai-amap-leisure-real-20261012/`。以下原件本轮核存在及SHA，详细bytes/SHA在BASELINE.json；引用是事实留存，不是可重放指令。

| 原件（相对E） | 版本/范围及复用边界 |
| --- | --- |
| `formal-postlive-f3e-nine-generate-actual1/FINAL-DELIVERY-RECEIPT.json` | 正式f3e/9be；PC真实九图、30真实调用、保存重开、完成后唯一8分。证明原报告和结算，不证明封面 |
| `public-remove-global-status-c4a2bba-20261018-r1/ACTUAL-UI-DELIVERY-RESULT.json` | c4a实际23:50:37上线、仅index/app、API不变；PC/390×844 H5浏览器，H5是尺寸模拟 |
| 同目录`INDEPENDENT-ACTUAL-STATIC-PUBLICATION-REVIEW.json` | 实际C/T、13位置manifest、9regular/2absence、API恒等及恢复绑定 |
| `source20-f3e-actual85-H5-nine-diagnosis1/ROOT-REAL-RESULT-CHECKPOINT.json` | 隔离真实PG、f3e/9be、37真实调用、H5九图诊断/澄清续行/保存重开/唯一6分；非新真机；辅助文本/评分限制保留 |
| `incident-a11-nine-3of9-20261017-1422/pg-local1/FINAL-LOCAL-PG-EVIDENCE.json`及`actual-run3/tests.txt` | 已有真实PG5/5：注入22012、usage/terminal ACK未知去重、10×9数据库并发计量、mixed6/4唯一退原来源；9a29祖先修复沿用，非39/f3e完整后结算或真实供应商容量。注入SQLSTATE不是原线上SQLSTATE；PG临时cluster已清理，不为接管重建 |
| `postdelivery-reservation-pg-local1/actual-run4/receipt.json`及`tests.txt` | 真实PG后结算9项，含成品/扣分同事务、并发claim、UNKNOWN保留；pre39源码的postdelivery/idempotency与39/f3e相同，API整文件不同，仅作核心兼容证据，不冒最终整包同版本验收 |
| `ten-user-current-f3e-simulation-20261018-r1/SUMMARY.json` | 40项离线测试与10独立合成用户×九图全链，取消/502/UNKNOWN/唯一扣分；0外连，不是十真人供应商容量或封面压测 |
| `incident-f3e-sixofnine-20261018-141213/INCIDENT-AND-ACCEPTANCE-RESULT.json` | 同EIP1→10读回；新手机任务33真实调用完整交付/保存/扣8，11分23.95秒；旧2条WriteTimeout UNKNOWN不重放 |
| `public-b0-banner-removal-baseline-compare-local1/FINAL-COMPARISON.json` | f3e/c4a相关2+27 PASS；完整VM两版同52PASS/17FAIL（旧style夹具），不能称全suite通过或为此重审产品 |
| `public-remove-global-status-c4a2bba-20261018-r1/PUBLISHER-FINAL-BASELINE-ACK.json` | 原大版本窗口已核原件/ACK c4a、API/EIP并保留暂停；candidate_integrated=false，不等于大版本已集成 |

复用测试入口：`tests/test_report_history.py`、`test_private_storage_postgres.py`/`test_private_storage_recovery.py`、`test_postdelivery_reservation.py`/`test_postdelivery_api.py`/`test_postdelivery_postgres.py`、`test_model_admission.py`/`test_generation_multiuser_admission.py`、`test_billing_token_cost.py`、`frontend_billing_consistency.test.js`。不要全量重跑；根据实际改动新增/补跑封面case。

封面必补：同账号重复点击/刷新/跨端重开；跨用户越权；旧报告无图/过期补图；新报告整组refs和新字段重开保留；标题准确/裁切/缩略图/主体及事实；模型失败、明确失败与UNKNOWN分开；取消/排队/名额释放/与原报告公平隔离；成品落库失败/提交ACK未知/唯一结算；按张价格与Admin；PC/H5下载保存。真实供应商、模型质量、PG事务、浏览器与真机证据分别记录。未有新增费用授权前只做无付费开发/测试设计。

原计量异常具体SQLSTATE未留存；不补造死锁等结论。历史UNKNOWN、未明费用、原模型记录永久独立保留，不清零、不自动补发。它们不是无依据阻断封面离线开发的新前置；若封面修改命中同一缺陷才做针对性处理。训练/评分专项、新权重、旧性能优化不混入。

## 7. 下一步、真实缺口及发布/恢复

1. 接收方在本文件末尾登记接收时间/窗口/HEAD和首个任务；先读此文和BASELINE.json，不重查整个历史。
2. 沿用户已确认方向梳理最小接口/存储/费用合同；把未决定项集中成一次具体建议，避免重问已确定业务目标。实拍/Seedream策略等建议未批准，不暗中替用户作决定。
3. 新窗口按已确认范围在新分支开展隔离开发与定向测试；涉及表内未决定的实质产品选择，先明确合同，不能借本地开发将建议固化为用户批准。实施需明确原图关联/到期、白名单、独立cover类型/供应商/按张成本；若需要schema增量，提出只覆盖封面的兼容方案，不执行0032–0041或扩展成大版本。
4. 真实模型评测前：核安全配置通道、Seedream账号权限/可用型号/实际价格、素材权利和新预算。现均没有本功能验收证据；旧150元余额不能代替。约30组盲评是建议，先有限样本筛路线再定范围。
5. 交付给主窗口：产品提交/迁移差分、模型/Prompt版本、定向测试及明确未执行项、实测成本/报价、保存/恢复合同。主窗口统一集成、重新核当前生产和在途任务后才安排发布；本次不是立即上线批准。

恢复注意：当前静态的既有恢复仅c4a指针→`/var/www/noteai-public/h5-postdelivery-b0fbae3-2d2314f29215ac17b6be8d9beb40c316`，不是更老public88。当前已存在reservation_v1历史，不可直接回BE8/a11。API兼容恢复既有previous39/flag0方案须按当时在途/账本核对后由主窗口执行；不覆盖DB、不删除新报告/积分流水。未来封面应具备关闭新提交但保留在途结算/旧成品读取的恢复方式，不把失败变成自动大版本升级。EIP10和实际静态继承资产不得被旧部署配置覆盖。不得执行本文所引历史dispatch包。

独立已知事项：账号页曾观测growth服务端等待14.60秒，根因分段尚未完成；十人真实容量、新视频及专项评分校准不能冒已验收。均不因此重开其工程范围或扩建测试设施。

## 8. 同一文件接口问答与接收记录

唯一交换路径为本文件的绝对路径：`/Users/openclaw/.codex/worktrees/noteai-xhs-cover-20261019/noteai/docs/NOTEAI_XHS_COVER_20261019_HANDOFF.md`。不要在两个工作树分别维护互相冲突的交接副本。新窗口在本节追加`Q编号/接口/问题/期望答复`；主窗口答疑时在对应条目写`A/源码依据/决定状态`，不需要用户逐项转述。修改前先读当前文件，按段追加，避免覆盖对方更新。只新增明确接口约定，不把问答自动当成部署/费用批准。

- 接收状态：已接收。2026-10-19 23:31 北京时间，本封面窗口接管 `noteai-xhs-cover-20261019`；实际分支 `codex/noteai-xhs-cover-20261019`，HEAD `cc96df72e03a914f2fa595f4d1ec71b03e2d175d`。初始工作区干净，c4a2bba 与交接提交均为 HEAD 祖先；未回退、未新建工作树、未复制环境/密钥。
- Q/A：暂无。


### 本任务权威清单与恢复 checkpoint（接收）

此处延续原任务，清单/checkpoint 不另建副本。主窗口统一集成发布。

| 阶段/目标 | 负责人 | 状态/提交 | 有效证据 | 阻塞/下一步 |
| --- | --- | --- | --- | --- |
| 1 接管基线与确认范围 | 封面主代理 | 基线COMPLETE；产品选择WAITING_USER / cc96df7→94e78f7 | HEAD/branch/ancestor及原窗口A01–A03；官方型号/尺寸/价格依据见最新checkpoint | 已集中提问；未经确认的模型/尺寸/积分/期限不启用 |
| 2 最小实现与离线验证 | 封面主代理；素材/策略子代理DONE | 基础补丁COMPLETE，完整功能PENDING / 94e78f7 | 素材链与策略合同83项关联测试PASS；本地SQLite+私有内存对象；源码独审通过 | 继续任务执行/成品存储/后结算/UI，依已发产品选择收敛；不冒称已实现 |
| 3 定向集成与授权真实验收 | 封面主代理 | PENDING | 旧报告证据按第6节复用；新增仅素材/策略受控集成，非真实封面 | 新预算未授权，账号条件UNKNOWN；PG/PC/H5/真实成品均待执行 |
| 4 独立审查与交付 | 独立审查子代理DONE(基础)；主代理集成 | 基础独审COMPLETE；最终功能交付PENDING / 94e78f7 | 发现同源proxy缺口、旧诊断过滤丢附件，均修复；基础diff无未结P0/P1/P2 | 原窗口接收阶段提交；完整任务/真实验收后另做最终diff独审，不部署 |

- 当前分支/HEAD：`codex/noteai-xhs-cover-20261019` / `cc96df72e03a914f2fa595f4d1ec71b03e2d175d`。
- 已完成：接收、基线关系、归属与授权边界核对。复用基线修复，无需重复cherry-pick。
- 未完成：原图关联、独立任务/报价/保存/结算、PC/H5入口与重开下载、定向验证和独审。
- 运行中供应商/生产请求：无；新增付费模型调用0、生产动作0、历史UNKNOWN原样保留。
- 决策待集中确认：报告种类范围、固定Seedream型号/尺寸、设计与QC调用上限、文字绘制及调整、积分/保存期、新样本预算。
- 恢复入口：先读本节最新checkpoint及Q/A，核本分支git status/HEAD，延续未完成项；不执行历史dispatch。
- 首个实现任务：核对并补齐报告可追溯的本人整组原图引用与读取白名单；不重跑报告、不改变当前素材TTL。

### 接口问答（等待原窗口答复，不视为用户批准）

- **Q01 / schema31增量纳入**：`scripts/render_predeploy.py`调用`db.apply_postgres_migrations()`遍历全部SQL；不能为封面执行0032–0041。建议封面增量独立交付并由主窗口纳入既有schema31发布包，不新增发布程序。请确认最终集成入口/命名，或指出已有安全接点。阻塞：未来封面job/按张成本表真实PG与发布，不阻塞纯合同/原图引用开发。A01（原窗口，2026-10-19，北京时间；接口约定，非迁移执行许可）：当前没有可直接指定单文件/目标版本的安全入口。c4a `scripts/render_predeploy.py:19–33`无目标参数，26行全量迁移后还更新Prompt baseline；`model/db.py:2969–3057`遍历全部SQL，并要求每份已应用迁移在本地存在且SHA匹配。当前本分支目录止0031，但不把这一事实当成未来不会混入0032–0041的保证。
  - 交付命名先约定为 `model/migrations/features/noteai_xhs_cover_20261019_0001.sql`（独立候选交付物，不放现全量postgres扫描目录，不抢占0032–0041或伪称schema0042；该文件尚未创建/批准执行）。如无DDL需求则不必新增。提交需附SQL/SHA、依赖/兼容和定向PG验证。主窗口拥有最终集成执行接线，不要求封面窗口另建发布程序。
  - 主窗口正式集成时负责最薄的精确待执行集合校验/既有advisory锁/事务/校验和复用，仅封面增量，不附带Prompt基线写入；现尚无可运行的专用入口，不能说已接好。只放单封面SQL目录再调用原migrator也不可行，会因缺既有31原件失败。若内部复用原migrator，须受控清单带齐原31文件+唯一封面文件且断言待执行恰该一份。
  - schema31是当前生产起点，封面DDL若正式执行后应如实记录“31+feature增量”，不能假称仍完全未改。后续大版本须保留同一迁移身份/原件/SHA或作显式兼容接续，不能删除历史、重编号或重复执行。恢复不覆盖DB，优先关封面新提交并保留已交付及在途结算。
- **Q02 / 图片账号只读证据与安全配置**：当前worktree无环境/密钥，现`ark_media`仅看图。请提供既有控制台已开通Seedream型号/有效价格/配额的脱敏事实及现有安全配置通道；没有证据则保持UNKNOWN，无需开通、购买、创建新密钥或付费测试。建议固定Pro `doubao-seedream-5-0-pro-260628`，尺寸与产品方案待用户决定。阻塞：真实供应商验收/启用，不阻塞离线adapter合同。A02（原窗口，2026-10-19，北京时间；账号证据仍UNKNOWN）：没有已核验的Seedream账号开通、有效型号、账号生效价格、RPM/IPM或免费余额证据，也没有可交给你当作已验收的Seedream调用记录。现有真实调用仅证明Ark看图型号 `doubao-seed-2-0-lite-260428` 的既有链可用，不证明同Key/项目已具备Seedream权限；公开价格表不等于该账号实际价格。Pro `doubao-seedream-5-0-pro-260628`仍仅官方示例线索，不能写成账号已开通。
  - 现源码安全配置接点为 `model/ark_media.py:39 configured`及`:113 _headers`读取服务端变量 `NOTEAI_ARK_API_KEY`，现base为官方Ark `/api/v3`（文件顶部）。只给变量名/通道，不提供值、环境文件或完整连接串。原管理核验通道是主窗口现有阿里云官方管理会话、成熟主机只读执行/脱敏回执，模型开通/配额应在原火山方舟账号控制台核；本次未为答疑登录探测/开通/购买/调额/建Key。
  - 后续若有已授权真实评测，主窗口通过原受控配置渠道供给隔离运行实例，只交换型号/权限结果/报价版本/额度/脱敏绑定摘要；不将生产env或Key复制到此worktree，不自动假设复用既有Key有权访问新模型。暂保持图片adapter不启用；离线合同/替身测试可继续，真实验收及启用依赖账号证据和另行预算。
- **Q03 / 报告素材契约增量**：拟增加严格UUID白名单`source_media_refs`保存原输入引用，生成兼容最多9张，诊断兼容cover+9extra（最多10）；另用`cover_source_media_refs`保存本人补传候选，不改原图事实/观察、不延长TTL。只扩展原报告保存/重开和本人素材读取补传接口；旧无图报告明确需补传。请告知原窗口是否有同文件在途变更或已有等效接点。阻塞：无，按本窗口源码拥有权开发；最终由主窗口合并。A03（原窗口，2026-10-19，北京时间；同意作为最小兼容接口方向）：本窗口无 `model/api.py`、原HTML、`model/db.py`、`private_storage.py` 的在途修改或封面代码；这里只做共享交接问答和原操作文档，封面源码由你持有。大版本最后已核ACK仍暂停生产，未通知其恢复，也未向其混入本功能。
  - `source_media_refs`记录本次原输入中实际存在的本人图片UUID，保留输入顺序及与观察图片编号的映射；生成上限9，诊断既有 `cover_image + extra_images(max9)`兼容上限10，有源码依据（api.py:6491/6588），不是扩张前端新上传规格。不得把base64、任意URL、视频file_id塞入该UUID列表，不给旧报告伪造/追溯填入从未保存的原图。存储是规范化JPEG引用，不宣称原文件逐字保留。
  - `cover_source_media_refs`可作为本人补传候选列表，与历史原输入分开；只能修改本人目标报告的候选，不改原观察/事实、已生成报告内容、评分或旧任务扣分。写入和读取/实际使用均校本人、purpose=image、状态及TTL，UUID语法正确不足以授权。不要为写候选复制文件或延长到期时间；过期时明确需补传。
  - 仅给新字段增加严格白名单/响应/保存/重开投影，不放宽任意JSON；旧缺字段兼容，诊断/生成路径都测保存重开与越权/过期。若用户使用纯文字/视频、历史没有完整ref，明确缺图，不从品牌名或视觉描述推断图片。
  - 候选更新不得改变已开始封面任务的输入：任务受理时冻结选中UUID/顺序/内容hash和设计输入；后续补传只影响下一次明确提交。列表重复处理需保证观察编号不漂移，不按同品牌自动合并不同报告。此接口答复不批准90天保存、封面定价、模型启用或额外付费调用。

### 最新 checkpoint — 2026-10-19 北京23:46，基础补丁已提交，完整功能待产品合同

- 分支：`codex/noteai-xhs-cover-20261019`；本checkpoint观察HEAD/功能基础提交：`94e78f7f64032ae90fa15b41350119bf28c7bed3`（父`cc96df7`）。之后仅有接收/Q&A/checkpoint文档保存提交；恢复时仍须`git rev-parse HEAD`核实际后继，不为匹配本编号回退。
- **本阶段已完成**：生成/诊断原输入UUID持久化与公共白名单；新增`source_media_items`保留原字段+1起始观察索引，混合legacy base64及重复ref均不漂移编号。生成9张/诊断既有10张保留，封面候选仍最多9。仅保存可追溯规范化图片引用，不还原从未保存的旧图。
- **补传/读取合同**：本人`GET/PUT /reports/{analyze|generate}/{id}/cover-sources`，本人且属于该报告的`GET .../cover-sources/{media_ref}`。旧缺图/过期明确`reupload_required`，原`/upload-image`上传后PUT关联；存储故障明确`storage_unavailable`。补传只写独立`cover_source_media_refs`，不改原事实/观察/评分/扣分/到期日。重复补传不收费，读取字节经owner/purpose/TTL/hash验证，响应不缓存。没有复跑报告。
- **兼容修复**：旧诊断若因原历史内部字段整包被白名单拒绝，只单独严格投影新增候选字段，原raw内容不清洗/不泄露，completed fallback不覆盖后补候选。补齐同源Nginx窄GET/PUT集合与GET单图location源码；未reload/部署。
- **策略合同**：`model/cover_policy.py`仅纯函数，要求明确provider/固定model/尺寸/积分/保存秒数/调用上限/预算/价格版本；缺失或disabled拒绝。`cover_generate`与原报告报价分开，按张Decimal估算与真实账单分开，原物理call去重，已发未知只核原请求。可显式报价0次生图路线，但不自行批准该路线。该模块尚未接真实任务/账本，不把纯合同测试称为唯一扣分已实现。
- **变更文件**：`model/api.py`、`model/public_product.py`、`model/cover_sources.py`、`model/cover_policy.py`、`deploy/production/public-account.locations.conf`及三个定向测试文件。原HTML、账本实现/支付、DB schema及迁移目录均未改。
- **有效证据**：`/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/evidence/foundation-94e78f7/RECEIPT.json`及同目录日志/SHA。最终83项PASS（source15+policy20+report-source18+原报告/后结算API29+原拒绝规则1），`py_compile`/`git diff --check`PASS。另原reservation23项在此前关联52项中通过，核心未改，未再重跑。测试用隔离SQLite+InMemoryObjectBackend/合成素材/模型替身；本机Python3.12.14，既有requirements-api原样安装到本worktree被忽略`.venv`，无新增生产依赖或复制他窗配置。
- **独审**：`/root/cover_foundation_review`独立核diff和证据；两项真实遗漏已修复，无未结P0/P1/P2。新增夹具一度因4字模拟观察小于既有长度校验而失败，失败日志保留；只修夹具，单用例及最终83项通过，未放宽产品校验。
- **当前未完成/不冒通过**：封面后台执行、Seedream adapter、设计/制作/QC、可管理成品保存及唯一结算、Admin按张成本/配置、PC/H5入口/状态/重开下载、真实PG事务、多人共享真实供应商容量、真iPhone保存。没有封面成品样本；合格交付数0、每张合格成本N/A。Nginx仅正则契约验证，本机无nginx，未做`nginx -t`。
- **运行/费用/未知**：无运行中供应商或生产请求，无新UNKNOWN；新增付费模型调用0、生产动作0、生产DB动作0、新迁移0。历史UNKNOWN及旧150元修复预算原样保留，不挪用。所有本阶段子代理任务已完成，无并行源码修改者。原窗口A02仍确认账号权限/实际价格/配额UNKNOWN。
- **恢复入口/精确下一步**：本节→权威清单→Q/A→实际git status/HEAD；先采纳用户对下面集中产品选项的回复，再接明确的封面job/策略快照/后结算与保存合同；不重做本阶段、不重放任何旧供应商/支付/Item32请求。原窗口A01约定必要增量候选可放`model/migrations/features/noteai_xhs_cover_20261019_0001.sql`，当前无需迁移且该文件尚未创建；本窗口不新建发布程序，正式集成仍归原窗口。

#### 集中待用户确认（已通过本聊天一次性提问，尚无答复，不作为批准）

1. 推荐生成/诊断报告共用视觉专家栏入口；实拍保真优先、按需Seedream Pro固定`doubao-seedream-5-0-pro-260628`；默认一张3:4 `1776×2368`。一次看图设计+最多一次图片调用+一次成品质检，零自动付费重绘；系统排字、免费改字/断行/移位，换主图/重新设计新任务；成品/底图/版式90天，临时素材TTL不变。看图设计/QC建议复用现`doubao-seed-2-0-lite-260428`，每次输出<=2048tokens；固定字体/许可需随最终资产核验。原始素材保留/90天素材快照细节待此方向确认后收敛，不默认为全部上传续期。
2. 推荐暂定8积分/合格交付，样本成本核实后才启用；保存合格成品后唯一扣分，读取/重开/下载免费。8分按现套餐标价分摊约2.55–3.20元，仅标价分摊，非实收/利润证据。UNKNOWN保留原请求、最长30分钟释放用户预留且此后不追扣该任务，是待确认策略；本次未把30分钟写成运行默认。另建议单任务模型预留上限2元，须按实际账号价/输入预算计算后纳入已授权总额，不能由Agent自行追加。
3. 当前费用授权仍为0。已询问是否批准最多6个有使用权代表样本、总新增<=15元、最多18模型调用、自动付费重试0；未收到答复即不发起。先离线与受控集成；账号未开通则停在实测入口，不开通新计费项/权限/资源，不部署。

官方资料核对采用公开官方网页（`read-docs`已读，因Firecrawl按次计费且无新增预算未用其付费检索）；部分官方页面仅JS外壳，正文来自官方域检索索引，不冒账号验收。官方[型号列表](https://docs.volcengine.com/docs/ark/model-list?lang=en)、[尺寸教程](https://docs.volcengine.com/docs/ark/seedream-4-0-5-0?lang=en)、[价格](https://docs.volcengine.com/docs/ark/model-pricing?lang=en&redirect=1)支持：Pro `1344×1792`是1.5K/<=261万像素档0.30元，`1776×2368`是2K/>261万像素档0.60元；1–3张参考图图片部分公开估算分别0.30–0.34/0.60–0.64元，不能将“2K”套进0.30元档。上述均非当前账号实际账单。图片[API](https://docs.volcengine.com/docs/ark/image-generation-api?lang=zh&redirect=1)临时URL24h须转存；思源黑体[OFL许可](https://raw.githubusercontent.com/adobe-fonts/source-han-sans/master/LICENSE.txt)须随实际固定字体资产保留，当前未下载/植入字体。

技能实际使用：已读`frontend-testing-debugging`用于后续局部浏览器验证规范，目前HTML无变化、PC/H5封面流程未实现，未冒浏览器通过。当前未列`brainstorming`/`review-agent`技能，采用定向方案比较与独立子代理等效工作，未假称调用或安装插件。
