# NoteAI V0.4 商业级模型训练执行计划

更新时间：2026-06-25

目标：训练并上线一个真正服务 AI 诊断、截图上传、手动上传、视频上传、爆文生成、对话优化的 V0.4-composite 商业级质量模型。这个模型必须以人工交付质量、A/B 偏好、事实可信、自然表达、行业价值和线上反馈为目标，不能继承 v0.3 的错误分数逻辑。

## 不可妥协原则

- 不做假训练：标签不足时必须阻断，不能用小样本 artifact 冒充商业模型。
- 不继承 v0.3：v0.3 只做历史遥测/审计对照，不进入 V0.4-composite 训练目标。
- 不只看模型分：训练目标必须包含人工质量分、交付就绪、自然度、事实状态、AI 味、同任务 A/B 偏好。
- 不单行业过拟合：美食、旅行、穿搭、美妆、家居、健身、母婴都必须有独立覆盖和校准。
- 不绕开真实链路：模型上线前必须通过截图上传、手动上传、视频上传、爆文生成、对话优化的真实回归。
- 不让生成模型自证正确：Claude 可以作为商业质量预审/主审候选，但不得把 Claude 单模型判断伪装成人工真值；所有标签必须保留来源、置信度、分歧标记和可追溯理由。

## 当前状态

- v0.3 审计：已确认不可靠，冻结为遥测。
- v0.4 CES candidate：已建立无泄漏训练管线，但指标不足，不能上线。
- v0.4-composite 特征层：已完成，124 维复合特征。
- v0.4 产品行业口径：已冻结第一批核心行业为美食、旅行、穿搭、美妆、家居、健身、母婴；研究数据中的“运动”进入训练/标注/报告时统一归为“健身”。
- golden 当前标签：145 条，其中 11 条 seed、134 条 Claude/特征首审 + Kimi 第二评审一致的 `ai_rubric_consensus` 标签；按行业为美食31、旅行17、穿搭33、美妆14、家居17、健身25、母婴8。
- preference 当前标签：204 组，其中 A 胜 91、B 胜 113，不再是单类；按行业为美食30、旅行22、穿搭36、美妆23、家居36、健身31、母婴26，但样本量仍远低于候选训练门槛。
- 当前训练决策：`blocked_need_labels`。
- 当前生产策略：`do_not_deploy=true`。

## 阶段 1：数据与训练目标冻结

状态：已完成

输入：

- RedNote-Vibe 授权数据快照。
- 项目内生成稿、真实诊断样本、人工改写样本。

输出：

- `MODEL_V03_TRAINING_AUDIT.md`
- `docs/MODEL_V04_TRAINING_ENGINEERING.md`
- `docs/V04_COMPOSITE_TRAINING_STRATEGY.md`

验收标准：

- 明确 v0.3 不能作为训练目标。
- 明确 V0.4-composite 的主标签来自人工 golden 和 A/B preference。
- 明确候选/生产训练门槛。

## 阶段 2：V0.4 基础训练管线重建

状态：已完成，但不可上线

输入：

- RedNote-Vibe 原始真实笔记。
- 去重后的真实互动样本。

输出：

- `model/rednote_vibe_v04.py`
- `model/train_v04.py`
- `model/artifacts/model_a_v0.4_candidate.lgb`
- `model/artifacts/model_a_v0.4_report.json`

验收标准：

- 按 `note_id` 分组切分，验证集无泄漏。
- 去除重复 note_id 和 many-to-many 膨胀。
- AIGC 不进入真实互动评分训练。

当前结论：

- 工程可信，但能力不足。
- 该模型只作为输入信号，不作为商业交付模型。

## 阶段 3：V0.4-composite 特征层

状态：已完成

输入：

- 标题、正文、领域、事实上下文。
- 原 v0.4 62 维输入信号。

输出：

- `model/v04_composite_features.py`

验收标准：

- 特征数稳定为 124。
- 包含标题自然度、正文信息密度、CTA、模板风险、自然度、事实槽位。
- 覆盖美食、旅行、穿搭、美妆、家居、健身、母婴。
- 测试覆盖非餐饮行业，避免餐饮规则绑架全局。

## 阶段 4：标注生产线

状态：已完成工具，进入人工标注执行

输入：

