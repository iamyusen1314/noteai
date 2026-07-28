# NoteAI Internal Production Readiness Handoff

> Updated: 2026-07-29 (Asia/Shanghai)
>
> This file is the current Secret-free recovery source. After context
> compression, re-read this file, Git, the readiness manifest and the risk
> register before continuing.

## 1. Objective and standing authority

- Umbrella task: `PROD-COMPLETE-FIRST-LAUNCH-001`.
- Goal: internal deployment readiness `29/29`.
- Main CTO may approve finite, bounded, reversible internal-production work
  without repeated product-owner confirmation.
- Do not stop merely because a task, checkpoint, cleanup or Handoff completed.
  Continue through the dependency graph.
- Stop only for interactive login/new credentials, public DNS or real traffic,
  irreversible destruction, uncapped cost, a new product decision, public
  launch declaration, a true security conflict, a database-connected UNKNOWN
  result or genuine technical inability.
- Never print or persist Secret values, credentials, private keys, cookies,
  complete connection strings, IP addresses, cloud resource IDs, user data or
  long raw logs. Never force-push, merge directly to `main`, run concurrent
  production writes or automatically retry a database-connected failure.

## 2. Git and readiness truth

- Branch: `codex/quality-stabilization-real-chain`.
- ROOT-CAUSE-003 base:
  `6dd7d6d6df22c92b39d51445ce543ee3658894aa`.
- Historical V4 package binding:
  `13377d7ac37b090818c56be545f34a7ac5587d49`.
- Historical V4 exact execution source:
  `8f6b8b68e24726ab6a57abfb805b9fd222238d0f`.
- Schema executor legacy-ledger repair:
  `e5883abc01c4b009907bee550209d7036d383771`.
- Resolve the pushed ROOT-CAUSE-003 checkpoint from the newest
  `[skip render]` commit; do not embed a self-referential hash here.
- Repository/isolated readiness: `12/12`.
- Internal deployment readiness: `14/29 = 48%`.
- Public launch readiness: `14/38 = 37%`.
- Public launch completion: false.

## 3. Preserved production incident boundary

- V3B and V4 are both
  `CONNECTED_KNOWN / ROLLED_BACK / DATABASE WRITES 0 / CLEAN`.
- Never retry either database action.
- V4 passed its fresh backup/private-network/zero-residue/API checks, exact
  remote package verification, network-none import and forced-readonly
  pre-dispatch before its one apply.
- V4 returned the sanitized coarse stage `apply_runtime_acl_failed`.
- The independent forced-readonly outcome audit proved the transaction rolled
  back and all five permitted write categories were zero.
- Production therefore remains exactly:
  - ledger migrations `0001`-`0008`;
  - 30 public tables;
  - 5 public sequences;
  - 2 historical runtime roles;
  - no SHA backfill, new ledger row, new table, new role, seed, retention
    backfill or existing business-row update.
- Last independently observed cleanup baseline after V4:
  `3 accounts / 1 Super / 0 task accounts`, zero task account/key/ciphertext/
  directory/package/sentinel/result/container/process/Cloud Shell residue;
  API-C/API-F/Admin active, ready and loopback-only.
- ROOT-CAUSE-003 made no production database, cloud, service, provider or
  public-traffic action. The next production read-only task must refresh the
  cleanup and service baseline rather than inherit browser memory.

Historical evidence:

- `deploy/production/evidence/production-schema-roles-v4-rolled-back-20260728.json`
  - 26 files including manifest;
  - 25/25 hashes;
  - 16 migrations;
  - 64,252 bytes;
  - deterministic archive SHA-256
    `0e16fd34404319902b1f15b9b1bccce6394f0ade5fb09ca0dd3979e1158bac5a`;
  - preflight result 3,853 bytes / SHA-256
    `66821db97930871d06fcf8538cbc0626bd820cb3e198c022f0c9d287b4bd7335`.

The older 25-file/62,275-byte package and 3,845-byte result belong to the
accepted-risk read-only audit, not V4.

