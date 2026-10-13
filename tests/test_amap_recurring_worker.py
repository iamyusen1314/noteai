"""Offline worker faults, synthetic public HTML and policy metadata; no HTTP/DB prod.

SQLite controls SQL behavior; admission policy metadata is injected, not proof of
root-owned production mounts. Actual secure-file validation has separate cases.
"""
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'model'))
import amap_recurring_worker as worker
from tests import test_amap_recurring_budget as fixture

HTML='''<html><nav>OFFLINE NOT OFFICIAL {navigation}</nav><h2>月配额</h2><table>
<tr><th>服务名称</th><th>月配额</th></tr><tr><th>个人认证开发者</th>
<th>企业认证开发者 非商业目的 一年自注册认证 {header}</th><th>企业认证开发者（技术服务许可）</th></tr><tr>
<td>基础搜索服务 配额共享平台：API JS Android iOS 微信小程序</td>
<td>5,000</td><td>{quota}</td><td>500,000</td>{extra_cell}</tr></table>
<h2>高德开放平台乘风计划</h2>符合平台认定标准的企业免费提供为期{term}基础服务，定向邀请 {qualification}
<h2>购买流程</h2></html>'''

def html(**changes):return HTML.format(navigation=changes.get('navigation','sample'),quota=changes.get('quota','50,000'),term=changes.get('term','一年'),header=changes.get('header',''),qualification=changes.get('qualification',''),extra_cell=changes.get('extra_cell','')).encode()

class FakeObserver:
    def __init__(self,body,fail=False):self.body=body;self.fail=fail;self.http_reads=0;self.fetch_sha256=None
    def observe(self):
        if self.http_reads:raise worker.RulesUnknown('PUBLIC_RULES_READ_LIMIT')
        self.http_reads=1
        if self.fail:raise worker.RulesUnknown('PUBLIC_RULES_FETCH_HOLD')
        self.fetch_sha256=hashlib.sha256(self.body).hexdigest();return self.body

class MemoryState:
    def __init__(self,path):
        self.path=path;self.started={};self.results={};self.confirmed={};self.published=None;self.private=None;self.fail_finish=False
        self.public_path='/run/offline-public/rules-status.json';self.private_path='/run/offline-private/producer-rules-status.json'
    def rules_artifact(self,body):
        p=self.path/'OFFLINE-current-rules.json';p.write_bytes(body);return p
    def private_policy(self,value):self.private=dict(value);return self.private_path
    def policy(self,value):self.published=dict(value)
    def markers(self):return list(self.started.values())
    def marker(self,period):return self.started.get(period)
    def outcome(self,period):return self.results.get(period)
    def begin(self,marker):
        if marker['period'] in self.started:raise RuntimeError('duplicate attempt')
        self.started[marker['period']]=dict(marker)
    def finish(self,period,result):
        if self.fail_finish:raise RuntimeError('offline state fsync failure')
        if period in self.results:raise RuntimeError('outcome cannot be rewritten')
        self.results[period]=dict(result)
    def confirm(self,marker,readback):self.confirmed.setdefault(marker['period'],dict(readback))

class Loader:
    def __init__(self,prepared):self.prepared=prepared;self.has_rights=True
    def present(self):return self.has_rights
    def prepare(self,path):
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=self.prepared.metadata['official_rules_sha256']:
            raise worker.producer.RefreshError('AMAP_RECURRING_OFFICIAL_ARTIFACT_MISMATCH')
        return self.prepared

