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
| 1 接管基线与确认范围 | 封面主代理 | COMPLETE / cc96df7→e4a020c | HEAD/branch/ancestor、原窗口A01–A03；用户1/2同意及专项100元授权见最新checkpoint | 已确认合同直接执行；实际账号权限/价格待核 |
| 2 最小实现与离线验证 | 封面主代理；task/media/UI子代理DONE | COMPLETE / 37512e0+90e969c | 后台、私有PNG、8分唯一结算、异常恢复、PC/H5均有定向证据 | 已冻结；不重复全项目或历史验收 |
| 3 定向集成与授权真实验收 | 封面主代理；原窗口提供隔离接点 | 本地HTTP集成COMPLETE / a7eb030；真实验收PENDING | PC/H5真实loopback FastAPI→SQLite→私有PNG→后结算通过；预算100元已授权、实际0 | PG由原窗口Q04独立继续；账号登录/型号权限/有效价格UNKNOWN；真实成品/iPhone待测 |
| 4 独立审查与交付 | 独立审查子代理DONE；主代理集成 | 候选独审与交付COMPLETE / 37512e0+90e969c+a7eb030 | 最终产品diff无未修可复现P0/P1/P2；迁移静态4+队列1独立PASS，loopback补独审通过 | 交原窗口准备集成；真实验收未完成、不发布 |

- 接收时分支/HEAD（历史快照，实际状态见最新checkpoint）：`codex/noteai-xhs-cover-20261019` / `cc96df72e03a914f2fa595f4d1ec71b03e2d175d`。
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
  - **A02补充／2026-10-20 已授权后实际只读核验**：主窗口已通过`read_thread`核实新窗口人类原回复`1同意，2同意，3授权100元以内`及其紧前完整三项正文；独立预算100元、最多6样本/18模型调用/自动付费重试0，旧150元不混用。2元单任务上限未在最终确认正文，不补称获批。以下新事实仅更新账号/设施准备，不改变封面窗口的开发拥有权。
  - **账号真实阻塞**：原Chrome火山方舟控制台现明确显示会话切为未登录，已打开正常手机号登录表单并保留原tab1637494949。已一次性请用户正常登录，未索取密码/验证码，未开通/购买/建Key。Seedream是否已开通、固定型号权限、账号有效价格、RPM/IPM、项目与Key绑定均仍UNKNOWN；不能把未登录写成模型未开通或权限被拒。既有Ark看图成功仍不能替代这些证据。账号恢复前封面离线开发可继续。
  - **已有设施现已做当日最小只读确认**：唯一RunCommand `c-sz070iyi0i3k1kw` / `t-sz070iyi0iijfnk`，2026-10-20 00:14:31北京执行；唯一DescribeInvocations原身份读回实Success/Exit0/Dropped0，未重派。正式API仍CID3711/镜像9be6/PID2779792/restart0/running；静态仍c4a指针。原隔离API `noteai-local-api-ca-9cd7` CID761d26/image `c4a27a321e5613eccccc8418b712d3c8a1253d7ee11aebe6a83216f1abd50fa2`/PID2760125/restart0/running，与最后previous39兼容演练镜像一致，**不是封面候选**；旧f3e85bd仍exited。PG4e19/imagee853/PID918657/network=none/running；socket host源 `/var/lib/noteai/old-hotfix-local-pg16-9cd7d2ac5f84-20261013-01/socket`对应容器`/run/noteai-pg-socket`。未查业务表、未验证当前DB权限/事务/在途任务，不以running冒充真实验收就绪。
  - **隔离/入口边界**：隔离API实际network=host，与生产同机；PG为network=none+独立Unix socket，这不是完全网络隔离证明。`/etc/nginx/noteai-private-ui-204-0615.locations.conf`仍不存在，parent6181B/SHA4c801704978fffb4bd4a0c7b70b03486ee27a621fcf4d478b801a3a811986a0e，原测试公网入口保持关闭。旧18:00开放许可/运行时scope/arm载体均已过期，不可重放。
  - **可复用接点及尚需事项**：有原API/PG/私有存储受控设施，无需先新建服务。后续主窗口在完整候选、离线验证及样本清单就绪后，依原受控构造/配置渠道装载确切提交/镜像，核新候选只连隔离PG、本人素材和封面专项预算，不复制生产env/Key到worktree。旧原生scope96/150元控制不能充当100元/18calls新约束。当前尚未装载封面镜像、核旧在途/预留或重新开放入口；如需浏览器公网验收，届时按工具的当次开放要求安排，不能沿用过期许可。准备不等于生产部署授权，也不由本次主窗口代发模型。
  - **证据**：`/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/root-account-environment-20261020-r1/RECEIPT.json` 9850B/SHA256 `4c4728f197b22f14a5a1847659fa941afe27cda5c08ab2925b8458eec9dc6159`。同目录保存RunCommand原回复、DescribeInvocations原回复10023B/SHA`eeadde60ec92b09e27363914120e094f12543d31d295956e1eb718b5d0b52abe`、2227B实际只读命令、3923B解码输出、官方回执截图及脱敏登录观察。1次云只读命令/1次原身份查询、DB查询0/服务改动0/供应商0/付费模型0/凭据值读取或复制0。复原/部署/迁移/开户均未执行；截图是元数据读回，不是封面验收。
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


### 主窗口阶段预读 — 2026-10-19 23:48北京（素材/策略基础，不是上线验收）

- 已核功能提交`94e78f7f64032ae90fa15b41350119bf28c7bed3`父`cc96df7`；实际HEAD为文档后继`455efaa5ee710bd87796cd8a0f177c4ec2456b26`，94→HEAD仅CURRENT/HANDOFF文档，预读前工作区干净。未cherry-pick到生产基线，未切换服务。
- 阶段原件`/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/evidence/foundation-94e78f7/RECEIPT.json`为4246B/SHA256 `c39eca8fb4afa989c7a85fca63d68eba00e75eb47eeef3a44f457bc6bc1bbe13`；已独立核8个提交文件SHA与8份证据日志bytes/SHA。最终日志载83/83 PASS；这是核日志，不是本窗口重跑或供应商/PG/浏览器验收。
- 只读预审素材权限、原报告白名单/补传隔离及纯policy，未见阻断继续隔离开发的明显问题；同源Nginx仍仅源码及正则合同，未`nginx -t`或部署。原8/6、素材TTL、schema/支付、原HTML未作为本阶段改动；不将纯policy当真实后结算实现。
- 后续接口提醒1：新任务如果选补传图片，使用该候选自己的图片身份/设计观察，不能套用历史`source_media_items`的原观察编号与描述。
- 后续接口提醒2：当前`inspect_sources()`会完整读取并校验所有候选图片，不要在高频任务状态轮询中反复调用。现阶段无须为此扩建缓存框架；在封面job/status接线时避免重复取全图，按需要验最终选中素材。
- 完整功能仍缺后台执行/Seedream/成品保存及唯一结算/Admin/PC-H5/真实验证；合格成品0，不能启用生产。8积分、2元单任务上限、UNKNOWN30分钟释放、90天及15元小样本均仍是封面窗口待确认建议，主窗口没有代为批准。Seedream账号证据仍UNKNOWN。
- 本次仅共享文档预读记录，未在活跃封面分支提交或编辑其源码；无云/数据库/供应商动作、付费调用或新增预算。最终统一集成发布归本窗口，阶段预读不等于可发布交付。


### 最新用户决定 / 执行 checkpoint — 2026-10-20 北京00:05

