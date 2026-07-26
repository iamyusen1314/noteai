# NoteAI first-launch database runtime permission matrix

Version: `first-launch-2026-07-26`

Status: repository-only design. This file is not authorization to execute a
`GRANT`, `REVOKE`, migration or production database operation.

## Application role additions

Migration `0009_account_security_compliance.sql` introduces the following
runtime tables. The existing API role `noteai_app` needs exactly:

| Table | SELECT | INSERT | UPDATE | DELETE |
|---|---:|---:|---:|---:|
| `auth_login_limits` | yes | yes | yes | yes |
| `auth_verification_challenges` | yes | yes | yes | no |
| `content_retention` | yes | yes | column-limited | no |
| `account_deletion_requests` | yes | yes | yes | no |
| `user_contract_acceptances` | yes | yes | no | no |

The only permitted retention update surface is
`UPDATE(active_until,recovery_until,deleted_at,purge_after,purged_at,updated_at)`.
The role must not receive table-level `UPDATE` on `content_retention`, nor
column UPDATE on `content_type`, `content_id`, `user_id`, `retention_class`,
`created_at` or `contract_version`. This makes the identity, creation basis,
classification and contract version immutable while allowing only recovery,
owner-deletion and bounded-purge transitions.

Migration `0009` also activates account-deletion code paths against existing
tables. Relative to the last verified `noteai_app` matrix, the exact
permissions for retained primary content are narrowed to:

| Existing table | SELECT | INSERT | UPDATE | DELETE |
|---|---:|---:|---:|---:|
| `notes` | yes | yes | `parent_id` only | yes |
| `saved_diagnoses` | yes | yes | no | yes |

The role must not receive table-level `UPDATE` on `notes`; its only UPDATE
permission is `UPDATE(parent_id)`, which is required for version-family
detachment during owner deletion and individual-note purge. The verified
baseline already grants no UPDATE permission on `saved_diagnoses`; H19 does
not subtract it a second time. Current repository call-path review finds no
other UPDATE target on either table. The expected complete application table
matrix is therefore `100 true / 145 false`, with sequence results unchanged
at `5 / 10`. These constraints keep the primary content `id` and `user_id`
aligned with the immutable retention row.

The remaining additional existing-table DML required is:

| Existing table | Additional DML only | Why |
|---|---|---|
| `ai_operation_admissions` | DELETE | remove user-linked admission joins |
| `chat_sessions` | DELETE | erase account and note-linked copies |
| `credit_transactions` | UPDATE | replace the user id with a pseudonymous subject |
| `user_learn` | DELETE | erase learned preferences |
| `users` | DELETE | finish primary account deletion |

All existing positive permissions not explicitly narrowed or added above
remain unchanged. No new sequence is introduced.

## Persistent data and migration-integrity constraints

Migration `0009` adds a database-level `users_phone_canonical_check`.
Future non-empty phone values must match the canonical
`+861[3-9][0-9]{9}` form; `NULL` and the historical unbound empty string
remain allowed. Its existing-data preflight still runs before the constraint
and unique index are created.

Free-retention deadlines remain stored as text for the existing application
contract, but PostgreSQL now requires a strict real timestamp with an explicit
UTC offset (or `Z`) for `active_until`, `recovery_until` and `purge_after`.
The persistent check casts those values to `timestamptz` before comparing
them, so malformed dates and offset-based chronological inversions are
rejected. Outer whitespace is rejected rather than silently normalized.
Paid-indefinite rows keep `active_until` and `recovery_until` `NULL`.
While undeleted, `deleted_at` and `purge_after` are also `NULL`; after an
explicit owner deletion, both must be strict explicitly zoned clocks with
`deleted_at <= purge_after`. This tombstone preserves the paid-at-creation
classification while allowing the bounded 30-day purge contract.

