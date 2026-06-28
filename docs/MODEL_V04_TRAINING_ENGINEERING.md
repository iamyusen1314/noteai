# Model A v0.4 训练工程标准

创建时间：2026-06-25

## 原则

v0.4 不再追求“把所有特征一次性塞进模型”，而是先保证评分模型的根基可信：

- 原始素材必须版本化保存，并记录来源 commit、文件 hash、行数和领域分布。
- 训练数据必须统一字段 schema，兼容 `desc/liked_count` 与 `note_content/likes` 两套字段。
- 评分模型只使用有真实互动数据的真实笔记；`training_set_aigc` 暂不进入 CES 评分训练。
- 每个 `note_id` 只能进入训练集一次，禁止 many-to-many merge 膨胀。
- 标签口径统一为 `liked_count + collected_count + comments_count * 4`，再按 `source_type::domain` 计算百分位。
- 验证集必须按 `note_id` 分组切分，训练集和验证集不能共享同一 note。
- 所有模型先产出 candidate，不自动覆盖线上 `model_a_current.lgb`。

## 新增文件

- `tools/sync_rednote_vibe.py`：同步 RedNote-Vibe Google Drive 素材，生成 snapshot manifest。
- `model/rednote_vibe_v04.py`：字段标准化、去重、标签构造、特征构造、dataset manifest。
- `model/train_v04.py`：GroupShuffleSplit 训练、行业/来源评估、candidate 模型和报告输出。

## v0.4 第一阶段范围

v0.4 第一阶段是“62列兼容的内容质量基线”：

- 可信使用：37 个内容文本特征。
- 中性占位：3 个语义特征、14 个封面特征、8 个时机特征。
- 目的：先验证内容评分是否稳定、无泄漏、跨行业可校准，再逐层加入封面、语义、人感/自然度和事实源特征。

## 命令

同步最新 RedNote-Vibe 素材：

```bash
.venv/bin/python tools/sync_rednote_vibe.py
```

重建 v0.4 数据集并训练候选模型：

```bash
.venv/bin/python model/train_v04.py --rebuild-dataset
```

主要输出：

- `model/data/v04/dataset_manifest.json`
- `model/data/v04/features_v04.parquet`
- `model/artifacts/model_a_v0.4_candidate.lgb`
- `model/artifacts/model_a_v0.4_report.json`

## 上线门槛

candidate 只有同时满足以下条件，才允许进入人工验收和灰度：

- `split.leakage.overlap_note_ids == 0`
- 每个核心行业都有独立评估结果：美食、旅行、穿搭、健康、职场、情感、心理、运动、宠物、学习。
- 不只看整体 RMSE，还要检查各行业 `bias`，避免某行业系统性高估/低估。
- golden set 上不能出现“模型高分但人感明显差”的样本通过。
- 真实 AI 诊断/爆文生成回归中，模型分、自然度、事实准确性必须同时达标。

## 2026-06-25 首次候选训练结果

已同步 RedNote-Vibe 当前 Google Drive 快照：

- GitHub commit：`a9bc6e29654986c4bfc5d0c61d8d801c0a855291`
- Snapshot：`model/data/rednote_vibe_raw/20260625T062120Z_a9bc6e296549`
- 原始文件 hash：见 `sync_manifest.json`

v0.4 数据集重建结果：

- normalized rows：150,649
- score rows deduped：110,717
- exploration：59,045
- human：51,672
- removed duplicate note_id：31,562
- 美食样本：10,515

v0.4 regression candidate：

- 文件：`model/artifacts/model_a_v0.4_candidate.lgb`
- 报告：`model/artifacts/model_a_v0.4_report.json`
- split：GroupShuffleSplit(note_id)，overlap note_id = 0
- RMSE：26.46
- MAE：22.68
- ±10 分准确率：21.58%
- Spearman：0.349

结论：训练工程可信度已显著提高，但第一版“规则文本特征”模型能力不足，不能替换线上评分器。旧 v0.3 的高准确率主要来自泄漏/膨胀；v0.4 的低指标是更真实的难度暴露。

补充实验：同一特征训练 `CES>=70` Top30 分类，AUC 约 0.657，仍不足以作为付费级质量判断主模型。

下一步必须补齐：

