# v0.4-composite 训练策略

执行总计划见：`docs/V04_TRAINING_EXECUTION_PLAN.md`。后续所有训练推进必须同步更新该计划和交付台账。

## 决策

v0.3 只保留为历史遥测和审计对照，不再作为生成目标、辅助模型或硬拦截依据。

v0.4 的目标不是复刻 v0.3 分数，而是训练一个复合质量模型：

- 人工 golden 标签：是否可交付、人工质量分、自然度、事实状态、AI 味、失败标签。
- A/B 偏好标签：同任务下哪个标题/正文更值得交付，为什么赢。
- 事实可信：结构化事实是否来自用户输入或可信事实源。
- 自然表达：是否像真实创作者，而不是关键词拼接。
- 行业价值：每个行业有自己的决策信息和表达结构。

## 训练形态

第一阶段：`v0.4-composite-ranker`

- 目标：学习同任务候选之间谁更好。
- 数据：A/B preference pairs。
- 用途：选择三方案、chat 优化候选、二修候选。
- 评估：pairwise accuracy、按行业 accuracy、score-hacking 负例召回。

第二阶段：`v0.4-composite-regressor`

- 目标：预测人工质量分和交付就绪概率。
- 数据：golden labels。
- 输出：`human_quality_score_pred`、`delivery_ready_prob`、`ai_smell_risk`。
- 评估：MAE、Spearman、ready/not-ready AUC、行业校准误差。

第三阶段：`v0.4-composite-arbiter`

- 目标：融合 ranker、regressor、事实完整度、自然度风险和行业规则。
- 用途：生产质量门禁、候选排序、对话优化建议。
- 规则：事实编造、空内容、标题不自然等仍为硬门禁；模型只做质量判断，不覆盖事实安全。

## 特征

保留现有 62 维作为可解释特征，但只作为输入，不作为训练目标。

新增特征必须覆盖：

- 标题自然度：断词、拼接、价格+推荐词异常、可读性。
- 正文实用密度：价格/地址/营业/步骤/清单/适合人群/避坑/CTA 的品类化覆盖。
- 事实源完整度：高德/美团酒旅/用户输入字段的覆盖率和置信度。
- AI 味和模板感：自然度模型分、重复模板句、泛化爆词密度。
- 行业适配：美食、旅行、穿搭、美妆、家居、健身、母婴分别建校准统计。

行业口径冻结：

- 第一批核心行业只覆盖：美食、旅行、穿搭、美妆、家居、健身、母婴。
- RedNote 研究数据中的“运动”属于产品交付里的“健身”，进入 v0.4-composite 的标注、训练、健康审计和 readiness 时必须统一映射到“健身”。
- 不再把旧 RedNote 归一化结果当作产品行业标准；产品行业以 `model/v04_domain_policy.py` 为准。

## 上线门槛

Candidate 灰度最低门槛：

- 每个核心行业至少 300 条人工 golden。
- 每个核心行业至少 1000 组已标注 A/B 偏好。
- golden 上不能出现“模型高分但人工明显不可交付”的高危误判。
- v0.3 false negative 行业样本不得被新模型继续压错。

Production 最低门槛：

- 每个核心行业至少 1000 条人工 golden。
- 每个核心行业至少 3000 组已标注 A/B 偏好。
- 每个行业单独出校准报告。
- 真实 AI 诊断和爆文生成样本通过人工验收。

推荐上线目标：

- 每个核心行业 2000 条人工 golden。
- 每个核心行业 5000+ 组 A/B 偏好。
- 持续接入线上“用户采纳/复制/继续优化/删除”反馈。

## 当前状态

截至 2026-06-25：

- v0.4 去重训练管线已建立，但第一版 candidate 不能上线。
- 自然度模型可做风险信号，不能做硬门禁。
- golden/偏好工程已建立，但人工标签量远未达到训练强模型门槛。
- 旧 v0.3 已从生成目标和硬拦截中撤出，只保留遥测。

运行就绪检查：

```bash
.venv/bin/python tools/v04_composite_readiness.py --json
```

## 2026-06-25 工程落地 v0.1

已新增 v0.4-composite 训练工程入口：

- `model/v04_composite_features.py`：124 维复合特征。包含原 v0.4 的 62 维输入信号，以及标题自然度、正文信息密度、CTA、模板风险、自然度模型信号、各行业事实槽位覆盖。
- `model/v04_composite_dataset.py`：从人工 golden 和同任务 A/B 偏好构建训练数据，输出 `model/data/v04_composite/`；明确排除 raw 队列中的旧评分字段，不允许作为训练特征或目标。
- `model/train_v04_composite.py`：训练守门脚本。默认在标签不足时只写阻断报告；只有显式 `--allow-experimental-small-data` 才会生成实验 artifact，且报告固定 `do_not_deploy=true`。

