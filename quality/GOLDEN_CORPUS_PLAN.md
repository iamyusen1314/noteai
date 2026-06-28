# NoteAI Golden Corpus Plan

创建时间：2026-06-25

目标：把“爆文质量”从 v0.3 单一模型分升级为可人工复核、可训练、可回归测试的复合质量标准。这个工程服务于 AI 诊断、截图/手动/视频上传、AI 爆文生成和对话优化，不允许再用虚高模型指标替代用户真实感受。

## 核心结论

`30-50 条/行业`只能作为校准种子集，不能作为正式训练集。

正式交付前，核心行业需要分阶段建设，不能把“候选模型门槛”当成“生产交付门槛”：

- `300 条/行业`：只够进入第一版 composite candidate 训练。
- `500 条/行业`：只够做 candidate 稳定性评估和灰度前人工验收。
- `1000 条/行业`：生产训练最低线。
- `2000 条/行业`：生产上线推荐线，覆盖高质量、边界、低质、AIGC、Claude 好稿、Claude 失败稿、事实越界稿、标题失败稿、对话优化稿。
- `3000+ 组/行业`：生成内容 A/B 偏好对，用于训练“哪版更值得交付”。

当前导出的 `annotation_queue.v01` 是“待人工标注队列”，不是训练完成的数据集。

## 分层数据结构

### Layer 0：Seed 校准集

用途：统一人工评分口径，验证评测工具链。

要求：

- 每个重点行业 `30-50 条`。
- 包含好稿、坏稿、模型误判稿、评分黑客稿。
- 已有文件：`quality/golden_labels.v01.seed.json`。

状态：已建立，但样本量太小，只能做回归测试，不能训练最终模型。

### Layer 1：人工 Golden 训练集

用途：训练 composite quality model。

候选模型每个核心行业最低结构：

| 样本层 | 建议数量 | 目的 |
| --- | ---: | --- |
| 高互动真实笔记 | 80-120 | 学真实平台表达和内容密度 |
| 良好真实笔记 | 50-80 | 学可交付中高质量边界 |
| 55-70 分边界样本 | 70-120 | 学“需要优化但不是废稿” |
| 中低质真实笔记 | 80-120 | 学低信息密度和弱钩子 |
| AIGC / AI味样本 | 40-80 | 学模板化、AI味、拼接感 |
| 系统生成稿 | 60-120 | 学 NoteAI 自身会犯的错误 |

生产模型需要在候选结构基础上继续扩样：

- 每个核心行业 `>=1000 条` 才允许训练生产候选。
- 每个核心行业 `>=2000 条` 才建议进入正式上线评估。
- 每类高发错误都要有专项样本：标题不自然、正文模板化、事实越界、信息密度低、过度夸张、行业错配、对话优化后变差、v0.3 高分假阳性。
- 每轮训练后必须从失败集反向补样，不能只机械追加随机样本。

第一版自动队列默认按 RedNote-Vibe 已有行业抽样约 `350 条/行业`：

- `real_top`：CES 85-100，80 条。
- `real_good`：CES 70-85，50 条。
- `real_boundary`：CES 55-70，70 条。
- `real_mid`：CES 35-55，50 条。
- `real_low`：CES 0-25，60 条。
- `aigc`：40 条。

注意：CES 是互动分位，不是人工质量分。人工标注时可以给高互动样本低分，也可以给低互动但真实有价值样本高分。

### Layer 2：生成偏好数据

用途：训练“同一个用户需求下，哪个标题/正文更值得交付”。

要求：

- 每个核心行业至少 `3000+ 组 A/B 对比`。
- 比较对象包括 Claude 首稿、二修稿、对话优化稿、人工改写稿。
- 标签不是单分数，而是 `winner / margin / reason_tags / delivery_readiness_delta`。

这一层对付费 SaaS 很关键，因为用户最终看到的是系统生成内容，不是原始平台笔记。

### Layer 3：线上反馈闭环

用途：让 Harness agent 越来越懂用户。