- 语义/自然度特征：用授权数据训练或标注“人感自然、模板化、AI味、实用密度、情绪穿透”。
- 行业 golden set：每行业人工审核高/中/低质量样本，并对模型分数做行业校准。
- 标签重构：从单一互动分位升级为“互动表现 + 人工质量 + 事实实用性 + AI味惩罚”的复合目标。
- 线上生成评测：Claude 生成结果必须进入 golden/harness 回归，不允许只看模型分。

## Naturalness v0.1 辅助模型

RedNote-Vibe 原始任务适合训练 AIGT/自然度检测，因此新增独立辅助模型：

- 训练脚本：`model/train_naturalness_v01.py`
- 特征：`model/text_naturalness_features.py`
- 运行时 helper：`model/naturalness.py`
- 探针工具：`tools/naturalness_probe.py`
- 模型：`model/artifacts/model_naturalness_v0.1.lgb`
- 报告：`model/artifacts/model_naturalness_v0.1_report.json`

验证设计：

- 正类：`training_set_aigc`
- 负类：`training_set_human`
- 不使用发布时间和 domain encoded，避免来源泄漏。
- 验证集 holdout AI 模型：`claude-sonnet-4`、`gpt-4.1`、`qwen3`、`gemini-2.5`。

首轮结果：

- ROC AUC：0.983
- Average Precision：0.940
- human false positive rate：1.13%
- AI false negative rate：16.64%

重要边界：

- 该模型擅长区分真实历史人类笔记和 AIGC。
- 对当前 Claude 生成稿概率会饱和，连“更自然”的手工候选也会被判为 AI。
- 因此 v0.1 只能作为 AI 味风险监控、特征诊断和后续训练辅助，暂不能作为硬拦截。

## Composite Golden v0.1

新增人工 golden 标签工程：

- Schema：`quality/golden_label_schema.v01.json`
- 标注指南：`quality/GOLDEN_LABELING_GUIDE.md`
- 种子标签：`quality/golden_labels.v01.seed.json`
- 复合质量报告：`tools/composite_quality_report.py`
- 报告输出：`quality/composite_quality_report.v01.json`

标签目标不再等同于 v0.3 分数，而是：

- `human_quality_score`：人工综合质量分。
- `delivery_ready`：是否允许交付。
- `naturalness_label`：人工自然度。
- `fact_status`：事实状态。
- `ai_smell_level`：AI 味等级。
- `failure_tags`：失败原因。

首批种子报告：

- total：11
- delivery_ready：8
- not_ready：3
- ready 平均 v0.3：75.05
- not-ready 平均 v0.3：65.37
- ready 平均 v0.4：45.10
- not-ready 平均 v0.4：38.17
- ready 平均 naturalness model：71.14
- not-ready 平均 naturalness model：0.10

已暴露的关键 mismatch：

- `v03_false_negative`：健身好稿被 v0.3 压分。
- `naturalness_model_false_positive`：美妆好稿、长禧家自然稿被自然度模型误伤。
- `signal_false_negative`：实验复合信号仍偏保守，不能上线。

结论：现在已经有了复合目标工程，但样本量太小，不能训练最终模型。`30-50 条/行业`只允许作为校准种子集；`300-500 条/核心行业`只允许进入 candidate 训练和灰度前验收；生产训练最低需要 `1000 条/核心行业`，推荐上线目标为 `2000 条/核心行业`，并额外建立 `3000+ 组/核心行业`生成稿 A/B 偏好数据。

## Golden Annotation Queue v0.1

新增正式人工标注队列工程：

- 计划文档：`quality/GOLDEN_CORPUS_PLAN.md`
- 导出工具：`tools/export_golden_annotation_queue.py`
- 标注队列 JSONL：`quality/annotation_queue.v01.jsonl`
- 标注队列 CSV：`quality/annotation_queue.v01.csv`
- 覆盖报告：`quality/annotation_queue.v01.report.json`

首批导出结果：

- total：3,821
- needs_label：3,810
- locked_seed：11
- RedNote-Vibe 真实评分样本：3,410
- RedNote-Vibe AIGC 样本：400
- 每个已观察行业默认约 350 条待标注样本。

分层抽样结构：