当前真实输出：

- golden rows：11。
- labeled preference pairs：3。
- single feature count：124。
- readiness：`blocked_need_labels`。
- experimental report：`model/artifacts/model_v04_composite_train_report.json`，状态 `experimental_not_production`。

重要结论：

- 当前只能验证训练链路，不能称为商业级模型。
- preference ranker 暂未训练，因为 3 个锁定偏好全是 B 胜，类别不平衡。
- legacy score-directed 样本只作为负例保留，origin 已改为 `legacy_score_directed_second_pass`。

## 2026-06-25 标注生产线 v0.1

新增标注生产线工具：

- `tools/export_labeling_batch.py`：从 golden / preference 队列导出小批人工标注文件。
- `tools/ingest_golden_annotations.py`：校验并合并已完成人工 golden，默认输出 `quality/golden_labels.v01.merged.json`。
- `tools/ingest_preference_annotations.py`：校验并导出已完成 A/B 偏好，默认输出 `quality/preference_queue.v01.labeled.jsonl`。
- `tools/v04_training_data_health.py`：训练前健康审计，检查行业覆盖、候选/生产缺口、重复文本、delivery/pairwise 类别平衡。

当前第一批人工标注包：

- `quality/labeling_batches/v04_round01_golden.csv`：160 条，覆盖美食/旅行/穿搭/健身各 40 条高优先级样本。
- `quality/labeling_batches/v04_round01b_golden.csv`：120 条，覆盖美妆/家居/母婴各 40 条高优先级补样候选。
- `quality/labeling_batches/v04_round01_preference.csv`：63 组，美食长禧家同任务 A/B 偏好待标注。
- `quality/labeling_batches/v04_round01b_preference.csv`：105 组，覆盖 7 个核心行业各 15 组同任务 A/B 偏好待标注。

当前显性缺口：

- 美妆、家居、母婴已通过 `tools/export_core_domain_supplement_queue.py` 从原始真实笔记中挖出补样候选：美妆可用候选 1283、家居 329、母婴 1782；当前各选 120 条进入补样队列，其中各 40 条进入 Round01B。
- preference 已通过真实生成 artifact 组装第一轮多行业队列：7 个核心行业各 6 个候选、15 组 A/B，共 105 组待人工标注。
- 这些批次仍是“待人工标签”，训练数据不会增加，直到标注完成并通过 ingest 校验。
- 核心行业缺口报告已固化到 `model/artifacts/v04_core_domain_gap_report.json`。

标准命令：

```bash
.venv/bin/python tools/export_labeling_batch.py --kind golden --batch-id v04_round01 --max-rows 280 --per-domain 40 --domains '美食,旅行,穿搭,美妆,家居,健身,母婴'
.venv/bin/python tools/export_core_domain_supplement_queue.py --per-domain 120 --domains '美妆,家居,母婴'
.venv/bin/python tools/export_labeling_batch.py --kind golden --queue quality/annotation_queue.v01.core_supplement.jsonl --batch-id v04_round01b --max-rows 120 --per-domain 40 --domains '美妆,家居,母婴'
.venv/bin/python tools/export_labeling_batch.py --kind preference --batch-id v04_round01 --max-rows 100
.venv/bin/python tools/fill_preference_generation_slots.py --routes analyze,generate,offline_candidate
.venv/bin/python tools/build_preference_seed_from_generated_artifacts.py --include-blocking
.venv/bin/python tools/export_preference_annotation_queue.py --seed quality/preference_pairs.v01.generated_from_artifacts.json --output-jsonl quality/preference_queue.v01.generated.jsonl --output-csv quality/preference_queue.v01.generated.csv --report quality/preference_queue.v01.generated.report.json
.venv/bin/python tools/export_labeling_batch.py --kind preference --queue quality/preference_queue.v01.generated.jsonl --batch-id v04_round01b --max-rows 105
.venv/bin/python tools/ingest_golden_annotations.py
.venv/bin/python tools/ingest_preference_annotations.py
.venv/bin/python tools/v04_training_data_health.py
.venv/bin/python tools/v04_core_domain_gap_report.py
```

## 2026-06-25 第一批核心行业执行结果

本轮已按用户确认仅处理第一批核心行业，完成以下工程收口：