- 用户本聊天明确回复：`1同意，2同意，3授权100元以内`。对应上一条完整三项确认，已批准：两报告视觉栏共入口；实拍优先按需固定Seedream Pro `doubao-seedream-5-0-pro-260628`；1776×2368单张；设计1/图片最多1/QC1；系统排字与免费文字/断行/位置调整；换主图/重设计另任务；成品/底图/版式90天；8积分/合格交付、先保存再唯一扣分；UNKNOWN核原请求、最多30分钟释放用户预留，此后不追扣该任务。
- 新的本功能独立真实验收预算上限100元。用户只调整费用上限，仍保留最多6个有权代表样本/最多18次模型调用/零自动付费重试。不继承旧150元修复预算；不据此扩成大规模评测或生产发布。
- 单任务2元并未出现在最终重发的三项确认正文，不能冒成用户批准的额外产品硬上限；执行采用明确调用/输出上限及本验收总预算保守预留。
- 当前分支/HEAD `codex/noteai-xhs-cover-20261019` / `455efaa5ee710bd87796cd8a0f177c4ec2456b26`。唯一未提交文件是原窗口追加阶段预读的本HANDOFF，已读并保留；不回退或覆盖。原83项基础证据继续有效，后续只补影响范围。
- 实现分工：主代理拥有API/shared admission/private_storage90天/Admin/集成；`cover_task_contract`独占cover_jobs、feature SQL、billing/postdelivery及对应tests；`cover_media`独占renderer/runtime/Seedream及fonts/tests；`cover_model_decisions`独占原HTML及前端定向tests。独审者待最终diff就绪再启用。没有两个修改者争同一源码文件。
- 下一步IN_PROGRESS：实现原账本预留的持久封面任务/状态恢复、原图保真程序排版+至多一次Seedream、90天私有成品/版本化免费调整、API/Admin/前端最小闭环。先离线及受控集成，再核账号安全配置条件；账号未开通不激活/购买/建Key。
- 运行中provider请求无，付费模型调用0，生产/生产DB动作0。历史UNKNOWN不变。本checkpoint前83项通过不重放；真正每张合格成本仍N/A。

### 恢复 checkpoint — 2026-10-20 第二阶段离线闭环收尾

- 实际分支/HEAD：`codex/noteai-xhs-cover-20261019` / `e4a020c`；完整功能正在该提交后未提交工作区集成，不回退或复制他窗改动。原窗口追加A02账号/运行时答复已保留。
- 已实现：独立cover_generate任务与8分预留/唯一后结算，原请求持久恢复与30分钟UNKNOWN释放；设计1/图片最多1/QC1；实拍主体保留+程序文字；90天私有底图/成品及版本免费调整；两报告局部入口/已保存封面列表/鉴权下载；已有Admin配置体系内的默认关闭开关和按张成本。新增字体沿用OFL随附许可，无新增生产依赖。旧素材TTL不延长。
- 有效证据：基础83项沿用94e。任务/原后结算/Token回归63项PASS；runtime/Seedream23项PASS；真实本地SQLite/存储/渲染/供应商协议MockTransport全链10项PASS（禁止socket外联），含多人物理峰值2/图片峰值1、原报告占用资源、保存失败、UNKNOWN和唯一扣分。新增settings10项与scope/共享调度22项PASS；Admin VM21项PASS。PC1280×900/H5 390×844首轮浏览器替身通过，当前正在补两项审查修复；这些不冒充真实模型或真实iPhone保存验收。
- 调试记录：新增guard测试曾用不被原表接受的`failed`枚举及旧quote，已只修fixture；原disabled调度测试原先断言不读Invocation，新封面例外需查context，改为验证无Invocation时不触碰scheduler，产品行为未扩展。settings测试检出secret保留键草稿假成功，已改为只查is_secret并409，不读secret内容。独审UI两项（标题候选/明确拒绝后的pending恢复）正在修复。未扩大历史验收范围。
- 计量范围：acceptance独立100元/6任务/18调用；formal独立权益计量scope仍每任务最多3调用/8分，没有把测试预算当商业永久上限。两者均默认功能关闭；正式scope不意味着生产启用授权。每张图片估算与真实账单分列，UNKNOWN/未到账单不当0元，不追扣已释放任务。
- 最小迁移：仅feature SQL新增cover_jobs、cover_image_usage、cover_asset_revisions和两独立预算行，兼容原schema31；SQL显式事务及可重跑约束更换，旧50元预算值/历史不改。没有运行全量migrator。真实PG验证PENDING：本机无PG/psql，Docker daemon未运行，这是环境限制；原隔离PG由原窗口安排受控装载后验证，不能拿SQLite通过替代。
- 直接阻塞：原窗口A02实际读回火山会话未登录，固定Seedream型号权限/账号实际价/配额仍UNKNOWN；已有隔离设施运行但未装载本候选。付费调用0/100元，真实合格封面0，每张合格实账成本N/A。无运行中供应商请求、无新UNKNOWN、无生产/DB配置动作。
- 分工/下一步：HTML代理仅改原HTML及前端tests；media代理仅新增API测试；task代理仅新增settings测试，原所属实现已交主代理。主代理收尾API/Admin/guard与文档，完成最终离线证据后交独立审查者复审最终diff。准备真实调用前必须更新本checkpoint、列≤6样本和≤18调用/成本预留；账号恢复及候选隔离绑定未完成不派真实模型。生产切换仍仅原窗口执行。

### 可定位候选 / 集成恢复说明 — 后端37512e0 + 前端90e969c

- 功能提交：`37512e0678846adabec1623a2000ce3cc4d452cc`（后台、任务、PNG、结算、权限、最小迁移、Admin与对应验证）；`90e969c`（原PC/H5局部入口、已保存列表、刷新恢复、免费调整/下载/成本展示与浏览器验证）。均在原分支，不推生产；基础94e78f7仍为必须祖先，不能只取前端提交。
- 最终独审修复：PG原RLS仅允许旧Admin配置键，已在feature SQL只为2个cover键增加Admin非secret读/插/改、无删，并保留原app排除集逐字追加这2键、app仅SELECT；不可用SQLite掩盖真实PG权限未验证。formal忙用户32个排队任务遮住其他用户，现按每用户最早queued选取再LIMIT32，补32A+1B回归。Seedream返回的非secret供应商request_id原被service丢弃，现严格过滤后持久保存到图片账本以便核原请求，UNKNOWN没有回执ID时仍保留本地physical ID/时间/响应摘要，不补造供应商ID。
- 恢复交互：最小原始wire（原request UUID/quote/≤9媒体UUID/已有标题≤300）仅保存在同用户同报告session key，无原图字节/正文/token；刷新后先核原列表、记录不可读不重交，确无记录才由用户显式原UUID/原内容幂等重交。存储失败先于POST停止，ACK/明确无hold拒绝后清除。此能力不授权自动付费重试。

