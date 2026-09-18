"""Fixed API-F containers for Item33's existing read-only CLI and collector.

Host-local only, no import-time I/O. A caller supplies the reviewed source map.
The original DATABASE_URL is filtered in RAM into a sealed memfd, never argv,
receipts or the collector's stdout. No Cookie or SSK is forwarded.
"""
from __future__ import annotations
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
from datetime import datetime, timezone

try:
    from . import item33_trends_host_actions as host
except ImportError:
    import item33_trends_host_actions as host

SOURCE_ROOT=Path('/var/lib/noteai/item33-trends-promotion/source')
CAPTURE_ROOT=Path('/var/lib/noteai/item33-trends-promotion/capture')
IO_ROOT=Path('/var/lib/noteai/item33-trends-promotion/container-io')
SESSION=Path('/etc/noteai/xhs-trends.env')
SESSION_SHA='18f72f26971be0f578342ea7f8ae6336c7ee66ea67f6e7246b2b7d3866d26f6a'
IMAGE='sha256:6d5dcf058c5a0990ba7df3103f63e414de69b62b0ec3481c08490d66ae30b703'
COLLECTOR_NAME='noteai-item33-trends-capture'
MODES={'preflight','catalog','cycle','prepare-install','finalize-config','prepare-teardown','finalize-teardown'}
PHASES={'preflight':'preflight','catalog':'catalog','prepare-install':'prepare-install','finalize-config':'finalize-config',
    'prepare-teardown':'prepare-teardown','finalize-teardown':'finalize-teardown',
    'cycle':'cycle','promoted':'cycle','rollback':'cycle','final':'cycle','normal':'cycle'}
MAX_OUTPUT=4*1024*1024
INSPECT='{"id":{{json .Id}},"name":{{json .Name}},"image":{{json .Image}},"running":{{json .State.Running}},"exit_code":{{json .State.ExitCode}},"oom":{{json .State.OOMKilled}},"task":{{json (index .Config.Labels "com.noteai.task")}},"activation":{{json (index .Config.Labels "com.noteai.activation")}}}'

class ContainerIOError(RuntimeError):
    """Fixed safe reason; the command and its raw diagnostics are not exposed."""

def require(condition,code='item33_container_contract'):
    if not condition:raise ContainerIOError(code)

def sha(raw):return hashlib.sha256(raw).hexdigest()
def canonical(value):return (json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False)+'\n').encode()
def is_sha(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None

def pairs(values):
    result={}
    for key,value in values:
        require(key not in result,'item33_duplicate_json');result[key]=value
    return result

def safe_json(raw):
    require(isinstance(raw,bytes) and 0<len(raw)<=MAX_OUTPUT,'item33_output_size')
    try:value=json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _:require(False))
    except (ValueError,UnicodeError):raise ContainerIOError('item33_invalid_json') from None
    require(isinstance(value,dict),'item33_output_shape')
    banned={'database_url','dsn','cookie','cookies','cookie_json','password','authorization','headers','secret','env','environment','connection_string'}
    def check(item,depth=0):
        require(depth<=32,'item33_output_depth')
        if isinstance(item,dict):
            for key,child in item.items():
                require(isinstance(key,str) and key.lower() not in banned,'item33_sensitive_output');check(child,depth+1)
        elif isinstance(item,list):
            require(len(item)<=32768,'item33_output_shape')
            for child in item:check(child,depth+1)
        elif isinstance(item,str):
            require(not re.search(r'(?i)(postgres(?:ql)?://|(?:cookie|authorization)\s*[:=]|bearer\s+)',item),'item33_sensitive_output')
        elif isinstance(item,float):require(math.isfinite(item),'item33_invalid_json')
    check(value);return value

def read_file(path,*,mode=0o444,maximum=MAX_OUTPUT):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        before=os.fstat(fd)
        require(stat.S_ISREG(before.st_mode) and before.st_uid==before.st_gid==0 and before.st_nlink==1
            and stat.S_IMODE(before.st_mode)==mode and 0<before.st_size<=maximum,'item33_file_metadata')
        with os.fdopen(fd,'rb',closefd=False) as stream:raw=stream.read(maximum+1)
        after=os.fstat(fd);linked=os.stat(path,follow_symlinks=False)
        require(len(raw)==before.st_size and (before.st_dev,before.st_ino)==(linked.st_dev,linked.st_ino)
            and (before.st_size,before.st_mtime_ns,before.st_ctime_ns)==(after.st_size,after.st_mtime_ns,after.st_ctime_ns),'item33_file_changed')
        return raw
    finally:os.close(fd)

