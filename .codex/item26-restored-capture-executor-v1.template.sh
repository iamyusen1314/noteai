#!/bin/bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset DATABASE_URL NOTEAI_SQLITE_PATH PGHOST PGPORT PGDATABASE PGUSER PGPASSWORD PGSERVICE PGSERVICEFILE
unset ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN
unset ALICLOUD_ACCESS_KEY ALICLOUD_SECRET_KEY ALICLOUD_SECURITY_TOKEN OSS_ACCESS_KEY_ID OSS_ACCESS_KEY_SECRET

exec python3 -I -B - <<'PY'
import gzip,hashlib,json,os,re,signal,stat,subprocess

TRANSFER="/var/lib/noteai/item26-restored-v1/restored-capture-transfer-v1.sh.gz"
TRANSFER_BYTES=@@TRANSFER_BYTES@@
TRANSFER_SHA256="@@TRANSFER_SHA256@@"
RAW_BYTES=@@RAW_BYTES@@
RAW_SHA256="@@RAW_SHA256@@"
HEX64=re.compile(r"^[0-9a-f]{64}$")
CONNECTED=frozenset("NOTEAI_ITEM26_RESTORED_CAPTURE attempt_sentinel_retained automatic_retry_allowed comparison_exact container_residue_count control_material_retained database_connection_count database_transaction_count database_write_count force_rls_table_count incident_class managed_owner_activation_count manifest_bytes mismatch_codes new_capture_allowed object_contents_read object_keys_emitted object_write_count oss_get_request_count oss_head_request_count oss_list_request_count oss_operation_mode owner_mismatch_count owner_table_contract_exact persistent_permission_mutation_count postgresql_major_version readback_required reconciliation_retained reconciliation_schema_version restored_manifest_file_sha256 restored_manifest_retained restored_manifest_sha256 rls_contract_exact rls_table_count row_security_off row_values_emitted runtime_container_start_count same_invocation_replay_allowed search_path_exact secret_values_emitted source_manifest_sha256 table_count task_root_retained transaction_terminal transfer_retained verified".split())
PRECONNECT=frozenset("NOTEAI_ITEM26_RESTORED_CAPTURE automatic_retry_allowed database_attempted_state incident_class new_capture_allowed phase same_invocation_replay_allowed".split())
UNKNOWN=PRECONNECT|{"readback_required"}
EXECUTOR=UNKNOWN|{"transfer_state"}
PHASES=frozenset("absolute_tool container_cleanup control_inventory control_root db_socket_after db_socket_before docker_service docker_version driver_contract driver_preconnect_failure driver_stderr driver_stdout driver_terminal envelope envelope_hash final_fsync final_hash final_inventory final_manifest final_move final_preexisting final_receipt final_receipt_hash final_root identity image key_pair output_inventory persistent_parent persistent_root preconnect_contract preconnect_retention preconnect_stderr preconnect_stdout preexisting_capture_state preflight private_hash private_key public_hash public_key receipt replay_barrier restored_read_only_capture root task_container task_identity task_retention terminal_promotion tool".split())
EXECUTOR_PHASES=frozenset("capture_contract capture_failure_stream capture_json capture_output_limit capture_pass_stream capture_returncode capture_shape capture_spawn capture_timeout executor_exception executor_preflight raw_hash transfer_after_capture transfer_hash transfer_metadata".split())
MISMATCH=frozenset("release_commit database_engine database_schema database_migrations database_tables database_references private_objects".split())

class Failure(Exception):
    def __init__(self,phase,spawned=False,transfer="UNVERIFIED"):
        Exception.__init__(self,phase); self.phase=phase; self.spawned=spawned; self.transfer=transfer

