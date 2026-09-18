"""Offline phase and once-only orchestration checks; never contacts F or XHS."""
import copy
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools import run_item33_trends_promotion as outer
from tests.test_item33_trends_runtime_cli import plan_fixture


class MemoryStore:
    def __init__(self):self.files={}
    def exists(self,ref):return ref in self.files
    def put(self,ref,raw):
        if self.exists(ref):raise FileExistsError('retained')
        self.files[ref]=raw;return outer.sha(raw)
    def json(self,ref,value):return self.put(ref,outer.encoded(value))
    def read(self,ref):return self.files[ref]
    def value(self,ref):return json.loads(self.read(ref))


class Ports:
    def __init__(self,plan):
        self.plan=plan;self.calls=[];self.captured={};self.dependencies={'real':'verified'};self.capture_binding={'actual':'binding'}
        self.actions=SimpleNamespace(**{name:self.action(name) for name in ('promote_unit','rollback_unit','reapply_unit','normal_handoff_once')})
    def action(self,name):
        def call(auth):self.calls.append(name);return {'action':name}
        return call
    def resource_inventory(self):return {'bound_original_host_verified':True,'synthetic_sha256':'a'*64}
    def recovery_host(self):self.calls.append('recovery_host');return {'synthetic_stopped':True}
    def managed_runtime(self,database,host):return {'synthetic_runtime':True}
    def configure(self,value):self.calls.append('configure')
    def readonly(self,mode,**kwargs):
        self.calls.append((mode,kwargs.get('phase',mode)))
        if mode=='prepare-install' or mode=='prepare-teardown':
            text='BEGIN;\nSELECT 1;\nCOMMIT;\n'
            return {'state':'SQL_PREPARED_NOT_EXECUTED','sql':text,'sql_sha256':outer.sha(text.encode()),'control_plane_ddl_count':29}
        if mode=='finalize-config':
            config=outer.runtime_cli.initial_config(self.plan)
            return {'state':'CONFIGURATION_VERIFIED_NOT_RUNNING','config':config,'config_sha256':outer.sha(outer.capture.encoded(config))}
        if mode=='finalize-teardown':return {'sql_sha256':outer.sha(b'BEGIN;\nSELECT 1;\nCOMMIT;\n'),'synthetic':True}
        return {'run_identity_sha256':'b'*64,'snapshot':{'payload':{}},'phase':kwargs.get('phase',mode)}
    def read_capture(self,name):return self.captured[name]
    def write_capture(self,name,raw,mode=0o600):
        if name in self.captured:raise FileExistsError(name)
        self.calls.append(('write',name,mode));self.captured[name]=raw
    def stage_runtime(self):self.calls.append('verify_overlays')
    def start_ready(self):self.calls.append('start_ready')
    def failure_cleanup(self):self.calls.append('cleanup')
    def host(self,phase):self.calls.append(('host',phase));return {'phase':phase}
    def http(self,database):self.calls.append('actual_http');return {'worker_receipt':{}}
    def seal_close(self):
        self.calls.append('seal_close')
        self.captured['capture-seal.json']=b'{}';self.captured['production-item33-trends-dml-journal.jsonl']=b'synthetic'
        return b'{}',b'synthetic'


