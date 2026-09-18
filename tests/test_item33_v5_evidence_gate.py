"""Managed V5 evidence inherits accepted Item32; no provider or database IO."""
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import shutil
import unittest
from unittest import mock
import uuid

from tests import test_item33_trends_evidence_gate as legacy
from tests import test_item32_source_retention_evidence_gate as accepted
from tools import item33_trends_http_readback as http_reader
from tools import item33_trends_runtime_capture as capture
from tools import item33_trends_dml_capture as dml

gate = legacy.gate


def shift_day(value, before="2026-09-08", after="2026-09-19"):
    if isinstance(value, dict):
        return {key: shift_day(item, before, after) for key, item in value.items()}
    if isinstance(value, list):
        return [shift_day(item, before, after) for item in value]
    if isinstance(value, str) and value.startswith(before):
        return value.replace(before, after, 1)
    return value


class Item33V5EvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.f = f = legacy.Item33TrendsEvidenceGateTests()
        f.setUp()
        self.addCleanup(f.tearDown)
        item32 = accepted.SourceRetentionEvidenceTests()
        item32.setUp()
        self.addCleanup(item32.doCleanups)
        self.assertEqual(item32.validate(), [])
        shutil.copytree(item32.f.root, f.root, dirs_exist_ok=True)
        f.payload = shift_day(f.payload)
        f.rewrite_snapshot(lambda snapshot: snapshot.update(shift_day(snapshot)))
        self.payload, self.root = f.payload, f.root
        sources = dict(gate.ITEM33_V5_RUNTIME_OVERLAY_SHA256)
        f.payload["release_binding"].update(
            source_sha256={**gate.ITEM32_IMAGE_SOURCE_SHA256, **sources},
            image_config_sha256=gate.ITEM32_V5_CONFIG_SHA256,
            registry_manifest_sha256=gate.ITEM32_V5_MANIFEST_SHA256,
            promoted_unit_sha256=gate.ITEM33_V5_PROMOTED_UNIT_SHA256,
            image_source_sha256=dict(gate.ITEM32_IMAGE_SOURCE_SHA256),
            runtime_overlay_sha256=sources,
            item32_terminal_sha256=hashlib.sha256(
                (f.root / gate.ITEM32_TRENDS_EVIDENCE).read_bytes()).hexdigest(),
        )
        f.payload["recovery"]["reapplied_promoted_unit_sha256"] = gate.ITEM33_V5_PROMOTED_UNIT_SHA256
        f.payload["promotion"]["argv"] = ["/app/scripts/render_run_market_timing.sh"]
        physical = copy.deepcopy(item32.f.attempt_payload["physical_http"])
        events = physical["observations"]
        base = datetime(2026, 9, 19, 0, 5, tzinfo=timezone.utc)
        for index, event in enumerate(events):
            event["at"] = (base + timedelta(milliseconds=500 * index)).isoformat()
        attempts = f.payload["cycle"]["attempts"]
        for index, attempt in enumerate(attempts):
            dispatch, response = events[4 + index * 2:6 + index * 2]
            attempt.update(endpoint=dispatch["request_kind"], admitted_at=dispatch["at"],
                           completed_at=response["at"])
        f.payload["cycle"]["physical_http"] = physical
        f.payload["cost"].update(xhs_provider_requests=36, provider_fee_fen="UNKNOWN",
                                incremental_cloud_cost_fen="UNKNOWN")
        self.bind_http_receipt()
        self.bind_capture(terminal_proof=True)
        self.bind_normal_handoff()

    def bind_capture(self, *, catalog_proof=None, config_fields=None, terminal_proof=False):
        """Two synthetic counted transactions, not claimed production evidence."""
        cycle = self.payload["cycle"]
        activation = "b4cba5a6-737e-4b83-8f5f-e88d37c5a317"
        activation_hash = hashlib.sha256(activation.encode()).hexdigest()
        cycle["activation_identity_sha256"] = activation_hash
        sources = {}
        for name in gate.ITEM33_V5_CAPTURE_TOOLS:
            raw = (legacy.ROOT / name).read_bytes()
            target = self.root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(raw)
            sources[name] = hashlib.sha256(raw).hexdigest()
        targets = {table: dml.TableTarget(keys) for table, keys in dml.TABLE_KEYS.items()} | {
            "test_" + group: dml.TableTarget(("id",), group) for group in dml.FORBIDDEN_GROUPS}
        config = {"schema": capture.CONFIG_SCHEMA, "activation_id": activation,
            "activation_identity_sha256": activation_hash, "bucket_key": cycle["bucket_key"],
            "socket_path": capture.SOCKET_PATH, "accepted_source_sha256": dict(gate.ITEM33_V5_RUNTIME_OVERLAY_SHA256),
            "instrumentation_sha256": {**sources, "scripts/render_run_market_timing.sh": gate.ITEM33_V5_LAUNCHER_SHA256},
            "coverage": dml._coverage(targets), "coverage_sha256": dml.coverage_sha256(targets),
            "catalog_before_sha256": "c" * 64, "installed_definition_sha256": "d" * 64}
        config.update(config_fields or {})
        if terminal_proof:
            from tests import test_item33_trends_capture_catalog as catalog_tests
            from tools import item33_trends_capture_catalog as catalog
            with mock.patch.object(catalog_tests, "datetime") as clock:
                clock.now.return_value = datetime(2026, 9, 19, tzinfo=timezone.utc)
                catalog_proof = catalog_tests.catalog_fixture(config)
            catalog_proof["after"]["observed_at"] = "2026-09-19T00:35:00+00:00"
            source = (legacy.ROOT / catalog.SOURCE_REF).read_bytes()
            (self.root / catalog.SOURCE_REF).write_bytes(source)
            catalog_proof["source_sha256"] = hashlib.sha256(source).hexdigest()
        targets = {table: dml.TableTarget(tuple(item["key_columns"]), item["group"])
                   for table, item in config["coverage"].items()}
        events = [{"kind": "capture_start", "activation_id": activation,
                   "configuration_sha256": capture.sha(capture.encoded(config)), "bucket_key": cycle["bucket_key"]},
                  {"kind": "barrier", "activation_id": activation, "phase": "start", "nonce": str(uuid.uuid4()), "sender_pid": 1}]
        records = []
        def transaction(number, rows):
            binding = {"nonce": str(uuid.uuid4()), "run_identity_sha256": cycle["run_identity_sha256"],
                       "pid": 2, "txid": str(number)}
            records.append({"kind": "registered", **binding})
            for table, key, operation, succeeded in rows:
                row_hash = legacy.digest(table + str(key))
                records.append({"kind": "mutation", **binding, "sender_pid": 2, "activation": activation,
                    "coverage_sha256": config["coverage_sha256"], "event_id": str(uuid.uuid4()), "table": table,
                    "op": operation, "old_row_sha256": row_hash if operation == "UPDATE" else None,
                    "new_row_sha256": row_hash, "scope_violation": False, "run_succeeded": succeeded})
            records.append({"kind": "commit", **binding, "sender_pid": 2, "mutation_count": len(rows)})
        first = [("xhs_trends_runs", 0, "INSERT", False), ("xhs_trends_service_state", 0, "UPDATE", False)]
        first += [("xhs_trends_provider_attempts", index, operation, False) for index in range(34)
                  for operation in ("INSERT", "UPDATE")]
        transaction(10, first)
        second = [(table, index, "INSERT", False) for table, count in (
            ("hot_keywords", 90), ("keyword_snapshots", 90), ("xhs_crawler_health", 6),
            ("xhs_freshness_ledger", 6), ("xhs_trends_snapshot_evidence", 1)) for index in range(count)]
        transaction(11, second + [("xhs_trends_runs", 0, "UPDATE", True)])
        events += records + [{"kind": "admission_closed", "activation_id": activation},
            {"kind": "barrier", "activation_id": activation, "phase": "end", "nonce": str(uuid.uuid4()), "sender_pid": 1}]
        previous, lines = "0" * 64, []
        for index, event in enumerate(events, 1):
            row = {"sequence": index, "previous_sha256": previous, "event": event}
            row["sha256"] = previous = capture.sha(capture.encoded(row))
            lines.append(capture.encoded(row) + b"\n")
        raw = b"".join(lines)
        aggregate = dml.aggregate_records(records, activation=activation, targets=targets,
            run_identity_sha256=cycle["run_identity_sha256"], require_mutation_count=True)
        self.assertEqual(dml.cycle_contract_errors(aggregate, request_count=34, keyword_count=90), [])
        seal = {"schema": capture.SEAL_SCHEMA, "state": "CAPTURE_SEALED_NOT_TERMINAL",
            "activation_id": activation, "activation_identity_sha256": activation_hash,
            "run_identity_sha256": cycle["run_identity_sha256"], "bucket_key": cycle["bucket_key"],
            "config_sha256": capture.sha(capture.encoded(config)), **{key: config[key] for key in (
                "accepted_source_sha256", "instrumentation_sha256", "coverage_sha256", "catalog_before_sha256",
                "installed_definition_sha256", "coverage")},
            "journal": {"ref": gate.ITEM33_V5_CAPTURE_JOURNAL, "bytes": len(raw), "sha256": capture.sha(raw),
                        "record_count": len(lines), "last_chain_sha256": previous},
            "stream": {"start_barrier_received": True, "end_barrier_received": True, "disconnect_count": 0, "invalid_count": 0},
            "writers": {"registered": 2, "committed": 2, "rolled_back": 0, "admission_closed": True, "all_closed": True},
            "counted_commits": True, "single_bucket_only": True, "readiness_credit": False,
            "aggregate": aggregate, "catalog_proof": catalog_proof}
        self.assertEqual(capture.verify_capture_artifacts(seal, raw, require_terminal_proofs=terminal_proof), aggregate)
        (self.root / gate.ITEM33_V5_CAPTURE_JOURNAL).write_bytes(raw)
        seal_bytes = capture.encoded(seal) + b"\n"
        (self.root / gate.ITEM33_V5_CAPTURE_EVIDENCE).write_bytes(seal_bytes)
        self.payload["release_binding"]["capture_binding"] = {"source_sha256": sources,
            "launcher_sha256": gate.ITEM33_V5_LAUNCHER_SHA256, "configuration_sha256": seal["config_sha256"],
            "activation_identity_sha256": activation_hash, "receipt_ref": gate.ITEM33_V5_CAPTURE_EVIDENCE,
            "receipt_sha256": capture.sha(seal_bytes)}
        return seal, raw, config

    def bind_normal_handoff(self):
        cycle = self.payload["cycle"]
        capture_sha = self.payload["release_binding"]["capture_binding"]["receipt_sha256"]
        from tools import item33_trends_capture_teardown as removal
        from tools import item33_trends_capture_catalog as catalog
        seal_raw = (self.root / gate.ITEM33_V5_CAPTURE_EVIDENCE).read_bytes()
        seal = json.loads(seal_raw)
        journal = (self.root / gate.ITEM33_V5_CAPTURE_JOURNAL).read_bytes()
        source = (legacy.ROOT / removal.SOURCE_REF).read_bytes()
        (self.root / removal.SOURCE_REF).write_bytes(source)
        after = copy.deepcopy(seal["catalog_proof"]["after"])
        after["catalog"] = removal._without_capture(after["catalog"])
        after["catalog_sha256"] = catalog.digest(after["catalog"])
        after["observed_at"] = "2026-09-19T00:35:45+00:00"
        script = removal.render_teardown_sql(seal=seal, journal=journal, operator_role="noteai_operator")
        execution = {"schema": removal.EXECUTION_SCHEMA, "status": "COMMITTED",
            "activation_identity_sha256": cycle["activation_identity_sha256"], "operator_role": "noteai_operator",
            "sql_sha256": hashlib.sha256(script.encode()).hexdigest(), "started_at": "2026-09-19T00:35:01+00:00",
            "committed_at": "2026-09-19T00:35:30+00:00", "control_plane_ddl_count": 2 * len(seal["coverage"]) + 1,
            "outcome_unknown_count": 0}
        proof = removal.build_teardown_proof(seal_raw=seal_raw, journal=journal, after=after,
            execution=execution, source_sha256=hashlib.sha256(source).hexdigest())
        proof_raw = removal.encoded(proof) + b"\n"
        (self.root / gate.ITEM33_V5_CAPTURE_TEARDOWN).write_bytes(proof_raw)
        common = {"activation_identity_sha256": cycle["activation_identity_sha256"],
            "run_identity_sha256": cycle["run_identity_sha256"], "bucket_key": cycle["bucket_key"],
            "capture_receipt_sha256": capture_sha, "teardown_sha256": hashlib.sha256(proof_raw).hexdigest()}
        start, finish, observed = [f"2026-09-19T00:{minute}:00+00:00" for minute in (36, 37, 38)]
        action = {"phase": "normal_handoff", "status": "APPLIED_REQUIRES_STATE_READBACK", **common,
            "before_unit_sha256": gate.ITEM33_V5_PROMOTED_UNIT_SHA256,
            "after_unit_sha256": gate.ITEM33_V5_NORMAL_UNIT_SHA256, "observed_at": start, "completed_at": finish}
        same_bucket = {"bucket_key": cycle["bucket_key"], "new_run_delta": 0, "provider_call_delta": 0}
        readback = {"schema": "noteai.item33.normal_readback.v1", **common, "observed_at": observed,
            "unit_sha256": gate.ITEM33_V5_NORMAL_UNIT_SHA256, "same_bucket": same_bucket,
            "preserved": copy.deepcopy(self.payload["recovery"]["preserved"]),
            "final": copy.deepcopy(self.payload["recovery"]["final"]), "secret_values_recorded": False}
        hashes = []
        for ref, value in ((gate.ITEM33_V5_NORMAL_ACTION, action), (gate.ITEM33_V5_NORMAL_READBACK, readback)):
            raw = (json.dumps(value, sort_keys=True, indent=2) + "\n").encode()
            (self.root / ref).write_bytes(raw); hashes.append(hashlib.sha256(raw).hexdigest())
        self.payload["normal_handoff"] = {"status": "VERIFIED", "started_at": start, "completed_at": finish,
            "observed_at": observed, **{key: value for key, value in common.items() if key != "bucket_key"},
            "before_unit_sha256": gate.ITEM33_V5_PROMOTED_UNIT_SHA256, "normal_unit_sha256": gate.ITEM33_V5_NORMAL_UNIT_SHA256,
            "image_config_sha256": gate.ITEM32_V5_CONFIG_SHA256, "runtime_overlay_sha256": dict(gate.ITEM33_V5_RUNTIME_OVERLAY_SHA256),
            "mutation_count": 1, "other_unit_actions": 0, "restart_policy": "no", "same_bucket": same_bucket,
            "preserved": readback["preserved"], "final": readback["final"],
            "action_ref": gate.ITEM33_V5_NORMAL_ACTION, "action_sha256": hashes[0],
            "readback_ref": gate.ITEM33_V5_NORMAL_READBACK, "readback_sha256": hashes[1]}
        self.payload["normal_handoff"].update(teardown_ref=gate.ITEM33_V5_CAPTURE_TEARDOWN,
                                               teardown_sha256=hashlib.sha256(proof_raw).hexdigest())
        capture_common = {"activation_identity_sha256": cycle["activation_identity_sha256"],
            "configuration_sha256": seal["config_sha256"], "bucket_key": cycle["bucket_key"]}
        service = {"schema": "noteai.item33.capture_service_result.v1", "state": "SEALED", **capture_common,
            "observed_at": "2026-09-19T00:35:00.200000+00:00", "run_identity_sha256": cycle["run_identity_sha256"],
            "capture_seal_sha256": capture_sha, "provider_calls": 0, "schema_changes": 0, "secret_values_recorded": False}
        closed = {**capture_common, "state": "CONNECTIONS_CLOSED", "connection_count": 3,
            "observed_at": "2026-09-19T00:35:00.500000+00:00", "secret_values_recorded": False}
        host = {"schema": "noteai.item33.host_facts.v1", "phase": "normal", "host": "noteai-api-f",
            "observed_at": observed, "activation_identity_sha256": cycle["activation_identity_sha256"],
            "unit_sha256": gate.ITEM33_V5_NORMAL_UNIT_SHA256, "unit_active": "active", "unit_sub": "running",
            "unit_enabled": "enabled", "collection_suspended": False, "startup_healthcheck_succeeded": True,
            "capture_service_failure_present": False, "secret_values_recorded": False,
            **{key: 1 for key in ("formal_unit_count", "formal_container_count", "process_count")},
            **{key: 0 for key in ("capture_container_count", "task_container_count", "inspection_container_count",
                "runtime_directory_count", "stage_directory_count", "temporary_unit_count", "temporary_dropin_count",
                "observation_provider_calls", "observation_database_connections", "observation_mutations")}}
        host["canonical_sha256"] = hashlib.sha256(json.dumps(host, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        self.payload["normal_handoff"]["capture_close"] = self.save_capture_close({"service_result": service,
            "close": closed, "host": host})
        readback["capture_close"] = copy.deepcopy(self.payload["normal_handoff"]["capture_close"])
        readback_raw = (json.dumps(readback, sort_keys=True, indent=2) + "\n").encode()
        (self.root / gate.ITEM33_V5_NORMAL_READBACK).write_bytes(readback_raw)
        self.payload["normal_handoff"]["readback_sha256"] = hashlib.sha256(readback_raw).hexdigest()

    def save_capture_close(self, values):
        bindings = {}
        for name, ref in gate.ITEM33_V5_CAPTURE_CLOSE_REFS.items():
            raw = (json.dumps(values[name], sort_keys=True, indent=2) + "\n").encode()
            (self.root / ref).write_bytes(raw)
            bindings[name + "_ref"] = ref
            bindings[name + "_sha256"] = hashlib.sha256(raw).hexdigest()
        return bindings

    def bind_http_receipt(self):
        cycle = self.payload["cycle"]
        run_id = "synthetic-item33-v5-run"
        cycle["run_identity_sha256"] = hashlib.sha256(run_id.encode()).hexdigest()
        identity = {"run_id": run_id, "bucket_key": cycle["bucket_key"]}
        rows = [{"event": "trends_run_started", **identity, "status": "running"}]
        rows.extend({"event": "xhs_trends_http_observation", **row} for row in cycle["physical_http"]["observations"])
        rows.extend(({"event": "trends_run_succeeded", **identity, "status": "succeeded", "provider_calls": 34},
                     {"ok": True, **identity, "provider_calls": 34}))
        result = http_reader.read_http_facts(b"\n".join(json.dumps(row).encode() for row in rows),
            cycle=cycle, observed_at=datetime(2026, 9, 19, 1, tzinfo=timezone.utc))
        self.assertTrue(result["physical_http_verified"])
        cycle["physical_http"] = result["physical_http"]
        (self.root / gate.ITEM33_V5_HTTP_RECEIPT).write_bytes(http_reader.encoded(result["worker_receipt"]))

    def validate(self):
        self.f.path.write_text(json.dumps(self.payload, ensure_ascii=False), encoding="utf-8")
        return gate.validate_item33_trends_promotion_evidence(
            self.f.control, root=self.root, now=datetime(2026, 9, 20, tzinfo=timezone.utc))

    def test_accepts_full_v5_with_real_physical_counts_and_unknown_fees(self):
        self.assertEqual(self.validate(), [])

    def test_frozen_image_and_all_eight_effective_sources_remain_distinct(self):
        original = copy.deepcopy(self.payload["release_binding"])
        for field, value in (
            ("image_config_sha256", gate.ITEM32_EXPECTED_CONFIG_SHA256),
            ("registry_manifest_sha256", "e" * 64),
            ("image_source_sha256", original["runtime_overlay_sha256"]),
            ("runtime_overlay_sha256", gate.ITEM32_RUNTIME_OVERLAY_SHA256),
            ("source_sha256", gate.ITEM32_EFFECTIVE_SOURCE_SHA256),
            ("promoted_unit_sha256", gate.ITEM33_EFFECTIVE_PROMOTED_UNIT_SHA256),
            ("item32_terminal_sha256", "f" * 64),
        ):
            with self.subTest(field=field):
                self.payload["release_binding"] = {**copy.deepcopy(original), field: value}
                self.assertIn("Item33 release binding mismatch", self.validate())

    def test_full_accepted_item32_is_required_not_only_matching_source_hash(self):
        path = self.root / gate.ITEM32_TRENDS_EVIDENCE
        item32 = json.loads(path.read_text())
        item32["status"], item32["readiness_credit"] = "HOLD", False
        path.write_text(json.dumps(item32))
        self.payload["release_binding"]["item32_terminal_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertIn("Item33 release binding mismatch", self.validate())

    def test_physical_summary_is_not_a_substitute_for_all_paired_events(self):
        original = copy.deepcopy(self.payload["cycle"]["physical_http"])
        for field, value in (("initialization_count", 0), ("collection_count", True),
                             ("total_count", 34), ("automatic_retry_count", False),
                             ("observations", original["observations"][:-1])):
            with self.subTest(field=field):
                self.payload["cycle"]["physical_http"] = {**copy.deepcopy(original), field: value}
                self.assertIn("Item33 V5 physical HTTP evidence mismatch", self.validate())

    def test_unknown_or_reused_item32_clock_cannot_credit_managed_http(self):
        events = self.payload["cycle"]["physical_http"]["observations"]
        original = copy.deepcopy(events[5])
        for field, value in (("phase", "unknown"), ("at", "2026-09-18T11:30:17+00:00"),
                             ("sequence", 4), ("request_kind", "search_notes")):
            with self.subTest(field=field):
                events[5] = {**copy.deepcopy(original), field: value}
                self.assertIn("Item33 V5 physical HTTP evidence mismatch", self.validate())

    def test_recommendation_1000_needs_its_own_usable_count(self):
        diag = self.payload["cycle"]["physical_http"]["observations"][25]["response_diagnostics"]
        diag.update(business_code=1000, business_code_kind="integer",
                    recommendation_items_total=10, recommendation_items_usable=10)
        self.bind_http_receipt()
        self.assertEqual(self.validate(), [])
        self.payload["cycle"]["physical_http"]["observations"][25]["response_diagnostics"]["recommendation_items_usable"] = 0
        self.assertIn("Item33 V5 physical HTTP evidence mismatch", self.validate())

    def test_attempt_ledger_and_initialization_cost_are_both_required(self):
        self.payload["cycle"]["attempts"][10]["endpoint"] = "search_notes"
        self.assertIn("Item33 V5 physical HTTP evidence mismatch", self.validate())
        self.payload["cost"]["xhs_provider_requests"] = 34
        self.assertIn("Item33 cost/resource boundary mismatch", self.validate())

    def test_database_zero_cannot_reuse_item32_utc_bucket(self):
        self.f.payload = self.payload = shift_day(self.payload, "2026-09-19", "2026-09-18")
        self.f.rewrite_snapshot(lambda snapshot: snapshot.update(shift_day(snapshot, "2026-09-19", "2026-09-18")))
        self.assertIn("Item33 UTC budget overlaps Item32 terminal cycle", self.validate())

    def test_reapply_cannot_start_a_new_bucket(self):
        self.payload["recovery"]["reapplied_at"] = "2026-09-20T00:00:00+00:00"
        self.assertIn("Item33 Trends-only rollback/no-replay mismatch", self.validate())

    def test_complete_http_does_not_relax_quality_or_eight_table_dml(self):
        self.f.rewrite_snapshot(lambda snapshot: snapshot["domains"]["美食"]["keywords"][0].update(quality_score=54))
        self.assertIn("Item33 six-domain quality snapshot mismatch", self.validate())
        self.payload["production_write_set"]["forbidden_table_mutations"]["billing"] = 1
        self.assertIn("Item33 production write-set mismatch", self.validate())

    def test_chained_counted_capture_without_catalog_proof_stays_unverified(self):
        seal, raw, _ = self.bind_capture()
        self.assertEqual(capture.verify_capture_artifacts(seal, raw, require_terminal_proofs=False), seal["aggregate"])
        with self.assertRaises(ValueError):
            capture.verify_capture_artifacts(seal, raw)
        self.assertFalse(gate._item33_v5_capture_valid(self.payload["release_binding"]["capture_binding"],
            self.payload["cycle"], self.payload["production_write_set"], root=self.root))

    def rewrite_capture(self, seal, raw=None):
        if raw is not None:
            (self.root / gate.ITEM33_V5_CAPTURE_JOURNAL).write_bytes(raw)
            rows = [json.loads(line) for line in raw.splitlines()]
            seal["journal"].update(bytes=len(raw), sha256=capture.sha(raw), record_count=len(rows),
                                   last_chain_sha256=rows[-1]["sha256"])
        value = capture.encoded(seal) + b"\n"
        (self.root / gate.ITEM33_V5_CAPTURE_EVIDENCE).write_bytes(value)
        self.payload["release_binding"]["capture_binding"]["receipt_sha256"] = capture.sha(value)

    def capture_valid(self):
        return gate._item33_v5_capture_valid(self.payload["release_binding"]["capture_binding"],
            self.payload["cycle"], self.payload["production_write_set"], root=self.root,
            observed_at=self.payload["observed_at"])

    def test_catalog_is_actual_source_and_brackets_the_real_cycle(self):
        original = json.loads((self.root / gate.ITEM33_V5_CAPTURE_EVIDENCE).read_bytes())
        self.assertTrue(self.capture_valid())
        for defect in ("source", "missing", "late_before", "early_after", "future_after", "unknown"):
            seal = copy.deepcopy(original)
            proof = seal["catalog_proof"]
            if defect == "source": proof["source_sha256"] = "c" * 64
            elif defect == "missing": seal["catalog_proof"] = None
            elif defect == "late_before": proof["before"]["observed_at"] = "2026-09-19T00:06:00+00:00"
            elif defect == "early_after": proof["after"]["observed_at"] = "2026-09-19T00:02:00+00:00"
            elif defect == "future_after": proof["after"]["observed_at"] = "2026-09-19T23:59:59+00:00"
            else: seal["state"] = "UNKNOWN"
            self.rewrite_capture(seal)
            with self.subTest(defect=defect): self.assertFalse(self.capture_valid())

    def test_rechaining_a_missing_mutation_cannot_replace_trigger_count(self):
        seal = json.loads((self.root / gate.ITEM33_V5_CAPTURE_EVIDENCE).read_bytes())
        events = [json.loads(line)["event"] for line in
                  (self.root / gate.ITEM33_V5_CAPTURE_JOURNAL).read_bytes().splitlines()]
        index = next(index for index, event in enumerate(events)
                     if event.get("table") == "xhs_trends_provider_attempts" and event.get("op") == "UPDATE")
        del events[index]
        previous, lines = "0" * 64, []
        for index, event in enumerate(events, 1):
            row = {"sequence": index, "previous_sha256": previous, "event": event}
            row["sha256"] = previous = capture.sha(capture.encoded(row))
            lines.append(capture.encoded(row) + b"\n")
        self.rewrite_capture(seal, b"".join(lines))
        self.assertFalse(self.capture_valid())

    def test_terminal_physical_summary_needs_its_original_safe_http_artifact(self):
        path = self.root / gate.ITEM33_V5_HTTP_RECEIPT
        value = json.loads(path.read_bytes())
        value["reader_source_sha256"] = "f" * 64
        path.write_bytes(http_reader.encoded(value))
        self.payload["cycle"]["physical_http"]["worker_receipt_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertIn("Item33 V5 worker HTTP receipt mismatch", self.validate())

    def test_normal_handoff_binds_original_action_and_same_bucket_preserved_rows(self):
        self.assertTrue(gate._item33_v5_normal_handoff_valid(self.payload, root=self.root))
        original = copy.deepcopy(self.payload["normal_handoff"])
        for change in ("unit", "next_day", "source", "activation", "new_run", "old_artifact"):
            item = self.payload["normal_handoff"] = copy.deepcopy(original)
            if change == "unit": item["normal_unit_sha256"] = gate.ITEM33_V5_PROMOTED_UNIT_SHA256
            elif change == "next_day": item["completed_at"] = "2026-09-20T00:00:00+00:00"
            elif change == "source": item["runtime_overlay_sha256"].pop("model/trends_contract.py")
            elif change == "activation": item["activation_identity_sha256"] = item["run_identity_sha256"]
            elif change == "new_run": item["same_bucket"]["new_run_delta"] = 1
            else: item["action_sha256"] = "0" * 64
            with self.subTest(change=change):
                self.assertFalse(gate._item33_v5_normal_handoff_valid(self.payload, root=self.root))

    def test_normal_handoff_requires_exact_temporary_capture_removal(self):
        path = self.root / gate.ITEM33_V5_CAPTURE_TEARDOWN
        original = json.loads(path.read_bytes())
        for defect in ("missing", "unknown", "source", "residual", "acl", "too_late", "bool_count"):
            proof = copy.deepcopy(original)
            if defect == "missing": path.unlink()
            else:
                if defect == "unknown": proof["execution"]["status"] = "UNKNOWN"
                elif defect == "source": proof["source_sha256"] = "f" * 64
                elif defect == "residual": proof["after"]["catalog"]["triggers"].append(proof["before"]["catalog"]["triggers"][0])
                elif defect == "acl": proof["after"]["catalog"]["database_create"] = True
                elif defect == "too_late": proof["after"]["observed_at"] = "2026-09-19T00:36:30+00:00"
                else: proof["execution"]["control_plane_ddl_count"] = True
                from tools import item33_trends_capture_catalog as catalog
                proof["after"]["catalog_sha256"] = catalog.digest(proof["after"]["catalog"])
                path.write_bytes(capture.encoded(proof) + b"\n")
                self.payload["normal_handoff"]["teardown_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.subTest(defect=defect):
                self.assertFalse(gate._item33_v5_normal_handoff_valid(self.payload, root=self.root))
            path.write_bytes(capture.encoded(original) + b"\n")

    def test_seal_without_original_service_and_process_cleanup_is_not_normal_handoff(self):
        originals = {key: json.loads((self.root / ref).read_bytes())
                     for key, ref in gate.ITEM33_V5_CAPTURE_CLOSE_REFS.items()}
        for defect in ("close_unknown", "two_connections", "bad_config", "failure", "container", "bool_zero", "clock"):
            values = copy.deepcopy(originals)
            if defect == "close_unknown": values["close"]["state"] = "CLOSE_UNKNOWN"
            elif defect == "two_connections": values["close"]["connection_count"] = 2
            elif defect == "bad_config": values["service_result"]["configuration_sha256"] = "f" * 64
            elif defect == "failure": values["host"]["capture_service_failure_present"] = True
            elif defect == "container": values["host"]["capture_container_count"] = 1
            elif defect == "bool_zero": values["host"]["capture_container_count"] = False
            else: values["close"]["observed_at"] = "2026-09-19T00:36:30+00:00"
            host = values["host"]
            host["canonical_sha256"] = hashlib.sha256(json.dumps({key: value for key, value in host.items()
                if key != "canonical_sha256"}, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
            self.payload["normal_handoff"]["capture_close"] = self.save_capture_close(values)
            with self.subTest(defect=defect):
                self.assertFalse(gate._item33_v5_normal_handoff_valid(self.payload, root=self.root))


if __name__ == "__main__":
    unittest.main()