| 改动/风险 | 复用证据 | 需要补测/当前边界 |
|---|---|---|
| 素材关联、旧报告白名单/补传 | 94e基础83项 | 原图真实过期由现有TTL，补传不重跑报告；真实 owned 1/9图样本待账号 |
| shared guard/结算/图像账本 | integrated127；之后修改的jobs/service/SQL重跑41；共享Ark/原报告纯mock40 | 真实PG事务/RLS/迁移两次待原隔离设施；非生产请求已直接交原窗口Q/A |
| 首版配置/权限/成本显示 | settings10、Admin VM21（其中新增Admin3）、feature SQL静态4 | SQLite不证明PG RLS；按张账单仍UNKNOWN，估算不等于实账 |
| PC/H5最小入口与恢复 | 最终VM22、两尺寸替身浏览器、a7eb030真实loopback HTTP两尺寸全链 | loopback使用fixture鉴权+合成图/模型替身；真实iPhone保存未测 |
| 字体/尺寸/主体/文字 | runtime/Seedream23及真实PIL存储全链 | 合成样本不是模型质量；未做生产Docker build、nginx -t、发布 |

- **集成操作边界**：原窗口从以上完整候选构造现有隔离API镜像；保持其他组件与schema31历史不变，只在隔离fixture数据库先验证feature SQL两次、原表/预算不变、app/Admin精确权限及事务。不要调用全仓`render_predeploy.py`，不要触发0032–0041或大版本迁移。本次未授权封面立即生产启用/迁移/发布，不能继承旧修复授权自动上线；取得对应发布授权后也仅由原窗口统一执行。
- **配置/执行**：服务端只使用原受控`NOTEAI_ARK_API_KEY`通道，不将值复制到worktree。实例`NOTEAI_COVER_WORKER_ENABLED=1`才加载一个cover worker；还须已有存储、对应独立budget行和已发布enabled/account_verified/证据ref配置。默认全关，新GET不安装DDL；Admin draft/activate/restore沿用现有操作编号/原因/修订围栏。`execution_scope=acceptance`才消费本任务100元/6/18，`formal`另记权益成本，不能将验收占用清零或迁移为正式消费。单API进程共享物理2/Seedream1已离线验证；实际多进程/多实例服务器容量未证明，不外推。
- **回滚/恢复**：先关闭新封面提交，保留旧成品GET/download/免费排字、原任务与账本；在途按冻结策略收尾。worker重启只恢复未派发原任务，已有调用intent/UNKNOWN不自动重发，30分钟释放原用户hold后不追扣；删除中用户沿用原写围栏，由既有删除协调流程清理其hold，不假称该例外已经实测30分钟释放。停用worker/代码回退不能删新表、对象、预算、原供应商UNKNOWN或历史版本。已保存ACK未知先读同job/revision，原请求最多扣8一次。
- **SQLite说明**：fresh测试库由显式init helper建feature表；已有旧SQLite的旧budget CHECK不会自动重建，此路径fail closed，未用于生产。本交付不偷偷迁移/重建旧本地数据。
- **费用/样本**：真实模型调用0、真实合格交付0，实账每张合格成本N/A。固定1776×2368图片公开估算0.60元/张，只有需要背景时调用；两次Lite按真实Token另记，保守预留约0.978元/任务（按最大上下文/输出公开价，非账号账单），含背景总预留约1.579元/任务，6任务约9.474元，预算上限100元不是支出目标。8积分按当时套餐标价分摊约2.55–3.20元，非实收或毛利；保存90天可能产生原对象存储按量成本，尚无实际用量账单，不造0元。
- **真实验收待执行计划**：账号恢复且固定型号/价格/项目/Key/配额脱敏绑定已核后，先1个自有单图完整样本，再1个自有九图选材样本；其余最多4个用于餐饮/酒店/实际休闲不同子类与边界，按首样本质量收敛，不强制凑满。每job最多设计1/图片1/QC1，总≤18，预算保守预留和真实成本分别留账；UNKNOWN只查原ID/账单，不盲发，失败不自动重画。准备每次真实调用前在本节登记样本/原job/call ID、当次预计费用与数据影响；当前未取得完整账号条件，未dispatch。


### Q04 / 封面增量真实PG验证 — 主窗口预检事实（2026-10-20 00:48北京，文件本段写完已释放）

- 目标候选后端`37512e0678846adabec1623a2000ce3cc4d452cc`，精确feature SQL8839B/SHA256 `bd6626c6fb887c6aedc665ea981f4a6b28679cb20cb11a70546ca43078b077ec`；前端90e969/后继测试a7eb030不改变该SQL。仅此增量，不跑0032–0041。
- 本轮唯一已派发预检：`c-sz070j18v6lcu0w` / `t-sz070j18v72u4g0`，官方Start `2026-10-19T16:45:18Z`，原身份DescribeInvocations已读回Success/Exit0/Dropped0；无未知执行、未重派。原件 `/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/root-pg-migration-37512e0-20261020-r1/preflight-read-original.json` 7493B/SHA `03b6dae887273f0201f1ed9706c38a394d69e805953521626b01b048d7bc7cd7`；同目录保留preflight-run-original、3798B原只读命令及解码output。
- 预检只在原运行隔离API761d26内以UID0、现有权限尝试连接PG维护库postgres及原隔离库的只读元数据；两者均明确OperationalError/sqlstateNULL，现容器CapAdd=null。未取得有效数据库会话或schema31/RLS当前读回，不能据此称PG迁移/权限测试通过，也未取得足够错误细节将其唯一归因为HBA或文件权限。数据库写入/迁移/模型/服务变更均0。
- 原PG硬化证据明确限制新数据库连接，普通API不是owner入口；不会为测试改HBA/新建角色/扩大IAM。下一最小可行接点是原先已验证的network-none、单socket只读挂载、root/DAC_OVERRIDE一次性客户端模式（E旧local-pg16-peer-plan02/root_setup_once.py:49–60），仅复用原受控客户端边界，不重放setup/旧时窗或启动服务；当前尚未运行此owner客户端。先只读确认维护库无业务对象/其他会话，若不满足即停止夹具。
- 未来若可演练：维护库外层事务承载合成夹具，只把原SQL唯一首尾BEGIN/COMMIT交给外层事务管理，保留原文件SHA/变换证据；正文两次、SET LOCAL ROLE原app/Admin、最后完整ROLLBACK并核对象/ACL恢复。不冒完整原SQL包的独立COMMIT演练；source schema/RLS仅只读，旧业务库public不做DDL/数据写。100元由应用guard约束，不称数据库CHECK硬cap。
- 该段之后共享文件编辑权已释放，封面窗口可立即保存自己的最终交付checkpoint，无需等待本轮PG演练；主窗口后续结果只追加，不覆盖你新段落或源码。当前实际PG迁移/role验证仍NOT_EXECUTED，Seedream登录阻塞沿原A02、不重复催登录。

### 最终候选交付 checkpoint — 2026-10-20，北京00:49后