- 新增 `model/v04_domain_policy.py`，冻结产品行业口径并将“运动/运动健身”映射为“健身”。
- `export_golden_annotation_queue`、`export_labeling_batch`、`ingest_golden_annotations`、`ingest_preference_annotations`、`v04_training_data_health`、`v04_composite_readiness`、`v04_composite_features` 均接入统一行业口径。
- 重建 `quality/annotation_queue.v01.jsonl`：总计 3820 条，其中 3809 条待标注、11 条 locked seed。
- 重导出 Round01 golden：美食/旅行/穿搭/健身各 40 条，共 160 条。
- 重导出 Round01 preference：美食 63 组。
- 训练数据构建结果仍为 golden 11 条、preference 3 组；`model/train_v04_composite.py` 正确输出 `blocked_need_labels` 和 `do_not_deploy=True`。
- 新增 `tools/v04_core_domain_gap_report.py`，输出 `model/artifacts/v04_core_domain_gap_report.json`，作为后续训练进度对照。

验证记录：

- `python3 -m py_compile model/v04_domain_policy.py model/v04_composite_features.py model/v04_composite_dataset.py model/train_v04_composite.py tools/export_golden_annotation_queue.py tools/export_labeling_batch.py tools/ingest_golden_annotations.py tools/ingest_preference_annotations.py tools/v04_training_data_health.py tools/v04_composite_readiness.py tools/v04_core_domain_gap_report.py`
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：78 项通过。
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`：通过。

## 2026-06-25 Round01B 补样与偏好队列

已完成第一批核心行业补样和多行业偏好队列扩展：

- `tools/export_core_domain_supplement_queue.py`：从 RedNote 原始真实笔记中挖掘缺失核心行业候选；扫描 143395 行，选出 360 条补样候选，美妆/家居/母婴各 120 条。
- `quality/labeling_batches/v04_round01b_golden.csv`：美妆/家居/母婴各 40 条，共 120 条高优先级人工 golden 标注包。
- `tools/fill_preference_generation_slots.py`：执行 32 个真实 Claude 直接槽位，全部 ready、无失败；总计 artifact 中 7 行业各 6 个候选，共 42 个候选可组装 A/B。
- `tools/build_preference_seed_from_generated_artifacts.py`：将 artifact 转为 `quality/preference_pairs.v01.generated_from_artifacts.json`。
- `quality/preference_queue.v01.generated.jsonl`：105 组待标注 A/B，7 个核心行业各 15 组。
- `quality/labeling_batches/v04_round01b_preference.csv`：105 组多行业偏好标注包。

生成候选暴露出的质量信号：

- 穿搭/家居候选整体较强，多数在 70+。
- 旅行有 72+ 候选，但部分方案因质量/事实边界仍 blocking。
- 美妆在 55-65 区间，表达和效果实测信号不足。
- 健身普遍 30-41，确认旧评分信号对健身仍有系统性偏差，必须作为 V0.4-composite 的专项校准行业。
- 母婴在 66-70 区间，安全边界较好但自然度和结构还需人工偏好校准。

本轮验证记录：

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：79 项通过。
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`：通过。
- `model/train_v04_composite.py` 仍输出 `blocked_need_labels`、`do_not_deploy=True`，因为 Round01/Round01B 尚未人工标注。

## 2026-06-25 AI 辅助标注流程

为解决“非专业人员不懂人工标注”的问题，新增 AI 预标注 + 审核提升流程：

- `tools/ai_prelabel_review_batch.py`：读取 golden / preference 标注包，生成 `quality/review_packets/*_ai_review.csv/jsonl/report.json`。
- `tools/promote_reviewed_prelabels.py`：只把 `review_decision=accept_ai`、`accept_with_edits` 或显式 `--auto-accept-consensus` 且 `judge_consensus=agree` 的行提升成正式 ingest-ready 标签。
- `quality/AI_ASSISTED_LABELING_PLAYBOOK.md`：给非技术用户使用的极简说明。

已生成审核包：

- `quality/review_packets/v04_round01_golden_ai_review.csv`：160 条，AI 建议后 146 条需复核、14 条可快速审核。
- `quality/review_packets/v04_round01b_golden_ai_review.csv`：120 条，AI 建议后 110 条需复核、10 条可快速审核。
- `quality/review_packets/v04_round01_preference_ai_review.csv`：63 条，AI 建议后 47 条需复核、16 条可快速审核。
- `quality/review_packets/v04_round01b_preference_ai_review.csv`：105 条，AI 建议后 94 条需复核、11 条可快速审核。

