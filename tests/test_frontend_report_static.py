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
        self.assertIn("await _ssOcrPromise", HTML)
        self.assertIn("function _getScreenshotRecognitionState()", HTML)
        self.assertIn("const total = imgs.length", HTML)
        self.assertIn("ssState.pending > 0", HTML)
        self.assertIn("ssState.failed > 0 || ssState.ok !== ssState.total", HTML)
        self.assertIn("必须全部识别成功后才能诊断", HTML)
        self.assertIn("原因：${firstError}", HTML)
        self.assertIn("图片 AI 识别未成功，请重新上传或稍后重试", HTML)
        self.assertNotIn("只要有图片，就允许进入 AI 诊断", HTML)
        self.assertNotIn("任一识别成功才允许后续诊断", HTML)
        self.assertNotIn("_setScreenshotImageOnlyFallback", HTML)

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


if __name__ == "__main__":
    unittest.main()