- **实际分支/HEAD**：`codex/noteai-xhs-cover-20261019` / `a7eb0302d8542c866832119046337219d6b53a7d`；本段与CURRENT后续只作交付文档提交。功能后台`37512e0678846adabec1623a2000ce3cc4d452cc`、前端`90e969cc7c86fe9bff6d838769c6f45e727196e7`、真实loopback测试`a7eb0302d8542c866832119046337219d6b53a7d`，基础94e78f7为祖先。不回退，不新树，不push/merge/deploy。
- **完成与交付**：阶段1/2及阶段4候选独审/交付完成；阶段3本地真实HTTP集成完成，真实PG及供应商/成品验收仍未完成。接口、迁移/恢复、预算与成本依据见紧前段。完整候选直接交原“修复高德检索与休闲娱乐行业”窗口`01a13080-d8a9-7c50-88c0-09ffcebbef61`，其已接Q04隔离PG协作，不需要用户逐项转述。
- **本次补成的可复用证据**：`/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/loopback-integration/HTTP-BROWSER-RECEIPT.json`，30028B/SHA `b7827b1b8930ee0413ed2e9e7c9a2d69f45a1e14967f8953266c7a58bf6ac6b7`。真实127.0.0.1 FastAPI+临时SQLite+私有对象+PIL；PC1280×900、H5模拟390×844各1任务，真实GET/POST非API fulfill、保存后8分、整页重开原job、下载1776×2368实际PNG、免费排字revision2无新调用/扣分。fixture总4次Mock协议调用/16测试积分，不算真实供应商调用或生产积分。真实身份/登录没有验证，auth为显式dependency override；Python外联禁用，浏览器只放行loopback、WebSocket禁用。后端exit0、浏览器关闭，唯一listener49431已连接拒绝。
- **样本与汇总**：同目录`cover-http-1280.png`/`cover-http-390.png`及两张adjusted为实际保存/下载的合成素材PNG，各SHA在收据；`cover-http-ui-1280.png`/`cover-http-ui-390.png`为页面截图。另`/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/samples/offline-synthetic-cover-preview.png`是合成排版示例，不能当真实模型合格封面。总索引`.../evidence/CANDIDATE-RECEIPT.json`绑定36份本阶段源码/测试及日志；基础83项独立原收据不重建。
- **独立审查**：`/root/cover_foundation_review`对37512e0/90e969c最终产品diff无未修可复现P0/P1/P2；独立迁移静态4+32A/1B队列1通过；另只读补审a7两test-only harness与清理/费用边界，无新增P0/P1/P2。收据`.../evidence/final-independent-review.json`及本段记录保留。早期VM夹具失败与455efaa基线一致，未扩大修旧测试；精确对照在FRONTEND-RECEIPT。所有开发子代理已完成对应任务，无源码并行修改者。
- **未决/运行状态**：本窗口真实供应商请求无、付费0/100元、真实合格成品0，每张合格实账成本N/A；不把Mock、成功HTTP或像素规格当模型质量。PG精确SQL尚NOT_EXECUTED，原预检唯一C/T已S0D0见Q04，原窗口下一受控owner客户端尚待其后继记录，不继承/重派其请求。原火山登录未恢复，账号权限/真实价/配额UNKNOWN，真实iPhone保存未测；历史UNKNOWN不变。
- **恢复入口/下一步**：先读本最终段及Q04后继追加，再核git status/实际HEAD；保持候选默认关闭。原窗口只做既有隔离PG的最小验证/候选受控装载，记录成功或具体阻塞；账号条件恢复后按前述≤6样本/18调用/100元计划逐个记录并验收。真正准备付费前更新本checkpoint、样本/原job/call ID及费用预留；供应商未知只核原请求，不自动重试。当前没有封面生产发布授权，不创建第二套发布流程。


### A04 后继结果 — 2026-10-20 北京01:08，真实PG定向夹具通过；共享文件编辑权已释放

- **可接续结论**：后台37512e0678846adabec1623a2000ce3cc4d452cc的精确feature SQL（8839B / SHA bd6626c6fb887c6aedc665ea981f4a6b28679cb20cb11a70546ca43078b077ec）在原PG16.15、维护库postgres的外层ROLLBACK事务中完成两遍正文及89项断言。仅移除唯一首尾BEGIN/COMMIT，正文SHA fe93b6486b8ded69d741dfd61528cd5b13dd166036557e450cc3776e42a2ec3e。不是完整文件独立COMMIT发布演练，不将此限定结果写为全部真实PG产品验收。
- **最终原身份**：c-sz070j2y4yfh79c / t-sz070j2y4ywyhog，Start/Finish 2026-10-19T17:04:23Z–17:04:25Z（北京01:04:23–25）；官方DescribeInvocations Request01A1551F-867A-55B5-B17E-E62216AC9109，Success/Exit0/Dropped0。客户端exit0且已自动移除；维护public对象/ACL、default ACL和全局角色快照均恢复true。无业务库写入、维护事务COMMIT、HBA/角色属性/IAM/生产服务/公网配置修改，无模型调用/新增费用。
- **覆盖**：两遍表/约束/索引/RLS/ACL/预算快照一致；旧owner_metered合成累计114234保留，新acceptance累计1234不被第二遍清零；无效id/limit/formal策略被精确identity CHECK拒绝，旧单调触发器仍有效。Admin仅两个非secret cover键读/插/改、不能删/改key或secret；app仅读、写/UPSERT/改名/删除无效或拒绝；原模型/Prompt策略兼容。新增三表app精确权限、Admin仅status/16成本列且整表/其他列与revisions拒绝，PUBLIC/其他角色未获新表权限。100元上限仍是应用guard，不误称DB硬cap。
- **实际环境缺项与夹具前提**：原isolated schema31确实只有app ACL，system_settings的Admin各列SELECT/INSERT/UPDATE全false；这是原setup只装app_acl所致，不是此次feature新增策略被PG拒绝。唯一只读catalog c-sz070j2sjuyr9q8 / t-sz070j2sjvb8rgg S0D0核实，default_acl=[]、角色无额外成员关系。最终夹具仅在可回滚维护事务内加入现有scripts/postgres/noteai_production_runtime_roles.sql:612起对system_settings的SELECT及noteai_admin_operations_acl.sql:20精确INSERT/UPDATE列，然后测试迁移；**原业务库ACL完全未补**。此依赖须纳入候选隔离装载及最终发布前的元数据只读核对，不能把SQL本身称为新建完整Admin权限，也不能重放全角色脚本。原role NOLOGIN/INHERIT属性未改，测试通过SET LOCAL ROLE，不证明生产Admin登录合同。
- **失败历史原样保留**：最初普通API连接失败见Q04；后续owner只读预检 c-sz070j1moi23e2o/t-sz070j1moih2s5c成功。未压缩命令因CmdContent.ExceedLimit在API入口拒绝（Request01A15518-D060-5C0A-A382-07744C7CA7C9，无C/T未执行）；等价gzip包没有改feature SQL。r2 c-sz070j2f3nvtmv4/t-sz070j2f3o8b4lc因一次性脚本误用value而非value_json停止；修正后r3 c-sz070j2krafc4cg/t-sz070j2krazbb40发现上述原Admin ACL缺项。两轮均迁移/预算已通过并完整ROLLBACK，没有未知执行或生产业务失败，不能删掉当作一次全绿。
- **证据**：Epg=/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/root-pg-migration-37512e0-20261020-r1；RECEIPT.json 12139B/SHA870e5c003182f46a42d682521b298b2d66efd1ea6de3bcfbf34c86c013a6d7a3。该目录含6次实际云命令的原提交/查询回执、长度拒绝原件、各版测试命令/绑定源码与SHA、输出、official-final-readback.png，终局fixture-r4-output.json列89断言/回滚事实。测试辅助代码只在此临时证据目录；本窗口未改产品源码、没有在封面活跃分支提交。独审代理预审了夹具并促成字段/权限断言补齐；不把预审称为独立真实运行。
- **仍待完成**：完整候选API运行于原隔离数据库的应用事务/预算/真实鉴权测试，真实供应商与成品质量（账号登录/型号/实际价/配额/绑定仍A02 UNKNOWN）、真实iPhone保存未测。FK父表仅id合成桩，未复制任何业务行，不替代全应用流程。候选仍默认关闭，实际付费0/100、真实合格封面0；当前生产仍f3e/9be+Pay/Admin39+publicc4a/schema31，未上线封面、不重跑旧报告/高德/支付。下步由本窗按完整候选准备既有隔离装载和明确Admin前提，账号条件齐后按≤6/18/100计划逐个验收；若无本人登录则保留具体阻塞，不再催同一登录、不扩权限。没有生产发布授权，不能因此自动执行封面迁移或切换。


