"""Synthetic Docker lifecycle and Linux RAM-only credential transport tests."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import item33_trends_container_io as io

CID = 'a' * 64
ACTIVATION = 'b' * 64
CONFIG = 'c' * 64
SOURCES = {'item33-runtime-plan.json': 'd' * 64}


class FakeDocker:
    def __init__(self):
        self.commands = []
        self.exists = False
        self.running = False
        self.output = b'{"state":"READONLY","secret_values_recorded":false}'
        self.exit_code = 0
        self.image = io.IMAGE
        self.create_unknown = False
        self.start_unknown = False
        self.removal_unknown = False

    def __call__(self, argv, **kwargs):
        self.commands.append((list(argv), kwargs))
        if argv[:2] == ['docker', 'create']:
            if self.create_unknown:
                raise subprocess.TimeoutExpired(argv, 1, stderr=b'synthetic private diagnostic')
            self.exists = True
            self.name = next(v.split('=', 1)[1] for v in argv if v.startswith('--name='))
            self.task = next(v.split('=', 2)[2] for v in argv if v.startswith('--label=com.noteai.task='))
            return subprocess.CompletedProcess(argv, 0, (CID + '\n').encode(), b'')
        if argv[:2] == ['docker', 'inspect']:
            assert self.exists
            data = dict(id=CID, name='/' + self.name, image=self.image, running=self.running,
                        exit_code=self.exit_code, oom=False, task=self.task, activation=ACTIVATION)
            return subprocess.CompletedProcess(argv, 0, json.dumps(data).encode(), b'')
        if argv[:2] == ['docker', 'start']:
            self.running = True
            if self.start_unknown:
                raise subprocess.TimeoutExpired(argv, 1, stderr=b'synthetic private diagnostic')
            if '--attach' in argv:
                self.running = False
                return subprocess.CompletedProcess(argv, self.exit_code, self.output, b'never returned')
            return subprocess.CompletedProcess(argv, 0, (CID + '\n').encode(), b'')
        if argv[:2] == ['docker', 'stop']:
            self.running = False
            return subprocess.CompletedProcess(argv, 0, (CID + '\n').encode(), b'')
        if argv[:2] == ['docker', 'rm']:
            self.exists = self.removal_unknown
            return subprocess.CompletedProcess(argv, 0, (CID + '\n').encode(), b'')
        if argv[:3] == ['docker', 'container', 'ls']:
            return subprocess.CompletedProcess(argv, 0, CID.encode() if self.exists else b'', b'')
        raise AssertionError('unexpected synthetic command')


class ContainerIOTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.work = Path(self.temporary.name)
        self.records = self.work / 'records'
        self.records.mkdir(mode=0o700)
        self.addCleanup(patch.stopall)
        patch.object(io, 'IO_ROOT', self.records).start()
        self.fake = FakeDocker()
        self.helper = io.ContainerIO(source_sha256=SOURCES, activation_identity_sha256=ACTIVATION,
            config_sha256=CONFIG, deadline=(datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat(),
            run=self.fake, host_check=lambda: None, memfd=lambda: os.open(os.devnull, os.O_RDONLY))
        patch.object(self.helper, '_preflight', lambda: None).start()

    def commands(self, operation):
        return [(argv, options) for argv, options in self.fake.commands if argv[:2] == ['docker', operation]]

    def test_probe_uses_exact_image_readonly_mounts_and_ram_fd(self):
        result = self.helper.run_readonly('preflight')
        self.assertEqual(result['state'], 'READONLY')
        argv, kwargs = self.commands('create')[0]
        self.assertIn('--pull=never', argv)
        self.assertIn('--restart=no', argv)
        self.assertIn('--read-only', argv)
        self.assertIn('--cap-drop=ALL', argv)
        self.assertIn('--network=bridge', argv)
        self.assertNotIn('--cap-add=CHOWN', argv)
        self.assertTrue(all(v.endswith(',readonly') for v in argv if v.startswith('--mount=')))
        self.assertEqual(argv[argv.index(io.IMAGE) + 1:],
            ['-E', '-B', '/workspace/tools/item33_trends_runtime_cli.py', 'preflight'])
        self.assertEqual(len(kwargs['pass_fds']), 1)
        self.assertIn('--env-file=/proc/self/fd/' + str(kwargs['pass_fds'][0]), argv)
        self.assertEqual(kwargs['env'], {'PATH': '/usr/bin:/bin'})
        self.assertFalse(any('DATABASE_URL=' in value or 'COOKIE' in value for value in argv))
        self.assertFalse(self.fake.exists)
        saved = json.loads((self.records / 'preflight-result.json').read_text())
        self.assertIs(saved['exact_container_removed'], True)
        self.assertEqual((self.records / 'preflight-result.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.commands('start')[0][1]['timeout'], 90)

    def test_only_first_cycle_waits_and_uses_bounded_long_timeout(self):
        self.helper.run_readonly('cycle', bucket_key='2026-09-19', expected_run_identity_sha256='e' * 64)
        self.helper.run_readonly('cycle', phase='promoted', bucket_key='2026-09-19')
        created = self.commands('create')
        self.assertIn('--wait-cycle', created[0][0])
        self.assertNotIn('--wait-cycle', created[1][0])
        self.assertIn('--expected-run-identity-sha256', created[0][0])
        self.assertEqual([options['timeout'] for _, options in self.commands('start')], [2000, 90])

    def test_same_phase_cannot_launch_again_even_after_success(self):
        self.helper.run_readonly('preflight')
        original = (self.records / 'preflight-started.json').read_bytes()
        with self.assertRaises(FileExistsError):
            self.helper.run_readonly('preflight')
        self.assertEqual(len(self.commands('create')), 1)
        self.assertEqual((self.records / 'preflight-started.json').read_bytes(), original)

    def test_unknown_create_preserves_start_claim_and_never_replays(self):
        self.fake.create_unknown = True
        with self.assertRaisesRegex(io.ContainerIOError, 'command_unknown') as error:
            self.helper.run_readonly('preflight')
        self.assertNotIn('private', str(error.exception))
        with self.assertRaises(FileExistsError):
            self.helper.run_readonly('preflight')
        self.assertEqual(len(self.commands('create')), 1)
        self.assertFalse(self.commands('start'))
        self.assertFalse((self.records / 'preflight-result.json').exists())

    def test_attach_timeout_stops_only_exact_container_and_remains_unknown(self):
        self.fake.start_unknown = True
        with self.assertRaisesRegex(io.ContainerIOError, 'unknown_readback_only'):
            self.helper.run_readonly('preflight')
        self.assertEqual(len(self.commands('start')), 1)
        self.assertEqual(self.commands('stop')[0][0][-1], CID)
        self.assertEqual(self.commands('rm')[0][0], ['docker', 'rm', CID])
        saved = json.loads((self.records / 'preflight-result.json').read_text())
        self.assertEqual(saved['state'], 'UNKNOWN_READBACK_ONLY')
        self.assertTrue(saved['exact_container_removed'])

    def test_bad_exit_and_secret_output_are_not_returned(self):
        self.fake.output = b'{"database_url":"synthetic-secret-value"}'
        with self.assertRaisesRegex(io.ContainerIOError, 'unknown_readback_only'):
            self.helper.run_readonly('preflight')
        self.assertFalse(self.fake.exists)
        self.assertNotIn(b'synthetic-secret-value', (self.records / 'preflight-result.json').read_bytes())

    def test_nonzero_exit_preserves_only_projected_inspection_failure(self):
        self.fake.exit_code = 1
        failure = dict(state='READONLY_INSPECTION_FAILED', error_code='item33_readonly_failed',
                       stage='catalog', error_type='InsufficientPrivilege', sqlstate='42501', secret_values_recorded=False)
        self.fake.output = json.dumps(failure).encode()
        with self.assertRaisesRegex(io.ContainerIOError, 'unknown_readback_only'):
            self.helper.run_readonly('catalog')
        raw = (self.records / 'catalog-result.json').read_bytes()
        receipt = json.loads(raw)
        self.assertEqual(receipt['inspection_failure'], failure)
        self.assertEqual(receipt['state'], 'UNKNOWN_READBACK_ONLY')
        self.assertTrue(receipt['exact_container_removed'])
        self.assertNotIn(b'never returned', raw)
        self.assertEqual(len(self.commands('start')), 1)

    def test_nonjson_error_output_is_never_persisted(self):
        self.fake.exit_code = 1
        self.fake.output = b'private arbitrary exception details'
        with self.assertRaises(io.ContainerIOError):self.helper.run_readonly('catalog')
        raw = (self.records / 'catalog-result.json').read_bytes()
        self.assertNotIn(b'private', raw)
        self.assertNotIn('inspection_failure', json.loads(raw))

    def test_container_identity_drift_is_never_stopped_or_removed(self):
        self.fake.image = 'sha256:' + 'f' * 64
        with self.assertRaisesRegex(io.ContainerIOError, 'cleanup_unknown'):
            self.helper.run_readonly('preflight')
        self.assertFalse(self.commands('start'))
        self.assertFalse(self.commands('stop'))
        self.assertFalse(self.commands('rm'))

    def test_rm_success_without_actual_absence_is_unknown(self):
        self.fake.removal_unknown = True
        with self.assertRaisesRegex(io.ContainerIOError, 'cleanup_unknown'):
            self.helper.run_readonly('preflight')
        saved = json.loads((self.records / 'preflight-result.json').read_text())
        self.assertFalse(saved['exact_container_removed'])
        self.assertEqual(saved['state'], 'UNKNOWN_READBACK_ONLY')

    def test_collector_only_capture_mount_rw_and_close_is_exact(self):
        started = self.helper.start_collector()
        self.assertTrue(started['running'])
        argv = self.commands('create')[0][0]
        self.assertIn('--cap-add=CHOWN', argv)
        mounts = [v for v in argv if v.startswith('--mount=')]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(mounts[0].endswith(',readonly'))
        self.assertNotIn('readonly', mounts[1])
        self.assertIn('/workspace/tools/item33_trends_capture_service.py', argv)
        self.assertFalse(any('--attach' in command for command, _ in self.commands('start')))
        with patch.object(self.helper, '_collector_id', return_value=CID):
            with self.assertRaisesRegex(io.ContainerIOError, 'identity'):
                self.helper.close_collector('f' * 64)
            self.assertFalse(self.commands('stop'))
            result = self.helper.close_collector(CID)
            self.assertEqual(result['state'], 'EXACT_CONTAINER_REMOVED')
            with self.assertRaises(FileExistsError):
                self.helper.close_collector(CID)
        self.assertEqual(len(self.commands('stop')), 1)
        self.assertEqual(len(self.commands('rm')), 1)
        self.assertTrue((self.records / 'collector-container.json').exists())

    def test_invalid_mode_phase_and_missing_config_reject_before_create(self):
        for mode, phase in [('provider', None), ('preflight', 'cycle')]:
            with self.assertRaises(io.ContainerIOError):self.helper.run_readonly(mode, phase=phase)
        self.helper.config_sha = None
        with self.assertRaises(io.ContainerIOError):self.helper.run_readonly('cycle')
        self.assertFalse(self.fake.commands)

    def test_expired_or_non_utc_deadline_cannot_start_collector(self):
        for value in [(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(), '2099-01-01T01:00:00+08:00']:
            self.helper.deadline = value
            with self.assertRaisesRegex(io.ContainerIOError, 'deadline'):self.helper.start_collector()
        self.assertFalse(self.fake.commands)

    def test_json_rejects_duplicates_nonfinite_and_secret_keys_or_values(self):
        for raw in [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e309}', b'{"Cookie":"x"}',
                    b'{"message":"postgresql://synthetic"}', b'{"nested":[{"authorization":"x"}]}']:
            with self.subTest(raw=raw), self.assertRaises(io.ContainerIOError):io.safe_json(raw)
        self.assertEqual(io.safe_json(b'{"secret_values_recorded":false}'), {'secret_values_recorded': False})

    @unittest.skipUnless(os.geteuid() == 0, 'isolated Linux root metadata fixture')
    def test_source_and_config_bytes_and_exact_members_checked_before_launch(self):
        base = self.work / 'fixed'; base.mkdir(mode=0o700)
        source = base / 'source'; source.mkdir(mode=0o700)
        capture = base / 'capture'; capture.mkdir(mode=0o700)
        plan = source / 'item33-runtime-plan.json'; plan.write_bytes(b'{}'); plan.chmod(0o444)
        config = capture / 'runtime-config.json'; config.write_bytes(b'{}'); config.chmod(0o444)
        helper = io.ContainerIO(source_sha256={plan.name: io.sha(b'{}')}, activation_identity_sha256=ACTIVATION,
            config_sha256=io.sha(b'{}'), run=self.fake, host_check=lambda: None)
        with patch.object(io, 'SOURCE_ROOT', source), patch.object(io, 'CAPTURE_ROOT', capture):
            helper._preflight()
            extra = source / 'unexpected'; extra.write_bytes(b'never-read')
            with self.assertRaisesRegex(io.ContainerIOError, 'source_members'):helper._preflight()
            extra.unlink(); plan.chmod(0o600)
            with self.assertRaisesRegex(io.ContainerIOError, 'file_metadata'):helper._preflight()
            plan.chmod(0o444); config.chmod(0o600); config.write_bytes(b'{"changed":true}'); config.chmod(0o444)
            with self.assertRaisesRegex(io.ContainerIOError, 'configuration_binding'):helper._preflight()
        self.assertFalse(self.fake.commands)


@unittest.skipUnless(hasattr(os, 'memfd_create'), 'actual Linux memfd required')
class MemoryCredentialTests(unittest.TestCase):
    def test_exact_dsn_only_and_actual_linux_seals(self):
        raw = b'# synthetic only\nDATABASE_URL=postgresql://synthetic\nXHS_COOKIE=not-forwarded\nWEB_SSK=not-forwarded\n'
        with patch.object(io, 'read_file', return_value=raw), patch.object(io, 'SESSION_SHA', io.sha(raw)):
            fd = io.database_memfd()
        try:
            self.assertEqual(os.read(fd, 4096), b'DATABASE_URL=postgresql://synthetic\n')
            self.assertEqual(os.fstat(fd).st_mode & 0o777, 0o600)
            expected = fcntl.F_SEAL_WRITE | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SEAL
            self.assertEqual(fcntl.fcntl(fd, fcntl.F_GET_SEALS) & expected, expected)
            with self.assertRaises(PermissionError):os.write(fd, b'cannot-change')
        finally:os.close(fd)

    def test_drift_duplicate_missing_and_empty_dsn_never_allocate_fd(self):
        for raw, pinned in [(b'DATABASE_URL=x\n', 'f' * 64), (b'DATABASE_URL=x\nDATABASE_URL=x\n', None),
                            (b'XHS_COOKIE=not-read\n', None), (b'DATABASE_URL=\n', None)]:
            with self.subTest(raw=raw), patch.object(io, 'read_file', return_value=raw), \
                    patch.object(io, 'SESSION_SHA', pinned or io.sha(raw)), patch.object(io.os, 'memfd_create') as create:
                with self.assertRaises(io.ContainerIOError):io.database_memfd()
                create.assert_not_called()


if __name__ == '__main__':unittest.main()