可用信号：

- 用户复制、导出、收藏、继续优化、放弃。
- 用户手动改标题/正文的差异。
- 用户对“更自然/更短/更有信息/别夸张”的反馈。
- 同一用户历史偏好和行业偏好。

线上信号不能直接替代人工 golden，但可以作为个性化排序和长期优化信号。

## 人工标签字段

每条样本必须标注：

- `human_quality_score`：0-100 综合质量分。
- `delivery_ready`：是否可作为最终稿交付。
- `naturalness_label`：人工自然度，不等同于 AI 检测分。
- `hook_quality`：标题/开头钩子 1-5。
- `body_value`：正文价值密度 1-5。
- `industry_fit`：行业适配 1-5。
- `fact_status`：`verified / safe / unknown / overclaim`。
- `ai_smell_level`：AI味 1-5。
- `failure_tags`：失败原因。
- `rationale`：一句人工判断理由。

## 训练准入门槛

任何 composite 模型进入候选前，必须满足：

- 每个核心行业已标注样本数 `>=300`。
- 高/中/低/AIGC/系统生成稿都有覆盖。
- `delivery_ready=true` 和 `false` 都有足够样本，不允许单边标签。
- 标注文件能通过 schema 校验。
- 对 v0.3 假阳性、v0.3 假阴性、自然度模型误伤都有专项样本。

任何 composite 模型进入生产候选前，必须满足：

- 每个核心行业已标注样本数 `>=1000`。
- 每个核心行业 A/B 偏好对 `>=1000`。
- 系统生成稿、对话优化稿、失败修复稿占比不能低于核心行业样本的 `20%`。
- 对每个核心行业都有独立验证集，不允许只看全局平均。

上线前建议满足：

- 每个核心行业已标注样本数建议 `>=2000`。
- 每个核心行业 A/B 偏好对建议 `>=3000`。
- Golden 回归集中不得出现“模型高分但标题读不懂/正文模板化”的样本通过。
- AI 诊断三入口和爆文生成入口都要跑同一套质量 harness。
- 低于 60 分仍硬拦截；60 分以上可进入对话优化，但不能把“可优化稿”当成“高质量交付稿”。

## 当前产物

- `tools/export_golden_annotation_queue.py`：从 RedNote-Vibe v0.4 数据集中分层抽样，导出人工标注队列。
- `quality/annotation_queue.v01.jsonl`：机器可读待标注队列。
- `quality/annotation_queue.v01.csv`：人工标注表。
- `quality/annotation_queue.v01.report.json`：覆盖率和缺口报告。
- `tools/export_preference_annotation_queue.py`：从同一任务的多个生成稿导出 A/B 偏好标注队列。
- `quality/preference_queue.v01.jsonl`：机器可读 A/B 偏好队列。
- `quality/preference_queue.v01.csv`：人工偏好标注表。
- `quality/preference_queue.v01.report.json`：偏好队列覆盖报告。
- `quality/preference_task_pool.v01.seed.json`：多行业同任务生成任务池。
- `tools/export_preference_task_pool.py`：把任务池展开成候选生成队列。
- `quality/preference_generation_queue.v01.jsonl`：机器可读候选生成队列。
- `quality/preference_generation_queue.v01.csv`：人工/批处理可读候选生成队列。
- `quality/preference_generation_queue.v01.report.json`：生成任务覆盖报告。

## 已知缺口

RedNote-Vibe 当前公开字段的 domain 不完全等于 NoteAI 产品行业：

- 美妆目前可能并入穿搭/其他，需要人工二级分类或产品样本补齐。
- 家居、母婴在当前 domain 中没有稳定独立类目，需要从用户素材、生成稿和后续授权数据补样。
- 酒旅需要结合 `meituan-travel` 事实源和真实生成任务单独建偏好集。

因此第一版 annotation queue 解决的是“真实平台表达底座”，不是完整产品行业标签闭环。后续必须继续补系统生成稿和产品行业样本。
