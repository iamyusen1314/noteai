"""Read a real Item33 cycle without provider calls or database mutations.

This is a component, not a promotion CLI or DML/HTTP proof. The supplied original
Trends connection must be idle/autocommit. Only hashed operational identities and
the already sanitized public keyword snapshot leave the transaction.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re

try:
    from . import execute_item32_readonly_trends_successor as accepted
except ImportError:
    import execute_item32_readonly_trends_successor as accepted


class Item33ReadbackError(RuntimeError):
    """Fixed reason codes only; never propagate driver/provider contents."""


def require(condition, code):
    if not condition:
        raise Item33ReadbackError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def read_cycle_facts(connection, *, bucket_key: str, now: datetime,
                     expected_run_identity_sha256: str | None = None) -> dict:
    """Return one successful persisted cycle and its source/ledger readbacks.

    All reads share a repeatable-read read-only snapshot. This deliberately does
    not infer physical HTTP, retries, distinct rows touched, DELETE/DDL absence,
    or capture completeness from final database state.
    """
    from psycopg.rows import dict_row

    require(isinstance(now, datetime) and now.tzinfo is not None, "clock")
    now = now.astimezone(timezone.utc)
    require(isinstance(bucket_key, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", bucket_key), "bucket")
    try:
        require(date.fromisoformat(bucket_key).isoformat() == bucket_key, "bucket")
    except ValueError:
        raise Item33ReadbackError("bucket") from None
    require(expected_run_identity_sha256 is None or (isinstance(expected_run_identity_sha256, str)
            and re.fullmatch(r"[0-9a-f]{64}", expected_run_identity_sha256)), "run_identity")
    require(connection.autocommit is True and connection.info.transaction_status == 0,
            "connection_not_idle_autocommit")
    begun = False
    try:
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
            begun = True
            cursor.execute("SET LOCAL statement_timeout='5000ms'")
            cursor.execute("SET LOCAL TIME ZONE 'UTC'")
            identity = cursor.execute("""SELECT session_user::text AS session_role,
                current_user::text AS current_role,CURRENT_TIMESTAMP AS observed_at,
                current_setting('transaction_read_only') AS read_only,
                pg_current_xact_id_if_assigned()::text AS xid""").fetchone()
            require(identity["session_role"] == identity["current_role"] == "noteai_xhs_trends"
                    and identity["read_only"] == "on" and identity["xid"] is None, "role_or_readonly")
            require(abs((identity["observed_at"] - now).total_seconds()) <= 60, "database_clock")
            runs = cursor.execute("""SELECT id,bucket_key,status,started_at,completed_at,lease_expires_at,
                provider_attempt_count,last_error_code,snapshot_sha256,snapshot_size
                FROM xhs_trends_runs WHERE bucket_key=%s LIMIT 2""", (bucket_key,)).fetchall()
            require(len(runs) == 1, "cycle_count")
            run = runs[0]
            require(run["status"] == "succeeded" and run["last_error_code"] == ""
                    and run["provider_attempt_count"] == 34, "cycle_not_succeeded")
            run_hash = digest(run["id"].encode())
            require(expected_run_identity_sha256 is None or run_hash == expected_run_identity_sha256,
                    "run_identity")
            started, finished = run["started_at"], run["completed_at"]
            require(isinstance(finished, datetime) and started <= finished <= now
                    and started.date().isoformat() == finished.date().isoformat() == bucket_key
                    and run["lease_expires_at"] == started + timedelta(minutes=30)
                    and finished <= run["lease_expires_at"], "cycle_clock")
            attempts = cursor.execute("""SELECT id,ordinal,endpoint,status,admitted_at,completed_at,error_code
                FROM xhs_trends_provider_attempts WHERE run_id=%s ORDER BY ordinal LIMIT 35""",
                (run["id"],)).fetchall()
            require(len(attempts) == 34 and [x["ordinal"] for x in attempts] == list(range(1, 35))
                    and [x["endpoint"] for x in attempts] == accepted.ENDPOINT_SEQUENCE
                    and len({x["id"] for x in attempts}) == 34
                    and all(x["status"] == "succeeded" and x["error_code"] == ""
                        and x["completed_at"] is not None
                        and started <= x["admitted_at"] <= x["completed_at"] <= finished for x in attempts),
                    "attempt_contract")
            snapshots = cursor.execute("""SELECT schema_version,snapshot_sha256,snapshot_size,keyword_count,
                domain_counts_json,payload_json,created_at FROM xhs_trends_snapshot_evidence WHERE run_id=%s""",
                (run["id"],)).fetchall()
            require(len(snapshots) == 1, "snapshot_count")
            snapshot = snapshots[0]
            raw = snapshot["payload_json"].encode()
            require(0 < len(raw) <= 1048576 and snapshot["schema_version"] == 1
                    and run["snapshot_sha256"] == snapshot["snapshot_sha256"] == digest(raw)
                    and run["snapshot_size"] == snapshot["snapshot_size"] == len(raw)
                    and started <= snapshot["created_at"] <= finished, "snapshot_binding")
            counts, search, recommend, total = accepted._snapshot_quality(raw,
                execution_started_at=started.isoformat(), execution_finished_at=finished.isoformat())
            payload = json.loads(raw)
            declared = {domain: len(part["keywords"]) for domain, part in payload["domains"].items()}
            require(snapshot["domain_counts_json"] == declared and snapshot["keyword_count"] == total,
                    "snapshot_counts")
            health = cursor.execute("""SELECT domain,status,risk_login_detected,evidence_count,checked_at
                FROM xhs_crawler_health WHERE run_id=%s ORDER BY domain LIMIT 7""", (run["id"],)).fetchall()
            freshness = cursor.execute("""SELECT domain,status,evidence_count,evidence_date,acquired_at,fresh_until
                FROM xhs_freshness_ledger WHERE last_run_id=%s ORDER BY domain LIMIT 7""",
                (run["id"],)).fetchall()
            ledger = cursor.execute("""SELECT
                (SELECT count(*) FROM xhs_trends_runs WHERE status IN ('running','needs_manual'))::int AS active_run_count,
                (SELECT count(*) FROM xhs_trends_runs WHERE bucket_key=%s)::int AS same_bucket_run_count,
                (SELECT count(*) FROM xhs_trends_provider_attempts WHERE status='admitted')::int AS active_attempt_count,
                (SELECT count(*) FROM xhs_trends_provider_attempts WHERE status='outcome_unknown')::int AS outcome_unknown_count,
                (SELECT count(*) FROM xhs_trends_provider_attempts a LEFT JOIN xhs_trends_runs r ON r.id=a.run_id
                 WHERE r.id IS NULL)::int AS orphan_attempt_count,
                (SELECT count(*) FROM xhs_trends_provider_attempts a LEFT JOIN xhs_trends_service_state s
                 ON s.service_key='market_timing' AND s.active_run_id=a.run_id
                 WHERE a.status='admitted' AND s.active_run_id IS NULL)::int AS unlinked_attempt_count,
                (SELECT count(*) FROM xhs_trends_service_state WHERE service_key='market_timing'
                 AND status='idle' AND active_run_id IS NULL AND session_blocked=FALSE)::int AS idle_service_count
                """, (bucket_key,)).fetchone()
            end = cursor.execute("""SELECT current_setting('transaction_read_only') AS read_only,
                                  pg_current_xact_id_if_assigned()::text AS xid""").fetchone()
            require(end == {"read_only": "on", "xid": None}, "readonly_changed")
            result = {"schema": "noteai.item33.database_cycle_readback.v1",
                "observed_at": identity["observed_at"].isoformat(), "bucket_key": bucket_key,
                "database_role": "noteai_xhs_trends", "server_enforced_read_only": True,
                "xid_assigned": False, "provider_calls": 0, "production_database_writes": 0,
                "run_identity_sha256": run_hash, "started_at": started.isoformat(),
                "completed_at": finished.isoformat(), "lease_expires_at": run["lease_expires_at"].isoformat(),
                "provider_request_count": len(attempts), "endpoint_counts": dict(Counter(x["endpoint"] for x in attempts)),
                "attempts": [{"attempt_identity_sha256": digest(x["id"].encode()),
                    "ordinal": x["ordinal"], "endpoint": x["endpoint"], "status": x["status"],
                    "admitted_at": x["admitted_at"].isoformat(), "completed_at": x["completed_at"].isoformat()}
                    for x in attempts],
                "snapshot": {"sha256": digest(raw), "size": len(raw), "payload": payload},
                "quality": {"domain_real_keyword_counts": counts, "search_result_domains": search,
                    "search_recommend_domains": recommend, "keyword_count": total},
                "health_rows": [dict(x) for x in health], "freshness_rows": [dict(x) for x in freshness],
                "ledger": dict(ledger), "physical_http_verified": False, "production_write_set_verified": False,
                "business_ddl_count_verified": False, "automatic_retry_count": None,
                "secret_values_recorded": False}
        connection.rollback()
        begun = False
        result["transaction_rolled_back"] = True
        result["canonical_sha256"] = digest(canonical(result))
        return result
    except Item33ReadbackError:
        raise
    except accepted.Item32Error:
        raise Item33ReadbackError("snapshot_quality") from None
    except Exception:
        raise Item33ReadbackError("database_readback_unknown") from None
    finally:
        if begun:
            try:
                connection.rollback()
            except Exception:
                raise Item33ReadbackError("database_rollback_unknown") from None