安全边界：

- AI 预标注不写入正式 `human_quality_score` / `winner` 等训练字段。
- 空 `review_decision` 的行提升结果为 0，已经用回归测试固定。
- AI 建议只能加速审核，不能伪装成原生人工标签；最终训练报告必须保留 `reviewer=owner_approved_ai_prelabeller` 或人工 reviewer 来源。
- Kimi 已作为第二评审接入；Kimi 与首审分歧时进入 holdout，`accept_ai` 不会被提升。
- `ai_rubric_consensus` 标签必须保留 `label_source`、`judge_consensus` 和分歧字段；不得伪装成人工标签。

2026-06-25 Kimi 共识执行结果：

- 四个批次共 448 条/组进入 Kimi 第二评审。
- 初次 Kimi 成功 438、失败 10；失败 10 条已用 JSON mode + 修复重试补跑成功。
- 双评审一致 76 条/组；golden 因空标题过滤后最终提升 34 条。
- 最终训练数据：golden 45 条（含 11 seed），preference 39 组，winner 分布 A=17 / B=22。
- 健康审计不再有 winner 单类问题，但仍为 `blocked_need_labels`；实验训练仅 `experimental_not_production`，`do_not_deploy=true`。

2026-06-25 Round02 focused preference 执行结果：

- 针对美妆、健身、母婴新增 focused preference 任务池：`quality/preference_task_pool.v02.focus.json`，共 9 个任务、54 个直接生成槽位。
- 真实候选生成 54/54 ready，失败 0；组装 `quality/preference_queue.v02.focus.jsonl` 共 135 组 A/B。
- 生成质量暴露两类问题：健身旧评分系统性偏低（18 个候选最高 48.794），以及部分标题压缩出现语义半截；已修复标题交付后处理并补充回归测试。
- Kimi 第二评审主批成功 134/135，失败 1 组因 429 过载重试成功。严格 `judge_consensus=agree` 只有 4 组，主要分歧来自 `delivery_ready_mismatch`，但 82 组 Kimi ok 样本的 A/B winner 与首审一致。
- 为 preference 新增显式 `winner consensus` 提升规则：只在 Claude/Kimi 同选 A/B winner、Kimi ok、无 winner_mismatch/second_review_failed/low_kimi_confidence 且 Kimi confidence ≥0.7 时提升；交付就绪采用 Kimi 保守值，`label_source=ai_rubric_winner_consensus`。该规则只用于训练偏好方向，不把样本伪装成完全共识或人工标签。
- Round02 新增 79 组可用 preference；合并 Round01 后当前 `quality/preference_queue.v01.labeled.jsonl` 为 118 组，按行业为：美食16、旅行5、穿搭7、美妆23、家居10、健身31、母婴26，winner 分布 A=50 / B=68。
- 默认训练仍 `blocked_need_labels`、`do_not_deploy=true`；实验训练可跑通但为 `experimental_not_production`。

2026-06-25 Round03 focused preference 执行结果：

- 针对美食、旅行、穿搭、家居新增 focused preference 任务池：`quality/preference_task_pool.v03.focus.json`，共 12 个任务、72 个直接生成槽位。
- 真实候选生成 72/72 ready，失败 0；组装 `quality/preference_queue.v03.focus.jsonl` 共 180 组 A/B。
- 生成质量暴露两类改进点：穿搭候选常缺价格/预算，旅行候选常缺交通/路线或预算信息；标题压缩半截问题跨行业复现，已扩展 `_repair_dangling_title_tail()` 和 `_title_readability_issues()` 回归测试。
- Kimi 第二评审成功 180/180，严格 `judge_consensus=agree` 28 组；采用显式 `winner consensus` 规则后，Round03 新增 86 组可用 preference。
- 合并 Round01/Round02/Round03 后，当前 `quality/preference_queue.v01.labeled.jsonl` 为 204 组，按行业为：美食30、旅行22、穿搭36、美妆23、家居36、健身31、母婴26，winner 分布 A=91 / B=113。
- 默认训练仍 `blocked_need_labels`、`do_not_deploy=true`；实验训练可跑通但为 `experimental_not_production`。