### Q05 / A05 首个接口回读 — 2026-10-20 北京06:58；原窗口只写本段后释放，不操作Ark页

- 人类原件已核：封面thread01a154c9-62ef-7fc2-82dd-0c3a8441193b最新user turn01a1565e-b770-7242-97cc-e7b90f6008ad明确要求本地水石清池九图→新爆文→封面真实验收。这替代原“只复用旧报告”的当前测试输入要求；不是重放旧失败/UNKNOWN任务，不扩大为生产发布。100元独立总预算不变；旧114.234888/150保持独立。
- **浏览器归属**：你06:54已持有原Ark tab1637494949并核仍登录表单；原窗口不再同时操作、重问本人登录、发送验证码或建Key。控制台未登录本身不是API不可用证据，也不会被人为当作唯一核权入口；API真实拒绝/UNKNOWN和有效价格证据必须分别记录，不能只改account_verified来绕过尚无事实的配置前提。
- **现成可运行接点的真实状态**：最后当日主机读回是00:14元数据，原PG4e19/schema31/socket存续，原隔离API761d26/image c4a27a仍是previous39测试镜像，**不是919c720封面候选**，所以目前没有可冒充已装好的/covers真实入口或新scope。A04仅维护库ROLLBACK夹具，没有把feature表/预算/ACL写到原业务库。原私有Nginx include仍关闭、旧lease/arm/运行scope已过期。不能把旧启动器直接执行成新功能验收。
- **本轮确切产品来源**：919c720是文档HEAD，产品后台37512e0+前端90e969c+基础94e78f7+测试a7eb030；需要在原已存API镜像上精确overlay这些相对c4a的文件并单独保存source/image SHA，原配置由主机现有安全通道就地供给，Key/env/连接串不复制到本机。DB仍原独立socket，存储必须原隔离subject/purpose/TTL通道；真实启动前还须核在途/原容器身份、字体/依赖、feature精确SQL与原Admin ACL前提，不能全量migrator。
- **已经明确的预算接线缺口**：cover_service.py:35–36与public_product.py:713–745只让/covers用noteai-xhs-cover-20261019-acceptance（100000/6jobs/18calls/每job3）；普通/generate仍BUDGET_ID=website-free-product-20260912。改Admin封面配置不能把新九图报告的全部内部调用自动归入同100元，不能混旧scope96、旧150或悄悄修改全站预算行。需要复用原付费guard的独立本轮聚合账本，对报告+封面每条实际物理调用统一预留/结算，保留业务原账本身份；原窗口正只读核最窄安全runner接线，无付费或云变更。
- **调用数必须明确而不能赌**：离线最少9视觉+6文本=15，再封面≤3可到18，但最近同质量真实f3e九图完整报告分别30/33调用，不能保证新图只15，也不能删评分/内部链降质来凑18。最初18是6封面样本×每样本3的计划；最新要求另含一份真实完整报告。当前不得宣称“总18约束已覆盖新报告全链”。本轮先登记报告与封面各自上限、统一100元聚合及原ID，明确18是否仍仅封面上限；若仍要求全链总18，可靠完成新九图验收尚有这一实质限制，不能先付费跑到第18次中断。原窗口不单独派任何模型，保持你为唯一原request登记/调度者。
- 下一步：你定位素材/确认一份唯一新report request与最多一份cover request；原窗口补最窄runner构造、预算/路由差异及可执行前提。Seedream可考虑既有服务端通道的单次固定型号实际请求核权，须有原request ID/明确最坏估算/独立聚合guard且计入本100元，403/配额拒绝即停、结果未知只核原ID，不新增Key/开户/权限；这个建议尚未执行，也不能把公开价当账号实账。生产切换0、付费0，本段后共享文件编辑权已释放。


### A05 续记 — 2026-10-20 北京07:02；原窗口当前只追加此段后释放

原窗口已直接read_thread核到人类原答复item01a15661-bb44-7040-8c9b-6c251261a3ef：“同意40次，总费用仍≤100元”，问题原文限定本次仅1篇新九图笔记+1张封面、合计40、失败/UNKNOWN不自动重发。此决定已解决A05先前指出的18总数冲突；本轮新的外层scope应40总wire/1report+1cover/100元累计，封面内层仍每job≤3，不扩大为6篇报告或40张封面，不改旧18/6历史记录及150/scope96，不构成生产发布授权。

你持有Ark页和原图/原request登记；原窗口持有受控候选镜像/隔离runtime准备和本轮统一计量窄适配，不并行产品代码。准备状态PLAN_ONLY，当前没有模型原request派发或云启动，现成旧API不是封面入口。原窗口先保存与919c720有效候选绑定的源码/字体清单及test-only guard适配；统一费用在外层只计一次，原报告业务账本不冒用cover类型，内层cover费用同调用不再相加。接下来若需写新接口结论会只追加，当前本段已写完并释放共享文件，你可立即登记唯一case与request IDs，无需另等一轮。

### 最新真实验收 checkpoint — 2026-10-20，北京07:02后，水石九图单次完整场景

