#!/usr/bin/env python3
"""One bound Item33 activation, in separately retained operator phases.

Installation/removal SQL is exported only. The original authenticated operator
executes it and supplies the original transaction receipt. UNKNOWN never replays
an action. Importing this module performs no host, DB or provider operation.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import execute_item33_trends_promotion as controller
import item33_trends_host_actions as actions
import item33_trends_host_readback as host_reader
import item33_trends_container_io as containers
import item33_trends_runtime_capture as capture
import item33_trends_capture_teardown as teardown
import item33_trends_readback_assembly as facts
import item33_trends_http_readback as http_reader
import item33_trends_runtime_cli as runtime_cli

ACTION_ROOT = Path('/var/lib/noteai/item33-trends-promotion')
SOURCE_ROOT = ACTION_ROOT / 'source'
CAPTURE_ROOT = ACTION_ROOT / 'capture'
OUTER_ROOT = ACTION_ROOT / 'outer'
EVIDENCE_PREFIX = 'deploy/production/evidence/'
PHASES = ('prepare-install','finalize-config','rehearse','prepare-teardown','finalize-teardown','normal')
BASIS = 'Owner Sep13 formal 37-item delivery; Sep15 and later after real Item32 continue Item33; no new resources'
PREDECESSOR_ROOTS = tuple(Path('/var/lib/noteai') / name for name in (
    'item32-readonly','item32-xhs-diagnostic','item32-readonly-successor','item32-v5-successor-20260916',
    'item32-v5-successor-20260917','item32-v5-network-repair-20260917','item32-v5-source-retention-20260918'))


class OuterError(RuntimeError):
    """Fixed safe code, never command/driver/provider content."""


def require(value, code='item33_outer_binding'):
    if not value: raise OuterError(code)


def sha(raw): return hashlib.sha256(raw).hexdigest()
def encoded(value): return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def utc_now(): return datetime.now(timezone.utc)
def clock(value): return runtime_cli.clock(value)


def validate_plan(plan):
    runtime_cli.validate_plan(plan)
    require(plan.get('status')=='AUTHORIZED' and plan.get('authorization_kind')=='standing_follow_on'
        and plan.get('authorization_basis')==BASIS, 'item33_authorization')
    require(clock(plan['recorded_at']) <= clock(plan['starts_at']), 'item33_authorization_clock')
    return plan


class Store:
    def __init__(self,root=OUTER_ROOT): self.root=Path(root)
    def path(self,ref):
        require(isinstance(ref,str) and ref and not ref.startswith('/')
            and all(part not in ('','.','..') for part in ref.split('/')), 'item33_artifact_path')
        return self.root/ref
    def put(self,ref,raw):
        path=self.path(ref)
        for parent in reversed(path.parents):
            if parent==self.root or self.root in parent.parents: containers.directory(parent,create=True)
        actions._exclusive(path,raw)
        return sha(raw)
    def json(self,ref,value): return self.put(ref,encoded(value))
    def read(self,ref): return containers.read_file(self.path(ref),mode=0o600,maximum=16*1024*1024)
    def value(self,ref): return containers.safe_json(self.read(ref))
    def exists(self,ref): return os.path.lexists(self.path(ref))


@contextmanager
def host_locks():
    """All seven retained Item32 locks SH; this activation's outer lock EX."""
    descriptors=[]
    try:
        for root in PREDECESSOR_ROOTS:
            path=root/'executor.lock';fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK);descriptors.append(fd)
            meta=os.fstat(fd);linked=os.lstat(path)
            require(stat.S_ISREG(meta.st_mode) and meta.st_uid==meta.st_gid==0 and meta.st_nlink==1
                and stat.S_IMODE(meta.st_mode)==0o600 and meta.st_size==0
                and (meta.st_dev,meta.st_ino)==(linked.st_dev,linked.st_ino),'item33_predecessor_lock')
            fcntl.flock(fd,fcntl.LOCK_SH|fcntl.LOCK_NB)
        path=OUTER_ROOT/'executor.lock';fd=os.open(path,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600);descriptors.append(fd)
        meta=os.fstat(fd)
        require(stat.S_ISREG(meta.st_mode) and meta.st_uid==meta.st_gid==0 and meta.st_nlink==1
            and stat.S_IMODE(meta.st_mode)==0o600 and meta.st_size==0,'item33_outer_lock')
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield
    finally:
        for fd in reversed(descriptors):os.close(fd)