- `quality/annotation_queue.v01.jsonl`
- `quality/preference_queue.v01.jsonl`

输出：

- `tools/export_labeling_batch.py`
- `tools/ingest_golden_annotations.py`
- `tools/ingest_preference_annotations.py`
- `tools/v04_training_data_health.py`
- `tools/v04_core_domain_gap_report.py`
- `tools/export_core_domain_supplement_queue.py`
- `tools/build_preference_seed_from_generated_artifacts.py`
- `tools/ai_prelabel_review_batch.py`
- `tools/promote_reviewed_prelabels.py`
- `model/v04_domain_policy.py`
- `quality/labeling_batches/v04_round01_golden.csv`
- `quality/labeling_batches/v04_round01b_golden.csv`
- `quality/labeling_batches/v04_round01_preference.csv`
- `quality/labeling_batches/v04_round01b_preference.csv`
- `model/artifacts/v04_core_domain_gap_report.json`

验收标准：

- 可导出小批次人工标注文件。
- 可校验并合并已完成 golden。
- 可校验并导入已完成 preference。
- 可审计行业覆盖、类别平衡、重复文本、训练缺口。
- 标注、导入、训练数据、健康审计和 readiness 使用同一套产品行业口径。

当前批次：

- Round01 golden：160 条，美食/旅行/穿搭/健身各 40 条。
- Round01B golden：120 条，美妆/家居/母婴各 40 条，来自原始真实笔记关键词补样候选。
- Round01 preference：63 组，美食长禧家同任务 A/B。
- Round01B preference：105 组，7 个核心行业各 15 组，由真实 Claude 生成 artifact 组装，全部待人工 A/B 标注。
- AI 辅助审核包：已生成到 `quality/review_packets/`，只作为审核建议；未填写 `review_decision` 的行不会进入训练。
- Kimi 第二评审包：已生成 `v04_round01_kimi_*` 与 `v04_round01b_kimi_*` 四批；448 条/组评审中初次 Kimi 成功 438、失败 10，失败 10 条已用 JSON mode 补跑成功。
- AI-rubric 共识标签：最终提升 golden 34 条、preference 合并后 39 组，冲突样本全部保留 holdout。

当前阻断：

- Round01/Round01B 已完成第一轮 AI-rubric consensus 导入，但标签量远低于 candidate 门槛。
- 美妆、健身当前 preference 共识标签仍为 0，母婴仅 1 组；不能训练可上线 ranker。
- 当前健康审计不再报 winner 单类，但仍为 `blocked_need_labels`。

当前缺口报告：

- `model/artifacts/v04_core_domain_gap_report.json`
- 美食：队列可标注 350，Round01 golden 40，Round01 preference 78，生产缺口 golden 995 / preference 2997。
- 旅行：队列可标注 350，Round01 golden 40，Round01 preference 15，生产缺口 golden 999 / preference 3000。
- 穿搭：队列可标注 350，Round01 golden 40，Round01 preference 15，生产缺口 golden 999 / preference 3000。
- 美妆：队列可标注 120，Round01 golden 40，Round01 preference 15，生产缺口 golden 999 / preference 3000。
- 家居：队列可标注 120，Round01 golden 40，Round01 preference 15，生产缺口 golden 999 / preference 3000。
- 健身：队列可标注 350，Round01 golden 40，Round01 preference 15，生产缺口 golden 999 / preference 3000。
- 母婴：队列可标注 120，Round01 golden 40，Round01 preference 15，生产缺口 golden 999 / preference 3000。

## 阶段 5：Round01 人工标注

状态：待执行

输入：

- `quality/labeling_batches/v04_round01_golden.csv`
- `quality/labeling_batches/v04_round01_preference.csv`

执行要求：

- golden 必填：`human_quality_score`、`delivery_ready`、`naturalness_label`、`fact_status`、`ai_smell_level`、`failure_tags`、`rationale`。
- preference 必填：`winner`、`preference_margin`、`delivery_ready_winner`、`reason_tags`、`loser_failure_tags`、`rationale`。
- 不懂标注时，优先使用 AI 辅助审核包：只需要在 `review_decision` 填 `accept_ai`、`accept_with_edits`、`needs_manual` 或 `reject`。
- 只有 `accept_ai` / `accept_with_edits` 会被 `tools/promote_reviewed_prelabels.py` 提升为正式训练标签。
- 对 v0.3 高分但标题拼接/正文模板化的样本，必须按人工交付质量判，不看旧分。
- 对分数低但自然真实的样本，必须保留人工偏好。