class WorkerTests(unittest.TestCase):
    rows=fixture.RecurringBudgetTests.rows
    prepare=fixture.RecurringBudgetTests.prepare
    def setUp(self):
        fixture.RecurringBudgetTests.setUp(self)
        self.prepared=self.prepare()
        self.rules_body=self.rules_artifact.read_bytes()
        self.state=MemoryState(self.path)
        self.state.private=self.rules_status()
        self.state.published=self.rules_status()
        self.loader=Loader(self.prepared)
        # Private producer approval is not the shared API approval during apply.
        self.rules_status=lambda: self.state.private
        self.policy_patch=mock.patch.object(worker.quota,'_read_rules_status',side_effect=lambda path:
            self.state.private if path==self.state.private_path else self.state.published)
        self.policy_patch.start();self.addCleanup(self.policy_patch.stop)
    def tick(self,*,fail=False,body=None):
        return worker.run_once(self.storage,entitlement_loader=self.loader,
            observer=FakeObserver(self.rules_body if body is None else body,fail),state_store=self.state,current_binding_verified=True)
    def app_environment(self):
        return dict(self.prepared.runtime,NOTEAI_AMAP_RECURRING_RULES_STATUS_FILE=self.state.public_path)
    def test_missing_rights_hold_without_http_or_attempt(self):
        self.loader.has_rights=False
        result=self.tick()
        self.assertEqual(result['state'],'HOLD');self.assertEqual(result['public_http_reads'],0)
        self.assertFalse(self.state.started);self.assertEqual(len(self.rows()),1)
    def test_monthly_success_then_noop_is_automatic_without_new_document(self):
        with mock.patch.object(worker.producer,'produce_month_budget',wraps=worker.producer.produce_month_budget) as producer:
            first=self.tick();second=self.tick()
        self.assertEqual(first['state'],'APPLY_ACKNOWLEDGED');self.assertEqual(second['state'],'CURRENT_MONTH_NOOP')
        self.assertEqual(sum(call.kwargs.get('apply') is True for call in producer.call_args_list),1)
        self.assertEqual(self.state.published['state'],'VERIFIED')
        self.assertEqual(len(self.rows()),2)
    def test_failed_observation_stops_existing_derived_admission_and_can_recover(self):
        self.tick()
        result=self.tick(fail=True)
        self.assertEqual(result['state'],'HOLD');self.assertEqual(result['public_http_reads'],1)
        with mock.patch.dict(worker.quota.os.environ,self.app_environment(),clear=True):
            with self.assertRaisesRegex(worker.quota.AmapQuotaError,'RULES_UNCONFIRMED'):
                worker.quota.admit('text',storage=self.storage)
        self.assertEqual(self.tick()['state'],'CURRENT_MONTH_NOOP')
        with mock.patch.dict(worker.quota.os.environ,self.app_environment(),clear=True):
            self.assertIsInstance(worker.quota.admit('text',storage=self.storage),worker.quota.Admission)
    def test_changed_rules_do_not_approve_themselves(self):
        self.tick();before=self.rows()
        result=self.tick(body=b'OFFLINE changed quota rule')
        self.assertEqual(result['state'],'HOLD');self.assertEqual(self.rows(),before)
        self.assertEqual(self.state.published['state'],'HOLD')
    def test_commit_unknown_exact_primary_read_can_confirm_without_reapply(self):
        self.storage.unknown_commit=True
        result=self.tick()
        self.assertEqual(result['state'],'APPLY_CONFIRMED_READONLY')
        self.assertEqual(self.state.results['2026-10']['status'],'commit_unknown')
        self.assertTrue(self.state.confirmed['2026-10']['binding_matches'])
        self.storage.unknown_commit=False
        self.assertEqual(self.tick()['state'],'CURRENT_MONTH_NOOP')
        self.assertEqual(len(self.rows()),2)
    def test_absent_unknown_is_not_rollback_and_never_reapplied(self):
        original=worker.producer.produce_month_budget
        def uncertain(storage,prepared,**kwargs):
            if kwargs.get('apply'):raise worker.producer.CommitUnknown()
            return original(storage,prepared,**kwargs)
        with mock.patch.object(worker.producer,'produce_month_budget',side_effect=uncertain) as produce:
            self.assertEqual(self.tick()['state'],'HOLD_APPLY_RESULT')
            self.assertEqual(self.tick()['state'],'HOLD_UNKNOWN_READONLY')
        self.assertEqual(sum(call.kwargs.get('apply') is True for call in produce.call_args_list),1)
        self.assertFalse(self.state.confirmed);self.assertEqual(len(self.rows()),1)
        self.assertEqual(self.state.published['state'],'HOLD')
    def test_known_insert_failure_consumes_attempt_and_preserves_original(self):
        self.storage.fail_readback=True
        self.assertEqual(self.tick()['state'],'HOLD_APPLY_RESULT')
        original=dict(self.state.results['2026-10'])
        self.storage.fail_readback=False
        self.assertEqual(self.tick()['state'],'HOLD_RECORDED_ATTEMPT')
        self.assertEqual(self.state.results['2026-10'],original)
        self.assertEqual(len(self.rows()),1)
    def test_result_fsync_failure_can_only_recover_by_exact_read(self):
        self.state.fail_finish=True
        self.assertEqual(self.tick()['state'],'HOLD_STATE_UNKNOWN')
        self.assertEqual(self.state.published['state'],'HOLD')
        self.state.fail_finish=False
        self.assertEqual(self.tick()['state'],'CURRENT_MONTH_NOOP')
        self.assertNotIn('2026-10',self.state.results)
        self.assertTrue(self.state.confirmed['2026-10']['binding_matches'])
        self.assertEqual(len(self.rows()),2)
    def test_shared_state_and_cli_report_do_not_leak_key_binding(self):
        report=self.tick()
        text=json.dumps([report,self.state.published,self.state.private,self.state.started,self.state.results])
        self.assertNotIn(fixture.KEY,text)
        self.assertNotIn(hashlib.sha256(fixture.KEY.encode()).hexdigest(),text)
        self.assertNotIn('"k"',text)

