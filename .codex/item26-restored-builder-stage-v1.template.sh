#!/usr/bin/env bash
set -Eeuo pipefail
set +x
umask 077
export LC_ALL=C
export PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy NO_PROXY no_proxy
unset PYTHONPATH PYTHONHOME PYTHONSTARTUP PYTHONINSPECT PYTHONOPTIMIZE
unset DATABASE_URL PGPASSWORD ALIBABA_CLOUD_ACCESS_KEY_ID ALIBABA_CLOUD_ACCESS_KEY_SECRET ALIBABA_CLOUD_SECURITY_TOKEN

exec python3 -I -B - <<'PY'
import base64,hashlib,json,os,re,stat,subprocess,urllib.request

MODE="@@MODE@@"
BUILDER_IDENTITY_SHA256="@@BUILDER_IDENTITY_SHA256@@"
RECIPIENT_PUBLIC_KEY_SHA256="@@RECIPIENT_PUBLIC_KEY_SHA256@@"
ENVELOPE_BYTES=@@ENVELOPE_BYTES@@
ENVELOPE_SHA256="@@ENVELOPE_SHA256@@"
TRANSFER_BYTES=@@TRANSFER_BYTES@@
TRANSFER_SHA256="@@TRANSFER_SHA256@@"
BASE="/var/lib/noteai/item26-restored-v1"
CONTROL=BASE+"/control"
PRIVATE=CONTROL+"/control-private.pem"
PUBLIC=CONTROL+"/control-public.pem"
KEYGEN=BASE+"/keygen-public-metadata.json"
ENVELOPE=CONTROL+"/control-envelope-successor-v1.json"
TRANSFER=BASE+"/restored-capture-transfer-successor-v1.sh.gz"
RECEIPT=BASE+"/stage-receipt-v1.json"
HEX64=re.compile(r"^[0-9a-f]{64}$")

class Failure(Exception):
    def __init__(self,phase,unknown=False):
        Exception.__init__(self,phase); self.phase=phase; self.unknown=unknown

def canonical(value,newline=True):
    body=json.dumps(value,ensure_ascii=True,sort_keys=True,separators=(",",":"),allow_nan=False).encode("ascii")
    return body+(b"\n" if newline else b"")

def no_duplicates(pairs):
    result={}
    for key,value in pairs:
        if key in result: raise Failure("duplicate",True)
        result[key]=value
    return result

def emit(value,code):
    body=canonical(value)
    if len(body)>4096: os._exit(4)
    try:
        if os.write(1 if code==0 else 2,body)!=len(body): os._exit(4)
    except BaseException: os._exit(4)
    os._exit(code)

def fixed(state,phase):
    value={"NOTEAI_ITEM26_RESTORED_BUILDER_STAGE":state,"automatic_retry_allowed":False,"materials_retained":True,"new_sendfile_allowed":False,"phase":phase,"same_invocation_replay_allowed":False,"secret_values_emitted":0}
    if state=="UNKNOWN": value["readback_required"]=True
    return value

