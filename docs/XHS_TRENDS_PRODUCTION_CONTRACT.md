# XHS Trends Production Execution Contract

## Scope and status

`PROD-XHS-TRENDS-LONGRUN-CONTRACT-001` defines the repository and database
contract required before Trends may become a managed production service. It
does not apply migration `0011`, create a production role, build/publish an
image, start a service, remove suspension or call XHS.

The earlier suspended Canary remains accepted evidence for its exact old
digest. This contract supersedes that runtime design: a default-suspended
long-lived process performs zero database writes and zero provider calls.

## Scheduling and singleton

- Production uses one managed `--daemon` process with `restart: "no"`. It
  wakes at a bounded interval, but one unique UTC-day bucket permits at most
  one real collection cycle.
- `xhs_trends_service_state` owns one 30-minute lease token hash and monotonic
  fence. PostgreSQL serializes claims with an advisory lock and row lock;
  SQLite uses `BEGIN IMMEDIATE` for parity.
- A live lease has one winner. A completed daily bucket cannot run again.
  Expiry before any provider admission becomes a failed run. Expiry after an
  admitted call becomes `needs_manual / provider_outcome_unknown` and blocks
  every later provider call.
- Unknown outcomes are never retried. The only release is the explicit,
  provider-free `--acknowledge-unknown` command; it preserves the run and
  attempt evidence and cannot reuse the same UTC-day bucket.

## Provider and write bounds

- Every XHS HTTP request is durably inserted in
  `xhs_trends_provider_attempts` after local signing and immediately before
  network I/O.
- The fixed endpoint set is `homefeed`, `search_recommend`, and
  `search_notes`. Detail/Tracking endpoints are outside the Trends contract.
- The compile-time hard limits are 34 requests per run and 34 requests per
  UTC day: 10 homefeed requests plus six domains × two fixed seeds × two
  search requests. Environment values cannot raise the two-seed limit.
- Candidate ordering is deterministic. Only the six launch domains are
  retained, with at most 15 keywords per domain and 90 per run.
- A successful run requires at least one durable provider attempt, every
  admitted attempt terminal as `succeeded`, and the attempt-row count equal
  to the run counter. It also requires this run—not cumulative history—to
  provide at least 12 unique real-XHS keywords in every domain and both
  search-result and search-recommend evidence for every domain. Duplicate
  rows never increase this count, and environment values cannot disable this
  gate.
- Exactly one deterministic real-first pack is written: at most 90
  `hot_keywords` upserts, 90 `keyword_snapshots` inserts, six freshness
  upserts, six health inserts and one snapshot-evidence insert. Labelled
  baseline rows may only fill the 15-per-domain pack after the real gate
  passes; they can never make a production run succeed.

## Snapshot and evidence

Managed production does not write a local snapshot target and rejects every
HTTP snapshot upload URL before it claims a run. The payload is serialized
only from this run's bounded publish rows, so historical high-score rows
cannot enter it. Before publication it verifies:

- schema version `1`;
- exactly the six launch domains;
- 12–15 keywords in every domain and no more than 90 total;
- size `1..1,048,576` bytes;
- non-empty, domain-matching, unique keywords in every domain;
- SHA-256 of the exact stored UTF-8 bytes.

The exact payload, hash, size, keyword count and six domain counts are stored
in `xhs_trends_snapshot_evidence`. Hot-keyword writes, freshness/health rows,
snapshot evidence and the succeeded run transition share one fenced database
transaction: all commit or all roll back. Provider-attempt evidence remains
durable outside that transaction. Each daily payload is at most 1 MiB and is
retained as audit/business evidence; rollback must not delete it.

## Health, recovery and logs

`python market_timing_worker.py --healthcheck` is database-read-only,
provider-free and does not create a missing SQLite database. It checks the
four contract tables, the exact PostgreSQL runtime role, singleton shape,
stale lease and unlinked/unknown attempt state. A non-expired active run and
its linked admitted request remain healthy. Stale, unlinked, unknown, missing
schema/state, invalid succeeded snapshot evidence, blocked session or
wrong-role state is not ready.

Session logout uses the dedicated service-state stop, not arbitrary
`system_settings` writes. After an operator replaces credentials, only the
explicit provider-free `--clear-session-block` command may clear it while the
service is idle. Operational logs use a fixed event allowlist and fixed
fields; URLs, queries, cookies, response bodies and exception messages are
not accepted.

## Dedicated PostgreSQL role

Long-lived Trends must use the exact role `noteai_xhs_trends`. Migration
`0011_trends_execution_contract.sql` creates and seeds contract state but
contains no `GRANT`, `REVOKE`, role creation or ownership change.

Exact positive table contract:

The role has only database `CONNECT` and schema `public USAGE`; database or
schema `CREATE` and database `TEMP` remain forbidden.

| Table | Required privilege |
|---|---|
| `hot_keywords` | `SELECT`, `INSERT`; column `UPDATE(search_vol,trend_dir,source,sample_count,quality_score,evidence_level,quality_reason,captured_at)` |
| `keyword_snapshots` | `SELECT`, `INSERT` |
| `xhs_crawler_health` | `SELECT`, `INSERT` |
| `xhs_freshness_ledger` | `SELECT`, `INSERT`; column `UPDATE(source,evidence_count,status,acquired_at,fresh_until,last_run_id,details_json)` |
| `xhs_trends_runs` | `SELECT`, `INSERT`; column `UPDATE(status,completed_at,provider_attempt_count,last_error_code,snapshot_sha256,snapshot_size)` |
| `xhs_trends_provider_attempts` | `SELECT`, `INSERT`; column `UPDATE(status,completed_at,error_code)` |
| `xhs_trends_service_state` | `SELECT`; column `UPDATE(active_run_id,status,lease_token_hash,lease_fence,lease_expires_at,session_blocked,session_block_reason,session_blocked_at,updated_at)` |
| `xhs_trends_snapshot_evidence` | `SELECT`, `INSERT` |

Only `USAGE` on `hot_keywords_id_seq` and `keyword_snapshots_id_seq` is
required. The role needs effective `EXECUTE` on
`pg_catalog.hashtext(text)` and
`pg_catalog.pg_advisory_xact_lock(bigint)` through the existing catalog
contract, without ownership or grant option.

Every other table/sequence/function/column privilege is negative, including:

- zero access to `tracked_notes`, `tracking_provider_attempts`,
  `growth_records`, `user_memories`, Users, Notes, billing, auth, Admin,
  payment, AI-operation, retention, prompt and migration-ledger tables;
- no `system_settings`, `crawler_events` or Secret-table access;
- no table-level `UPDATE`, any `DELETE`, `TRUNCATE`, `REFERENCES`, `TRIGGER`,
  schema `CREATE`, DDL, ownership, grant option, role membership, superuser
  or `BYPASSRLS`;
- no sequence `SELECT`/`UPDATE`, and no access to a sequence outside the two
  listed identities.

Production promotion must compare database, schema, table, column, sequence,
function, role-attribute and default-ACL booleans against this matrix. It
must not reuse the historical union `noteai_xhs` role. Because API freshness
binds to the latest succeeded run, the separate application-role delta is
only column `noteai_app SELECT(id,status,completed_at)` on
`public.xhs_trends_runs`; table-level SELECT and all other run columns remain
negative. A missing privilege fails closed and never enables legacy evidence.

## Rollback

Keep collection suspended, stop only the Trends process, pin the previous
digest and leave contract/audit rows intact. Do not delete attempt evidence,
reuse the one-time EntryPoint Override, start Tracking, change API/Admin, or
alter ALB/TLS/DNS/traffic as part of a Trends rollback.