class PublicObserverTests(unittest.TestCase):
    def test_navigation_changes_do_not_change_semantics(self):
        a=worker.projection_bytes(worker.rules_projection(html(navigation='news yesterday')))
        b=worker.projection_bytes(worker.rules_projection(html(navigation='new navigation today')))
        self.assertEqual(a,b);self.assertNotEqual(hashlib.sha256(html(navigation='a')).digest(),hashlib.sha256(html(navigation='b')).digest())
    def test_quota_changes_change_digest_and_validity_unknown_holds(self):
        a=worker.projection_bytes(worker.rules_projection(html()))
        b=worker.projection_bytes(worker.rules_projection(html(quota='30,000')))
        self.assertNotEqual(a,b)
        for change in ({'qualification':'不得用于商业服务'}, {'header':'需额外申请'}, {'term':'一年半'},
                       {'extra_cell':'<td>商业用途禁止</td>'}):
            self.assertNotEqual(a,worker.projection_bytes(worker.rules_projection(html(**change))))
        with self.assertRaises(worker.RulesUnknown):worker.rules_projection(html(term='半年'))
        with self.assertRaises(worker.RulesUnknown):worker.rules_projection(b'<html>50,000 not a supported contract</html>')
    def test_one_fixed_https_read_and_no_cookie_or_auth_headers(self):
        class Response(io.BytesIO):
            status=200
            def geturl(self):return worker.quota.PUBLIC_RULES_URL
        opener=mock.Mock();opener.open.return_value=Response(html())
        observer=worker.PublicRulesObserver()
        with mock.patch.object(worker.urllib.request,'build_opener',return_value=opener):
            self.assertTrue(observer.observe())
            with self.assertRaisesRegex(worker.RulesUnknown,'READ_LIMIT'):observer.observe()
        self.assertEqual(opener.open.call_count,1)
        request=opener.open.call_args.args[0]
        self.assertEqual(request.full_url,worker.quota.PUBLIC_RULES_URL)
        self.assertNotIn('Cookie',request.headers);self.assertNotIn('Authorization',request.headers)
        self.assertIsNotNone(observer.fetch_sha256)
    def test_redirect_non200_and_parse_failure_hold_without_cached_success(self):
        with self.assertRaises(worker.RulesUnknown):worker._NoRedirect().redirect_request(None,None,302,None,None,'https://other.invalid')
        class Response(io.BytesIO):
            status=304
            def geturl(self):return worker.quota.PUBLIC_RULES_URL
        opener=mock.Mock();opener.open.return_value=Response(b'')
        with mock.patch.object(worker.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(worker.RulesUnknown):worker.PublicRulesObserver().observe()
        opener.open.return_value=Response(b'OFFLINE invalid contract');opener.open.return_value.status=200
        observer=worker.PublicRulesObserver()
        with mock.patch.object(worker.urllib.request,'build_opener',return_value=opener):
            with self.assertRaises(worker.RulesUnknown):observer.observe()
        self.assertIsNotNone(observer.fetch_sha256)

class PolicyFileTests(unittest.TestCase):
    """Real bytes, root ownership mocked explicitly on this non-root Mac."""
    def setUp(self):
        import tempfile
        self.temp=tempfile.TemporaryDirectory(prefix='amap-policy-offline-')
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'rules-status.json'
        self.path.write_text(json.dumps({'schema':'offline-not-official','state':'HOLD'}))
        self.path.chmod(0o600)
    def metadata(self,entry,*,directory=False,**changes):
        from types import SimpleNamespace
        fields={name:getattr(entry,name) for name in ('st_mode','st_uid','st_gid','st_nlink','st_size','st_dev','st_ino','st_mtime_ns','st_ctime_ns')}
        fields.update(st_uid=0,st_gid=0)
        if directory:fields['st_mode']=0o40700
        fields.update(changes);return SimpleNamespace(**fields)
    def read(self,*,unsafe_file=False,unsafe_directory=False,changed=False):
        real_fstat=worker.quota.os.fstat;real_lstat=Path.lstat
        def lstat(path):
            entry=real_lstat(path)
            if path==self.path:
                return self.metadata(entry,st_ino=entry.st_ino+1) if changed else self.metadata(entry)
            return self.metadata(entry,directory=True,st_mode=0o40777 if unsafe_directory else 0o40700)
        def fstat(fd):
            entry=real_fstat(fd)
            return self.metadata(entry,st_uid=501) if unsafe_file else self.metadata(entry)
        with mock.patch.object(Path,'lstat',lstat),mock.patch.object(worker.quota.os,'fstat',fstat):
            return worker.quota._read_rules_status(str(self.path))
    def test_bounded_metadata_read_with_approved_ownership_shape(self):
        self.assertEqual(self.read()['state'],'HOLD')
    def test_owner_directory_race_and_large_file_reject_before_use(self):
        for changes in ({'unsafe_file':True},{'unsafe_directory':True},{'changed':True}):
            with self.assertRaises(ValueError):self.read(**changes)
        self.path.write_bytes(b'x'*4096)
        with self.assertRaises(ValueError):self.read()
    def test_symlink_does_not_follow_target(self):
        link=self.path.parent/'link.json';link.symlink_to(self.path)
        with self.assertRaises((ValueError,OSError)):
            worker.quota._read_rules_status(str(link))