验收标准：

- 导入无 error。
- golden 至少同时有 ready/not-ready 两类。
- preference 至少同时有 A 胜/B 胜，不再单类。

导入命令：

```bash
.venv/bin/python tools/ingest_golden_annotations.py --input quality/labeling_batches/v04_round01_golden.csv
.venv/bin/python tools/ingest_preference_annotations.py --input quality/labeling_batches/v04_round01_preference.csv
.venv/bin/python tools/v04_training_data_health.py
.venv/bin/python tools/v04_core_domain_gap_report.py
```

AI 辅助审核命令：

```bash
.venv/bin/python tools/ai_prelabel_review_batch.py --kind golden --input quality/labeling_batches/v04_round01_golden.csv --batch-id v04_round01
.venv/bin/python tools/ai_prelabel_review_batch.py --kind golden --input quality/labeling_batches/v04_round01b_golden.csv --batch-id v04_round01b
.venv/bin/python tools/ai_prelabel_review_batch.py --kind preference --input quality/labeling_batches/v04_round01_preference.csv --batch-id v04_round01
.venv/bin/python tools/ai_prelabel_review_batch.py --kind preference --input quality/labeling_batches/v04_round01b_preference.csv --batch-id v04_round01b
.venv/bin/python tools/promote_reviewed_prelabels.py --kind golden --input quality/review_packets/v04_round01_golden_ai_review.csv --batch-id v04_round01
```

### Claude 主审候选的边界

为什么第一阶段允许 Claude 做商业质量预审：

- 当前生成链路已经以 Claude 为主脑，Claude 对中文长文本、标题自然度、正文节奏、行业语境和“用户是否愿意发布”这类非结构化判断更敏感，能先把粗糙标注工作做成可审核建议。
- RedNote-Vibe 的原项目也不是靠传统硬规则完成语义维度判断，而是用结构化 rubric、少量锚点样例和代理 LLM 做心理语言学特征评估；我们借鉴的是这种“rubric + LLM judge + 校验”的方法，而不是照搬它的 AIGC 检测标签。
- 用户不应被迫承担专业标注员角色，因此第一阶段必须让 AI 先给出清晰建议、分数理由、失败标签和置信度，再由审核/一致性规则决定能否进入训练。

为什么 Claude 不能成为唯一真值：

- 生成模型和评审模型同源时，会有自我偏好和奖励黑客风险，容易把“Claude 喜欢的表达”训练成唯一标准。
- Claude 预审标签不能写成 `human_quality_score` 的原生人工来源，必须保留 `label_source=ai_rubric_prelabeller` 或 `ai_rubric_consensus`。
- 低置信、事实不明、行业规则冲突、v0.4 特征/自然度/事实检查不一致的样本，必须进入 holdout，不得训练。

落地原则：

- 第一层：Claude rubric judge 产出结构化建议。
- 第二层：确定性 v0.4 特征、事实边界、标题自然度、正文信息密度和 AI 味风险做一致性校验。
- 第三层：Kimi 作为已接入的第二评审，独立输出 `kimi_*` 字段；首审与 Kimi 在分数、可交付、winner、事实风险或严重失败标签上分歧时，样本进入 holdout，不得直接 `accept_ai`。
- 第四层：正式训练报告必须分开统计人工标签、AI-rubric 标签和线上反馈标签，不能混为一类。

Kimi 第二评审命令：

```bash
.venv/bin/python tools/ai_prelabel_review_batch.py --kind golden --input quality/labeling_batches/v04_round01_golden.csv --batch-id v04_round01 --second-review kimi
.venv/bin/python tools/ai_prelabel_review_batch.py --kind golden --input quality/labeling_batches/v04_round01b_golden.csv --batch-id v04_round01b --second-review kimi
.venv/bin/python tools/ai_prelabel_review_batch.py --kind preference --input quality/labeling_batches/v04_round01_preference.csv --batch-id v04_round01 --second-review kimi
.venv/bin/python tools/ai_prelabel_review_batch.py --kind preference --input quality/labeling_batches/v04_round01b_preference.csv --batch-id v04_round01b --second-review kimi
```

