import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tools import production_durable_ai_protected_control as control
from tools import production_secret_envelope as envelope


CONTROL_DSN = (
    "postgresql://noteai_schema_task_durable_ai_0017:protected-value@"
    "db.internal.invalid:5432/noteai?sslmode=require"
)
API_DSN = (
    "postgresql://noteai_app:runtime-value@"
    "db.internal.invalid:5432/noteai?sslmode=require"
)


class ProductionDurableAiProtectedControlTests(unittest.TestCase):
    def _fixture(self, raw: str):
        root = Path(raw)
        private_key = root / "control-private.pem"
        public_key = root / "control-public.pem"
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_key.write_bytes(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        public_key.write_bytes(
            key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        api_env = root / "api.env"
        api_env.write_text(
            f"DATABASE_URL={API_DSN}\n"
            "ANTHROPIC_API_KEY=example",
            encoding="utf-8",
        )
        for path in (private_key, api_env):
            path.chmod(0o600)
        protected = envelope.encrypt_payload(
            json.dumps(
                {"control_database_url": CONTROL_DSN},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            public_key,
        )
        return private_key, public_key, api_env, protected

    def test_schema_dispatch_decrypts_in_memory_without_env_or_output_secret(self):
        with tempfile.TemporaryDirectory() as raw:
            private_key, _public_key, api_env, protected = self._fixture(raw)
            observed = []

            def schema_action(action, database_url):
                observed.append((action, database_url))
                return {
                    "status": "verified",
                    "action": action,
                    "secret_values_emitted": 0,
                }

            with mock.patch.object(control, "_schema_action", side_effect=schema_action):
                before = os.environ.get(control.schema_0017.DATABASE_URL_ENV)
                result = control.execute(
                    "schema-preflight",
                    protected,
                    private_key=private_key,
                    api_env=api_env,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
                after = os.environ.get(control.schema_0017.DATABASE_URL_ENV)
        self.assertEqual(observed, [("schema-preflight", CONTROL_DSN)])
        self.assertEqual(before, after)
        self.assertNotIn("protected-value", json.dumps(result))
        self.assertNotIn("example", json.dumps(result))

    def test_confirmation_fails_before_key_or_stdin_is_read(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(control, "_require_private_file") as private_file,
            mock.patch.object(control, "_read_envelope") as read_envelope,
            contextlib.redirect_stderr(stderr),
        ):
            result = control.main(
                [
                    "--action",
                    "schema-apply",
                    "--confirm",
                    "wrong-task",
                ]
            )
        self.assertEqual(result, 2)
        private_file.assert_not_called()
        read_envelope.assert_not_called()
        self.assertIn("confirmation_missing", stderr.getvalue())

    def test_private_key_metadata_and_envelope_tamper_fail_preconnect(self):
        with tempfile.TemporaryDirectory() as raw:
            private_key, _public_key, api_env, protected = self._fixture(raw)
            private_key.chmod(0o644)
            with self.assertRaisesRegex(
                control.ProtectedControlError,
                "private_key_metadata",
            ):
                control.execute(
                    "schema-preflight",
                    protected,
                    private_key=private_key,
                    api_env=api_env,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
            private_key.chmod(0o600)
            tampered = bytearray(protected)
            tampered[-2] ^= 1
            with self.assertRaisesRegex(
                control.ProtectedControlError,
                "envelope_decrypt",
            ):
                control.execute(
                    "schema-preflight",
                    bytes(tampered),
                    private_key=private_key,
                    api_env=api_env,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )

    def test_control_dsn_is_exact_account_and_api_topology(self):
        with tempfile.TemporaryDirectory() as raw:
            private_key, public_key, api_env, _protected = self._fixture(raw)
            for bad_dsn in (
                CONTROL_DSN.replace(control.TASK_ACCOUNT_NAME, "noteai_app"),
                CONTROL_DSN.replace("db.internal.invalid", "other.invalid"),
                CONTROL_DSN + "&host=override.invalid",
                CONTROL_DSN.replace("sslmode=require", "sslmode=disable"),
            ):
                protected = envelope.encrypt_payload(
                    json.dumps(
                        {"control_database_url": bad_dsn},
                        separators=(",", ":"),
                    ).encode("utf-8"),
                    public_key,
                )
                with self.subTest(bad_dsn=bad_dsn), self.assertRaises(
                    control.ProtectedControlError
                ):
                    control.execute(
                        "schema-preflight",
                        protected,
                        private_key=private_key,
                        api_env=api_env,
                        expected_uid=os.geteuid(),
                        require_root=False,
                    )

    def test_schema_apply_exception_is_connected_unknown_and_no_retry(self):
        connection = mock.Mock()
        connection.execute.return_value.fetchone.return_value = {
            "session_role": control.TASK_ACCOUNT_NAME
        }
        with (
            mock.patch.object(control.schema_0017, "source_contract", return_value={}),
            mock.patch.object(
                control.schema_0017,
                "connect_database_url",
                return_value=connection,
            ),
            mock.patch.object(
                control.schema_0017,
                "apply_schema",
                side_effect=OSError("commit acknowledgement lost"),
            ) as apply_schema,
            self.assertRaises(control.ProtectedControlError) as raised,
        ):
            control._schema_action("schema-apply", CONTROL_DSN)
        self.assertEqual(raised.exception.incident_class, "CONNECTED_UNKNOWN")
        self.assertEqual(raised.exception.database_outcome, "UNKNOWN")
        self.assertEqual(
            apply_schema.call_args.kwargs["expected_session_role"],
            control.TASK_ACCOUNT_NAME,
        )
        connection.close.assert_called_once_with()

    def test_dispatcher_actions_are_called_once_and_errors_are_fixed(self):
        with mock.patch.object(
            control.dispatcher,
            "apply_activation",
            return_value={
                "status": "activated",
                "secret_values_emitted": 0,
            },
        ) as apply:
            result = control._dispatcher_action(
                "dispatcher-apply",
                CONTROL_DSN,
            )
        apply.assert_called_once_with(CONTROL_DSN)
        self.assertEqual(result["automatic_retry"], 0)
        with (
            mock.patch.object(
                control.dispatcher,
                "apply_activation",
                side_effect=control.dispatcher.DispatcherSecretError(
                    "connected_unknown_role_apply"
                ),
            ),
            self.assertRaises(control.ProtectedControlError) as raised,
        ):
            control._dispatcher_action("dispatcher-apply", CONTROL_DSN)
        self.assertEqual(raised.exception.code, "dispatcher_database_unknown")
        self.assertEqual(raised.exception.incident_class, "CONNECTED_UNKNOWN")

    def test_reconcile_rejection_failure_preserves_known_rolled_back_state(self):
        with (
            mock.patch.object(
                control.dispatcher,
                "reconcile_activation",
                side_effect=control.dispatcher.DispatcherSecretError(
                    "connected_known_reconcile_rolled_back_cleanup"
                ),
            ),
            self.assertRaises(control.ProtectedControlError) as raised,
        ):
            control._dispatcher_action("dispatcher-reconcile", CONTROL_DSN)
        self.assertEqual(
            raised.exception.code,
            "dispatcher_rolled_back_reconcile_required",
        )
        self.assertEqual(raised.exception.incident_class, "CONNECTED_KNOWN")
        self.assertEqual(raised.exception.database_outcome, "ROLLED_BACK")

    def test_reconcile_connection_failure_does_not_claim_preconnect_safety(self):
        with (
            mock.patch.object(
                control.dispatcher,
                "reconcile_activation",
                side_effect=control.dispatcher.DispatcherSecretError(
                    "database_connect"
                ),
            ),
            self.assertRaises(control.ProtectedControlError) as raised,
        ):
            control._dispatcher_action("dispatcher-reconcile", CONTROL_DSN)
        self.assertEqual(
            raised.exception.code,
            "dispatcher_reconcile_state_unknown",
        )
        self.assertEqual(raised.exception.incident_class, "CONNECTED_UNKNOWN")
        self.assertEqual(raised.exception.database_outcome, "UNKNOWN")

    def test_envelope_size_is_bounded_before_decryption(self):
        with tempfile.TemporaryDirectory() as raw:
            private_key, _public_key, api_env, _protected = self._fixture(raw)
            with self.assertRaisesRegex(
                control.ProtectedControlError,
                "envelope_too_large",
            ):
                control.execute(
                    "schema-preflight",
                    b"x" * (control.MAX_ENVELOPE_BYTES + 1),
                    private_key=private_key,
                    api_env=api_env,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )


if __name__ == "__main__":
    unittest.main()