- `real_top`：CES 85-100，高互动真实笔记。
- `real_good`：CES 70-85，中高质量候选。
- `real_boundary`：CES 55-70，交付线附近边界样本。
- `real_mid`：CES 35-55，中低质量样本。
- `real_low`：CES 0-25，低互动/低质候选。
- `aigc`：AIGC 样本，用于标注 AI味和模板化。
- `seed_locked`：已人工判断的种子样本。

覆盖缺口：

- 当前 RedNote-Vibe 快照可按独立 domain 抽样：健康、其他、学习、宠物、心理、情感、旅行、穿搭、美食、职场、运动。
- 美妆、家居、母婴没有稳定独立 RedNote domain；家居/母婴目前只有 seed 样本，仍需要产品素材、用户样例、生成稿和后续授权数据补齐。
- `其他` 缺少 AIGC 样本，因此本轮只导出 310 条待标注样本。

重要原则：`annotation_queue.v01` 是待人工标注队列，不是最终训练标签。只有人工填完 `human_quality_score`、`delivery_ready`、`naturalness_label`、`fact_status`、`ai_smell_level` 等字段并通过 schema 校验后，才能进入 composite 模型训练。

## Preference Annotation Queue v0.1

生成质量不能只靠真实笔记评分训练，还必须训练“同一个用户需求下哪一稿更值得交付”。新增 A/B 偏好标注队列工程：

- Schema：`quality/preference_label_schema.v01.json`
- 标注指南：`quality/PREFERENCE_LABELING_GUIDE.md`
- 种子任务：`quality/preference_pairs.v01.seed.json`
- 导出工具：`tools/export_preference_annotation_queue.py`
- 队列 JSONL：`quality/preference_queue.v01.jsonl`
- 队列 CSV：`quality/preference_queue.v01.csv`
- 覆盖报告：`quality/preference_queue.v01.report.json`

首批队列聚焦长禧家同一任务下的真实生成链路：AI 诊断三方案、chat 对话优化、brief 后稿、评分导向二修、标题自然化二修、Claude 自然候选和人工自然候选。它专门覆盖 v0.3 高分但标题难读、人感自然但模型分略低、正文模板化、对话优化未升分等关键错误。

首批导出结果：

- task：`changxi_longchu_wanbo_food_001`
- variants：12
- A/B pairs：66
- needs_label：63
- locked_seed：3
- domain：美食

覆盖缺口：

- 当前偏好队列只是美食同一任务种子，距离 `3000+ 组/核心行业`生产目标很远。
- 旅行、穿搭、美妆、家居、运动、母婴仍需要同任务生成稿、对话优化稿和人工改写稿构成偏好队列。

重要原则：偏好标签必须同任务比较。不能把不同行业、不同素材、不同用户意图的两篇笔记硬配成 A/B；否则模型会学到题材差异，而不是质量偏好。

## v0.4-composite 训练工程 v0.1

新增文件：

- `model/v04_composite_features.py`：复合特征层，使用 62 维 v0.4 输入信号 + 商业交付质量特征。
- `model/v04_composite_dataset.py`：golden / preference 数据集构建器。
- `model/train_v04_composite.py`：训练守门与实验训练脚本。
- `tests/test_v04_composite_features.py`、`tests/test_v04_composite_dataset.py`、`tests/test_train_v04_composite.py`：防回归测试。

复合特征当前共 124 维：

- 62 维 v0.4 内容/语义/视觉/时机输入。
- 标题自然度、标题价格拼接风险、正文主体长度、段落/句子节奏、CTA、第一人称/真实口吻。
- 事实密度、行动价值、具体性、自然度模型输出。
- 美食/旅行/穿搭/美妆/家居/健身/母婴各自的事实槽位覆盖。

训练数据策略：

- 旧 `variant_score` / v0.3 分数只保留在原始队列做历史上下文，不进入 composite features，也不作为 target。
- golden target：`human_quality_score`、`delivery_ready`、`naturalness_label`、`hook_quality`、`body_value`、`industry_fit`、`fact_status`、`ai_smell_level`。
- preference target：同任务 A/B 的 `preference_label_a_wins`。
- `legacy_score_directed_second_pass` 只作为历史评分黑客负例，不代表现行生成策略。

当前运行结果：

```bash
.venv/bin/python model/v04_composite_dataset.py
.venv/bin/python model/train_v04_composite.py --allow-experimental-small-data
```