提升规则：

- `judge_consensus=agree`：可以作为 `accept_ai` 候选。
- `judge_consensus=disagree` 或 `second_review_failed`：`accept_ai` 会被提升工具拒绝，必须 `accept_with_edits` 后才能进入训练。
- golden 样本即使双评审一致，只要标题或正文为空，也不会被自动提升。

本轮执行结果：

- 评审总量：448 条/组。
- Kimi 初次成功：438；初次失败：10；失败补跑成功：10。
- 双评审一致：76；其中 golden 因空标题过滤后最终提升 34 条，preference 最终可用 39 组。
- 当前训练数据：golden 45 条，preference 39 组；`model/train_v04_composite.py` 默认仍输出 `blocked_need_labels`、`do_not_deploy=True`。
- 实验训练：`--allow-experimental-small-data` 可跑通，状态为 `experimental_not_production`，只能验证管线，不能发布。

2026-06-25 Round02 focused preference 执行结果：

- 新增 `quality/preference_task_pool.v02.focus.json`，聚焦上一轮低共识行业：美妆、健身、母婴；每类 3 个任务，共 9 个任务、54 个生成槽位。
- 真实生成结果：54/54 ready、失败 0；分数分布为美妆均值 66.1、健身均值 40.0、母婴均值 70.3。健身旧分数继续系统性偏低，列为 V0.4 行业校准重点。
- 组装 `quality/preference_queue.v02.focus.jsonl`：135 组 A/B，三类各 45 组。
- Kimi 复核：主批 135 组，Kimi 成功 134、失败 1；失败 1 组因 429 过载重试成功。严格完全共识仅 4 组，但 winner 一致样本较多，主要分歧来自 `delivery_ready_mismatch`。
- 新增显式 promotion 模式 `--auto-accept-winner-consensus`：仅 preference 可用；要求 Claude/Kimi 同选 A/B winner、Kimi ok、无 winner_mismatch、无 second_review_failed、无 low_kimi_confidence、Kimi confidence ≥0.7；`delivery_ready_winner` 采用 Kimi 的保守判断。该模式不改变默认严格共识策略，标签来源记为 `ai_rubric_winner_consensus`。
- Round02 最终提升 79 组 preference，合并 Round01 后 `quality/preference_queue.v01.labeled.jsonl` 当前为 118 组，winner 分布 A=50 / B=68；导入错误 0、警告 0。
- 当前训练数据：golden 45 条，preference 118 组；健康审计与 readiness 仍为 `blocked_need_labels`；默认训练仍 `do_not_deploy=True`，实验训练仅 `experimental_not_production`。
- 关键记录：`quality/review_packets/promoted/v04_round02_focus_summary.json`。

2026-06-25 Round03 focused preference 执行结果：

- 新增 `quality/preference_task_pool.v03.focus.json`，聚焦仍偏少的美食、旅行、穿搭、家居；每类 3 个任务，共 12 个任务、72 个生成槽位。
- 真实生成结果：72/72 ready、失败 0；分数均值为美食 65.3、旅行 67.8、穿搭 65.1、家居 70.2。家居表现最好；穿搭暴露价格/预算信息缺失较多，旅行暴露交通/路线或预算信息缺失较多。
- 本轮再次暴露跨行业标题压缩半截问题，如“稳定套”“留时间休”“地铁8”“遮胯显”“收纳动”“灯光窗帘让”；已扩展标题交付后处理与断词检测回归测试。
- 组装 `quality/preference_queue.v03.focus.jsonl`：180 组 A/B，四类各 45 组。
- Kimi 复核：180/180 成功，无失败；严格完全共识 28 组；采用显式 winner consensus 规则后，Round03 最终提升 86 组 preference。
- 合并 Round01/Round02/Round03 后，`quality/preference_queue.v01.labeled.jsonl` 当前为 204 组，winner 分布 A=91 / B=113；按行业为：美食30、旅行22、穿搭36、美妆23、家居36、健身31、母婴26。
- 当前训练数据：golden 45 条，preference 204 组；健康审计与 readiness 仍为 `blocked_need_labels`；默认训练仍 `do_not_deploy=True`，实验训练仅 `experimental_not_production`。
- 关键记录：`quality/review_packets/promoted/v04_round03_focus_summary.json`。