验证记录：

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：87 项通过。
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`：通过。
- `python3 -m py_compile tools/ai_prelabel_review_batch.py tools/promote_reviewed_prelabels.py tools/ingest_golden_annotations.py tools/ingest_preference_annotations.py tests/test_ai_prelabel_review_tools.py`：通过。

2026-06-25 Round04 focused golden 执行结果：

- 新增 `--exclude-ids-from` 到 `tools/export_labeling_batch.py`，导出下一批标注时可排除历史 batch、review packet、promoted 文件和 merged label 文件中的 `annotation_id/pair_id`，避免重复审同一批样本。
- 导出 Round04a golden：`quality/labeling_batches/v04_round04a_golden.jsonl`，美食/旅行/穿搭/健身各 40 条，共 160 条；Kimi 第二评审 160/160 ok，严格共识 40 条。
- 导出 Round04b golden：`quality/labeling_batches/v04_round04b_golden.jsonl`，美妆/家居/母婴各 40 条，共 120 条；Kimi 第二评审 120/120 ok，严格共识 20 条。
- Golden 晋级继续只允许 `judge_consensus=agree` 且无分歧标记；实际提升 48 条，其中 Round04a 31 条、Round04b 17 条，其余 232 条保留 holdout。
- 修复 `tools/promote_reviewed_prelabels.py` 把数值 `0` 清洗为空字符串的问题；低自然度/低质量负样本是回归器训练需要的合法标签，不能因 `0` 值被错误丢弃。
- 合并后 `quality/golden_labels.v01.merged.json` 为 93 条，按行业为：美食22、旅行13、穿搭15、美妆12、家居10、健身17、母婴4。
- Preference 保持 204 组，按行业为：美食30、旅行22、穿搭36、美妆23、家居36、健身31、母婴26，winner 分布 A=91 / B=113。
- 默认训练仍 `blocked_need_labels`、`do_not_deploy=true`；实验训练仍不可生产上线。当前瓶颈仍是每行业 golden 和 preference 数量远低于 candidate/production 门槛。

Round04 关键 artifact：

- `quality/review_packets/promoted/v04_round04_golden_summary.json`
- `quality/review_packets/v04_round04a_kimi_golden_ai_review.report.json`
- `quality/review_packets/v04_round04b_kimi_golden_ai_review.report.json`
- `quality/review_packets/promoted/v04_round04a_kimi_consensus_golden_promoted.report.json`
- `quality/review_packets/promoted/v04_round04b_kimi_consensus_golden_promoted.report.json`
- `quality/golden_labels.v01.merged.round04a.retry.report.json`
- `quality/golden_labels.v01.merged.round04b.report.json`

Round04 验证记录：

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：89 项通过。
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`：通过。
- `python3 -m py_compile model/api.py tools/export_labeling_batch.py tools/promote_reviewed_prelabels.py tools/ai_prelabel_review_batch.py tools/ingest_golden_annotations.py tools/ingest_preference_annotations.py tools/v04_training_data_health.py tools/v04_composite_readiness.py tools/v04_core_domain_gap_report.py model/train_v04_composite.py tests/test_labeling_pipeline_tools.py tests/test_ai_prelabel_review_tools.py`：通过。

2026-06-25 Round05 focused golden 执行结果：

- 扩大低覆盖行业补样池：`tools/export_core_domain_supplement_queue.py --per-domain 300` 导出 `quality/annotation_queue.v01.core_supplement.v02.jsonl/csv/report.json`，美妆/家居/母婴各 300 条；可用候选分别为美妆 1283、家居 329、母婴 1782，无 shortfall。
- 导出 Round05a golden：`quality/labeling_batches/v04_round05a_golden.jsonl`，美食/旅行/穿搭/健身各 40 条，共 160 条；Kimi 第二评审 160/160 ok，严格共识 41 条。
- 导出 Round05b golden：`quality/labeling_batches/v04_round05b_golden.jsonl`，美妆/家居/母婴各 60 条，共 180 条；Kimi 第二评审 180/180 ok，严格共识 15 条。
- Golden 晋级继续只允许 `judge_consensus=agree` 且无分歧标记；实际提升 52 条，其中 Round05a 39 条、Round05b 13 条，其余 288 条保留 holdout。
- 合并后 `quality/golden_labels.v01.merged.json` 为 145 条，按行业为：美食31、旅行17、穿搭33、美妆14、家居17、健身25、母婴8。
- Preference 保持 204 组，按行业为：美食30、旅行22、穿搭36、美妆23、家居36、健身31、母婴26。
- 更新 `tools/v04_core_domain_gap_report.py`，当 v02 补样报告存在时默认读取 v02，避免低覆盖行业队列容量仍显示旧的 120 条。
- 默认训练仍 `blocked_need_labels`、`do_not_deploy=true`；实验训练仍不可生产上线。当前最大短板：母婴 Golden 只有 8 条，低覆盖行业共识率明显低于主行业，需要继续专项抽样和可能的 rubric 校准。