class OuterTests(unittest.TestCase):
    def setUp(self):
        self.plan=plan_fixture();self.now=outer.clock(self.plan['starts_at'])
        self.plan.update(status='AUTHORIZED',authorization_kind='standing_follow_on',authorization_basis=outer.BASIS,
            recorded_at=(self.now-timedelta(days=1)).isoformat())
        self.store=MemoryStore();self.ports=Ports(self.plan)
        self.runner=outer.Outer(plan=self.plan,sources={'item33-runtime-plan.json':'a'*64,outer.teardown.SOURCE_REF:'c'*64},store=self.store,ports=self.ports,current=lambda:self.now)
    def mark(self,phase):self.store.json(phase+'.result.json',{'state':'COMPLETED'})
    def configured(self):
        self.mark('finalize-config');self.store.json('finalize-config.facts.json',self.ports.readonly('finalize-config'))
    def test_plan_preserves_standing_authorization_without_fabricated_confirmed_at(self):
        self.assertNotIn('confirmed_at',self.runner.plan)
        for change in ({'status':'PENDING'},{'authorization_kind':'new_approval'},{'authorization_basis':'invented'}):
            with self.subTest(change=change),self.assertRaises(outer.OuterError):outer.validate_plan(self.plan|change)
    def test_expired_dispatch_rejects_before_any_marker_or_operation(self):
        self.now=outer.clock(self.plan['dispatch_before'])
        with self.assertRaisesRegex(outer.OuterError,'dispatch_window'):self.runner.run('rehearse')
        self.assertEqual(self.store.files,{});self.assertEqual(self.ports.calls,[])
    def test_prepare_only_exports_sql_and_second_call_never_reissues_probe(self):
        self.runner.run('prepare-install');saved=dict(self.store.files)
        with self.assertRaisesRegex(outer.OuterError,'once_readback_only'):self.runner.run('prepare-install')
        self.assertEqual(self.store.files,saved);self.assertEqual(self.ports.calls,[('prepare-install','prepare-install')])
        self.assertTrue(self.store.read('install.sql').startswith(b'BEGIN;'))
    def test_unknown_is_retained_and_readback_only_has_no_callback(self):
        def fail(*a,**k):raise RuntimeError('SECRET synthetic not for output')
        self.ports.readonly=fail
        with self.assertRaises(outer.OuterError):self.runner.run('prepare-install')
        self.assertEqual(self.store.value('prepare-install.result.json')['state'],'UNKNOWN_READBACK_ONLY')
        self.assertNotIn('SECRET',str(self.store.files));self.ports=None;self.runner.ports=None
        value=self.runner.readback();self.assertEqual(value['provider_calls'],0);self.assertEqual(value['database_connections'],0)
        self.assertEqual(value['phases']['rehearse']['state'],'NOT_STARTED')
        with self.assertRaisesRegex(outer.OuterError,'once_readback_only'):self.runner.run('prepare-install')
    def test_finalize_requires_actual_committed_matching_operator_receipt(self):
        self.runner.run('prepare-install')
        receipt={'schema':'noteai.item33.capture_install_execution.v1','status':'COMMITTED',
            'activation_identity_sha256':self.plan['activation_identity_sha256'],'operator_role':'noteai_admin',
            'sql_sha256':self.store.value('prepare-install.facts.json')['sql_sha256'],'control_plane_ddl_count':29,
            'outcome_unknown_count':0,'started_at':self.now.isoformat(),'committed_at':self.now.isoformat()}
        self.ports.captured['operator-install-execution.json']=outer.encoded(receipt)
        value=self.runner.run('finalize-config')
        self.assertEqual(value['result']['state'],'CONFIGURATION_VERIFIED_NOT_RUNNING')
        self.assertIn(('write','runtime-config.json',0o444),self.ports.calls)
        self.assertEqual(self.ports.captured['runtime-config.json'],outer.capture.encoded(self.store.value('finalize-config.facts.json')['config']))
        self.assertNotIn('start_ready',self.ports.calls)
    def test_bad_install_receipt_stops_before_config_probe(self):
        self.runner.run('prepare-install');self.ports.captured['operator-install-execution.json']=b'{}'
        with self.assertRaises(outer.OuterError):self.runner.run('finalize-config')
        self.assertNotIn(('finalize-config','finalize-config'),self.ports.calls)
    def test_rehearsal_order_seals_and_removes_collector_before_state_rollback_reapply(self):
        self.configured()
        def driver(**kw):
            kw['read_preflight']();kw['promote_unit']({});kw['read_single_cycle']({});kw['read_promoted']()
            kw['rollback_unit']({});kw['read_rollback']();kw['reapply_unit']({});kw['read_final']()
            return {'run_identity_sha256':'b'*64,'cycle':{'run_identity_sha256':'b'*64}}
        with mock.patch.object(outer.controller,'execute_item33_promotion',side_effect=driver),mock.patch.object(outer.capture,'verify_capture_artifacts',return_value={}),mock.patch.object(outer.facts,'compose_preflight',return_value={}),mock.patch.object(outer.facts,'compose_cycle',return_value={'run_identity_sha256':'b'*64}),mock.patch.object(outer.facts,'compose_state',return_value={}):
            result=self.runner.run('rehearse')
        calls=self.ports.calls
        self.assertLess(calls.index('start_ready'),calls.index(('preflight','preflight')))
        self.assertLess(calls.index('promote_unit'),calls.index(('cycle','cycle')))
        self.assertLess(calls.index('actual_http'),calls.index('seal_close'))
        self.assertLess(calls.index('seal_close'),calls.index(('host','promoted')))
        self.assertLess(calls.index('rollback_unit'),calls.index('reapply_unit'))
        self.assertEqual(calls.count(('cycle','cycle')),1);self.assertNotIn('cleanup',calls)
        self.assertEqual(result['result']['state'],'REHEARSAL_COMPLETE_TEARDOWN_REQUIRED')
    def test_rehearsal_keyboard_interrupt_cleans_only_collector_once_and_cannot_replay(self):
        self.configured()
        with mock.patch.object(outer.controller,'execute_item33_promotion',side_effect=KeyboardInterrupt):
            with self.assertRaises(outer.OuterError):self.runner.run('rehearse')
        self.assertEqual(self.ports.calls.count('cleanup'),1)
        with self.assertRaisesRegex(outer.OuterError,'once_readback_only'):self.runner.run('rehearse')
        self.assertEqual(self.ports.calls.count('start_ready'),1)
    def test_normal_cannot_run_before_actual_teardown_finalize(self):
        with self.assertRaises(outer.OuterError):self.runner.run('normal')
        self.assertNotIn('normal_handoff_once',self.ports.calls)
    def test_teardown_and_normal_phases_do_not_request_a_new_collection(self):
        self.configured();self.mark('rehearse')
        self.store.json('promotion-result.json',{'run_identity_sha256':'b'*64,'cycle':{}})
        self.store.json('cycle.database.json',{'snapshot':{'payload':{}}})
        self.ports.captured.update({'capture-seal.json':b'{}','production-item33-trends-dml-journal.jsonl':b'journal',
            'service-result.json':b'{}','service-close.json':b'{}'})
        self.runner.run('prepare-teardown')
        with mock.patch.object(outer.teardown,'verify_teardown_proof',return_value=None):self.runner.run('finalize-teardown')
        def normal_driver(**kw):
            kw['handoff_unit']({});kw['read_normal']();return {'status':'VERIFIED'}
        with mock.patch.object(outer.controller,'execute_item33_normal_handoff',side_effect=normal_driver),mock.patch.object(
            outer.facts,'preserved_rows',return_value={}),mock.patch.object(outer.facts,'compose_normal',return_value={'safe':True}),mock.patch.object(
            self.runner,'assemble',return_value={'candidate':True}):result=self.runner.run('normal')
        self.assertEqual(result['result']['state'],'TERMINAL_CANDIDATE_ASSEMBLED_NOT_GATE_CREDITED')
        self.assertIn(('cycle','normal'),self.ports.calls);self.assertNotIn(('cycle','cycle'),self.ports.calls)
        self.assertEqual(self.ports.calls.count('normal_handoff_once'),1)

    def test_assembly_preserves_all_thirteen_original_bytes_without_schema_shortcut(self):
        import item33_trends_evidence_assembly as assembler
        import internal_deployment_readiness_gate as gate
        self.runner.sources[gate.ITEM33_TRENDS_PROMOTION_EXECUTOR]='c'*64
        self.store.json('resource.before.json',self.ports.resource_inventory())
        self.store.json('cycle.http.json',{'worker_receipt':{'中文':'synthetic'}})
        self.store.json('normal.host.json',{'phase':'normal'})
        self.store.json('promoted.runtime.json',{'actual_projection':True})
        self.store.put('normal.readback.json',b'{"original_spacing": true}\n')
        self.ports.captured.update({'service-result.json':b'{"service":true}\n','service-close.json':b'{"close":true}\n'})
        self.ports.action_raw=lambda phase:outer.encoded({'phase':phase})
        self.ports.cleanup_facts=lambda host:{'actual_inventory':True}
        prior={'action_counts':{'cycle':1,'promotion':1,'rollback':1,'reapply':1,'automatic_retry':0},
            'cycle':{'physical_http':{'total_count':36,'observations':[{'request_kind':'session','phase':'response'}]}},'capture_binding':{}}
        with mock.patch.object(outer.http_reader,'verify_worker_receipt',return_value=True),mock.patch.object(
            assembler,'assemble_terminal',return_value={'terminal':{'candidate':True},'required_artifacts':[]}) as assemble:
            self.runner.assemble({'mutation_count':1,'other_unit_actions':0},prior,{'snapshot':{'payload':{'中文':'真实原投影'}}},b'{}\n',b'journal\n',b'{"teardown":true}\n')
        artifacts=assemble.call_args.kwargs['artifacts'];self.assertEqual(len(artifacts),13)
        self.assertEqual(artifacts[gate.ITEM33_V5_CAPTURE_JOURNAL],b'journal\n')
        self.assertEqual(artifacts[gate.ITEM33_V5_NORMAL_READBACK],b'{"original_spacing": true}\n')
        self.assertEqual(artifacts[assembler.SNAPSHOT_REF],outer.facts.encoded({'中文':'真实原投影'}))
        self.assertEqual(self.store.value('terminal-candidate.json'),{'candidate':True})

    def test_configuration_unknown_is_not_treated_as_completed(self):
        self.store.json('prepare-install.result.json',{'state':'UNKNOWN_READBACK_ONLY'})
        with self.assertRaises(outer.OuterError):self.runner.run('finalize-config')
        self.assertEqual(self.ports.calls,[])

    def recovery_inputs(self):
        from tests.test_item33_trends_capture_catalog import catalog_fixture
        self.runner.run('prepare-install')
        receipt={'schema':'noteai.item33.capture_install_execution.v1','status':'COMMITTED',
            'activation_identity_sha256':self.plan['activation_identity_sha256'],'operator_role':self.plan['operator_role'],
            'sql_sha256':self.store.value('prepare-install.facts.json')['sql_sha256'],'control_plane_ddl_count':29,
            'outcome_unknown_count':0,'started_at':self.now.isoformat(),'committed_at':self.now.isoformat()}
        self.ports.captured['operator-install-execution.json']=outer.encoded(receipt)
        self.store.json('finalize-config.started.json',{'state':'STARTED_UNKNOWN'})
        self.store.json('finalize-config.result.json',{'state':'UNKNOWN_READBACK_ONLY'})
        self.now+=timedelta(days=1)
        config=outer.runtime_cli.initial_config(self.plan)
        # The existing synthetic builder verifies its construction-day clock;
        # this fixture then supplies a later actual observation of the same objects.
        config['bucket_key']=datetime.now(timezone.utc).date().isoformat()
        before=catalog_fixture(config)['before']
        before.update(observed_at=self.now.isoformat(),bucket_key=self.now.date().isoformat())
        before['catalog']['privileges'][0]['delete']=True
        before['catalog_sha256']=outer.teardown.catalog.digest(before['catalog'])
        after=copy.deepcopy(before);after['catalog']=outer.teardown._without_capture(before['catalog'])
        after['catalog_sha256']=outer.teardown.catalog.digest(after['catalog'])
        after['observed_at']=(self.now+timedelta(seconds=3)).isoformat()
        old=self.ports.readonly
        def readonly(mode,**kwargs):
            if mode!='catalog':return old(mode,**kwargs)
            self.ports.calls.append((mode,kwargs['phase']))
            return before if kwargs['phase']=='recovery-before' else after
        self.ports.readonly=readonly
        return before,after

    def test_cross_day_failed_install_recovery_has_no_config_retry_cycle_or_credit(self):
        before,after=self.recovery_inputs()
        result=self.runner.run('prepare-recovery')
        self.assertEqual(result['result']['state'],'PRE_CYCLE_RECOVERY_SQL_PREPARED_NOT_EXECUTED')
        self.assertFalse(result['result']['readiness_credit'])
        self.assertEqual(self.store.value('recovery-before.catalog.json'),before)
        receipt={'schema':outer.teardown.RECOVERY_EXECUTION_SCHEMA,'status':'COMMITTED',
            'activation_identity_sha256':self.plan['activation_identity_sha256'],'operator_role':self.plan['operator_role'],
            'sql_sha256':outer.sha(self.store.read('pre-cycle-recovery.sql')),'control_plane_ddl_count':29,'outcome_unknown_count':0,
            'started_at':(self.now+timedelta(seconds=1)).isoformat(),'committed_at':(self.now+timedelta(seconds=2)).isoformat()}
        self.ports.captured['operator-pre-cycle-recovery-execution.json']=outer.encoded(receipt)
        self.now+=timedelta(seconds=4)
        result=self.runner.run('finalize-recovery')
        self.assertEqual(result['result']['state'],'PRE_CYCLE_CAPTURE_REMOVED');self.assertFalse(result['result']['readiness_credit'])
        self.assertEqual(self.store.value('pre-cycle-recovery.json')['after'],after)
        self.assertEqual([call for call in self.ports.calls if isinstance(call,tuple) and call[0]=='catalog'],
            [('catalog','recovery-before'),('catalog','recovery-after')])
        self.assertNotIn('start_ready',self.ports.calls);self.assertNotIn(('cycle','cycle'),self.ports.calls)
        self.assertNotIn(('finalize-config','finalize-config'),self.ports.calls)
        with self.assertRaisesRegex(outer.OuterError,'once_readback_only'):self.runner.run('prepare-recovery')
        self.now=outer.clock(self.plan['starts_at'])
        with self.assertRaisesRegex(outer.OuterError,'recovery_no_resume'):self.runner.run('rehearse')
        self.assertFalse(self.store.exists('terminal-candidate.json'))

    def test_recovery_requires_actual_stop_and_no_completed_cycle(self):
        self.recovery_inputs()
        def unsafe():raise outer.OuterError('live_worker')
        self.ports.recovery_host=unsafe
        with self.assertRaises(outer.OuterError):self.runner.run('prepare-recovery')
        self.assertNotIn(('catalog','recovery-before'),self.ports.calls);self.assertFalse(self.store.exists('pre-cycle-recovery.sql'))
        self.assertEqual(self.store.value('prepare-recovery.result.json')['state'],'UNKNOWN_READBACK_ONLY')

    def test_recovery_does_not_bypass_successful_rehearsal_teardown(self):
        self.recovery_inputs();self.mark('rehearse')
        with self.assertRaises(outer.OuterError):self.runner.run('prepare-recovery')
        self.assertNotIn('recovery_host',self.ports.calls)

    def test_recovery_host_accepts_retained_failure_but_rejects_live_pid_or_capture(self):
        import subprocess
        ports=outer.HostPorts.__new__(outer.HostPorts);ports.plan=self.plan;ports.current=lambda:self.now
        unit={'FragmentPath':str(outer.actions.UNIT_PATH),'DropInPaths':'','LoadState':'loaded',
            'ActiveState':'inactive','SubState':'dead','UnitFileState':'disabled','MainPID':'0','ControlPID':'0'}
        with mock.patch.object(outer.actions,'_assert_host_identity'),mock.patch.object(outer.host_reader,'_image'),mock.patch.object(
            outer.host_reader,'_unit',return_value=unit),mock.patch.object(outer.actions,'_regular',return_value=b'fixed'),mock.patch.object(
            outer.controller,'SUSPENDED_UNIT_SHA256',outer.sha(b'fixed')),mock.patch.object(outer.host_reader,'_session_digest'),mock.patch.object(
            outer.host_reader,'_inventory',return_value=[]) as inventory,mock.patch.object(subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=b'')) as processes,mock.patch.object(
            outer.os.path,'lexists',return_value=True):
            result=ports.recovery_host();self.assertTrue(result['capture_service_failure_present']);self.assertEqual(result['worker_count'],0)
            processes.return_value=SimpleNamespace(returncode=0,stdout=b'123\n')
            with self.assertRaisesRegex(outer.OuterError,'recovery_process'):ports.recovery_host()
            processes.return_value=SimpleNamespace(returncode=1,stdout=b'')
            inventory.side_effect=lambda run,**kw:['a'*64] if kw.get('label')=='com.noteai.task=item33-trends-capture' else []
            with self.assertRaisesRegex(outer.OuterError,'recovery_container'):ports.recovery_host()


