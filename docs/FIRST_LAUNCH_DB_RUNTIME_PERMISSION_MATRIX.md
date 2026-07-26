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

## Durable AI roles

Migration `0012_durable_ai_execution_contract.sql` adds
`ai_payload_refs`, `ai_operation_outbox`, `ai_operation_settlements` and
`ai_dispatch_state` without any `GRANT` or `REVOKE`. The complete behavior and
data boundary are frozen in `docs/DURABLE_AI_PRODUCTION_CONTRACT.md`.

The existing API role must receive only the columns required to:

- insert one request ref, Outbox row and charged settlement in the same
  transaction as the existing idempotency/usage admission;
- cancel only a provider-free owner operation during account deletion,
  changing its Outbox row to `dead` and its charged settlement to the exact
  `refunded/cancelled` state; PostgreSQL RLS requires column-only
  `SELECT(id,operation_id,state)` plus `UPDATE(state,updated_at)` on the
  Outbox for this path, never table-level SELECT or lease-column access;
- read owner-scoped operation state and the ready result-ref metadata;
- never read or write lease owner hashes, provider attempts, dispatch state
  or another user's join path.

The exact `noteai_ai_dispatcher` role may select only Outbox identity/state,
operation UUID/priority and dispatch streak, then update only Outbox lease,
attempt, delivery and dispatch-streak columns. It receives no access to
payload-ref hashes, user/idempotency/billing tables, provider attempts,
results, XHS tables or model usage.

The exact `noteai_ai_worker` role may:

- select/update the fenced operation/event/provider-attempt state;
- select the request/result ref metadata needed to verify an opaque object;
- insert a result ref and update only settlement terminal columns;
- select the linked admission, idempotency, user/subscription/credits/usage
  rows required by the canonical user fence and atomic completion/refund;
- insert numeric model-usage and exact refund ledger rows;
- never select user credentials/profile content, Note/Diagnosis/Chat content,
  raw XHS data, Secrets, prompts, migration metadata or Admin sessions.

All three roles must lack object ownership, role membership, superuser,
`BYPASSRLS`, database/schema creation, TEMP, DDL, TRUNCATE, REFERENCES,
TRIGGER, grant option, sequence SELECT/UPDATE and `schema_migrations` access.
Only reviewed sequences and the two existing user advisory-lock built-ins may
be usable. The final positive/negative column matrix must be generated from
the integrated API/Worker SQL call paths and proved on disposable PostgreSQL
before any production privilege change.

## Private object and media roles

Migration `0013_private_storage_recovery_contract.sql` adds
`private_media_refs`, `ai_operation_media_refs` and the persistent
owner/ready/TTL link guard without granting runtime privileges. The full
object, lifecycle and restore contract is frozen in
`docs/PRIVATE_STORAGE_AND_RECOVERY_CONTRACT.md`.

`noteai_app` requires:

- `SELECT, INSERT` on the content-free private-media metadata;
- column-only `UPDATE(state,deleted_at)` for expiry/account deletion;
- `SELECT, INSERT` on the operation/media link;
- only `id,subject_hash` from `ai_operations` for the persistent link guard.

`noteai_ai_worker` receives read-only access to both new tables. Dispatcher,
Admin, Trends and Tracking receive zero access. No runtime role receives
object keys, URLs, media bytes, table ownership, sequence privilege,
`schema_migrations`, schema/database creation, TEMP, DDL, role membership,
superuser, `BYPASSRLS` or grant option. The API lifecycle policy can move only
a ready row to `expired` or `deleted`; a Worker cannot insert or mutate media.

## Payment roles

Migration `0014_payment_execution_contract.sql` adds ten content-minimized
payment tables, RLS, immutable transition guards and fixed catalogue/amount
constraints. It intentionally contains no `GRANT` or `REVOKE`. The exact
production privilege task must reproduce this positive matrix:

