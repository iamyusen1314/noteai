"""Bounded container inspection preparation and status-polling checks."""
import copy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import unittest
from unittest import mock
import uuid
import os

from tools import item33_trends_runtime_cli as cli


def plan_fixture():
    identity = str(uuid.uuid4())
    return {"schema": "noteai.item33.runtime_plan.v1", "activation_id": identity,
        "activation_identity_sha256": cli.sha(identity.encode()), "operator_role": "noteai_admin",
        "accepted_source_sha256": dict(cli.controller.V5_RUNTIME_OVERLAY_SHA256),
        "image_config_sha256": cli.controller.V5_IMAGE_CONFIG_SHA256,
        "instrumentation_sha256": {**dict.fromkeys(cli.controller.V5_CAPTURE_TOOLS, "a" * 64),
            cli.controller.V5_CAPTURE_LAUNCHER_PATH: cli.sha(cli.controller.V5_CAPTURE_LAUNCHER)},
        "limits": {"initialization": 2, "collection": 34, "automatic_retry": 0, "cycles": 1},
        "bucket_key": "2026-09-19", "starts_at": "2026-09-19T01:00:00+00:00",
        "dispatch_before": "2026-09-19T01:35:00+00:00", "ends_at": "2026-09-19T02:30:00+00:00"}


class Cursor:
    def __init__(self, owner): self.owner = owner
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, statement, params=None): self.owner.sql.append((statement, params)); return self
    def fetchall(self): return next(self.owner.rows)


class Connection:
    autocommit = True
    info = SimpleNamespace(transaction_status=0)
    def __init__(self, rows): self.rows=iter(rows); self.sql=[]; self.rollbacks=0
    def cursor(self): return Cursor(self)
    def rollback(self): self.rollbacks += 1


class RuntimeCliTests(unittest.TestCase):
    def setUp(self): self.plan = plan_fixture()

    def test_instrumentation_does_not_replace_accepted_eight_sources(self):
        config = cli.initial_config(self.plan)
        self.assertEqual(config["accepted_source_sha256"], cli.controller.V5_RUNTIME_OVERLAY_SHA256)
        self.assertEqual(len(config["coverage"]), 14)
        self.assertEqual(config["catalog_before_sha256"], "0" * 64)
        self.assertIn("payment_reconciliation_runs", config["coverage"])
        self.plan["accepted_source_sha256"]["model/hot_keywords.py"] = "f" * 64
        with self.assertRaises(cli.RuntimeInspectionError): cli.initial_config(self.plan)

    def test_plan_rejects_item32_consumed_bucket_and_larger_budget(self):
        for key, value in (("limits", {"initialization":2,"collection":35,"automatic_retry":0,"cycles":1}),
                           ("bucket_key", "2026-09-18")):
            plan = copy.deepcopy(self.plan); plan[key] = value
            with self.subTest(key=key), self.assertRaises(cli.RuntimeInspectionError): cli.validate_plan(plan)

    def test_install_is_transactional_nonreplacing_and_window_bound(self):
        text = cli.render_install_sql(self.plan)
        self.assertTrue(text.startswith("BEGIN;\n") and text.endswith("COMMIT;\n"))
        self.assertEqual(text.count("CREATE TRIGGER"), 28)
        self.assertIn("item33 install window", text)
        self.assertNotIn("CREATE OR REPLACE", text)
        self.assertNotIn("GRANT ", text)
        self.assertNotIn("bucket_key=", text.split("public.xhs_trends_provider_attempts a",1)[1].split("JOIN",1)[0])

    def test_status_polling_waits_without_claim_mutation_or_provider_calls(self):
        conn = Connection([[], [("running",)], [("succeeded",)]])
        pauses = []
        count = cli.wait_for_success(conn, plan=self.plan, current=lambda:cli.clock(self.plan["starts_at"]), pause=pauses.append)
        self.assertEqual(count, 3); self.assertEqual(pauses, [30,30]); self.assertEqual(conn.rollbacks, 3)
        self.assertTrue(all(sql.startswith(("BEGIN READ ONLY", "SET LOCAL", "SELECT ")) for sql,_ in conn.sql))

    def test_failed_unknown_multiple_and_expired_stop_without_poll_retry(self):
        for rows in ([("failed",)], [("needs_manual",)], [("running",),("succeeded",)]):
            conn = Connection([rows]); pauses=[]
            with self.assertRaises(cli.RuntimeInspectionError):
                cli.wait_for_success(conn, plan=self.plan, current=lambda:cli.clock(self.plan["starts_at"]), pause=pauses.append)
            self.assertEqual(pauses, []); self.assertEqual(conn.rollbacks, 1)
        conn = Connection([])
        with self.assertRaises(cli.RuntimeInspectionError):
            cli.wait_for_success(conn, plan=self.plan, current=lambda:cli.clock(self.plan["ends_at"])+timedelta(seconds=1))
        self.assertEqual(conn.sql, [])

    def test_readonly_polling_is_bounded(self):
        conn = Connection([[]]*61); pauses=[]
        with self.assertRaisesRegex(cli.RuntimeInspectionError,"cycle_wait_deadline"):
            cli.wait_for_success(conn, plan=self.plan, current=lambda:cli.clock(self.plan["starts_at"]), pause=pauses.append)
        self.assertEqual(conn.rollbacks, 61); self.assertEqual(len(pauses), 60)