def directory(path,*,create=False):
    if create and not os.path.lexists(path):
        os.mkdir(path,0o700);os.chmod(path,0o700);host._sync_directory(path.parent)
    meta=path.lstat();require(stat.S_ISDIR(meta.st_mode) and meta.st_uid==meta.st_gid==0
        and stat.S_IMODE(meta.st_mode)==0o700,'item33_directory')

def database_memfd():
    raw=read_file(SESSION,mode=0o600,maximum=65536)
    require(sha(raw)==SESSION_SHA,'item33_session_binding')
    try:lines=raw.decode('utf-8').splitlines()
    except UnicodeError:raise ContainerIOError('item33_session_shape') from None
    values=[]
    for line in lines:
        if not line.strip() or line.lstrip().startswith('#'):continue
        require('=' in line,'item33_session_shape')
        key,value=line.split('=',1)
        if key=='DATABASE_URL':values.append(value)
    require(len(values)==1 and values[0] and '\x00' not in values[0] and '\r' not in values[0] and '\n' not in values[0], 'item33_database_binding')
    require(hasattr(os,'memfd_create'),'item33_memfd_unavailable')
    fd=os.memfd_create('noteai-item33-db',os.MFD_CLOEXEC|os.MFD_ALLOW_SEALING)
    try:
        os.fchmod(fd,0o600);data=('DATABASE_URL='+values[0]+'\n').encode();offset=0
        while offset<len(data):
            size=os.write(fd,data[offset:]);require(size>0);offset+=size
        os.lseek(fd,0,os.SEEK_SET)
        seals=fcntl.F_SEAL_SEAL|fcntl.F_SEAL_SHRINK|fcntl.F_SEAL_GROW|fcntl.F_SEAL_WRITE
        fcntl.fcntl(fd,fcntl.F_ADD_SEALS,seals)
        require(fcntl.fcntl(fd,fcntl.F_GET_SEALS)&seals==seals)
        return fd
    except Exception:
        os.close(fd);raise

