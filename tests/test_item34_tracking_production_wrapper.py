import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
WRAPPER_PATH = ROOT / "deploy" / "production" / "execute_item34_tracking.py"
SPEC = importlib.util.spec_from_file_location("item34_production_wrapper", WRAPPER_PATH)
wrapper = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(wrapper)


TRACK_ID = "8cc8b6de-f826-4c4a-965e-67dbb7e1fcf8"
IMAGE = "registry.cn-shenzhen.aliyuncs.com/noteai/xhs@sha256:" + "a" * 64


class Item34TrackingProductionWrapperTests(unittest.TestCase):
    def _image_inspect(self):
        labels = {
            "com.noteai.runtime.role": "xhs-http",
            **wrapper._expected_image_source_labels(),
        }
        return [{
            "Id": "sha256:" + "b" * 64,
            "RepoDigests": [IMAGE],
            "Config": {
                "Labels": labels,
                "Entrypoint": ["/app/scripts/docker_entrypoint.sh"],
            },
        }]

    def test_image_preflight_binds_current_runtime_sources_and_repo_digest(self):
        with mock.patch.object(
            wrapper, "_docker_json", return_value=self._image_inspect()
        ):
            self.assertEqual(wrapper._image_preflight(IMAGE), "b" * 64)

    def test_image_preflight_rejects_source_label_drift(self):
        inspected = self._image_inspect()
        inspected[0]["Config"]["Labels"][
            "com.noteai.item34.source.spider-sha256"
        ] = "0" * 64
        with mock.patch.object(wrapper, "_docker_json", return_value=inspected):
            with self.assertRaises(wrapper.ProductionAdapterError) as raised:
                wrapper._image_preflight(IMAGE)
        self.assertEqual(raised.exception.code, "image_contract")

    def test_worker_container_is_hardened_and_keeps_the_image_entrypoint(self):
        argv = wrapper._container_create_argv(
            name="noteai-item34-tracking-24h",
            image=IMAGE,
            env_file=wrapper.XHS_ENV_PATH,
            command=list(wrapper.checkpoint.WORKER_ARGV),
            acceptance_track_id=TRACK_ID,
            acceptance_stage="24h",
        )
        self.assertEqual(argv[:3], ["docker", "container", "create"])
        self.assertEqual(argv[-6], IMAGE)
        self.assertEqual(argv[-5:], list(wrapper.checkpoint.WORKER_ARGV))
        self.assertNotIn("--rm", argv)
        self.assertFalse(any(value.startswith("--entrypoint") for value in argv))
        for required in (
            "--pull=never",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit=64",
            "--env=NOTEAI_XHS_COLLECTION_SUSPENDED=0",
            "--env=NOTEAI_ITEM34_ACCEPTANCE=1",
            f"--env=NOTEAI_ITEM34_TRACK_ID={TRACK_ID}",
            "--env=NOTEAI_ITEM34_CHECKPOINT_STAGE=24h",
        ):
            self.assertIn(required, argv)

    def test_inner_commands_are_image_baked_and_narrowly_allowlisted(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        entrypoint = (ROOT / "scripts" / "docker_entrypoint.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "COPY deploy/production/execute_item34_tracking.py "
            "tools/execute_item34_tracking_checkpoint.py ./model/",
            dockerfile,
        )
        for binding in (
            "_snapshot:24h",
            "_snapshot:3d",
            "_schedule:24h",
            "_bind:24h",
            "_role:24h",
            "_role:3d",
            "_config:activate",
            "_config:restore",
        ):
            self.assertIn(binding, entrypoint)
        self.assertNotIn("--entrypoint", entrypoint)

    def test_attempt_digest_is_derived_from_the_canonical_database_uuid(self):
        expected = wrapper.hashlib.sha256(
            f"noteai-item34-tracking-attempt-row-v1:{TRACK_ID}".encode("ascii")
        ).hexdigest()
        self.assertEqual(wrapper._attempt_digest(TRACK_ID), expected)
        with self.assertRaises(wrapper.ProductionAdapterError) as raised:
            wrapper._attempt_digest("caller-supplied-digest")
        self.assertEqual(raised.exception.code, "attempt_identity")

    def test_write_audit_is_computed_from_pre_and_post_counters(self):
        before = {
            "attempt_count": 0,
            "crawler_event_count": 10,
            "growth_record_count": 0,
            "user_memory_count": 0,
        }
        after = {
            "attempt_count": 1,
            "crawler_event_count": 11,
            "growth_record_count": 1,
            "user_memory_count": 1,
        }
        audited = wrapper._write_audit(
            "3d", before, after, transition_used=True
        )
        self.assertEqual(audited["tracking_provider_attempts_inserted"], 1)
        self.assertEqual(audited["crawler_events_inserted"], 1)
        self.assertEqual(audited["growth_records_inserted"], 1)
        self.assertEqual(audited["user_memories_inserted"], 1)
        self.assertEqual(audited["system_settings_row_mutations"], 1)
        self.assertEqual(audited["other_tracked_notes_row_mutations"], 0)

    def test_write_audit_rejects_counter_regression_and_booleans(self):
        for before, after in (({"attempt_count": 2}, {"attempt_count": 1}),
                              ({"attempt_count": False}, {"attempt_count": 1})):
            full_before = {
                "crawler_event_count": 0,
                "growth_record_count": 0,
                "user_memory_count": 0,
                **before,
            }
            full_after = {
                "crawler_event_count": 1,
                "growth_record_count": 0,
                "user_memory_count": 0,
                **after,
            }
            with self.subTest(before=before):
                with self.assertRaises(wrapper.ProductionAdapterError) as raised:
                    wrapper._write_audit(
                        "24h", full_before, full_after, transition_used=False
                    )
                self.assertEqual(raised.exception.code, "write_audit")

    def test_known_nonzero_worker_exit_is_not_mislabeled_unknown(self):
        completed = subprocess.CompletedProcess(
            ["docker", "container", "start"], 1, b'{"failed":1}\n', b""
        )
        inspect = [{"State": {"Running": False, "ExitCode": 1}}]
        with mock.patch.object(wrapper.subprocess, "run", return_value=completed), \
             mock.patch.object(wrapper, "_docker_json", return_value=inspect):
            raw, exit_code = wrapper._start_known_container(
                "noteai-item34-tracking-24h", timeout=1, provider=True
            )
        self.assertEqual(raw, b'{"failed":1}\n')
        self.assertEqual(exit_code, 1)

    def test_uncertain_worker_transport_is_stopped_and_never_retried(self):
        with mock.patch.object(
            wrapper.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["docker"], 1),
        ) as run, mock.patch.object(
            wrapper,
            "_quiesce_named_container",
            return_value={
                "container_present": True,
                "before_running": True,
                "after_running": False,
            },
        ) as quiesce:
            with self.assertRaises(wrapper.ProductionAdapterError) as raised:
                wrapper._start_known_container(
                    "noteai-item34-tracking-24h", timeout=1, provider=True
                )
        self.assertEqual(raised.exception.code, "worker_outcome_unknown")
        self.assertEqual(run.call_count, 1)
        quiesce.assert_called_once_with("noteai-item34-tracking-24h")

    def test_json_result_must_be_one_bounded_object(self):
        self.assertEqual(wrapper._json_line(b'{"ok":true}\n', "bad"), {"ok": True})
        for raw in (b"", b"{}\n{}\n", b"[]\n"):
            with self.subTest(raw=raw):
                with self.assertRaises(wrapper.ProductionAdapterError):
                    wrapper._json_line(raw, "bad")

    def test_worker_json_accepts_event_then_pretty_result_only(self):
        raw = (
            b'{"crawler_event":{"action":"round_complete"}}\n'
            b'{\n'
            b'  "claimed": 1,\n'
            b'  "attempted": 1,\n'
            b'  "collected": 1,\n'
            b'  "failed": 0,\n'
            b'  "released": 0,\n'
            b'  "total": 1\n'
            b'}\n'
        )
        self.assertEqual(
            wrapper._worker_json_result(raw),
            {
                "claimed": 1,
                "attempted": 1,
                "collected": 1,
                "failed": 0,
                "released": 0,
                "total": 1,
            },
        )
        for invalid in (
            raw + b"not-json\n",
            raw + b'{"extra":true}\n',
            b'{"unexpected":{}}\n' + raw,
        ):
            with self.subTest(invalid=invalid[-32:]):
                with self.assertRaises(wrapper.ProductionAdapterError) as raised:
                    wrapper._worker_json_result(invalid)
                self.assertEqual(raised.exception.code, "worker_json")

    def test_worker_json_normalizes_only_known_zero_call_outcomes(self):
        expected = {
            "claimed": 0,
            "attempted": 0,
            "collected": 0,
            "failed": 0,
            "released": 0,
            "total": 0,
        }
        for value in (
            {"skipped": True, "reason": "server_session_logged_out", "collected": 0},
            {"skipped": True, "reason": "collection_safety_unavailable", "collected": 0},
            {"message": "暂无待采集记录", "collected": 0},
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    wrapper._worker_json_result(wrapper._canonical_json(value)),
                    expected,
                )
        for value in (
            {"skipped": True, "reason": "unknown", "collected": 0},
            {"skipped": True, "reason": "server_session_logged_out", "collected": 1},
        ):
            with self.subTest(value=value):
                with self.assertRaises(wrapper.ProductionAdapterError):
                    wrapper._worker_json_result(wrapper._canonical_json(value))

    def test_preexisting_collection_block_rejects_before_worker(self):
        adapter = object.__new__(wrapper.HostAdapter)
        adapter.stage = "24h"
        adapter.track_id = TRACK_ID
        adapter.runtime_state = {"active": "inactive", "sub": "dead"}
        adapter.initial_private = None
        adapter.latest_private = None
        adapter.last_worker = None
        adapter.transition_used = False
        with mock.patch.object(
            adapter,
            "_short_container",
            return_value={
                "snapshot": {},
                "private": {
                    "safety": {
                        "present": True,
                        "session_blocked": True,
                        "reason_code": "server_session_logged_out",
                    }
                },
            },
        ):
            with self.assertRaises(wrapper.ProductionAdapterError) as raised:
                adapter.read_snapshot(phase="pre")
        self.assertEqual(raised.exception.code, "collection_safety_blocked")

    def test_short_helper_cleanup_runs_after_create_uncertainty(self):
        adapter = object.__new__(wrapper.HostAdapter)
        adapter.image = IMAGE
        with mock.patch.object(
            wrapper,
            "_run",
            side_effect=wrapper.ProductionAdapterError("local_command_unknown"),
        ), mock.patch.object(wrapper, "_cleanup_helper_container") as cleanup:
            with self.assertRaises(wrapper.ProductionAdapterError):
                adapter._short_container("role", ["python", "x.py"])
        cleanup.assert_called_once()

    def test_session_failure_persists_block_and_surfaces_stable_reason(self):
        adapter = mock.Mock()
        adapter.read_snapshot.return_value = {}
        adapter.authorization.return_value = None
        adapter.worker_name = "noteai-item34-tracking-3d"
        adapter.last_worker = {"result": {"attempted": 1}}
        adapter.failure_readback.return_value = {
            "status": "failed",
            "error_code": "challenge",
        }
        lock = mock.MagicMock()
        with mock.patch.object(wrapper.os, "geteuid", return_value=0), \
             mock.patch.object(wrapper, "_exclusive_lock", return_value=lock), \
             mock.patch.object(wrapper, "HostAdapter", return_value=adapter), \
             mock.patch.object(
                 wrapper.checkpoint,
                 "execute_3d_checkpoint",
                 side_effect=RuntimeError("safe test failure"),
             ), \
             mock.patch.object(
                 wrapper,
                 "_quiesce_named_container",
                 return_value={
                     "container_present": True,
                     "before_running": False,
                     "after_running": False,
                 },
             ):
            with self.assertRaises(wrapper.ProductionAdapterError) as raised:
                wrapper._execute_host("3d", TRACK_ID, IMAGE)
        self.assertEqual(raised.exception.code, "xhs_session_blocked_challenge")
        adapter.persist_session_block.assert_called_once_with(
            {"status": "failed", "error_code": "challenge"}
        )
        adapter.cleanup_known_worker.assert_called_once_with()

    def test_wrapper_never_opens_or_copies_managed_env_files(self):
        source = WRAPPER_PATH.read_text(encoding="utf-8")
        self.assertIn('Path("/etc/noteai/xhs-tracking.env")', source)
        self.assertIn('Path("/etc/noteai/api.env")', source)
        self.assertNotIn("XHS_ENV_PATH.read", source)
        self.assertNotIn("APP_ENV_PATH.read", source)
        self.assertNotIn("open(XHS_ENV_PATH", source)
        self.assertNotIn("open(APP_ENV_PATH", source)
        self.assertNotIn("capture_output=True", source)

    def test_provider_runtime_preflight_exposes_only_safe_health_facts(self):
        class Credentials:
            @classmethod
            def from_runtime_settings(cls):
                return cls()

            def public_health(self):
                return {
                    "configured": True,
                    "status": "ready",
                    "cookie_count": 2,
                    "a1_present": True,
                    "auth_cookie_present": True,
                    "auth_cookie_expired": False,
                    "secret_marker": "must-not-escape",
                }

        fake = SimpleNamespace(
            SessionCredentials=Credentials,
            verify_pinned_signer_assets=lambda: {"one.js": "a" * 64},
        )
        with mock.patch.dict(sys.modules, {"spider_xhs_http": fake}):
            result = wrapper._provider_runtime_preflight()
        self.assertEqual(
            result,
            {
                "session_configured": True,
                "session_status": "ready",
                "session_cookie_count": 2,
                "session_a1_present": True,
                "session_auth_cookie_present": True,
                "session_auth_cookie_expired": False,
                "signer_assets_verified": True,
                "signer_asset_count": 1,
                "secret_values_recorded": False,
            },
        )
        self.assertNotIn("must-not-escape", repr(result))

    def test_provider_runtime_preflight_fails_closed_before_dispatch(self):
        class Credentials:
            @classmethod
            def from_runtime_settings(cls):
                return cls()

            def public_health(self):
                return {
                    "configured": True,
                    "status": "login_required",
                    "cookie_count": 2,
                    "a1_present": True,
                    "auth_cookie_present": False,
                    "auth_cookie_expired": True,
                }

        fake = SimpleNamespace(
            SessionCredentials=Credentials,
            verify_pinned_signer_assets=lambda: {"one.js": "a" * 64},
        )
        with mock.patch.dict(sys.modules, {"spider_xhs_http": fake}):
            with self.assertRaises(wrapper.ProductionAdapterError) as raised:
                wrapper._provider_runtime_preflight()
        self.assertEqual(raised.exception.code, "provider_runtime_preflight")

    def test_tracking_daily_admission_casts_text_clock_before_comparison(self):
        class Cursor:
            def __init__(self):
                self.query = ""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, query):
                self.query = query

            def fetchone(self):
                if self.query == "SELECT current_user":
                    return {"current_user": "noteai_xhs_tracking"}
                self.assert_daily_query()
                return {"count": 0}

            def fetchall(self):
                return [
                    {"key": "crawler_config", "is_secret": 0},
                    {"key": "xhs_collection_safety", "is_secret": 0},
                ]

            def assert_daily_query(self):
                if "admitted_at::timestamptz" not in self.query:
                    raise AssertionError("text admission clock was not cast")

        class Connection:
            def __init__(self):
                self.cursor_value = Cursor()

            def transaction(self):
                return self.cursor_value

            def cursor(self):
                return self.cursor_value

            def close(self):
                return None

        provider = {
            "session_configured": True,
            "session_status": "ready",
            "session_cookie_count": 2,
            "session_a1_present": True,
            "session_auth_cookie_present": True,
            "session_auth_cookie_expired": False,
            "signer_assets_verified": True,
            "signer_asset_count": 1,
            "secret_values_recorded": False,
        }
        connection = Connection()
        with mock.patch.object(
            wrapper, "_provider_runtime_preflight", return_value=provider
        ), mock.patch.object(wrapper, "_connect", return_value=connection):
            result = wrapper._inner_role()

        connection.cursor_value.assert_daily_query()
        self.assertEqual(result["tracking_daily_provider_used"], 0)
        self.assertEqual(result["tracking_daily_provider_remaining"], 300)


if __name__ == "__main__":
    unittest.main()
