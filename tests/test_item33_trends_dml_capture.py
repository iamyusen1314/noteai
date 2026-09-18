"""Pure checks plus opt-in disposable network-none PostgreSQL 16 socket tests."""

import copy
import hashlib
import json
import os
from pathlib import Path
import unittest
import uuid

import psycopg
from psycopg import sql

from tools import item33_trends_dml_capture as dml


ENABLED = os.environ.get("NOTEAI_LOCAL_PG16_ITEM33_TEST") == "1"
CONNECT = dict(host="/var/run/postgresql", dbname="noteai_item33_local", user="postgres")
ROOT = Path(__file__).resolve().parents[1]


def coverage():
    return {table: dml.TableTarget(keys) for table, keys in dml.TABLE_KEYS.items()} | {
        "item33_test_" + group: dml.TableTarget(("id",), group) for group in dml.FORBIDDEN_GROUPS
    }


class Item33DmlPreparationTests(unittest.TestCase):
    def test_sql_generation_is_separate_bounded_and_nonreplacing(self):
        activation = str(uuid.uuid4())
        statements = [item.as_string() for item in dml.installation_sql(activation, coverage())]
        self.assertEqual(len(statements), 2 + 2 * len(coverage()))
        joined = "\n".join(statements)
        self.assertIn("noteai_item33_trends_dml_notice", joined)
        self.assertNotIn("item31", joined)
        self.assertNotIn("CREATE OR REPLACE", joined)
        self.assertNotIn("SECURITY DEFINER", joined)
        self.assertIn("session_user", joined)
        self.assertEqual(len(dml.removal_sql(coverage())), 2 * len(coverage()) + 1)

    def test_missing_changed_or_unreviewed_key_fails(self):
        for change in ("missing", "changed", "extra_allowed", "unsafe", "mutable_list", "missing_group"):
            targets = coverage()
            if change == "missing":
                del targets["hot_keywords"]
            elif change == "changed":
                targets["hot_keywords"] = dml.TableTarget(("keyword",))
            elif change == "extra_allowed":
                targets["extra"] = dml.TableTarget(("id",))
            elif change == "unsafe":
                targets['bad;DROP TABLE x'] = dml.TableTarget(("id",), "out_of_contract")
            elif change == "mutable_list":
                targets["hot_keywords"] = dml.TableTarget(["id"])
            else:
                del targets["item33_test_payment"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                dml.installation_sql(str(uuid.uuid4()), targets)

    def test_partial_capture_cannot_claim_terminal_or_zero_ddl(self):
        activation = str(uuid.uuid4())
        result = dml.aggregate_records([], activation=activation, targets=coverage(), run_identity_sha256="a" * 64)
        self.assertEqual(result["status"], "UNKNOWN")
        self.assertFalse(result["readiness_credit"])
        self.assertNotIn("ddl_count", result)
        self.assertIn("business_ddl_count", result["unproven"])
        self.assertEqual(dml.cycle_contract_errors(result, request_count=1, keyword_count=72), ["capture_unknown"])


@unittest.skipUnless(ENABLED, "explicit disposable network-none PG16 socket required")
class Item33DmlPostgresTests(unittest.TestCase):
    def setUp(self):
        self.owner = psycopg.connect(**CONNECT, autocommit=True)
        version, address, database = self.owner.execute(
            "SELECT current_setting('server_version_num')::int,inet_server_addr(),current_database()"
        ).fetchone()
        self.assertTrue(160000 <= version < 170000)
        self.assertIsNone(address)
        self.assertEqual(database, "noteai_item33_local")
        self.owner.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public")
        self.owner.execute("DO $$ BEGIN IF NOT EXISTS(SELECT 1 FROM pg_roles WHERE rolname='noteai_xhs_trends') "
                           "THEN CREATE ROLE noteai_xhs_trends LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT; END IF; END $$")
        for name in ("0003_market_timing.sql", "0004_xhs_freshness.sql", "0011_trends_execution_contract.sql"):
            self.owner.execute((ROOT / "model/migrations/postgres" / name).read_text())
        self.targets = coverage()
        for table in self.targets.keys() - dml.TABLE_KEYS.keys():
            self.owner.execute(sql.SQL("CREATE TABLE {}(id bigint PRIMARY KEY,content text)").format(sql.Identifier(table)))
        self.owner.execute("GRANT USAGE ON SCHEMA public TO noteai_xhs_trends; "
                           "GRANT SELECT,INSERT,UPDATE,DELETE,TRUNCATE ON ALL TABLES IN SCHEMA public TO noteai_xhs_trends; "
                           "GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO noteai_xhs_trends")
        self.activation = str(uuid.uuid4())
        self.run_id = str(uuid.uuid4())
        self.run_hash = hashlib.sha256(self.run_id.encode()).hexdigest()
        self.install()
        self.listener = psycopg.connect(**CONNECT, autocommit=True)
        self.listener.execute(sql.SQL("LISTEN {}").format(sql.Identifier(dml.channel_for(self.activation))))
        self.writer = psycopg.connect(**(CONNECT | {"user": dml.WRITER_ROLE}), autocommit=True)
        self.records = []
        self.addCleanup(self.writer.close)
        self.addCleanup(self.listener.close)
        self.addCleanup(self.owner.close)

    def install(self):
        with self.owner.transaction():
            for statement in dml.installation_sql(self.activation, self.targets):
                self.owner.execute(statement)

    def begin(self, *, counted=False):
        self.writer.execute("BEGIN")
        nonce = str(uuid.uuid4())
        for statement in dml.binding_sql(self.activation, nonce, self.run_hash, mutation_counts=counted):
            cursor = self.writer.execute(statement)
        pid, txid = cursor.fetchone()
        binding = dict(nonce=nonce, run_identity_sha256=self.run_hash, pid=pid, txid=txid)
        self.records.append({"kind": "registered", **binding})
        return binding

    def commit(self, binding, *, counted=False):
        self.writer.execute(dml.completion_sql(self.activation, binding, mutation_counts=counted))
        self.writer.execute("COMMIT")
        # Test-only transport: actual sender PID comes from Notify, not payload.
        # The production continuous listener/registration/seal is not implemented here.
        received_commit = False
        for notification in self.listener.notifies(timeout=2):
            self.assertEqual(notification.channel, dml.channel_for(self.activation))
            record = json.loads(notification.payload)
            self.assertNotIn("sender_pid", record)
            record["sender_pid"] = notification.pid
            self.records.append(record)
            if record["kind"] == "commit":
                received_commit = True
                break
        self.assertTrue(received_commit)

    def result(self, records=None, *, counted=False):
        return dml.aggregate_records(self.records if records is None else records,
            activation=self.activation, targets=self.targets, run_identity_sha256=self.run_hash, require_mutation_count=counted)

    def claim(self):
        binding = self.begin()
        self.writer.execute("INSERT INTO xhs_trends_runs(id,bucket_key,status,lease_token_hash,lease_fence,"
            "lease_expires_at,started_at) VALUES(%s,'2026-09-17','running',%s,1,now()+interval '30 minutes',now())",
            (self.run_id, "b" * 64))
        self.writer.execute("UPDATE xhs_trends_service_state SET status='running',active_run_id=%s,"
            "lease_token_hash=%s,lease_fence=1,lease_expires_at=now()+interval '30 minutes',updated_at=now()",
            (self.run_id, "b" * 64))
        self.commit(binding)

    def attempt_sql(self):
        attempt = str(uuid.uuid4())
        self.writer.execute("INSERT INTO xhs_trends_provider_attempts(id,run_id,ordinal,endpoint,status,admitted_at,"
            "admitted_date) VALUES(%s,%s,1,'search_notes','admitted',now(),(now() AT TIME ZONE 'UTC')::date)",
            (attempt, self.run_id))
        self.writer.execute("UPDATE xhs_trends_provider_attempts SET status='succeeded',completed_at=now() WHERE id=%s", (attempt,))
        self.writer.execute("UPDATE xhs_trends_runs SET provider_attempt_count=1 WHERE id=%s", (self.run_id,))

    def publish(self, *, split=False, attempt_inside=False):
        binding = self.begin()
        if attempt_inside:
            self.attempt_sql()
        for ordinal in range(72):
            self.writer.execute("INSERT INTO hot_keywords(keyword,captured_at) VALUES(%s,'fixture-time')",
                                ("private-keyword-" + str(ordinal),))
            self.writer.execute("INSERT INTO keyword_snapshots(keyword,count,captured_at) VALUES(%s,1,'fixture-time')",
                                ("private-keyword-" + str(ordinal),))
        domains = ("美食", "旅行", "穿搭", "美妆", "家居", "健身")
        for domain in domains:
            self.writer.execute("INSERT INTO xhs_crawler_health(id,run_id,adapter,domain,status,checked_at,details_json) "
                "VALUES(%s,%s,'spider_xhs_http',%s,'ok','fixture-time','private-content')",
                (str(uuid.uuid4()), self.run_id, domain))
            self.writer.execute("INSERT INTO xhs_freshness_ledger(id,domain,evidence_date,source,status,acquired_at,"
                "fresh_until,last_run_id) VALUES(%s,%s,'2026-09-17','search_notes','ok','fixture-time','fixture-future',%s)",
                (str(uuid.uuid4()), domain, self.run_id))
        if split:
            self.commit(binding)
            binding = self.begin()
        payload = json.dumps({"schema_version": 1, "domains": {
            domain: {"keywords": [{} for _ in range(12)]} for domain in domains}}, separators=(",", ":"))
        digest = hashlib.sha256(payload.encode()).hexdigest()
        self.writer.execute("INSERT INTO xhs_trends_snapshot_evidence(run_id,schema_version,snapshot_sha256,snapshot_size,"
            "keyword_count,domain_counts_json,payload_json,created_at) VALUES(%s,1,%s,%s,72,%s::jsonb,%s,now())",
            (self.run_id, digest, len(payload.encode()), json.dumps(dict.fromkeys(domains, 12)), payload))
        self.writer.execute("UPDATE xhs_trends_runs SET status='succeeded',completed_at=now(),snapshot_sha256=%s,"
                            "snapshot_size=%s WHERE id=%s", (digest, len(payload.encode()), self.run_id))
        self.writer.execute("UPDATE xhs_trends_service_state SET status='idle',active_run_id=NULL,lease_token_hash=NULL,"
                            "lease_expires_at=NULL,updated_at=now()")
        self.commit(binding)

    def full_cycle(self, **publish_options):
        self.claim()
        if not publish_options.get("attempt_inside"):
            binding = self.begin()
            self.attempt_sql()
            self.commit(binding)
        self.publish(**publish_options)

    def enable_counted(self):
        for statement in dml.removal_sql(self.targets): self.owner.execute(statement)
        for statement in dml.installation_sql(self.activation, self.targets, mutation_counts=True): self.owner.execute(statement)

    def test_counted_commit_detects_one_lost_mutation_and_duplicate_or_false_count(self):
        self.enable_counted(); binding = self.begin(counted=True)
        self.writer.execute("INSERT INTO hot_keywords(keyword,captured_at) VALUES('hidden','time')")
        self.writer.execute("UPDATE hot_keywords SET search_vol=1")
        self.commit(binding, counted=True)
        self.assertEqual(self.records[-1]["mutation_count"], 2)
        self.assertEqual(self.result(counted=True)["status"], "ROW_CAPTURE_AGGREGATED_NOT_TERMINAL")
        for defect in ("lost", "duplicate", "bool", "wrong", "missing"):
            rows = copy.deepcopy(self.records)
            if defect == "lost": rows.pop(1)
            elif defect == "duplicate": rows.insert(1, copy.deepcopy(rows[1]))
            elif defect == "bool": rows[-1]["mutation_count"] = True
            elif defect == "missing": rows[-1].pop("mutation_count")
            else: rows[-1]["mutation_count"] = 1
            with self.subTest(defect=defect): self.assertEqual(self.result(rows, counted=True)["status"], "UNKNOWN")

    def test_counted_savepoint_and_outer_rollback_keep_only_committed_count(self):
        self.enable_counted(); binding = self.begin(counted=True)
        self.writer.execute("INSERT INTO hot_keywords(keyword,captured_at) VALUES('keep','time')")
        self.writer.execute("SAVEPOINT discard")
        self.writer.execute("UPDATE hot_keywords SET search_vol=9")
        self.writer.execute("ROLLBACK TO SAVEPOINT discard")
        self.commit(binding, counted=True)
        self.assertEqual(self.records[-1]["mutation_count"], 1)
        binding = self.begin(counted=True)
        self.writer.execute("UPDATE hot_keywords SET search_vol=8")
        self.writer.execute("ROLLBACK")
        self.records.append({"kind": "rollback", **binding})
        self.assertEqual(list(self.listener.notifies(timeout=.05)), [])
        self.assertEqual(self.result(counted=True)["write_mutations_by_table"], {"hot_keywords": 1})

    def test_real_schema_counts_distinct_rows_and_atomic_transaction(self):
        self.full_cycle()
        result = self.result()
        self.assertEqual(dml.cycle_contract_errors(result, request_count=1, keyword_count=72), [])
        self.assertEqual(result["distinct_rows_touched_by_table"]["xhs_trends_runs"], 1)
        self.assertEqual(result["write_mutations_by_table"]["xhs_trends_runs"], 3)
        self.assertEqual(result["distinct_rows_touched_by_table"]["xhs_trends_provider_attempts"], 1)
        self.assertEqual(result["write_mutations_by_table"]["xhs_trends_provider_attempts"], 2)
        self.assertEqual(len(result["transactions"]), 3)
        raw = json.dumps(self.records)
        self.assertNotIn("private-keyword", raw)
        self.assertNotIn("private-content", raw)
        self.assertNotIn(self.run_id, raw)
        self.assertNotIn("ddl_count", result)
        self.assertFalse(result["readiness_credit"])

    def test_split_publish_is_not_atomic(self):
        self.full_cycle(split=True)
        self.assertIn("atomic_publish", dml.cycle_contract_errors(self.result(), request_count=1, keyword_count=72))

    def test_missing_duplicate_row_mutation_cannot_be_detected_by_counts_alone(self):
        self.full_cycle()
        records = copy.deepcopy(self.records)
        index = next(index for index, row in enumerate(records) if row.get("table") == "xhs_trends_provider_attempts"
                     and row.get("op") == "UPDATE")
        records.pop(index)
        result = self.result(records)
        # A terminal proof must supply the independent continuous journal/source
        # binding: distinct rows and txids alone cannot detect this missing row.
        self.assertEqual(dml.cycle_contract_errors(result, request_count=1, keyword_count=72), [])
        self.assertEqual(result["status"], "ROW_CAPTURE_AGGREGATED_NOT_TERMINAL")
        self.assertIn("all_writer_registration_and_stream_continuity", result["unproven"])
        self.assertFalse(result["readiness_credit"])

    def test_attempt_audit_inside_publish_is_rejected(self):
        self.full_cycle(attempt_inside=True)
        result = self.result()
        self.assertTrue(result["atomic_publish"]["business_pack_snapshot_run_success_one_transaction"])
        self.assertFalse(result["atomic_publish"]["attempt_audit_outside_transaction"])

    def test_savepoint_and_outer_rollback_emit_no_discarded_rows(self):
        binding = self.begin()
        self.writer.execute("INSERT INTO hot_keywords(keyword,captured_at) VALUES('keep','time')")
        self.writer.execute("SAVEPOINT discard")
        self.writer.execute("INSERT INTO hot_keywords(keyword,captured_at) VALUES('discard','time')")
        self.writer.execute("UPDATE hot_keywords SET search_vol=99")
        self.writer.execute("ROLLBACK TO SAVEPOINT discard")
        self.commit(binding)
        binding = self.begin()
        self.writer.execute("UPDATE hot_keywords SET search_vol=100")
        self.writer.execute("ROLLBACK")
        self.records.append({"kind": "rollback", **binding})
        self.assertEqual(list(self.listener.notifies(timeout=0.05)), [])
        result = self.result()
        self.assertEqual(result["write_mutations_by_table"], {"hot_keywords": 1})
        self.assertEqual(result["distinct_rows_touched_by_table"]["hot_keywords"], 1)

    def test_key_change_delete_truncate_and_nested_forbidden_write_visible(self):
        self.owner.execute("CREATE FUNCTION item33_fixture_nested() RETURNS trigger LANGUAGE plpgsql AS $$ "
            "BEGIN INSERT INTO item33_test_payment VALUES(NEW.id,'hidden-side-effect'); RETURN NEW; END $$;"
            "CREATE TRIGGER item33_fixture_nested AFTER INSERT ON hot_keywords "
            "FOR EACH ROW EXECUTE FUNCTION item33_fixture_nested()")
        binding = self.begin()
        self.writer.execute("INSERT INTO hot_keywords(id,keyword,captured_at) VALUES(1,'hidden','time')")
        self.writer.execute("UPDATE hot_keywords SET id=2 WHERE id=1")
        self.writer.execute("DELETE FROM hot_keywords WHERE id=2")
        self.writer.execute("TRUNCATE hot_keywords")
        self.commit(binding)
        result = self.result()
        self.assertEqual(result["distinct_rows_touched_by_table"]["hot_keywords"], 2)
        self.assertEqual(result["write_mutations_by_table"]["hot_keywords"], 4)
        self.assertEqual(result["delete_rows"], 1)
        self.assertEqual(result["truncate_count"], 1)
        self.assertEqual(result["forbidden_table_mutations"]["payment"], 1)
        self.assertEqual(result["out_of_contract_row_mutations"], 2)
        self.assertNotIn("hidden", json.dumps(self.records))

    def test_wrong_run_and_wrong_transaction_are_rejected_or_reported(self):
        binding = self.begin()
        self.writer.execute("INSERT INTO xhs_trends_runs(id,bucket_key,status,lease_token_hash,lease_fence,"
            "lease_expires_at,started_at) VALUES(%s,'2026-09-17','running',%s,1,now()+interval '30 minutes',now())",
            (str(uuid.uuid4()), "b" * 64))
        self.commit(binding)
        self.assertEqual(self.result()["out_of_contract_row_mutations"], 1)
        binding = self.begin()
        wrong = dict(binding, txid=str(int(binding["txid"]) + 1))
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "writer transaction changed"):
            self.writer.execute(dml.completion_sql(self.activation, wrong))
        self.writer.execute("ROLLBACK")

    def test_missing_activation_or_transaction_cannot_write(self):
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "binding missing"):
            self.writer.execute("INSERT INTO hot_keywords(keyword,captured_at) VALUES('blocked','time')")
        self.assertEqual(self.owner.execute("SELECT count(*) FROM hot_keywords").fetchone()[0], 0)
        self.assertEqual(list(self.listener.notifies(timeout=0.05)), [])

    def test_schema_guard_and_duplicate_install_fail_without_replacement(self):
        function_before = self.owner.execute("SELECT pg_get_functiondef('public.noteai_item33_trends_dml_notice()'::regprocedure)").fetchone()[0]
        with self.assertRaises(psycopg.errors.DuplicateFunction):
            self.install()
        self.assertEqual(self.owner.execute("SELECT pg_get_functiondef('public.noteai_item33_trends_dml_notice()'::regprocedure)").fetchone()[0], function_before)
        self.owner.execute("ALTER TABLE hot_keywords DROP CONSTRAINT hot_keywords_pkey")
        with self.assertRaisesRegex(psycopg.errors.RaiseException, "primary key shape"):
            self.owner.execute(dml.schema_guard_sql(self.targets))

    def test_missing_duplicate_spoofed_or_unregistered_records_remain_unknown(self):
        self.claim()
        mutation_index = next(index for index, row in enumerate(self.records) if row["kind"] == "mutation")
        for defect in ("missing_commit", "duplicate", "sender", "txid", "coverage", "content", "unregistered", "after_commit"):
            rows = copy.deepcopy(self.records)
            if defect == "missing_commit":
                rows.pop()
            elif defect == "duplicate":
                rows.insert(mutation_index, copy.deepcopy(rows[mutation_index]))
            elif defect == "sender":
                rows[mutation_index]["sender_pid"] += 1
            elif defect == "txid":
                rows[mutation_index]["txid"] = "999999"
            elif defect == "coverage":
                rows[mutation_index]["coverage_sha256"] = "f" * 64
            elif defect == "content":
                rows[mutation_index]["raw_content"] = "never accepted"
            elif defect == "unregistered":
                rows.pop(0)
            else:
                rows.append(rows[mutation_index])
            with self.subTest(defect=defect):
                self.assertEqual(self.result(rows)["status"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
