# NoteAI 真实链路质量稳定化执行计划

更新时间：2026-06-28

目标：把 V0.4 composite 模型、事实源、多 agent、AI 诊断、爆文生成和对话优化串成稳定可交付链路。判断标准不是“模型能打分”，而是真实用户输入后能持续产出有价值、自然、可信、愿意付费的内容。

## 当前基线

- V0.4 composite 已通过生产训练门禁，API 默认接入 V0.4 主评分链路；v0.3 仅保留为 fallback/历史对照。
- Golden 当前为 `6694`，Preference 当前为 `24850`；第一批核心行业均达到当前生产接受线。
- Round13 已完成多候选择优：`/generate` 与 `/generate/stream` 已接入候选池、V0.4 选择器和 `selection_meta`。
- Round14 已完成旅行/家居/穿搭专项：真实探针 `12/12 ready`，失败 `0`，blocking `0`，均分 `73.718`；家居标题补修探针 `4/4 ready`，标题可读性问题 `0`。
- RQS-05/RQS-06 已完成 AI 诊断三入口与对话优化回归：v36 覆盖 6 个核心行业，直接生成 `36/36 ready`、二修/chat `12/12 ready`、全量 post-sanitize 标题问题 `0`。
- RQS-07 已完成真实链路 shadow/E2E 总验收：当前 v36 验收集 `48/48 ready`、失败 `0`、blocking `0`、标题可读性问题 `0`、总验收 gate `PASS`；报告见 `docs/RQS07_REAL_CHAIN_ACCEPTANCE_REPORT.md`。
- RQS-08 已完成上线前 CI/PR/部署核验：新增生产 readiness gate，当前 `42/42` 检查通过；GitHub main 分支保护、secret scanning、push protection、Dependabot security updates、production Secrets/Variables 均已核验。
- 母婴行业按用户要求冻结，不再继续专项 prompt、规则、特征或后处理优化；只保留现有安全边界和回归测试。

## 执行纪律

- 每个任务必须有编号、状态、验收标准、验证证据和完成备注。
- 完成一项只更新对应任务状态，不把未完成项写成完成。
- `<60` 或灾难性空稿/格式错误硬拦；`60+` 轻修问题不硬拦，进入二修或对话优化。
- 事实源策略保持：餐饮/本地生活使用高德基础事实源；酒旅/旅行使用美团 `meituan-travel`；事实只能自然融入，不能形成机械信息块。
- 不为追分强塞规则。V0.4 62/124 维特征用于生成前规划、候选择优和解释二修，不把所有特征硬塞进正文。
- 所有真实链路验证必须记录失败数、blocking 数、标题可读性、分数分布、典型问题和 artifact 路径。

## 状态说明

- `[待处理]` 尚未开始。
- `[进行中]` 正在执行，尚未完成验收。
- `[已完成]` 已完成代码/文档/验证，并记录证据。
- `[需复测]` 已完成初修，但需要真实 API、真实素材或 E2E 再验证。
- `[冻结]` 用户明确要求暂不继续优化。

## 当前任务清单