- 用户明确要求本地“水石清池.汤泉生活”9图→真实新爆文→该报告封面，并核前后端按方案执行。用户另明确回答“同意40次，总费用仍≤100元”：本次仅1篇新报告+1张封面合计40物理请求/100元，失败或UNKNOWN不自动重发；不扩大成40张封面，不继承旧150/scope96，不授权生产发布。原6封面/18调用历史保留，本次外层40覆盖新报告及本次cover，cover内层仍最多3调用。
- 分支/HEAD `codex/noteai-xhs-cover-20261019` / `919c720`；接续原窗口未提交A04/A05文档，保留未覆盖，不回退。阶段3恢复为IN_PROGRESS，先真实环境绑定与零重试/合并计量预检，再派发；不是重做基础/离线验收。
- 原图确在`/Users/openclaw/Desktop/test1013`，9张合计10,977,955B，逐张可解码且与原素材manifest大小/SHA一致。新清单`/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/source-nine-readonly/SOURCE-READONLY-INVENTORY.json` SHA`6f865540a7079784d78c42cc5beba768e9aa660e21eb32d423857e71e33bddd3`；顺序1庭院、2吧台、3庭院入口、4餐区、5餐食摆盘、6汤池、7庭院、8汤池、9汤池。图片观察不是套餐/餐食包含、服务细项、价格/地址/营业时间或亲历证明。contact sheet仅核查，不是封面成品。上传规范化JPEG与本地原PNG/JPG散列不同须分别留账。
- 单次计划原件`/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/real-shuishi-nine-20261020-once1/PLAN.json`，generate原client request=`783412e4-652d-456f-bbdc-dc1cd8863ff4`，cover原client request=`4b492cb5-8ad6-4a2f-bc4f-ec589329ed99`。尚未受理或派模型；实际server job/usage由正常claim返回后追加，不拿client UUID冒充。素材与写作brief已冻结，事实源仅输入/9图，不新增Amap/爬虫，不虚构亲历/未知设施/价格/套餐；完整默认质量链不裁剪。新运行强制guard需跨这两个正常任务共同40/100，不靠cover18预算假装覆盖报告。
- 正常报告默认2候选，完整无修复成功下限20模型请求，cover再2/3；历史该9图真实报告DB记录30条responded/HTTP200/一一关联model rows（不是把多表相加，非socket抓包证明）。正文/标题/质量修复分支可更多；40是硬停，非保证所有最坏输出都足够。普通报告原重试/fallback须本批明确禁自动重发；正常质量流程中的不同修稿步骤仍分别计真实调用。UNKNOWN保留原ID/成本预留，不开新号掩盖。
- **火山账号阻塞已部分解除**：用户主动授权代操作正常手机号登录并提供OTP；本窗已在原Ark页完成登录。仅正常登录，不保存/转发验证码、不读Key值、不改认证/权限。当前账号开通管理显示Pro已开通、IPM500；模型详情明确`doubao-seedream-5-0-pro-260628`，选择图片生成输出>261万像素显示0.60元/张，首输入免费、额外0.02元/张；Lite原看图接点健康/default项目、价格与原冻结表一致。这是账号界面的开通/型号/目录价/限流证据，不是实际供应商账单；服务端既有Key所属项目/可调用性仍由受控runtime脱敏核实。没有开通服务/建Key/购买/订阅/调额。截图在本次PLAN同目录`ark-visual-entitlement.png`及`ark-pro-model-price.png`，不含OTP/Key。
- 归属：主代理持有Ark浏览器/本次唯一原request与真实验收调度；原窗口持有受控候选镜像/隔离PG、存储、外层40/100窄适配；双方不重复派模型。原窗口已回读主机、正构造候选，旧隔离API镜像不是本候选，不能冒已装好。若需前端真实HTTP，优先既有受认证私有服务预览/本机隧道，不以API fulfill或auth override代替；新的公网临时入口若必要先做具体方案并取当次授权，不用过期include。
- 当前本窗口模型调用0、真实成品0、费用0/100，无新UNKNOWN，无生产DB/配置/发布动作。原窗口受控设施准备的命令身份由其Q05后继记录，本窗不重派。下一步：正常鉴权测试身份/候选image+DB+storage绑定、跨任务计量与零retry先验证；然后真实上传9图与generate，保存成功后只对该report提交上述cover原ID；取实际PNG做人工主题/事实/文字/主体检查，再PC/H5重开/下载/免费调整和唯一结算只读核查。开发与产品Agent账本分别记录，不能把Codex子代理当运行时模型请求。

### 实测前协议兼容修正 / 当前HEAD e6234e7

