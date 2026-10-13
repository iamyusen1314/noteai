"""Local function rendering only; no authenticated Admin or production UI proof."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('node'),'existing Node runtime required')
class AmapAdminRenderTests(unittest.TestCase):
    def render(self,state):
        source=(ROOT/'model/admin.html').read_text()
        function=source[source.index('function renderAmapAccountStatus('):source.index('\nfunction renderSupplierView(')]
        script='const esc=v=>String(v).replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;");\n'+function+'\nconsole.log(renderAmapAccountStatus('+json.dumps(state)+',"offline checked"));'
        result=subprocess.run([shutil.which('node'),'-e',script],capture_output=True,text=True,timeout=5,check=True)
        return result.stdout
    def snapshot(self):
        return dict(period='2026-11',time_zone='Asia/Shanghai',quota=50000,official_used=None,observed_at=None,
            source_kind='entitlement_derived_local_budget',source='noteai_recurring_monthly_budget_v1',
            unmetered_usage_upper_bound=3,admitted_in_local_budget=7,remaining=49990,
            budget_derived_at='offline derived',entitlement_valid_from='offline finite start',
            entitlement_valid_until='offline finite end',period_end='offline month end')
    def test_derived_shows_local_counts_and_unknown_official_use(self):
        text=self.render(dict(status='ready',snapshot=self.snapshot()))
        for phrase in ['官方当月已用量未知','不确定请求上界 3','本地已准入 7','本地账本剩余 49990','预算派生：offline derived','offline finite end']:
            self.assertIn(phrase,text)
        self.assertNotIn('官方观察 0',text);self.assertNotIn('受控已用 未知',text);self.assertNotIn('已安装',text)
    def test_held_budget_keeps_counts_but_reports_admission_pause(self):
        text=self.render(dict(status='recurring_hold',snapshot=self.snapshot()))
        self.assertIn('当前查询准入暂停',text);self.assertIn('本地已准入 7',text)
    def test_legacy_console_presentation_is_unchanged(self):
        snap=dict(period='2026-10',quota=50000,official_used=4,admitted_since_snapshot=7,remaining=49989,
            observed_at='offline console time',source='amap_console_base_search_statistics')
        text=self.render(dict(status='ready',snapshot=snap))
        self.assertIn('受控已用 11（官方观察 4，观察后本系统获准 HTTP 请求 7）',text)
        self.assertIn('账户观察：offline console time',text);self.assertNotIn('预算派生',text)
    def test_unknown_and_escaped_strings_do_not_invent_zero_or_html(self):
        self.assertIn('未知',self.render(dict(snapshot=None)))
        snap=self.snapshot();snap['entitlement_valid_until']='<img onerror="offline">'
        text=self.render(dict(status='ready',snapshot=snap))
        self.assertNotIn('<img',text);self.assertIn('&lt;img',text)