| 编号 | 状态 | 任务 | 验收标准 | 完成备注 |
|---|---|---|---|---|
| RQS-00 | [已完成] | 固化本执行计划，并同步训练计划/交付台账口径 | 新增独立计划文档；旧 `blocked_need_labels` 口径改为当前 V0.4 production 状态；交付台账能指向本计划 | 2026-06-28 已完成：新增本计划；同步 `docs/V04_TRAINING_EXECUTION_PLAN.md` 顶部状态为 `production_training`；在 `DELIVERY_FIX_TRACKER.md` 登记 RQS 计划入口 |
| RQS-01 | [已完成] | 美食/高德事实源生成专项 | 高德事实自然融入；无“实用信息/地址/营业时间”机械块；真实探针失败 `0`、blocking `0`、标题问题 `0`；均分目标 `>=72`，低于 72 样本能给出明确可修原因 | 2026-06-28 已完成：高德事实自然句、标题断尾修复、套餐菜品事实一致性、重复事实句去重已接入。真实探针 v18 `24/24 ready`、失败 `0`、blocking `0`、均分 `73.564`、中位 `72.790`；post-sanitize 标题问题 `0`，事实边界/假菜名/信息栏污染 `0`。剩余风险：长禧家/点都德个别单候选 `68-71`，不硬拦，进入 RQS-05/RQS-06 的多候选选择优与对话优化兜底 |
| RQS-02 | [已完成] | 美妆生成专项 | 肤质/场景/成分/使用感表达自然；无无依据功效承诺；真实探针失败 `0`、blocking `0`；均分目标 `>=72` | 2026-06-28 已完成：美妆 brief/agent 方向按彩妆/唇妆 vs 防晒/底妆分流；补充价格/渠道自然写入、未提供试用周期/敏感反应/全天持妆清洗、标题半截和未提供经历标题修复。真实探针 v23 focus `18/18 ready`、失败 `0`、blocking `0`、post-sanitize 标题/事实边界问题 `0`、均分 `72.803`、中位 `72.661`、任务组最佳 `73.055/78.150/73.742`；Round12 商业槽位补测 `4/4 ready`、失败 `0`、post-sanitize 问题 `0`、均分 `72.615`、最佳 `75.284`。剩余风险：唇妆单候选最低 `67.603`，不硬拦，必须由多候选择优/对话优化继续兜底 |
| RQS-03 | [已完成] | 旅行/酒旅稳定性二轮 | 美团事实在前 120 字自然保留起价/评分/交通/权益等至少 3 项；扩大样本后失败 `0`、blocking `0`；均分目标 `>=72` | 2026-06-28 已完成：单酒店美团事实前置/嵌入、价格格式归一、标题 fallback、重复事实句去重、无依据价格/门票/旺季/延迟退房/儿童年龄/提前几周等清洗、多酒店早餐重复压缩已接入。真实链路 v30 `4/4 ready`、失败 `0`、blocking `0`、均分 `79.303`；latest post-clean v30 均分 `80.877`、bad_terms `0`；30 条酒旅大样本回归 `30/30 >=72`、均分 `73.446`、issues `0` |
| RQS-04 | [已完成] | 健身多场景真实验证 | 覆盖减脂、塑形、低冲击、办公室、器械/无器械、膝盖敏感等任务；动作覆盖不丢失；失败 `0`、blocking `0`；均分目标 `>=73` | 2026-06-28 已完成：新增健身场景化 brief，覆盖膝盖友好低冲击、办公室肩颈放松、弹力带臀腿塑形；补充动作事实槽位，清洗无来源周期/效果/医学化承诺，修复“新手3周/适合新”等标题半截。真实链路 v33 覆盖 3 个任务、18 个候选，`18/18 ready`、失败 `0`、blocking `0`、min `72.278`、mean `74.026`、median `73.519`、max `77.039`；post-clean mean `73.947`、`ge72=18/18`、issues `0`、bad `0`、body_gt480 `0`。剩余风险：个别单候选仍为 `72.x`，不硬拦，进入多候选择优/对话优化兜底 |
| RQS-05 | [已完成] | AI 诊断三入口回归 | 截图上传、手动上传、视频上传均走统一 V0.4 agent/事实源/历史偏好链路；三标题对应三篇不同正文；无空响应、无共享正文冒充成功 | 2026-06-28 已完成：新增后端合同测试，验证手动、图片/截图、视频三入口都会进入同一 `/analyze` V0.4 五 agent 链路，并把高德/美团事实源、长期偏好、图片描述、视频理解上下文传入 agent；三方案正文保持独立，不再共享正文冒充成功。v36 直接探针覆盖美食/旅行/穿搭/美妆/家居/健身共 `36/36 ready`、失败 `0`、blocking `0`、mean `73.642`、median `73.590`、min `67.276`、`32/36 >=72`、`36/36 >=60` |
| RQS-06 | [已完成] | 对话优化链路回归 | 60+ 不硬拦；用户提出“更自然/更短/更种草/更真实”等反馈后，改写不劣化且能记录偏好 | 2026-06-28 已完成：chat 增加分数回退安全阀，若改写比当前版本低超过 `2.0` 分或触发硬问题，自动回退并复核上一版标题/正文；离线 dependent 槽位同步修复 blocking 状态和 fallback 复核。v36 二修/chat 探针 `12/12 ready`、失败 `0`、blocking `0`、mean `76.211`、median `75.716`、min `73.357`、`12/12 >=72`。v36 全量 `48` 个 artifact post-sanitize 审计：blocking `0`、标题可读性问题 `0`、mean `74.284`、median `74.068`、min `67.276`、`44/48 >=72`、`48/48 >=60` |
| RQS-07 | [已完成] | 真实链路 shadow/E2E 总验收 | 覆盖 AI 诊断、生成、对话优化、事实源、候选择优；输出总报告，列明各行业分数、失败、blocking、剩余风险 | 2026-06-28 已完成：新增 `tools/real_chain_acceptance_report.py` 与报告 `docs/RQS07_REAL_CHAIN_ACCEPTANCE_REPORT.md`。当前 v36 验收集 `48/48 ready`、失败 `0`、blocking `0`、低于 60 分 `0`、标题可读性问题 `0`、mean `74.284`、median `74.068`、min `67.276`、`44/48 >=72`；覆盖美食/旅行/穿搭/美妆/家居/健身，每行业 8 条，AI 诊断三方案正文均保持独立。latest shadow QA 当前 v36 集合 `48/48` shadow ready、hard block `0`、avg V0.4 `73.804`、`39/48 >=72`。历史旧生成样本仍有 `15` 个 hard block，主要是旧产物结构化事实边界问题，已作为审计残留记录，不计入当前 v36 上线 gate |
| RQS-08 | [已完成] | 上线前 CI/PR/部署核验 | 单测、质量门禁、核心真实探针、GitHub CI 和部署配置均通过；无 secrets、无大数据误提交 | 2026-06-29 已完成：新增 `tools/production_readiness_gate.py`，本地生产 gate `42/42` 通过；CI 已接入生产 gate，并在 `main`、`codex/**` push 和 PR to `main` 运行；Docker 增加 `/app/scripts/docker_entrypoint.sh`，API/admin 容器启动前会校验/下载 V0.4 模型 artifact，生产 `NOTEAI_MODEL_ARTIFACT_REQUIRED=1` 时不允许模型缺失静默降级；GitHub main 分支保护、required `test`、strict、PR、linear history、admin enforcement、no force push/delete、conversation resolution 已核验；secret scanning、push protection、Dependabot security updates 已开启；production Secrets/Variables 名称已核验，无 secret 值进入仓库。报告见 `docs/RQS08_PRODUCTION_READINESS_REPORT.md` |

