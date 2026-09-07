import json
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from contextlib import ExitStack, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import execute_item32_xhs_diagnostic as diagnostic


def completed(args, stdout=b"", returncode=0):
    return subprocess.CompletedProcess(args, returncode, stdout, b"")


class Item32XHSDiagnosticExecutorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.executor = self.root / "execute.py"
        self.adapter = self.root / "spider_xhs_http.py"
        self.executor.write_bytes(Path(diagnostic.__file__).read_bytes())
        self.adapter.write_bytes((ROOT / "model/spider_xhs_http.py").read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def plan(self):
        return {
            "schema": diagnostic.PLAN_SCHEMA,
            "item": 32,
            "status": "PREPARED_NOT_EXECUTED",
            "readiness_credit": False,
            "diagnostic_only": True,
            "outer_executor": "tools/execute_item32_xhs_diagnostic.py",
            "outer_executor_sha256": diagnostic._sha256_bytes(
                self.executor.read_bytes()
            ),
            "adapter_source": "model/spider_xhs_http.py",
            "adapter_source_sha256": diagnostic._sha256_bytes(
                self.adapter.read_bytes()
            ),
            "existing_image_config_sha256": diagnostic.IMAGE_CONFIG_SHA256,
            "existing_registry_manifest_sha256": diagnostic.IMAGE_MANIFEST_SHA256,
            "existing_registry_manifest_provenance": (
                "HISTORICAL_SEALED_PLAN_ONLY"
            ),
            "sealed_executor_sha256": diagnostic.SEALED_EXECUTOR_SHA256,
            "sealed_plan_sha256": diagnostic.SEALED_PLAN_SHA256,
            "sealed_admission_sha256": "a" * 64,
            "sealed_store_sha256": "b" * 64,
            "sealed_admission_required_status": "HOLD",
            "request": {
                "method": "POST",
                "endpoint": "/api/sns/web/v1/homefeed",
                "category": "homefeed_recommend",
                "max_pages": 1,
                "max_items": 20,
                "user_agent": diagnostic.SIGNER_USER_AGENT,
                "timeout_seconds": 20,
                "follow_redirects": False,
            },
            "bounds": {
                "provider_requests": 1,
                "prior_sealed_provider_requests": 1,
                "cumulative_provider_requests": 2,
                "automatic_retry": 0,
                "production_database_queries": 0,
                "production_database_writes": 0,
                "cloud_resource_mutations": 0,
                "readiness_credit": False,
            },
        }

    def enter_host_patches(self, stack):
        plan = self.plan()
        work = self.root / "host-work"
        stack.enter_context(mock.patch.object(diagnostic.os, "geteuid", return_value=0))
        stack.enter_context(mock.patch.object(diagnostic.os, "close"))
        stack.enter_context(mock.patch.object(diagnostic, "WORK_ROOT", work))
        stack.enter_context(mock.patch.object(diagnostic, "ADMISSION", work / "admission.json"))
        stack.enter_context(mock.patch.object(diagnostic, "RESULT", work / "result.json"))
        stack.enter_context(
            mock.patch.object(
                diagnostic, "RESULT_CANDIDATE", work / ".result.candidate.json"
            )
        )
        stack.enter_context(mock.patch.object(diagnostic, "_assert_staged_source"))
        stack.enter_context(
            mock.patch.object(
                diagnostic, "_load_plan", return_value=(plan, "d" * 64)
            )
        )
        stack.enter_context(mock.patch.object(diagnostic, "_ensure_work_root"))
        stack.enter_context(
            mock.patch.object(diagnostic, "_acquire_lock", return_value=11)
        )
        stack.enter_context(
            mock.patch.object(
                diagnostic, "_acquire_sealed_executor_lock", return_value=12
            )
        )
        stack.enter_context(
            mock.patch.object(
                diagnostic,
                "_verify_sealed_hold",
                return_value={
                    "admission_sha256": "a" * 64,
                    "store_sha256": "b" * 64,
                },
            )
        )
        stack.enter_context(mock.patch.object(diagnostic, "_assert_host_preflight"))
        stack.enter_context(
            mock.patch.object(
                diagnostic,
                "_read_secret_values",
                return_value={
                    "DATABASE_URL": "postgresql://synthetic-not-used",
                    "NOTEAI_XHS_COOKIES_JSON": "synthetic-cookie-json",
                },
            )
        )
        stack.enter_context(mock.patch.object(diagnostic, "_create_admission"))
        return plan

    def test_plan_binds_new_executor_adapter_and_sealed_hold(self):
        path = self.root / "plan.json"
        path.write_text(json.dumps(self.plan()), encoding="utf-8")
        loaded, digest = diagnostic._load_plan(
            path, self.executor, self.adapter
        )
        self.assertFalse(loaded["readiness_credit"])
        self.assertEqual(digest, diagnostic._sha256_bytes(path.read_bytes()))

        changed = self.plan()
        changed["request"]["max_pages"] = 2
        path.write_text(json.dumps(changed), encoding="utf-8")
        with self.assertRaisesRegex(
            diagnostic.Item32DiagnosticError, "plan_binding"
        ):
            diagnostic._load_plan(path, self.executor, self.adapter)

        self.assertEqual(
            diagnostic.SEALED_PLAN_SHA256,
            diagnostic._sha256_bytes(
                (
                    ROOT
                    / "deploy/production/plans/item32-readonly-execution-20260904.json"
                ).read_bytes()
            ),
        )

    def test_committed_diagnostic_plan_remains_sealed_to_historical_adapter(self):
        plan = (
            ROOT
            / "deploy/production/plans/item32-xhs-diagnostic-20260906.json"
        )
        payload = json.loads(plan.read_text(encoding="utf-8"))
        self.assertEqual(
            payload["adapter_source_sha256"],
            "981a7c704ae4b9efbf0db39aa2a8a1531f40e6848da3a95357bd3cc7b18ce7b7",
        )
        self.assertNotEqual(
            payload["adapter_source_sha256"],
            diagnostic._sha256_bytes(
                (ROOT / "model/spider_xhs_http.py").read_bytes()
            ),
        )
        with self.assertRaisesRegex(
            diagnostic.Item32DiagnosticError, "plan_binding"
        ):
            diagnostic._load_plan(
                plan,
                Path(diagnostic.__file__).resolve(),
                ROOT / "model/spider_xhs_http.py",
            )

    def test_response_classifier_separates_owner_gates_and_engineering(self):
        cases = (
            (401, {}, "LOGIN_REQUIRED", "XHS_LOGIN"),
            (403, {}, "ACCESS_REVIEW_REQUIRED", "XHS_ACCESS_REVIEW"),
            (
                200,
                {"success": False, "msg": "captcha"},
                "INTERACTIVE_VERIFICATION_REQUIRED",
                "XHS_INTERACTIVE_VERIFICATION",
            ),
            (
                200,
                {"success": False, "msg": "异常登录"},
                "RISK_CONTROL_REVIEW_REQUIRED",
                "XHS_RISK_CONTROL_REVIEW",
            ),
            (
                200,
                {"success": False, "msg": "账号限制"},
                "ACCOUNT_ACCESS_REVIEW_REQUIRED",
                "XHS_ACCOUNT_ACCESS_REVIEW",
            ),
            (429, {}, "COOLDOWN_HOLD", "NONE"),
            (422, {}, "REQUEST_CONTRACT_REJECTION", "NONE"),
            (503, {}, "PROVIDER_SERVER_REJECTION", "NONE"),
            (
                200,
                {"success": False, "code": 12345},
                "ENGINEERING_KNOWN_REJECTION",
                "NONE",
            ),
            (
                200,
                {"success": True, "code": 0, "data": {"items": []}},
                "SUCCESS_SHAPE",
                "NONE",
            ),
        )
        for status, payload, expected, gate in cases:
            with self.subTest(expected=expected):
                result = diagnostic.classify_response(status, payload)
                self.assertEqual(result["classification"], expected)
                self.assertEqual(result["owner_gate_kind"], gate)
                self.assertNotIn("msg", result)
                self.assertNotIn(12345, result.values())
                self.assertEqual(result["automatic_retry_count"], 0)

    def test_no_response_after_request_is_unknown_and_never_retriable(self):
        result = diagnostic.classify_no_response(
            request_started=True,
            adapter_code="network_error",
        )
        self.assertEqual(result["classification"], "UNKNOWN_HOLD")
        self.assertEqual(result["provider_call_count"], 1)
        self.assertEqual(result["outcome_unknown_count"], 1)
        self.assertEqual(result["automatic_retry_count"], 0)
        self.assertEqual(result["isolated_sqlite_state"], "UNKNOWN")
        self.assertFalse(result["owner_gate_required"])
        self.assertEqual(
            diagnostic._validate_runner_result(result)["classification"],
            "UNKNOWN_HOLD",
        )

        local = diagnostic.classify_no_response(
            request_started=False,
            adapter_code="login_required",
        )
        self.assertEqual(local["classification"], "LOGIN_REQUIRED")
        self.assertEqual(local["provider_call_count"], 0)

    def test_precise_owner_markers_survive_success_shaped_payloads(self):
        cases = (
            (
                {"success": False, "msg": "拒绝访问"},
                "ACCOUNT_ACCESS_REVIEW_REQUIRED",
                "XHS_ACCOUNT_ACCESS_REVIEW",
            ),
            (
                {"msg": "请先登录", "data": {"items": []}},
                "LOGIN_REQUIRED",
                "XHS_LOGIN",
            ),
            (
                {"success": "yes", "data": {"items": []}},
                "ENGINEERING_RESPONSE_SCHEMA",
                "NONE",
            ),
            (
                {"success": False, "msg": "安全风险"},
                "RISK_CONTROL_REVIEW_REQUIRED",
                "XHS_RISK_CONTROL_REVIEW",
            ),
        )
        for payload, classification, gate in cases:
            with self.subTest(classification=classification):
                result = diagnostic.classify_response(200, payload)
                self.assertEqual(result["classification"], classification)
                self.assertEqual(result["owner_gate_kind"], gate)
                diagnostic._validate_runner_result(result)

    def test_over_bound_item_count_remains_a_known_response(self):
        for count in (21, 100):
            with self.subTest(count=count):
                result = diagnostic.classify_response(
                    200,
                    {
                        "success": True,
                        "code": 0,
                        "data": {"items": [{}] * count},
                    },
                )
                self.assertEqual(
                    result["classification"], "ENGINEERING_RESPONSE_SCHEMA"
                )
                self.assertEqual(result["item_count"], 21)
                self.assertEqual(result["outcome_unknown_count"], 0)
                diagnostic._validate_runner_result(result)

    def test_fresh_admission_is_root_only_exclusive_and_no_replay(self):
        work = self.root / "work"
        work.mkdir(mode=0o700)
        admission = work / "admission.json"
        with mock.patch.object(diagnostic, "WORK_ROOT", work), mock.patch.object(
            diagnostic, "ADMISSION", admission
        ):
            diagnostic._create_admission("a" * 64, "b" * 64, "c" * 64)
            payload = json.loads(admission.read_text(encoding="utf-8"))
            self.assertTrue(payload["no_replay"])
            self.assertEqual(payload["automatic_retry_count"], 0)
            self.assertEqual(stat.S_IMODE(admission.stat().st_mode), 0o600)
            with self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError,
                "diagnostic_already_dispatched",
            ):
                diagnostic._create_admission("a" * 64, "b" * 64, "c" * 64)

    def test_container_boundary_has_no_database_and_mounts_patch_read_only(self):
        runtime = self.root / "runtime"
        runtime.mkdir()
        adapter = self.adapter.resolve()
        executor = self.executor.resolve()
        calls = []
        container_id = "c" * 64

        def fake_run(args, **_kwargs):
            calls.append(args)
            if args[:2] == ["docker", "create"]:
                env_index = args.index("--env-file") + 1
                env_path = Path(args[env_index])
                self.assertIn("NOTEAI_XHS_COOKIES_JSON=", env_path.read_text())
                return completed(args, (container_id + "\n").encode())
            if args[:2] == ["docker", "inspect"]:
                return completed(
                    args,
                    json.dumps(
                        [
                            {
                                "Image": diagnostic.IMAGE,
                                "Config": {
                                    "User": "999:999",
                                    "Env": [
                                        "NOTEAI_XHS_COOKIES_JSON=not-printed",
                                        "NOTEAI_RUNTIME_ROLE=xhs-http",
                                        "NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http",
                                        "NOTEAI_XHS_COLLECTION_SUSPENDED=0",
                                        "NOTEAI_CLOUD_RUNTIME=1",
                                        f"NOTEAI_SQLITE_PATH={diagnostic.ISOLATED_SQLITE_PATH}",
                                    ],
                                    "Labels": {
                                        "com.noteai.task": "item32-xhs-diagnostic"
                                    },
                                    "Entrypoint": ["python"],
                                    "Cmd": [
                                        "-EsB",
                                        "/diagnostic/execute.py",
                                        "--container-runner",
                                    ],
                                },
                                "Mounts": [
                                    {
                                        "Type": "bind",
                                        "Source": str(adapter),
                                        "Destination": "/app/model/spider_xhs_http.py",
                                        "RW": False,
                                    },
                                    {
                                        "Type": "bind",
                                        "Source": str(executor),
                                        "Destination": "/diagnostic/execute.py",
                                        "RW": False,
                                    },
                                ],
                                "HostConfig": {
                                    "ReadonlyRootfs": True,
                                    "Privileged": False,
                                    "CapDrop": ["ALL"],
                                    "CapAdd": None,
                                    "NetworkMode": "bridge",
                                    "IpcMode": "private",
                                    "Memory": 268435456,
                                    "NanoCpus": 250000000,
                                    "PidsLimit": 48,
                                    "SecurityOpt": ["no-new-privileges:true"],
                                    "RestartPolicy": {
                                        "Name": "no",
                                        "MaximumRetryCount": 0,
                                    },
                                    "Tmpfs": {
                                        "/tmp": "rw,noexec,nosuid,nodev,size=134217728,mode=1777,uid=999,gid=999"
                                    },
                                },
                                "NetworkSettings": {
                                    "Networks": {"bridge": {}}
                                },
                            }
                        ]
                    ).encode(),
                )
            return completed(args)

        with mock.patch.object(
            diagnostic.tempfile,
            "mkdtemp",
            return_value=str(runtime),
        ), mock.patch.object(diagnostic, "_run", side_effect=fake_run):
            name = "noteai-item32-diagnostic-test"
            actual_id = diagnostic._create_container(
                name=name,
                executor_path=executor,
                adapter_path=adapter,
                cookie_json='[{"name":"a1"}]',
            )
        self.assertTrue(name.startswith("noteai-item32-diagnostic-"))
        self.assertEqual(actual_id, container_id)
        create = next(call for call in calls if call[:2] == ["docker", "create"])
        self.assertFalse(any("DATABASE_URL" in token for token in create))
        self.assertIn(
            f"type=bind,src={adapter},dst=/app/model/spider_xhs_http.py,readonly",
            create,
        )
        self.assertFalse(runtime.exists())

    def test_container_boundary_rejects_identity_resource_and_mount_drift(self):
        inspection = {
            "Image": diagnostic.IMAGE,
            "Config": {
                "User": "999:999",
                "Env": [
                    "NOTEAI_XHS_COOKIES_JSON=secret-not-printed",
                    "NOTEAI_RUNTIME_ROLE=xhs-http",
                    "NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http",
                    "NOTEAI_XHS_COLLECTION_SUSPENDED=0",
                    "NOTEAI_CLOUD_RUNTIME=1",
                    f"NOTEAI_SQLITE_PATH={diagnostic.ISOLATED_SQLITE_PATH}",
                ],
                "Labels": {"com.noteai.task": "item32-xhs-diagnostic"},
                "Entrypoint": ["python"],
                "Cmd": ["-EsB", "/diagnostic/execute.py", "--container-runner"],
            },
            "Mounts": [
                {
                    "Type": "bind",
                    "Source": str(self.adapter.resolve()),
                    "Destination": "/app/model/spider_xhs_http.py",
                    "RW": False,
                },
                {
                    "Type": "bind",
                    "Source": str(self.executor.resolve()),
                    "Destination": "/diagnostic/execute.py",
                    "RW": False,
                },
            ],
            "HostConfig": {
                "ReadonlyRootfs": True,
                "Privileged": False,
                "CapDrop": ["ALL"],
                "CapAdd": None,
                "NetworkMode": "bridge",
                "IpcMode": "private",
                "Memory": 268435456,
                "NanoCpus": 250000000,
                "PidsLimit": 48,
                "SecurityOpt": ["no-new-privileges:true"],
                "RestartPolicy": {"Name": "no", "MaximumRetryCount": 0},
                "Tmpfs": {
                    "/tmp": "rw,noexec,nosuid,nodev,size=134217728,mode=1777,uid=999,gid=999"
                },
            },
            "NetworkSettings": {"Networks": {"bridge": {}}},
        }
        diagnostic._validate_container_inspection(
            inspection,
            executor_path=self.executor,
            adapter_path=self.adapter,
        )
        mutations = (
            ("Config", "User", "0:0"),
            ("HostConfig", "NetworkMode", "host"),
            ("HostConfig", "Memory", 0),
            ("HostConfig", "PidsLimit", 0),
            ("HostConfig", "IpcMode", "host"),
            (
                "HostConfig",
                "RestartPolicy",
                {"Name": "always", "MaximumRetryCount": 0},
            ),
        )
        for section, key, replacement in mutations:
            changed = json.loads(json.dumps(inspection))
            changed[section][key] = replacement
            with self.subTest(section=section, key=key), self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError, "container_boundary"
            ):
                diagnostic._validate_container_inspection(
                    changed,
                    executor_path=self.executor,
                    adapter_path=self.adapter,
                )

        changed = json.loads(json.dumps(inspection))
        changed["Config"]["Env"].append("DATABASE_URL=forbidden")
        with self.assertRaisesRegex(
            diagnostic.Item32DiagnosticError, "container_boundary"
        ):
            diagnostic._validate_container_inspection(
                changed,
                executor_path=self.executor,
                adapter_path=self.adapter,
            )

    def test_runner_result_rejects_extra_raw_provider_fields(self):
        result = diagnostic.classify_response(
            200,
            {"success": True, "data": {"items": []}},
        )
        self.assertEqual(
            diagnostic._validate_runner_result(result)["classification"],
            "SUCCESS_SHAPE",
        )
        result["raw_message"] = "sensitive"
        with self.assertRaisesRegex(
            diagnostic.Item32DiagnosticError, "runner_result"
        ):
            diagnostic._validate_runner_result(result)

    def test_container_runner_invokes_exact_homefeed_shape_once(self):
        calls = []
        holder = {}

        class FakeClient:
            def __init__(self, **kwargs):
                holder["hooks"] = kwargs["event_hooks"]

            def close(self):
                return None

        class FakeResponse:
            status_code = 200
            headers = {}

            def read(self):
                return b""

            def json(self):
                return {
                    "success": True,
                    "code": 0,
                    "msg": "must-not-be-emitted",
                    "data": {"items": [{"id": "must-not-be-emitted"}]},
                }

        class FakeAdapter:
            def __init__(self, *, client):
                self.client = client

            def session_health(self):
                return {"status": "ready"}

            def homefeed(self, **kwargs):
                calls.append(kwargs)
                request = types.SimpleNamespace(headers={"user-agent": "old"})
                holder["hooks"]["request"][0](request)
                holder["sent_user_agent"] = request.headers["user-agent"]
                holder["hooks"]["response"][0](FakeResponse())
                return {"unused": True}

        fake_xhs = types.SimpleNamespace(
            SIGNER_USER_AGENT=diagnostic.SIGNER_USER_AGENT,
            VENDOR_DIR=ROOT / "model/vendor/spider_xhs",
            SpiderXHSHTTPAdapter=FakeAdapter,
        )
        fake_httpx = types.SimpleNamespace(Client=FakeClient)
        isolated_database = self.root / "isolated.db"
        fake_db = types.SimpleNamespace(
            init_db=lambda: isolated_database.write_bytes(b"sqlite")
        )
        output = StringIO()
        with mock.patch.object(
            diagnostic, "ISOLATED_SQLITE_PATH", isolated_database
        ), mock.patch.dict(
            os.environ,
            {"NOTEAI_SQLITE_PATH": str(isolated_database)},
            clear=True,
        ), mock.patch.dict(
            sys.modules,
            {
                "spider_xhs_http": fake_xhs,
                "httpx": fake_httpx,
                "db": fake_db,
            },
        ), redirect_stdout(output):
            self.assertEqual(diagnostic._container_runner(), 0)
        self.assertEqual(
            calls,
            [
                {
                    "category": "homefeed_recommend",
                    "max_pages": 1,
                    "max_items": 20,
                }
            ],
        )
        rendered = output.getvalue()
        self.assertIn('"classification":"SUCCESS_SHAPE"', rendered)
        self.assertNotIn("must-not-be-emitted", rendered)
        self.assertEqual(holder["sent_user_agent"], diagnostic.SIGNER_USER_AGENT)

    def test_success_text_never_creates_login_gate_and_redirect_is_sanitized(self):
        success = diagnostic.classify_response(
            200,
            {
                "success": True,
                "code": 0,
                "msg": "login success 登录成功",
                "data": {"items": []},
            },
        )
        self.assertEqual(success["classification"], "SUCCESS_SHAPE")
        self.assertEqual(success["marker_class"], "NONE")
        self.assertFalse(success["owner_gate_required"])

        marker = diagnostic._redirect_marker(
            "https://www.xiaohongshu.com/passport/login?opaque=discarded"
        )
        redirected = diagnostic.classify_response(
            302, None, redirect_marker=marker
        )
        self.assertEqual(redirected["classification"], "LOGIN_REQUIRED")
        self.assertEqual(redirected["marker_class"], "LOGIN")
        self.assertNotIn("opaque", json.dumps(redirected))

    def test_runner_result_rejects_type_enum_and_relationship_tampering(self):
        base = diagnostic.classify_response(
            200,
            {"success": True, "code": 0, "data": {"items": []}},
        )
        mutations = [
            {"classification": "ARBITRARY"},
            {"owner_gate_required": True},
            {"owner_gate_kind": "XHS_LOGIN"},
            {"response_received": False},
            {"http_status": True},
            {"http_status": 99},
            {"payload_shape": "RAW"},
            {"success_state": "YES"},
            {"code_state": "UNKNOWN"},
            {"marker_class": "RAW_PROVIDER_MESSAGE"},
            {"data_shape": "LIST"},
            {"items_shape": "OTHER", "item_count": 1},
            {"item_count": True},
            {"item_count": 21},
            {"provider_call_count": 0},
            {"outcome_unknown_count": 1},
            {"automatic_retry_count": 1},
            {"isolated_sqlite_state": "NOT_INITIALIZED"},
            {
                "classification": "LOGIN_REQUIRED",
                "owner_gate_required": True,
                "owner_gate_kind": "XHS_LOGIN",
            },
        ]
        for mutation in mutations:
            value = dict(base)
            value.update(mutation)
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError, "runner_result"
            ):
                diagnostic._validate_runner_result(value)

        unknown = diagnostic.classify_no_response(
            request_started=True,
            adapter_code="network_error",
            isolated_sqlite_state="UNKNOWN",
        )
        self.assertEqual(
            diagnostic._validate_runner_result(unknown)["classification"],
            "UNKNOWN_HOLD",
        )
        unknown["classification"] = "REMOTE_HTTP_REJECTION"
        with self.assertRaisesRegex(
            diagnostic.Item32DiagnosticError, "runner_result"
        ):
            diagnostic._validate_runner_result(unknown)

    def test_runner_output_is_bounded_and_rejects_every_secret_value(self):
        values = {
            "DATABASE_URL": "postgresql://secret-connection-value",
            "NOTEAI_XHS_COOKIES_JSON": json.dumps(
                [
                    {
                        "name": "a1",
                        "value": "secret-a1-value",
                        "domain": ".xiaohongshu.com",
                        "path": "/",
                    },
                    {
                        "name": "web_session",
                        "value": "secret-web-session-value",
                        "domain": ".xiaohongshu.com",
                        "path": "/",
                    },
                ]
            ),
        }
        diagnostic._assert_runner_output_secret_free(b'{"safe":true}', values)
        for secret in (
            values["DATABASE_URL"],
            values["NOTEAI_XHS_COOKIES_JSON"],
            "secret-a1-value",
            "secret-web-session-value",
        ):
            with self.subTest(secret_len=len(secret)), self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError, "runner_output_secret"
            ):
                diagnostic._assert_runner_output_secret_free(
                    ("prefix" + secret + "suffix").encode(), values
                )

    def test_sealed_hold_binds_exact_admission_store_and_idle_safety(self):
        sealed_root = self.root / "sealed"
        database = sealed_root / "run-one" / "task-store" / "hot_keywords.db"
        database.parent.mkdir(parents=True)
        connection = sqlite3.connect(database)
        connection.executescript(
            """
            CREATE TABLE xhs_trends_runs(
              status TEXT, provider_attempt_count INTEGER,
              last_error_code TEXT, snapshot_sha256 TEXT, snapshot_size INTEGER
            );
            CREATE TABLE xhs_trends_provider_attempts(
              ordinal INTEGER, endpoint TEXT, status TEXT, error_code TEXT
            );
            CREATE TABLE xhs_trends_snapshot_evidence(id TEXT);
            CREATE TABLE xhs_trends_service_state(
              status TEXT, active_run_id TEXT, session_blocked INTEGER
            );
            INSERT INTO xhs_trends_runs VALUES(
              'failed',1,'trends_provider_attempt_evidence_incomplete','',0
            );
            INSERT INTO xhs_trends_provider_attempts VALUES(
              1,'homefeed','failed','remote_business_error'
            );
            INSERT INTO xhs_trends_service_state VALUES('idle',NULL,0);
            """
        )
        connection.commit()
        connection.close()
        admission = {
            "schema": "noteai.item32.execution_admission.v1",
            "status": "HOLD",
            "created_at": "2026-09-06T01:06:19+00:00",
            "run_identity_sha256": "c" * 64,
            "automatic_retry_count": 0,
            "updated_at": "2026-09-06T01:06:24+00:00",
            "provider_calls": 1,
            "outcome_unknown_count": 0,
        }
        raw = diagnostic._json_bytes(admission)
        plan = {
            "sealed_admission_sha256": diagnostic._sha256_bytes(raw),
            "sealed_store_sha256": diagnostic._sha256_regular_file(
                database, max_size=64 * 1024 * 1024
            ),
        }
        with mock.patch.object(
            diagnostic, "SEALED_WORK_ROOT", sealed_root
        ), mock.patch.object(
            diagnostic, "SEALED_ADMISSION", sealed_root / "admission.json"
        ), mock.patch.object(
            diagnostic, "_read_regular_root_file", return_value=raw
        ):
            result = diagnostic._verify_sealed_hold(plan)
            self.assertEqual(result["store_sha256"], plan["sealed_store_sha256"])
            connection = sqlite3.connect(database)
            connection.execute(
                "UPDATE xhs_trends_service_state SET session_blocked=1"
            )
            connection.commit()
            connection.close()
            plan["sealed_store_sha256"] = diagnostic._sha256_regular_file(
                database, max_size=64 * 1024 * 1024
            )
            with self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError, "sealed_store_binding"
            ):
                diagnostic._verify_sealed_hold(plan)

    def test_result_candidate_is_not_published_when_admission_finish_fails(self):
        work = self.root / "commit"
        work.mkdir()
        candidate = work / ".result.candidate.json"
        result_path = work / "result.json"
        result = diagnostic.classify_response(
            200,
            {"success": True, "code": 0, "data": {"items": []}},
        )
        with mock.patch.object(
            diagnostic, "WORK_ROOT", work
        ), mock.patch.object(
            diagnostic, "RESULT_CANDIDATE", candidate
        ), mock.patch.object(
            diagnostic, "RESULT", result_path
        ), mock.patch.object(
            diagnostic,
            "_finish_admission",
            side_effect=diagnostic.Item32DiagnosticError("synthetic_finish"),
        ):
            with self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError, "synthetic_finish"
            ):
                diagnostic._commit_result(
                    {"safe": True},
                    result,
                    terminal_status="COMPLETE_NO_REPLAY",
                    cleanup_state="ABSENT",
                )
        self.assertFalse(candidate.exists())
        self.assertFalse(result_path.exists())

    def test_cleanup_readback_returns_present_or_unknown_without_replay(self):
        present = [
            completed(["docker", "rm"]),
            completed(["docker", "ps"], b"c" * 64 + b"\n"),
        ]
        with mock.patch.object(diagnostic, "_run", side_effect=present) as run:
            self.assertEqual(diagnostic._remove_container("task-name"), "PRESENT")
        self.assertEqual(run.call_count, 2)

        unknown = [
            completed(["docker", "rm"]),
            diagnostic.Item32DiagnosticError("docker_read"),
        ]
        with mock.patch.object(diagnostic, "_run", side_effect=unknown) as run:
            self.assertEqual(diagnostic._remove_container("task-name"), "UNKNOWN")
        self.assertEqual(run.call_count, 2)

    def test_create_boundary_failure_persists_cleanup_hold(self):
        finish = mock.Mock()
        cleanup = mock.Mock(return_value="PRESENT")
        with ExitStack() as stack:
            self.enter_host_patches(stack)
            stack.enter_context(
                mock.patch.object(
                    diagnostic,
                    "_create_container",
                    side_effect=diagnostic.Item32DiagnosticError(
                        "container_boundary"
                    ),
                )
            )
            stack.enter_context(mock.patch.object(diagnostic, "_remove_container", cleanup))
            stack.enter_context(mock.patch.object(diagnostic, "_finish_admission", finish))
            with self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError, "container_boundary"
            ):
                diagnostic._host_main(self.root / "plan.json", self.adapter)
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual(finish.call_args.kwargs["terminal_status"], "HOLD_CLEANUP")
        self.assertEqual(finish.call_args.kwargs["cleanup_state"], "PRESENT")
        self.assertIsNone(finish.call_args.kwargs["result_sha256"])

    def test_pre_start_failure_persists_unknown_cleanup(self):
        finish = mock.Mock()
        cleanup = mock.Mock(return_value="UNKNOWN")
        with ExitStack() as stack:
            self.enter_host_patches(stack)
            stack.enter_context(
                mock.patch.object(
                    diagnostic, "_create_container", return_value="c" * 64
                )
            )
            stack.enter_context(
                mock.patch.object(
                    diagnostic,
                    "_assert_pre_start",
                    side_effect=diagnostic.Item32DiagnosticError(
                        "diagnostic_container_present"
                    ),
                )
            )
            stack.enter_context(mock.patch.object(diagnostic, "_remove_container", cleanup))
            stack.enter_context(mock.patch.object(diagnostic, "_finish_admission", finish))
            with self.assertRaisesRegex(
                diagnostic.Item32DiagnosticError,
                "diagnostic_container_present",
            ):
                diagnostic._host_main(self.root / "plan.json", self.adapter)
        self.assertEqual(cleanup.call_count, 1)
        self.assertEqual(finish.call_args.kwargs["terminal_status"], "HOLD_CLEANUP")
        self.assertEqual(finish.call_args.kwargs["cleanup_state"], "UNKNOWN")

    def test_timeout_and_cleanup_failure_preserve_both_unknowns(self):
        commit = mock.Mock(return_value="e" * 64)
        cleanup = mock.Mock(return_value="PRESENT")
        output = StringIO()
        with ExitStack() as stack:
            self.enter_host_patches(stack)
            stack.enter_context(
                mock.patch.object(
                    diagnostic, "_create_container", return_value="c" * 64
                )
            )
            stack.enter_context(mock.patch.object(diagnostic, "_assert_pre_start"))
            stack.enter_context(
                mock.patch.object(
                    diagnostic,
                    "_run",
                    side_effect=subprocess.TimeoutExpired("docker start", 30),
                )
            )
            stack.enter_context(mock.patch.object(diagnostic, "_remove_container", cleanup))
            stack.enter_context(mock.patch.object(diagnostic, "_commit_result", commit))
            with redirect_stdout(output):
                result = diagnostic._host_main(
                    self.root / "plan.json", self.adapter
                )
        self.assertEqual(result, 1)
        self.assertEqual(commit.call_args.kwargs["terminal_status"], "HOLD_UNKNOWN")
        self.assertEqual(commit.call_args.kwargs["cleanup_state"], "PRESENT")
        committed_output = commit.call_args.args[0]
        self.assertFalse(committed_output["container_cleanup_complete"])
        self.assertEqual(committed_output["container_residue_state"], "PRESENT")
        self.assertEqual(
            committed_output["result"]["isolated_sqlite_state"], "UNKNOWN"
        )
        self.assertEqual(
            diagnostic._validate_runner_result(committed_output["result"])[
                "classification"
            ],
            "UNKNOWN_HOLD",
        )

    def test_real_adapter_reads_isolated_safety_db_and_makes_one_mock_request(self):
        database = self.root / "real-adapter.db"
        code = r'''
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, os.environ["NOTEAI_TEST_MODEL_DIR"])
import db
db.init_db()
import spider_xhs_http

calls = []
def handler(request):
    calls.append((request.method, request.url.path, request.headers["user-agent"]))
    return httpx.Response(
        200,
        json={"success": True, "code": 0, "data": {"items": []}},
        request=request,
    )

def set_effective_user_agent(request):
    request.headers["user-agent"] = os.environ["NOTEAI_TEST_SIGNER_UA"]

class Signer:
    def sign(self, **_kwargs):
        return {"xs": "safe", "xt": "1", "xs_common": "safe"}

credentials = spider_xhs_http.SessionCredentials(
    cookie_header="a1=synthetic; web_session=synthetic",
    a1="synthetic-a1",
    cookie_count=2,
    auth_cookie_present=True,
    auth_cookie_expired=False,
)
with httpx.Client(
    transport=httpx.MockTransport(handler),
    event_hooks={"request": [set_effective_user_agent]},
    trust_env=False,
) as client:
    adapter = spider_xhs_http.SpiderXHSHTTPAdapter(
        credentials=credentials,
        signer=Signer(),
        client=client,
    )
    result = adapter.homefeed(max_pages=1, max_items=20)
assert result["items"] == []
assert calls == [("POST", "/api/sns/web/v1/homefeed", os.environ["NOTEAI_TEST_SIGNER_UA"])]
assert Path(os.environ["NOTEAI_SQLITE_PATH"]).is_file()
print(json.dumps({"calls": len(calls), "isolated": True}, sort_keys=True))
'''
        environment = dict(os.environ)
        environment.pop("DATABASE_URL", None)
        environment.pop("NOTEAI_XHS_SERVICE", None)
        environment.update(
            {
                "NOTEAI_SQLITE_PATH": str(database),
                "NOTEAI_RUNTIME_ROLE": "xhs-http",
                "NOTEAI_XHS_ACQUISITION_ADAPTER": "spider_xhs_http",
                "NOTEAI_XHS_COLLECTION_SUSPENDED": "0",
                "NOTEAI_TEST_MODEL_DIR": str(ROOT / "model"),
                "NOTEAI_TEST_SIGNER_UA": diagnostic.SIGNER_USER_AGENT,
            }
        )
        completed_process = subprocess.run(
            [sys.executable, "-c", code],
            env=environment,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )
        self.assertEqual(
            completed_process.returncode,
            0,
            completed_process.stderr,
        )
        self.assertEqual(
            json.loads(completed_process.stdout),
            {"calls": 1, "isolated": True},
        )

    def test_user_agent_exactly_matches_pinned_signer_and_adapter(self):
        model_dir = ROOT / "model"
        sys.path.insert(0, str(model_dir))
        try:
            import spider_xhs_http
        finally:
            sys.path.remove(str(model_dir))
        signer = (
            model_dir / "vendor/spider_xhs/xhs_main_260411.js"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'userAgent: "' + diagnostic.SIGNER_USER_AGENT + '"',
            signer,
        )
        adapter_source = (model_dir / "spider_xhs_http.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            spider_xhs_http.BROWSER_USER_AGENT,
            diagnostic.SIGNER_USER_AGENT,
        )
        self.assertIn('"user-agent": BROWSER_USER_AGENT', adapter_source)

    def test_executor_has_no_retry_loop_or_production_database_access(self):
        source = Path(diagnostic.__file__).read_text(encoding="utf-8")
        self.assertNotIn('os.environ["DATABASE_URL"]', source)
        self.assertNotIn("psycopg", source)
        self.assertIn("NOTEAI_SQLITE_PATH", source)
        self.assertIn("mode=ro&immutable=1", source)
        self.assertNotIn("follow_redirects=True", source)
        self.assertNotIn("raw_response", source)
        self.assertNotIn("raw_payload", source)


if __name__ == "__main__":
    unittest.main()