| Role | Exact positive payment access |
|---|---|
| `noteai_app` | `SELECT, INSERT` `payment_orders`; column `UPDATE(user_id,provider_payment_id,payment_status,updated_at,terminal_at)`; `SELECT` positions/consumptions; position `UPDATE(user_id,remaining_milli,state,updated_at)`; consumption `INSERT` and `UPDATE(state,updated_at)` |
| `noteai_payment` | `SELECT` all ten payment tables; `INSERT` refunds, events, cash/entitlement ledgers, positions, reconciliation runs/items and settlements; exact order/refund/event/position update columns |
| `noteai_admin` | read-only `SELECT` on all ten payment tables |
| `noteai_ai_worker` | `SELECT` positions/consumptions; position `UPDATE(remaining_milli,state,updated_at)`; consumption `UPDATE(state,updated_at)` |
| dispatcher, Trends, Tracking | zero payment-table access |

`noteai_payment` additionally needs only:

- `SELECT(id,deletion_requested_at)` on `users`;
- selected `id,user_id,tier,started_at,is_active` subscription columns,
  subscription `INSERT` and `UPDATE(is_active)`;
- selected `user_id,balance,total_purchased` credit columns, credit `INSERT`
  and `UPDATE(balance,total_purchased,updated_at)`;
- `INSERT` on `credit_transactions`;
- `SELECT(user_id,recorded_at,credits_used,source)` on `usage_records`;
- effective `EXECUTE` on `pg_catalog.hashtext(text)` and
  `pg_catalog.pg_advisory_xact_lock(bigint)`.

The HTTP payment boundary must connect using this exact role and exposes only
liveness, readiness and the Adapay callback. The normal API role may create
owner-bound order intent and submit through the injected adapter, but its
compatibility callback route always rejects and it cannot mutate callback,
cash, refund or reconciliation truth.

Every unlisted table/column/sequence privilege remains false. All eight
`public.noteai_payment_*_v1()` trigger functions must have direct `PUBLIC`
execution revoked; no runtime role may own them, execute them directly or
hold grant option. Runtime trigger invocation remains valid. The payment role
has no profile credentials/content, auth/session, Admin, prompt, XHS,
Tracking, Trends, AI payload/result, object storage or migration access.
`noteai_app` insertion is RLS-limited to a clean `created` order; its
`user_id=NULL` update remains available for account-deletion pseudonymization
of settled rows only when every other order field is unchanged. Repointing an
order to another user, restoring a nulled join or smuggling any state change
through the pseudonymization update is rejected by the order identity guard.
Catalogue version, product and exact integer-fen price are enforced
persistently, not trusted only to application code.

## Admin role

The first-launch Admin contract is defined in
`docs/FIRST_LAUNCH_UI_ADMIN_CONTRACT.md`. Production Admin must connect as a
dedicated `noteai_admin` login, never as `noteai_app`. Its only positive DML is:

- `admin_sessions`: `SELECT, INSERT, DELETE`; no `UPDATE`, `TRUNCATE`,
  `REFERENCES`, `TRIGGER`, ownership or grant option;
- read-only `SELECT` needed by the integrated Admin views on `users`,
  `subscriptions`, `credits`, `credit_transactions`, `notes`,
  `usage_records`, `model_usage_records`, `system_settings`,
  `managed_prompts`, `prompt_history`, `tracked_notes`,
  `ai_operations`, `ai_operation_settlements`, `ai_operation_outbox`,
  `xhs_freshness_ledger`, `xhs_crawler_health`, `xhs_trends_runs` and the ten
  payment tables described above.

The final PostgreSQL permission task must generate the exact positive
table/column set from current Admin SQL, add any required `noteai_admin` RLS
read policy, and prove every unlisted table/column/sequence/function privilege
false on disposable PostgreSQL. Admin receives no sequence privilege, business
DML, Prompt/model/Crawler/Tracking mutation, schema/database creation, TEMP,
DDL, role membership, superuser, `BYPASSRLS`, `schema_migrations`, ownership or
grant option.

Do not force the whole Admin connection to
`default_transaction_read_only=on`: that makes the exact session
`INSERT`/`DELETE` contract unusable. The application itself fails closed on
every business mutation in production, while database ACL/RLS supplies the
independent persistent boundary.

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