## 4. First-launch accepted risks

- Exactly two zero-credit accepted risks remain active:
  - the existing `noteai_xhs -> noteai_admin` row is
    `ADMIN TRUE / INHERIT FALSE / SET FALSE`;
  - `noteai_app ROLINHERIT` has incoming membership 0 and high-privilege
    inheritance 0.
- They are `ACCEPTED_RISK`, never `VERIFIED_FIXED`, and are reviewed 30 days
  after first public launch.
- They authorize no new `noteai_xhs` role, membership, ADMIN OPTION, DDL,
  ownership, role management or database privilege.
- Provider support remains an optional post-launch remediation, not a
  first-launch blocker.

## 5. Completed unique task: ROOT-CAUSE-003

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-RUNTIME-ACL-ROOT-CAUSE-003`

Status:
`REPOSITORY + DISPOSABLE POSTGRESQL VERIFIED / PRODUCTION UNCHANGED`.

Exact root cause:

1. Alibaba RDS PostgreSQL exposes no native PostgreSQL superuser.
2. PostgreSQL 16 always gives a NOSUPERUSER+CREATEROLE creator implicit
   `ADMIN OPTION` on each role it creates. The default empty
   `createrole_self_grant` only omits `INHERIT` and `SET`.
3. V4 created six runtime roles directly as the short-term managed-RDS
   privileged executor.
4. PostgreSQL therefore created six
   `new_runtime_role -> executor / ADMIN TRUE / INHERIT FALSE / SET FALSE`
   rows.
5. With the one accepted legacy row, the old exact-one assertion observed
   seven rows and failed inside the first runtime ACL `role_contract` block.
   Database/schema ACL was not reached.
6. The old disposable fixture used a native superuser for role creation and
   could not reproduce this managed-RDS behavior.

Corrected V5 owner contract:

- Activate persistent `noteai_admin` with `SET LOCAL ROLE` inside the bounded
  transaction before advisory lock or writes.
- Require `noteai_admin` to be non-native-superuser, have `CREATEROLE`, own the
  current database and own every existing/new public relation and function.
- Create the six new NOLOGIN roles as the persistent owner.
- Require exactly six owner management rows, each
  `ADMIN TRUE / INHERIT FALSE / SET FALSE`; they allow role administration
  but no privilege inheritance or `SET ROLE`.
- Preserve the one historical accepted-risk row separately.
- Require unexpected membership, runtime ownership, migration-owner mismatch
  and short-term-executor ownership all to be zero.
- Split runtime ACL into ten fixed sanitized stages:
  `role_contract`, `database_schema`, `clear_new_roles`, `api`, `tracking`,
  `trends`, `durable_ai`, `private_storage`, `payment`, `admin`.
- Use the new task root `/var/lib/noteai/schema-roles-v5-owner`; never reuse
  the V4 directory or runner identity.
- Distinguish `apply_transaction=committed` from
  `audit_transaction=rolled_back` in runner summaries.

Secret-free evidence:

`deploy/production/evidence/production-schema-runtime-acl-root-cause-20260729.json`

Current hashes:

- executor:
  `56d148fbbbadc2f8b15c6cfdc5ef978f10b79dbd86dbbf5ccb272dc1ce23972a`;
- outcome auditor:
  `223ee1df52e53ef53a7e3247d78a8d4e40e4792876032807d78a25d8a04861fb`;
- read-only preflight:
  `2d873101db846689be20d8fee2d4adb21017fe51c54cc4ebfaffd54e58d3ad17`;
- runtime ACL:
  `b5fc9e7074c09b0ca26368049225873a6b342b810a17aab48ec7b89278a672d7`;
- V5 runner:
  `fea169abd58fa37b0c5c4c446abfc8ae6f7f38ab908e111b6f3cd1b78c8672bf`;
- unchanged 16-migration aggregate:
  `a6cc4fef8d988adb05108edeb16d8b520f600e4fd3bac06f61812c3db24ada73`.

Disposable PostgreSQL 16 proof:

- `2/2` integration tests passed.
- The first test pinned the implicit ADMIN edge and proved the non-super
  creator cannot remove the bootstrap-granted row itself.
- The second used a distinct short-term executor, activated the persistent
  owner, completed first apply, apply-twice, independent outcome and six
  negative mutations, then actually deleted the executor.
- First apply exact counts:
  `8 SHA backfills + 8 ledger inserts + 2 fixed seeds + 0 retention +
  0 existing business updates`.
- Apply-twice: all five categories zero.
- Owner mismatch, executor-owned objects and executor residue: zero.
- Focused schema/outcome unit tests: `24/24`.

Local diagnostic failures were bounded:

- three package mount/import failures were `PRE_CONNECT`;
- two disposable SQL probes were
  `CONNECTED_KNOWN / ROLLED_BACK / WRITE 0`;
- local `CONNECTED_UNKNOWN` count was zero;
- none involved production.

## 6. Unique next task

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-OWNER-AUTHORITY-PREFLIGHT-004`