## 最近完成记录

- 2026-06-28 RQS-00：真实链路质量稳定化计划已固化，训练计划和交付台账口径已同步；后续按 RQS 编号推进并逐项备注完成状态。
- 2026-06-28 RQS-01：美食/高德事实源生成专项完成。修复“实用信息/地址：/营业时间：”机械块、长禧家点心拼盘擅自扩写虾饺/烧卖、同一组地址人均营业事实重复、餐饮标题多类半截尾巴；`quality/generated_variants/v16_food_amap_single_after_dish_fact_fix` 单店 `4/4 ready`、均分 `73.971`；`quality/generated_variants/v18_food_amap_final_title_clean` 多店 `24/24 ready`、失败 `0`、blocking `0`、均分 `73.564`、中位 `72.790`、post-sanitize 标题问题 `0`、事实污染 `0`。
- 2026-06-28 RQS-02：美妆生成专项完成。修复护肤/防晒模板套唇妆、无依据试用周期/敏感反应/全天持妆承诺、价格渠道缺失、标题“6小时不/上粉底不/69元玫瑰/我能涂一年”等半截或未提供经历问题；v23 focus `18/18 ready`、失败 `0`、blocking `0`、post-sanitize 问题 `0`、均分 `72.803`；Round12 商业槽位 `4/4 ready`、均分 `72.615`。
- 2026-06-28 RQS-03：旅行/酒旅稳定性二轮完成。修复单酒店标题冷/半截、正文未在前 120 字保留美团事实、`￥929起/晚` 表达不统一、重复事实句、无依据“首选/直接省门票钱/多玩半天/提前几周/旺季满房/延迟退房”等风险表达；真实链路 `quality/generated_variants/v30_travel_v12_stability` 为 `4/4 ready`、失败 `0`、blocking `0`、均分 `79.303`，latest post-clean 均分 `80.877`、最低 `79.015`、bad_terms `0`；30 条酒旅大样本回归 `30/30 >=72`、均分 `73.446`、最低 `72.353`、issues `0`。
- 2026-06-28 RQS-04：健身多场景真实验证完成。新增场景化生成 brief：膝盖友好低冲击聚焦 `18分钟/4个动作/3轮`，办公室肩颈聚焦 `8分钟/一面墙/椅子/肩胛后缩/靠墙天使`，弹力带臀腿聚焦 `弹力带/臀腿/发力感/3组`；清洗未提供的 `坚持一周明显缓解`、`第二天酸痛减少`、`颈椎病变/神经压迫`、`血液循环恢复正常` 等承诺或医学化表达。真实链路 `quality/generated_variants/v33_fitness_rqs04_scene_brief` 为 `18/18 ready`、失败 `0`、blocking `0`、min `72.278`、mean `74.026`、median `73.519`、max `77.039`；post-clean issues `0`、bad `0`、`ge72=18/18`。
- 2026-06-28 Round13：多候选择优接入完成，修复 ranker 过权重风险，真实小批覆盖美食/旅行/美妆/健身/穿搭/家居并全部跑通。
- 2026-06-28 Round14：旅行/家居/穿搭专项完成，穿搭夸张身材承诺清洗、家居标题断尾修复、旅行酒店事实密度软信号已接入。
- 2026-06-28 RQS-05/RQS-06：AI 诊断三入口与对话优化回归完成。修复点：低于 60 的 artifact 不再被标为 ready；chat 改写低于当前版本超过 `2.0` 分自动回退并复核；dependent fallback 不再带回旧半截标题；新增标题断尾修复覆盖 `排队20/衬衫开/显气色还/不显毛/终于走路/每晚2/执行指/动作20/1200元这样` 等真实探针问题；旅行普通攻略不再误触酒店事实密度规则。验证证据：`quality/generated_variants/v36_rqs05_06_regression/run_report_20260628T151411Z.json` 为 `36/36 ready`、失败 `0`、blocking `0`、mean `73.642`、min `67.276`；`run_report_20260628T152141Z.json` 为 `12/12 ready`、失败 `0`、blocking `0`、mean `76.211`、min `73.357`；全量 post-sanitize `48` 条标题问题 `0`、blocking `0`。
- 2026-06-28 RQS-07：真实链路 shadow/E2E 总验收完成。新增可重复执行的验收报告工具，汇总 AI 诊断、生成、对话优化、事实源、候选择优产物；当前 v36 总验收 gate `PASS`，`48/48 ready`、失败 `0`、blocking `0`、低于 60 分 `0`、标题可读性问题 `0`、mean `74.284`、median `74.068`、min `67.276`、`44/48 >=72`。latest shadow QA 对当前 v36 集合为 `48/48` shadow ready、hard block `0`、avg V0.4 `73.804`、`39/48 >=72`；全历史旧 artifact 仍有 `15` 个 hard block，已列入 `docs/RQS07_REAL_CHAIN_ACCEPTANCE_REPORT.md` 的审计残留，不作为当前上线 gate。
- 2026-06-29 RQS-08：上线前 CI/PR/部署核验完成。新增生产 readiness gate 覆盖模型 artifact、registry/manifest、训练报告、RQS-07 报告、CI、Docker、部署文档、Git hygiene 和明显 secret 值扫描；当前 `42/42` 通过。Docker 入口脚本已保证 API/admin 启动前先执行模型 artifact 校验/下载；GitHub 远端核验 main 分支保护和 security settings 均符合当前上线治理要求。剩余非本轮风险：正式付费公开上线仍需要支付订单、回调验签、对账、订阅权益激活和生产监控。

## 下一步执行顺序

1. 进入正式部署前产品闭环：支付/订阅、生产域名、线上监控与灰度发布。
