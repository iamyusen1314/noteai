import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import production_managed_secret_files as managed_files
from tools import production_managed_secret_lifecycle as lifecycle
from tools import production_managed_secret_login_audit as login_audit
from tools import production_managed_secret_roles as managed_roles
from tools import production_managed_secret_initial_apply as initial_apply
from tools import production_secret_envelope as secret_envelope


PASSWORDS = {
    role: f"{index:02d}" + ("A" * 48)
    for index, role in enumerate(managed_roles.TARGET_LOGIN_ROLES)
}


def database_url(role: str, password: str = "A" * 48) -> str:
    return f"postgresql://{role}:{password}@db.invalid:5432/noteai"


class ManagedSecretFileTests(unittest.TestCase):
    def _private(self, path: Path, body: str) -> None:
        path.write_text(body, encoding="utf-8")
        path.chmod(0o600)

    def _api_c(self, root: Path) -> str:
        admin_password_key = "ADMIN_" + "PASSWORD"
        api_body = (
            f"DATABASE_URL={database_url('noteai_app')}\n"
            "NOTEAI_FACT_SEARCH=0\n"
        )
        admin_body = (
            f"DATABASE_URL={database_url('noteai_app')}\n"
            f"{admin_password_key}=synthetic-admin-value\n"
            "ADMIN_USERNAME=noteai_admin\n"
        )
        self._private(root / "api.env", api_body)
        self._private(root / "admin.env", admin_body)
        return admin_body

    def _payload(self, host_label: str) -> dict[str, object]:
        return {
            "database_urls": {
                role: database_url(
                    managed_files.ROLE_DATABASE_USERS[role],
                    PASSWORDS[managed_files.ROLE_DATABASE_USERS[role]],
                )
                for role in managed_files.STAGED_ROLES[host_label]
            }
        }

    def test_api_c_stage_promote_verify_and_finalize_are_atomic(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "env"
            task_root = root / "task"
            env_root.mkdir()
            self._api_c(env_root)
            result = managed_files.stage_distribution(
                "API-C",
                self._payload("API-C"),
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            staged = json.dumps(result, sort_keys=True)
            for password in PASSWORDS.values():
                self.assertNotIn(password, staged)
            self.assertEqual(result["staged_file_count"], 3)
            self.assertFalse((env_root / "payment.env").exists())

            promoted = managed_files.promote_distribution(
                "API-C",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            verified = managed_files.verify_distribution(
                "API-C",
                env_root=env_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            finalized = managed_files.finalize_distribution(
                "API-C",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )

        self.assertEqual(promoted["promoted_file_count"], 3)
        self.assertEqual(verified["verified_file_count"], 4)
        self.assertEqual(verified["distinct_file_count"], 4)
        self.assertEqual(finalized["rollback_artifact_count"], 0)
        self.assertFalse(task_root.exists())

    def test_api_f_split_uses_host_local_cookie_and_removes_legacy(self):
        cookie = "synthetic-host-local-cookie"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "env"
            task_root = root / "task"
            env_root.mkdir()
            self._private(
                env_root / "api.env",
                f"DATABASE_URL={database_url('noteai_app')}\n",
            )
            self._private(
                env_root / "xhs.env",
                f"NOTEAI_XHS_COOKIES_JSON={cookie}\n",
            )
            result = managed_files.stage_distribution(
                "API-F",
                self._payload("API-F"),
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            self.assertNotIn(cookie, json.dumps(result))
            managed_files.promote_distribution(
                "API-F",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            verified = managed_files.verify_distribution(
                "API-F",
                env_root=env_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            finalized = managed_files.finalize_distribution(
                "API-F",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )

            self.assertIn(
                f"NOTEAI_XHS_COOKIES_JSON={cookie}",
                (env_root / "xhs-trends.env").read_text(encoding="utf-8"),
            )
            self.assertIn(
                f"NOTEAI_XHS_COOKIES_JSON={cookie}",
                (env_root / "xhs-tracking.env").read_text(encoding="utf-8"),
            )
            self.assertFalse((env_root / "xhs.env").exists())
        self.assertEqual(verified["distinct_file_count"], 3)
        self.assertEqual(finalized["legacy_file_removed"], 1)

    def test_api_f_database_only_legacy_creates_suspended_role_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "env"
            task_root = root / "task"
            env_root.mkdir()
            self._private(
                env_root / "api.env",
                f"DATABASE_URL={database_url('noteai_app')}\n",
            )
            self._private(
                env_root / "xhs.env",
                f"DATABASE_URL={database_url('noteai_xhs')}\n",
            )
            preflight = managed_files.preflight_distribution(
                "API-F",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            managed_files.stage_distribution(
                "API-F",
                self._payload("API-F"),
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            managed_files.promote_distribution(
                "API-F",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            managed_files.verify_distribution(
                "API-F",
                env_root=env_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            for name in ("xhs-trends.env", "xhs-tracking.env"):
                keys = {
                    line.split("=", 1)[0]
                    for line in (env_root / name)
                    .read_text(encoding="utf-8")
                    .splitlines()
                }
                self.assertEqual(keys, {"DATABASE_URL"})
            managed_files.finalize_distribution(
                "API-F",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )

        self.assertEqual(preflight["legacy_cookie_present"], 0)
        self.assertEqual(preflight["legacy_database_url_present"], 1)

    def test_api_c_preflight_accepts_only_exact_transition_state(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "env"
            task_root = root / "task"
            env_root.mkdir()
            self._api_c(env_root)
            result = managed_files.preflight_distribution(
                "API-C",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            self._private(
                env_root / "payment.env",
                f"DATABASE_URL={database_url('noteai_payment')}\n",
            )
            with self.assertRaisesRegex(
                managed_files.ManagedSecretFileError,
                "final_file_preexists",
            ):
                managed_files.preflight_distribution(
                    "API-C",
                    env_root=env_root,
                    task_root=task_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )

        self.assertEqual(result["status"], "preflight_verified")
        self.assertEqual(result["new_file_count"], 0)

    def test_rollback_restores_admin_and_removes_new_files(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "env"
            task_root = root / "task"
            env_root.mkdir()
            original = self._api_c(env_root)
            managed_files.stage_distribution(
                "API-C",
                self._payload("API-C"),
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            managed_files.promote_distribution(
                "API-C",
                env_root=env_root,
                task_root=task_root,
                expected_uid=os.geteuid(),
                require_root=False,
            )
            result = managed_files.rollback_distribution(
                "API-C",
                env_root=env_root,
                task_root=task_root,
                require_root=False,
            )

            self.assertEqual(
                (env_root / "admin.env").read_text(encoding="utf-8"),
                original,
            )
            self.assertFalse((env_root / "payment.env").exists())
            self.assertFalse((env_root / "ai-worker.env").exists())
            self.assertFalse(task_root.exists())
        self.assertEqual(result["status"], "rolled_back")

    def test_wrong_database_role_and_task_residue_fail_closed(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            env_root = root / "env"
            task_root = root / "task"
            env_root.mkdir()
            self._api_c(env_root)
            payload = self._payload("API-C")
            payload["database_urls"]["admin"] = database_url("noteai_app")
            with self.assertRaisesRegex(
                managed_files.ManagedSecretFileError,
                "database_role_mismatch",
            ):
                managed_files.stage_distribution(
                    "API-C",
                    payload,
                    env_root=env_root,
                    task_root=task_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )
            task_root.mkdir()
            with self.assertRaisesRegex(
                managed_files.ManagedSecretFileError,
                "task_residue",
            ):
                managed_files.stage_distribution(
                    "API-C",
                    self._payload("API-C"),
                    env_root=env_root,
                    task_root=task_root,
                    expected_uid=os.geteuid(),
                    require_root=False,
                )


class ManagedSecretRoleTests(unittest.TestCase):
    def test_target_set_is_exact_and_dispatcher_remains_inert(self):
        self.assertEqual(len(managed_roles.TARGET_LOGIN_ROLES), 5)
        self.assertNotIn(
            managed_roles.INERT_ROLE,
            managed_roles.TARGET_LOGIN_ROLES,
        )
        self.assertEqual(len(managed_roles.EXPECTED_MIGRATIONS), 16)
        self.assertEqual(
            {role for role, _digest in managed_roles.EXPECTED_MIGRATIONS},
            {
                f"{number:04d}_{suffix}"
                for number, suffix in (
                    (1, "initial.sql"),
                    (2, "shared_runtime_state.sql"),
                    (3, "market_timing.sql"),
                    (4, "xhs_freshness.sql"),
                    (5, "idempotency_requests.sql"),
                    (6, "model_usage_records.sql"),
                    (7, "ai_operations.sql"),
                    (8, "ai_operation_admissions.sql"),
                    (9, "account_security_compliance.sql"),
                    (10, "tracking_execution_contract.sql"),
                    (11, "trends_execution_contract.sql"),
                    (12, "durable_ai_execution_contract.sql"),
                    (13, "private_storage_recovery_contract.sql"),
                    (14, "payment_execution_contract.sql"),
                    (15, "admin_runtime_contract.sql"),
                    (16, "admin_runtime_role_collision.sql"),
                )
            },
        )

    def test_passwords_are_exact_distinct_and_url_safe(self):
        self.assertEqual(managed_roles.validate_passwords(PASSWORDS), PASSWORDS)
        reused = dict(PASSWORDS)
        reused[managed_roles.TARGET_LOGIN_ROLES[-1]] = next(
            iter(PASSWORDS.values())
        )
        with self.assertRaisesRegex(
            managed_roles.ManagedSecretRoleError,
            "password_reuse",
        ):
            managed_roles.validate_passwords(reused)
        malformed = dict(PASSWORDS)
        malformed[managed_roles.TARGET_LOGIN_ROLES[0]] = "not long enough"
        with self.assertRaisesRegex(
            managed_roles.ManagedSecretRoleError,
            "password_shape",
        ):
            managed_roles.validate_passwords(malformed)

    def test_apply_requires_confirmation_before_stdin_or_connection(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                managed_roles,
                "_protected_payload",
                side_effect=AssertionError("stdin must not be read"),
            ),
            mock.patch.object(
                managed_roles,
                "_connect",
                side_effect=AssertionError("database must not be reached"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = managed_roles.main(["--apply"])

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_managed_secret_roles=FAIL code=confirmation_missing",
        )

    def test_protected_payload_failure_never_prints_values(self):
        synthetic = "never-print-protected-control-dsn"
        stderr = io.StringIO()
        with (
            mock.patch.object(
                managed_roles,
                "_connect",
                side_effect=RuntimeError(synthetic),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = managed_roles.main(
                [
                    "--apply",
                    "--confirm",
                    managed_roles.TASK_ID,
                ],
                protected_payload={
                    "database_url": synthetic,
                    "passwords": PASSWORDS,
                },
            )

        self.assertEqual(result, 1)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_managed_secret_roles=FAIL "
            "code=database_connection_failed",
        )
        self.assertNotIn(synthetic, stderr.getvalue())

    def test_source_has_one_bounded_transaction_and_no_business_sql(self):
        source = Path(managed_roles.__file__).read_text(encoding="utf-8")
        self.assertIn("with conn.transaction():", source)
        self.assertIn("SET LOCAL statement_timeout='30s'", source)
        self.assertIn("ALTER ROLE {} LOGIN PASSWORD {}", source)
        self.assertIn("schema_writes", source)
        self.assertIn("business_row_writes", source)
        self.assertNotIn("UPDATE users", source)
        self.assertNotIn("INSERT INTO", source)
        self.assertNotIn("DELETE FROM", source)


class ManagedSecretLoginAuditTests(unittest.TestCase):
    def test_host_audit_aggregates_only_secret_free_counts(self):
        with (
            mock.patch.object(
                managed_files,
                "verify_distribution",
                return_value={"verified_file_count": 4},
            ),
            mock.patch.object(
                managed_files,
                "_parse_env",
                return_value=[("DATABASE_URL", "opaque")],
            ),
            mock.patch.object(
                login_audit,
                "_audit_connection",
                return_value={
                    "connection_count": 1,
                    "read_only_transaction_count": 1,
                    "unexpected_elevation_count": 0,
                    "incoming_membership_count": 0,
                    "owned_object_count": 0,
                    "ledger_read_count": 0,
                },
            ) as audit_connection,
        ):
            result = login_audit.audit_host(
                "API-C",
                require_root=False,
            )

        self.assertEqual(audit_connection.call_count, 4)
        self.assertEqual(result["connection_count"], 4)
        self.assertEqual(result["read_only_transaction_count"], 4)
        self.assertEqual(result["business_values_read"], 0)
        self.assertNotIn("opaque", json.dumps(result))


class ManagedSecretLifecycleTests(unittest.TestCase):
    def test_installed_program_names_select_exact_action(self):
        self.assertEqual(
            lifecycle._action_from_program(lifecycle.ROTATE_BASENAME),
            "rotate",
        )
        self.assertEqual(
            lifecycle._action_from_program(lifecycle.REVOKE_BASENAME),
            "revoke",
        )
        self.assertIsNone(
            lifecycle._action_from_program("unrecognized-program")
        )

    def test_lifecycle_requires_confirmation_before_stdin(self):
        stderr = io.StringIO()
        with (
            mock.patch("json.load", side_effect=AssertionError("no stdin")),
            contextlib.redirect_stderr(stderr),
        ):
            result = lifecycle.main(
                ["rotate", "--role", "noteai_payment"]
            )
        self.assertEqual(result, 2)
        self.assertIn("confirmation_missing", stderr.getvalue())

    def test_dsn_replacement_is_role_bound_and_url_safe(self):
        old = database_url("noteai_payment")
        new_password = ("_" * 48) + "-"
        replaced = lifecycle._replace_password(
            "noteai_payment",
            old,
            new_password,
        )
        parsed = lifecycle.urlsplit(replaced)
        self.assertEqual(parsed.username, "noteai_payment")
        self.assertEqual(parsed.password, new_password)
        with self.assertRaisesRegex(
            lifecycle.ManagedSecretLifecycleError,
            "database_url_shape",
        ):
            lifecycle._replace_password(
                "noteai_ai_worker",
                old,
                new_password,
            )

    def test_lifecycle_source_enforces_rejection_and_stdin_only(self):
        source = Path(lifecycle.__file__).read_text(encoding="utf-8")
        self.assertIn("sqlstate in {\"28P01\", \"28000\"}", source)
        self.assertIn("password authentication failed", source)
        self.assertIn("is not permitted to log in", source)
        self.assertIn("old_credential_rejected", source)
        self.assertIn("SET TRANSACTION READ ONLY", source)
        self.assertIn("json.load(sys.stdin)", source)
        self.assertNotIn("--password", source)
        self.assertNotIn("--database-url", source)


class ManagedSecretEnvelopeTests(unittest.TestCase):
    def test_hybrid_envelope_round_trip_and_tamper_rejection(self):
        synthetic = b"never-emit-envelope-plaintext"
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            private_path = root / "private.pem"
            public_path = root / "public.pem"
            private_key = secret_envelope.rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
            )
            private_path.write_bytes(
                private_key.private_bytes(
                    secret_envelope.serialization.Encoding.PEM,
                    secret_envelope.serialization.PrivateFormat.PKCS8,
                    secret_envelope.serialization.NoEncryption(),
                )
            )
            public_path.write_bytes(
                private_key.public_key().public_bytes(
                    secret_envelope.serialization.Encoding.PEM,
                    secret_envelope.serialization.PublicFormat.SubjectPublicKeyInfo,
                )
            )
            envelope = secret_envelope.encrypt_payload(
                synthetic,
                public_path,
            )
            recovered = secret_envelope.decrypt_payload(
                envelope,
                private_path,
            )
            tampered = bytearray(envelope)
            tampered[-2] = ord("A") if tampered[-2] != ord("A") else ord("B")
            with self.assertRaises(secret_envelope.SecretEnvelopeError):
                secret_envelope.decrypt_payload(bytes(tampered), private_path)

        self.assertEqual(recovered, synthetic)
        self.assertNotIn(synthetic, envelope)

    def test_initial_apply_generates_five_distinct_role_bound_dsns(self):
        passwords = initial_apply._passwords()
        self.assertEqual(set(passwords), set(managed_roles.TARGET_LOGIN_ROLES))
        self.assertEqual(len(set(passwords.values())), 5)
        base = database_url("temporary_executor")
        for role, password in passwords.items():
            result = initial_apply._database_url(base, role, password)
            parsed = initial_apply.urlsplit(result)
            self.assertEqual(initial_apply.unquote(parsed.username), role)
            self.assertEqual(initial_apply.unquote(parsed.password), password)

    def test_initial_apply_requires_confirmation_before_stdin(self):
        stderr = io.StringIO()
        with (
            mock.patch.object(
                initial_apply.sys.stdin,
                "read",
                side_effect=AssertionError("stdin must not be read"),
            ),
            contextlib.redirect_stderr(stderr),
        ):
            result = initial_apply.main(["--api-c"])
        self.assertEqual(result, 2)
        self.assertIn("confirmation_missing", stderr.getvalue())

    def test_initial_apply_contract_is_single_write_and_secret_free(self):
        source = Path(initial_apply.__file__).read_text(encoding="utf-8")
        self.assertEqual(source.count("managed_roles.apply_contract("), 1)
        self.assertIn("dispatcher_login_enabled", source)
        self.assertIn("business_row_writes", source)
        self.assertIn("plaintext_task_file_count", source)
        self.assertIn("secret_values_emitted", source)
        self.assertNotIn("print(control_database_url", source)
        self.assertNotIn("--database-url", source)
        self.assertNotIn("--password", source)

    def test_runner_binds_exact_source_and_failure_classes(self):
        runner_path = (
            Path(initial_apply.__file__).parent
            / "production_managed_secret_runner.sh"
        )
        runner = runner_path.read_text(encoding="utf-8")
        bound_paths = (
            managed_files.__file__,
            managed_roles.__file__,
            login_audit.__file__,
            lifecycle.__file__,
            secret_envelope.__file__,
            initial_apply.__file__,
        )
        for raw_path in bound_paths:
            digest = __import__("hashlib").sha256(
                Path(raw_path).read_bytes()
            ).hexdigest()
            self.assertIn(digest, runner)
        self.assertIn("fail_preconnect()", runner)
        self.assertIn("fail_connected_unknown()", runner)
        self.assertIn("fail_connected_known()", runner)
        self.assertIn("database_outcome=COMMITTED", runner)
        self.assertIn("--network none", runner)
        self.assertIn("--network host", runner)
        self.assertIn(
            "sha256:c44354b5abfbb2b22f61e8db316d6abf9a44e805ba3ea3b64074508ff8562f1f",
            runner,
        )
        self.assertIn(
            "sha256:0b13cd9cafe7de65d5a2754f7cd119cf6fcb822ab134b66a5009c06e08248504",
            runner,
        )
        self.assertIn("docker image inspect", runner)
        self.assertNotIn("filter label=com.noteai.runtime.role=api", runner)
        self.assertNotIn("\nset -e\n", runner)

    def test_installed_wrapper_preserves_container_boundary_and_stdin(self):
        wrapper = (
            Path(__file__).resolve().parents[1]
            / "scripts"
            / "production"
            / "noteai-managed-secret-lifecycle-wrapper"
        ).read_text(encoding="utf-8")
        self.assertIn("--cap-drop=ALL", wrapper)
        self.assertIn("--security-opt=no-new-privileges:true", wrapper)
        self.assertIn("--read-only", wrapper)
        self.assertIn("-i", wrapper)
        self.assertIn("/etc/noteai:/etc/noteai:rw", wrapper)
        self.assertIn(
            "sha256:c44354b5abfbb2b22f61e8db316d6abf9a44e805ba3ea3b64074508ff8562f1f",
            wrapper,
        )
        self.assertIn("docker image inspect", wrapper)
        self.assertNotIn("filter label=com.noteai.runtime.role=api", wrapper)
        self.assertNotIn("source /etc/noteai", wrapper)
        self.assertNotIn("cat /etc/noteai", wrapper)


if __name__ == "__main__":
    unittest.main()