Round05 关键 artifact：

- `quality/review_packets/promoted/v04_round05_golden_summary.json`
- `quality/annotation_queue.v01.core_supplement.v02.report.json`
- `quality/review_packets/v04_round05a_kimi_golden_ai_review.report.json`
- `quality/review_packets/v04_round05b_kimi_golden_ai_review.report.json`
- `quality/review_packets/promoted/v04_round05a_kimi_consensus_golden_promoted.report.json`
- `quality/review_packets/promoted/v04_round05b_kimi_consensus_golden_promoted.report.json`
- `quality/golden_labels.v01.merged.round05a.report.json`
- `quality/golden_labels.v01.merged.round05b.report.json`

Round05 验证记录：

- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：89 项通过。
- `.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json`：通过。
- `python3 -m py_compile model/api.py tools/export_core_domain_supplement_queue.py tools/export_labeling_batch.py tools/promote_reviewed_prelabels.py tools/ai_prelabel_review_batch.py tools/ingest_golden_annotations.py tools/ingest_preference_annotations.py tools/v04_training_data_health.py tools/v04_composite_readiness.py tools/v04_core_domain_gap_report.py model/train_v04_composite.py tests/test_labeling_pipeline_tools.py tests/test_ai_prelabel_review_tools.py`：通过。

2026-06-25 Round09 酒旅/旅行表达专项结果：

- 事实源策略按用户口径固化：餐饮/本地生活训练阶段不学习“未提供/不能编造”提示，真实链路由高德补结构化事实；酒店/旅行攻略使用美团 `meituan-travel` Skill 事实素材。
- 生成链路修复：旅行/酒店/住宿/酒旅别名统一；生成 brief 区分酒店对比和路线攻略；旅行安全事实策略禁止无依据最低价、最划算、必住、提前预订更便宜；Claude 非流式调用增加硬超时；Markdown 清理保留小红书 `#话题标签`；旅行标题断尾样例加入修复和测试。
- 真实候选重刷：`quality/generated_variants/v09_travel_expression_probe/` 共 `30` 个候选，`14` 篇 ≥72，`22` 篇 ≥70，`score<60=0`，`blocking=0`，Markdown/无依据价格承诺/标题断尾扫描均为 `0`。
- 偏好标注：重新导出 `75` 组旅行 A/B；Claude 主审 + Kimi 二审 `75/75 ok`，winner 一致 `23` 组；按 winner-consensus 且 Kimi confidence ≥`0.75` 安全晋级 `14` 组，其余 `61` 组 holdout。
- 标签合并：补回最早 `3` 条 locked seed 后，merged preference 当前 `272` 组；行业分布为美食 `73`、旅行 `47`、穿搭 `36`、美妆 `23`、家居 `36`、健身 `31`、母婴 `26`。Golden 当前 `157` 条。
- 训练结论：`tools/v04_training_data_health.py`、`tools/v04_composite_readiness.py`、`model/train_v04_composite.py` 均保持 `blocked_need_labels`，`candidate_ready=false`、`production_ready=false`、`do_not_deploy=true`。本轮只能作为高置信偏好样本补充，不能训练/部署生产模型。

Round09 关键 artifact：

- `quality/review_packets/promoted/v09_travel_expression_summary.json`
- `quality/preference_pairs.v09.travel_expression.generated_from_artifacts.report.json`
- `quality/preference_queue.v09.travel_expression.report.json`
- `quality/review_packets/v09_travel_expression_preference_ai_review.report.json`
- `quality/review_packets/promoted/v09_travel_expression_preference_promoted.report.json`
- `quality/preference_labels.v01.merged.round09_travel_expression.report.json`

Round09 验证记录：

- `find model tools tests -name '*.py' -print0 | xargs -0 python3 -m py_compile`：通过。
- `.venv/bin/python -m unittest discover -s tests -p 'test_*.py'`：104 项通过。
- `.venv/bin/python tools/quality_gate.py quality/quality_gate_cases.v04_round06_food_travel.json --json`：通过。
- `.venv/bin/python model/train_v04_composite.py --json`：正确阻断，`do_not_deploy=true`。

2026-06-28 真实链路质量稳定化 Round01：

