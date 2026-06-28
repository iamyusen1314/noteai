# NoteAI Pro — 开发进程日志

---

## v0.5  P3 Thinking 修复 + 评分突破 74 分（2026-05-06）

### 核心目标达成
- `/generate` 评分从 62-67 分提升至实测 **74.2 分**，稳定超过目标 70 分
- P3 仲裁首次真正使用 thinking 模式完成（之前 100% fallback 到 fast mode）
- 总生成耗时从 449s 压缩至 **183s**

### 三个关键修复（model/api.py）

| 问题 | 根因 | 修复方案 |
|------|------|---------|
| P3 thinking 每次超时 fallback | `_KIMI_TIMEOUT_THINK.read=90s`，Kimi 思考完成后有 >90s 静默期再输出 content，触发 read timeout | `read` 从 `90s` 改为 `600s` |
| thinking 完成但总超时 504 | `max_tokens=32768` 导致思考链超长（16448 chunks），总耗时 >660s | `max_tokens` 从 `32768` 改为 `16000`（官方最低建议值） |
| 模型版本 | 使用 `kimi-k2.6`，thinking 耗时偏长 | 切换至 `kimi-k2.5`（同样支持 thinking，256K 上下文） |

### 技术细节

**为什么 max_tokens=32768 这么慢？**
- Kimi K2 thinking 模式下，`reasoning_content` 和 `content` 共享 `max_tokens` 预算
- 32768 token 预算 → 思考链消耗 ~16448 chunks ≈ 640s
- 16000 token 预算 → 思考链压缩至 ~4976 chunks ≈ 181s
- 官方文档建议：`max_tokens >= 16000` 避免输出不完整

**P3 thinking 验证结果（日志证据）：**
```
[kimi_stream] chunk#0 delta_keys=['role', 'content'] finish=None
[kimi_stream] chunk#1 delta_keys=['reasoning_content'] finish=None   ← 思考链流式输出
[kimi_stream] chunk#4976 delta_keys=[] finish=stop
[kimi_stream] DONE received, content_parts=409                        ← 完整输出
[gen] P3-arbitrate done in 181s title_len=20 body_len=408
[gen] P4-refine round=0 score=74.2                                    ← 74.2分！
```

### 其他改进（同步完成）

- `_build_fix_instructions` 新增 `plad_avg_sentence_len` 检查：若草稿平均句长 <33 字，Pre-P3 阶段注入明确修复指令
- `compute_market_timing` 调用前增加 `_DOMAIN_ALIASES` 归一化，确保 `category_saturation` 取到正确域统计值（如 "餐饮" → "美食" → `saturation=0.028`）
- `_GEN_CHECKLISTS` ⑪⑫ 强化句子节奏要求（已在 v0.4 写入，本版验证有效）

### 生成耗时对比

| 阶段 | 修复前 | 修复后 |
|------|--------|--------|
| P1 视觉分析 | ~5s | ~7s |
| P2 三专家并行 | ~14s | ~20s |
| P3 仲裁（thinking）| 449s fallback / 660s+ 超时 | **181s 完整完成** |
| P4 评分 | ~10s | ~10s |
| **总计** | **449s（fast mode 结果）** | **183s（thinking 结果）** |

---

## v0.4  对话式笔记优化 + 评分修复（2026-05-05）

### 核心目标达成
- `/generate` 端点评分突破 70 分（实测 **71.1 分**），达到爆文目标
- 新增完整的「对话式笔记优化」工作流，支持从生成 → 对话 → 重写的闭环

### 三个关键 Bug 修复（model/api.py）

| Bug | 影响 | 修复方案 |
|-----|------|---------|
| `feature_extraction.py` DOMAIN_MAP 缺少 `'餐饮'` 别名 | 品类编码落到 `others`(10)，评分天花板 ~50 | 新增 `'餐饮': 'food'` 等别名映射 |
| `api.py _get_dk()` 缺少别名 | `_get_dk('餐饮')` 返回 generic 品类知识，Agent 建议质量下降 | 新增 `_DOMAIN_ALIASES`，查询前先做别名归一化 |
| 5 个 Agent 未与 v0.3 模型训练结合 | 生成内容靠 prompt，分值不稳定 | 新增 Pre-P3 评分步骤：P2 后先对草稿调用 `_predict()`，把特征缺口作为 `v0.3模型分析` 上下文注入 P3 仲裁 |

### 生成质量提升（_GEN_CHECKLIST + _build_fix_instructions）
- 标题交付：14-18字 · 城市名/核心卖点 · 情绪词 · 数字 · 疑问词仅自然使用
- 美食正文交付：260-360字（不含标签）· 价格 · 地址 · 营业时间 · 「排队」关键词
- 表情符号：最多 3 种不同类型（`plad_unique_emoji_ratio ≤ 0.4`）
- 话题标签：恰好 5 个（含城市词）
- 互动结尾：「点赞」+「收藏」+疑问句

