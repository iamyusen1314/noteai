"""Host launcher for the existing, bounded Native canary; no provider calls.

Prepare renders the existing collector SQL. The database owner applies that SQL
separately. Start temporarily binds the current API and Payment to one capture;
close drains them, seals the original journal, and restores the saved units.
The existing payment_canary_executor remains the only operator entry point.
"""
from pathlib import Path
import ast
import fcntl
import hashlib
import json
import os
import shlex
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import uuid

ROOT = Path('/var/lib/noteai/native-80b01ea/trade')
API_IMAGE = 'sha256:51f46b9a5ec522841379c97a6564c3f5b6ef02ee6b4b93cb85e6ab257d907589'
PAYMENT_IMAGE = 'sha256:62ffa056101ca1b573253364ed7d094abcb5d25e7c756e8e051ad65ce607b8e8'
CANARY_IMAGE = 'sha256:35097f4f4c5912f23de5affcf2d38958fff7c85270eee42ff50f7972e21bdf14'
USER_ID = '61d63b05-17eb-47d5-b19e-fb7eab297299'
APP_ID = 'wxfa4405963601a505'
API_UNIT = Path('/etc/systemd/system/noteai-api.service')
API_DROP = Path('/etc/systemd/system/noteai-api.service.d/public-product.conf')
PAYMENT_UNIT = Path('/etc/systemd/system/noteai-payment.service')
PROXIES = [Path('/etc/nginx/noteai-' + n + '-proxy.conf') for n in ('account', 'product')]
BOUND_ENV = Path('/var/lib/noteai/wechat-native-20260913/candidate-config/canary-bound.env')
HASHES = {
    str(API_UNIT): '46010368ded3db5567bca45afb75f18383ccf23de6aa6d0d99299d87701677e6',
    str(API_DROP): '4862ef72c0735c329a1967b766e1112b1e96e860c7a9b3fd28533b44f2a83d67',
    str(PAYMENT_UNIT): '40a49dbee82bbb6f617d2ec439b1ab608b980ceea60125a20dc09a83737547bb',
    str(BOUND_ENV): '861cc4be3dec07a5c20c1f271f87a566ab91bb61e4c3049add5e641d6db0f9bf',
    '/etc/noteai/public-account.env': '49690b5c2e4aa1612eae64c13adaead84ee80ec0fd7b399040bb275e062ecd8d',
    '/etc/noteai/payment.env': '5f16eb47778f0667849698e19a524c73c3d0f4fa35cba86baa3cdd3911e57a03',
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(domain, value):
    return digest(domain.encode() + b'\0' + value.encode())


def save(path, value):
    raw = json.dumps(value, sort_keys=True).encode()
    with path.open('xb') as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    os.fsync(directory)
    os.close(directory)


def helpers():
    old = Path('/var/lib/noteai/formal-claude-363f3e3/deploy.py').read_bytes()
    assert digest(old) == 'd679f27bbe99494b2711ee267c7506c936e8413b5d63ba289e76cb07d0b94bc2'
    names = {'run', 'inspect', 'put', 'runtime', 'call', 'health', 'idle', 'config_hash'}
    nodes = [n for n in ast.parse(old).body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert len(nodes) == len(names)
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'existing_deploy_helpers', 'exec'), globals())
    globals()['opener'] = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def api_read(code):
    return json.loads(run(['docker', 'exec', 'noteai-api-c', 'python', '-c', code], 20))


def check_original():
    for path, expected in HASHES.items():
        assert digest(Path(path).read_bytes()) == expected, path
    assert inspect('noteai-api-c')['Image'] == API_IMAGE
    assert run(['systemctl', 'show', 'noteai-payment.service', '-p', 'ActiveState', '--value']).strip() == b'inactive'
    assert not run(['docker', 'ps', '-aq', '--filter', 'name=^/noteai-payment$']).strip()
    for image in (API_IMAGE, PAYMENT_IMAGE, CANARY_IMAGE):
        info = json.loads(run(['docker', 'image', 'inspect', image]))[0]
        assert info['Architecture'] == 'amd64' and info['Os'] == 'linux'