def metadata(path,kind,mode=None,size=None):
    row=os.lstat(path)
    if kind=="dir":
        if not stat.S_ISDIR(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=(mode or 0o700): raise Failure("metadata",True)
    else:
        if not stat.S_ISREG(row.st_mode) or stat.S_ISLNK(row.st_mode) or row.st_uid or row.st_gid or stat.S_IMODE(row.st_mode)!=(mode or 0o600) or row.st_nlink!=1 or (size is not None and row.st_size!=size): raise Failure("metadata",True)
    return row

def stable(path,low,high,do_fsync=False):
    before=metadata(path,"file")
    if not low<=before.st_size<=high: raise Failure("metadata",True)
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        body=b""
        while len(body)<=high:
            chunk=os.read(fd,min(65536,high+1-len(body)))
            if not chunk: break
            body+=chunk
        opened=os.fstat(fd)
        if do_fsync: os.fsync(fd)
        closed=os.fstat(fd)
    finally: os.close(fd)
    final=os.lstat(path)
    first=(before.st_dev,before.st_ino,before.st_mode,before.st_uid,before.st_gid,before.st_nlink,before.st_size)
    if first!=(opened.st_dev,opened.st_ino,opened.st_mode,opened.st_uid,opened.st_gid,opened.st_nlink,opened.st_size) or first!=(closed.st_dev,closed.st_ino,closed.st_mode,closed.st_uid,closed.st_gid,closed.st_nlink,closed.st_size) or first!=(final.st_dev,final.st_ino,final.st_mode,final.st_uid,final.st_gid,final.st_nlink,final.st_size) or len(body)!=before.st_size: raise Failure("race",True)
    return body

def fsync_dir(path):
    fd=os.open(path,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try: os.fsync(fd)
    finally: os.close(fd)

def identity():
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl): raise RuntimeError("redirect")
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    req=urllib.request.Request("http://100.100.100.200/latest/api/token",method="PUT",headers={"X-aliyun-ecs-metadata-token-ttl-seconds":"60"})
    with opener.open(req,timeout=3) as response: token=response.read(512).decode("ascii").strip()
    if not token or len(token)>256: raise Failure("identity")
    headers={"X-aliyun-ecs-metadata-token":token}; values=[]
    for suffix in ("instance-id","ram/security-credentials/"):
        req=urllib.request.Request("http://100.100.100.200/latest/meta-data/"+suffix,headers=headers,method="GET")
        with opener.open(req,timeout=3) as response: body=response.read(4096)
        if len(body)>=4096: raise Failure("identity")
        values.append(body.decode("ascii").strip())
    roles=[row for row in values[1].splitlines() if row]
    if not re.fullmatch(r"i-[a-z0-9]+",values[0]) or len(roles)!=1 or hashlib.sha256(canonical({"instance_id":values[0],"ram_role":roles[0]},False)).hexdigest()!=BUILDER_IDENTITY_SHA256: raise Failure("identity")

def public_contract():
    metadata("/var/lib/noteai","dir",0o700); metadata(BASE,"dir",0o700); metadata(CONTROL,"dir",0o700)
    private=stable(PRIVATE,1,8192); public=stable(PUBLIC,625,625); keygen=stable(KEYGEN,1,4096)
    der=subprocess.check_output(["/usr/bin/openssl","pkey","-pubin","-outform","DER"],input=public,stderr=subprocess.DEVNULL)
    private_der=subprocess.check_output(["/usr/bin/openssl","pkey","-in","-","-pubout","-outform","DER"],input=private,stderr=subprocess.DEVNULL); del private
    try: row=json.loads(keygen.decode("ascii"),object_pairs_hook=no_duplicates)
    except BaseException: raise Failure("keygen",True)
    expected={"NOTEAI_ITEM26_RESTORED_BUILDER_KEYGEN":"PASS","automatic_retry_allowed":False,"builder_identity_sha256":BUILDER_IDENTITY_SHA256,"private_key_created":True,"private_key_pair_verified":True,"private_key_value_read_count":1,"public_der_sha256":hashlib.sha256(der).hexdigest(),"public_key_pem_b64":base64.b64encode(public).decode("ascii"),"same_invocation_replay_allowed":False,"schema_version":1}
    if private_der!=der or expected["public_der_sha256"]!=RECIPIENT_PUBLIC_KEY_SHA256 or canonical(expected)!=keygen: raise Failure("key_pair",True)

def artifact(path,size,digest,do_fsync=False):
    if not os.path.lexists(path): return False
    body=stable(path,size,size,do_fsync)
    if hashlib.sha256(body).hexdigest()!=digest: raise Failure("artifact_hash",True)
    return True

def receipt_value():
    return {"NOTEAI_ITEM26_RESTORED_BUILDER_STAGE":"PASS","automatic_retry_allowed":False,"builder_identity_sha256":BUILDER_IDENTITY_SHA256,"control_inventory_exact":True,"envelope_bytes":ENVELOPE_BYTES,"envelope_sha256":ENVELOPE_SHA256,"materials_retained":True,"new_sendfile_allowed":False,"recipient_public_key_sha256":RECIPIENT_PUBLIC_KEY_SHA256,"same_invocation_replay_allowed":False,"schema_version":1,"secret_values_emitted":0,"transfer_bytes":TRANSFER_BYTES,"transfer_sha256":TRANSFER_SHA256}

def read_receipt():
    body=stable(RECEIPT,1,4096)
    try: row=json.loads(body.decode("ascii"),object_pairs_hook=no_duplicates)
    except BaseException: raise Failure("receipt",True)
    if canonical(row)!=body or row!=receipt_value(): raise Failure("receipt",True)
    return row

def finalize():
    if os.path.lexists(RECEIPT): raise Failure("replay_barrier",True)
    if sorted(os.listdir(BASE))!=["control","keygen-public-metadata.json","restored-capture-transfer-successor-v1.sh.gz"]: raise Failure("base_inventory",True)
    if sorted(os.listdir(CONTROL))!=["control-envelope-successor-v1.json","control-private.pem","control-public.pem"]: raise Failure("control_inventory",True)
    if artifact(ENVELOPE,ENVELOPE_BYTES,ENVELOPE_SHA256,True) is not True or artifact(TRANSFER,TRANSFER_BYTES,TRANSFER_SHA256,True) is not True: raise Failure("artifact_absent",True)
    fsync_dir(CONTROL); fsync_dir(BASE)
    body=canonical(receipt_value()); fd=os.open(RECEIPT,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        offset=0
        while offset<len(body):
            count=os.write(fd,body[offset:])
            if count<=0: raise Failure("receipt_write",True)
            offset+=count
        os.fchown(fd,0,0); os.fchmod(fd,0o600); os.fsync(fd)
    finally: os.close(fd)
    fsync_dir(BASE); read_receipt(); emit(receipt_value(),0)

def readback():
    envelope=artifact(ENVELOPE,ENVELOPE_BYTES,ENVELOPE_SHA256)
    transfer=artifact(TRANSFER,TRANSFER_BYTES,TRANSFER_SHA256)
    receipt=os.path.lexists(RECEIPT)
    inventory=sorted(os.listdir(CONTROL))
    base_inventory=sorted(os.listdir(BASE))
    if receipt:
        if not envelope or not transfer or inventory!=["control-envelope-successor-v1.json","control-private.pem","control-public.pem"] or base_inventory!=["control","keygen-public-metadata.json","restored-capture-transfer-successor-v1.sh.gz","stage-receipt-v1.json"]: raise Failure("terminal_inventory",True)
        emit(read_receipt(),0)
    if not envelope and not transfer and inventory==["control-private.pem","control-public.pem"] and base_inventory==["control","keygen-public-metadata.json"]: state="KEYGEN_ONLY"
    elif envelope and not transfer and inventory==["control-envelope-successor-v1.json","control-private.pem","control-public.pem"] and base_inventory==["control","keygen-public-metadata.json"]: state="ENVELOPE_EXACT"
    elif envelope and transfer and inventory==["control-envelope-successor-v1.json","control-private.pem","control-public.pem"] and base_inventory==["control","keygen-public-metadata.json","restored-capture-transfer-successor-v1.sh.gz"]: state="READY_TO_FINALIZE"
    else: raise Failure("partial_inventory",True)
    emit({"NOTEAI_ITEM26_RESTORED_BUILDER_STAGE":state,"automatic_retry_allowed":False,"finalize_allowed":state=="READY_TO_FINALIZE","materials_retained":True,"new_sendfile_allowed":False,"same_invocation_replay_allowed":False,"secret_values_emitted":0},0)

try:
    if os.geteuid()!=0 or os.getegid()!=0 or MODE not in {"FINALIZE","READBACK"} or any(HEX64.fullmatch(value) is None for value in (BUILDER_IDENTITY_SHA256,RECIPIENT_PUBLIC_KEY_SHA256,ENVELOPE_SHA256,TRANSFER_SHA256)) or not 1<=ENVELOPE_BYTES<=12288 or not 1<=TRANSFER_BYTES<=24576: raise Failure("preflight")
    identity(); public_contract(); finalize() if MODE=="FINALIZE" else readback()
except Failure as exc:
    emit(fixed("UNKNOWN" if exc.unknown else "FAIL",exc.phase),4 if exc.unknown else 3)
except BaseException:
    emit(fixed("UNKNOWN","unexpected"),4)
PY