- 当前生产模型以 `model/artifacts/model_v04_composite_train_report.json` 的 run `20260628T013926Z` 为准，训练报告 `deployment_gate.passed=true`、`training_policy.do_not_deploy=false`。后续重心从继续凑 Golden 转向真实链路稳定化：截图上传、手动上传、视频上传、爆文生成、流式生成和对话优化都必须稳定使用 V0.4 质量内核、事实源和多行业 brief。
- 同步训练健康工具口径：`tools/v04_training_data_health.py` 与 `tools/v04_composite_readiness.py` 的生产 Golden 默认线更新为当前接受线 `600/行业`；重建 `model/artifacts/v04_training_data_health.json` 与 `model/artifacts/v04_composite_readiness.json` 后均为 `production_ready`，各核心行业 gap 为 0，避免旧 `1000/行业` 报告误导项目进度。
- 扩展生成前 planning brief 的事实抽取：美食继续显式读取高德/本地核验事实，旅行/酒旅继续读取美团 travel/路线事实；穿搭新增身材/场合/单品/价格渠道，美妆新增肤质/产品色号/用量/妆效边界，家居新增空间/清单/预算/动线，健身新增动作/组数时长/目标/安全替代，母婴新增月龄/用品/步骤/观察安全。目标是让 Claude 在写作前读懂本行业真实素材，而不是只对餐饮高质量。
- 对话优化接入 V0.4 explainable lift：`_repair_chat_note_if_needed()` 现在会在 60+、无硬错误但事实密度/具体性/行业槽位/行动指导不足时触发分数导向二修，不再只等待显性 quality issue。
- 新增回归测试：多行业 planning brief 事实断言；chat 在无显性问题但 V0.4 可解释低分时触发二修。下一步继续扩大健身、穿搭、美妆、家居、餐饮/高德、酒旅/美团的真实生成探针，并复跑 shadow QA。

2026-06-28 Round01 后半段补充：

- 酒旅事实源解析升级：`meituan-travel` 真实输出存在卡片式和叙述式两种形态，已新增结构化解析与清洗，优先把酒店名、真实评分、起价、地址、入住/退房、亲子设施、交通权益、套餐权益送入生成链路；泛化解释话术、Markdown、Skill 前缀和“套餐浮动/我来帮你查”等不再进入 facts。
- 多行业生成策略升级：生成前 brief 新增“商业价值槽位”，让 Claude 在写作前明确每个行业真正影响用户付费感知的交付信息；二修链路同步加入旅行交通/预算、穿搭价格/渠道、美妆价格/渠道、家居预算/单品价、餐饮营业时间/必点等优先项；美妆、家居新增专属表达 brief。
- 真实事实源验证：高德餐饮链路复测长禧家珑厨万博广晟店可得地址、营业时间、人均、评分、招牌、套餐、电话、门店图，provider=`local_verified+amap`、confidence=`0.9`；美团酒旅链路复测广州长隆亲子酒店可得酒店评分/起价/设施/时间/权益，provider=`meituan_travel`、confidence 可达 `0.9`。
- 验证结果：全量单测 `145` 项通过，质量门禁通过，py_compile 通过，训练健康/readiness 均 `production_ready`；Shadow QA 当前 `362/362` ready、hard block `0`、平均 V0.4 `71.585`、`166` 条 `>=72`。剩余风险来自历史 artifact 的标题可读性、餐饮营业信号、旅行交通信号，后续需用新策略重刷真实生成探针验证增益。

2026-06-28 Round12 真实链路稳定性探针：

- 探针池：新增 `quality/preference_task_pool.v12.real_chain_stability.json`，覆盖美食/旅行/穿搭/美妆/家居/健身 6 个核心行业，每行业 4 个槽位，共 `24` 条真实生成；母婴按用户要求冻结。
- 真实生成结果：第二轮真实生成并刷新交付层后 `24/24 ready`，失败 `0`，blocking `0`，标题可读性问题 `0`；均分 `72.318`，中位数 `73.255`，`13/24` 达到 72+。
- 修复项：硬拦截语义收敛为 `<60` 或灾难性空稿/格式错误，60+ 进入二修/对话优化；酒旅价格 `￥929起/晚`、`929元/晚` 不再误判为编造；标题压缩修复 `929起的长`、`芝士焗小青龙必`、`遮胯搭`、`2600元让动线/做出顺`。
- 分行业稳定性：健身 `75.432` 且 `4/4` 72+，穿搭 `73.650`、家居 `72.506` 基本可用；美食 `70.529`、美妆 `70.900`、旅行 `70.891` 仍有单次 Claude 输出波动。
- Shadow QA：纳入 v12 后全量 `386/386` shadow ready、hard block `0`；v12 set `24/24` shadow ready、`13/24` 72+、平均 V0.4 `72.13`。
- 策略结论：事实源 + 行业 brief + V0.4 二修已能带来真实增益，但不能把单次 Claude 输出当生产确定性。下一阶段应建设候选择优器：同任务生成多候选，使用 V0.4 composite/ranker、事实安全、标题自然度和行业槽位选择最佳；低于 60 才硬拦，60+ 进入对话优化继续提升。