@unittest.skipUnless(os.geteuid()==0,'isolated root metadata fixture')
class StoreTests(unittest.TestCase):
    def test_exclusive_0600_artifact_and_readback_preserve_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);root.chmod(0o700);store=outer.Store(root)
            store.json('result.json',{'safe':True});before=store.read('result.json')
            self.assertEqual((root/'result.json').stat().st_mode&0o777,0o600)
            with self.assertRaises(FileExistsError):store.json('result.json',{'changed':True})
            self.assertEqual(store.read('result.json'),before)
            with self.assertRaises(outer.OuterError):store.path('../escape')

    def test_source_manifest_0600_exact_members_and_readonly_files_are_bound(self):
        plan=plan_fixture();start=outer.clock(plan['starts_at'])
        plan.update(status='AUTHORIZED',authorization_kind='standing_follow_on',authorization_basis=outer.BASIS,
            recorded_at=(start-timedelta(days=1)).isoformat())
        original=Path(__file__).resolve().parents[1]
        content={ref:(original/ref).read_bytes() for ref in plan['accepted_source_sha256']}
        for ref in outer.controller.V5_CAPTURE_TOOLS:content[ref]=(original/ref).read_bytes()
        content[outer.controller.V5_CAPTURE_LAUNCHER_PATH]=outer.controller.V5_CAPTURE_LAUNCHER
        plan['instrumentation_sha256']={ref:outer.sha(content[ref]) for ref in plan['instrumentation_sha256']}
        content['item33-runtime-plan.json']=outer.encoded(plan)
        sources={ref:outer.sha(raw) for ref,raw in content.items()}
        manifest=outer.encoded({'schema':'noteai.item33.source_manifest.v1','source_sha256':sources})
        with tempfile.TemporaryDirectory() as directory:
            action=Path(directory);action.chmod(0o700);source=action/'source';source.mkdir(mode=0o700)
            for ref,raw in content.items():
                path=source/ref;path.parent.mkdir(parents=True,exist_ok=True)
                for parent in path.parents:
                    if parent==source or source in parent.parents:parent.chmod(0o700)
                path.write_bytes(raw);path.chmod(0o555 if ref.endswith('.sh') else 0o444)
            path=action/'source-manifest.json';path.write_bytes(manifest);path.chmod(0o600)
            with mock.patch.object(outer,'SOURCE_ROOT',source),mock.patch.object(outer,'ACTION_ROOT',action):
                bound,actual=outer.load_sources(outer.sha(manifest));self.assertEqual(actual,sources);self.assertEqual(bound,plan)
                path.chmod(0o444)
                with self.assertRaises(outer.containers.ContainerIOError):outer.load_sources(outer.sha(manifest))
                path.chmod(0o600)
                (source/'extra.py').write_text('extra');(source/'extra.py').chmod(0o444)
                with self.assertRaisesRegex(outer.OuterError,'source_members'):outer.load_sources(outer.sha(manifest))