def canonical(value):
    return (json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n").encode("ascii")

def emit(value,code,descriptor):
    body=canonical(value)
    if len(body)>4096: os._exit(4)
    try:
        if os.write(descriptor,body)!=len(body): os._exit(4)
    except BaseException: os._exit(4)
    os._exit(code)

def fixed(spawned,phase,transfer):
    return {"NOTEAI_ITEM26_RESTORED_CAPTURE":"UNKNOWN" if spawned else "FAIL","automatic_retry_allowed":False,"database_attempted_state":"UNKNOWN" if spawned else "NO","incident_class":"CONNECTED_UNKNOWN" if spawned else "PRE_CONNECT","new_capture_allowed":False,"phase":phase,"readback_required":spawned,"same_invocation_replay_allowed":False,"transfer_state":transfer}

def read_transfer():
    parent,name=os.path.split(TRANSFER); dirfd=os.open(parent,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW); fd=None
    try:
        before=os.stat(name,dir_fd=dirfd,follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode) or before.st_uid!=0 or before.st_gid!=0 or stat.S_IMODE(before.st_mode)!=0o600 or before.st_nlink!=1 or before.st_size!=TRANSFER_BYTES: raise Failure("transfer_metadata")
        fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=dirfd)
        body=b""
        while len(body)<=TRANSFER_BYTES:
            chunk=os.read(fd,min(65536,TRANSFER_BYTES+1-len(body)))
            if not chunk: break
            body+=chunk
        current=os.fstat(fd); after=os.stat(name,dir_fd=dirfd,follow_symlinks=False)
        expected=(before.st_dev,before.st_ino,before.st_mode,before.st_uid,before.st_gid,before.st_nlink,before.st_size)
        if (current.st_dev,current.st_ino,current.st_mode,current.st_uid,current.st_gid,current.st_nlink,current.st_size)!=expected or (after.st_dev,after.st_ino,after.st_mode,after.st_uid,after.st_gid,after.st_nlink,after.st_size)!=expected or len(body)!=TRANSFER_BYTES or hashlib.sha256(body).hexdigest()!=TRANSFER_SHA256: raise Failure("transfer_hash")
        raw=gzip.decompress(body)
        if len(raw)!=RAW_BYTES or hashlib.sha256(raw).hexdigest()!=RAW_SHA256: raise Failure("raw_hash")
        return dirfd,fd,before,raw
    except BaseException:
        if fd is not None: os.close(fd)
        os.close(dirfd)
        raise

def transfer_still_exact(dirfd,fd,before):
    try:
        os.lseek(fd,0,os.SEEK_SET); body=b""
        while len(body)<=TRANSFER_BYTES:
            chunk=os.read(fd,min(65536,TRANSFER_BYTES+1-len(body)))
            if not chunk: break
            body+=chunk
        current=os.fstat(fd); after=os.stat(os.path.basename(TRANSFER),dir_fd=dirfd,follow_symlinks=False)
        expected=(before.st_dev,before.st_ino,before.st_mode,before.st_uid,before.st_gid,before.st_nlink,before.st_size)
        return (current.st_dev,current.st_ino,current.st_mode,current.st_uid,current.st_gid,current.st_nlink,current.st_size)==expected and (after.st_dev,after.st_ino,after.st_mode,after.st_uid,after.st_gid,after.st_nlink,after.st_size)==expected and len(body)==TRANSFER_BYTES and hashlib.sha256(body).hexdigest()==TRANSFER_SHA256
    except BaseException: return False

def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise ValueError("duplicate")
        result[key]=value
    return result

def exact_contract(value,returncode,allow_executor=False):
    if type(value) is not dict: return False
    keys=set(value)
    if keys==CONNECTED:
        passed=returncode==0
        if returncode not in (0,3) or value["NOTEAI_ITEM26_RESTORED_CAPTURE"]!=("PASS" if passed else "FAIL") or value["incident_class"]!=("CONNECTED_KNOWN_READ_ONLY" if passed else "CONNECTED_KNOWN_READ_ONLY_MISMATCH") or value["verified"] is not passed or value["comparison_exact"] is not passed: return False
        if any(value[k] is not x for k,x in {"attempt_sentinel_retained":True,"automatic_retry_allowed":False,"control_material_retained":True,"new_capture_allowed":False,"owner_table_contract_exact":True,"readback_required":False,"reconciliation_retained":True,"restored_manifest_retained":True,"rls_contract_exact":True,"row_security_off":True,"same_invocation_replay_allowed":False,"search_path_exact":True,"task_root_retained":True,"transfer_retained":True}.items()): return False
        ints={"container_residue_count":0,"database_connection_count":1,"database_transaction_count":1,"database_write_count":0,"force_rls_table_count":0,"managed_owner_activation_count":1,"object_contents_read":0,"object_keys_emitted":0,"object_write_count":0,"oss_get_request_count":0,"owner_mismatch_count":0,"persistent_permission_mutation_count":0,"postgresql_major_version":16,"rls_table_count":19,"row_values_emitted":0,"runtime_container_start_count":1,"secret_values_emitted":0,"table_count":56}
        if any(type(value[k]) is not int or value[k]!=x for k,x in ints.items()) or type(value["manifest_bytes"]) is not int or value["manifest_bytes"]<1 or type(value["oss_list_request_count"]) is not int or value["oss_list_request_count"]<1 or type(value["oss_head_request_count"]) is not int or value["oss_head_request_count"]<0: return False
        if value["transaction_terminal"]!="ROLLBACK" or value["oss_operation_mode"]!="LIST_HEAD_ONLY" or value["reconciliation_schema_version"]!="noteai.item26.restored-reconciliation.v1" or any(type(value[k]) is not str or HEX64.fullmatch(value[k]) is None for k in ("restored_manifest_file_sha256","restored_manifest_sha256","source_manifest_sha256")): return False
        codes=value["mismatch_codes"]
        return type(codes) is list and all(type(x) is str for x in codes) and len(codes)==len(set(codes)) and not set(codes)-MISMATCH and (codes==[] if passed else bool(codes))
    if keys==PRECONNECT:
        return returncode==3 and value=={**value,"NOTEAI_ITEM26_RESTORED_CAPTURE":"FAIL","automatic_retry_allowed":False,"database_attempted_state":"NO","incident_class":"PRE_CONNECT","new_capture_allowed":False,"same_invocation_replay_allowed":False} and type(value["phase"]) is str and value["phase"] in PHASES
    if keys==UNKNOWN:
        return returncode==4 and value=={**value,"NOTEAI_ITEM26_RESTORED_CAPTURE":"UNKNOWN","automatic_retry_allowed":False,"database_attempted_state":"UNKNOWN","incident_class":"CONNECTED_UNKNOWN","new_capture_allowed":False,"readback_required":True,"same_invocation_replay_allowed":False} and type(value["phase"]) is str and value["phase"] in PHASES
    if allow_executor and keys==EXECUTOR:
        return returncode in (3,4) and value["NOTEAI_ITEM26_RESTORED_CAPTURE"]==("FAIL" if returncode==3 else "UNKNOWN") and value["automatic_retry_allowed"] is False and value["database_attempted_state"]==("NO" if returncode==3 else "UNKNOWN") and value["incident_class"]==("PRE_CONNECT" if returncode==3 else "CONNECTED_UNKNOWN") and value["new_capture_allowed"] is False and value["readback_required"] is (returncode==4) and value["same_invocation_replay_allowed"] is False and type(value["phase"]) is str and value["phase"] in EXECUTOR_PHASES and value["transfer_state"] in ({"UNVERIFIED","EXACT_RETAINED"} if returncode==3 else {"UNKNOWN"})
    return False