def prepare():
    check_original()
    assert not ROOT.exists()
    os.chmod(ROOT.parent, 0o711)
    ROOT.mkdir(mode=0o700)
    (ROOT / 'before').mkdir(mode=0o700)
    work = ROOT / 'work'
    work.mkdir(mode=0o700)
    os.chown(work, 999, 999)
    activation = str(uuid.uuid4())
    key = 'item31-native-' + activation
    key_hash = identity('noteai-payment-idempotency-v1', key)
    targets = {
        'payment_orders': ['idempotency_key_hash', key_hash],
        'payment_events': ['provider_event_id_hash', '@authenticated-event'],
        'credits': ['user_id', USER_ID], 'credit_transactions': ['user_id', USER_ID],
        'subscriptions': ['user_id', 'forbidden-subscription-write'],
        'users': ['id', 'forbidden-user-write'],
        'usage_records': ['user_id', 'forbidden-usage-write'],
        'payment_reconciliation_runs': ['id', 'no-reconcile'],
        'payment_reconciliation_items': ['id', 'no-reconcile'],
        'payment_settlement_summaries': ['id', 'no-settlement'],
    }
    for table in ('payment_cash_ledger', 'payment_credit_positions', 'payment_entitlement_ledger',
                  'payment_refunds', 'payment_credit_consumptions'):
        targets[table] = ['order_id', '@order/' + key_hash]
    context = {'provider': 'wechatpay_direct',
               'activation_identity_sha256': identity('payment-canary-activation-v1', activation),
               'user_identity_sha256': identity('payment-canary-user-v1', USER_ID),
               'idempotency_identity_sha256': identity('noteai-item31-create-idempotency-v1', key)}
    binding = {'activation': activation, 'provider': 'wechatpay_direct', 'targets': targets,
               'work_directory': str(work), 'user_id': USER_ID, 'idempotency_key_hash': key_hash,
               'app_id': APP_ID, 'create_context': context, 'reconciliation_run_id': None}
    save(ROOT / 'binding.json', binding)
    os.chmod(ROOT / 'binding.json', 0o644)
    # Container UID can traverse only this prepared directory and its own work.
    os.chmod(ROOT, 0o711)
    code = "import collect_item31_canary_dml as d,json\nb=" + repr(binding) + "\n"
    code += "print(json.dumps({'install':[s.as_string() for s in d.installation_sql(b['activation'],b['targets'])],'remove':[s.as_string() for s in d.removal_sql(list(b['targets']))]}))"
    sql = api_read(code)
    for phase, statements in sql.items():
        text = 'BEGIN;\nSET LOCAL lock_timeout=\'5s\';\nSET LOCAL statement_timeout=\'30s\';\n'
        text += '\n'.join(s.rstrip(';') + ';' for s in statements) + '\nCOMMIT;\n'
        (ROOT / (phase + '.sql')).write_text(text)
    paths = [API_UNIT, API_DROP, PAYMENT_UNIT, *PROXIES]
    backups = {}
    for index, path in enumerate(paths):
        raw = path.read_bytes()
        name = str(index) + '-' + path.name
        (ROOT / 'before' / name).write_bytes(raw)
        backups[str(path)] = {'file': name, 'sha256': digest(raw)}
    save(ROOT / 'prepared.json', {'binding_sha256': digest((ROOT / 'binding.json').read_bytes()),
         'activation': activation, 'backups': backups, 'config_hash': config_hash(),
         'web': str(Path('/var/www/noteai-public/current').resolve()),
         'admin_image': inspect('noteai-admin-c')['Image'], 'at': time.time()})
    return {'state': 'PREPARED_NOT_ACTIVATED', 'activation': activation,
            'tables': len(targets), 'functions': 1, 'business_writes': 0, 'provider_requests': 0}


def originals():
    meta = json.loads((ROOT / 'prepared.json').read_text())
    result = {}
    for path, item in meta['backups'].items():
        raw = (ROOT / 'before' / item['file']).read_bytes()
        assert digest(raw) == item['sha256']
        result[Path(path)] = raw
    return meta, result