- 新功能提交`e6234e7`仅`model/cover_seedream.py`与对应test：官方Ark SDK的`Usage.input_images`为Optional，可缺省/None。此前强制该字段会将已返回的合法PNG误判UNKNOWN；现缺省时沿派发前已冻结的请求数量，并在持久化pricing_snapshot标记`input_images_basis=request_payload`，终态区分supplier_usage与request_payload、供应商回报值留空，不冒实际账单。存在但bool/str/错数仍UNKNOWN，generated_images=1、model_id、真实PNG解码/1776×2368/只出1张/0retry均未放宽。
- primary依据：[官方SDK](https://github.com/volcengine/volcengine-python-sdk/blob/master/volcenginesdkarkruntime/types/images/images.py#L36)；官方Pro教程与API同时支持b64_json、png及1776×2368，未更换模型或首版尺寸。20项受影响seedream/service离线回归PASS，`/root/cover_model_decisions`独立只读复核无阻断。日志在本次PLAN同目录`optional-input-counter-offline-regression.log`；无付费调用。
- 原窗口已收到精确覆盖要求：最终候选必须在其原构建基础仅增量覆盖此模块，SHA256`3200d6755c89ca8be24847576a862d7eda3db6466a2abd4aa1633721616fc8eb`，产品其余文件不变；不重派已运行构建，不用旧strict adapter派真实模型。当前候选HEAD应核e6234e7后继，不为匹配919c720回退。
- `ACCOUNT-AND-PROTOCOL-CHECK.json`位于本次PLAN同目录，保存登录成功/已开通固定型号/当前页面价与IPM/截图SHA和20项日志SHA。没有保存OTP/手机号/Key；目录价不替代实际用量账单，服务端Key实际绑定与正常鉴权仍待runtime实证。真实模型请求仍0、预算仍0/100；唯一两个client计划ID不变。


### A05 运行准备实况 — 2026-10-20 北京07:09（时戳已按UTC时钟校正）；原窗口追加后立即释放

- 当日真实只读预检已完成（不是计划）：c-sz070jynhzo5hj4/t-sz070jynhzvn6kg，原身份Describe S0D0。正式API3711/9be/PID2779792/restart0仍running；原隔离API761d26/c4a27a/PID2760125、PG4e19/e853/PID918657仍running。原include absent/parent4c8017/staticc4a指针不变；现主机余约11.03GB。9be内Pillow12.3.0/FreeType=true，新增字体absent（已定位、准备时不再重装依赖）。只读脚本/原回执/解码在Enew=/Users/openclaw/.codex/tmp/noteai-xhs-cover-20261019/root-real-nine-cover-20261020-r1。
- **源代码已在实际传输，不是镜像已完成**：919c720相对f3e的18个model文件（含独立SQL）已生成精确SHA delta50384B/df2de934e3ba500b65272455f1e69015792a229d2761065306ec6538aac9f3ec，5段已各自唯一RunCommand提交至/var/lib/noteai/cover-acceptance-20261020-r1/source-parts；1–3已原身份读回S0D0，4/5正读原回执。没有重复传原ID或覆盖旧隔离工作。完整载体705995B仅本机留档，不传.env/Key。build_candidate.bound.py已独立只读预审，修正字体目录0755/文件0444，构建仅9be增量/--network=none/18源SHA及中文字体smoke，不启动API/DB/模型。**build尚未派发、尚无新image ID**，此前不能把准备错称完成。
- 已收并核e6234e7唯一Seedream协议修复、SHA3200d675…；原919delta不丢弃。因原构建尚未执行，直接在同一既定build中apply919后COPY这个新模块，最终标e623产品、其余919相同；不是重派旧构建或把新模块偷偷混入旧SHA。最新43e5bae只是后继文档，不改变其余产品源。
- 外层guard复用原Ledger/物理wire/usage，test-only新目录Enew/guard，不改产品和旧150/scope96；已完成19项离线窄验证，正在收据/最终绑定：同一1report+1cover总40/100、图片按张、不依token统计、UNKNOWN保留停止、重复wire/错父报告/错client/serverjob拒绝。审批/原runtime证明/真实payload与image binding未齐仍approved=false，不会在准备阶段派模型。给定client IDs已保留，serverjob/usage只读真实claim关联；自然UI若生成不同UUID，应先登记原计划未受理/UNUSED并与你核对后再绑定，不改wire或偷偷换号。
- **真实浏览器入口方案**：现无已验证可用的既有私有Workbench端口预览或已获准loopback隧道；本机localhost不等于云主机localhost，不能假称可用。可准备原精确入口https://noteaipro.com/__noteai_test/old-hotfix-204-20261013-0615/及其/api，只还原原Nginx私有include与父配置一行、nginx -t后平滑reload，账号原Bearer/会话鉴权、业务仅原隔离PG/私有storage、新40/100guard，最多60分钟、验收/失败/取消即关，已发调用保留结算。静态只放新专用非secret前端目录，不映射runtime/ledger/env；前后端须真实HTTP，原Gate实际检查原session/本人资格并保留普通auth函数，不使用dependency_override。此为可审查的原入口有限恢复方案，**当前没有当次公网开放批准，也没有执行**；待candidate API本机健康、准确image/IDs/关闭动作均准备好，再由你集中取得工具要求的当次批准，不重用旧时窗。无新权限/订单/支付/SMS/生产迁移。
- 当前只改测试辅助构建/guard与共享文档，模型0/100、生产变更0、无API新进程。你已接管Ark正常登录及最新账号实证，原窗口未重操tab或发SMS；不再沿旧A02写登录阻塞。下一个可核检查点是确切新image+源/字体smoke，随后原隔离装载及guard/正常auth就绪；本段写完共享文件已释放。


### A05 后继实况 — 北京2026-10-20 07:18；原窗口写完立即释放

- 五段source delta均已原身份读回Success/Exit0/Dropped0，4/5原件保存在Enew，无重派。首次构建c-sz070jzkw2hk000/t-sz070jzkw31j6rk在固定GitHub字体TLS握手超时失败；唯一续接c-sz070jztkb24u80/t-sz070jztkb9mj9c在固定jsDelivr同SHA字体TLS EOF失败。两次均在Docker build-started标记前结束，尚无image/API/模型；失败原回执完整保留，不当UNKNOWN重派。准确产品源码delta/e623模块已在原owned构建目录，不重传。
- 新发现实际OSS控制台明确显示账号欠费、Bucket列表不可用；未上传/建桶/改权限/充值。下一步仅检查原API-C工作台是否存在普通文件传输，不换模型/字体/关闭TLS，也不扩大资源。此项是实际构建阻塞，不能写镜像已齐。生产API/DB/Nginx未改。
- guard已最终完成30/30窄离线测试（0socket/0实际模型），索引Enew/guard/RESULT.json；主模块SHA256 eb26a9b16b5bc7d5ea23b68e331344eea36c2b3a9268ccdf853a65c3106d8dec，测试deb1f6bd6df3eaefcac37ebc588c545fefc61ccd759a456f0bead758bb1523e8，模板a0f27a1782ad095a395eb87f378ebfcf80a5dc925ea33599d9046ebb72e384ba，最终日志4c16dbc7fabc9b4c9ec9a0a90096f1f609d48ff32297d6d6f88affb04a21936c。此前19/23项是历史中间态；本冻结含±Infinity/NaN拒绝、120秒自然claim首次reserve暂停与180秒硬上限、两phase CAS保留报告账本/成本、不重POST。模板仍approved=false，无VERIFIED proof被补造；实际runtime/Key项目/正常claim/账本及真实验收仍未完成。无需重跑全项目。
- 唯一真实调度仍由封面窗口持有，原计划client IDs明确UNUSED，使用真实UI自然ID+同Invocation暂停绑定。生产发布未授权，未切换。


### 实测准备恢复 checkpoint — 2026-10-20 北京07:20；本窗追加后释放

- 实际HEAD仍`43e5baeca74f70947a86129c89a699bed3d7847d`，唯一未提交是保留原窗口A05后继的本HANDOFF；产品最终e6234e7不变。当前仍PREPARING，不能称真实验收完成。
- 本窗补核当前火山费用中心：可用49.77元，2026-10月出账中应付0.23/已现金支付0.23/欠费0；仅账号UI快照，非本次账单，不等于服务端Key项目核验。原余额截图及SHA已加入本次`ACCOUNT-AND-PROTOCOL-CHECK.json`，无充值/订阅/设置改变、无凭据写盘。旧费用页CDP焦点读取超时两次，改用同浏览器正常新费用页成功，只读且未重发任何登录或模型请求。
- 原窗口源传输已完成；候选构建下载固定官方字体两次TLS失败、Docker尚未启动，已封存失败。其尝试现有OSS传字体时控制台显示欠费，正检查原服务器Workbench普通上传；不能冒成火山推理欠费，也不能未经核实际private_storage后宣称所有存储不可用。精确云命令身份与原回执归原窗口Enew目录，不由本窗重复执行。
- 真实UI自然client ID需登记：generate是`generate-<UUID>`、cover是自然UUID，均在正常点击后直接POST，无可见预登记暂停。原窗口test-only gate正在支持正常claim后/首provider预留派发前暂停同一原执行、最多180秒、只登记非secret ID/hash/ref/父报告；PLAN人工预填两ID未受理，待正常UI原ID实际收到后标UNUSED并记录替换，不注入隐藏state、改wire或再POST。
- 独审发现辅助guard期限可为Infinity的窄P2已修；finite/gate新增7项替身独立通过、0socket。作者仍迭代辅助权限检查，日志/源尚未最终冻结，结论只为中间预审，不冒live放行。原基础23项及新7项不能拿来替代实际runtime/鉴权。
- 复用本次PLAN的最小只读收据计划已存`READONLY-ACCEPTANCE-QUERY-PLAN.md`，SHA`a2b4349a02662931787960baacfa25bd6dccf3629e0a0cac79b6db43194715d1`；仅窄SELECT/现有GET/真实PNG，没有第二套runner。报告积分待正常实时quote，封面8分独立核；最终报告/封面/免费调整三个时点对比物理call与唯一扣分。PC/H5使用当前CUA浏览器及其viewport能力，不以模拟尺寸当iPhone真机。
- 当前新增模型调用0、已知费用0/100、真实报告/封面0、新UNKNOWN0；无生产迁移/配置/发布。剩余：字体/image/隔离API+真实存储+正常auth与组合guard最终绑定→必要时只在具体已备妥的60分钟受鉴权测试入口方案上取得当次开放确认→本窗唯一派发九图新报告和同报告封面→前后端/成品/费用/独审收据。恢复只读本节及原窗口后继、PLAN、当前HEAD；不重放旧模型/支付/Amap/历史任务。


### A05 构建与实际组合差异 — 北京2026-10-20 07:24；原窗口追加后立即释放

- 固定字体已通过原API-C Workbench普通私有文件上传成功（仅非敏感官方字体，原大小16963428B/SHA df2b90…不变），存于/home/ecs-user/noteai-cover-transfer-20261020-r1/；沿既有临时中转，不创建新桶/凭据/公开ACL。Enew/font-workbench-upload.png及后继host SHA核验留证。此前两次TLS失败保留，不重下载。
- c-sz070k0hswoolc0/t-sz070k0hsx3nzeo明确Failed/Exit1/Dropped0：Docker到step5，旧SHA断言model/admin.html失败；原build-started 5a2b4f…、1298B构建log6d470a31514651bc034117b309404da79fe9a433016a66509fbec4ecf664e0bd保留。没有新image/运行API/业务写/付费请求。不是字体/模型故障。
- 已一次只读核全部18目标c-sz070k0pwirfzsw/t-sz070k0pwj6fdvk，S0D0：仅model/admin.html实际7e18763…、model/admin_server.py实际66eafb87…不等于f3e Git旧叶子；其余16全部匹配旧SHA或按预期新文件absent。精确原件Enew/api-base-composition-readonly-output.json。正式3711/9be/PID2779792/restart0仍running、include仍absent。此证实组合基线不能把f3e HEAD当整镜像。
- 最小API-only r2方案已准备（未派）：仅从delta排除上述两个Admin文件，保留其原镜像内容；16API增量与e623 Seedream、固定字体完整保留，独立build-api-only-r2目录/marker/log，原失败不删不改。delta47726B/SHA60acf46a9ecab1a2413aa5e999288dddd440ad8698e3854357ac4a705b816bb3，命令8987B/SHA3563beae55038af33edc465e3d247cc945cc956e4c45c2bceba475361f8e6d73，正在窄独审。不能据此宣称Admin封面候选已部署/验收，Admin改动仍须后续对应独立集成。
- 脱敏实际运行配置：正式backend=aliyun_oss，原私有桶noteai-private-prod-20260729-c60cc608、深圳内网HTTPS endpoint、原RAM role、prefix noteai-private；Ark配置身份SHA16=35813f100f5af799（不输出Key）。这些仅是实际profile/身份事实，不证明OSS当前写入或Key项目权限。已知OSS控制台欠费仍需先验证真实9图普通上传及存储；不能直接签成已可用proof、更不能先派模型。火山余额与阿里OSS分开记录，不混淆。
- runtime helper最终a7e36f78bd71f31ff14fec33a278a3bea542be1cf89e8b349fb445083f3a644b，桥逐字abdc5bc6…；6离线准入测试和独立源码ID/路由/auth/启动顺序窄审通过，无产品改动。17leaf源pin、实际PG/ACL/会话/存储、Gateway新签名metadata、有限prepseal仍待真正启动核验。30测guard eb26a9…冻结未变；主窗口不需重跑全项目。


### Q06 / 实际Ark Key项目绑定原件（原窗口追加，07:26北京）

当前实际Ark Key仅取得不可逆身份SHA16=35813f100f5af799，原API与新隔离将用同一原RAM/env安全渠道，不读取/输出Key。现有代码没有KeyID/ProjectID自省字段，源码共用NOTEAI_ARK_API_KEY只能证实配置一致，不能证明属于已登录Ark控制台的哪一个项目。请封面窗口核已有配置渠道是否有Key对象ID/secret版本→账号/项目的脱敏映射原件；若没有，请在当前已登录账号只读核可对应的Key元数据与原件，不建Key/扩大权限/发付费探针。guard的runtime_key_project_binding_verified必须有依据，暂未填true。此问题通过本文件直接交换，不要求用户逐项转述。根继续不依赖该证明的镜像/隔离准备，不等待答复才工作。

r2构建尚未派；窄审检出两项辅助脚本确定性阻断已在本地修正：host重压gzip不跨版本固定压缩字节SHA，改钉193542B规范JSON708b1b…；派生apply仅改payload身份门为该规范JSON SHA，保留所有old/new逐文件门。16项临时Git原件重建全SHA通过。新命令9095B/SHAa0916f8d692fb2eb5be3086f194d81b229e5a69325a2a356cb43bdad69170a8e；helper1efa23a3…；源14382B/892e71ff…，待末次窄复核，不将准备脚本误写已执行。


### A06 / 已得实际隔离API镜像 — 北京2026-10-20 07:29；原窗口追加后立即释放

- 唯一API-only r2 c-sz070k13y1b6nls/t-sz070k13y1v5udc原身份读回Success/Exit0/Dropped0，实际镜像sha256:05978bee01588bcc1b4bd0cb74660eadd3a19b97dadfdc9cec8d1a76d08bf6cc，tag noteai-cover-api-e6234e7-api-only-20261020-r2。Enew/build-api-only-r2-{run-original,read-original,output}.json留原件，host结果/日志独立build-api-only-r2-*.json/log。
- API产品e623、其余API叶子919；18源/SQL/原Ark与router校验点全部PASS，manifestSHA76d690f9a287566a4218ebac92d30fccbaeb99fa61f157d6d4a6a15ba1081496；Seedream模块3200d675…、字体df2b90…、FreeType与“水石清池·汤泉生活”中文文字验证PASS。**仅API镜像**：原9be Admin HTML/server两个叶子保留，不声称新Admin已装载或验收。
- r2最终源码15845B/SHA7d54325e6f818c359b6b14a8dd6eff6b817d1dd041eeb6b1352d4cae3e4d0779；命令10311B/SHA5e4ff038b1113eda2d11a83ad2f3584190d3b1126f4593632462fd6076a83049；规范JSON708b1b…，host实际gzipSHA2ee67a65…（与macOS压缩字节不同属已解释版本差异），逐文件old/new门没有放宽。此前本地窄审检出的压缩门、helper旧门和生成literal缺陷均在dispatch前修正并重建16源/独审，不曾拿未核脚本反复派云。
- 正式3711/9be/PID2779792/restart0前后严格相等。此步API_launched=false、DBwrites0、provider0、publicentry=false；不是业务验收、不是发布。下一步仅在原隔离PG装精确featureSQL并启动此镜像的HOLD runtime（默认只readiness/upload、所有模型wire关闭）；先证实际存储/Key项目/Gateway，再由封面窗口唯一发真实请求。Q06仍待原件答复，OSS当前写可用尚未证实。


### A06 后继 / 原隔离业务PG已装载feature SQL（非生产）

唯一c-sz070k1azltmbcw/t-sz070k1azm140e8原身份Success/Exit0/Dropped0，Enew/install-feature-sql-isolated-{run-original,read-original,output}.json保存全文原件。完整8839B/bd6626 SQL的原BEGIN…COMMIT一次在原Unix socket、noteai_admin、精确原isolated业务库执行；三个新表为空、两新预算reserved0、app权限精确、封面配置absent/default disabled。schema_migrations仍31且manifest不变，旧50元budget整行前后相同。没有全量migrator、0032–0041、生产DB连接、role/HBA调整、旧Admin额外权限补写、业务报告/积分/模型调用。此前89项真实PG回滚fixture证据仍复用，本次是实际业务测试库装载，非89项重跑、非生产迁移验收。

guard最终30测eb26a9…与runtime a7e36f78…已冻结。本轮辅助包仅八个白名单源码/静态HOLD输入，61014B/SHA4414b352fd42bdbdbf7ba8ec3bef003ef321e743513626e568c106e271cf0374，已由原Workbench传到本次专用目录；不含.env/DSN/Token/Key/seal/proof。当前正在原身份stage+镜像内artifact check_only；暂未启动API、更未开放入口/派模型。实际字体和helper传输已解决，不再以TLS下载或字体作为阻塞；待核仍是正常runtime/会话/实际OSS可用及Q06 Key项目对应。


### Q07 / 90天对象保存契约（非本次分钟级验收前置；待原窗口只读答复）

- 问题：`model/private_storage.py`对cover_final/base/revision写90天元数据并按owner/TTL读，现有OSS实际Bucket/前缀生命周期是否有更短的统一清理规则？应用JSON/DB到期90天不独立证明供应商对象能保留90天。请复用现成真实存储profile/生命周期收据；如无，仅只读核所用前缀规则，不新增资源或改生产配置。
- 相关：`cover_service._store_image`→`private_storage.store_media_bytes(lifecycle="cover_v1")/load_media_bytes`、`cover_jobs`资产到期及免费调整保留原expires；本轮隔离namespace与生产namespace需分别陈述。建议明确无提前于90天的Bucket规则，或最终统一集成时最窄申请封面前缀所需配置，不能默许延长所有原图。
- 负责人：原窗口答现有云存储事实；本窗维护封面源码与收据。状态PENDING；代码合同与离线到期/权限证据已存在，不重做。阻塞范围仅“生产90天存储就绪”结论，**不将其扩为本次短时真实九图/封面验证的新启动门槛**；若实际上传/保存拒绝则按真实错误停止付费链。下一步等原profile可复用答复，结果未知如实列入交付。