2026-06-28 Round13 多候选择优接入：

- API runtime 已加载 V0.4 三件套：composite regressor 继续负责交付评分，ready classifier 提供可发布概率，preference ranker 用于同任务候选偏好选择；v0.3 仍仅作为 fallback/历史对照，不参与生产选择目标。
- `/generate` 和 `/generate/stream` 均接入候选池：初始仲裁稿、按行业角度生成的挑战稿、P4 修复稿、score-directed 二修稿和最终压缩稿都会进入同一选择器；返回 `selection_meta`，记录 `candidate_count/viable_count/used_ranker/selected_origin/selected_score` 和候选摘要，便于线上审计。
- 选择策略：先按交付质量分层，`72+ 且无问题` 优先；若只有带问题的 72+ 候选，则允许 5 分内干净稿参与竞争；ranker 只在同层/近分候选中排序，不能把低分或缺核心槽位候选压过 72+ 干净稿；低于 60 或灾难性空稿/格式错误才硬拦。
- 真实链路小批探针：长禧家珑厨高德餐饮样本 `80.9`，地址识别修复后复评 `80.7` 且 issues=0；广州长隆酒旅 `70.3`；美妆防晒 `72.7`；健身低冲击训练 `75.5`；穿搭梨形通勤 `76.7`；家居阳台洗衣区首跑暴露 ranker 过权重，修复后复跑 `72.1`、issues=0。全部 `quality_failed=false`、无空响应、无 blocking、标题均 ≤18 字。
- 本轮新增测试覆盖：候选选择器 issue penalty、ranker 同分近分排序、72+ 干净候选优先级、地址识别误伤回归。验证：`.venv/bin/python -m unittest discover -s tests` 通过 `148` 项；`quality/golden_notes.sample.json` 与 `quality/quality_gate_cases.v04_round06_food_travel.json` 质量门禁通过；训练健康/readiness 仍为 `production_ready`。
- 剩余策略风险：旅行/酒旅仍有 `70.x` 波动，家居刚过 72，穿搭有“穿出165/多五厘米”这类轻夸张表达；下一轮应针对旅行/家居做候选方向和自然度专项，而不是提高硬拦线。

2026-06-28 Round14 旅行/家居/穿搭专项：

- 策略调整：旅行/酒旅候选方向从泛化“路线/权益”升级为“前120字做决策”，要求起价/评分/位置交通/设施权益至少自然保留3项；家居候选方向升级为预算动线型与清单复刻型，要求空间、预算、改造结果、单品作用和复刻顺序；穿搭候选方向和表达 brief 明确禁止身高/身材承诺，改用腰线、比例、垂感、遮胯边界解释价值。
- 后处理与选择器：新增穿搭夸大表达清洗器，覆盖 `160穿出165`、`秒变170`、`凭空多五厘米`、`腿长一米八`、`瘦十斤`、`同事说瘦` 等模式；新增旅行酒旅事实密度、家居复刻密度软问题，进入 selector penalty 和二修方向，但不改变 `<60` 才硬拦原则。
- 标题可读性：本轮真实探针继续发现高分半截标题，已新增修复和测试覆盖 `高腰A`、`搞定收`、`让折叠`、`做完整`、`元打造`，防止标题压缩把语义停在动词或半个单品。
- 真实验证：`quality/generated_variants/v14_travel_home_fashion_stability` 覆盖旅行/穿搭/家居 12 条，`12/12 ready`、失败 `0`、blocking `0`、均分 `73.718`、中位数 `73.956`、`9/12` 达到 72+；穿搭 4 条均 `74+` 且夸大风险扫描为 `0`。家居标题补修后单独跑 `quality/generated_variants/v14_home_title_repair_probe`，`4/4 ready`、失败 `0`、blocking `0`、均分 `72.312`、标题可读性问题 `0`。
  - 风险保留：旅行仍有 70.x 候选，家居自然候选最低仍可能在 71.x；这些内容按产品策略允许交付并进入对话优化，不作为硬拦截。