def api_running():
    p = subprocess.run(['docker', 'inspect', 'noteai-api-c'], capture_output=True, timeout=10)
    if p.returncode:
        assert b'No such' in p.stderr
        return False
    info = json.loads(p.stdout)[0]
    assert info['Image'] == API_IMAGE
    return bool(info['State']['Running'])


def drain():
    master = Path('/run/nginx.pid').read_text().strip()
    workers = [int(x.split()[0]) for x in run(['ps', '--ppid', master, '-o', 'pid=,args=']).decode().splitlines()
               if 'nginx: worker process' in x]
    for path in PROXIES:
        put(path, b'default_type application/json; add_header Retry-After 15 always; return 503;\n')
    run(['nginx', '-t'])
    run(['systemctl', 'reload', 'nginx'])
    for _ in range(45):
        if not any(Path('/proc/' + str(pid)).exists() for pid in workers) and (not api_running() or idle()):
            return
        time.sleep(1)
    raise RuntimeError('active_requests_not_drained')


def restore_ingress(before):
    for path in PROXIES:
        put(path, before[path])
    run(['nginx', '-t'])
    run(['systemctl', 'reload', 'nginx'])


def journal_readback():
    # Offline read of the original bytes after all peers and broker have exited.
    # Restored services alone never prove a sealed, complete capture.
    code = ("from pathlib import Path;import json,collect_item31_canary_dml as d;"
            "b=json.loads(Path(" + repr(str(ROOT / 'binding.json')) + ").read_text());"
            "print(json.dumps(d.read_journal(Path(b['work_directory'])/'canary-dml.jsonl',"
            "activation=b['activation'],coverage_sha256=d.coverage_sha256(b['targets']),provider=b['provider'])))")
    return json.loads(run(['docker', 'run', '--rm', '--pull=never', '--network=none',
        '--read-only', '--user=999:999', '--cap-drop=ALL', '--security-opt=no-new-privileges:true',
        '--env=PYTHON_DOTENV_DISABLED=1', '--entrypoint=python',
        '--mount=type=bind,src=' + str(ROOT / 'binding.json') + ',dst=' + str(ROOT / 'binding.json') + ',readonly',
        '--mount=type=bind,src=' + str(ROOT / 'work') + ',dst=' + str(ROOT / 'work') + ',readonly',
        CANARY_IMAGE, '-EsB', '-c', code], 30))


