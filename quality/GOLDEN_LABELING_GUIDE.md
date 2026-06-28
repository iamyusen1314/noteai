# NoteAI Golden Labeling Guide v0.1

目标：把“用户愿意付费的交付质量”从单一模型分，拆成可标注、可训练、可复查的质量目标。

## 核心标签

`human_quality_score`：0-100，人工综合质量分。

- 90-100：可直接交付，标题自然有吸引力，正文真实、具体、行业感强。
- 80-89：可交付，有少量可优化点，但用户大概率认可。
- 70-79：接近可交付，需要小修。
- 60-69：有价值但不够成稿，需要明显优化。
- 40-59：结构或表达有明显问题，不应作为最终稿交付。
- 0-39：低质、空泛、事实风险、标题读不懂或明显 AI 模板。

`delivery_ready`：是否可以作为最终稿交付给用户。

- true：允许进入用户可复制/发布状态。
- false：只能进入对话优化或重新生成。

`naturalness_label`：人工自然度评分，不等同于 AI 检测模型分。

- 高分：像真实用户经验，有人称、取舍、细节和自然节奏。
- 低分：模板腔、堆特征、堆形容词、标题拼接、像营销稿或 AI 方案。

`fact_status`：

- verified：关键事实有来源或用户明确提供。
- safe：没有编造具体数字/背书，表达安全。
- unknown：事实不足，但没有明显越界。
- overclaim：编造价格、评分、营业时间、权威背书、节假日场景等。

`ai_smell_level`：1-5。

- 1：几乎无 AI 味。
- 2：略规整，但可接受。
- 3：有模板痕迹，需要小修。
- 4：AI 味明显，不建议交付。
- 5：强模板/拼接/评分黑客，不可交付。

## 常用 failure_tags

- `title_unreadable`
- `title_weak_hook`
- `score_hacking`
- `body_template`
- `low_info_density`
- `fact_overclaim`
- `missing_fact`
- `missing_cta`
- `too_short`
- `too_long`
- `wrong_industry`
- `v03_domain_bias`
- `needs_minor_revision`
- `delivery_ready`

## 使用原则

- v0.3/v0.4/naturalness 都只是信号，人工标签是训练目标。
- fitness 等被 v0.3 系统性压分的样本，如果人工看是好稿，应标为好稿，并打 `v03_domain_bias`。
- 自然度模型如果误伤某行业好稿，不改人工标签，后续用标签校准模型。