def run(raw):
    try:
        process=subprocess.Popen(["/bin/bash","-s"],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin","LC_ALL":"C"},close_fds=True,start_new_session=True)
    except BaseException: raise Failure("capture_spawn",False,"EXACT_RETAINED")
    try:
        stdout,stderr=process.communicate(raw,timeout=1320)
    except BaseException:
        try: os.killpg(process.pid,signal.SIGKILL)
        except BaseException: pass
        try: process.communicate(timeout=10)
        except BaseException: pass
        raise Failure("capture_timeout",True,"UNKNOWN")
    if len(stdout)+len(stderr)>4096: raise Failure("capture_output_limit",True,"UNKNOWN")
    return process.returncode,stdout,stderr

def validate_terminal(returncode,stdout,stderr):
    if returncode==0:
        body=stdout
        if not body or stderr: raise Failure("capture_pass_stream",True,"UNKNOWN")
    elif returncode in (3,4):
        body=stderr
        if stdout or not body: raise Failure("capture_failure_stream",True,"UNKNOWN")
    else: raise Failure("capture_returncode",True,"UNKNOWN")
    if not body.endswith(b"\n") or body.count(b"\n")!=1: raise Failure("capture_shape",True,"UNKNOWN")
    try: value=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
    except BaseException: raise Failure("capture_json",True,"UNKNOWN")
    if canonical(value)!=body or not exact_contract(value,returncode): raise Failure("capture_contract",True,"UNKNOWN")
    return body

dirfd=None; fd=None; spawned=False
try:
    if os.geteuid()!=0 or os.getegid()!=0 or type(TRANSFER_BYTES) is not int or type(RAW_BYTES) is not int or not 1<=TRANSFER_BYTES<=131072 or not 1<=RAW_BYTES<=131072 or HEX64.fullmatch(TRANSFER_SHA256) is None or HEX64.fullmatch(RAW_SHA256) is None: raise Failure("executor_preflight")
    dirfd,fd,before,raw=read_transfer()
    returncode,stdout,stderr=run(raw); spawned=True
    if not transfer_still_exact(dirfd,fd,before): raise Failure("transfer_after_capture",True,"UNKNOWN")
    terminal=validate_terminal(returncode,stdout,stderr)
    emit(json.loads(terminal.decode("ascii")),returncode,1 if returncode==0 else 2)
except Failure as exc:
    emit(fixed(exc.spawned,exc.phase,exc.transfer),4 if exc.spawned else 3,2)
except BaseException:
    emit(fixed(spawned,"executor_exception","UNKNOWN" if spawned else "UNVERIFIED"),4 if spawned else 3,2)
finally:
    if fd is not None: os.close(fd)
    if dirfd is not None: os.close(dirfd)
PY