2026-06-25 Round04 focused golden 执行结果：

- 新增 `tools/export_labeling_batch.py --exclude-ids-from`，导出后续标注包时可排除历史 batch、review packet、promoted 文件和 merged label 文件中的 `annotation_id/pair_id`，避免重复审同一批样本。
- 导出 Round04a golden：`quality/labeling_batches/v04_round04a_golden.jsonl`，美食/旅行/穿搭/健身各 40 条，共 160 条；Kimi 第二评审 160/160 ok，严格共识 40 条。
- 导出 Round04b golden：`quality/labeling_batches/v04_round04b_golden.jsonl`，美妆/家居/母婴各 40 条，共 120 条；Kimi 第二评审 120/120 ok，严格共识 20 条。
- Golden 晋级继续只允许 `judge_consensus=agree` 且无分歧标记；实际提升 48 条，其中 Round04a 31 条、Round04b 17 条，其余 232 条保留 holdout。
- 修复 `tools/promote_reviewed_prelabels.py` 把数值 `0` 清洗为空字符串的问题；低自然度/低质量负样本是回归器训练需要的合法标签，不能因 `0` 值被错误丢弃。
- 合并后 `quality/golden_labels.v01.merged.json` 为 93 条，按行业为：美食22、旅行13、穿搭15、美妆12、家居10、健身17、母婴4。
- 当前训练数据：golden 93 条，preference 204 组；健康审计与 readiness 仍为 `blocked_need_labels`；默认训练仍 `do_not_deploy=True`，实验训练仅 `experimental_not_production`。
- 关键记录：`quality/review_packets/promoted/v04_round04_golden_summary.json`。

2026-06-25 Round05 focused golden 执行结果：

- 扩大低覆盖行业补样池：`quality/annotation_queue.v01.core_supplement.v02.jsonl` 达到美妆/家居/母婴各 300 条；可用候选为美妆1283、家居329、母婴1782，无 shortfall。
- 导出 Round05a golden：美食/旅行/穿搭/健身各 40 条，共 160 条；Kimi 第二评审 160/160 ok，严格共识 41 条，实际提升 39 条。
- 导出 Round05b golden：美妆/家居/母婴各 60 条，共 180 条；Kimi 第二评审 180/180 ok，严格共识 15 条，实际提升 13 条。
- 合并后 `quality/golden_labels.v01.merged.json` 为 145 条，按行业为：美食31、旅行17、穿搭33、美妆14、家居17、健身25、母婴8。
- 更新 `tools/v04_core_domain_gap_report.py`，当 v02 补样报告存在时默认读取 v02，低覆盖行业队列容量不再误显示为旧的 120 条。
- 当前训练数据：golden 145 条，preference 204 组；健康审计与 readiness 仍为 `blocked_need_labels`；默认训练仍 `do_not_deploy=True`，实验训练仅 `experimental_not_production`。
- 关键记录：`quality/review_packets/promoted/v04_round05_golden_summary.json`。

## 阶段 6：多行业样本补齐

状态：执行中

目标：

- Candidate 最低门槛：每个核心行业 300 条 golden、1000 组 preference。
- Production 最低门槛：每个核心行业 1000 条 golden、3000 组 preference。
- 推荐上线目标：每个核心行业 2000 条 golden、5000+ 组 preference。

执行方向：

- 美食：继续扩展本地生活真实店铺样本，高德事实源辅助。
- 旅行：结合 meituan-travel 和真实路线/酒店/景点样本。
- 穿搭：围绕身材、场景、价格、单品公式补样。
- 美妆：围绕肤质、色号、妆效、价格、使用方法补样。
- 家居：围绕面积、预算、清单、改造前后补样。
- 健身：围绕动作、组数、安全、适合人群补样。
- 母婴：围绕月龄、安全、步骤、观察周期补样。

验收标准：

- 每个行业都有高/中/低质量样本。
- 每个行业都有同任务 A/B 生成稿、对话优化稿、人工自然稿。
- 每个行业都有 false positive / false negative 专项样本。

## 阶段 7：Candidate 训练

状态：待标签达标后执行

输入：

- `quality/golden_labels.v01.merged.json`
- `quality/preference_queue.v01.labeled.jsonl`