def load_sources(expected_sha):
    require(containers.is_sha(expected_sha),'item33_source_manifest')
    raw=containers.read_file(ACTION_ROOT/'source-manifest.json',mode=0o600)
    require(sha(raw)==expected_sha,'item33_source_manifest')
    manifest=containers.safe_json(raw)
    require(set(manifest)=={'schema','source_sha256'} and manifest['schema']=='noteai.item33.source_manifest.v1','item33_source_manifest')
    sources=manifest['source_sha256'];require(isinstance(sources,dict),'item33_source_manifest')
    for ref,digest in sources.items():
        require(isinstance(ref,str) and not ref.startswith('/') and all(part and not part.startswith('.') for part in ref.split('/'))
            and containers.is_sha(digest),'item33_source_manifest')
    actual=set()
    for directory,dirs,files in os.walk(SOURCE_ROOT,followlinks=False):
        containers.directory(Path(directory))
        for name in dirs:containers.directory(Path(directory)/name)
        for name in files:actual.add(str((Path(directory)/name).relative_to(SOURCE_ROOT)))
    require(actual==set(sources),'item33_source_members')
    for ref,digest in sources.items():
        require(sha(containers.read_file(SOURCE_ROOT/ref,mode=0o555 if ref.endswith('.sh') else 0o444))==digest,'item33_source_hash')
    plan=validate_plan(containers.safe_json(containers.read_file(SOURCE_ROOT/'item33-runtime-plan.json')))
    require(all(sources.get(ref)==value for ref,value in {**plan['accepted_source_sha256'],**plan['instrumentation_sha256']}.items()),'item33_effective_sources')
    return plan,sources


