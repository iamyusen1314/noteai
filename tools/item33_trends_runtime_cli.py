#!/usr/bin/env python3
"""Database-only inspection inside the existing Item33 image.

Every mode is read-only. SQL returned by preparation modes is not executed here;
the existing authenticated owner control plane installs/removes temporary capture.
Only DATABASE_URL is supplied by the host. No provider/session credentials enter.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import execute_item33_trends_promotion as controller
import item33_trends_capture_catalog as catalog
import item33_trends_capture_teardown as teardown
import item33_trends_dml_capture as dml
import item33_trends_runtime_capture as capture

CAPTURE_ROOT = Path("/var/lib/noteai/item33-trends-promotion/capture")
MODES = ("preflight", "catalog", "cycle", "prepare-install", "finalize-config", "prepare-teardown", "finalize-teardown")
FORBIDDEN_TARGETS = {
    "system_settings": dml.TableTarget(("key",), "system_settings"),
    "crawler_events": dml.TableTarget(("id",), "crawler_events"),
    "tracking_provider_attempts": dml.TableTarget(("id",), "tracking"),
    "users": dml.TableTarget(("id",), "authentication"),
    "credit_transactions": dml.TableTarget(("id",), "billing"),
    "payment_reconciliation_runs": dml.TableTarget(("id",), "payment"),
}


class RuntimeInspectionError(ValueError):
    """Fixed code, never driver content."""


def require(value, code="runtime_inspection_binding"):
    if not value:
        raise RuntimeInspectionError(code)


def now():
    return datetime.now(timezone.utc)


def clock(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(result.tzinfo is not None and result.utcoffset().total_seconds() == 0)
    return result


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def targets():
    return {name: dml.TableTarget(keys) for name, keys in dml.TABLE_KEYS.items()} | FORBIDDEN_TARGETS


def validate_plan(plan):
    require(isinstance(plan, dict) and plan.get("schema") == "noteai.item33.runtime_plan.v1")
    activation = dml._uuid(plan["activation_id"])
    require(plan["activation_identity_sha256"] == sha(activation.encode())
        and plan["operator_role"] == "noteai_admin"
        and plan["accepted_source_sha256"] == controller.V5_RUNTIME_OVERLAY_SHA256
        and plan["image_config_sha256"] == controller.V5_IMAGE_CONFIG_SHA256
        and plan["limits"] == {"initialization": 2, "collection": 34, "automatic_retry": 0, "cycles": 1})
    start, cutoff, end = (clock(plan[key]) for key in ("starts_at", "dispatch_before", "ends_at"))
    require(start < cutoff < end and 3600 <= (end - start).total_seconds() <= 7200
        and start.date().isoformat() == cutoff.date().isoformat() == end.date().isoformat() == plan["bucket_key"]
        and start.date().isoformat() > "2026-09-18")
    require(set(plan["instrumentation_sha256"]) == capture.INSTRUMENTATION_REFS)
    for value in plan["instrumentation_sha256"].values():
        dml._sha(value)
    require(plan["instrumentation_sha256"][controller.V5_CAPTURE_LAUNCHER_PATH] == sha(controller.V5_CAPTURE_LAUNCHER))
    return plan


def initial_config(plan):
    validate_plan(plan)
    value = {"schema": capture.CONFIG_SCHEMA,
        **{key: plan[key] for key in ("activation_id", "activation_identity_sha256", "bucket_key", "accepted_source_sha256", "instrumentation_sha256")},
        "socket_path": capture.SOCKET_PATH, "coverage": dml._coverage(targets()),
        "coverage_sha256": dml.coverage_sha256(targets()), "catalog_before_sha256": "0" * 64,
        "installed_definition_sha256": sha(dml.function_body(plan["activation_id"], targets(), mutation_counts=True).encode())}
    capture.validate_config(value)
    return value


def render_install_sql(plan):
    """Transactional, bounded, non-replacing installation; returns text only."""
    from psycopg import sql
    validate_plan(plan)
    guard = sql.SQL("""DO $item33_install$ BEGIN
 IF session_user <> {role} OR current_user <> {role} THEN RAISE EXCEPTION 'item33 operator identity'; END IF;
 IF clock_timestamp() < {starts}::timestamptz - interval '15 minutes'
    OR clock_timestamp() >= {cutoff}::timestamptz THEN RAISE EXCEPTION 'item33 install window'; END IF;
 IF EXISTS (SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname='public' AND p.proname={function}) THEN RAISE EXCEPTION 'item33 function exists'; END IF;
 IF EXISTS (SELECT 1 FROM public.xhs_trends_runs WHERE bucket_key={bucket})
    OR EXISTS (SELECT 1 FROM public.xhs_trends_provider_attempts a JOIN public.xhs_trends_runs r ON r.id=a.run_id
               WHERE r.bucket_key={bucket})
 THEN RAISE EXCEPTION 'item33 bucket consumed'; END IF;
 END $item33_install$""").format(role=sql.Literal(plan["operator_role"]), function=sql.Literal(dml.FUNCTION),
        bucket=sql.Literal(plan["bucket_key"]), starts=sql.Literal(plan["starts_at"]), cutoff=sql.Literal(plan["dispatch_before"]))
    statements = [sql.SQL("BEGIN"), sql.SQL("SET LOCAL lock_timeout='3000ms'"),
        sql.SQL("SET LOCAL statement_timeout='15000ms'"), guard,
        *dml.installation_sql(plan["activation_id"], targets(), mutation_counts=True), sql.SQL("COMMIT")]
    return "\n".join(item.as_string().rstrip(";") + ";" for item in statements) + "\n"


def wait_for_success(connection, *, plan, current=now, pause=time.sleep):
    """Bounded status polling, not a collection retry or a run claim."""
    require(connection.autocommit is True and connection.info.transaction_status == 0)
    poll_count = 0
    until = min(clock(plan["ends_at"]), current() + timedelta(minutes=30))
    while poll_count < 61:
        require(current() <= until and current().date().isoformat() == plan["bucket_key"], "cycle_wait_deadline")
        begun = False
        try:
            with connection.cursor() as cursor:
                cursor.execute("BEGIN READ ONLY"); begun = True
                cursor.execute("SET LOCAL statement_timeout='5000ms'")
                cursor.execute("SELECT status FROM public.xhs_trends_runs WHERE bucket_key=%s ORDER BY started_at LIMIT 2",
                               (plan["bucket_key"],))
                rows = cursor.fetchall()
            connection.rollback(); begun = False
        finally:
            if begun:
                connection.rollback()
        poll_count += 1
        require(len(rows) <= 1, "cycle_wait_multiple_runs")
        if rows:
            require(rows[0][0] in ("running", "succeeded"), "cycle_wait_terminal_failure")
            if rows[0][0] == "succeeded":
                return poll_count
        if poll_count < 61:
            pause(30)
    raise RuntimeInspectionError("cycle_wait_deadline")


def inspect(mode, *, connection, plan, config=None, seal_raw=None, journal=None,
            teardown_execution=None, bucket_key=None, expected_run_identity_sha256=None,
            wait_cycle=False, current=now):
    require(mode in MODES)
    validate_plan(plan)
    if bucket_key is not None:
        require(bucket_key == plan["bucket_key"])
    if config is not None:
        capture.validate_config(config)
        initial = initial_config(plan)
        require(all(config[key] == initial[key] for key in initial if key != "catalog_before_sha256"))
    seed = config or initial_config(plan)
    if mode == "preflight":
        from item33_trends_preflight import read_database_facts
        return read_database_facts(connection, now=current())
    if mode == "cycle":
        from item33_trends_database_readback import read_cycle_facts
        polls = 0
        if wait_cycle:
            polls = wait_for_success(connection, plan=plan, current=current)
        result = read_cycle_facts(connection, bucket_key=plan["bucket_key"], now=current(),
            expected_run_identity_sha256=expected_run_identity_sha256)
        result.pop("canonical_sha256")
        result["status_readonly_poll_count"] = polls
        result["canonical_sha256"] = sha(capture.encoded(result))
        return result
    if mode == "prepare-teardown":
        require(seal_raw is not None and journal is not None)
        text = teardown.render_teardown_sql(seal=capture.decoded(seal_raw), journal=journal, operator_role=plan["operator_role"])
        return {"state": "SQL_PREPARED_NOT_EXECUTED", "sql": text, "sql_sha256": sha(text.encode()),
            "control_plane_ddl_count": 2 * len(targets()) + 1, "provider_calls": 0, "production_database_writes": 0,
            "secret_values_recorded": False}
    facts = catalog.read_catalog_facts(connection, config=seed, now=current())
    if mode == "catalog":
        return facts
    if mode == "prepare-install":
        require(all(row["function"] != dml.FUNCTION for row in facts["catalog"]["triggers"])
            and all(row["name"] != dml.FUNCTION for row in facts["catalog"]["functions"]), "capture_already_installed")
        require({row["name"]: row["keys"] for row in facts["catalog"]["tables"]}
            == {name: list(target.key_columns) for name, target in targets().items()}, "capture_primary_keys")
        text = render_install_sql(plan)
        return {"state": "SQL_PREPARED_NOT_EXECUTED", "sql": text, "sql_sha256": sha(text.encode()),
            "catalog_before_install": facts, "control_plane_ddl_count": 2 * len(targets()) + 1,
            "provider_calls": 0, "production_database_writes": 0, "secret_values_recorded": False}
    require(current().date().isoformat() == plan["bucket_key"], "capture_bucket")
    if mode == "finalize-config":
        seed["catalog_before_sha256"] = facts["catalog_sha256"]
        require(seed["installed_definition_sha256"] == catalog.validate_catalog(facts["catalog"], config=seed))
        catalog.build_catalog_proof(facts, facts, config=seed, source_sha256=sha(Path(catalog.__file__).read_bytes()))
        return {"state": "CONFIGURATION_VERIFIED_NOT_RUNNING", "config": seed,
            "config_sha256": sha(capture.encoded(seed)), "catalog": facts, "provider_calls": 0,
            "production_database_writes": 0, "secret_values_recorded": False}
    require(mode == "finalize-teardown" and seal_raw is not None and journal is not None and teardown_execution is not None)
    return teardown.build_teardown_proof(seal_raw=seal_raw, journal=journal, after=facts,
        execution=teardown_execution, source_sha256=sha(Path(teardown.__file__).read_bytes()))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=MODES)
    parser.add_argument("--bucket-key")
    parser.add_argument("--expected-run-identity-sha256")
    parser.add_argument("--wait-cycle", action="store_true")
    args = parser.parse_args(argv)
    try:
        import psycopg
        plan = capture.decoded((ROOT / "item33-runtime-plan.json").read_bytes())
        config_path = CAPTURE_ROOT / "runtime-config.json"
        config = capture.decoded(config_path.read_bytes()) if config_path.exists() else None
        extra = {}
        if args.mode in {"prepare-teardown", "finalize-teardown"}:
            extra.update(seal_raw=(CAPTURE_ROOT / "capture-seal.json").read_bytes(),
                journal=(CAPTURE_ROOT / "production-item33-trends-dml-journal.jsonl").read_bytes())
        if args.mode == "finalize-teardown":
            extra["teardown_execution"] = capture.decoded((CAPTURE_ROOT / "operator-teardown-execution.json").read_bytes())
        with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, connect_timeout=5,
                             application_name="noteai-item33-readonly") as connection:
            result = inspect(args.mode, connection=connection, plan=plan, config=config,
                bucket_key=args.bucket_key, expected_run_identity_sha256=args.expected_run_identity_sha256,
                wait_cycle=args.wait_cycle, **extra)
        print(capture.encoded(result).decode())
        return 0
    except Exception as error:
        code = str(error) if isinstance(error, RuntimeInspectionError) else "item33_readonly_failed"
        kind = type(error).__name__
        sqlstate = getattr(error, "sqlstate", None)
        result = {"state": "READONLY_INSPECTION_FAILED", "error_code": code,
            "stage": args.mode, "error_type": kind if re.fullmatch(r"[A-Za-z_]{1,80}", kind) else "Exception",
            "sqlstate": sqlstate if isinstance(sqlstate, str) and re.fullmatch(r"[0-9A-Z]{5}", sqlstate) else None,
            "secret_values_recorded": False}
        print(capture.encoded(result).decode())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