- `model/data/v04_composite/golden_training_rows.parquet`：11 rows。
- `model/data/v04_composite/preference_pair_rows.parquet`：3 rows。
- `model/artifacts/model_v04_composite_train_report.json`：`experimental_not_production`，`do_not_deploy=true`。
- preference ranker 未训练：当前 3 个锁定偏好全为 B 胜，类别不平衡。

结论：v0.4-composite 的“训练工程”已经建立，但商业级模型仍被标签量阻断；不能用当前实验 artifact 上线。

## Preference Task Pool v0.1

为了把 A/B 偏好数据扩展到多行业，新增“任务池 -> 生成队列 -> 偏好队列”三段式流程：

- Schema：`quality/preference_task_pool_schema.v01.json`
- 指南：`quality/PREFERENCE_TASK_POOL_GUIDE.md`
- 任务池：`quality/preference_task_pool.v01.seed.json`
- 导出工具：`tools/export_preference_task_pool.py`
- 生成队列 JSONL：`quality/preference_generation_queue.v01.jsonl`
- 生成队列 CSV：`quality/preference_generation_queue.v01.csv`
- 覆盖报告：`quality/preference_generation_queue.v01.report.json`

首批任务池覆盖 7 个核心行业：

- 美食：上海南京西路蟹黄拌面
- 旅行：成都 3 天 1200 元城市漫游
- 穿搭：小个子通勤显高 3 套公式
- 美妆：黄皮奶杏玫瑰腮红测评
- 家居：38 平出租屋 3000 元改造
- 健身：居家 7 天减脂 4 动作
- 母婴：8 月龄宝宝辅食添加

导出结果：

- tasks：7
- generation rows：63
- 每个行业 1 条任务、9 个候选槽位。
- 所有槽位当前均为 `needs_generation`，等待真实 `/analyze`、`/generate`、chat、离线 Claude 候选和人工改写产出。

规模估算：

- 9 个候选槽位全部完成后，一条任务最多形成 36 组 A/B。
- 若目标是 `3000+ 组/核心行业`，每个行业约需 84 条完成任务。
- 当前任务池只是多行业骨架，不是生产规模数据。

## Preference Slot Fill Runner v0.1

为避免把空槽位、假样本或无法追溯的批量生成混进偏好训练，新增离线槽位填充器：

- 生成工具：`tools/fill_preference_generation_slots.py`
- 输入队列：`quality/preference_generation_queue.v01.jsonl`
- 输出目录：`quality/generated_variants/v01/<task_id>/<slot_id>.json`
- 每个 artifact 记录：原始 Claude 响应、最终标题、正文、v0.3 分数、grade、是否硬阻断、质量问题、62 维特征快照、完整特征、已核验事实上下文。

执行策略：

- `analyze`、`generate`、`offline_candidate` 可直接生成。
- `second_pass`、`chat` 需要同任务已有可用基稿，默认不批量跑，避免无上下文假装对话优化。
- `manual` 不由模型生成，必须人工改写后再进入偏好队列。
- 生成后统一经过标题压缩/清洗、正文交付整形、事实边界检查、语义特征评分和质量门禁。

2026-06-25 真实小批结果：

- 美食 AI 诊断三方向：`63.7 / 58.9 / 69.2`，其中 B 因低于 60 分硬阻断；A/C 超过 60 但未达 72，可进入二修/对话优化。三方向标题仍有同质化现象，后续要强化同任务方向差异。
- 7 个核心行业 `generate_initial` 冒烟：美食 `63.4`、旅行 `65.3`、穿搭 `75.4`、美妆 `61.2`、家居 `64.8`、健身 `37.2`、母婴 `69.8`。只有穿搭首稿达到 72+。
- 真实冒烟暴露并修复标题硬裁断问题：XML 解析阶段不再提前截断长标题，交给语义压缩和 fallback；fallback 增加常见断词清理，避免交付「无器械计」「软颗粒安」这类半截标题。

关键结论：当前生成链路可以稳定产出可追溯训练样本，但生成质量还不稳定；v0.3 对健身等行业明显不可靠，不能单独作为多行业交付标准。下一阶段应优先扩充人工偏好标签，并针对低于 72 但高于 60 的候选跑同任务二修/自然化对比，训练“人感 + 实用密度 + 分数”的复合偏好模型。