class HostPorts:
    def __init__(self,plan,sources,store,*,current=utc_now,pause=time.sleep):
        self.plan=plan;self.sources=sources;self.store=store;self.current=current;self.pause=pause
        self.dependencies=controller._load_verified_dependencies();self.collector=None;self.capture_binding=None
        self.io=containers.ContainerIO(source_sha256=sources,activation_identity_sha256=plan['activation_identity_sha256'])
    def configure(self,config):
        raw=capture.encoded(config)
        self.capture_binding={'source_sha256':{ref:self.sources[ref] for ref in controller.V5_CAPTURE_TOOLS},
            'launcher_sha256':self.sources[controller.V5_CAPTURE_LAUNCHER_PATH],
            'configuration_sha256':sha(raw),'activation_identity_sha256':self.plan['activation_identity_sha256']}
        self.io=containers.ContainerIO(source_sha256=self.sources,activation_identity_sha256=self.plan['activation_identity_sha256'],
            config_sha256=sha(raw),deadline=min(clock(self.plan['ends_at']),self.current()+timedelta(minutes=34)).isoformat())
        self.actions=actions.Item33HostUnitActions(dependencies=self.dependencies,capture_binding=self.capture_binding,clock=self.current)
    def readonly(self,mode,**kwargs):return self.io.run_readonly(mode,bucket_key=self.plan['bucket_key'],**kwargs)
    def host(self,phase):return host_reader.read_host_facts(phase=phase,dependencies=self.dependencies,capture_binding=self.capture_binding,clock=self.current)
    def read_capture(self,name):return containers.read_file(CAPTURE_ROOT/name,mode=0o600,maximum=16*1024*1024)
    def write_capture(self,name,raw,mode=0o600):
        require('/' not in name,'capture_path');actions._exclusive(CAPTURE_ROOT/name,raw)
        if mode!=0o600:
            fd=os.open(CAPTURE_ROOT/name,os.O_RDONLY|os.O_NOFOLLOW)
            try:os.fchmod(fd,mode);os.fsync(fd)
            finally:os.close(fd)
            actions._sync_directory(CAPTURE_ROOT)
    def stage_runtime(self):
        # Source staging owns creation. Here only verify the exact prior bytes.
        root=controller.V5_RUNTIME_OVERLAY_ROOT
        containers.directory(root.parent);containers.directory(root)
        for ref,digest in {**self.plan['accepted_source_sha256'],**self.plan['instrumentation_sha256']}.items():
            path=root/ref
            for parent in path.parents:
                if parent==root or root in parent.parents:containers.directory(parent)
            mode=0o555 if ref.endswith('.sh') else 0o444
            require(sha(containers.read_file(path,mode=mode))==digest,'item33_overlay_existing')
    def _wait_record(self,name,*,seconds):
        deadline=time.monotonic()+seconds
        while time.monotonic()<deadline:
            require(self.current()<clock(self.plan['ends_at']),'item33_wait_window')
            require(not os.path.lexists(CAPTURE_ROOT/'service-failure.json'),'item33_collector_failed')
            if os.path.lexists(CAPTURE_ROOT/name):return containers.safe_json(self.read_capture(name))
            state=self.io.read_collector()
            if not state['running']:
                if os.path.lexists(CAPTURE_ROOT/name):return containers.safe_json(self.read_capture(name))
                raise OuterError('item33_collector_exited')
            self.pause(0.25)
        raise OuterError('item33_collector_wait_unknown')
    def start_ready(self):
        state=self.io.start_collector();self.collector=state['id']
        ready=self._wait_record('service-ready.json',seconds=60)
        require(ready['state']=='LISTENING_READY' and ready['configuration_sha256']==self.capture_binding['configuration_sha256']
            and ready['activation_identity_sha256']==self.plan['activation_identity_sha256'],'item33_collector_ready')
    def seal_close(self):
        request={'schema':'noteai.item33.capture_seal_request.v1','activation_identity_sha256':self.plan['activation_identity_sha256'],
            'configuration_sha256':self.capture_binding['configuration_sha256'],'bucket_key':self.plan['bucket_key']}
        self.write_capture('seal-request.json',capture.encoded(request)+b'\n')
        result=self._wait_record('service-result.json',seconds=30)
        closed=self._wait_record('service-close.json',seconds=30)
        require(result['state']=='SEALED' and closed['state']=='CONNECTIONS_CLOSED' and type(closed['connection_count']) is int
            and closed['connection_count']==3,'item33_collector_close')
        self.io.close_collector(self.collector);self.collector=None
        seal_raw=self.read_capture('capture-seal.json');journal=self.read_capture('production-item33-trends-dml-journal.jsonl')
        require(sha(seal_raw)==result['capture_seal_sha256'],'item33_capture_receipt')
        capture.verify_capture_artifacts(containers.safe_json(seal_raw),journal)
        return seal_raw,journal
    def failure_cleanup(self):
        if self.collector is not None:
            cid=self.collector;self.collector=None
            self.io.close_collector(cid)
    def http(self,database):
        ids=host_reader._inventory(actions._run,label='com.noteai.service=noteai-xhs-trends')
        require(len(ids)==1 and ids==host_reader._inventory(actions._run,name='noteai-xhs-trends'),'item33_formal_identity')
        import subprocess
        completed=subprocess.run(['docker','logs','--since',database['started_at'],'--until',self.current().isoformat(),ids[0]],
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=20,check=False,env={'PATH':'/usr/bin:/bin'})
        require(completed.returncode==0 and len(completed.stdout)<=http_reader.MAX_OUTPUT,'item33_http_log_readback')
        raw=completed.stdout
        require(host_reader._inventory(actions._run,name='noteai-xhs-trends')==ids,'item33_formal_identity')
        return http_reader.read_http_facts(raw,cycle=database,observed_at=self.current())

    def resource_inventory(self):
        # Actual existing-host resource identities; state flags may legitimately
        # change on this one service, so hash names/IDs, not enabled/active text.
        result={}
        for key,argv in (
            ('images',['docker','image','ls','--no-trunc','--quiet']),
            ('networks',['docker','network','ls','--no-trunc','--quiet']),
            ('volumes',['docker','volume','ls','--quiet'])):
            names=sorted(set(actions._run(argv).decode('ascii').splitlines()))
            result[key+'_sha256']=sha(capture.encoded(names))
        lines=actions._run(['systemctl','list-unit-files','--type=service','--no-legend','--no-pager']).decode().splitlines()
        result['service_names_sha256']=sha(capture.encoded(sorted(line.split()[0] for line in lines if line.strip())))
        actions._assert_host_identity()
        result['bound_original_host_verified']=True
        return result
    def managed_runtime(self,database,host):
        ids=host_reader._inventory(actions._run,label='com.noteai.service=noteai-xhs-trends')
        require(len(ids)==1 and host['formal_container_count']==host['process_count']==1,'item33_runtime_singleton')
        template='{"user":{{json .Config.User}},"argv":{{json .Config.Cmd}},"memory_bytes":{{json .HostConfig.Memory}},"nano_cpus":{{json .HostConfig.NanoCpus}},"pids_limit":{{json .HostConfig.PidsLimit}},"read_only":{{json .HostConfig.ReadonlyRootfs}},"cap_drop":{{json .HostConfig.CapDrop}},"security_opt":{{json .HostConfig.SecurityOpt}},"log_driver":{{json .HostConfig.LogConfig.Type}},"log_max_size":{{json (index .HostConfig.LogConfig.Config "max-size")}},"log_max_file":{{json (index .HostConfig.LogConfig.Config "max-file")}},"docker_restart_count":{{json .RestartCount}}}'
        meta=containers.safe_json(actions._run(['docker','inspect','--format',template,ids[0]]))
        rows=actions._run(['systemctl','show',controller.UNIT_NAME,'-p','Restart','-p','NRestarts']).decode().splitlines()
        system=dict(row.split('=',1) for row in rows)
        require(system=={'Restart':'no','NRestarts':'0'} and type(meta['docker_restart_count']) is int and meta['docker_restart_count']==0
            and meta['argv']==['/app/scripts/render_run_market_timing.sh'] and meta['nano_cpus']==500000000
            and meta['security_opt']==['no-new-privileges:true'] and meta['log_max_file']=='2','item33_runtime_metadata')
        runtime={key:meta[key] for key in ('memory_bytes','pids_limit','user','read_only','cap_drop','log_driver','log_max_size')}
        runtime.update(cpus_millis=meta['nano_cpus']//1000000,no_new_privileges=True,log_max_file=int(meta['log_max_file']))
        require(database['ledger']['same_bucket_run_count']==database['ledger']['idle_service_count']==1,'item33_runtime_singleton')
        return {'unit_name':controller.UNIT_NAME,'container_name':'noteai-xhs-trends','database_role':database['database_role'],
            'argv':meta['argv'],'runtime':runtime,'singleton_winner_count':database['ledger']['same_bucket_run_count'],
            'restart_policy':system['Restart'],'automatic_restart_count':int(system['NRestarts'])}
    def cleanup_facts(self,host):
        # Only this task's documented transient namespaces. Retained evidence,
        # source and rollback files are intentionally outside this inventory.
        ephemeral=[path for path in host_reader.RUN_ROOT.iterdir() if path.name.startswith(('noteai-item33-runtime-','noteai-item33-stage-'))]
        snapshots=sum(1 for directory in ephemeral if directory.is_dir() for path in directory.rglob('*')
                      if path.is_file() and ('snapshot' in path.name or path.suffix in {'.sqlite','.db'}))
        exports=sum(1 for path in Path('/home/ecs-assist-user').glob('item33-*.tar*') if path.is_file())
        rollback=actions._regular(ACTION_ROOT/'suspended-unit.rollback',mode=0o600)
        require(sha(rollback)==controller.SUSPENDED_UNIT_SHA256,'item33_rollback_retained')
        return {**{key:host[key] for key in ('task_container_count','inspection_container_count','stage_directory_count',
            'runtime_directory_count','temporary_unit_count','temporary_dropin_count')},
            'local_snapshot_count':snapshots,'local_export_count':exports,
            'formal_managed_container_count':host['formal_container_count'],'rollback_artifact_retained':True,
            'rollback_artifact_sha256':sha(rollback)}
    def action_raw(self,phase):return actions._regular(ACTION_ROOT/(phase+'.applied.json'),mode=0o600)


class Outer:
    def __init__(self,*,plan,sources,store,ports,current=utc_now):
        self.plan=validate_plan(plan);self.sources=sources;self.store=store;self.ports=ports;self.current=current
    def _window(self,phase):
        now=self.current();start=clock(self.plan['starts_at']);cutoff=clock(self.plan['dispatch_before']);end=clock(self.plan['ends_at'])
        require(clock(self.plan['recorded_at'])<=now,'item33_clock')
        if phase in ('prepare-install','finalize-config'):require(start-timedelta(minutes=15)<=now<cutoff,'item33_prepare_window')
        elif phase=='rehearse':require(start<=now<cutoff and now+timedelta(minutes=35)<=end,'item33_dispatch_window')
        elif phase=='normal':require(start<=now<end,'item33_normal_window')
        else:require(start<=now and now.date().isoformat()==self.plan['bucket_key'],'item33_cleanup_bucket')
    def _prior(self,phase):
        value=self.store.value(phase+'.result.json');require(value['state']=='COMPLETED','item33_previous_phase_unknown')
        return value
    def _config(self):
        value=self.store.value('finalize-config.facts.json');self.ports.configure(value['config']);return value['config']
    def run(self,phase):
        require(phase in PHASES,'item33_phase');self._window(phase)
        require(not self.store.exists(phase+'.started.json'),'item33_once_readback_only')
        marker={'phase':phase,'state':'STARTED_UNKNOWN','started_at':self.current().isoformat(),
            'activation_identity_sha256':self.plan['activation_identity_sha256'],'source_sha256':sha(containers.canonical(self.sources))}
        self.store.json(phase+'.started.json',marker)
        try:
            result=getattr(self,phase.replace('-','_'))()
            final={**marker,'state':'COMPLETED','completed_at':self.current().isoformat(),'result':result,'secret_values_recorded':False}
            self.store.json(phase+'.result.json',final);return final
        except BaseException:
            cleanup='NOT_REQUESTED'
            if phase=='rehearse':
                try:self.ports.failure_cleanup();cleanup='EXACT_COLLECTOR_CLEANUP_ATTEMPTED'
                except BaseException:cleanup='UNKNOWN'
            value={**marker,'state':'UNKNOWN_READBACK_ONLY','observed_at':self.current().isoformat(),
                'error_code':'item33_phase_unknown','collector_cleanup':cleanup,'secret_values_recorded':False}
            if not self.store.exists(phase+'.result.json'):self.store.json(phase+'.result.json',value)
            raise OuterError('item33_phase_unknown_readback_only') from None
    def prepare_install(self):
        value=self.ports.readonly('prepare-install');require(value['state']=='SQL_PREPARED_NOT_EXECUTED','item33_install_prepare')
        require(value['sql_sha256']==sha(value['sql'].encode()),'item33_install_sql')
        self.store.json('prepare-install.facts.json',value);self.store.put('install.sql',value['sql'].encode())
        return {'state':value['state'],'sql_sha256':value['sql_sha256'],'control_plane_ddl_count':value['control_plane_ddl_count']}
    def finalize_config(self):
        self._prior('prepare-install');prepared=self.store.value('prepare-install.facts.json')
        receipt=containers.safe_json(self.ports.read_capture('operator-install-execution.json'))
        require(receipt['schema']=='noteai.item33.capture_install_execution.v1' and receipt['status']=='COMMITTED'
            and receipt['activation_identity_sha256']==self.plan['activation_identity_sha256']
            and receipt['operator_role']==self.plan['operator_role'] and receipt['sql_sha256']==prepared['sql_sha256']
            and type(receipt['control_plane_ddl_count']) is int and receipt['control_plane_ddl_count']==prepared['control_plane_ddl_count']
            and type(receipt['outcome_unknown_count']) is int and receipt['outcome_unknown_count']==0
            and clock(self.plan['starts_at'])-timedelta(minutes=15)<=clock(receipt['started_at'])<=clock(receipt['committed_at'])<=self.current(), 'item33_install_execution')
        value=self.ports.readonly('finalize-config');require(value['state']=='CONFIGURATION_VERIFIED_NOT_RUNNING','item33_config')
        raw=capture.encoded(value['config']);require(sha(raw)==value['config_sha256'],'item33_config')
        self.ports.write_capture('runtime-config.json',raw,mode=0o444);self.ports.stage_runtime();self.ports.configure(value['config'])
        self.store.json('finalize-config.facts.json',value)
        return {'configuration_sha256':value['config_sha256'],'state':value['state']}
    def rehearse(self):
        self._prior('finalize-config');self._config();self.ports.start_ready();self._window('rehearse')
        state={}
        self.store.json('resource.before.json',self.ports.resource_inventory())
        def preflight():
            database=self.ports.readonly('preflight');host=self.ports.host('preflight')
            self.store.json('preflight.database.json',database);self.store.json('preflight.host.json',host)
            return facts.compose_preflight(host,database)
        def cycle(authorization):
            database=self.ports.readonly('cycle');state['database']=database
            self.store.json('cycle.database.json',database)
            http=self.ports.http(database);self.store.json('cycle.http.json',http)
            seal_raw,journal=self.ports.seal_close();seal=containers.safe_json(seal_raw)
            state['aggregate']=capture.verify_capture_artifacts(seal,journal)
            state['cycle']=facts.compose_cycle(database,http,seal,journal)
            self.store.json('cycle.composed.json',state['cycle']);return state['cycle']
        def read_state(phase):
            require('database' in state and 'cycle' in state,'item33_cycle_unresolved')
            database=self.ports.readonly('cycle',phase=phase,expected_run_identity_sha256=state['cycle']['run_identity_sha256'])
            host=self.ports.host(phase)
            self.store.json(phase+'.database.json',database);self.store.json(phase+'.host.json',host)
            if phase=='promoted':self.store.json('promoted.runtime.json',self.ports.managed_runtime(database,host))
            return facts.compose_state(phase=phase,host=host,database=database,baseline=state['database'],cycle=state['cycle'],aggregate=state['aggregate'])
        result=controller.execute_item33_promotion(dependencies=self.ports.dependencies,activation_identity_sha256=self.plan['activation_identity_sha256'],
            capture_binding=self.ports.capture_binding,read_preflight=preflight,read_single_cycle=cycle,
            promote_unit=self.ports.actions.promote_unit,read_promoted=lambda:read_state('promoted'),
            rollback_unit=self.ports.actions.rollback_unit,read_rollback=lambda:read_state('rollback'),
            reapply_unit=self.ports.actions.reapply_unit,read_final=lambda:read_state('final'),clock=self.current)
        self.store.json('promotion-result.json',result)
        return {'state':'REHEARSAL_COMPLETE_TEARDOWN_REQUIRED','run_identity_sha256':result['run_identity_sha256']}
    def prepare_teardown(self):
        self._prior('rehearse');self._config()
        value=self.ports.readonly('prepare-teardown');require(value['state']=='SQL_PREPARED_NOT_EXECUTED','item33_teardown_prepare')
        require(sha(value['sql'].encode())==value['sql_sha256'],'item33_teardown_prepare')
        self.store.json('prepare-teardown.facts.json',value);self.store.put('teardown.sql',value['sql'].encode())
        return {'state':value['state'],'sql_sha256':value['sql_sha256'],'control_plane_ddl_count':value['control_plane_ddl_count']}
    def finalize_teardown(self):
        self._prior('prepare-teardown');self._config()
        value=self.ports.readonly('finalize-teardown')
        teardown.verify_teardown_proof(value,seal_raw=self.ports.read_capture('capture-seal.json'),
            journal=self.ports.read_capture('production-item33-trends-dml-journal.jsonl'),source_sha256=self.sources[teardown.SOURCE_REF])
        require(value['sql_sha256']==self.store.value('prepare-teardown.facts.json')['sql_sha256'],'item33_teardown_execution')
        raw=encoded(value);self.ports.write_capture('capture-teardown.json',raw)
        self.store.put('capture-teardown.json',raw)
        return {'state':'TEARDOWN_VERIFIED_NORMAL_HANDOFF_PENDING','teardown_sha256':sha(raw)}
    def normal(self):
        self._prior('finalize-teardown');self._config();prior=self.store.value('promotion-result.json');baseline=self.store.value('cycle.database.json')
        seal_raw=self.ports.read_capture('capture-seal.json');journal=self.ports.read_capture('production-item33-trends-dml-journal.jsonl')
        teardown_raw=self.ports.read_capture('capture-teardown.json')
        def read_normal():
            database=self.ports.readonly('cycle',phase='normal',expected_run_identity_sha256=prior['run_identity_sha256'])
            host=self.ports.host('normal');host_raw=encoded(host)
            self.store.json('normal.database.json',database);self.store.put('normal.host.json',host_raw)
            close={}
            for key,name,filename in (('service_result','service-result.json','capture-service-result'),('close','service-close.json','capture-service-close'),('host','normal.host.json','normal-host-readback')):
                raw=host_raw if key=='host' else self.ports.read_capture(name)
                close[key+'_ref']=EVIDENCE_PREFIX+'production-item33-trends-'+filename+'.json';close[key+'_sha256']=sha(raw)
            value=facts.compose_normal(host=host,database=database,baseline=baseline,cycle=prior['cycle'],seal_raw=seal_raw,teardown_raw=teardown_raw,capture_close=close)
            self.store.put('normal.readback.json',controller._normal_json_bytes(value));return value
        result=controller.execute_item33_normal_handoff(dependencies=self.ports.dependencies,previous_result=prior,preserved=facts.preserved_rows(baseline),
            capture_seal_raw=seal_raw,capture_journal=journal,teardown_raw=teardown_raw,handoff_unit=self.ports.actions.normal_handoff_once,
            read_normal=read_normal,clock=self.current)
        self.store.json('normal-handoff.json',result)
        terminal=self.assemble(result,prior,baseline,seal_raw,journal,teardown_raw)
        return {'state':'TERMINAL_CANDIDATE_ASSEMBLED_NOT_GATE_CREDITED','normal_handoff_sha256':sha(encoded(result)),
            'terminal_candidate_sha256':sha(encoded(terminal))}
    def assemble(self,normal,prior,database,seal_raw,journal,teardown_raw):
        import item33_trends_evidence_assembly as assembler
        import internal_deployment_readiness_gate as gate
        http=self.store.value('cycle.http.json');host=self.store.value('normal.host.json')
        before=self.store.value('resource.before.json');after=self.ports.resource_inventory()
        self.store.json('resource.after.json',after)
        require(before==after and before.get('bound_original_host_verified') is True,'item33_resources_changed')
        require(prior['action_counts']=={'cycle':1,'promotion':1,'rollback':1,'reapply':1,'automatic_retry':0}
            and normal['mutation_count']==1 and normal['other_unit_actions']==0,'item33_action_scope')
        physical=prior['cycle']['physical_http']
        session=[row for row in physical['observations'] if row['request_kind']=='session' and row['phase']=='response']
        require(len(session)==1 and http_reader.verify_worker_receipt(http['worker_receipt'],prior['cycle']),'item33_session_proof')
        artifacts={gate.ITEM33_V5_CAPTURE_EVIDENCE:seal_raw,gate.ITEM33_V5_CAPTURE_JOURNAL:journal,
            gate.ITEM33_V5_HTTP_RECEIPT:http_reader.encoded(http['worker_receipt']),gate.ITEM33_V5_CAPTURE_TEARDOWN:teardown_raw,
            gate.ITEM33_V5_NORMAL_ACTION:self.ports.action_raw('normal_handoff'),
            gate.ITEM33_V5_NORMAL_READBACK:self.store.read('normal.readback.json'),
            assembler.SNAPSHOT_REF:facts.encoded(database['snapshot']['payload'])}
        for phase,ref in assembler.ACTION_REFS.items():artifacts[ref]=self.ports.action_raw(phase)
        for key,name in (('service_result','service-result.json'),('close','service-close.json'),('host','normal.host.json')):
            artifacts[gate.ITEM33_V5_CAPTURE_CLOSE_REFS[key]]=self.store.read(name) if key=='host' else self.ports.read_capture(name)
        control={'cycle_authentication':{'source':'real_xhs','authenticated_session':True},
            'managed_runtime':self.store.value('promoted.runtime.json'),'cleanup':self.ports.cleanup_facts(host),
            'cost':{'currency':'CNY','xhs_provider_requests':physical['total_count'],
                'provider_fee_fen':'UNKNOWN','incremental_cloud_cost_fen':'UNKNOWN',
                # These are scoped operations, established by the bound code's
                # action set plus unchanged host image/network/volume/unit IDs.
                'postpaid_resources_started':0,'postpaid_resources_running':0,'new_recurring_resource_count':0,
                'new_recurring_monthly_fen':0,'real_funds_fen':0,'payment_actions':0}}
        release={'outer_executor_ref':gate.ITEM33_TRENDS_PROMOTION_EXECUTOR,
            'outer_executor_sha256':self.sources[gate.ITEM33_TRENDS_PROMOTION_EXECUTOR],
            'source_sha256':{**gate.ITEM32_IMAGE_SOURCE_SHA256,**controller.V5_RUNTIME_OVERLAY_SHA256},
            'image_config_sha256':controller.V5_IMAGE_CONFIG_SHA256,'registry_manifest_sha256':controller.V5_REGISTRY_MANIFEST_SHA256,
            'suspended_unit_sha256':controller.SUSPENDED_UNIT_SHA256,'promoted_unit_sha256':controller.V5_PROMOTED_UNIT_SHA256,
            'image_source_sha256':gate.ITEM32_IMAGE_SOURCE_SHA256,'runtime_overlay_sha256':controller.V5_RUNTIME_OVERLAY_SHA256,
            'item32_terminal_sha256':controller.V5_ITEM32_TERMINAL_SHA256,
            'capture_binding':{**prior['capture_binding'],'receipt_ref':gate.ITEM33_V5_CAPTURE_EVIDENCE,'receipt_sha256':sha(seal_raw)}}
        assembled=assembler.assemble_terminal(promotion_result=prior,normal_handoff=normal,database_cycle=database,
            release_binding=release,artifacts=artifacts,control_facts=control,observed_at=self.current(),source_root=SOURCE_ROOT)
        self.store.json('control-facts.json',control)
        for ref,raw in artifacts.items():self.store.put('evidence/'+Path(ref).name,raw)
        self.store.json('terminal-candidate.json',assembled['terminal']);self.store.json('required-artifacts.json',assembled['required_artifacts'])
        return assembled['terminal']
    def readback(self):
        result={}
        for phase in PHASES:
            name=phase+'.result.json'
            if self.store.exists(name):
                raw=self.store.read(name);value=containers.safe_json(raw)
                result[phase]={'state':value['state'],'sha256':sha(raw)}
            elif self.store.exists(phase+'.started.json'):result[phase]={'state':'UNKNOWN_READBACK_ONLY','sha256':sha(self.store.read(phase+'.started.json'))}
            else:result[phase]={'state':'NOT_STARTED'}
        return {'state':'RETAINED_READBACK_ONLY','phases':result,'provider_calls':0,'database_connections':0,'mutations':0,'secret_values_recorded':False}


def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('phase',choices=(*PHASES,'readback-only'))
    parser.add_argument('--source-manifest-sha256',required=True);args=parser.parse_args(argv)
    try:
        require(os.geteuid()==0,'item33_root_required')
        plan,sources=load_sources(args.source_manifest_sha256)
        store=Store()
        if args.phase=='readback-only':
            runner=Outer(plan=plan,sources=sources,store=store,ports=None);result=runner.readback()
        else:
            containers.directory(ACTION_ROOT);containers.directory(CAPTURE_ROOT,create=True);containers.directory(OUTER_ROOT,create=True)
            with host_locks():
                ports=HostPorts(plan,sources,store);ports.io._preflight()
                runner=Outer(plan=plan,sources=sources,store=store,ports=ports);result=runner.run(args.phase)
        print(encoded(result).decode());return 0
    except BaseException:
        print('{"state":"UNKNOWN_READBACK_ONLY","error_code":"item33_outer_stopped","secret_values_recorded":false}');return 1


if __name__=='__main__':raise SystemExit(main())
