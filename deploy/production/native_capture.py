"""Host launcher for the existing, bounded Native canary; no provider calls.

Prepare renders the existing collector SQL. The database owner applies that SQL
separately. Start temporarily binds the current API and Payment to one capture;
close drains them, seals the original journal, and restores the saved units.
The existing payment_canary_executor remains the only operator entry point.
prepare-bill/run-bill/close-bill retain the original order and action ledger; only
Payment is temporarily started after next-day bill availability. API is unchanged.
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

ROOT = Path('/var/lib/noteai/native-6c9221e/trade')
API_IMAGE = 'sha256:5ab062cff52514d48c37aaeeb430b009584c7f7708db73423174c5b565fbf361'
PAYMENT_IMAGE = 'sha256:15d15189ea5c414933b20d84ef7889b0cd3a6b8faca9439f1f05fc264cc81584'
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
    str(API_DROP): '8daf5abbc33b3dbeb559ef28e5b77cf719e64e62b95251025fa245d6d1ad9fbf',
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
    # A completed, stopped prior capture can retain systemd's failure status.
    # Preserve that history; absence of a job/container is independently required.
    assert run(['systemctl', 'show', 'noteai-payment.service', '-p', 'ActiveState', '--value']).strip() in (b'inactive', b'failed')
    assert run(['systemctl', 'show', 'noteai-payment.service', '-p', 'Job', '--value']).strip() in (b'', b'0')
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
        (ROOT / (phase + '-dms.sql')).write_text(dms_transaction(
            statements, binding['activation'], removal=phase == 'remove'))
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
    # Offline read after admitted actions and broker exit. The idle API network
    # owner may still exist; it cannot append to the broker's sealed file.
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
        'NOTEAI_ITEM31_WECHAT_ACK_FAILURE_ONCE': meta['activation'],
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
        # Ingress is closed and requests are drained. The API container owns
        # Payment's network namespace: keep it alive until the broker has sent
        # its final database notification and sealed. Stopping the owner first
        # removes the follower's route even though its process is still alive.
        operators = run(['docker', 'ps', '-q', '--filter', 'label=com.noteai.native-operator=' + meta['activation']]).strip()
        assert not operators, 'operator_still_running'
        run(['systemctl', 'stop', 'noteai-payment.service'], 60)
        try:
            result['journal'] = journal_readback()
        except Exception as exc:
            result['journal'] = {'status': 'UNKNOWN', 'error_type': type(exc).__name__}
        run(['systemctl', 'stop', 'noteai-api.service'], 60)
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
    finally:
        save(ROOT / ('closed.json' if result['state'] != 'UNKNOWN' else 'close-unknown-' + str(int(time.time())) + '.json'), result)
    return result


def bill_binding(original, directory, activation, run_id):
    """New capture of the original order, never a second create authorization."""
    assert original['provider'] == 'wechatpay_direct' and original['user_id'] == USER_ID
    assert original['app_id'] == APP_ID and original['reconciliation_run_id'] is None
    assert str(uuid.UUID(activation)) == activation and str(uuid.UUID(run_id)) == run_id
    assert activation != original['activation']
    result = json.loads(json.dumps(original))
    result.update(activation=activation, work_directory=str(directory), reconciliation_run_id=run_id)
    result['targets']['payment_reconciliation_runs'] = ['id', run_id]
    result['targets']['payment_reconciliation_items'] = ['run_id', run_id]
    assert result['create_context'] == original['create_context']
    assert result['idempotency_key_hash'] == original['idempotency_key_hash']
    return result


def bill_originals_intact(meta):
    current = inspect('noteai-api-c')
    assert current['Id'] == meta['api_container'] and current['Image'] == meta['api_image'] and current['State']['Running']
    for path, expected in meta['unchanged_files'].items():
        assert digest(Path(path).read_bytes()) == expected, 'original_configuration_changed'
    assert config_hash() == meta['config_hash']
    assert str(Path('/var/www/noteai-public/current').resolve()) == meta['web']
    assert inspect('noteai-admin-c')['Image'] == meta['admin_image']
    for name, expected in meta['original_action_ledger'].items():
        assert digest((Path('/var/lib/noteai/payment-canary-actions')/name).read_bytes())==expected, 'original_action_record_changed'
    original = Path(meta['trade_directory'])
    for name, expected in meta['original_evidence'].items():
        assert digest((original / name).read_bytes()) == expected, 'original_trade_evidence_changed'


def dms_transaction(statements, activation, *, removal=False,
                    owner='noteai_admin', database='noteai'):
    """Transport existing collector DDL as one atomic DMS statement."""
    assert str(uuid.UUID(activation)) == activation
    literal = lambda value: "'" + str(value).replace("'", "''") + "'"
    lines = ["DO $noteai$", "BEGIN",
        "  IF current_user <> " + literal(owner) + " OR current_database() <> " + literal(database) +
        " THEN RAISE EXCEPTION 'owner identity mismatch'; END IF;",
        "  PERFORM set_config('lock_timeout','5s',true);",
        "  PERFORM set_config('statement_timeout','30s',true);"]
    if removal:
        lines.append("  IF position(" + literal(activation) +
            " in pg_get_functiondef('public.noteai_item31_canary_dml_notice()'::regprocedure))=0"
            " THEN RAISE EXCEPTION 'capture identity mismatch'; END IF;")
    else:
        lines.append("  IF to_regprocedure('public.noteai_item31_canary_dml_notice()') IS NOT NULL"
            " OR EXISTS(SELECT 1 FROM pg_trigger WHERE tgname='noteai_item31_canary_dml_notice')"
            " THEN RAISE EXCEPTION 'existing capture must be reconciled'; END IF;")
    for statement in statements:
        assert '$noteai$' not in statement
        lines.append('  EXECUTE ' + literal(statement) + ';')
    return '\n'.join(lines + ['END', '$noteai$;', ''])


def prepare_bill():
    trade = Path('/var/lib/noteai/native-80b01ea/trade')
    assert ROOT == trade.parent / 'bill-20260914' and not ROOT.exists()
    assert run(['systemctl','show','noteai-payment.service','-p','ActiveState','--value']).strip() in (b'inactive', b'failed')
    assert run(['systemctl','show','noteai-payment.service','-p','Job','--value']).strip() in (b'', b'0')
    assert not run(['docker','ps','-aq','--filter','name=^/noteai-payment$']).strip()
    for path in (PAYMENT_UNIT, BOUND_ENV):
        assert digest(path.read_bytes()) == HASHES[str(path)]
    original_bytes=(trade/'binding.json').read_bytes()
    assert digest(original_bytes)==json.loads((trade/'prepared.json').read_text())['binding_sha256']
    original = json.loads(original_bytes)
    ledger=Path('/var/lib/noteai/payment-canary-actions')
    import stat
    lm=ledger.lstat();assert stat.S_ISDIR(lm.st_mode) and lm.st_uid==999 and stat.S_IMODE(lm.st_mode)==0o700
    ledger_entries={p.name:digest(p.read_bytes()) for p in ledger.glob('*.json') if p.is_file() and not p.is_symlink()}
    assert ledger_entries, 'original_action_ledger_missing'
    assert json.loads((trade/'closed.json').read_text())['state'] == 'SERVICES_RESTORED_COLLECTOR_REMOVAL_PENDING'
    # Current app role reads its original order only, without owner credentials.
    order_id = '1e2acc0a-ebf6-4830-9cd3-e1bccfa4a8a6'
    code = "import db,json;r=db.fetchone(\"SELECT id,user_id,provider,payment_status,refund_status,refunded_fen,amount_fen,idempotency_key_hash FROM payment_orders WHERE id=?\",(" + repr(order_id) + ",));print(json.dumps(dict(r or {})))"
    order = api_read(code)
    assert order['user_id'] == USER_ID and order['provider'] == 'wechatpay_direct' and order['amount_fen'] == 1200
    assert order['idempotency_key_hash'] == original['idempotency_key_hash']
    assert order['payment_status']=='succeeded' and order['refund_status']=='refunded' and order['refunded_fen']==1200
    assert api_read("import db,json;print(json.dumps({'n':db.fetchone(\"SELECT count(*) n FROM pg_trigger WHERE tgname='noteai_item31_canary_dml_notice'\")['n']}))")['n'] == 0
    current = inspect('noteai-api-c')
    assert current['State']['Running']
    for image in (PAYMENT_IMAGE, CANARY_IMAGE):
        info = json.loads(run(['docker','image','inspect',image]))[0]
        assert info['Architecture'] == 'amd64' and info['Os'] == 'linux'
    ROOT.mkdir(mode=0o711)
    os.chmod(ROOT,0o711)  # umask077 must not prevent the runtime UID traversing.
    (ROOT/'before').mkdir(mode=0o700)
    work=ROOT/'work';work.mkdir(mode=0o700);os.chown(work,999,999)
    binding=bill_binding(original,work,str(uuid.uuid4()),str(uuid.uuid4()))
    save(ROOT/'binding.json',binding);os.chmod(ROOT/'binding.json',0o644)
    code="import collect_item31_canary_dml as d,json;b="+repr(binding)+";print(json.dumps({'install':[s.as_string() for s in d.installation_sql(b['activation'],b['targets'])],'remove':[s.as_string() for s in d.removal_sql(list(b['targets']))]}))"
    for phase, statements in api_read(code).items():
        (ROOT/(phase+'.sql')).write_text("BEGIN;\nSET LOCAL lock_timeout='5s';\nSET LOCAL statement_timeout='30s';\n"+'\n'.join(s.rstrip(';')+';' for s in statements)+'\nCOMMIT;\n')
        (ROOT/(phase+'-dms.sql')).write_text(dms_transaction(
            statements, binding['activation'], removal=phase=='remove'))
    raw=PAYMENT_UNIT.read_bytes();(ROOT/'before/payment.service').write_bytes(raw)
    unchanged={str(p):digest(p.read_bytes()) for p in (API_UNIT,API_DROP,*PROXIES,BOUND_ENV,Path('/etc/noteai/public-account.env'),Path('/etc/noteai/payment.env'))}
    evidence={name:digest((trade/name).read_bytes()) for name in ('binding.json','closed.json','final-readback.json','work/canary-dml.jsonl.incomplete')}
    meta={'mode':'bill','order_id':order_id,'bill_date':'2026-09-14','activation':binding['activation'],
          'binding_sha256':digest((ROOT/'binding.json').read_bytes()),'trade_directory':str(trade),
          'original_evidence':evidence,'original_action_ledger':ledger_entries,'api_image':current['Image'],'api_container':current['Id'],
          'unchanged_files':unchanged,'config_hash':config_hash(),'admin_image':inspect('noteai-admin-c')['Image'],
          'web':str(Path('/var/www/noteai-public/current').resolve()),
          'backups':{str(PAYMENT_UNIT):{'file':'payment.service','sha256':digest(raw)}},'at':time.time()}
    save(ROOT/'prepared.json',meta)
    return {'state':'BILL_PREPARED_NOT_ACTIVATED','activation':binding['activation'],'order_id':order_id,'provider_requests':0,'business_writes':0}


def bill_environment(meta, binding, starts):
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    available=datetime.strptime(meta['bill_date'],'%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Shanghai'))+timedelta(days=1,hours=10)
    assert starts >= int(available.timestamp()), 'bill_not_available_before_next_day_10BJT'
    assert binding['reconciliation_run_id'] and binding['activation'] == meta['activation']
    return {'NOTEAI_PAYMENT_CANARY_ENABLED':'1','NOTEAI_PAYMENT_CANARY_ACTION':'reconcile',
       'NOTEAI_PAYMENT_CANARY_PROVIDER':'wechatpay_direct','NOTEAI_PAYMENT_CANARY_ORDER_ID':meta['order_id'],
       'NOTEAI_PAYMENT_CANARY_BILL_DATE':meta['bill_date'],'NOTEAI_PAYMENT_CANARY_ACTIVATION_ID':meta['activation'],
       'NOTEAI_PAYMENT_CANARY_USER_ID_SHA256':identity('payment-canary-user-v1',USER_ID),
       'NOTEAI_PAYMENT_CANARY_SUBJECT_HASH':identity('noteai-payment-subject-v1',USER_ID),
       'NOTEAI_PAYMENT_CANARY_AMOUNT_FEN':'1200','NOTEAI_PAYMENT_CANARY_OWNER_TEST_ASSERTION':'ITEM31-OWNER-CONTROLLED-TEST-ORDER',
       'NOTEAI_PAYMENT_CANARY_NOT_BEFORE_EPOCH':str(starts),'NOTEAI_PAYMENT_CANARY_EXPIRES_EPOCH':str(starts+3600),
       'NOTEAI_ITEM31_DML_BINDING_FILE':str(ROOT/'binding.json'),'NOTEAI_ITEM31_DML_BINDING_SHA256':meta['binding_sha256'],
       'NOTEAI_PAYMENT_ORDERING_ENABLED':'0','NOTEAI_PAYMENT_CALLBACK_RELAY_ENABLED':'0','NOTEAI_PAYMENT_CALLBACK_ENABLED':'0',
       'NOTEAI_ITEM31_WECHAT_ACK_FAILURE_ONCE':'',
       'NOTEAI_PAYMENT_ORDER_PROVIDERS':'wechatpay_direct','NOTEAI_PAYMENT_CALLBACK_PROVIDERS':'wechatpay_direct',
       'PGOPTIONS':'-c default_transaction_read_only=off -c statement_timeout=10000 -c lock_timeout=5000'}


def close_bill():
    if (ROOT/'closed.json').exists():
        return json.loads((ROOT/'closed.json').read_text())
    meta,before=originals()
    result={'state':'UNKNOWN','at':time.time()}
    try:
        try:
            bill_originals_intact(meta)
        except Exception as drift:
            result['original_state_drift']=type(drift).__name__
        operators=run(['docker','ps','-q','--filter','label=com.noteai.native-operator='+meta['activation']]).strip()
        if operators:
            result['reason']='operator_still_running_read_original_result'
            return result
        # Restore Payment even after API/config drift. Never touch the API;
        # a lost namespace may make the original journal UNKNOWN, not reusable.
        run(['systemctl','stop','noteai-payment.service'],60)
        try:
            result['journal']=journal_readback()
        except Exception as exc:
            result['journal']={'status':'UNKNOWN','error_type':type(exc).__name__}
        put(PAYMENT_UNIT,before[PAYMENT_UNIT]);run(['systemctl','daemon-reload'])
        assert PAYMENT_UNIT.read_bytes()==before[PAYMENT_UNIT]
        result['payment_restored']=True
        if 'original_state_drift' not in result:
            bill_originals_intact(meta)
            result['state']='BILL_PAYMENT_RESTORED_COLLECTOR_REMOVAL_PENDING'
        return result
    finally:
        save(ROOT/('closed.json' if result['state']!='UNKNOWN' else 'close-unknown-'+str(time.time_ns())+'.json'),result)


def run_bill():
    meta,before=originals();assert meta['mode']=='bill'
    binding=json.loads((ROOT/'binding.json').read_text())
    assert digest((ROOT/'binding.json').read_bytes())==meta['binding_sha256']
    assert not (ROOT/'started.json').exists()
    bill_originals_intact(meta)
    assert PAYMENT_UNIT.read_bytes()==before[PAYMENT_UNIT]
    assert not run(['docker','ps','-aq','--filter','name=^/noteai-payment$']).strip()
    ready=api_read("import db,json;r=db.fetchone(\"SELECT count(*) n FROM pg_trigger WHERE tgname='noteai_item31_canary_dml_notice' AND NOT tgisinternal\");f=db.fetchone(\"SELECT pg_get_functiondef('public.noteai_item31_canary_dml_notice()'::regprocedure) body\");print(json.dumps({'n':r['n'],'matches':"+repr(meta['activation'])+" in f['body']}))")
    assert ready=={'n':15,'matches':True}
    starts=int(time.time());env=bill_environment(meta,binding,starts)
    with (ROOT/'input.env').open('x') as f:
        f.write(''.join(k+'='+v+'\n' for k,v in env.items()));f.flush();os.fsync(f.fileno())
    template=(Path(__file__).with_name('systemd')/'noteai-payment-canary-capture.service.template').read_text()
    for key,value in {'NOTEAI_PAYMENT_CALLBACK_ENABLED':'0','NOTEAI_ITEM31_ENV_FILE':str(ROOT/'input.env'),
       'NOTEAI_ITEM31_BINDING_FILE':str(ROOT/'binding.json'),'NOTEAI_ITEM31_WORK_DIRECTORY':str(ROOT/'work'),
       'NOTEAI_PAYMENT_IMAGE':PAYMENT_IMAGE,'NOTEAI_API_CONTAINER':meta['api_container']}.items():
        template=template.replace('@@'+key+'@@',value)
    assert '@@' not in template
    save(ROOT/'started.json',{'starts':starts,'expires':starts+3600,'at':time.time()})
    try:
        put(PAYMENT_UNIT,template.encode());run(['systemctl','daemon-reload']);run(['systemctl','start','--no-block','noteai-payment.service'])
        for _ in range(60):
            try:
                current=inspect('noteai-payment')
                if current['State']['Running'] and current['Image']==PAYMENT_IMAGE and api_read("import json,urllib.request;op=urllib.request.build_opener(urllib.request.ProxyHandler({}));print(json.dumps({'status':op.open('http://127.0.0.1:8002/health/live',timeout=3).status}))")['status']==200:
                    break
            except Exception:
                pass
            time.sleep(1)
        else:
            raise RuntimeError('bill_broker_not_ready')
        bill_originals_intact(meta)
        save(ROOT/'active.json',{'state':'BILL_ACTIVE_NO_CALLBACK','at':time.time(),'api_container':meta['api_container']})
        name='noteai-native-bill-'+meta['activation']
        args=['docker','run','--rm','--pull=never','--name='+name,'--cidfile='+str(ROOT/'operator.cid'),
           '--label=com.noteai.native-operator='+meta['activation'],'--network=container:'+meta['api_container'],
           '--read-only','--user=999:999','--cap-drop=ALL','--security-opt=no-new-privileges:true',
           '--memory=256m','--cpus=0.25','--pids-limit=64','--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=128m,mode=1777',
           '--env-file='+str(BOUND_ENV),'--env-file='+str(ROOT/'input.env'),
           '--mount=type=bind,src='+str(ROOT/'binding.json')+',dst='+str(ROOT/'binding.json')+',readonly',
           '--mount=type=bind,src='+str(ROOT/'work')+',dst='+str(ROOT/'work'),
           '--mount=type=bind,src=/var/lib/noteai/payment-canary-actions,dst=/var/lib/noteai/payment-canary-actions',
           '--entrypoint=/usr/local/bin/python',CANARY_IMAGE,'-EsB','/app/model/payment_canary_executor.py','reconcile','wechatpay_direct',meta['bill_date']]
        with (ROOT/'operator-result.json').open('xb') as out,(ROOT/'operator.stderr').open('xb') as err:
            completed=subprocess.run(args,stdout=out,stderr=err,timeout=1200)
            out.flush();os.fsync(out.fileno())
        save(ROOT/'operator-exited.json',{'exit_code':completed.returncode,'at':time.time()})
        # Failed/UNKNOWN operator results still seal their original capture;
        # no second execution, callback, query-payment or refund is dispatched.
        return close_bill()
    except BaseException as exc:
        save(ROOT/('run-error-'+str(time.time_ns())+'.json'),
             {'state':'UNKNOWN','error_type':type(exc).__name__,'at':time.time()})
        close_bill()
        raise


def main():
    assert socket.gethostname() == 'noteai-api-c' and os.geteuid() == 0
    os.umask(0o077)
    helpers()
    global ROOT
    if sys.argv[1:] in (['prepare-bill'], ['run-bill'], ['close-bill']):
        ROOT = Path('/var/lib/noteai/native-80b01ea/bill-20260914')
        if sys.argv[1:] == ['prepare-bill']:
            result = prepare_bill()
        else:
            lock = (ROOT / 'control.lock').open('a')
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run_bill() if sys.argv[1:] == ['run-bill'] else close_bill()
        print(json.dumps(result), flush=True)
        return
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
