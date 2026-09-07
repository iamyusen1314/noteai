import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import execute_item32_readonly_trends as executor
import internal_deployment_readiness_gate as readiness_gate


SOURCE_SHA256 = {
    "model/market_timing_worker.py": "e89be24bd3d32c8283acf4cba3f6586d2d5dff7c2c113377b743897bd0527978",
    "model/trends_contract.py": "530820f68b1feb67aba0037d76ff9548ac0e629fea1c9854cc3df2048e2f2ca8",
    "model/spider_xhs_http.py": "981a7c704ae4b9efbf0db39aa2a8a1531f40e6848da3a95357bd3cc7b18ce7b7",
    "model/hot_keywords.py": "48073372ef7c490192ff6cff54c326401b14d313d427e705a1a90f9bc17449b4",
}


def completed(args, stdout=b"", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout, b"")


class Item32ReadonlyExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def plan(self):
        source = Path(executor.__file__).resolve()
        return {
            "item": 32,
            "status": "PREPARED_NOT_EXECUTED",
            "readiness_credit": False,
            "outer_executor": "tools/execute_item32_readonly_trends.py",
            "outer_executor_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "existing_unit_sha256": executor.EXPECTED_UNIT_SHA256,
            "existing_image_config_sha256": executor.EXPECTED_CONFIG_SHA256,
            "existing_registry_manifest_sha256": executor.EXPECTED_MANIFEST_SHA256,
            "database_readonly_probe_sha256": executor.DB_PROBE_QUERYSET_SHA256,
            "source_sha256": SOURCE_SHA256,
            "bounds": {
                "cycles": 1,
                "provider_requests_per_run_max": 34,
                "provider_requests_per_utc_day_max": 34,
                "keywords_max": 90,
                "real_keywords_per_domain_min": 12,
                "domains": 6,
                "automatic_retry": 0,
            },
            "provider_calls_dispatched": 0,
            "cloud_resources_started": 0,
        }

    def test_plan_binds_outer_executor_and_accepted_image(self):
        path = self.root / "plan.json"
        path.write_text(json.dumps(self.plan()), encoding="utf-8")
        loaded, digest = executor._load_plan(
            path, Path(executor.__file__).resolve()
        )
        self.assertEqual(loaded["source_sha256"], SOURCE_SHA256)
        self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())

        changed = self.plan()
        changed["outer_executor_sha256"] = "0" * 64
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(executor.Item32Error, "plan_binding"):
            executor._load_plan(path, Path(executor.__file__).resolve())

    def _inspection(self, task_dir, *, include_database=False):
        environment = [
            "NOTEAI_XHS_COOKIES_JSON=[]",
            "NOTEAI_SQLITE_PATH=/task/noteai.db",
            "NOTEAI_HOT_KEYWORD_DB_PATH=/task/hot_keywords.db",
        ]
        if include_database:
            environment.append("DATABASE_URL=synthetic")
        return {
            "Config": {
                "Env": environment,
                "Cmd": ["python", "market_timing_worker.py", "--once"],
            },
            "Image": executor.IMAGE,
            "Mounts": [
                {"Destination": "/task", "Source": str(task_dir)}
            ],
            "HostConfig": {
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
            },
        }

    def test_collection_container_has_one_call_path_and_no_database(self):
        run_dir = self.root / "run"
        run_dir.mkdir()
        runtime_dir = self.root / "runtime"
        runtime_dir.mkdir()
        container_id = "a" * 64
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if args[:2] == ["docker", "create"]:
                return completed(args, (container_id + "\n").encode())
            if args[:2] == ["docker", "inspect"]:
                task_dir = run_dir / "task-store"
                return completed(
                    args, json.dumps([self._inspection(task_dir)]).encode()
                )
            return completed(args)

        with mock.patch.object(executor, "_run", side_effect=fake_run), mock.patch(
            "execute_item32_readonly_trends.os.chown"
        ):
            name, actual_id, cookie_env = executor._create_collection_container(
                run_dir,
                runtime_dir,
                '[{"name":"a1","value":"synthetic"}]',
            )
        self.assertTrue(name.startswith("noteai-item32-"))
        self.assertEqual(actual_id, container_id)
        create = next(call for call in calls if call[:2] == ["docker", "create"])
        command_text = "\n".join(create)
        self.assertNotIn("DATABASE_URL", command_text)
        self.assertNotIn("synthetic", command_text)
        self.assertEqual(create[-3:], ["python", "market_timing_worker.py", "--once"])
        self.assertEqual(create.count("market_timing_worker.py"), 1)
        self.assertFalse(cookie_env.exists())

    def test_collection_boundary_rejection_removes_candidate(self):
        run_dir = self.root / "run"
        run_dir.mkdir()
        runtime_dir = self.root / "runtime"
        runtime_dir.mkdir()
        container_id = "b" * 64
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            if args[:2] == ["docker", "create"]:
                return completed(args, (container_id + "\n").encode())
            if args[:2] == ["docker", "inspect"]:
                return completed(
                    args,
                    json.dumps(
                        [self._inspection(run_dir / "task-store", include_database=True)]
                    ).encode(),
                )
            return completed(args)

        with mock.patch.object(executor, "_run", side_effect=fake_run), mock.patch(
            "execute_item32_readonly_trends.os.chown"
        ):
            with self.assertRaisesRegex(executor.Item32Error, "container_boundary"):
                executor._create_collection_container(run_dir, runtime_dir, "[]")
        self.assertTrue(
            any(call[:3] == ["docker", "rm", "-f"] for call in calls)
        )
        self.assertFalse((runtime_dir / "xhs.env").exists())

    def test_database_probe_is_read_only_and_has_no_mutation_statement(self):
        source = executor.DB_PROBE_SOURCE.upper()
        queryset = executor.DB_PROBE_QUERYSET.upper()
        self.assertIn("BEGIN READ ONLY", source)
        self.assertIn("TXID_CURRENT_IF_ASSIGNED", source)
        self.assertIn("ROLLBACK", source)
        self.assertEqual(
            json.loads(executor.DB_PROBE_QUERYSET), executor.DB_PROBE_SQL
        )
        for key in executor.DB_PROBE_SQL:
            self.assertIn(f'CURSOR.EXECUTE(SQL["{key.upper()}"])', source)
        for verb in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE ", "ALTER ", "DROP "):
            self.assertNotIn(verb, queryset)

    def test_database_probe_is_task_labeled_and_secret_file_is_removed(self):
        runtime_dir = self.root / "runtime"
        runtime_dir.mkdir()
        calls = []
        result = {
            "observed_at": "2026-09-05T14:54:00+00:00",
            "server_enforced_read_only": True,
            "write_count": 0,
            "tuple_write_count": 0,
            "write_tables": [],
            "xid_assigned": False,
            "transaction_rolled_back": True,
            "session_identity_sha256": "4" * 64,
            "readback_query_sha256": executor.DB_PROBE_QUERYSET_SHA256,
            "active_or_manual_count": 0,
            "session_blocked_count": 0,
            "today_attempt_count": 0,
            "secret_values_recorded": False,
        }

        def fake_run(args, **_kwargs):
            calls.append(args)
            if args[:2] == ["docker", "run"]:
                return completed(
                    args,
                    (json.dumps(result, separators=(",", ":")) + "\n").encode(),
                )
            return completed(args)

        with mock.patch.object(executor, "_run", side_effect=fake_run):
            self.assertEqual(
                executor._run_db_probe(
                    runtime_dir,
                    "postgresql://synthetic.invalid/noteai",
                    "before",
                ),
                result,
            )
        command = next(call for call in calls if call[:2] == ["docker", "run"])
        self.assertIn("--label=com.noteai.task=item32-readonly", command)
        self.assertFalse((runtime_dir / "db-before.env").exists())
        self.assertTrue(
            any(call[:3] == ["docker", "rm", "-f"] for call in calls)
        )

    def test_unit_state_requires_exact_inactive_dead_disabled(self):
        valid = b"ActiveState=inactive\nSubState=dead\nUnitFileState=disabled\n"
        with mock.patch.object(executor, "_run", return_value=completed([], valid)):
            executor._assert_trends_unit_suspended()
        for active, substate, unit_file in [
            ("activating", "start", "disabled"),
            ("deactivating", "stop-sigterm", "disabled"),
            ("failed", "failed", "disabled"),
            ("unknown", "dead", "disabled"),
            ("inactive", "dead", "enabled"),
        ]:
            raw = (
                f"ActiveState={active}\nSubState={substate}\n"
                f"UnitFileState={unit_file}\n"
            ).encode()
            with self.subTest(active=active, substate=substate, unit_file=unit_file):
                with mock.patch.object(
                    executor, "_run", return_value=completed([], raw)
                ):
                    with self.assertRaisesRegex(
                        executor.Item32Error, "trends_unit_state"
                    ):
                        executor._assert_trends_unit_suspended()

    def test_admission_is_create_once_and_blocks_replay(self):
        work_root = self.root / "work"
        work_root.mkdir(mode=0o700)
        with mock.patch.object(executor, "WORK_ROOT", work_root):
            executor._create_admission("a" * 64)
            first = (work_root / "item32-admission.json").read_bytes()
            with self.assertRaisesRegex(
                executor.Item32Error, "item32_already_dispatched"
            ):
                executor._create_admission("b" * 64)
        self.assertEqual(
            json.loads(first)["run_identity_sha256"], "a" * 64
        )

    def test_prior_attempt_scan_blocks_every_retained_attempt_date(self):
        work_root = self.root / "work"
        database = work_root / "run-retained" / "task-store" / "hot_keywords.db"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        connection.execute(
            "CREATE TABLE xhs_trends_provider_attempts(admitted_date TEXT)"
        )
        connection.executemany(
            "INSERT INTO xhs_trends_provider_attempts VALUES(?)",
            [("2026-09-05",), ("2026-09-05",), ("2026-09-04",)],
        )
        connection.commit()
        connection.close()
        with mock.patch.object(executor, "WORK_ROOT", work_root):
            self.assertEqual(executor._prior_attempt_count(), 3)

    def test_worker_output_secret_is_never_written(self):
        run_dir = self.root / "run"
        run_dir.mkdir()
        with self.assertRaisesRegex(
            executor.Item32Error, "worker_output_secret_detected"
        ):
            executor._record_worker_receipt(
                run_dir,
                b"prefix-current-cookie-value-suffix",
                exit_code=1,
                secret_values=["current-cookie-value"],
            )
        self.assertFalse((run_dir / "worker-receipt.json").exists())

    def test_publish_export_uses_new_owned_file(self):
        candidate = self.root / "candidate.tar.gz"
        candidate.write_bytes(b"sanitized evidence")
        fake_account = types.SimpleNamespace(
            pw_uid=os.getuid(), pw_gid=os.getgid()
        )
        with mock.patch.object(executor, "EXPORT_ROOT", self.root), mock.patch(
            "execute_item32_readonly_trends.pwd.getpwnam",
            return_value=fake_account,
        ):
            published = executor._publish_export(candidate)
        self.assertNotEqual(published, candidate)
        self.assertEqual(published.read_bytes(), b"sanitized evidence")
        self.assertEqual(published.stat().st_mode & 0o777, 0o600)

    def _execute_fixture(
        self,
        *,
        fail_update=False,
        fail_run_cleanup=False,
        fail_redispatch_state=False,
    ):
        work_root = self.root / ("execute-work-" + str(len(list(self.root.iterdir()))))
        export_root = self.root / ("execute-export-" + str(len(list(self.root.iterdir()))))
        runtime_root = self.root / ("execute-runtime-" + str(len(list(self.root.iterdir()))))
        work_root.mkdir()
        export_root.mkdir(mode=0o700)
        runtime_root.mkdir(mode=0o700)
        lock_path = self.root / ("lock-" + str(len(list(self.root.iterdir()))))
        lock_descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        probes = [
            {
                "session_identity_sha256": "4" * 64,
                "observed_at": "2026-09-05T14:54:00+00:00",
                "readback_query_sha256": executor.DB_PROBE_QUERYSET_SHA256,
                "today_attempt_count": 0,
            },
            {
                "session_identity_sha256": "4" * 64,
                "observed_at": "2026-09-05T14:59:00+00:00",
                "readback_query_sha256": executor.DB_PROBE_QUERYSET_SHA256,
                "today_attempt_count": 0,
            },
        ]
        secret_values = {
            "DATABASE_URL": "postgresql://synthetic.invalid/noteai",
            "NOTEAI_XHS_COOKIES_JSON": json.dumps(
                [
                    {
                        "name": "a1",
                        "value": "synthetic-a1-value",
                        "domain": ".xiaohongshu.com",
                        "path": "/",
                    },
                    {
                        "name": "web_session",
                        "value": "synthetic-session-value",
                        "domain": ".xiaohongshu.com",
                        "path": "/",
                    },
                ]
            ),
        }

        def fake_create(run_dir, runtime_dir, _cookie_json):
            if fail_redispatch_state:
                (run_dir / "task-store").mkdir()
            else:
                self._create_task_database(run_dir)
            return "item32-container", "a" * 64, runtime_dir / "xhs.env"

        worker_output = (
            b'{"event":"trends_run_started","status":"running"}\n'
            b'{"event":"trends_run_succeeded","status":"succeeded",'
            b'"provider_calls":34,"keyword_count":72,"snapshot_size":100}\n'
        )

        run_calls = []
        self.last_execute_run_calls = run_calls

        def fake_run(args, **_kwargs):
            run_calls.append(args)
            if args[:3] == ["docker", "start", "--attach"]:
                return completed(args, worker_output)
            if args[:2] == ["docker", "inspect"]:
                return completed(
                    args,
                    json.dumps([{"State": {"ExitCode": 0}}]).encode(),
                )
            if args[:3] == ["docker", "ps", "-aq"]:
                return completed(args)
            raise AssertionError(args)

        update_statuses = []

        def fake_update(status, _provider_calls, _unknown_count):
            update_statuses.append(status)
            if fail_update and status == "SUCCEEDED":
                raise executor.Item32Error("synthetic_admission_update_failure")

        real_rmtree = shutil.rmtree

        def maybe_fail_rmtree(path, *args, **kwargs):
            candidate = Path(path)
            if fail_run_cleanup and candidate.parent == work_root:
                raise OSError("synthetic run cleanup failure")
            return real_rmtree(path, *args, **kwargs)

        fake_account = types.SimpleNamespace(
            pw_uid=os.getuid(), pw_gid=os.getgid()
        )
        patches = [
            mock.patch.object(executor, "WORK_ROOT", work_root),
            mock.patch.object(executor, "EXPORT_ROOT", export_root),
            mock.patch.object(executor, "RUNTIME_ROOT", runtime_root),
            mock.patch.object(executor.os, "geteuid", return_value=0),
            mock.patch.object(executor, "_ensure_work_root"),
            mock.patch.object(
                executor, "_acquire_executor_lock", return_value=lock_descriptor
            ),
            mock.patch.object(executor, "_preflight_host"),
            mock.patch.object(
                executor,
                "_assert_trends_unit_suspended",
                side_effect=(
                    executor.Item32Error("trends_unit_state")
                    if fail_redispatch_state
                    else None
                ),
            ),
            mock.patch.object(executor, "_read_secret_env", return_value=secret_values),
            mock.patch.object(executor, "_run_db_probe", side_effect=probes),
            mock.patch.object(executor, "_create_collection_container", side_effect=fake_create),
            mock.patch.object(executor, "_create_admission"),
            mock.patch.object(executor, "_update_admission", side_effect=fake_update),
            mock.patch.object(executor, "_remove_container"),
            mock.patch.object(executor, "_run", side_effect=fake_run),
            mock.patch.object(
                executor.pwd, "getpwnam", return_value=fake_account
            ),
            mock.patch.object(executor.shutil, "rmtree", side_effect=maybe_fail_rmtree),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        try:
            result = executor.execute(
                ROOT / "deploy/production/plans/item32-readonly-execution-20260904.json",
                ROOT / "tools/execute_item32_readonly_trends.py",
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()
        return result, export_root, work_root, update_statuses

    def test_admission_update_failure_leaves_no_verified_export(self):
        with self.assertRaisesRegex(
            executor.Item32Error, "synthetic_admission_update_failure"
        ):
            self._execute_fixture(fail_update=True)
        exports = list(self.root.glob("execute-export-*/item32-evidence-*.tar.gz"))
        self.assertEqual(exports, [])

    def test_final_cleanup_failure_revokes_verified_export(self):
        with self.assertRaisesRegex(executor.Item32Error, "cleanup_incomplete"):
            self._execute_fixture(fail_run_cleanup=True)
        exports = list(self.root.glob("execute-export-*/item32-evidence-*.tar.gz"))
        self.assertEqual(exports, [])

    def test_unit_state_change_before_dispatch_never_starts_container(self):
        with self.assertRaisesRegex(executor.Item32Error, "trends_unit_state"):
            self._execute_fixture(fail_redispatch_state=True)
        self.assertFalse(
            any(
                call[:3] == ["docker", "start", "--attach"]
                for call in self.last_execute_run_calls
            )
        )

    def _create_task_database(self, run_dir):
        task_dir = run_dir / "task-store"
        task_dir.mkdir(parents=True)
        database = task_dir / "hot_keywords.db"
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE xhs_trends_runs(
                id TEXT, status TEXT, provider_attempt_count INTEGER,
                snapshot_sha256 TEXT, snapshot_size INTEGER,
                started_at TEXT, completed_at TEXT, last_error_code TEXT
            );
            CREATE TABLE xhs_trends_provider_attempts(
                id TEXT, run_id TEXT, ordinal INTEGER, endpoint TEXT, status TEXT,
                admitted_at TEXT, completed_at TEXT
            );
            CREATE TABLE xhs_trends_snapshot_evidence(
                run_id TEXT, schema_version INTEGER, snapshot_sha256 TEXT,
                snapshot_size INTEGER, keyword_count INTEGER,
                domain_counts_json TEXT, payload_json TEXT, created_at TEXT
            );
            """
        )
        generated_at = "2026-09-05T14:57:00+00:00"
        snapshot = {
            "schema_version": 1,
            "generated_at": generated_at,
            "freshness_max_hours": 30,
            "domains": {},
        }
        for domain in sorted(executor.DOMAINS):
            rows = []
            for index in range(12):
                source = (
                    "search_recommend"
                    if index == 0
                    else "search_phrase"
                    if index == 1
                    else "homefeed_phrase"
                )
                rows.append(
                    {
                        "keyword": f"{domain}-真实-{index}",
                        "search_vol": 80 - index,
                        "trend_dir": 1,
                        "source": source,
                        "category": domain,
                        "sample_count": 1,
                        "quality_score": 80,
                        "evidence_level": "strong",
                        "quality_reason": "bounded real source",
                        "captured_at": generated_at,
                    }
                )
            snapshot["domains"][domain] = {
                "captured_at": generated_at,
                "keywords": rows,
            }
        snapshot_raw = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        run_id = "run-raw-identity"
        connection.execute(
            "INSERT INTO xhs_trends_runs VALUES(?,?,?,?,?,?,?,?)",
            (
                run_id,
                "succeeded",
                34,
                hashlib.sha256(snapshot_raw).hexdigest(),
                len(snapshot_raw),
                "2026-09-05T14:55:00+00:00",
                "2026-09-05T14:58:00+00:00",
                "",
            ),
        )
        for ordinal, endpoint in enumerate(executor.ENDPOINT_SEQUENCE, start=1):
            connection.execute(
                "INSERT INTO xhs_trends_provider_attempts VALUES(?,?,?,?,?,?,?)",
                (
                    f"attempt-raw-{ordinal}",
                    run_id,
                    ordinal,
                    endpoint,
                    "succeeded",
                    "2026-09-05T14:56:00+00:00",
                    "2026-09-05T14:57:30+00:00",
                ),
            )
        connection.execute(
            "INSERT INTO xhs_trends_snapshot_evidence VALUES(?,?,?,?,?,?,?,?)",
            (
                run_id,
                1,
                hashlib.sha256(snapshot_raw).hexdigest(),
                len(snapshot_raw),
                72,
                json.dumps(
                    {domain: 12 for domain in executor.DOMAINS},
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ),
                snapshot_raw.decode("utf-8"),
                "2026-09-05T14:57:30+00:00",
            ),
        )
        connection.commit()
        connection.close()
        return snapshot_raw, run_id

    def test_task_result_rejects_attempt_or_snapshot_for_another_run(self):
        run_dir = self.root / "run"
        self._create_task_database(run_dir)
        database = run_dir / "task-store" / "hot_keywords.db"
        connection = sqlite3.connect(database)
        connection.execute(
            "UPDATE xhs_trends_provider_attempts SET run_id='other-run' WHERE ordinal=1"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(executor.Item32Error, "terminal_run_shape"):
            executor._read_task_result(database)

        run_dir_2 = self.root / "run-2"
        self._create_task_database(run_dir_2)
        database_2 = run_dir_2 / "task-store" / "hot_keywords.db"
        connection = sqlite3.connect(database_2)
        connection.execute(
            "UPDATE xhs_trends_snapshot_evidence SET run_id='other-run'"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(executor.Item32Error, "terminal_run_shape"):
            executor._read_task_result(database_2)

    def test_task_result_rejects_snapshot_ledger_drift(self):
        run_dir = self.root / "run"
        self._create_task_database(run_dir)
        database = run_dir / "task-store" / "hot_keywords.db"
        connection = sqlite3.connect(database)
        connection.execute(
            "UPDATE xhs_trends_snapshot_evidence SET keyword_count=73"
        )
        connection.commit()
        connection.close()
        with self.assertRaisesRegex(executor.Item32Error, "terminal_run_shape"):
            executor._read_task_result(database)

    def test_artifact_bundle_is_bound_and_excludes_raw_identities(self):
        run_dir = self.root / "run"
        snapshot_raw, raw_run_id = self._create_task_database(run_dir)
        probe = {
            "session_identity_sha256": "4" * 64,
            "observed_at": "2026-09-05T14:54:00+00:00",
            "readback_query_sha256": hashlib.sha256(
                executor.DB_PROBE_QUERYSET.encode()
            ).hexdigest(),
        }
        post_probe = dict(probe)
        post_probe["observed_at"] = "2026-09-05T14:59:00+00:00"
        fake_account = types.SimpleNamespace(
            pw_uid=os.getuid(), pw_gid=os.getgid()
        )
        with mock.patch.object(executor, "EXPORT_ROOT", self.root), mock.patch(
            "execute_item32_readonly_trends.pwd.getpwnam",
            return_value=fake_account,
        ):
            bundle = executor._build_artifacts(
                run_dir=run_dir,
                plan={"source_sha256": SOURCE_SHA256},
                plan_sha256="9" * 64,
                executor_sha256="8" * 64,
                container_id="container-raw-identity",
                pre_probe=probe,
                post_probe=post_probe,
            )
        executor._ensure_export_secret_free(bundle, ["secret-not-present"])
        with tarfile.open(bundle, "r:gz") as archive:
            names = sorted(member.name for member in archive.getmembers())
            self.assertEqual(len(names), 4)
            terminal_member = next(
                member for member in archive.getmembers()
                if member.name.endswith(Path(executor.TERMINAL_REF).name)
            )
            terminal = json.load(archive.extractfile(terminal_member))
            all_bytes = b"".join(
                archive.extractfile(member).read()
                for member in archive.getmembers()
            )
        self.assertEqual(terminal["status"], "VERIFIED")
        self.assertEqual(terminal["execution"]["provider_request_count"], 34)
        self.assertEqual(
            terminal["execution"]["outer_executor_sha256"], "8" * 64
        )
        self.assertEqual(
            terminal["quality"]["snapshot_sha256"],
            hashlib.sha256(snapshot_raw).hexdigest(),
        )
        self.assertNotIn(raw_run_id.encode(), all_bytes)
        self.assertNotIn(b"attempt-raw-1", all_bytes)
        self.assertNotIn(b"container-raw-identity", all_bytes)

    def test_sealed_v1_executor_bundle_cannot_satisfy_successor_validator(self):
        run_dir = self.root / "integration-run"
        self._create_task_database(run_dir)
        probe = {
            "session_identity_sha256": "4" * 64,
            "observed_at": "2026-09-05T14:54:00+00:00",
            "readback_query_sha256": executor.DB_PROBE_QUERYSET_SHA256,
        }
        post_probe = dict(probe, observed_at="2026-09-05T14:59:00+00:00")
        plan_path = ROOT / readiness_gate.ITEM32_EXECUTION_PLAN
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        bundle = executor._build_artifacts(
            run_dir=run_dir,
            plan=plan,
            plan_sha256=hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            executor_sha256=plan["outer_executor_sha256"],
            container_id="container-raw-identity",
            pre_probe=probe,
            post_probe=post_probe,
        )

        validation_root = self.root / "validation-root"
        for ref in [
            readiness_gate.ITEM32_EXECUTION_PLAN,
            plan["outer_executor"],
            *plan["source_sha256"],
        ]:
            target = validation_root / ref
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / ref).read_bytes())
        with tarfile.open(bundle, "r:gz") as archive:
            for member in archive.getmembers():
                target = validation_root / member.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(member).read())
        errors = readiness_gate.validate_item32_trends_evidence(
            {
                "evidence": [
                    {"kind": "path", "ref": readiness_gate.ITEM32_TRENDS_EVIDENCE}
                ]
            },
            root=validation_root,
            now=datetime.now(timezone.utc),
        )
        self.assertEqual(
            errors,
            [
                "exactly one noteai.item32.xhs_trends_readonly.v2 "
                "evidence object required"
            ],
        )

    def test_secret_scan_rejects_value_in_export(self):
        run_dir = self.root / "run"
        self._create_task_database(run_dir)
        probe = {
            "session_identity_sha256": "4" * 64,
            "observed_at": "2026-09-05T14:54:00+00:00",
            "readback_query_sha256": hashlib.sha256(
                executor.DB_PROBE_QUERYSET.encode()
            ).hexdigest(),
        }
        post_probe = dict(probe, observed_at="2026-09-05T14:59:00+00:00")
        fake_account = types.SimpleNamespace(
            pw_uid=os.getuid(), pw_gid=os.getgid()
        )
        with mock.patch.object(executor, "EXPORT_ROOT", self.root), mock.patch(
            "execute_item32_readonly_trends.pwd.getpwnam",
            return_value=fake_account,
        ):
            bundle = executor._build_artifacts(
                run_dir=run_dir,
                plan={"source_sha256": SOURCE_SHA256},
                plan_sha256="9" * 64,
                executor_sha256="8" * 64,
                container_id="container-raw-identity",
                pre_probe=probe,
                post_probe=post_probe,
            )
        with self.assertRaisesRegex(executor.Item32Error, "export_secret_detected"):
            executor._ensure_export_secret_free(bundle, ["美食-真实-0"])
        self.assertFalse(bundle.exists())


if __name__ == "__main__":
    unittest.main()
