# XHS Tracking first-launch production contract

Version: `first-launch-2026-07-26`

Status: repository candidate only. This document does not authorize a
migration, role change, service start, supplier call or production write.

## Product and URL boundary

- Tracking remains a first-launch hard requirement and is independently
  accepted from Trends.
- User API paths and the 24h/7d/manual-fill product flow remain stable.
- Only an HTTPS full note URL on exact host `xiaohongshu.com` or
  `www.xiaohongshu.com` and exact `explore`/`discovery/item` path is accepted.
- The stored identity is
  `https://www.xiaohongshu.com/explore/<lowercase-24-hex-id>`.
  Query strings, fragments, credentials and ports are never persisted.
- `xhslink.com` is rejected until a bounded trusted resolver can prove its
  final host and canonical note id without storing a supplier token.
- `(user_id,xhs_url)` and non-null `(user_id,xhs_note_id)` are database unique.

## Execution state machine

1. The direct-adapter role and default-suspended gates run before any due-row
   read or provider admission.
2. The round claims exactly one due row immediately before processing it,
   repeating at most 50 times. Each row therefore receives a fresh 15-minute
   lease. PostgreSQL uses `FOR UPDATE SKIP LOCKED`; SQLite serializes writers
   and compares zoned clocks by their UTC instant.
3. Before any supplier call, the Worker re-locks the exact user and row,
   proves the original status, unexpired claim and account-deletion fence,
   enforces the durable 300-admission UTC-day cap, and inserts one
   `tracking_provider_attempts` row.
4. The unique `(track_id,stage)` key permits at most one provider admission
   for each `24h` or `7d` window. There is no automatic supplier retry.
5. A known result is committed only with the exact claim and active attempt.
   A 24h success schedules 7d. A 7d success atomically commits the Tracking
   result, one deterministic growth record, one deterministic context memory
   and the succeeded attempt.
6. A known supplier failure atomically becomes `needs_manual`; it does not
   requeue itself. A process crash after admission leaves an active,
   audit-visible ambiguous attempt. The read-only healthcheck becomes
   `not_ready`; the explicit provider-free `--reconcile-stale` command changes
   only an expired attempt to `provider_outcome_unknown`/`needs_manual`.
   Neither path makes another supplier call.
7. Manual fill is allowed only from `needs_manual` or `failed`, with no active
   attempt, and atomically commits the same two deterministic side effects.
   A complete row cannot be silently reopened by the user or Admin.

Account deletion and provider admission use the same per-user advisory-lock
namespace. No new provider admission can be created after the deletion fence
wins. If admission wins first, the durable active-attempt marker makes the
deletion request return a bounded conflict until the known result or explicit
stale reconciliation clears it; account revocation cannot begin between
admission and the supplier call.

## Exact limits and write bounds

- Per round: `1 <= N <= 50` fresh single-row claims and at most `N` provider
  admissions.
- Per UTC day: at most 300 durable Tracking provider admissions across all
  Workers.
- Per record: at most one 24h and one 7d provider admission; lifecycle maximum
  is two calls. A failed/ambiguous stage requires manual resolution.
- Per claimed record: one claim update and at most one known-result finalize.
- Per successful 7d/manual terminal record: at most one growth insert and one
  context-memory insert, enforced by deterministic primary keys.
- Supplier writes are unavailable: the fixed adapter exposes read endpoints
  only. Browser fallback, `--force` and entrypoint override are not production
  operating modes.

## Migration and persistent checks

Migration `0010_tracking_execution_contract.sql` is additive and contains no
`GRANT`, `REVOKE`, role or service statement. It adds claims, the provider
attempt ledger, canonical identity and ownership constraints, semantic zoned
clock checks and the cross-track active-attempt foreign key. It fails closed
on any noncanonical/duplicate identity or invalid state/clock history.

Before production application, a read-only preflight must count—without
returning user values—duplicate canonical identities, invalid status/metrics,
invalid or unordered clocks, incomplete terminal rows, active legacy work and
owner mismatches. Any non-zero incompatible count blocks migration; data must
not be silently overwritten.

## Dedicated runtime role

Long-lived Tracking must use `noteai_xhs_tracking`, not the existing
Trends/Tracking union `noteai_xhs`.

Required positive table surface:

| Table | Required privilege |
|---|---|
| `tracked_notes` | `SELECT`; `UPDATE` only on `claim_token`, `claim_expires_at`, `active_attempt_id`, `note_title`, `likes_24h`, `saves_24h`, `comments_24h`, `check_24h_at`, `likes_7d`, `saves_7d`, `comments_7d`, `check_7d_at`, `views_est`, `next_check_at`, `last_checked_at`, `attempt_count`, `actual_ces`, `confidence`, `confidence_label`, `evidence_source`, `training_eligible`, `status`, `last_error_code`, `last_error`, `completed_at`, `insights_json` |
| `tracking_provider_attempts` | `SELECT`, `INSERT`; column `UPDATE(status,completed_at,error_code)` |
| `growth_records` | `INSERT` only |
| `user_memories` | `INSERT` only |
| `crawler_events` | `INSERT` only |
| `system_settings` | `SELECT` only |
| `crawler_events_id_seq` | `USAGE` only |

The role needs database `CONNECT`, schema `USAGE`, and effective execution of
`pg_catalog.hashtext(text)` and
`pg_catalog.pg_advisory_xact_lock(bigint)`.

It must have zero access to users, auth/session, billing, Admin, migration
ledger and every Trends table; no table-level `UPDATE` on `tracked_notes`; no
`UPDATE`/`DELETE` on growth or memory; no sequence `SELECT`/`UPDATE`; and no
ownership, membership, superuser, `BYPASSRLS`, database/schema create,
`TRIGGER`, `REFERENCES`, `TRUNCATE`, grant option or default-privilege power.

## Observability and service gate

- Every round emits a random `run_id`, selected/claimed/attempted/released
  counts, configured limit, exit reason and non-sensitive error codes.
- Per-note logs use only a SHA-256 prefix reference, stage and fixed code.
  URLs, note ids, supplier payloads, cookies and tokens are prohibited.
- The provider-attempt ledger is the authoritative admission/call cap audit.
- A safe suspended/no-due outcome exits 0. Invalid configuration, unsafe
  skip, partial/total failure and lost admission exit non-zero. A managed
  loop stops on the first failed round instead of auto-retrying.
- The container uses `restart: "no"`: an error cannot immediately restart
  supplier execution against another due row. Recovery is an explicit
  operator action after evidence review.
- `crawler_worker.py --healthcheck` is provider-free and read-only. It proves
  the dedicated role can read the exact Tracking schema and fails readiness
  on stale or structurally unlinked started attempts. It never treats
  suspended process liveness alone as readiness.
- Promotion still requires isolated PostgreSQL apply-twice/rollback and full
  permission matrices, a dedicated immutable-digest managed service,
  singleton/resource/restart/log/alert controls, then one separately bounded
  real-supplier validation.

Rollback order is: suspend admission, stop the dedicated Tracking service,
preserve sanitized logs and attempt rows, restore the previous immutable
image and revoke/drop only the dedicated role after proving no connection.
The additive migration remains dormant; destructive schema rollback is not
part of incident response.