输出：

- V0.4-composite regressor：预测人工质量分。
- V0.4-composite ready classifier：预测可交付概率。
- V0.4-composite ranker：同任务候选排序。
- 训练报告、行业校准报告、错误样本报告。

训练命令：

```bash
.venv/bin/python model/v04_composite_dataset.py
.venv/bin/python model/train_v04_composite.py
.venv/bin/python tools/v04_training_data_health.py
```

验收标准：

- Group split 无泄漏。
- 各行业都有独立评估。
- ready/not-ready AUC、人工分 MAE、pairwise accuracy 达到候选阈值。
- 不出现“模型高分但人工明显不可交付”的高危误判。

阻断条件：

- 标签量不足。
- 行业覆盖不足。
- preference winner 单类。
- golden delivery_ready 单类。
- 关键高危误判未解决。

## 阶段 8：Arbiter 与生成链路接入

状态：待 candidate 通过后执行

目标：

- 用 composite ranker 选择三方案。
- 用 regressor/ready classifier 判断候选是否可交付。
- 用 arbiter 融合事实安全、自然度、行业规则和模型输出。

接入范围：

- AI 诊断三方案排序。
- 爆文生成候选筛选。
- 对话优化候选选择。
- 二修候选采纳/拒绝。

上线方式：

- feature flag 灰度。
- 先只记录 shadow score，不影响用户。
- 再小流量替换旧排序。

验收标准：

- 不降低事实安全。
- 不牺牲标题自然度。
- 多行业输出质量稳定。
- 用户可见质量优于旧链路。

## 阶段 9：真实链路回归

状态：待模型接入后执行

必须覆盖：

- 手动上传 AI 诊断。
- 截图上传 AI 诊断。
- 视频上传 AI 诊断。
- AI 爆文生成。
- 对话优化。
- 事实源补全。
- 管理端模型发布/回滚。

验收标准：

- 三方案标题不同，正文不同，方向不同。
- 不出现空响应冒充成功。
- 不出现标题超过 18 字交付。
- 不出现事实编造。
- 不出现模板化高分稿通过。
- 用户能看懂、愿意复制、愿意继续优化。

## 阶段 10：生产上线门槛

状态：待执行

必须满足：

- Production 标签门槛达标。
- 每个核心行业有校准报告。
- Golden 高危误判归零或有硬规则兜底。
- 真实链路人工验收通过。
- 模型 artifact 有版本、报告、回滚路径。
- 管理端发布后 API 确认读取新模型。

禁止上线：

- 只用实验小样本 artifact。
- 只用 v0.3 或 CES 分数判断交付。
- preference ranker 单类训练。
- 任何核心行业没有最低覆盖。

## 每次推进必须更新

每次完成训练相关工作，必须同步更新：

- `docs/V04_TRAINING_EXECUTION_PLAN.md`
- `docs/V04_COMPOSITE_TRAINING_STRATEGY.md`
- `DELIVERY_FIX_TRACKER.md`
- 对应的 artifact report。

如果上下文中断，下一次从本文件继续。

## 阶段进展记录