`content_retention` also enables PostgreSQL row-level security without
granting any new privilege. The `PUBLIC` policies do not make the table
accessible: ordinary SQL privileges above are still mandatory. They allow
runtime SELECT, require every runtime INSERT to begin with `purged_at IS
NULL`, and allow UPDATE only from an unpurged row. A transition to a non-null
purge marker must be no later than the PostgreSQL transaction clock and must
observe that the matching Note or Diagnosis primary row has already been
deleted. Because an already-purged row is excluded from the UPDATE policy,
the marker cannot be cleared or rewritten by a runtime role. Column-level
UPDATE privileges prevent the same statement from swapping the identity used
by that absence check. The INSERT policy also requires matching primary
content. A primary-table INSERT trigger locks any existing retention identity
and rejects its reuse, covering post-purge, different-owner and same-
transaction resurrection. Its trigger function is schema-qualified, fixes
`search_path`, and uses the trusted migration owner only to see and lock
retention rows that runtime RLS intentionally hides after purge. It performs
no data write, has PUBLIC direct execution explicitly revoked, and can run
only through the two reviewed primary-table triggers. Runtime trigger
invocation does not add a callable function privilege. The migration owner
may otherwise bypass RLS only while applying the reviewed migration; neither
runtime role may own the table or hold `BYPASSRLS`.

The migration owner also maintains `schema_migrations.sha256` as a non-null,
lowercase 64-character SHA-256 of the exact SQL bytes that were executed.
The runner reads each migration file once into an immutable byte snapshot;
that same snapshot is hashed, UTF-8 decoded, executed and recorded. It
verifies every recorded digest while holding the migration advisory lock and
before executing any pending migration file. Legacy
versions `0001` through `0008` may receive their first digest only when their
current bytes match the reviewed hashes pinned in `model/db.py`; an unknown
digestless version, a missing local file or any later content drift aborts
the transaction. This ledger is owner-only metadata and creates no runtime
role permission.

The SQLite contract independently rejects duplicate insertion or replacement
of an existing retention identity. Repeated startup materialization first
checks the existing owner, creation clock and contract version, then skips the
row instead of relying on conflict replacement. The application retention
helper uses the same read-before-no-op rule for exact idempotent repeats and
rejects owner, contract or supplied-clock conflicts. This keeps local/test
behavior aligned with PostgreSQL's primary key and immutable-column ACL
boundary.

## Function execution dependencies

The user-level write fence has two PostgreSQL built-in function dependencies.
They are part of the exact runtime contract for both `noteai_app` and
`noteai_xhs`:

| Function signature | `noteai_app` EXECUTE | `noteai_xhs` EXECUTE | Purpose |
|---|---:|---:|---|
| `pg_catalog.hashtext(text)` | yes | yes | derive a stable advisory-lock key |
| `pg_catalog.pg_advisory_xact_lock(bigint)` | yes | yes | serialize one user's writes inside the transaction |

These are catalog-resolved built-ins normally executable through PostgreSQL's
existing `PUBLIC` function ACL. Migration `0009` must not add a task-specific
function `GRANT`, change function ownership, or change default privileges.
The verification task must still prove the effective privilege explicitly:

```sql
SELECT has_function_privilege(
  'noteai_app', 'pg_catalog.hashtext(text)', 'EXECUTE'
);
SELECT has_function_privilege(
  'noteai_app', 'pg_catalog.pg_advisory_xact_lock(bigint)', 'EXECUTE'
);
SELECT has_function_privilege(
  'noteai_xhs', 'pg_catalog.hashtext(text)', 'EXECUTE'
);
SELECT has_function_privilege(
  'noteai_xhs', 'pg_catalog.pg_advisory_xact_lock(bigint)', 'EXECUTE'
);
```

## Explicit negative matrix

For `noteai_app`, verification must prove all of the following remain absent:

- DELETE on `auth_verification_challenges`, `content_retention`,
  `account_deletion_requests` and `user_contract_acceptances`;
- UPDATE on `user_contract_acceptances`;
- table-level `UPDATE` on `content_retention`, or column UPDATE on any of its
  immutable identity/classification/creation/contract fields;
- table-level `UPDATE` on `notes`, or column UPDATE on any `notes` column
  other than `parent_id`;
- any `UPDATE` on `saved_diagnoses`;
- any DML on `schema_migrations`;
- schema `CREATE`, table ownership, `TRUNCATE`, `REFERENCES`, `TRIGGER`,
  grant option, role creation, default-privilege changes, or sequence
  `SELECT`/`UPDATE`.