@unittest.skipUnless(os.environ.get("NOTEAI_LOCAL_PG16_ITEM33_TEST") == "1",
                     "explicit disposable network-none PG16 socket required")
class RuntimeCliPostgresTests(unittest.TestCase):
    def setUp(self):
        import psycopg
        from psycopg import sql
        from tests import test_item33_trends_capture_catalog as catalogs
        from tests import test_item33_trends_dml_capture as fixtures
        self.fixture=catalogs.CatalogPostgresTests("test_real_catalog_exact_definitions_acl_foreign_keys_and_no_xid")
        self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.owner=self.fixture.fx.owner; self.reader=self.fixture.reader
        for statement in fixtures.dml.removal_sql(fixtures.coverage()): self.owner.execute(statement)
        for name, target in cli.FORBIDDEN_TARGETS.items():
            old="item33_test_"+target.group
            if self.owner.execute("SELECT to_regclass(%s)",(name,)).fetchone()[0] is not None:
                self.owner.execute(sql.SQL("DROP TABLE {}").format(sql.Identifier(old)))
                continue
            self.owner.execute(sql.SQL("ALTER TABLE {} RENAME TO {}").format(sql.Identifier(old),sql.Identifier(name)))
            if target.key_columns!=("id",):
                self.owner.execute(sql.SQL("ALTER TABLE {} RENAME COLUMN id TO {}").format(sql.Identifier(name),sql.Identifier(target.key_columns[0])))
        self.owner.execute("DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='noteai_admin') "
                           "THEN CREATE ROLE noteai_admin LOGIN SUPERUSER; END IF; END $$")
        self.operator=psycopg.connect(**(fixtures.CONNECT|{"user":"noteai_admin"}),autocommit=True)
        self.addCleanup(self.operator.close)
        self.plan=plan_fixture();current=datetime.now(timezone.utc)
        self.plan.update(bucket_key=current.date().isoformat(),starts_at=(current-timedelta(minutes=1)).isoformat(),
            dispatch_before=(current+timedelta(minutes=35)).isoformat(),ends_at=(current+timedelta(minutes=89)).isoformat())

    def test_real_install_sql_and_actual_catalog_produce_bound_config_in_synthetic_local_window(self):
        # The test DB uses today's clock. Production's later-bucket policy is
        # independently tested above; no production plan or caller is patched.
        with mock.patch.object(cli,"validate_plan",side_effect=lambda value:value):
            prepared=cli.inspect("prepare-install",connection=self.reader,plan=self.plan)
            self.assertEqual(prepared["control_plane_ddl_count"],29)
            self.operator.execute(prepared["sql"])
            result=cli.inspect("finalize-config",connection=self.reader,plan=self.plan)
        self.assertEqual(result["state"],"CONFIGURATION_VERIFIED_NOT_RUNNING")
        self.assertNotEqual(result["config"]["catalog_before_sha256"],"0"*64)
        self.assertEqual(result["config_sha256"],cli.sha(cli.capture.encoded(result["config"])))
        self.assertEqual(self.reader.execute("SELECT count(*) FROM xhs_trends_runs").fetchone()[0],0)

    def test_actual_postgres_enforces_expired_install_window_without_partial_objects(self):
        self.plan["starts_at"]=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
        self.plan["dispatch_before"]=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
        with mock.patch.object(cli,"validate_plan",side_effect=lambda value:value): text=cli.render_install_sql(self.plan)
        with self.assertRaises(Exception): self.operator.execute(text)
        self.operator.rollback()
        self.assertEqual(self.reader.execute("SELECT count(*) FROM pg_proc WHERE proname=%s",(cli.dml.FUNCTION,)).fetchone()[0],0)


if __name__ == "__main__":
    unittest.main()