Execution class: authenticated production, forced read-only only.

Required result:

1. Reconfirm fresh successful full backup, zero public RDS endpoint, exact
   account/task residue counts and API-C/API-F/Admin loopback health.
2. Rebuild a minimal package only from the pushed ROOT-CAUSE-003 checkpoint;
   verify every hash and complete zero-DSN/network-none imports before any
   protected database material.
3. Use one protected read-only connection/transaction, terminal `ROLLBACK`,
   with fixed aggregate queries only.
4. Reconfirm exact ledger `0001`-`0008`, 30 tables, 5 sequences and the two
   accepted-risk tuples.
5. Prove without changing state that:
   - `noteai_admin` is the database owner;
   - every existing public relation/function is owned by `noteai_admin`;
   - the role is non-native-superuser with the required `CREATEROLE`;
   - schema owner/grant-option requirements are satisfied;
   - the protected executor can activate the owner;
   - task/executor ownership and dependency counts are zero.
6. Save one Secret-free deterministic result, clean all transient material,
   and read back the baseline.

This task cannot create roles, alter memberships, run migrations, update the
ledger or open a V5 write transaction.

If and only if the read-only preflight passes, the later unique write incident
must be separately named (V5), use a fresh one-transaction allowance and
retain zero automatic retries. It cannot inherit V4 authority.

## 7. Mandatory failure classification

After any nonzero exit or tool failure, collect Secret-free sentinels,
process/container counts, connection/transaction state and result evidence:

1. `PRE_CONNECT`: prove database connection, transaction and write are zero;
   clean exact material; continue only after a material correction.
2. `CONNECTED_KNOWN`: preserve the deterministic result, never retry that
   database action, complete required cleanup and continue only with a
   separately authorized non-retry path.
3. `CONNECTED_UNKNOWN`: no automatic retry or new database action; preserve
   evidence, clean and stop at that incident boundary.

Read-only diagnosis, process/container/sentinel inspection, connection-count
checks and cleanup do not count as retries and are mandatory after failures.

## 8. Verification and checkpoint requirements

Completed verification:

- focused schema/outcome/readiness tests: `59/59`;
- full Python suite: `1036/1036`, 26 explicit skips;
- production readiness gate: `105/105 PASS`;
- internal readiness: fail-closed `14/29 = 48%`;
- public readiness: `14/38 = 37%`;
- zero-DSN import, Python compile, runner shell syntax, JSON parses and
  `git diff --check`: pass;
- disposable PostgreSQL containers/network/volume: zero;
- temporary package removed from active paths and Colima restored stopped;
- production database/cloud/service/provider/public-traffic actions: zero.

Remaining checkpoint step:

- run the final changed-file Secret/resource scan;
- create a `[skip render]` ROOT-CAUSE-003 checkpoint commit and push normally.

After push, mark ROOT-CAUSE-003 complete, mark OWNER-AUTHORITY-PREFLIGHT-004
in progress and continue without treating the checkpoint as a stop signal.