def activate():
    check_original()
    meta, before = originals()
    assert digest((ROOT / 'binding.json').read_bytes()) == meta['binding_sha256']
    assert not (ROOT / 'started.json').exists()
    code = "import db,json\nwith db.transaction(write=False) as tx:\n r=tx.fetchone(\"SELECT count(*) n FROM pg_trigger WHERE tgname='noteai_item31_canary_dml_notice' AND NOT tgisinternal\");f=tx.fetchone(\"SELECT pg_get_functiondef('public.noteai_item31_canary_dml_notice()'::regprocedure) AS body\");print(json.dumps({'n':r['n'],'matches':" + repr(meta['activation']) + " in f['body']}))"
    ready = api_read(code)
    assert ready == {'n': 15, 'matches': True}, 'reviewed_collector_not_installed'
    assert idle(), 'active_requests'
    starts = int(time.time())
    env = {
        'NOTEAI_PAYMENT_CANARY_ENABLED': '1', 'NOTEAI_PAYMENT_CANARY_ACTION': 'create-payment',
        'NOTEAI_PAYMENT_CANARY_PROVIDER': 'wechatpay_direct',
        'NOTEAI_PAYMENT_CANARY_ACTIVATION_ID': meta['activation'],
        'NOTEAI_PAYMENT_CANARY_USER_ID_SHA256': identity('payment-canary-user-v1', USER_ID),
        'NOTEAI_PAYMENT_CANARY_SUBJECT_HASH': identity('noteai-payment-subject-v1', USER_ID),
        'NOTEAI_PAYMENT_CANARY_IDEMPOTENCY_KEY_SHA256': identity('noteai-item31-create-idempotency-v1', 'item31-native-' + meta['activation']),
        'NOTEAI_PAYMENT_CANARY_AMOUNT_FEN': '1200',
        'NOTEAI_PAYMENT_CANARY_OWNER_TEST_ASSERTION': 'ITEM31-OWNER-CONTROLLED-TEST-ORDER',
        'NOTEAI_PAYMENT_CANARY_NOT_BEFORE_EPOCH': str(starts),
        'NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH': str(starts + 3600),
        'NOTEAI_ITEM31_DML_BINDING_FILE': str(ROOT / 'binding.json'),
        'NOTEAI_ITEM31_DML_BINDING_SHA256': meta['binding_sha256'],
        'NOTEAI_PAYMENT_ORDERING_ENABLED': '1', 'NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED': '1',
        'NOTEAI_PAYMENT_ORDER_PROVIDERS': 'wechatpay_direct',
        'NOTEAI_PAYMENT_CALLBACK_PROVIDERS': 'wechatpay_direct',
        'PGOPTIONS': '-c default_transaction_read_only=off -c statement_timeout=10000 -c lock_timeout=5000',
    }
    (ROOT / 'input.env').write_text(''.join(k + '=' + v + '\n' for k, v in env.items()))
    line = next(x[10:] for x in before[API_DROP].decode().splitlines() if x.startswith('ExecStart=/'))
    args = shlex.split(line)
    assert args[-1] == API_IMAGE and '--name=noteai-api-c' in args
    args = [x for x in args if not x.startswith('--env=PGOPTIONS=')]
    args[-1:-1] = ['--env-file=' + str(ROOT / 'input.env'),
                  '--mount=type=bind,src=' + str(ROOT / 'binding.json') + ',dst=' + str(ROOT / 'binding.json') + ',readonly',
                  '--mount=type=bind,src=' + str(ROOT / 'work') + ',dst=' + str(ROOT / 'work')]
    api_drop = '[Service]\nExecStart=\nExecStart=' + shlex.join(args) + '\n'
    api_unit = ('[Unit]\nDescription=NoteAI API with bounded Native capture\nRequires=docker.service\n'
                'After=docker.service network-online.target\n[Service]\nType=simple\nRestart=no\n'
                'TimeoutStopSec=45\nKillMode=process\nEnvironment=DOCKER_CONTEXT=default\n'
                'ExecStop=/usr/bin/docker stop --time=30 noteai-api-c\n')
    template = Path(__file__).with_name('systemd') / 'noteai-payment-canary-capture.service.template'
    payment_unit = template.read_text()
    for key, value in {'NOTEAI_PAYMENT_CALLBACK_ENABLED': '1', 'NOTEAI_ITEM31_ENV_FILE': str(ROOT / 'input.env'),
            'NOTEAI_ITEM31_BINDING_FILE': str(ROOT / 'binding.json'),
            'NOTEAI_ITEM31_WORK_DIRECTORY': str(ROOT / 'work'), 'NOTEAI_PAYMENT_IMAGE': PAYMENT_IMAGE,
            'NOTEAI_API_CONTAINER': 'noteai-api-c'}.items():
        payment_unit = payment_unit.replace('@@' + key + '@@', value)
    assert '@@' not in payment_unit
    save(ROOT / 'started.json', {'starts': starts, 'expires': starts + 3600, 'at': time.time()})
    changed = False
    try:
        drain()
        changed = True
        run(['systemctl', 'stop', 'noteai-api.service'], 60)
        put(API_UNIT, api_unit.encode())
        put(API_DROP, api_drop.encode())
        put(PAYMENT_UNIT, payment_unit.encode())
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'start', '--no-block', 'noteai-api.service'])
        for _ in range(100):
            p = subprocess.run(['docker', 'inspect', 'noteai-api-c'], capture_output=True, timeout=5)
            if p.returncode == 0 and json.loads(p.stdout)[0]['State']['Running']:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('api_namespace_unavailable')
        run(['systemctl', 'start', '--no-block', 'noteai-payment.service'])
        health('api', 8000)
        assert inspect('noteai-api-c')['Image'] == API_IMAGE
        assert inspect('noteai-payment')['Image'] == PAYMENT_IMAGE
        assert api_read("import asyncio,api,json;print(json.dumps({'ready':asyncio.run(api._payment_callback_runtime_ready())}))")['ready']
        assert config_hash() == meta['config_hash']
        save(ROOT / 'active.json', {'state': 'ACTIVE_OWNER_ONLY', 'expires': starts + 3600,
             'api_container': inspect('noteai-api-c')['Id'], 'payment_container': inspect('noteai-payment')['Id'], 'at': time.time()})
        restore_ingress(before)
    except BaseException:
        if changed:
            close()
        else:
            restore_ingress(before)
        raise
    return {'state': 'ACTIVE_OWNER_ONLY', 'expires': starts + 3600}


