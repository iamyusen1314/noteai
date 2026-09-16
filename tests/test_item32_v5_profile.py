"""Pure v5 Item32 plan/physical-proof checks, without provider or host execution."""
import copy
from contextlib import ExitStack
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import tempfile
import subprocess
from types import SimpleNamespace
import unittest
from unittest import mock

import execute_item32_readonly_trends_successor as e
ROOT=Path(__file__).resolve().parents[1]
PROFILE_GLOBALS=('ACTIVE_V5_PLAN','WORK_ROOT','IMAGE','EXPECTED_CONFIG_SHA256','EXPECTED_MANIFEST_SHA256',
                 'EXPECTED_IMAGE_SOURCE_SHA256','RUNTIME_OVERLAY_SHA256','RUNTIME_OVERLAY_CONTAINER_PATHS')

class V5ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)
        self.stack=ExitStack()
        for name in PROFILE_GLOBALS:self.stack.enter_context(mock.patch.object(e,name,copy.deepcopy(getattr(e,name))))
        self.plan=json.loads((ROOT/'deploy/production/plans/item32-v5-successor-prospective.json').read_bytes())
        self.plan['outer_executor_sha256']=hashlib.sha256(Path(e.__file__).read_bytes()).hexdigest()
        self.plan['runtime_overlay_sha256']={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in e.V5_OVERLAY_NAMES}
        self.plan['adapter_overlay_sha256']=self.plan['runtime_overlay_sha256'][e.ADAPTER_SOURCE_REF]
        self.plan['image_source_sha256']={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in e.IMAGE_SOURCE_CONTAINER_PATHS}
        self.plan['source_sha256']={**self.plan['image_source_sha256'],**self.plan['runtime_overlay_sha256']}
        day=(datetime.now(timezone.utc)+timedelta(days=1)).replace(hour=12,minute=0,second=0,microsecond=0)
        self.plan['admission'].update(not_before_utc=day.isoformat(),bucket_date_utc=day.date().isoformat(),
            dispatch_deadline_utc=(day+timedelta(minutes=40)).isoformat(),must_finish_before_utc=(day+timedelta(hours=1)).isoformat())
        records={}
        for prefix in ('item32-successor-package-20260915-79e1e35','item32-repair-package-20260915-fac5dd0'):
            for name in ('dispatch-started.json','dispatch-child.json','dispatch-done.json','dispatch.log'):
                records[f'/var/lib/noteai/{prefix}/{name}']={'bytes':1,'sha256':'a'*64}
        for name in ('item32-admission.json','run-synthetic/worker-receipt.json','run-synthetic/task-store/hot_keywords.db'):
            records[str(e.SEALED_SUCCESSOR_ROOT/name)]={'bytes':1,'sha256':'b'*64}
        self.plan['previous_successor']['files']=records
        self.authorize()
    def tearDown(self):self.stack.close();self.tmp.cleanup()
    def authorize(self):
        self.plan['authorization']={'status':'AUTHORIZED','confirmed_at_utc':datetime.now(timezone.utc).isoformat(),
                                    'approved_scope_sha256':e._approval_scope_sha256(self.plan)}
    def load(self):
        p=self.path/'plan.json';p.write_text(json.dumps(self.plan))
        return e._load_plan(p,Path(e.__file__),ROOT/e.ADAPTER_SOURCE_REF,ROOT/e.HOLD_EVIDENCE_REF)
    def test_new_plan_uses_bound_tracking_image_and_all_six_nested_overlays(self):
        loaded,_=self.load()
        self.assertEqual(e.IMAGE,'sha256:'+e.V5_CONFIG_SHA256)
        self.assertEqual(e.WORK_ROOT,e.V5_WORK_ROOT)
        self.assertEqual(loaded['physical_http_budget'],{'initialization':2,'collection':34,'total':36})
        self.assertEqual(e._runtime_overlay_paths(ROOT/e.ADAPTER_SOURCE_REF)['model/vendor/spider_xhs/v5/trends_bridge.js'],
                         ROOT/'model/vendor/spider_xhs/v5/trends_bridge.js')
    def test_pending_authority_leaves_legacy_profile_unchanged(self):
        before=e.IMAGE
        self.plan['authorization']['status']='PENDING'
        with self.assertRaisesRegex(e.Item32Error,'plan_not_authorized'):self.load()
        self.assertEqual(e.IMAGE,before);self.assertIsNone(e.ACTIVE_V5_PLAN)
    def test_changed_window_invalidates_previous_scope(self):
        self.plan['admission']['dispatch_deadline_utc']=(datetime.fromisoformat(self.plan['admission']['dispatch_deadline_utc'])-timedelta(minutes=1)).isoformat()
        with self.assertRaisesRegex(e.Item32Error,'plan_authorization_binding'):self.load()
    def test_old_image_or_widened_physical_budget_rejected_even_if_scope_rebound(self):
        for key,value in (('existing_image_config_sha256','a'*64),('physical_http_budget',{'initialization':3,'collection':34,'total':37})):
            saved=self.plan[key];self.plan[key]=value;self.authorize()
            with self.assertRaisesRegex(e.Item32Error,'plan_binding'):self.load()
            self.plan[key]=saved
    def test_omitted_prior_failed_identity_cannot_activate(self):
        self.plan['previous_successor']['files'].pop(next(iter(self.plan['previous_successor']['files'])))
        self.authorize()
        with self.assertRaisesRegex(e.Item32Error,'plan_binding'):self.load()
    def test_v5_preflight_compiles_bound_import_script_without_secret_or_network(self):
        self.load();unit=self.path/'unit';unit.write_bytes(b'synthetic unit')
        captured=[]
        def command(args,**kwargs):
            phase=kwargs.get('phase')
            if phase=='UNIT_FRAGMENT_READBACK':raw=str(unit).encode()
            elif phase=='TASK_CONTAINER_READBACK':raw=b''
            elif phase=='IMAGE_INSPECT':raw=json.dumps([{'Id':e.IMAGE,'Config':{'Labels':{'com.noteai.runtime.role':'xhs-http'},'Entrypoint':['/app/scripts/docker_entrypoint.sh'],'Cmd':['/bin/false']}}]).encode()
            elif phase=='IMAGE_SOURCE_CHECK':
                rows={**{e.IMAGE_SOURCE_CONTAINER_PATHS[k]:v for k,v in self.plan['image_source_sha256'].items()},'/app/model/vendor/spider_xhs/v5/upstream.json':e.V5_UPSTREAM_SHA256}
                raw='\n'.join(v+'  '+k for k,v in rows.items()).encode()
            elif phase=='RUNTIME_OVERLAY_CHECK':
                captured.append(args);compile(args[-1],'<v5-generated-import>','exec')
                raw=json.dumps({'protocol':'pc_v5','curl_cffi_version':'0.15.0','node_major':20,'upstream_manifest_sha256':e.V5_UPSTREAM_SHA256}).encode()
            else:raise AssertionError(phase)
            return subprocess.CompletedProcess(args,0,raw,b'')
        with mock.patch.object(e,'_validated_export_account'), mock.patch.object(e,'_assert_adapter_source'), mock.patch.object(e,'_assert_trends_unit_suspended'), mock.patch.object(e,'_assert_fixed_trends_container_absent'), mock.patch.object(e,'_remove_container'), mock.patch.object(e,'EXPECTED_UNIT_SHA256',hashlib.sha256(unit.read_bytes()).hexdigest()), mock.patch.object(e,'_run',side_effect=command):
            result=e._preflight_host(self.plan,ROOT/e.ADAPTER_SOURCE_REF)
        self.assertEqual(result['protocol'],'pc_v5');self.assertEqual(len(captured),1)
        args=captured[0];self.assertIn('--network=none',args);self.assertIn('--env=DATABASE_URL=',args)
        self.assertIn('--memory=256m',args);self.assertNotIn('--env-file',args)
        self.assertEqual(args.count('--mount'),6)
    def test_complete_cookie_context_accepts_legal_token_names_and_rejects_injection(self):
        self.load()
        path=self.path/'synthetic.env'
        cookies=[{'name':name,'value':'synthetic-value','domain':'.xiaohongshu.com','path':'/'}
                 for name in ('a1','web_session','x-test','!context')]
        def read():
            path.write_text('DATABASE_URL=postgresql://synthetic.invalid/test\nNOTEAI_XHS_COOKIES_JSON='+json.dumps(cookies)+'\n')
            metadata=SimpleNamespace(st_mode=0o100600,st_uid=0,st_gid=0,st_nlink=1,st_size=path.stat().st_size)
            with mock.patch.object(e.os,'lstat',return_value=metadata):return e._read_secret_env(path)
        self.assertEqual(len(json.loads(read()['NOTEAI_XHS_COOKIES_JSON'])),4)
        cookies[-1]['name']='invalid name'
        with self.assertRaisesRegex(e.Item32Error,'cookie_shape'):read()
    def test_collection_command_preserves_task_sqlite_and_bounded_v5_runtime(self):
        self.load();runtime=self.path/'runtime';runtime.mkdir()
        run=self.path/'run';run.mkdir();captured=[];cid='f'*64
        cookie_json=json.dumps([{'name':'a1','value':'synthetic-a1'},{'name':'web_session','value':'synthetic-session'}])
        storage=json.dumps({'xhs-pc-web':'synthetic-signing-context'})
        def command(args,**kwargs):
            if kwargs.get('phase')=='COLLECTION_CREATE':
                captured.append(args)
                self.assertEqual((runtime/'xhs.env').read_text(),
                    'NOTEAI_XHS_COOKIES_JSON='+cookie_json+'\nNOTEAI_XHS_WEB_SSK_JSON='+storage+'\n')
                return subprocess.CompletedProcess(args,0,cid.encode(),b'')
            if kwargs.get('phase')=='COLLECTION_INSPECT':
                env=[a.removeprefix('--env=') for a in captured[0] if a.startswith('--env=')]
                env+=['NOTEAI_XHS_COOKIES_JSON='+cookie_json,'NOTEAI_XHS_WEB_SSK_JSON='+storage]
                mounts=[{'Destination':'/task','Source':str(run/'task-store'),'RW':True}]
                mounts += [{'Destination':e.RUNTIME_OVERLAY_CONTAINER_PATHS[n],'Source':str(p),'RW':False}
                           for n,p in e._runtime_overlay_paths(ROOT/e.ADAPTER_SOURCE_REF).items()]
                value={'Image':e.IMAGE,'Config':{'Env':env,'Cmd':['python','market_timing_worker.py','--once']},
                       'Mounts':mounts,'HostConfig':{'ReadonlyRootfs':True,'Privileged':False,'CapDrop':['ALL']}}
                return subprocess.CompletedProcess(args,0,json.dumps([value]).encode(),b'')
            raise AssertionError(kwargs.get('phase'))
        with mock.patch.object(e.os,'chown'),mock.patch.object(e,'_assert_adapter_source'),mock.patch.object(e,'_run',side_effect=command):
            e._create_collection_container(run,runtime,cookie_json,ROOT/e.ADAPTER_SOURCE_REF,{},storage)
        args=captured[0]
        self.assertIn('--env=DATABASE_URL=',args);self.assertIn('--env=NOTEAI_XHS_PROTOCOL=pc_v5',args)
        self.assertIn('--env=NOTEAI_XHS_V5_BUDGET_JSON={"initialization":2,"collection":34,"total":36}',args)
        self.assertEqual(args.count('--mount'),7)
        self.assertFalse((runtime/'xhs.env').exists())
    def proof_fixture(self):
        start=datetime.fromisoformat(self.plan['admission']['not_before_utc'])
        observations=[];attempts=[]
        for i,kind in enumerate(['dsl','session',*e.ENDPOINT_SEQUENCE]):
            first=start+timedelta(seconds=1+i*2);last=first+timedelta(seconds=1)
            observations += [{'phase':'dispatch','request_kind':kind,'sequence':i+1,'at':first.isoformat(),'request_body_bytes':1},
                {'phase':'response','request_kind':kind,'sequence':i+1,'at':last.isoformat(),'response_bytes':1,
                 'response_diagnostics':{'http_status':200,'payload_kind':'object','success_state':'true','business_code':0,'business_code_kind':'integer'}}]
            if i>=2:attempts.append({'endpoint':kind,'status':'succeeded','admitted_at':first.isoformat(),'completed_at':last.isoformat()})
        receipt={'exit_code':0,'provider_failures':[],'secret_values_recorded':False,'physical_http_observations':observations}
        run={'started_at':start.isoformat(),'completed_at':(start+timedelta(seconds=80)).isoformat()}
        return receipt,run,attempts
    def proof(self,receipt,run,attempts):
        self.load()
        (self.path/'worker-receipt.json').write_text(json.dumps(receipt))
        return e._v5_physical_proof(self.path,self.plan,run,attempts)
    def test_complete_36_physical_events_cross_bind_original_34_admissions(self):
        result=self.proof(*self.proof_fixture());self.assertEqual(result['total_count'],36)
        self.assertEqual(result['initialization_count'],2);self.assertEqual(result['collection_count'],34)
    def test_http200_business_failure_is_not_accepted(self):
        r,run,a=self.proof_fixture();r['physical_http_observations'][3]['response_diagnostics']['business_code']=-3
        with self.assertRaisesRegex(e.Item32Error,'physical_http_business_failure'):self.proof(r,run,a)
    def test_unknown_or_duplicate_physical_event_rejects(self):
        r,run,a=self.proof_fixture();r['physical_http_observations'][5]['phase']='unknown'
        with self.assertRaisesRegex(e.Item32Error,'physical_http_evidence'):self.proof(r,run,a)
    def test_unbound_collection_admission_rejects(self):
        r,run,a=self.proof_fixture();a[0]['endpoint']='search_notes'
        with self.assertRaisesRegex(e.Item32Error,'physical_http_admission_binding'):self.proof(r,run,a)
    def test_physical_dispatch_outside_approved_window_rejects(self):
        r,run,a=self.proof_fixture();r['physical_http_observations'][0]['at']=(datetime.fromisoformat(run['started_at'])-timedelta(seconds=1)).isoformat()
        with self.assertRaisesRegex(e.Item32Error,'physical_http_window'):self.proof(r,run,a)

if __name__=='__main__':unittest.main()