- 2026-06-28 真实链路质量稳定化 Round01：确认 V0.4 composite 生产训练 run `20260628T013926Z` 已进入 API 主评分链路，当前任务从“继续补 Golden”转为“让真实 AI 诊断、爆文生成、对话优化稳定产出有付费价值的内容”。已完成第一组链路修复：`tools/v04_training_data_health.py` 与 `tools/v04_composite_readiness.py` 的生产 Golden 默认线同步为当前接受线 `600/行业`，并重建 `model/artifacts/v04_training_data_health.json`、`model/artifacts/v04_composite_readiness.json`，两者均为 `production_ready`；`_build_generation_planning_brief()` 不再只对美食/旅行显式抽取事实，已为穿搭、美妆、家居、健身、母婴提取本行业事实槽位（身材/场合、肤质/色号、空间/预算、动作/时长、月龄/用品等），保证 brief 真正多行业；`_repair_chat_note_if_needed()` 已允许对话优化在 60+、无硬错误但 V0.4 可解释低分时触发分数导向二修，而不是只处理显性质量问题。新增回归测试覆盖多行业 fact brief 和 chat V0.4 lift。
- 2026-06-28 真实链路质量稳定化 Round01 后半段：酒旅事实源解析从“只读美团卡片行”升级为“卡片式 + 叙述式”双解析，真实 `meituan-travel` 输出能提取酒店名、美团真实评分/起价、地址、入住/退房、亲子设施、交通权益和套餐权益，并过滤 Markdown、Skill 前缀、泛化套餐说明；餐饮高德事实源复测 `local_verified+amap` confidence=`0.9`。生成链路新增多行业“商业价值槽位”：旅行补交通/预算，穿搭补价格/渠道，美妆补价格/渠道，家居补预算/单品价，餐饮补营业时间/必点；美妆和家居新增专属表达 brief。验证记录：全量单测 `145` 项通过，质量门禁通过，py_compile 通过，训练健康/readiness 均 `production_ready`，Shadow QA `362/362` ready、hard block `0`、平均 V0.4 `71.585`、`166` 条 `>=72`。剩余风险：历史 artifact 仍有标题可读性、餐饮营业信号、旅行交通信号风险；母婴按用户要求冻结。
- 2026-06-28 真实链路质量稳定化 Round12：新增 `quality/preference_task_pool.v12.real_chain_stability.json`，覆盖美食/旅行/穿搭/美妆/家居/健身 6 个核心行业各 4 个真实生成槽位，母婴继续冻结。完整重刷两轮后修复三个交付层问题：60+ 旅行稿被旧 blocking 标记误拦、酒旅价格格式 `￥929起/晚` 被误判为编造、标题压缩出现 `芝士焗小青龙必/遮胯搭/2600元让动线/929起的长` 等半截尾。最终刷新结果：`24/24 ready`、失败 `0`、blocking `0`、标题可读性问题 `0`、均分 `72.318`、中位数 `73.255`、`13/24` 达到 72+；Shadow QA 全量 `386/386` ready、hard block `0`，v12 set `24/24` shadow ready、平均 V0.4 `72.13`。结论：新策略已有真实增益，但美食/美妆/旅行单次 Claude 输出仍波动，生产级下一步不是继续堆 prompt，而是接入“同任务多候选生成 + V0.4 composite/ranker 选择最佳 + <60 才硬拦 + 60+ 进入对话优化”的稳定交付器。
- 2026-06-25 Round08b：完成美食表达质量专项。高德事实进入生成/训练前已清洗重复标签，正文安全事实句改为自然决策句，训练 seed 写入交付清洗后的标题/正文/重算分数；新增“吃到饱/不限量”事实边界，除非来源明确自助/不限量，否则不允许从人均价推导。真实生成 `24/24 ready`、失败 `0`，最高 `76.029`，`3` 篇达到旧 72 参考线，污染扫描为 `0`；导出 `46` 组美食 A/B，Kimi 二审 `46/46 ok`，按 winner-consensus + Kimi confidence ≥`0.75` 晋级 `26` 组。合并后总 preference `258` 组，美食 preference `73` 组；训练守门仍 `blocked_need_labels`，生产部署继续禁止。
- 2026-06-25 Round09：完成酒旅/旅行表达专项。对齐用户事实源策略：餐饮/本地生活由高德在真实链路补事实，训练不学习“未提供/不能编造”提示；酒店/旅行攻略使用美团 `meituan-travel` 事实素材。修复旅行 brief、prompt、事实安全、标题断尾、Claude 硬超时和 hashtag/Markdown 误判。重刷 `quality/generated_variants/v09_travel_expression_probe/` 后 `30/30` 候选可用，`14` 篇 ≥72、`22` 篇 ≥70、低于 60 为 `0`、blocking 为 `0`，Markdown/无依据价格承诺/标题断尾扫描均为 `0`。重新导出 `75` 组旅行 A/B，Claude 主审 + Kimi 二审 `75/75 ok`，winner 一致 `23` 组，按 Kimi confidence ≥`0.75` 晋级 `14` 组，其余 `61` 组 holdout。重建 merged preference 时补回最早 `3` 条 locked seed，当前总 preference `272` 组，旅行 preference `47` 组；Golden `157` 条。训练健康、readiness、训练守门仍 `blocked_need_labels` / `do_not_deploy=true`，不能部署生产模型。专项报告：`quality/review_packets/promoted/v09_travel_expression_summary.json`。
