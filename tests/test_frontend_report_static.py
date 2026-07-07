import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "NoteAI_Pro_Demo_Framer.html").read_text(encoding="utf-8")


class FrontendReportStaticTests(unittest.TestCase):
    def test_report_no_longer_contains_demo_diagnosis_copy(self):
        forbidden = [
            "致命弱点",
            "22:30",
            "11:30 重发",
            "购物清单",
            "AI 正在分析，数据加载后将显示具体建议",
            "赛道平均",
        ]
        for phrase in forbidden:
            with self.subTest(phrase=phrase):
                self.assertNotIn(phrase, HTML)

    def test_report_uses_backend_v04_metadata(self):
        self.assertIn("renderReportDimensions(dims", HTML)
        self.assertIn("renderFeatureCoverage(d.feature_schema", HTML)
        self.assertIn('id="featureSchemaCard"', HTML)
        self.assertNotIn("computeDimensions(d.features", HTML)

    def test_agent_evidence_renderer_supports_structured_sources(self):
        self.assertIn("function renderAgentEvidenceItem", HTML)
        self.assertIn("function formatAgentEvidenceValue", HTML)
        self.assertIn("agent-source-chip value", HTML)
        self.assertIn("agent-source-chip benchmark", HTML)
        self.assertIn("op.evidence_binding === 'v04_structured'", HTML)
        self.assertIn("evidence.slice(0,4).map(renderAgentEvidenceItem)", HTML)

    def test_market_timing_stale_state_is_explicit(self):
        self.assertIn("!!mt.data_stale", HTML)
        self.assertIn("freshness > 30", HTML)
        self.assertIn("行业热词未更新，市场时机证据已停用", HTML)
        self.assertIn("管道状态：", HTML)
        self.assertIn("XHS health", HTML)
        self.assertIn("趋势 worker", HTML)
        self.assertNotIn("freshness > 48", HTML)

    def test_pricing_page_uses_backend_billing_contract(self):
        self.assertIn("loadPricingConfig", HTML)
        self.assertIn("/billing/tiers", HTML)
        self.assertIn("renderPricingConfig", HTML)
        self.assertIn("已同步后端计费规则", HTML)
        self.assertNotIn("静态页，无需初始化", HTML)

    def test_screenshot_diagnosis_requires_every_uploaded_image_recognized(self):
        self.assertIn("let _ssOcrPromise = null", HTML)
        self.assertIn("let _ssOcrErrors = new Map()", HTML)
        self.assertIn("let _ssOcrStatus = new Map()", HTML)
        self.assertIn("let _ssOcrValidating = false", HTML)
        self.assertIn("await _ssOcrPromise", HTML)
        self.assertIn("function _getScreenshotRecognitionState()", HTML)
        self.assertIn("function updateDiagnosisSubmitState()", HTML)
        self.assertIn("id=\"diagnoseSubmitBtn\"", HTML)
        self.assertIn("btn.disabled = disabled", HTML)
        self.assertIn("AI 鉴别去重中", HTML)
        self.assertIn("正在识别图片 ${state.completed}/${state.total} 张", HTML)
        self.assertIn("ss-image-summary-list", HTML)
        self.assertIn("id=\"ss-tags-display\"", HTML)
        self.assertIn("话题：<span id=\"ss-tags-display\"", HTML)
        self.assertIn("function _normalizeSsTags", HTML)
        self.assertIn("function _splitSsBodyAndTags", HTML)
        self.assertIn("function _joinSsBodyAndTags", HTML)
        self.assertIn("const ssTags = _normalizeSsTags(_screenshotExtracted?.tags || '')", HTML)
        self.assertIn("desc = _joinSsBodyAndTags(ssBodyOnly, ssTags)", HTML)
        self.assertIn("tags:   splitValidated.tags", HTML)
        self.assertIn("tags: mergedTags", HTML)
        self.assertIn("（未识别到话题）", HTML)
        self.assertIn("图${i + 1} 内容", HTML)
        self.assertIn("识别图${i+1}", HTML)
        self.assertIn("请确认识别内容是否准确；如有偏差，可删除对应图片重传，或切换到手动填写补充标题/正文/话题", HTML)
        self.assertIn("const total = imgs.length", HTML)
        self.assertIn("ssState.pending > 0", HTML)
        self.assertIn("ssState.failed > 0 || ssState.ok !== ssState.total", HTML)
        self.assertIn("必须全部识别成功后才能诊断", HTML)
        self.assertIn("原因：${firstError}", HTML)
        self.assertIn("图片 AI 识别未成功，请重新上传或稍后重试", HTML)
        self.assertNotIn("只要有图片，就允许进入 AI 诊断", HTML)
        self.assertNotIn("任一识别成功才允许后续诊断", HTML)
        self.assertNotIn("_setScreenshotImageOnlyFallback", HTML)

    def test_rewrite_titles_show_length_and_refine_status(self):
        self.assertIn("rewrite-title-meta", HTML)
        self.assertIn("id=\"titleMeta0\"", HTML)
        self.assertIn("id=\"titleMeta1\"", HTML)
        self.assertIn("id=\"titleMeta2\"", HTML)
        self.assertIn("function renderRewriteTitleMeta", HTML)
        self.assertIn("16-20字", HTML)
        self.assertIn("title_meta", HTML)
        self.assertIn("title_was_compressed", HTML)
        self.assertIn("title_needs_refine", HTML)
        self.assertIn("需精修", HTML)
        self.assertIn("已语义压缩", HTML)
        self.assertIn("未压缩", HTML)
        self.assertNotIn("AI改写目标≤18字", HTML)

    def test_content_intent_controls_are_real_payload_fields(self):
        for text in ["真实种草型", "决策转化型", "测评避坑型", "清单攻略型"]:
            with self.subTest(text=text):
                self.assertIn(text, HTML)
        self.assertIn("function getContentIntentPayload", HTML)
        self.assertIn("content_intent", HTML)
        self.assertIn("merchant_visibility", HTML)
        self.assertIn("merchant_name", HTML)
        self.assertIn("fact_source_policy", HTML)
        self.assertIn("shouldAskMerchantBeforeRun(domain", HTML)
        self.assertIn("...intentPayload", HTML)
        self.assertIn("generate_context: diagCtx", HTML)
        self.assertIn("generateContext = { ...d, user_constraints: constraints, ...intentPayload }", HTML)
        self.assertNotIn("只展示创作方向，不传给后端", HTML)

    def test_library_chat_version_chain_passes_note_ids(self):
        self.assertIn("saved_note_id", HTML)
        self.assertIn("_diagnoseResult._saved_note_id = ev.saved_note_id", HTML)
        self.assertIn("async function ensureDiagnosisRootNote(note)", HTML)
        self.assertIn("note_id:          _chatParentNoteId || null", HTML)
        self.assertIn("note_id:          d._saved_note_id || null", HTML)
        self.assertIn("note_id:    note.id || null", HTML)
        self.assertIn("if (ev.saved_note_id || ev._saved_note_id)", HTML)
        self.assertIn("_chatParentNoteId = ev.saved_note_id || ev._saved_note_id", HTML)
        self.assertIn("saved_note_version", HTML)
        self.assertIn("version: ev.saved_note_version || ev._saved_note_version || null", HTML)
        self.assertIn("noteId:       _chatParentNoteId || null", HTML)
        self.assertIn("version:      _chatIterCount || null", HTML)
        self.assertIn("formatScoreValue(score)", HTML)
        self.assertIn("_chatIterCount    = _numOrNull(d._saved_note_version || d.version) || 1", HTML)
        self.assertGreaterEqual(HTML.count("_chatIterCount    = _numOrNull(note._saved_note_version || note.version) || 1"), 2)
        self.assertNotIn("_chatIterCount    = _numOrNull(note.version) || 1", HTML)
        self.assertNotIn("_chatIterCount    = note.version || 1", HTML)
        self.assertNotIn("txt.textContent = Math.round(score)", HTML)
        self.assertNotIn("_chatIterCount++;", HTML)

    def test_selected_diagnosis_plan_score_is_used_for_chat_start(self):
        self.assertIn("function diagnosisPlanScore(idx)", HTML)
        self.assertIn("selected_plan_score: selectedScore", HTML)
        self.assertIn("current_score:    currentScore", HTML)
        self.assertIn("selected_plan_score: note.selected_plan_score ?? null", HTML)
        self.assertIn("diagnosis_ces_percentile", HTML)
        self.assertIn("仅为诊断建议；点击方案后才进入对话", HTML)

    def test_report_library_profile_share_growth_loop_language(self):
        self.assertIn('id="reportLifecycleCard"', HTML)
        self.assertIn("function renderReportLifecycle", HTML)
        self.assertIn("function hydrateReportLifecycleWithNoteChain", HTML)
        self.assertIn("function findReportNoteGroup", HTML)
        self.assertIn("note_version_group", HTML)
        self.assertIn("已选对话方案", HTML)
        self.assertIn("v${latestVersionNum", HTML)
        self.assertIn("/notes?grouped=true", HTML)
        self.assertIn("本篇成长闭环", HTML)
        self.assertIn("function renderLibraryLifecycleStrip", HTML)
        self.assertIn("${renderLibraryLifecycleStrip(group)}", HTML)
        self.assertIn("预测-优化-真实表现闭环", HTML)
        self.assertIn("function renderProfileLoopInsights", HTML)
        self.assertIn("/notes/tracking", HTML)

    def test_generation_report_keeps_generate_context(self):
        self.assertIn("if (!_isGenerateMode && _diagnosePromise)", HTML)
        self.assertIn("? !!_generateResult", HTML)
        self.assertIn("if (_isGenerateMode)", HTML)
        self.assertIn("await autoSaveGeneratedNote(_generateResult)", HTML)
        self.assertIn("_isGenerateMode = true; showPage('report'); await populateReport();", HTML)
        self.assertNotIn("\n              autoSaveGeneratedNote(_generateResult);\n", HTML)

    def test_chat_surfaces_supplement_prompts_and_keeps_thinking_visible(self):
        self.assertIn("function chatAppendSupplementPrompts", HTML)
        self.assertIn("supplement_prompts: _diagnoseResult.supplement_prompts || []", HTML)
        self.assertIn("selected_plan_quality_issues", HTML)
        self.assertIn("chatAppendSupplementPrompts(data.supplement_prompts || [])", HTML)
        self.assertIn("补充真实信息后，优化会更稳", HTML)
        self.assertIn("data-supplement-field", HTML)
        self.assertIn("提交补充并优化", HTML)
        self.assertIn("payload.supplement_values = supplementValues", HTML)
        self.assertIn("supplement_values: values", HTML)
        self.assertIn("useCurrentAttachments: false", HTML)
        self.assertIn("先不补充这些信息，请在不编造事实的前提下继续优化", HTML)
        self.assertIn("仲裁专家 · 思考完成 · 已完整展示", HTML)
        self.assertIn("<span class=\"cthink-toggle\">完整展示</span>", HTML)
        self.assertNotIn("inp.value = item.action_text", HTML)
        self.assertNotIn("chatToggleThink(this)", HTML)
        self.assertNotIn("maxHeight = '0px'", HTML)
        self.assertNotIn("仲裁专家 · 思考完成 ▾ 点击展开", HTML)

    def test_chat_plan_options_render_as_selectable_cards(self):
        self.assertIn("case 'plan_options':", HTML)
        self.assertIn("function chatAppendPlanOptions", HTML)
        self.assertIn("function chatSelectPlan", HTML)
        self.assertIn("chat-plan-card", HTML)
        self.assertIn("data-plan-select", HTML)
        self.assertIn("选择并保存", HTML)
        self.assertIn("候选方案，选择后才保存为新版本", HTML)
        self.assertIn("API_BASE + '/chat/select-plan'", HTML)
        self.assertIn("option_id: optionId", HTML)
        self.assertIn("chatUpdateNote(ev.title, ev.body, ev.score, ev.grade", HTML)
        self.assertIn("chatAppendNoteUpdatedMsg(ev.score, ev.grade", HTML)
        self.assertIn("_chatAiBubble.innerHTML = chatMD(ev.summary)", HTML)


if __name__ == "__main__":
    unittest.main()