- ownership or `EXECUTE WITH GRANT OPTION` on either built-in function above;
- direct `EXECUTE`, ownership or grant option on
  `public.noteai_retained_primary_insert_guard_h20()`; only its reviewed
  table triggers may invoke it;
- any other task-specific function ACL entry or function creation, or
  `CREATE` on `pg_catalog` or `public`.
- table ownership, `BYPASSRLS`, policy ownership changes, or any route around
  the reviewed retention policies or H20 primary-insert triggers.

Contract acceptances are append-only per `(user_id, contract_version)`;
`ON CONFLICT DO NOTHING` handles idempotent repeats.

## XHS role

`noteai_xhs` needs no privilege on any table introduced by migration `0009`.
Its already verified minimum matrix, including only `SELECT` on
`public.xhs_crawler_health`, must remain unchanged.

For the later Tracking service, the current `noteai_xhs` identity is only a
historical Trends/Tracking union and is not an acceptable long-lived runtime
identity. Migration `0010_tracking_execution_contract.sql` introduces
`tracking_provider_attempts` and new claim columns but intentionally grants
nothing. The dedicated `noteai_xhs_tracking` positive and complete negative
matrix is defined in `docs/XHS_TRACKING_PRODUCTION_CONTRACT.md`. In
particular, it receives column-limited Tracking updates, insert-only growth,
memory and crawler-event surfaces, read-only settings, and zero Trends-table
access. It must not gain `users SELECT` merely to call the generic memory
writer; the reviewed Tracking path inserts its deterministic context memory
inside the already-fenced terminal transaction.

The Trends long-running contract is independently defined in
`docs/XHS_TRENDS_PRODUCTION_CONTRACT.md`. Migration
`0011_trends_execution_contract.sql` creates and seeds the durable daily
run/admission/singleton state but grants nothing. Long-lived Trends must use
the exact `noteai_xhs_trends` role, with access limited to the eight listed
Trends tables, two sequences and the two existing advisory-lock built-ins.
It has zero Tracking, user, billing, auth, retention, prompt, migration,
`system_settings` or `crawler_events` access. The historical `noteai_xhs`
union is not an acceptable identity for either managed service.

The API freshness gate now binds visible evidence to the latest succeeded
Trends run. After `0011` is applied, `noteai_app` therefore needs only column
`SELECT(id,status,completed_at)` on `public.xhs_trends_runs`; table-level
SELECT and every other run column remain negative. A missing table or missing
permission fails closed as `trends_contract_unavailable` and must never fall
back to legacy unbound freshness. API receives no write privilege on any
Trends contract table and no access to the stored snapshot payload.

## Verification required before production use

A separately approved database task must:

1. apply the additive migration with a migration owner, not a runtime role;
2. fail closed if duplicate non-empty phones or invalid timestamp history
   block the migration;
3. prove future noncanonical phones, malformed/outer-whitespace retention
   deadlines and real-time reversed deadlines are rejected by persistent
   constraints; prove a runtime role cannot insert, predate, clear or rewrite
   a purge marker, cannot mark a row while its matching primary content still
   exists, can record the marker only after bounded primary deletion, and
   cannot reinsert either primary type afterward, under another owner or later
   in the same transaction;
4. prove first apply records the SHA-256 of the exact executed byte snapshot,
   second apply is empty, and any recorded-file drift aborts before subsequent
   migration SQL;
5. apply only the new-table matrix, the `notes` UPDATE contraction, the
   unchanged negative Diagnosis UPDATE baseline and five existing-table deltas
   above to `noteai_app`, using the exact six-column retention UPDATE list
   plus `notes(parent_id)` and proving table-level UPDATE plus every immutable-
   column UPDATE remain false;
6. compare every table/sequence privilege boolean for `noteai_app` and
   `noteai_xhs`, including explicit negative checks;
7. run all four exact `has_function_privilege` checks above and prove neither
   runtime role owns the built-ins or has grant option; also prove both roles
   lack direct EXECUTE, ownership and grant option on the H20 trigger function;
8. prove `schema_migrations`, ownership and DDL capabilities remain absent.
