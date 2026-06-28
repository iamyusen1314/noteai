# NoteAI AI 辅助标注操作说明

目标：让不懂机器学习标注的人，也能安全推进 V0.4-composite 训练数据。

## 你只需要理解 3 个动作

打开 `quality/review_packets/*.csv` 后，主要看这几列：

- `title` / `body` 或 `variant_a_title` / `variant_b_title`
- `ai_*` 建议字段
- `ai_rationale`
- `review_decision`

在 `review_decision` 填：

- `accept_ai`：你觉得 AI 建议基本合理，允许进入正式训练标签。
- `accept_with_edits`：你改了 `review_*` 字段后接受。
- `needs_manual`：你拿不准，先不进训练。
- `reject`：明显不合理，不进训练。

不填 `review_decision` 的行不会进入训练。

## Golden 单篇稿怎么判断

你只需要问一句：

> 这篇标题和正文，用户拿到后会不会觉得“有用、真实、能发布”？

可以就 `accept_ai`。

明显标题读不懂、正文很空、像模板、行业不对、编造事实，就 `needs_manual` 或 `reject`。

## Preference A/B 怎么判断

你只需要问一句：

> A 和 B 哪一篇更值得交付给用户？

认可 AI 建议就 `accept_ai`。

如果你觉得另一篇更好，就填：

- `review_decision=accept_with_edits`
- `review_winner=A` 或 `B`
- `review_preference_margin=1/2/3`
- `review_rationale=一句话说明为什么`

## 安全规则

- AI 预标注不会自动进入训练。
- 只有 `review_decision=accept_ai` 或 `accept_with_edits` 的行，才会被 `tools/promote_reviewed_prelabels.py` 提升成正式标签。
- 训练脚本仍会做健康审计；标签不够、类别单一、行业覆盖不足时仍会阻断。
- Claude 只能作为商业质量预审/主审候选，不能被当成天然真值；所有 AI 建议都必须保留来源、理由、置信度和分歧标记。
- 如果后续做全自动 AI-rubric consensus，标签来源必须写成 `ai_rubric_consensus`，不能写成人工标签；生成模型与评审模型同源时，还必须通过事实边界、v0.4 特征、自然度和第二评审分歧检查。
- Kimi 已作为第二评审接入。`kimi_*` 是独立复核结果，`judge_consensus` 表示首审与 Kimi 是否一致，`judge_disagreement_flags` 表示分歧原因。
- 如果 `judge_consensus=disagree` 或 `second_review_failed`，即使填写 `accept_ai`，提升工具也不会让它进入训练；必须人工确认并填写 `accept_with_edits`。

## 为什么不是直接让 Claude 定案

Claude 适合作为第一主审候选，是因为它能读懂长中文笔记、标题读感、正文节奏、行业语境和用户交付价值，能把大量样本先变成可审查的结构化建议。

但 Claude 不能单独定案。当前系统很多候选稿也是 Claude 生成的，如果再由 Claude 无约束打分，就会出现“自己生成、自己认可”的偏置。正确做法是：Claude 先给 rubric 判断，确定性特征和事实检查再做反证，低置信或分歧样本先搁置，不进入训练。

## 常用命令

生成 AI 预标注审核包：

```bash
.venv/bin/python tools/ai_prelabel_review_batch.py --kind golden --input quality/labeling_batches/v04_round01_golden.csv --batch-id v04_round01
.venv/bin/python tools/ai_prelabel_review_batch.py --kind golden --input quality/labeling_batches/v04_round01b_golden.csv --batch-id v04_round01b
.venv/bin/python tools/ai_prelabel_review_batch.py --kind preference --input quality/labeling_batches/v04_round01_preference.csv --batch-id v04_round01
.venv/bin/python tools/ai_prelabel_review_batch.py --kind preference --input quality/labeling_batches/v04_round01b_preference.csv --batch-id v04_round01b
```

生成带 Kimi 第二评审的审核包：

```bash
.venv/bin/python tools/ai_prelabel_review_batch.py --kind golden --input quality/labeling_batches/v04_round01_golden.csv --batch-id v04_round01 --second-review kimi
.venv/bin/python tools/ai_prelabel_review_batch.py --kind preference --input quality/labeling_batches/v04_round01b_preference.csv --batch-id v04_round01b --second-review kimi
```

审核后提升为正式标注文件：

```bash
.venv/bin/python tools/promote_reviewed_prelabels.py --kind golden --input quality/review_packets/v04_round01_golden_ai_review.csv --batch-id v04_round01
.venv/bin/python tools/promote_reviewed_prelabels.py --kind preference --input quality/review_packets/v04_round01_preference_ai_review.csv --batch-id v04_round01
```

只自动提升 Claude/特征首审与 Kimi 第二评审一致的样本：

```bash
.venv/bin/python tools/promote_reviewed_prelabels.py --kind golden --input quality/review_packets/v04_round01_kimi_golden_ai_review.csv --batch-id v04_round01_kimi_consensus --auto-accept-consensus
.venv/bin/python tools/promote_reviewed_prelabels.py --kind preference --input quality/review_packets/v04_round01b_kimi_preference_ai_review.csv --batch-id v04_round01b_kimi_consensus --auto-accept-consensus
```

`--auto-accept-consensus` 只接受 `judge_consensus=agree` 且无分歧标记的行；golden 标题或正文为空也不会被自动提升。
