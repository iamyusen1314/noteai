import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import production_payment_schema_0018 as schema_0018


class ProductionPaymentSchema0018Tests(unittest.TestCase):
    def test_readback_accepts_only_source_matching_successors_and_never_changes_apply_contract(self):
        contract = schema_0018.source_contract()
        rows = [{"version": name, "sha256": value} for name, value in contract["migration_hashes"].items()]
        successors = contract["successor_hashes"]
        later = [{"version": name, "sha256": value} for name, value in successors.items()]
        self.assertTrue(any(row["version"].startswith("0025_") for row in later))
        schema_0018._verify_ledger(rows + later, schema_0018.EXPECTED_MIGRATION_NAMES,
                                  contract["migration_hashes"], successor_hashes=successors)
        for invalid in (rows[:-1] + later, rows + later + later[-1:], rows + [{"version": "9999_unknown.sql", "sha256": "0" * 64}]):
            with self.assertRaises(schema_0018.PaymentSchemaError):
                schema_0018._verify_ledger(invalid, schema_0018.EXPECTED_MIGRATION_NAMES,
                                          contract["migration_hashes"], successor_hashes=successors)
        with self.assertRaisesRegex(schema_0018.PaymentSchemaError, "ledger_hash"):
            schema_0018._verify_ledger(rows + [{**later[0], "sha256": "0" * 64}],
                                      schema_0018.EXPECTED_MIGRATION_NAMES, contract["migration_hashes"],
                                      successor_hashes=successors)
        with self.assertRaisesRegex(schema_0018.PaymentSchemaError, "ledger_versions"):
            schema_0018._verify_ledger(rows + later, schema_0018.EXPECTED_MIGRATION_NAMES, contract["migration_hashes"])
        with self.assertRaisesRegex(schema_0018.PaymentSchemaError, "ledger_versions"):
            schema_0018._verify_ledger(rows, schema_0018.PRIOR_MIGRATION_NAMES, contract["migration_hashes"])

    def test_source_contract_is_exact_and_incremental(self):
        contract = schema_0018.source_contract()

        self.assertEqual(
            contract["migration_sha256"],
            schema_0018.MIGRATION_SHA256,
        )
        self.assertEqual(
            tuple(contract["migration_hashes"]),
            schema_0018.EXPECTED_MIGRATION_NAMES,
        )
        self.assertEqual(
            schema_0018.EXPECTED_MIGRATION_NAMES[-1],
            "0018_direct_payment_providers.sql",
        )
        self.assertEqual(
            schema_0018.PROVIDERS_AFTER,
            {"adapay", "wechatpay_direct", "alipay_direct"},
        )

    def test_source_contract_allows_only_later_migrations_after_0018(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory)
            for name in schema_0018.EXPECTED_MIGRATION_NAMES:
                source = schema_0018.MIGRATION_DIR / name
                (fixture / name).write_bytes(source.read_bytes())
            (fixture / "0019_later.sql").write_text(
                "SELECT 19;\n", encoding="utf-8"
            )
            with mock.patch.object(schema_0018, "MIGRATION_DIR", fixture):
                self.assertEqual(
                    tuple(schema_0018.source_contract()["migration_hashes"]),
                    schema_0018.EXPECTED_MIGRATION_NAMES,
                )
            (fixture / "0017_z_unexpected.sql").write_text(
                "SELECT 17;\n", encoding="utf-8"
            )
            with mock.patch.object(schema_0018, "MIGRATION_DIR", fixture):
                with self.assertRaisesRegex(
                    schema_0018.PaymentSchemaError,
                    "migration_set",
                ):
                    schema_0018.source_contract()

    def test_apply_requires_exact_confirmation_before_source_or_connection(self):
        stderr = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {
                schema_0018.CONFIRM_ENV: "",
                schema_0018.DATABASE_URL_ENV: "",
            },
            clear=False,
        ), mock.patch.object(
            schema_0018,
            "source_contract",
            side_effect=AssertionError("must not read source"),
        ), mock.patch.object(
            schema_0018,
            "_connect",
            side_effect=AssertionError("must not connect"),
        ), contextlib.redirect_stderr(stderr):
            result = schema_0018.main(["--apply"])

        self.assertEqual(result, 2)
        self.assertEqual(
            stderr.getvalue().strip(),
            "production_payment_schema_0018=FAIL code=confirmation_missing",
        )

    def test_preflight_and_verify_are_read_only_and_close_connection(self):
        for flag, function_name in (
            ("--preflight", "preflight_schema"),
            ("--verify", "verify_schema"),
        ):
            connection = mock.Mock()
            expected = {
                "status": "verified",
                "mode": flag.removeprefix("--"),
                "read_only": True,
                "database_writes": 0,
                "provider_calls": 0,
            }
            output = io.StringIO()
            with self.subTest(flag=flag), mock.patch.object(
                schema_0018,
                "source_contract",
                return_value={},
            ), mock.patch.object(
                schema_0018,
                "_connect",
                return_value=connection,
            ), mock.patch.object(
                schema_0018,
                function_name,
                return_value=expected,
            ) as operation, contextlib.redirect_stdout(output):
                result = schema_0018.main([flag])

            self.assertEqual(result, 0)
            operation.assert_called_once_with(connection, {})
            connection.close.assert_called_once_with()
            self.assertIn('"read_only":true', output.getvalue())
            self.assertNotIn("DATABASE_URL", output.getvalue())

    def test_apply_executes_only_fixed_payload_and_exact_privilege_delta(self):
        connection = mock.Mock()
        transaction = mock.MagicMock()
        connection.transaction.return_value = transaction
        inserted = mock.Mock(rowcount=1)
        payload = b"SELECT 'fixed-0018-payload';"
        before = {("payment_orders", "payment_status", "UPDATE", "NO")}
        after = before | {
            ("payment_refunds", "provider_submitted_at", "SELECT", "NO"),
            ("payment_refunds", "provider_submitted_at", "INSERT", "NO"),
            ("payment_refunds", "provider_submitted_at", "UPDATE", "NO"),
            ("payment_events", "duplicate_delivery_count", "SELECT", "NO"),
            ("payment_events", "duplicate_delivery_count", "INSERT", "NO"),
            ("payment_events", "duplicate_delivery_count", "UPDATE", "NO"),
        }

        def execute(statement, *args):
            if statement.startswith("INSERT INTO schema_migrations"):
                return inserted
            return mock.Mock()

        connection.execute.side_effect = execute
        with mock.patch.object(schema_0018, "_activate_owner"), mock.patch.object(
            schema_0018,
            "_verify_preconditions",
        ), mock.patch.object(
            schema_0018,
            "_verify_postconditions",
            return_value={"ledger_last": schema_0018.MIGRATION_NAME},
        ), mock.patch.object(
            schema_0018,
            "_runtime_role_snapshot",
            side_effect=("same", "same"),
        ), mock.patch.object(
            schema_0018,
            "_column_privilege_snapshot",
            side_effect=(before, after),
        ):
            result = schema_0018.apply_schema(
                connection,
                {"migration_payload": payload},
            )

        statements = [call.args[0] for call in connection.execute.call_args_list]
        self.assertIn(payload.decode("utf-8"), statements)
        self.assertNotIn("apply_postgres_migrations", "\n".join(statements))
        self.assertEqual(result["applied_versions"], [schema_0018.MIGRATION_NAME])
        self.assertEqual(result["database_writes"]["business_row_updates"], 0)
        self.assertEqual(len(result["runtime_privilege_delta"]), 6)

    def test_source_preserves_bounded_owner_transaction_and_no_generic_runner(self):
        source = schema_0018.Path(schema_0018.__file__).read_text(
            encoding="utf-8"
        )

        self.assertIn("SET LOCAL ROLE", source)
        self.assertIn("SET TRANSACTION READ ONLY", source)
        self.assertIn("pg_advisory_xact_lock", source)
        self.assertIn("SET LOCAL statement_timeout='60s'", source)
        self.assertIn("SET LOCAL lock_timeout='5s'", source)
        self.assertIn("PRIOR_MIGRATION_NAMES", source)
        self.assertIn("runtime_privilege_drift", source)
        self.assertNotIn("apply_postgres_migrations()", source)
        self.assertNotIn("render_predeploy.py", source)

    def test_bounded_checks_reject_reversed_or_weakened_constraints(self):
        self.assertTrue(
            schema_0018._exact_bounded_check(
                "CHECK ((duplicate_delivery_count >= 0) AND "
                "(duplicate_delivery_count <= 1000000))",
                column="duplicate_delivery_count",
                lower=0,
                upper=1000000,
                nullable=False,
            )
        )
        self.assertTrue(
            schema_0018._exact_bounded_check(
                "CHECK ((provider_submitted_at IS NULL) OR "
                "((provider_submitted_at >= 946684800) AND "
                "(provider_submitted_at <= 4102444800)))",
                column="provider_submitted_at",
                lower=946684800,
                upper=4102444800,
                nullable=True,
            )
        )
        for definition in (
            "CHECK (duplicate_delivery_count <= 0 AND "
            "duplicate_delivery_count >= 1000000)",
            "CHECK (duplicate_delivery_count >= 0 OR "
            "duplicate_delivery_count <= 1000000)",
            "CHECK (provider_submitted_at IS NULL OR "
            "provider_submitted_at >= 946684800)",
        ):
            with self.subTest(definition=definition):
                self.assertFalse(
                    schema_0018._exact_bounded_check(
                        definition,
                        column=(
                            "provider_submitted_at"
                            if "provider_" in definition
                            else "duplicate_delivery_count"
                        ),
                        lower=(946684800 if "provider_" in definition else 0),
                        upper=(
                            4102444800 if "provider_" in definition else 1000000
                        ),
                        nullable="provider_" in definition,
                    )
                )

    def test_event_guard_requires_full_identity_and_state_contract(self):
        migration = (
            schema_0018.MIGRATION_DIR / schema_0018.MIGRATION_NAME
        ).read_text(encoding="utf-8")
        self.assertTrue(schema_0018._event_guard_definition_exact(migration))
        self.assertFalse(
            schema_0018._event_guard_definition_exact(
                migration.replace(
                    "OR NEW.signature_sha256 <> OLD.signature_sha256",
                    "OR TRUE = FALSE",
                )
            )
        )
        self.assertFalse(
            schema_0018._event_guard_definition_exact(
                migration.replace(
                    "'accepted','processed','ignored','needs_manual'",
                    "'accepted','processed','ignored'",
                )
            )
        )

    def test_event_trigger_requires_enabled_row_before_update_binding(self):
        exact = {
            "tgname": "noteai_payment_event_identity_v1",
            "proname": "noteai_payment_event_identity_guard_v1",
            "tgenabled": "O",
            "tgtype": 19,
            "pronargs": 0,
            "return_type": "trigger",
        }
        self.assertTrue(schema_0018._event_trigger_row_exact(exact))
        for mutation in (
            {"tgenabled": "D"},
            {"tgtype": 21},
            {"tgtype": 17},
            {"pronargs": 1},
            {"return_type": "void"},
        ):
            with self.subTest(mutation=mutation):
                self.assertFalse(
                    schema_0018._event_trigger_row_exact(
                        {**exact, **mutation}
                    )
                )


if __name__ == "__main__":
    unittest.main()