class ContainerIO:
    def __init__(self,*,source_sha256,activation_identity_sha256,config_sha256=None,deadline=None,
                 run=subprocess.run,host_check=host._assert_host_identity,memfd=database_memfd):
        require(isinstance(source_sha256,dict) and 1<=len(source_sha256)<=256 and is_sha(activation_identity_sha256))
        require(config_sha256 is None or is_sha(config_sha256))
        require('item33-runtime-plan.json' in source_sha256)
        for ref,value in source_sha256.items():
            require(isinstance(ref,str) and not ref.startswith('/') and all(part and not part.startswith('.') for part in ref.split('/'))
                and re.fullmatch('[A-Za-z0-9_./-]+',ref) and is_sha(value),'item33_source_binding')
        self.sources=dict(source_sha256);self.activation=activation_identity_sha256;self.config_sha=config_sha256;self.deadline=deadline
        self.run=run;self.host_check=host_check;self.memfd=memfd;self.source_digest=sha(canonical(self.sources))

    def _command(self,argv,*,timeout=60,pass_fds=(),allow_failure=False):
        try:
            result=self.run(argv,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=timeout,
                env={'PATH':'/usr/bin:/bin'},pass_fds=pass_fds)
        except Exception:raise ContainerIOError('item33_command_unknown') from None
        require(isinstance(result.stdout,bytes) and len(result.stdout)<=MAX_OUTPUT,'item33_output_size')
        if not allow_failure:require(result.returncode==0,'item33_command_unknown')
        return result

    def _preflight(self):
        self.host_check();require(os.geteuid()==0,'item33_root_required')
        for path in (SOURCE_ROOT.parent,SOURCE_ROOT,CAPTURE_ROOT):directory(path)
        actual=set()
        for parent,dirs,files in os.walk(SOURCE_ROOT,followlinks=False):
            directory(Path(parent))
            for name in dirs:directory(Path(parent)/name)
            for name in files:actual.add(str((Path(parent)/name).relative_to(SOURCE_ROOT)))
        require(actual==set(self.sources),'item33_source_members')
        for ref,digest in self.sources.items():
            path=SOURCE_ROOT/ref;mode=0o555 if path.suffix=='.sh' else 0o444
            require(sha(read_file(path,mode=mode))==digest,'item33_source_binding')
        config=CAPTURE_ROOT/'runtime-config.json'
        if self.config_sha is not None:require(sha(read_file(config))==self.config_sha,'item33_configuration_binding')
        directory(IO_ROOT,create=True)

    def _record(self,name,value):host._exclusive(IO_ROOT/name,canonical(value))

    def _inspect(self,cid,*,name,task):
        require(is_sha(cid),'item33_container_identity')
        value=safe_json(self._command(['docker','inspect','--format',INSPECT,cid]).stdout)
        require(set(value)=={'id','name','image','running','exit_code','oom','task','activation'}
            and value['id']==cid and value['name']=='/'+name and value['image']==IMAGE
            and value['task']==task and value['activation']==self.activation
            and type(value['running']) is bool and type(value['exit_code']) is int and type(value['oom']) is bool,'item33_container_identity')
        return value

    def _create(self,*,name,task,collector,args):
        fd=self.memfd()
        try:
            argv=['docker','create','--pull=never','--name='+name,'--restart=no','--user=0:0','--read-only','--cap-drop=ALL',
                '--security-opt=no-new-privileges:true','--network=bridge','--pids-limit=64','--memory=256m','--cpus=0.25',
                '--log-driver=local','--log-opt=max-size=1m','--log-opt=max-file=1','--label=com.noteai.task='+task,
                '--label=com.noteai.activation='+self.activation,'--env-file=/proc/self/fd/'+str(fd),
                '--mount=type=bind,src='+str(SOURCE_ROOT)+',dst=/workspace,readonly',
                '--mount=type=bind,src='+str(CAPTURE_ROOT)+',dst='+str(CAPTURE_ROOT)+('' if collector else ',readonly'),
                '--entrypoint=python3']
            if collector:argv.insert(8,'--cap-add=CHOWN')
            argv += [IMAGE,'-E','-B',*args]
            raw=self._command(argv,pass_fds=(fd,)).stdout.strip()
            require(re.fullmatch(b'[0-9a-f]{64}',raw) is not None,'item33_create_unknown')
            return raw.decode()
        finally:os.close(fd)

    def _remove(self,cid):
        self._command(['docker','rm',cid])
        remaining=self._command(['docker','container','ls','-aq','--no-trunc','--filter','id='+cid]).stdout.strip()
        require(remaining==b'','item33_container_removal_unknown')

    def run_readonly(self,mode,*,phase=None,bucket_key=None,expected_run_identity_sha256=None):
        phase=phase or mode
        require(mode in MODES and PHASES.get(phase)==mode,'item33_probe_mode')
        if bucket_key is not None:require(re.fullmatch(r'\d{4}-\d{2}-\d{2}',bucket_key) is not None,'item33_bucket')
        require(expected_run_identity_sha256 is None or is_sha(expected_run_identity_sha256),'item33_run_identity')
        if mode in {'cycle','prepare-teardown','finalize-teardown'}:require(self.config_sha is not None,'item33_configuration_binding')
        self._preflight();name='noteai-item33-readonly-'+phase;task='item33-trends-inspection'
        binding={'mode':mode,'phase':phase,'source_sha256':self.source_digest,'activation_identity_sha256':self.activation}
        self._record(phase+'-started.json',dict(binding,state='STARTED_UNKNOWN'))
        args=['/workspace/tools/item33_trends_runtime_cli.py',mode]
        if phase=='cycle':args+=['--wait-cycle']
        if bucket_key is not None:args+=['--bucket-key',bucket_key]
        if expected_run_identity_sha256 is not None:args+=['--expected-run-identity-sha256',expected_run_identity_sha256]
        cid=self._create(name=name,task=task,collector=False,args=args)
        self._record(phase+'-container.json',dict(binding,id=cid,image=IMAGE,name=name))
        result=None;failure=None;removed=False;inspection_failure=None
        try:
            self._inspect(cid,name=name,task=task)
            completed=self._command(['docker','start','--attach',cid],timeout=2000 if phase=='cycle' else 90,allow_failure=True)
            state=self._inspect(cid,name=name,task=task)
            projected=safe_json(completed.stdout)
            if projected.get('state')=='READONLY_INSPECTION_FAILED':inspection_failure=projected
            require(completed.returncode==0 and state['running'] is False and state['exit_code']==0 and state['oom'] is False,'item33_probe_failed')
            require(inspection_failure is None,'item33_probe_failed')
            result=projected
        except Exception:failure=ContainerIOError('item33_probe_unknown_readback_only')
        finally:
            try:
                state=self._inspect(cid,name=name,task=task)
                if state['running']:
                    self._command(['docker','stop','--time=10',cid],timeout=20)
                    state=self._inspect(cid,name=name,task=task)
                require(state['running'] is False,'item33_probe_cleanup_unknown')
                self._remove(cid);removed=True
            except Exception:failure=ContainerIOError('item33_probe_cleanup_unknown')
            receipt=dict(binding,state='READONLY_PROBE_COMPLETED' if failure is None else 'UNKNOWN_READBACK_ONLY',
                container_id=cid,exact_container_removed=removed,secret_values_recorded=False)
            if inspection_failure is not None:receipt['inspection_failure']=inspection_failure
            self._record(phase+'-result.json',receipt)
        if failure is not None:raise failure
        return result

    def start_collector(self):
        self._preflight();require(self.config_sha is not None and isinstance(self.deadline,str),'item33_collector_binding')
        try:deadline=datetime.fromisoformat(self.deadline.replace('Z','+00:00'));now=datetime.now(timezone.utc)
        except ValueError:raise ContainerIOError('item33_collector_deadline') from None
        require(deadline.tzinfo is not None and deadline.utcoffset().total_seconds()==0
            and 0<(deadline-now).total_seconds()<=35*60 and deadline.date()==now.date(),'item33_collector_deadline')
        binding={'activation_identity_sha256':self.activation,'configuration_sha256':self.config_sha,'source_sha256':self.source_digest}
        self._record('collector-started.json',dict(binding,state='STARTED_UNKNOWN'))
        cid=self._create(name=COLLECTOR_NAME,task='item33-trends-capture',collector=True,
            args=['/workspace/tools/item33_trends_capture_service.py','--serve','--config',str(CAPTURE_ROOT/'runtime-config.json'),
                '--config-sha256',self.config_sha,'--deadline',self.deadline])
        self._record('collector-container.json',dict(binding,id=cid,name=COLLECTOR_NAME,image=IMAGE))
        self._inspect(cid,name=COLLECTOR_NAME,task='item33-trends-capture')
        self._command(['docker','start',cid])
        state=self._inspect(cid,name=COLLECTOR_NAME,task='item33-trends-capture')
        require(state['running'],'item33_collector_start_unknown')
        return state

    def _collector_id(self):
        receipt=safe_json(read_file(IO_ROOT/'collector-container.json',mode=0o600))
        require(receipt.get('activation_identity_sha256')==self.activation and receipt.get('configuration_sha256')==self.config_sha
            and receipt.get('source_sha256')==self.source_digest,'item33_collector_binding')
        require(is_sha(receipt.get('id')),'item33_collector_identity');return receipt['id']

    def read_collector(self):
        self.host_check();cid=self._collector_id()
        return self._inspect(cid,name=COLLECTOR_NAME,task='item33-trends-capture')

    def close_collector(self,expected_cid):
        self.host_check();cid=self._collector_id();require(cid==expected_cid,'item33_collector_identity')
        self._record('collector-close-started.json',dict(state='STARTED_UNKNOWN',id=cid,activation_identity_sha256=self.activation))
        state=self._inspect(cid,name=COLLECTOR_NAME,task='item33-trends-capture')
        if state['running']:
            self._command(['docker','stop','--time=10',cid],timeout=20);state=self._inspect(cid,name=COLLECTOR_NAME,task='item33-trends-capture')
        require(not state['running'],'item33_collector_close_unknown')
        self._remove(cid)
        result=dict(state='EXACT_CONTAINER_REMOVED',id=cid,exit_code=state['exit_code'],oom=state['oom'],activation_identity_sha256=self.activation,
            provider_calls=0,secret_values_recorded=False)
        self._record('collector-close-result.json',result);return result