def close():
    meta, before = originals()
    if (ROOT / 'closed.json').exists():
        return json.loads((ROOT / 'closed.json').read_text())
    result = {'state': 'UNKNOWN', 'at': time.time()}
    try:
        drain()
        # Never stop the broker before its actual API/operator peers exit.
        operators = run(['docker', 'ps', '-q', '--filter', 'label=com.noteai.native-operator=' + meta['activation']]).strip()
        assert not operators, 'operator_still_running'
        run(['systemctl', 'stop', 'noteai-api.service'], 60)
        run(['systemctl', 'stop', 'noteai-payment.service'], 60)
        for path in (API_UNIT, API_DROP, PAYMENT_UNIT):
            put(path, before[path])
        run(['systemctl', 'daemon-reload'])
        run(['systemctl', 'start', 'noteai-api.service'], 75)
        health('api', 8000)
        restore_ingress(before)
        assert inspect('noteai-api-c')['Image'] == API_IMAGE
        assert inspect('noteai-admin-c')['Image'] == meta['admin_image']
        assert str(Path('/var/www/noteai-public/current').resolve()) == meta['web']
        for path in (API_UNIT, API_DROP, PAYMENT_UNIT):
            assert path.read_bytes() == before[path]
        result['state'] = 'SERVICES_RESTORED_COLLECTOR_REMOVAL_PENDING'
        try:
            result['journal'] = journal_readback()
        except Exception as exc:
            result['journal'] = {'status': 'UNKNOWN', 'error_type': type(exc).__name__}
    finally:
        save(ROOT / ('closed.json' if result['state'] != 'UNKNOWN' else 'close-unknown-' + str(int(time.time())) + '.json'), result)
    return result


def main():
    assert socket.gethostname() == 'noteai-api-c' and os.geteuid() == 0
    os.umask(0o077)
    helpers()
    if sys.argv[1:] == ['prepare']:
        result = prepare()
    elif sys.argv[1:] == ['run']:
        lock = (ROOT / 'control.lock').open('a')
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        save(ROOT / 'runner.json', {'pid': os.getpid(),
             'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
             'start_ticks': Path('/proc/self/stat').read_text().split(') ', 1)[1].split()[19],
             'source_sha256': digest(Path(__file__).read_bytes())})
        result = activate()
        print(json.dumps(result), flush=True)
        while time.time() < result['expires'] and not (ROOT / 'close.request').exists():
            time.sleep(2)
        result = close()
    elif sys.argv[1:] == ['close']:
        runner = json.loads((ROOT / 'runner.json').read_text())
        proc = Path('/proc') / str(runner['pid'])
        try:
            alive = (Path('/proc/sys/kernel/random/boot_id').read_text().strip() == runner['boot_id']
                and (proc / 'stat').read_text().split(') ', 1)[1].split()[19] == runner['start_ticks'])
        except FileNotFoundError:
            alive = False
        if alive:
            (ROOT / 'close.request').touch(exist_ok=True)
            result = {'state': 'CLOSE_REQUESTED_READ_ORIGINAL_RESULT'}
        else:
            # Recover only the original activation after its process exited.
            # A host restart/PID reuse cannot silently start a second capture.
            lock = (ROOT / 'control.lock').open('a')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = close()
    else:
        raise ValueError('prepare, run or close required')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