### 新端点（model/api.py）

| 端点 | 方法 | 说明 |
|------|------|------|
| `/chat/start` | POST | 初始化对话会话；支持传入 `generate_context`（完整 `/generate` 响应）作为上下文 |
| `/chat/message` | POST | SSE 流式响应（`thinking_start/chunk/end`、`content_chunk`、`note_update`、`learning`、`done`） |
| `/chat/ui` | GET | 独立对话优化界面（`chat_ui.html`） |

### 对话优化框架（model/api.py + model/chat_ui.html）

**完整工作流：**
```
/generate 生成 → 传入 generate_context → /chat/start
  → 多轮对话（fast/thinking 模式自动切换）
  → AI 重写 → 自动评分 → note_update 实时更新笔记预览
  → 学习信号 → user_learn SQLite → 越用越懂你
```

**`generate_context` 注入内容：**
- `expert_opinions`：5 个专家 Agent 的原始意见摘要
- `feature_hits`：v0.3 模型特征命中/未命中明细
- `cover_analysis`：封面视觉分析结果
- `title_variants`：备选标题列表
- `ces_percentile` / `grade`：初始评分（避免重复计算）

**`越用越懂你` 机制：**
- SQLite `user_learn` 表按 `user_id` 存储偏好
- 识别拒绝信号（"太广告了" → `tone:接地气`）、认可信号（"就这个" → 记录标题风格）
- 下次对话自动注入 system prompt，AI 记住用户习惯

**思考链动画：**
- `thinking_start` → 弹出带转圈动画的「深度思考中」展示块
- `thinking_chunk` → 实时追加推理过程（可展开/收起）
- `thinking_end` → 折叠为「💡 深度思考完成」，点击可展开全文

### 前端更新（NoteAI_Pro_Demo_Framer.html）
- 新增导航 Tab：**💬 对话优化**（第 7 个）
- 生成结果页新增 **「开始对话优化」横幅**：点击传入完整 `_generateResult` 作为 `generate_context`
- 新增 `#page-chat` 页面（暗色主题两栏布局）：
  - 左栏：笔记预览 · 版本迭代计数 · 动态评分 gauge · 越用越懂你徽章
  - 右栏：多轮对话 · 快捷操作按钮 · 思考链动画 · 笔记更新通知
- `showPage` 映射扩展：`chat: 6`

---

## v0.3  模型升级 · 62 特征版本（2026-05-05）

### 模型 Model A v0.3
| 指标 | v0.1 | v0.2 | v0.3 |
|------|------|------|------|
| 特征数 | 28 | 59 | 62 |
| 训练集 | 91,517 | 101,517 | 101,517 |
| Val RMSE | ~16.x | 12.4334 | **12.2987** |
| Acc ±10pt | — | 81.95% | **82.34%** |
| 语义特征 | 无 | 无 | Kimi 标注 |

### 特征工程变更

#### PLAD 特征扩展（4 → 13）
基于 RedNote-Vibe 论文（arXiv 2509.22055）Table 2，PLAD 特征从 4 个扩展至 13 个：

新增特征：
- `plad_ttr`（词汇丰富度，Type-Token Ratio）
- `plad_sentence_count`（句子数量）
- `plad_avg_sentence_len`（平均句长）
- `plad_sentence_burstiness`（句子节奏变化度，CV 公式）
- `plad_emoji_density`（表情符号密度）
- `plad_unique_emoji_ratio`（独特表情比率）
- `plad_number_ratio`（数字占比）
- `plad_word_burstiness`（词频分布自然度）
- `plad_immediate_repetition`（连续词语重复率）

技术修正：原 emoji 正则 `\U000024C2-\U0001F251` 范围覆盖 CJK 字符（U+3400-U+9FFF），导致所有中文文本 emoji_density ≈ 0.85。已替换为精确的 Unicode 块列表，修正后均值降至 ~0.013。

#### 语义特征（新增，Kimi LLM 标注）
- `semantic_emotional_intensity`（情感强度，0-1）
- `semantic_empathetic_engagement`（共情度，0-1）
- `semantic_rhetorical_score`（修辞水平，0-1）

标注方案：Kimi moonshot-v1-8k，batch-size=5，workers=5，60,161 条唯一笔记，约 12,033 次 API 调用。选 batch=5 而非 20 的原因：输入 payload 超过 HTTP 限制（20 条 × 300 字 ≈ 6000 字），且小批次减少上下文干扰、提升每条评分精度。

