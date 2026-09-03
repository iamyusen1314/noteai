import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, urlsplit

from tools import production_ai_dispatcher_secret_activator as activator


CONTROL_URL = (
    "postgresql://noteai_schema_task_durable_ai_0017:control@"
    "db.invalid:5432/noteai?sslmode=require"
)
PASSWORD = "A" * 64


class FakeConnection:
    def close(self):
        return None


class IdentityConnection:
    def __init__(self, session_name, current_name):
        self.session_name = session_name
        self.current_name = current_name

    def execute(self, statement, *_args):
        if str(statement).startswith("SET LOCAL ROLE"):
            self.current_name = activator.OWNER_ROLE
            return mock.Mock()
        return mock.Mock(
            fetchone=lambda: {
                "session_name": self.session_name,
                "current_name": self.current_name,
            }
        )


class CommitUnknownConnection:
    class Transaction:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            raise OSError("synthetic commit acknowledgement loss")

    def transaction(self):
        return self.Transaction()

    def execute(self, *_args, **_kwargs):
        return mock.Mock()


class DispatcherSecretActivatorTests(unittest.TestCase):
    def _root(self, raw: str) -> Path:
        root = Path(raw) / "etc-noteai"
        root.mkdir(mode=0o700)
        root.chmod(0o700)
        return root

    def test_direct_script_help_is_runnable(self):
        completed = subprocess.run(
            [sys.executable, str(Path(activator.__file__).resolve()), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_role_url_preserves_network_and_binds_dispatcher_identity(self):
        rendered = activator.build_role_database_url(CONTROL_URL, PASSWORD)
        parsed = urlsplit(rendered)
        self.assertEqual(unquote(parsed.username or ""), activator.DISPATCHER_ROLE)
        self.assertEqual(unquote(parsed.password or ""), PASSWORD)
        self.assertEqual(parsed.hostname, "db.invalid")
        self.assertEqual(parsed.port, 5432)
        self.assertEqual(parsed.path, "/noteai")
        self.assertEqual(parsed.query, "sslmode=require")

    def test_owner_activation_requires_the_exact_temporary_executor(self):
        with self.assertRaisesRegex(
            activator.DispatcherSecretError,
            "executor_identity",
        ):
            activator._activate_owner(
                IdentityConnection("some_other_owner", activator.OWNER_ROLE)
            )
        accepted = IdentityConnection(
            activator.CONTROL_ROLE,
            activator.CONTROL_ROLE,
        )
        activator._activate_owner(accepted)
        self.assertEqual(accepted.current_name, activator.OWNER_ROLE)

    def test_role_url_rejects_query_identity_override_and_control_chars(self):
        for value in (
            CONTROL_URL + "&user=other",
            CONTROL_URL + "&password=other",
            CONTROL_URL + "&options=-c%20role%3Dother",
            CONTROL_URL + "&host=evil.invalid",
            CONTROL_URL + "&sslpassword=secret",
            CONTROL_URL + "\n",
        ):
            with self.subTest(value=value):
                with self.assertRaises(activator.DispatcherSecretError):
                    activator.build_role_database_url(value, PASSWORD)

    def test_scram_verifier_is_deterministic_and_contains_no_plaintext(self):
        verifier = activator._scram_verifier(PASSWORD, salt=b"S" * 16)
        self.assertTrue(verifier.startswith("SCRAM-SHA-256$4096:"))
        self.assertNotIn(PASSWORD, verifier)
        self.assertEqual(
            verifier,
            activator._scram_verifier(PASSWORD, salt=b"S" * 16),
        )

    def test_apply_writes_one_private_file_and_emits_no_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            with (
                mock.patch.object(
                    activator,
                    "preflight_activation",
                    return_value={"status": "preflight_verified"},
                ),
                mock.patch.object(
                    activator,
                    "_connect",
                    return_value=FakeConnection(),
                ),
                mock.patch.object(
                    activator,
                    "_apply_role",
                    return_value={
                        "role_attribute_writes": 1,
                        "password_writes": 1,
                    },
                ),
                mock.patch.object(
                    activator,
                    "_audit_dispatcher_login",
                    return_value={"read_only_transaction_count": 1},
                ),
            ):
                result = activator.apply_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                    password_factory=lambda _: PASSWORD,
                )
            final = env_root / activator.FINAL_NAME
            self.assertTrue(final.is_file())
            self.assertEqual(final.stat().st_mode & 0o777, 0o600)
            self.assertEqual(
                set(
                    line.split("=", 1)[0]
                    for line in final.read_text(encoding="utf-8").splitlines()
                ),
                {"DATABASE_URL"},
            )
            serialized = json.dumps(result, sort_keys=True)
            self.assertNotIn(PASSWORD, serialized)
            self.assertNotIn("postgresql://", serialized)
            self.assertEqual(result["status"], "activated")
            self.assertFalse((env_root / activator.TASK_NAME).exists())

    def test_preflight_reports_the_completed_read_only_connection(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            with mock.patch.object(
                activator,
                "_database_preflight",
                return_value={"dispatcher_login": False},
            ):
                result = activator.preflight_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
        self.assertEqual(result["incident_class"], "CONNECTED_KNOWN")
        self.assertEqual(
            result["database_outcome"],
            "READ_ONLY_VERIFIED",
        )
        self.assertEqual(result["database_writes"], 0)

    def test_apply_connected_unknown_preserves_stage_and_never_retries(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            connection = FakeConnection()
            with (
                mock.patch.object(activator, "preflight_activation"),
                mock.patch.object(activator, "_connect", return_value=connection) as connect,
                mock.patch.object(
                    activator,
                    "_apply_role",
                    side_effect=activator.DispatcherSecretError(
                        "connected_unknown_role_apply"
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    activator.DispatcherSecretError,
                    "connected_unknown_role_apply",
                ):
                    activator.apply_activation(
                        CONTROL_URL,
                        env_root=env_root,
                        expected_uid=os.geteuid(),
                        require_root=False,
                        password_factory=lambda _: PASSWORD,
                    )
            self.assertEqual(connect.call_count, 1)
            self.assertTrue(
                (env_root / activator.TASK_NAME / activator.STAGE_NAME).is_file()
            )
            self.assertFalse((env_root / activator.FINAL_NAME).exists())

    def test_reconcile_committed_promotes_existing_stage_without_new_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            task_root = env_root / activator.TASK_NAME
            role_url = activator.build_role_database_url(CONTROL_URL, PASSWORD)
            activator._write_stage(
                task_root,
                role_url,
                expected_uid=os.geteuid(),
            )
            with (
                mock.patch.object(activator, "_read_dispatcher_login", return_value=True),
                mock.patch.object(activator, "_audit_dispatcher_login"),
            ):
                result = activator.reconcile_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
            self.assertEqual(result["status"], "reconciled_committed")
            self.assertTrue((env_root / activator.FINAL_NAME).is_file())
            self.assertFalse(task_root.exists())

    def test_reconcile_finishes_crash_between_link_and_stage_unlink(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            task_root = env_root / activator.TASK_NAME
            role_url = activator.build_role_database_url(CONTROL_URL, PASSWORD)
            stage = activator._write_stage(
                task_root,
                role_url,
                expected_uid=os.geteuid(),
            )
            final = env_root / activator.FINAL_NAME
            os.link(stage, final, follow_symlinks=False)
            with (
                mock.patch.object(activator, "_read_dispatcher_login", return_value=True),
                mock.patch.object(activator, "_audit_dispatcher_login"),
            ):
                result = activator.reconcile_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
            self.assertEqual(result["status"], "reconciled_committed")
            self.assertEqual(final.stat().st_nlink, 1)
            self.assertFalse(task_root.exists())

    def test_reconcile_nologin_removes_final_only_after_rejection(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            role_url = activator.build_role_database_url(CONTROL_URL, PASSWORD)
            task_root = env_root / activator.TASK_NAME
            stage = activator._write_stage(
                task_root,
                role_url,
                expected_uid=os.geteuid(),
            )
            final = env_root / activator.FINAL_NAME
            activator._publish_stage(
                stage,
                final,
                task_root,
                expected_uid=os.geteuid(),
            )
            with (
                mock.patch.object(activator, "_read_dispatcher_login", return_value=False),
                mock.patch.object(activator, "_credential_rejected") as rejected,
            ):
                result = activator.reconcile_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
            rejected.assert_called_once_with(role_url)
            self.assertEqual(result["status"], "reconciled_not_committed")
            self.assertFalse(final.exists())

    def test_reconcile_nologin_cleanup_failure_keeps_rolled_back_classification(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            role_url = activator.build_role_database_url(CONTROL_URL, PASSWORD)
            task_root = env_root / activator.TASK_NAME
            activator._write_stage(
                task_root,
                role_url,
                expected_uid=os.geteuid(),
            )
            with (
                mock.patch.object(activator, "_read_dispatcher_login", return_value=False),
                mock.patch.object(activator, "_credential_rejected"),
                mock.patch.object(
                    activator.Path,
                    "unlink",
                    side_effect=OSError("synthetic unlink failure"),
                ),
                self.assertRaisesRegex(
                    activator.DispatcherSecretError,
                    "connected_known_reconcile_rolled_back_cleanup",
                ),
            ):
                activator.reconcile_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )

    def test_reconcile_committed_removes_empty_post_unlink_task_root(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            role_url = activator.build_role_database_url(CONTROL_URL, PASSWORD)
            task_root = env_root / activator.TASK_NAME
            stage = activator._write_stage(
                task_root,
                role_url,
                expected_uid=os.geteuid(),
            )
            activator._publish_stage(
                stage,
                env_root / activator.FINAL_NAME,
                task_root,
                expected_uid=os.geteuid(),
            )
            task_root.mkdir(mode=0o700)
            task_root.chmod(0o700)
            with (
                mock.patch.object(activator, "_read_dispatcher_login", return_value=True),
                mock.patch.object(activator, "_audit_dispatcher_login"),
            ):
                result = activator.reconcile_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
            self.assertEqual(result["status"], "reconciled_committed")
            self.assertFalse(task_root.exists())

    def test_rollback_rejects_active_unit_before_database_or_file_change(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            role_url = activator.build_role_database_url(CONTROL_URL, PASSWORD)
            task_root = env_root / activator.TASK_NAME
            stage = activator._write_stage(
                task_root,
                role_url,
                expected_uid=os.geteuid(),
            )
            activator._publish_stage(
                stage,
                env_root / activator.FINAL_NAME,
                task_root,
                expected_uid=os.geteuid(),
            )

            def active(command, **_kwargs):
                return subprocess.CompletedProcess(command, 0, "active\n", "")

            with mock.patch.object(activator, "_revoke_role") as revoke:
                with self.assertRaisesRegex(
                    activator.DispatcherSecretError,
                    "dispatcher_unit_active",
                ):
                    activator.rollback_activation(
                        CONTROL_URL,
                        env_root=env_root,
                        expected_uid=os.geteuid(),
                        require_root=False,
                        runner=active,
                    )
            revoke.assert_not_called()
            self.assertTrue((env_root / activator.FINAL_NAME).is_file())

    def test_rollback_post_commit_readback_failure_requires_reconcile(self):
        with tempfile.TemporaryDirectory() as raw:
            env_root = self._root(raw)
            role_url = activator.build_role_database_url(CONTROL_URL, PASSWORD)
            task_root = env_root / activator.TASK_NAME
            stage = activator._write_stage(
                task_root,
                role_url,
                expected_uid=os.geteuid(),
            )
            final = env_root / activator.FINAL_NAME
            activator._publish_stage(
                stage,
                final,
                task_root,
                expected_uid=os.geteuid(),
            )

            def inactive(command, **_kwargs):
                return subprocess.CompletedProcess(command, 3, "inactive\n", "")

            with (
                mock.patch.object(activator, "_revoke_role"),
                mock.patch.object(
                    activator,
                    "_read_dispatcher_login",
                    side_effect=activator.DispatcherSecretError(
                        "database_connect"
                    ),
                ),
                self.assertRaisesRegex(
                    activator.DispatcherSecretError,
                    "connected_known_committed_role_revoke_reconcile",
                ),
            ):
                activator.rollback_activation(
                    CONTROL_URL,
                    env_root=env_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                    runner=inactive,
                )
            self.assertTrue(final.is_file())

    def test_confirmation_fails_before_stdin_or_connection(self):
        stderr = io.StringIO()
        with (
            mock.patch.dict(os.environ, {activator.CONFIRM_ENV: ""}),
            mock.patch.object(activator.sys, "stdin", io.StringIO("not-json")),
            contextlib.redirect_stderr(stderr),
            mock.patch.object(activator, "_connect") as connect,
        ):
            result = activator.main(["--apply"])
        self.assertEqual(result, 2)
        self.assertIn("confirmation_missing", stderr.getvalue())
        connect.assert_not_called()

    def test_commit_acknowledgement_loss_is_connected_unknown(self):
        with (
            mock.patch.object(activator, "_activate_owner"),
            mock.patch.object(
                activator,
                "validate_database_contract",
                return_value={},
            ),
            self.assertRaisesRegex(
                activator.DispatcherSecretError,
                "connected_unknown_role_apply",
            ),
        ):
            activator._apply_role(
                CommitUnknownConnection(),
                "SCRAM-SHA-256$4096:synthetic$stored:server",
            )


if __name__ == "__main__":
    unittest.main()
