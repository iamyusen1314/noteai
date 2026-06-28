# NoteAI Preference Labeling Guide v0.1

目标：标注“同一个用户需求下，哪一版标题和正文更值得交付”。偏好数据用于训练生成排序、二修选择和对话优化，不替代单篇 golden 质量分。

## 标注原则

只比较同一任务、同一素材、同一行业下的两个候选稿。

优先判断：

1. 哪一版用户更愿意直接复制发布。
2. 哪一版标题更自然、更能读懂、更有点击动机。
3. 哪一版正文更真实、具体、有信息密度。
4. 哪一版事实更安全，没有编造价格、背书、时间、适用人群。
5. 哪一版 AI 味更低，不像模板或评分特征拼接。

不要只看 v0.3 分数。分数高但标题读不懂、正文模板化，应输给分数略低但真实自然的稿子。

## Winner

- `A`：A 明显或略微更值得交付。
- `B`：B 明显或略微更值得交付。
- `tie`：两者质量接近，无法稳定区分。
- `skip`：两者不是同一任务、内容残缺、事实无法比较，跳过。

## Preference Margin

- `0`：打平或跳过。
- `1`：略胜，主要是标题/节奏/细节的小优势。
- `2`：明显更好，用户大概率会选这一版。
- `3`：压倒性更好，另一版存在明显不可交付问题。

## Reason Tags

常用胜出原因：

- `title_readability`
- `title_hook`
- `naturalness`
- `body_specificity`
- `info_density`
- `fact_safety`
- `industry_fit`
- `cta_fit`
- `less_template`
- `better_structure`
- `better_user_value`

常用失败原因：

- `title_unreadable`
- `title_weak_hook`
- `score_hacking`
- `body_template`
- `low_info_density`
- `fact_overclaim`
- `too_long`
- `too_short`
- `wrong_industry`
- `ai_smell`
- `missing_cta`
- `format_pollution`

## 交付判断

`delivery_ready_winner` 表示胜出稿是否可直接交付：

- `true`：胜出稿可以直接给用户复制发布，最多轻微润色。
- `false`：胜出稿只是比另一版好，但仍需要优化。

很多 A/B 对比会出现“两篇都不够好”。这种情况下仍然选择相对更好的一版，同时把 `delivery_ready_winner=false`。

## 重点样本

必须重点标注这些对比：

- v0.3 高分但标题拼接 vs 分数略低但自然。
- Claude 首稿 vs 交付质量二修。
- 交付质量二修 vs 人工自然稿。
- 对话优化前 vs 对话优化后。
- 事实完整但模板化 vs 事实安全且读感自然。

这些样本比随机真实笔记更能训练 NoteAI 的交付能力。