#### 封面视觉特征（延续 v0.2）
14 个视觉特征（cover_brightness / warmth / saturation / contrast / sharpness / aspect_ratio / has_face / face_count / has_text / text_prominence / composition_score / aesthetic_score / emotion_intensity / visual_clarity），由 Kimi Vision 或 OpenCV 规则引擎提取。

#### 发布时机嵌入特征（延续 v0.2）
8 个 timing 特征（来自 `timing_features.parquet`），在训练阶段嵌入模型，预测时由 API 输入 0.0 作为中性值（timing 信号已通过训练集均值隐含编码）。

### 三路径训练数据
- **Path A**（91,517 条）：exploring_set.jsonl → 37 内容特征 + 3 语义特征 + 8 timing
- **Path B**（10,000 条）：cover_metadata_v2 × cover_features_v2 → 8 标题特征 + 14 视觉 + 8 timing
- **Path C**（disabled）：training_set_human 因 liked_count 均值差异（50 vs 2834，56×）导致 CES 标签噪声，暂停启用

### API 更新（api.py）

所有三个推理端点现已实时调用 Kimi 获取语义特征：
- `/score` — 新增 `compute_semantic_features()` 调用（之前固定 0.5）
- `/diagnose` — 新增 `compute_semantic_features()` 调用（之前固定 0.5）
- `/analyze` — 原已正确调用 ✓

`compute_semantic_features()` 实现：单次 Kimi 调用，max_tokens=120，temperature=0.1，timeout=10s，失败时回退到 0.5 defaults。

`_predict()` 自动检测：`has_semantic = n_model_features > (37 + 14 + 8)` 判断模型是否包含语义特征，向后兼容旧模型。

### 前端更新（NoteAI_Pro_Demo_Framer.html）

新增**技术引擎**页（第 6 个导航 Tab）：
- 英雄区：动态计数器（10万+笔记 / 62维特征 / 82.34%准确率 / RMSE 12.30）
- 四维特征展示系统：标签切换（内容文本 / 语义情感 / 视觉封面 / 发布时机）
- 62 个特征卡片：每卡含特征名、中文描述、作用说明
- Top-15 特征重要性横条图（gain importance from LightGBM）
- Holo 渐变动效（#FF6FD8 → #7B61FF → #00D4FF），符合 DESIGN.md 设计规范

---

## v0.2  特征扩展 · 59 特征版本（2026-04-下旬）

- PLAD 特征从 v0.1 的 4 个扩展至 9 个中间版本
- 新增 14 维封面视觉特征（cover_features_v2.parquet）
- 新增 8 维 timing 嵌入特征
- Path B 数据（cover_metadata_v2 × 10,000 条）接入训练
- Val RMSE 12.4334，Acc ±10pt 81.95%
- 修复 emoji 正则 Bug（CJK 字符误判）

---

## v0.1  基线版本（2026-04）

- LightGBM 回归，28 个内容特征
- 训练集：91,517 条 exploring_set.jsonl
- 目标变量：CES 分位（0-100，品类内 liked_count 百分位）
- API：/score / /diagnose / /analyze 三端点
- 前端：NoteAI_Pro_Demo_Framer.html 初版（上传 → 实时诊断 → 报告 → 成长档案）
- 市场时机系统：Scheduler A（每 6 小时热词更新）+ hot_keywords.db（2581 条热词）

---

## 当前技术栈快照（2026-05-05）

| 层级 | 组件 | 说明 |
|------|------|------|
| 推理模型 | LightGBM Booster | model_a_v0.3.lgb，62 特征，<50ms CPU |
| 语义标注 | Kimi moonshot-v1-8k | 批量标注 + 实时推理双模式 |
| 视觉特征 | Kimi Vision / OpenCV | 封面 14 维特征，/analyze 调用 Vision |
| 大模型诊断 | Claude Haiku 4.5 | 结构化输出（diagnosis/titles/plan/body） |
| 用户记忆 | mem0 | 跨会话个性化，/analyze 接入 |
| 热词感知 | Scheduler A + hot_keywords.db | 每 6 小时更新，2581+ 条热词 |
| 实验跟踪 | MLflow（SQLite） | 所有训练版本指标存档 |
| API 框架 | FastAPI + uvicorn | PORT 8000，CORS 全开 |

---

## 待办 / 下一步

- [ ] Path C 重启：设计品类内 CES 百分位归一化方案（消除 56× 基数差异）
- [ ] timing_features_human.parquet 与 human 训练集对齐
- [ ] /score 和 /diagnose 端点增加语义特征缓存（避免重复 Kimi 调用）
- [ ] 前端技术引擎页接入真实 /health 特征统计
- [ ] 分品类子模型（美食 / 美妆 / 旅行）独立训练
