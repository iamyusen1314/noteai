# NoteAI Internal Production Readiness Handoff

> Updated: 2026-07-30 (Asia/Shanghai)
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
- PRIVILEGED-OWNER-PREFLIGHT-005 outcome/evidence checkpoint:
  `465505e362752ea7f538d5a6ea821b934ea88863`.
- PRIVILEGED-OWNER-PREFLIGHT-005 source/import-fix checkpoint:
  `7c4204f22aaa109249cef7c2ff84474528a5f106`.
- Corrected V5 owner runner checkpoint:
  `efeb5bb82f09e30066416d6571bfc19f63ab9422`.
- The intermediate V5 checkpoint
  `fa2ebae6e0745effdcc5eb7722ba8e9a90d13f14` was independently found
  insufficiently fail-closed and is superseded. Never package or execute it.
- OWNER-AUTHORITY-PREFLIGHT-004 outcome/evidence checkpoint:
  `8a533ac7c5efd7cbf44cade5287f909fce831a79`.
- OWNER-AUTHORITY-PREFLIGHT-004 source checkpoint:
  `51ae87784d7e1e79358d95c7336c0e12bb2e9c04`.
- ROOT-CAUSE-003 pushed checkpoint:
  `ed5e699896c2f60fc303faa47139a068ac4fdb5f`.
- Exact b55 native source-candidate/VEX checkpoint:
  `d6a06ae5d933b14bd31d8bf5867df2f3c7421839`.
- b55 scanner-cache recovery checkpoint:
  `b981970`.
- b55 build10 scanner-gate checkpoint:
  `4646b17`.
- b55 single full-build launch checkpoint:
  `18335615f3754a8ada424410b20ec59a649b0ddf`.
- b55 build10 43-file acceptance checkpoint:
  `dcced8e39c20fb637a2d0e4b42626b164d68e8bd`.
- Historical V4 package binding:
  `13377d7ac37b090818c56be545f34a7ac5587d49`.
- Historical V4 exact execution source:
  `8f6b8b68e24726ab6a57abfb805b9fd222238d0f`.
- Schema executor legacy-ledger repair:
  `e5883abc01c4b009907bee550209d7036d383771`.
- V5 exact execution source checkpoint:
  `93d5d3b85688606b97e1716eec3b61d59d5b682d`.
- V5 package-evidence checkpoint:
  `883e874d4186e523b8110d44338c2e074b26c491`.
- Repository/isolated readiness: `12/12`.
- Internal deployment readiness: `18/29 = 62%`.
- Public launch readiness: `18/38 = 47%`.
- Public launch completion: false.

## 2.1 Completed V5 production schema and role deployment

- `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001` is
  `CONNECTED_KNOWN / COMMITTED / INDEPENDENTLY VERIFIED / CLEAN`.
- The exact deterministic package from `93d5d3b` contained 25 source files
  plus one manifest, 16 migrations, 68,915 bytes, archive SHA-256
  `0624644a…9718`, manifest SHA-256 `9494ac7e…d9fc` and runner SHA-256
  `5a906ce7…1ef`. Local and remote hashes, zero-DSN import and network-none
  import all passed.
- Fresh prerequisites proved one private running PostgreSQL RDS, no RDS
  public endpoint, seven successful full backups within seven days with the
  latest under ten hours old, accounts `3/1/0`, zero task residue and healthy
  loopback-only API-C/API-F/Admin.
- One short-term Super account and API-C-only RSA material were created after
  zero-database preparation. No plaintext credential file, environment,
  argument or log was retained.
- The only V5 pre-dispatch database action was a forced-readonly transaction.
  It independently proved ledger `0001`-`0008`, 30 tables, 5 sequences, no
  SHA column/constraint, no new roles/tables, retention source zero and the
  exact two accepted-risk findings; it rolled back with write zero.
- V5 apply was dispatched exactly once and committed exactly
  `8 legacy SHA backfills + 8 migration ledger rows + 2 fixed seeds`.
  Retention backfill and existing business-row updates were zero. Automatic
  retry count was zero.
- One separately dispatched forced-readonly outcome audit independently
  classified `COMMITTED` and rolled back its own transaction. Host-only
  validators checked all result bindings and hashes plus ledger
  `0001`-`0016`, 16/16 migration SHA values, 56 tables, 5 sequences,
  8 runtime roles, 6 new NOLOGIN roles, 7 memberships, 6 owner-management
  memberships, 2 fixed seeds, 3136 table checks, 419456 column checks and
  120 sequence checks. Grant options, default ACL entries, owner mismatches,
  unexpected memberships/elevations, app high-privilege inheritance,
  retention rows and business updates were all zero.
- Results were saved and hashed before cleanup. The task account was deleted
  by one provider request with automatic retry zero, restoring accounts
  `3/1/0`. API-C task root/key/ciphertext/source/sentinels/results/errors/
  containers/processes, four exact-hash Cloud Shell transfer files and all
  task variables were removed. API-C/API-F/Admin remain active, ready `200`
  and loopback-only.
- Secret-free evidence:
  `deploy/production/evidence/production-schema-roles-v5-owner-committed-20260729.json`.
- Current production schema state is `0001`-`0016`; the schema/role control
  receives one readiness credit. The exact two historical role findings
  remain zero-credit `ACCEPTED_RISK`, not `VERIFIED_FIXED`.
- Unique next task:
  `PROD-FIRST-LAUNCH-MANAGED-SECRETS-001`.

## 2.2 Managed-secret source and fresh production pre-dispatch baseline

- The initial managed-secret source checkpoint was pushed at
  `922cfb815415399ae5dcaf8c3d2ade8298ea2627`. The subsequent fresh
  production checks are read-only: production database connections,
  transactions, writes, account changes, service changes, provider calls and
  public traffic remain zero.
- The exact first-launch login set is five roles:
  `noteai_admin_runtime`, `noteai_ai_worker`, `noteai_payment`,
  `noteai_xhs_tracking` and `noteai_xhs_trends`.
  `noteai_ai_dispatcher` remains `NOLOGIN` because no independently deployed
  dispatcher consumer exists.
- `tools/production_managed_secret_roles.py` binds the exact 16-row migration
  ledger and six inert-role graph, then enables the five roles and sets five
  distinct URL-safe passwords in one PostgreSQL transaction. Membership,
  ACL, schema and business-row write counts are fixed at zero.
- `tools/production_managed_secret_files.py` stages root-only files in a
  fixed root-owned task directory, retains exact rollback copies, atomically
  promotes three API-C files and two API-F files, independently verifies
  role-bound DSN usernames/key allowlists/inodes, and removes rollback
  artifacts only after validation.
- The one-time executor generates credentials only in memory. API-F receives
  only an RSA-OAEP-SHA256 plus AES-256-GCM envelope. An API-F-local legacy
  XHS credential, if present, never leaves that host and is deleted with the
  legacy file after the two final XHS files and their read-only logins pass.
  Fresh protected key-name-only observation proves the current legacy
  `xhs.env` contains the `noteai_xhs` database URL but no XHS cookie; exact
  protected searches over `/etc/noteai` and the running API container also
  found no cookie key. The managed-secret control therefore creates the two
  suspended XHS files with their dedicated database URLs only. It does not
  create a placeholder or award provider readiness; a real XHS credential
  remains mandatory before provider runtime activation or public cutover.
- The installed root-owned `0750` rotation/revocation wrappers run the fixed
  lifecycle implementation in a bounded existing API image. Protected input
  is stdin-only. Rotation requires a new read-only login plus rejection of
  the old credential; revocation sets the exact role `NOLOGIN`, removes the
  exact file and requires rejection of the former credential. Neither path
  starts or restarts a service.
- Focused source/file/readiness checks pass `46/46`; the combined focused
  checkpoint passes `47` tests with only the explicitly gated local
  PostgreSQL test skipped. A fresh disposable PostgreSQL 16 run separately
  passes `1/1`, proving the five-role transaction, all five read-only logins,
  rotation rejection and `NOLOGIN` revocation. Its container was deleted and
  Colima was restored stopped.
- Three local test-harness failures were all production `PRE_CONNECT`:
  UID/GID test metadata, transition-state Admin identity and Psycopg
  connection-error SQLSTATE exposure. Each received a material fix; no
  production path was dispatched.
- Fresh control-plane observation proves one private running PostgreSQL RDS,
  no public endpoint, seven successful backups with the latest under
  thirteen hours old, accounts `3/1/0`, no task account and no managed-secret
  control-plane object.
- Fresh API-C/API-F host observation proves both API services and API-C Admin
  are active, ready `200` and loopback-only. Managed-secret task roots,
  maintenance containers, task processes, database connections,
  transactions and writes are all zero. The current narrow source correction
  adds an exact network-none preflight for this real database-only legacy
  state before any account, RSA material or database action may be created.

## 2.3 Historical V5 remote-prepare checkpoint

- The exact package from pushed checkpoint `af58b897` was transferred to
  API-C and independently reverified as 3 parts, 68,781 bytes, 26 regular
  files, 16 migrations, archive SHA-256 `02a01997…1941`, manifest SHA-256
  `a49a9786…9a0` and runner SHA-256 `98afd524…2be1`.
- Fresh production prerequisites were re-established before transfer:
  one running private PostgreSQL RDS, RDS public endpoint 0, three successful
  full backups with latest age under 9 hours, accounts `3/1/0`, two private
  API nodes, API `2/2` and Admin `1/1` active/ready/loopback-only, and task
  residue 0.
- The first remote `prepare` failed before creating any account, RSA,
  ciphertext, runner environment, sentinel, database connection, transaction
  or write. Import/audit container residue is zero. It is conclusively
  `PRE_CONNECT`; no database action was attempted or retried.
- Network-none diagnostics proved that `PYTHONPATH`, `sys.path`, uid 999,
  the source root and `tools/` entry were correct, but the executor file was
  not traversable. Host modes were source root `0755`, intermediate
  `model/scripts/security/tools` directories `0700`, executor `0644` and
  runner `0755`. The production image declares no `/task` or `/task/tools`
  volume. The exact root cause is restrictive extraction umask applied to
  archive-implied directories.
- The runner now verifies all package bytes and nested root ownership before
  any mode change; only `prepare` normalizes source directories to `0755`.
  All modes then require exact directory `0755`, world-readable files and no
  group/world-writable source file. Migration, executor, auditor and runtime
  ACL bytes are unchanged. The fix is pushed at checkpoint `93d5d3b`; runner
  SHA-256 is `5a906ce7…1ef`.
- Focused tests pass `43/43`; production gate passes `105/105`; zero-DSN
  import, shell syntax and diff checks pass. Internal readiness remains
  `14/29 = 48%`.
- The exact mode-fix package was built twice from `93d5d3b` and is
  byte-identical: 25 source files plus one manifest, 16 migrations,
  68,915 bytes, archive SHA-256 `0624644a…9718`, manifest SHA-256
  `9494ac7e…d9fc`, runner SHA-256 `5a906ce7…1ef`, root-owned fixed metadata,
  runner mode `0755`, all other files `0644`, and zero links/AppleDouble.
  Its three chunks are 23,000 / 23,000 / 22,915 bytes with independently
  recorded SHA-256 values. All 25 hashes and package zero-DSN import pass.
- The first local build route stopped because local bsdtar lacks fixed-mtime
  support. It produced no eligible archive and is `PRE_CONNECT`; the
  corrected standard-library USTAR writer was run twice with byte equality.
- Secret-free evidence:
  `deploy/production/evidence/production-schema-roles-v5-owner-remote-prepare-root-cause-20260729.json`.
  `deploy/production/evidence/production-schema-roles-v5-owner-mode-fix-package-20260729.json`.
- Historical next action at that checkpoint was to delete only the proven
  PRE_CONNECT V5 task
  root/chunks, transfer the exact new three-part package and rerun
  network-none `prepare`. That path has now completed through deterministic
  commit, independent outcome and cleanup. Never run V3B, V4, 004 or 005
  again, and never rerun the completed V5 apply.

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
- Before the now-completed V5 deployment, production therefore remained
  exactly:
  - ledger migrations `0001`-`0008`;
  - 30 public tables;
  - 5 public sequences;
  - 2 historical runtime roles;
  - no SHA backfill, new ledger row, new table, new role, seed, retention
    backfill or existing business-row update.
- The current state is now superseded by the V5 evidence in section 2.1:
  ledger `0001`-`0016`, 56 tables, 5 sequences, 8 runtime roles and exactly
  2 fixed service-state seeds.
- Last independently observed cleanup baseline after V4:
  `3 accounts / 1 Super / 0 task accounts`, zero task account/key/ciphertext/
  directory/package/sentinel/result/container/process/Cloud Shell residue;
  API-C/API-F/Admin active, ready and loopback-only.
- ROOT-CAUSE-003 made no production database, cloud, service, provider or
  public-traffic action. The next production read-only task must refresh the
  cleanup and service baseline rather than inherit browser memory.
- OWNER-AUTHORITY-PREFLIGHT-004 subsequently refreshed that baseline and ran
  exactly one forced-readonly audit. It is
  `CONNECTED_KNOWN / READ_ONLY_REJECTED / ROLLED_BACK / WRITE 0`: the existing
  protected API-C Admin runtime credential received SQLSTATE `42501` at the
  fixed `migration_owner_activation` stage and cannot activate
  `noteai_admin`. The audit was not retried.
- Post-004 cleanup was independently read back as
  `3 accounts / 1 Super / 0 task accounts`, zero task material/container/
  process/Cloud Shell residue, and API-C/API-F/Admin active, ready and
  loopback-only.

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
  `98afd524d9cc9524d20b3c76c31076fa9c638f3557b3c699577d190d763e2be1`;
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

## 6. Completed unique task: OWNER-AUTHORITY-PREFLIGHT-004

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-OWNER-AUTHORITY-PREFLIGHT-004`

Status:
`CONNECTED_KNOWN / READ_ONLY_REJECTED / ROLLED_BACK / WRITE 0 / CLEAN`.

- Source checkpoint: `51ae87784d7e1e79358d95c7336c0e12bb2e9c04`.
- Minimal package: 26 files including manifest, 25 manifest hashes,
  16 migrations, 64,889-byte deterministic gzip,
  SHA-256 `f872ed201597e902ac91b8cbced3f41f829c95f0ac254b4bc30512ff5b794f51`.
- Local zero-DSN import, remote `25/25` hashes and remote network-none import
  all passed before database dispatch.
- Fresh control-plane and host checks proved one running private RDS,
  a successful full backup younger than 48 hours, `3/1/0` accounts, zero task
  residue and healthy loopback-only API-C/API-F/Admin.
- Exactly one audit established one database connection and a repeatable-read,
  read-only transaction. It failed deterministically at
  `migration_owner_activation` with SQLSTATE `42501`, then rolled back.
- Result bytes were zero; the sanitized error artifact was 218 bytes.
  Database writes, role changes, business-value reads and automatic retries
  were all zero.
- The owner-contract and production-state aggregate queries were not reached,
  so this audit does not claim a fresh ledger read. The known rollback and
  zero-write result preserve the last independently proven production state
  at `0001`-`0008`.
- The exact fixed task directory, package, sentinels/results/errors, containers,
  processes and Cloud Shell task state were removed. Final account state was
  `3/1/0`; API-C/API-F/Admin remained active, ready and loopback-only.

Secret-free evidence:

`deploy/production/evidence/production-schema-owner-authority-preflight-known-failure-20260729.json`

This database action must never be retried. Its result only rejects the
existing runtime Admin credential as an owner-activation executor.

## 6.1. Completed unique task: PRIVILEGED-OWNER-PREFLIGHT-005

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-PRIVILEGED-OWNER-PREFLIGHT-005`

Status:
`VERIFIED_READ_ONLY_CLEAN / CONNECTED_KNOWN / ROLLED_BACK / WRITE 0`.

- Production used exact pushed source `7c4204f`; the final deterministic
  package contained 26 source files plus manifest, 16 migrations, 67,915
  bytes, manifest SHA-256 `e359e44b…4439` and archive SHA-256
  `66af35f6…0fc6`. Local top-level zero-DSN import, all hashes and remote
  network-none import passed.
- Fresh baseline proved one running private PostgreSQL instance, two
  successful full backups within 48 hours, accounts `3/1/0`, two API nodes
  with no public address, API-C API/Admin and API-F API active/ready and
  loopback-only, and zero task residue.
- One short-term managed-RDS privileged account and one API-C-only RSA keypair
  were created. Plaintext credential files, environment, argv and logs were
  zero; provider automatic retry was disabled.
- Exactly one database audit ran. It proved the executor is a non-native
  superuser with exactly one direct managed-privileged membership, no other
  direct/owner/runtime membership or object/shared dependency, and can
  activate `noteai_admin`.
- The activated persistent owner is non-superuser+CREATEROLE, owns the
  database and all existing public objects, and has the required schema
  grantable CREATE capability with owner mismatches zero.
- The same read-only snapshot independently re-established exact production
  state: ledger `0001`-`0008`, 30 tables, 5 sequences, no ledger SHA column,
  2 historical runtime roles, the exact two accepted-risk findings, no
  high-privilege app inheritance, no retention source and no task-role
  residue.
- The audit result was 4,111 bytes / SHA-256
  `fad95eaaa743ae6d87de75ead76468c1fe971c6bc829c0ba1dad7a154482ad2e`.
  A separate host-only validator checked its hash and complete fixed field
  matrix. The database transaction rolled back; writes and business-row value
  reads were zero. This database action is permanently no-retry.
- All packaging, shell, route, cleanup and Cloud Shell transport failures were
  independently proven `PRE_CONNECT` with database connection, transaction
  and write zero, then materially corrected without repeating a database
  action.
- Cleanup saved and hashed the result first, read back containers/processes
  zero, deleted the short-term account once with provider retry disabled,
  restored accounts `3/1/0`, then deleted RSA/ciphertext/source/result/
  sentinel/error/task-root and Cloud Shell task files/variables. Final RDS
  public endpoint and public API-node counts are zero; API-C/API-F/Admin remain
  active, ready and loopback-only.

Secret-free evidence:

- `deploy/production/evidence/production-schema-privileged-owner-preflight-local-20260729.json`
- `deploy/production/evidence/production-schema-privileged-owner-preflight-remote-prepare-20260729.json`
- `deploy/production/evidence/production-schema-privileged-owner-preflight-verified-20260729.json`

005 receives zero readiness credit because it is a capability preflight.
Internal readiness remains `14/29 = 48%` until V5 commits and passes an
independent complete outcome audit.

## 6.2. Unique next task

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V5-OWNER-001`

Execution class:
separately named authenticated production single-transaction incident.

Stage-safe runner stabilization:

- `tools/production_schema_roles_runner.sh` now uses the production-proven
  `/task/tools` Python path and top-level imports in both network-none prepare
  and database modes, eliminating the installed-image namespace collision.
- Preflight, state-changed preflight, apply and both COMMITTED/ROLLED_BACK
  outcomes are parsed as structured JSON and must match the complete fixed
  ledger, inventory, owner, role, risk, table/column/sequence/default-ACL,
  exact-write and zero-external-action contracts.
- Validation uses isolated Python with explicit fail-closed checks, contains
  no optimization-removable `assert`, and is executable-tested under
  `PYTHONOPTIMIZE=1`; a tampered retention write count is rejected.
- Incident identity is bound to the package-manifest hash. Each saved result
  is separately bound to incident, manifest, mode and result hash; apply
  revalidates the exact saved preflight binding before writing, and outcome
  revalidates any successful apply result binding.
- Decrypt and task stderr are separate root-only files. A successful mode
  requires both to be empty; known nonzero exits are accepted only through
  exact structured state-change output or one fixed sanitized error line.
  Grep-only result acceptance and broad exit-code classification are removed.
- Task/source/key/ciphertext ownership, modes, symlink count and hard-link
  counts are fail-closed. Every prepare, preconnect, known, unknown and success
  terminal summary keeps `cleanup_required=1` until external cleanup readback.
- New runner SHA-256:
  `98afd524d9cc9524d20b3c76c31076fa9c638f3557b3c699577d190d763e2be1`.
- Executor, outcome auditor, preflight auditor, runtime ACL and all migration
  bytes remain unchanged. Final focused tests pass `43/43`; runner syntax,
  top-level zero-DSN import and diff checks pass.
- This repository-only step made zero production database, cloud, account,
  service, provider or public-traffic action and receives no readiness credit.

Exact pushed V5 package:

- Source checkpoint:
  `af58b8978822cf698303ae8c8c0fb8f281768fa4`.
- Closure: 25 source files plus one manifest, 16 migrations.
- Manifest SHA-256:
  `a49a97861516716db8c0e5e6a5d942ff74da82153208a133693e40a057c849a0`.
- Deterministic archive: 68,781 bytes, SHA-256
  `02a019972d79de032c58e17d4b2fd1bea13e1ea0cc56748cf55e6a6c0671941b`;
  two independent builds are byte-identical.
- All 25 hashes, exact 26 regular archive members, root ownership metadata,
  runner mode `0755`, zero AppleDouble/link/non-regular members and package
  zero-DSN top-level import passed.
- One recursive-member build, one rejected local cleanup command and one
  auxiliary validator quoting error were independently classified
  `PRE_CONNECT`; all had production connection/transaction/write/account/RSA/
  cloud/service/provider/public-traffic counts zero. Only the corrected
  ordinary-file archive is eligible for transfer.
- Secret-free evidence:
  `deploy/production/evidence/production-schema-roles-v5-owner-local-package-20260729.json`.

Required path:

1. Commit and push the hardened runner source checkpoint, then build a fresh deterministic
   minimal package from that exact commit. Do not reuse 005 or V4 package,
   account, RSA, root, runner identity or result.
2. Repeat only the production-write prerequisites: fresh backup/private
   network/`3/1/0`/zero-residue/service checks, all hashes, zero-DSN and
   network-none imports.
3. Create one fresh short-term managed-RDS privileged account and fresh
   API-C-only RSA material with the same protected-input boundary.
4. Run one fresh forced-readonly V5 pre-dispatch proving exact ledger
   `0001`-`0008`.
5. Execute V5 apply at most once. The only permitted writes are
   `8 legacy SHA backfills + 8 new ledger rows + 2 fixed seeds`;
   retention backfill and existing business-row updates must be zero.
6. Any database-connected apply failure is permanently no-retry. Preserve the
   result and run only the predeclared independent forced-readonly outcome
   classifier.
7. Require a deterministic `COMMITTED` outcome plus the complete ledger SHA,
   inventory, role/table/column/sequence/function/default-ACL negative matrix,
   zero elevation and exact write counts before marking
   `production_schema_roles` verified.
8. Save Secret-free evidence, restore accounts `3/1/0`, delete all task
   material, read back services/network/residue, checkpoint/push, then
   continue to the dependency graph without stopping.

## 6.3 Completed V5 and unique next task

The required path in section 6.2 is now complete. V5 apply and its independent
outcome are permanently no-retry. Do not repeat package preparation,
pre-dispatch, apply or outcome without real conflict evidence.

Unique next task:
`PROD-FIRST-LAUNCH-MANAGED-SECRETS-001`.

Execution objective:

1. Reuse the now-created dedicated production runtime roles; do not create or
   alter schema, roles, memberships or accepted-risk tuples.
2. Inspect the existing Secret-free managed-secret audit and the production
   runtime consumers before changing files.
3. Build one minimal fail-closed distribution/rotation/revocation path for the
   final API, Admin, Payment, AI Worker, Trends and Tracking runtime files.
4. Keep each Secret in a distinct root-owned `0600` file. The protected
   API-F-local legacy XHS value may be read only in memory to create the two
   final XHS role files on that same host, after which the legacy file must
   be deleted. Never move that value through Cloud Shell or into a non-XHS
   role, never print values, and never persist plaintext outside its final
   protected files.
5. Verify consumers by key names, modes, owners, service identity and bounded
   loopback health only. Do not start Payment, Worker, Trends or Tracking as
   part of the secret-distribution control.
6. Use an explicit rollback copy or atomic replacement for every changed
   runtime file. Rotation must prove the old credential is rejected or
   revoked without exposing either value.
7. Save Secret-free evidence, run focused gates, checkpoint/push, mark only
   `managed_secret_distribution` verified, and continue to the next
   dependency. Public DNS, real traffic, real XHS and public-launch
   declaration remain prohibited.

## 6.4 Managed Secrets live pre-connect correction

- Fresh cloud readback, rather than browser memory, found both execution nodes
  at zero task residue before staging. The exact package was transferred to
  both nodes; API-C extraction/hash checks passed and API-F retained only the
  exact archive. No task account, RSA, ciphertext, runner sentinel, task
  container, PostgreSQL connection, transaction or write was created.
- API-C `prepare` failed under `--network none` because the historical running
  API image lacks `cryptography`; all other managed-secret imports passed.
  Independent process/container/5432/result checks classified this
  `PRE_CONNECT`. It does not authorize a database retry because no database
  action occurred.
- The immutable current-source API image already verified by ACR digest,
  local-image identity, AMD64 SBOM and VEX contains exactly one
  `cryptography 48.0.1`. The smallest reliable correction pins the execution
  runner and installed rotate/revoke wrapper to that exact digest and image
  ID, instead of discovering the historical running service image. It does
  not deploy, restart or modify the API service.
- ACR discovery found one running Shenzhen registry instance. An initial token
  request inherited the wrong default region and returned before any token,
  pull or host action; explicit `cn-shenzhen` returned a temporary-token
  response. This is `PRE_CONNECT`. Credentials must remain in memory or an
  RSA-encrypted envelope and must never enter Cloud Assistant command content,
  process arguments, logs or Git.
- Changed files:
  `tools/production_managed_secret_runner.sh`,
  `scripts/production/noteai-managed-secret-lifecycle-wrapper`, and
  `tests/test_production_managed_secret_runtime.py`.
- Focused tests pass `26/26`; both shell files pass `bash -n`. The updated
  wrapper SHA-256 is bound into the runner. Before any database action, commit
  and push this source checkpoint, build a new deterministic package, remove
  the old PRE_CONNECT package roots, pull the exact maintenance digest through
  a temporary protected ACR login on API-C then API-F, and repeat only
  network-none prepare/preflight.

## 6.5 Managed Secrets production completion

`PROD-FIRST-LAUNCH-MANAGED-SECRETS-001` is production `VERIFIED` and its
database transaction is permanently no-retry.

- Exact execution source was the pushed `ee2ff4f08f04aa85f613ba7c9701832e7135eb83`
  checkpoint. Two deterministic packages were byte-identical: 25,588 bytes,
  14 archive members and SHA-256
  `18010ee49f0d71312b7e2ac45ae980c2309bf47567d3313c92d4c76628294ec6`.
  Local zero-DSN import, both remote manifests and both network-none imports
  passed against the pinned maintenance image.
- Fresh prerequisites proved one private running PostgreSQL instance, no
  public endpoint, two successful full backups within 48 hours, initial
  accounts `3/1/0`, zero task residue and API-C/API-F/Admin
  active/ready/loopback-only.
- One short-term task account and three RSA keypairs were created through the
  protected boundary. Plaintext Secret files, argv, logs and Cloud Shell
  values remained zero. Forced-readonly pre-dispatch used one connection and
  terminal rollback, proved ledger 16, six runtime roles, dispatcher
  `NOLOGIN`, fixed membership seven, unexpected membership/ownership zero and
  database writes zero.
- The only production transaction was dispatched once with automatic retry
  zero and deterministically `COMMITTED`: five runtime roles became LOGIN and
  received five new passwords; membership, ACL, schema and business-row writes
  were zero. Do not rerun it.
- File promotion then failed after commit with the fixed
  `connected_known_committed_file_promotion` code. An independent five-byte
  network-none probe proved `EXDEV`: the staging root and `/etc/noteai` target
  were separate container mounts. This was `CONNECTED_KNOWN / COMMITTED`, not
  an unknown database outcome. API-C was recovered once from the exact
  encrypted bundle using `/etc/noteai/.managed-secrets-v1`; API-F received
  only its encrypted envelope and used the same same-filesystem promotion.
  Both recovery paths had database connection/transaction/write zero.
- Independent role-bound audits used four API-C plus three API-F forced
  read-only connections and verified the full negative matrix, zero elevation,
  incoming membership, ownership, ledger access, business-value reads and
  writes. A separate global forced-readonly verifier proved ledger 16, five
  LOGIN roles, one NOLOGIN dispatcher, six owner-management memberships,
  unexpected membership zero and owned objects zero.
- Final metadata is four API-C and three API-F distinct root-owned `0600`
  files, zero rejected/duplicate keys or backup artifacts, two root-owned
  `0750` rotate/revoke tools on each node and no legacy `xhs.env`. Trends and
  Tracking intentionally contain database credentials only; real provider
  credentials remain a separate runtime/public-launch gate.
- Secret-free result hashes were independently inventoried before cleanup.
  Finalize removed rollback roots. The short-term account was deleted through
  exactly one provider request with automatic retry zero; all execution roots,
  RSA/ciphertext/source/sentinels/results/errors, task containers/processes and
  Cloud Shell task files are zero.
- The new post-activation account baseline is `8/1/0`, not the historical
  `3/1/0`: three existing accounts plus the five expected dedicated runtime
  LOGIN accounts, one Super and zero task accounts. The exact runtime set is
  five and unexpected accounts are zero. RDS remains private with two fresh
  full backups; API-C/API-F/Admin remain active, ready and loopback-only.
- The repository default staging root is corrected to
  `/etc/noteai/.managed-secrets-v1` in
  `tools/production_managed_secret_files.py` and the host runner, with a
  regression assertion binding it to the `/etc/noteai` mount. This source fix
  is for future lifecycle runs and does not require production reexecution.
- Authoritative Secret-free evidence:
  `deploy/production/evidence/production-managed-secret-distribution-verified-20260729.json`.
  `managed_secret_distribution` is now verified; internal readiness is
  `16/29 = 55%` and complete public readiness is `16/38 = 42%`.

Unique next task:
`PROD-FIRST-LAUNCH-STORAGE-RECOVERY-RUNTIME-001`.

Required next path:

1. Reuse the verified private-storage repository contract and current immutable
   image identities. Do not repeat schema, role, managed-secret, registry,
   SBOM/VEX, Gate 0 or historical service recovery work without conflict
   evidence.
2. Read the storage runtime contract, current API-C/API-F consumers and
   production object-storage/RAM state before mutations.
3. Prefer a private, least-privilege, bounded-cost bucket and role path with
   explicit rollback and Secret-free evidence. Do not enable public access,
   DNS or real user traffic.
4. Prove cross-node recovery with synthetic task data only, delete all
   synthetic objects and temporary permissions, then read back private access,
   lifecycle/recovery controls, API/Admin non-regression and zero residue.
5. Mark only `private_storage_runtime` verified, checkpoint/push and continue
   to the next dependency without stopping at the task boundary.

## 6.6 Private-storage runtime source checkpoint

- Fresh Git takeover from `e9a7a5207d52a22d12a8062edabfa55342f76df8`
  proved the expected branch, a clean worktree and upstream divergence `0/0`.
  The authoritative manifest is `16/29`; the older `15/29` values at the top
  of this Handoff were corrected without changing evidence credit.
- Three independent read-only audits agree that this task must reuse the
  verified V5 schema/role state, managed-secret distribution, immutable
  release identities and repository storage contract. Production database
  connections, transactions and writes for this task are fixed at zero.
- Source inspection found two deployment-consumer gaps without changing the
  storage protocol: the Durable AI Worker did not initialize the explicit OSS
  adapter, and the recovery evidence CLI did not initialize OSS before an
  object-inclusive capture. `model/durable_ai_worker.py` now invokes the same
  fail-closed environment initializer as the API before any accepted runtime
  command. `tools/recovery_evidence.py` now initializes it only for an
  object-inclusive capture; `--database-only` and `verify` remain storage
  network-free.
- Focused storage/Worker/readiness regression is `63/63`; Python compile and
  `git diff --check` pass. No production database, service, provider, object or
  cloud mutation occurred. Two local search commands and one already-removed
  SQLite sidecar cleanup probe returned nonzero with production connection,
  transaction and write zero; all are `PRE_CONNECT`.
- Before any cloud write, create and push a source checkpoint, then obtain a
  fresh Secret-free OSS/RAM/ECS/API baseline through the stable CLI/Cloud
  Assistant path. Do not use iframe/DOM repair, static access keys, a public
  bucket/endpoint, real user data or a service restart.
- The source checkpoint was pushed normally at
  `a459d8189e3e2a2ce9ae39ce1c9b20f1df2e69c6`; the worktree was clean and
  upstream divergence `0/0`.
- The original in-app Cloud Shell session was expired, and the local host had
  no Alibaba CLI/profile. A separately authenticated Chrome Cloud Shell was
  reconnected without interactive login, and the optional paid NAS was
  explicitly declined. The official CLI is available; no standalone OSS
  binary or OSS Python package was installed in the ephemeral shell.
- Fresh read-only control-plane discovery found three buckets total, one in
  the production region and zero NoteAI regional buckets. Account-level Block
  Public Access is currently false. Three running NoteAI ECS instances exist;
  the one with a public address is excluded. The exact two private VPC API
  instances both match the API naming boundary and have zero attached RAM
  roles, so there is no replacement conflict. Their metadata-token mode is not
  exposed by the control-plane response and must be proved from the hosts.
- The credential adapter is now explicitly IMDSv2-only:
  `enable_imds_v2=True`, `disable_imds_v1=True` and a bounded 60-second
  metadata token. The first focused run failed two old source-shape checks
  with production/cloud actions zero (`PRE_CONNECT`); the gates now assert
  the stronger semantics. Focused regression is again `63/63`, compile and
  diff checks pass. Push this hardening checkpoint before any storage/RAM/ECS
  mutation.
- The IMDSv2 checkpoint was pushed at
  `42500ef27aa48a2b82ede67f5602212e48d4e644`. One private Standard OSS
  bucket, one least-privilege RAM role and one exact custom policy were then
  created and independently read back: public access is blocked, server-side
  encryption is AES256, lifecycle is limited to the `noteai-private/` prefix,
  the policy permits only Put/Get/Delete/List on the exact bucket/object
  resources, both private API nodes require IMDSv2 and static access keys are
  zero. Database connections, transactions, writes, service deployment and
  real-user object writes remain zero.
- The same current-source immutable image and encrypted root-only seven-key
  configuration were prepared on both private API nodes. Network-none import
  initially failed because the absolute acceptance script did not add
  `/app/model` to `sys.path`; zero container/process residue and zero database
  or object action proved `PRE_CONNECT`. The corrected script passed syntax,
  imports and network-none execution on both nodes.
- The first synthetic SDK Put reached OSS and returned
  `SignatureDoesNotMatch`. A separately dispatched forced-readonly Head now
  deterministically proves that exact synthetic object is absent
  (`NoSuchKey 404`); database connection/transaction/write, service write,
  real-user data and retained object count are zero. Therefore the object
  outcome is known and no blind retry is permitted or needed.
- Offline SDK/source inspection and current Alibaba OSS metadata rules locate
  the precise cause: NoteAI's internal metadata keys use underscores, while
  OSS user-metadata header names allow letters, digits and hyphens only.
  The SDK signs the underscored `x-oss-meta-*` headers but OSS does not accept
  that wire shape. The smallest fix maps `_` to `-` only at the Aliyun OSS Put
  boundary; existing Get/Head normalization already maps hyphens back to the
  unchanged internal schema. Focused storage `18/18`, adjacent
  Worker/readiness `45/45`, production gate `105/105`, compile and diff checks
  pass. Checkpoint and push this root-cause fix before one new bounded
  synthetic validation method.
- The metadata fix was pushed at
  `23c6bdde2235c206db1679f2a3c5d998e8d6d049`. Direct host GitHub download
  then failed before creating an overlay, container or object and was
  classified `PRE_CONNECT`. Cloud Shell fetched and hash-verified the exact
  56,490-byte file, split it into three Base64-bounded parts and delivered
  each part serially through Cloud Assistant SendFile. Both nodes reassembled
  the exact SHA, deleted every transfer part and passed network-none import.
- A fresh random synthetic key then received `NoSuchKey 404` from an
  independently dispatched read-only Head. This proved the object absent but
  exposed another adapter boundary defect before any Put: OSS SDK V2 wraps
  service errors in `OperationError`, while `_status` inspected only the
  wrapper. Consequently 404/409/412 could not reach the existing
  not-found/duplicate branches. `_status` now follows only bounded SDK
  `unwrap()`/exception-cause links and still returns only integer HTTP status.
  Focused `63/63`, production gate `105/105`, compile and diff checks pass.
  Push this second exact source checkpoint and replace the overlay on both
  nodes before repeating the fresh read-only two-key preflight.

## 6.7 Private-storage runtime production completion

- The SDK error-unwrapping checkpoint was pushed at
  `b55f11882100e9ef919522540729e366a511f88f`. The exact source overlay was
  hash-verified and passed network-none import on both private API nodes.
- One private Standard OSS bucket, one least-privilege custom RAM policy and
  one ECS-trusted RAM role are deployed only to the exact two private API
  nodes. Block Public Access, private ACL, AES256 encryption, disabled
  acceleration, empty logging target and the exact two-day
  `noteai-private/` lifecycle plus one-day multipart abort are independently
  read back. The policy has exactly four Put/Get/Delete/List actions, no
  wildcard action/resource, no sensitive action and exact prefix/resource
  scope. Static access keys are zero.
- The bounded cross-node matrix used exactly two synthetic objects, each
  under 64 bytes and containing no user data. It proved node-one Put,
  node-two cross-read, node-two Put, node-one cross-read, metadata/SSE,
  duplicate rejection, wrong-prefix rejection, bucket-ACL rejection and
  static-key rejection. Both objects were deleted; independent Head and
  prefix inventory prove residue zero. Never rerun this object write/delete
  matrix without real conflict evidence.
- Both nodes have one root-owned `0600` seven-key configuration with no static
  access key. IMDSv1 is blocked; IMDSv2 token acquisition, exact role identity
  and complete temporary-credential shape pass. API-C/API-F and API-C Admin
  remain active, ready and loopback-only. Task roots, transfer material,
  containers and processes are zero.
- Fresh final RDS control-plane readback proves one running VPC PostgreSQL
  instance, public endpoint zero, accounts `8/1/0`, seven successful full
  backups within seven days and the latest under 48 hours. This storage task
  made zero production database connections, transactions or writes.
- All nonzero tool and parser outcomes were classified before continuing.
  The initial signed object request is `CONNECTED_KNOWN / REJECTED / OBJECT
  ABSENT`, independently verified by read-only Head and never retried for the
  same object. Transport, import, parser, region, quoting and UI-tool failures
  were `PRE_CONNECT` and received material corrections. `CONNECTED_UNKNOWN`
  count is zero.
- Current Cloud Shell exact task files were deleted with `before=9` and
  `after=0`. Final object, host and task residue are zero. Secret-free
  evidence is
  `deploy/production/evidence/production-private-storage-runtime-verified-20260729.json`.
  `private_storage_runtime` receives one readiness credit; internal readiness
  is `17/29 = 59%` and complete public readiness is `17/38 = 45%`.
- Final focused storage/PostgreSQL-contract/Worker/internal-readiness
  regression passes `63/63` with four explicit local PostgreSQL skips;
  production readiness passes `105/105`, Python compile, both JSON parses and
  `git diff --check` pass.

Unique next task:
`PROD-FIRST-LAUNCH-API-C-INTERNAL-001`.

## 6.3. API-C exact-current-image source checkpoint

- API-C must not reuse the already published `b06671f` API image. The current
  storage runtime verified in production is bound to exact source `b55f118`;
  the older image lacks IMDSv2-only credential acquisition, canonical OSS
  metadata headers and bounded wrapped-SDK status extraction. Deploying it
  would regress a verified control.
- A fresh GitHub-hosted native AMD64 workflow checked out exact `b55f118` and
  built/scanned all five existing runtime targets once. Build, inspect, SBOM,
  secret scan, vulnerability scan and artifact upload completed; the terminal
  raw zero-Critical/High gate failed closed as expected because every role
  retains the same unsuppressed `4 Critical / 19 High` Debian rows as the
  reviewed predecessor.
- The downloaded 43-file artifact is bound by summary SHA-256
  `c6b1f206…162`. Every role independently matches the reviewed base images,
  exact 23 vulnerability rows, affected package set, linux/amd64 platform,
  entrypoint/CMD and finding counts. Secrets, browser components and forbidden
  OS packages are zero; `cryptography 48.0.1` occurs exactly once per role.
- `tools/verify_b55_native_release_vex.py` preserves the historical b066
  verifier and adds a fail-closed profile for b55. It proves the Docker image
  context changed only in `model/private_storage.py` and
  `model/durable_ai_worker.py`; Dockerfile, pinned runtime requirements,
  entrypoint, hardening contract and process-call graph remain unchanged.
  Source-candidate evidence, VEX and review explicitly keep registry access
  and deployment authorization false.
- The b55 bundle passes its own and the historical native tests `11/11`;
  combined focused readiness tests pass `29/29`; the offline production gate
  passes `106/106`. The VEX validates with zero errors against the exact
  checksum-pinned CycloneDX 1.6 schema. Python compile and diff checks pass.
- No Alibaba production write, registry push, database connection, service
  change, provider call or public traffic occurred in this stage. A local
  summary probe type mismatch was `PRE_CONNECT` and materially corrected;
  database connection, transaction and write counts are zero.

Current next action:

- preserve the recovered build9 task root, log, seven prefix evidence files
  and one local b55 API image. Do not overwrite, clean or redispatch the
  original build;
- reuse only the verified task-owned Trivy cache; do not redownload or fall
  back to either stale cache. Its DB SHA-256 is
  `43c58b4f5d8c99a9480dd018596c2d907ac2df1f87e94f9da859b2563454bfa0`
  and metadata SHA-256 is
  `c22e06141b5631651e7fda582ed629c876b0c500df2d78146053d157b6e4bb59`;
- continue the exact b55 evidence chain only through a source-tree-external,
  hash-bound wrapper with explicit cache, skip-update and offline flags. It
  must now run the unchanged b55 native evidence script in the prepared
  build10 root, fail closed on cache, image, source, scanner or report drift,
  and produce a new self-consistent 43-file bundle before publication;
- independently compare the completed five-role image/SBOM/scan evidence
  with the exact GitHub b55 evidence and reviewed predecessor, then bind new
  ACR manifest digests through one bounded private publication session;
- deploy only the exact API image to API-C through loopback canary and a
  reversible managed-service promotion. Preserve the historical image and
  unit bytes until independent acceptance completes.

## 6.4. API-C interrupted builder reconciliation and scanner gate

- Read-only takeover started from a clean
  `codex/quality-stabilization-real-chain` worktree at
  `d66827f6504c2400c9fa9ba7e04cdf5070ad1f56`. Local HEAD, the upstream
  tracking ref and a fresh remote branch query all match exactly.
- The prior control-plane chain continued after the last Git checkpoint.
  Its latest build9 invocation reached the control-plane timeout and is no
  longer running. A corrected read-only audit found the root-owned task root
  intact, task processes zero, running containers zero, database port
  connections zero, registry requests zero and service actions zero.
- The six-line state file is only the initial fail-closed state because the
  outer timeout prevented the exit trap from finalizing it. The retained log
  is therefore authoritative for this incident: the first API image exported
  successfully after the dependency build, then Trivy 0.72.0 failed while
  downloading `trivy-db:2` over TCP 443. The retained result is one b55 image,
  seven prefix evidence files and no role or total summary.
- The first takeover audit copied collapsed console text and exited before a
  remote connection; it is `PRE_CONNECT` with command, network, Docker,
  database, registry and service actions all zero. The corrected terminal,
  log and cache audits each executed once and were read-only.
- The exact Trivy binary supports `--cache-dir`, `--skip-db-update`,
  `--skip-java-db-update`, `--offline-scan` and DB-only download. Two local
  databases have valid JSON metadata, root ownership, non-symlink regular
  files and non-writable group/world permissions, but both exceed the
  predeclared 24-hour freshness bound and both have expired `NextUpdate`.
  Neither is eligible for continuation.
- Anonymous endpoint probes found the default GCR mirror unavailable and the
  official GHCR and Public ECR endpoints reachable. A first prefetch command
  failed before task-root creation because `pipefail` observed the early
  `grep -q` close; a materially corrected preflight then refused the
  archive-preserved nonroot binary UID, also before task-root creation or a
  network request. Both incidents are `PRE_CONNECT`, with files, processes,
  network requests, Docker, database, registry writes and service actions
  zero.
- Independent provenance proved the build, tools and shared-cache parent
  directories are root-only; the Trivy binary is a non-symlink single hard
  link with no group/world write, the checksum-pinned official archive is
  unique, and its sole `trivy` member is byte-identical to the executable.
  The corrected prefetch therefore replaced the inaccurate UID rule with
  fixed-archive bytes plus root-only containment.
- One anonymous, bounded official-GHCR download populated a new task-owned
  cache. Independent readback proves four root-owned `0700` directories, six
  root-owned `0600` files, no links or special files, exact state/sidecar
  agreement, no log errors and no remaining Trivy process. The DB SHA-256 is
  `43c58b4f5d8c99a9480dd018596c2d907ac2df1f87e94f9da859b2563454bfa0`;
  metadata SHA-256 is
  `c22e06141b5631651e7fda582ed629c876b0c500df2d78146053d157b6e4bb59`.
  `UpdatedAt` and `DownloadedAt` are within 24 hours and `NextUpdate` is
  unexpired. Both historical DB hashes remain unchanged.
- The remote source is exact b55 and its native evidence script, Dockerfile
  and critical runtime inputs match fixed Git hashes. Git porcelain reports
  only the three materialized LFS `.lgb` files; each and the fourth JSON
  artifact match the release manifest, while ordinary diff, staged and
  untracked counts are zero. The builder host's old Python cannot parse
  future annotations, so its model CLI result is `PRE_CONNECT`, not an
  artifact failure. One local-image Python 3.11 check with pull disabled,
  network none, read-only root/source, all capabilities dropped and
  no-new-privileges verified all four artifacts and removed its container.
- A new root-only build10 task copied the verified DB and metadata, then
  installed a source-tree-external Trivy shim. The shim accepts only the five
  fixed b55 image roles and the expected vulnerability/secret output paths;
  it rejects caller-supplied cache/repository/update/offline flags and adds
  the exact cache plus skip-update and offline flags itself. A two-call API
  smoke produced exactly `4 Critical / 19 High / 0 Secret`.
- Independent scanner-prep acceptance verifies the wrapper, state, sidecar,
  reports, source state and both cache hashes; directories/files are
  root-owned `0700/0600`, links and special files are zero, and Trivy
  processes, task containers, all running containers and database port
  connections are zero. This authorizes only the unchanged five-role build
  inside build10, not registry publication or deployment.
- Exactly one full build10 invocation ran the unchanged b55 native evidence
  script against the five fixed roles. It used the source-external scanner
  shim, fixed fresh database hashes, a new empty Docker config and
  deterministic b55 OCI metadata. It did not log in or push to the registry,
  connect to the production database, mutate services or send public traffic.
- The control-plane invocation reached its hard timeout after the native
  script had completed all five builds. Its original post-build wrapper,
  state and sidecar did not run, so the invocation itself remains truthfully
  classified `TIMEOUT`, not `VERIFIED`. The retained native log ends at
  `#28 DONE 0.0s`, has zero fatal matches and produced exactly the expected
  43 raw files: two base indexes, eight files for each of five roles and one
  total summary. Source processes, task/running containers and database-port
  connections are zero.
- A separate task-owned acceptance chain preserved the original timeout and
  never changed the 43 raw files. Its first three fail-closed attempts exposed
  validator-only assumptions: five Buildx metadata files are `0644` inside
  root-only `0700` directories, summary role order is not contractual, and
  build9 used a different OCI-created label so cross-run image-ID equality is
  not a valid gate. Each failed state is retained; no failed attempt produced
  a manifest or acceptance sidecar.
- Corrected v4 acceptance and a separately dispatched read-only audit both
  verified all 43 file hashes, exact file set and modes, five unique current
  image identities, OCI/config/runtime-role contracts, SBOM/report hashes,
  fixed scanner cache and all three failure records. Every role is
  `4 Critical / 19 High / 0 Secret`; browser and forbidden OS packages are
  zero and `cryptography 48.0.1` occurs exactly once. The canonical
  vulnerability-row hash matches the reviewed b55/GitHub bundle.
- v4 summary SHA-256 is
  `a8e1c7ca38e1d5886197f6f727a4fb51ce206817221cc404f4586d29588c41d0`;
  manifest SHA-256 is
  `ec14390c4ccf9515f659ee29dfb20b60e6776d804dfe3005e2c2edb6d7bca865`;
  acceptance-sidecar SHA-256 is
  `e16a3c3d2308a6e4d1b9113d37059933efc4d7965a4f3c12f5cf0a43d9b10a75`.
  The sidecar authorizes only one bounded private Registry publication.
  Deployment, database, service and public-traffic authorization remain false.
- Stage A is complete. Status remains `17/29 = 59%` internal and
  `17/38 = 45%` complete-public because evidence acceptance alone earns no
  readiness credit. The only task remains
  `PROD-FIRST-LAUNCH-API-C-INTERNAL-001`. Stage B below supersedes the former
  publication next step.

## 6.5. API-C b55 private Registry publication completion

- Stage B started only after a fresh control-plane read proved all five exact
  immutable b55 tags absent. The private repository was `NORMAL`, private and
  tag-immutable; its ten historical tags were retained.
- The repository permits one VPC endpoint. The exact production endpoint was
  first snapshotted and removed, the builder-only private endpoint was
  created and read back `RUNNING`, and the ACR public endpoint remained
  disabled. API-C/API-F stayed active, ready `200` and loopback-only during
  this bounded control-plane change.
- A temporary publisher role was recreated after the provider defaulted its
  first version to console-login enabled. The accepted replacement had
  console login disabled, exact ECS trust, a one-hour session bound and one
  custom least-privilege policy: token read plus pull/push on the single
  private repository only. It was attached only to the isolated builder.
- Publisher setup exposed several fail-closed local/control-plane preparation
  defects before any push: two unsupported CLI profile/region forms, one
  overly narrow local profile validator, one token-response shell validation
  error and two task-local state-writer/newline defects. The first returned
  token was never logged, persisted, used for login or used for a registry
  write. Each defect was materially corrected; no push had begun and no
  database, service or public-traffic action occurred. Intermittent console
  result polling failures were read-only UI failures.
- Docker login then used the protected short-lived token. The five exact tags
  were pushed serially in role order, once each, with manual retry zero:
  `git-b55f118-amd64-api-r1`,
  `git-b55f118-amd64-admin-r1`,
  `git-b55f118-amd64-payment-r1`,
  `git-b55f118-amd64-ai-worker-r1` and
  `git-b55f118-amd64-xhs-http-r1`.
- For every role, push return digest, retained manifest descriptor digest and
  ACR control-plane digest are identical; all five are unique, `NORMAL` and
  linux/amd64. The exact manifest digests are respectively
  `sha256:612a7e57…17620`, `sha256:271a089e…79e56`,
  `sha256:ad582745…2e2b`, `sha256:d4c5d0dd…ff34b` and
  `sha256:40644582…1e50`. Each config digest equals the independently accepted
  build10 local image ID and is distinct from its manifest digest.
- Final repository readback is exactly fifteen tags: the ten baseline tags
  plus five new b55 tags. Publication controls record five pushes, five
  manifest readbacks, five control-plane readbacks, five unique digests,
  serial execution and zero manual retry.
- Cleanup removed Docker auth and the temporary auth root, detached the
  builder role, deleted the custom policy and role, and removed the builder
  ACR endpoint. Independent readbacks prove the role and policy absent,
  builder IMDS role endpoint `404`, private ACR DNS zero, task target refs
  zero, running containers/push processes/database connections zero and no
  credentials retained. The exact production ACR VPC endpoint was restored
  `RUNNING`; the public endpoint remains disabled.
- API-C and API-F remain active, ready `200`, loopback-only and each resolve
  exactly one production private ACR address. No service restart/redeploy,
  production database connection/write, business-provider call, public
  endpoint or public-traffic change occurred.
- Nineteen root-only Secret-free publication files are retained for fourteen
  days through `2026-08-13T05:42:21.099Z`. Their file bytes are 66,763,
  directory-tree bytes are 83,147 and the retained `SHA256SUMS` file hash is
  `151f676b27258e0ad02748bf2bb6f475b416ec2a2cd615e8a9df8c67cdd2b3ee`.
  Links, special files, unsafe modes and credential-pattern matches are zero.
- New fail-closed repository artifacts preserve historical b066 files and
  bind exact Stage A, Trivy, build10 SBOM/report, tag, push-log, manifest and
  control-plane identities:
  `tools/verify_b55_registry_release_vex.py`,
  `security/vex/b55f118-registry-publication-attestation.json`,
  `security/vex/b55f118-registry-release-evidence.json`,
  `security/vex/b55f118-registry-release.vex.cdx.json`,
  `security/vex/b55f118-registry-release-review.json` and
  `tests/test_b55_registry_release_vex.py`. The Secret-free attestation stores
  local/config/push/manifest/control-plane observations independently and is
  pinned by both file and semantic SHA-256. Exact tags are compared by role,
  not by a regex or suffix.
- The b55 Registry bundle, historical/current registry tests and production
  integration tests pass. The offline production gate is `107/107 PASS`;
  internal readiness remains fail-closed `17/29 = 59%` and complete-public
  readiness remains `17/38 = 45%`. Stage B earns no readiness credit.
- The only task remains `PROD-FIRST-LAUNCH-API-C-INTERNAL-001`. The next
  acceptance condition is exact-digest private pull plus API-C loopback
  canary, reversible managed-service promotion, explicit restart, independent
  non-regression postcheck and rollback-ready evidence. Only the complete
  chain may verify `api_c_current_release` and advance internal readiness to
  `18/29`.

## 6.6. API-C exact-current release deployment completion

- Stage C began from pushed checkpoint
  `84be4da7b6e9d395f1ed3b33716be6a3465f3c4b`. Fresh host state captured the
  accepted historical API unit/image/revision, unchanged Admin and API-F
  fingerprints, four protected managed-secret files, the seven-key
  private-storage configuration, lifecycle tools, loopback listeners and
  rollback assets before any service mutation.
- API-C issued one short-lived private Registry token, performed one
  protected login and one exact-digest pull. The manifest digest is
  `sha256:612a7e57…17620`; the independent config/local image ID is
  `sha256:dd955f9e…fd53`; platform, b55 OCI revision, API role, entrypoint and
  command all match. Token, RSA, ciphertext, Docker auth and transport
  residue are zero. A post-pull validator initially confused the build-stage
  name with the runtime role; the pulled bytes were reused without another
  token, login or pull.
- Three canary generations were created with the same hashed command and
  `restart=no`. Generation 1 was removed after a local duplicate-env-count
  assumption. Generations 2 and 3 each passed three live/ready rounds, exact
  database/model readiness, read-only database state, loopback port `18000`,
  empty isolated data and zero provider/object/database writes. Generation 2
  was removed by the mandatory rollback below; generation 3 was removed only
  after the final independent postcheck. Automatic canary restart and blind
  retry are zero.
- The first promotion installed and restarted the candidate, then a local
  validator incorrectly required a durable-worker-only key from the formal
  API. Mandatory rollback restored the fresh historical unit/image and
  health, and cleaned that canary. The same candidate was promoted only after
  correcting the validator and fully rearming the canary. The candidate unit
  SHA-256 is
  `364a5e539b14a83d24ef9c1726ee3e14b988c398206b2711db5613b9e0a1fc77`;
  its only semantic changes are the exact b55 digest and private-storage env
  file reference. A subsequent single explicit systemd restart changed the
  managed container identity and again passed three live/ready rounds.
- The independent postcheck preserved every failed local validator state. A
  zero-byte first database artifact was classified `PRE_CONNECT` because
  container stdin was not attached. The first effective transaction was
  `CONNECTED_KNOWN / READ_ONLY_REJECTED / ROLLED_BACK / WRITE 0` because the
  least-privilege API role cannot select `schema_migrations`; that incident
  was not retried. A separate narrower runtime-session audit used one
  read-only transaction and terminal rollback to verify
  `default_transaction_read_only=on`, `transaction_read_only=on`,
  `noteai_app`, no assigned XID and transaction tuple writes zero.
- Pre-cleanup validation passed all `15/15` assertion families after two
  local assumptions were corrected without service or database action. The
  final canary cleanup first stopped before deletion because its allowlist
  excluded the task-root data path; exact parent/depth/hash/non-symlink/empty
  checks then authorized removal of only the canary container and its empty
  directory. Final validation passed `11/11` after two self-observation
  classifiers were narrowed; failed validator artifacts remain append-only.
- Final API-C state is one managed b55 API container, active/enabled/result
  success, live/ready `200`, only loopback port `8000`, exact hardening
  (`999:999`, read-only root, cap-drop ALL, no-new-privileges, bounded tmpfs,
  one writable data mount, fixed CPU/memory/PID limits, Docker restart
  `no`). Canary/container/data/listener, registry auth, credential material,
  task scripts/processes and temporary unit files are zero. The fresh
  historical unit SHA-256 `872c44e8…25` and old image ID
  `sha256:b1983bab…fedb` remain root-only rollback assets.
- API-C Admin and API-F were independently checked before and after cleanup:
  their unit/image/revision/start-time fingerprints, restart count zero,
  hardening, live/ready `200` and loopback listeners are unchanged. Protected
  managed-secret/storage/lifecycle hashes are unchanged. Bounded final logs
  have zero startup-failure, migration-execution, provider-call,
  Secret-assignment, traceback or fatal matches; raw logs are not committed.
- Fresh RDS control-plane readback is one Running PostgreSQL 16 VPC/Intranet
  instance, one private and zero public endpoint, accounts `8/1/0`, and eight
  successful automated full snapshots in the reviewed window with the latest
  approximately eighteen hours old. The production VPC has zero ALB. No
  schema/role/business/object/provider/ALB/TLS/DNS/public-traffic write
  occurred.
- Secret-free runtime evidence is
  `deploy/production/evidence/production-api-c-current-release-verified-20260730.json`.
  It records eighteen ordered attempts, nine failures, nine passes, one real
  service rollback, three canary generations, six bounded database
  connections, two explicit read-only transactions, automatic retry zero and
  `CONNECTED_UNKNOWN=0`. A dedicated semantic verifier is bound by both the
  internal and production gates; Stage B files remain unchanged with
  deployment/canary authorization false.
- Focused Stage C tests are `43/43`; Python compile, JSON, semantic verifier
  and diff checks pass. The production gate is `108/108 PASS`. Only
  `api_c_current_release` earns one new credit: internal readiness is now
  `18/29 = 62%`, complete-public readiness is `18/38 = 47%`, and public
  launch plus full-system rollback remain unverified.
- The only serial task is now
  `PROD-FIRST-LAUNCH-API-F-INTERNAL-001`. Its acceptance must independently
  deploy the same exact API digest to API-F with a fresh baseline, loopback
  canary, reversible promotion, explicit restart, API-C/Admin non-regression,
  independent postcheck, rollback-ready evidence and final residue zero.

## 6.7. API-F Stage C fresh baseline

- API-F began only after the API-C evidence/verifier checkpoint was pushed at
  `07ddcbcc1a6b62e9992aed26f42ce05ec4d3b816`; branch, HEAD and upstream were
  exact, divergence was `0/0` and the worktree was clean.
- The first local browser command template was rejected before dispatch for
  an escaped back-reference. The corrected read-only host dispatch then
  captured the full API-F baseline, but its collector counted one existing
  Docker configuration file instead of semantic auth entries and its error
  trap observed a false condition inside that count. A narrower resolution
  template was itself rejected locally before dispatch because shell
  parameter syntax collided with the browser language. The materially
  corrected narrow read-only dispatch proved semantic Docker auth entries
  zero and completed without error. All four attempts are `PRE_CONNECT` with
  service/database/object/provider/public mutations zero; exactly two reached
  the host and neither changed state.
- Fresh API-F state is the accepted historical unit SHA-256
  `32d552e3…4268`, image ID `sha256:b1983bab…fedb`, manifest
  `sha256:17706e18…e0d1` and revision `a635692a…94a`. The service is
  active/enabled/result success with restart count zero, one managed
  container, live/ready `200`, exact database/model readiness and only
  loopback port `8000`. Runtime identity, entrypoint/command and hardening
  remain exact: `999:999`, read-only root, cap-drop ALL,
  no-new-privileges, Docker restart `no`, 1.5 GiB/2 CPU/PID 512, one bounded
  `/tmp` tmpfs and one writable `/app/model/data` mount.
- The target image is not cached on API-F. Private Registry DNS and route are
  private and available; Docker free space is at least 32 GiB and available
  memory is 6,706 MiB. Canary container/listener, temporary unit, task root,
  database connection and semantic Registry auth counts are all zero.
- API-F's three distinct managed-secret files remain regular root-owned
  `0600` files with unchanged hashes, duplicate keys and backup residue zero.
  The one root-owned `0600` private-storage configuration has exactly seven
  keys, duplicate/static-access-key names zero and the same hash as API-C.
  Both lifecycle entrypoints resolve to the previously accepted identical
  wrapper hash.
- Independent API-C peer baseline proves the promoted API unit
  `364a5e53…fc77`, exact b55 image/revision, active/enabled/result success,
  restart zero, live/ready `200`, loopback-only and unchanged hardening.
  API-C Admin remains at unit `c299059d…1ab2`, its accepted historical image
  and start time, restart zero, live/ready `200` and loopback-only. Their four
  managed-secret hashes, storage hash and lifecycle hashes are unchanged;
  API-C canary/auth/database-connection residue is zero, while its one
  intentional sanitized Stage C evidence root remains retained.
- Fresh control-plane reads prove one Running PostgreSQL 16 VPC/Intranet
  instance, one private and zero public endpoint, accounts `8/1/0`, seven
  successful automated full snapshots in the bounded seven-day window with
  the latest approximately nineteen hours old, and zero production-VPC ALB.
- No pull, token, login, service restart, database transaction/write, object
  action, provider call, ALB/TLS/DNS or public-traffic change has occurred in
  API-F Stage C. Readiness therefore remains `18/29 = 62%` internal and
  `18/38 = 47%` complete-public. The only task remains
  `PROD-FIRST-LAUNCH-API-F-INTERNAL-001`; next acceptance is one protected
  exact-digest pull, a candidate derived only from the fresh API-F unit,
  loopback canary, reversible promotion, explicit restart, independent
  postcheck and cleanup.
- Transport setup subsequently created the exact root-only Stage C root,
  retained the fresh historical unit bytes and generated one ephemeral RSA
  keypair without service or database action. One short-lived Registry token
  was issued and encrypted, but the first exact-pull executor stopped before
  Python began because two Docker label templates lost their nested quoting.
  Independent incident audit proves `login=0`, `pull=0`, exact-image cache
  zero, unit unchanged, live/ready `200`, database connection zero and
  canary zero. The EXIT cleanup removed isolated auth, RSA public/private key
  and ciphertext residue. This attempt is append-only `PRE_CONNECT`; a new
  credential may be issued only after the materially corrected executor
  passes a separate syntax compile.
- The corrected pull executor passed an independent target-Python syntax
  compile before a second ephemeral transport key and short-lived token were
  created. Its outer observer returned only the initial markers, so the pull
  was not repeated. A separate read-only outcome audit proved the sanitized
  result is `PASS`: Registry login `1`, exact-digest pull `1`, automatic retry
  `0`, and exact config image ID, RepoDigest, b55 revision, API role,
  `linux/amd64`, entrypoint and command all match. The exact image is now
  cached on API-F. Isolated/global auth entries, RSA, public key and ciphertext
  residue are zero; the historical unit remains installed, live/ready
  `200`, canary zero and database connection/write zero. Cumulative transport
  counts are token issuance `2`, successful login `1`, successful pull `1`;
  the first token never reached login or pull and was not reused.
- The first candidate generator was syntax-valid but stopped before writing
  because it assumed the API env argument was a continued line. A dedicated
  read-only structural audit proved API-F's fresh unit uses a single-line
  `ExecStart`; source/installed bytes, digest, storage file and container name
  were otherwise exact. The corrected generator compiled first, inserted the
  storage env argument on that same line and passed `systemd-analyze verify`.
  Candidate SHA-256 is
  `23750496447ad6e31ad27b1461f1164bbf14c28296a0ac28be7e5886eb4e65c1`
  for 1,447 bytes. Replacing the new digest with the historical digest and
  deleting the one storage argument reconstructs all 1,404 historical bytes
  exactly; image-digest changes `1`, storage additions `1`, other semantic
  changes `0`. No installed unit, service, canary or database state changed.
- The canary command was derived from the 53 exact candidate tokens. It
  changes only the container name, loopback mapping to port `18000` and data
  source to the empty root-owned Stage C directory; API plus storage env
  count is `2`, XHS env count `0`, exact image count `1`, restart policy
  `no` and command SHA-256 is `0c0ace0b…c642`. A narrower read-only mount
  probe was not observed externally and made no change; the fail-closed
  generator itself proved the exact bind destination before writing.
- Exactly one canary generation was created and started. Its combined
  start-and-validation command exceeded the outer execution window after the
  container began, so no result file was accepted and the generation was not
  restarted or recreated. A separate read-only validator then passed three
  live/ready rounds, exact database/model readiness, b55 identity, all
  hardening/resource/mount/storage-env assertions, empty data, restart zero
  and bounded log hits zero. The canary result SHA-256 is
  `a8057cbb…8fd4`; the formal historical service remained `200/200`.
- A first over-composed syntax wrapper for the canary database probe failed
  before connection. The direct source compile passed, then one distinct
  explicit canary session completed `1` connection, `1` read-only
  transaction and `1` terminal rollback with runtime role exact,
  default/transaction read-only on, XID unassigned, transaction tuple writes
  zero, database writes zero and `CONNECTED_UNKNOWN=0`. Its result SHA-256 is
  `d2eb6dad…e9de`. The known migration-ledger denial path was not repeated.
- Promotion attempt 1 atomically installed the candidate and issued one
  managed-service restart. Its immediate post-start `docker inspect` ran
  before the stable container name became visible and raised a local
  `CalledProcessError`; the executor conservatively restored the historical
  unit, daemon-reloaded and restarted the old image once. Independent outcome
  evidence SHA-256 `de656f8f…6895` proves `service_mutation_started=true`,
  promotion restart `1`, rollback restart `1`, rollback `PASS`, automatic
  retry `0` and database/object/provider writes zero.
- Bounded journal/event diagnosis shows no unit failure, env-file failure or
  application fatal. The candidate container did create and start; the exact
  event chain contains the canary, candidate and rollback generations, while
  the two expected old/candidate stops and destroys match the promotion and
  rollback. Current installed/rollback unit SHA is again `32d552e3…4268`,
  historical image and formal health are restored, and the original canary
  remains running, healthy and restart zero. Any new promotion requires a
  complete canary rearm and a materially corrected bounded container-visible
  wait with explicit stage codes.
- The unchanged canary was rearmed without restart and again passed three
  live/ready/readiness-payload rounds; the fresh result SHA-256 is
  `9271273d…2325`. Promotion executor V2 compiled before dispatch and adds a
  bounded stable-container visibility wait plus precise failure stages. Its
  first outer invocation stopped at the read-only guard because the caller
  used two incorrect staged filenames and `/ready` instead of the already
  validated `/health/ready`; the candidate, canary result and runtime were
  untouched. A narrow always-success diagnosis resolved the actual staged
  filenames and health path before any retry.
- With the corrected read-only guard, promotion V2 atomically installed the
  exact `23750496…65c1` candidate and issued one managed-service restart.
  Result SHA-256 `90078e42…60dd` is
  `STARTED_PENDING_HEALTH`: service mutation/restart `true/1`, stable
  container visibility on poll `2`, container identity changed, Docker
  restart `0`, automatic retry `0`, rollback required/restart
  `false/0`, and database/object/provider calls and writes all zero.
  Independent immediate checks prove the candidate unit installed,
  systemd active/enabled/result success, formal live/ready `200`, and the
  original canary still live/ready with restart zero. One provisional audit
  incorrectly reconstructed a full config-image ID from an abbreviated
  API-C handoff value and correctly failed only that comparison; it was not
  a runtime mismatch. API-F identity acceptance remains independently bound
  to the exact values in API-F's own pull/canary evidence, even where the
  content-addressed API artifact is intentionally the same as API-C.
- Formal-validator source V1 failed its separate syntax-only dispatch because
  a generated dictionary entry used assignment syntax. Source V2 compiled
  but its first read-only execution stopped before result creation because a
  caller-added parser supported volume flags but not the candidate unit's
  exact `--mount` form. Both attempts are `PRE_CONNECT` with service restart,
  database/object/provider/public mutation and result writes zero; the
  installed candidate, formal health and original canary remained exact.
  A narrow read-only token audit proved one `--mount` across the 53 candidate
  tokens, and source V3 added only that missing parser branch before passing
  a fresh syntax compile.
- Formal initial acceptance then passed in a separate read-only dispatch.
  Result SHA-256 `f6726b17…7c9d` records three of three
  live/ready/readiness-payload rounds; exact API-F pull-bound config image,
  RepoDigest, b55 revision, role, user, hardening, resources, loopback port,
  storage-env names and writable model-data mount; container restart zero;
  bounded data files and migration/provider/secret/fatal log hits all zero;
  and database/object/provider writes zero. The candidate unit, formal
  service and unchanged canary independently remain healthy.
- The explicit-restart executor V1 was rejected only by its syntax compile
  because the generated result newline became an unterminated literal. The
  one-line serialization correction compiled, then exactly one explicit
  managed-service restart ran. Result SHA-256 `b0fc128a…1fcd` proves a new
  container identity on visibility poll `2`, exact API-F unit/config-image/
  digest identity, systemd active/enabled/result success, Docker restart
  zero, automatic retry zero, rollback not required, and database/object/
  provider calls and writes zero. Formal and canary health remained `200`.
- Separate post-restart result SHA-256 `6f22be7d…b1e4` passed another three
  live/ready/readiness-payload rounds with the same full identity,
  hardening, resource, loopback, mount, storage-env and bounded-log
  assertions. The final managed-service restart accounting is promotion
  restarts `2`, failed-promotion rollback restart `1`, and explicit restart
  `1`; the explicit restart itself was not retried.
- One new formal runtime database session produced deterministic result
  SHA-256 `addc5b90…3c80`: connection/read-only transaction/terminal rollback
  `1/1/1`, runtime role exact, default and transaction read-only true, XID
  unassigned, transaction tuple writes and database writes zero, and
  `CONNECTED_UNKNOWN=0`. The outer shell then rejected only its own
  string-valued expectation for those boolean read-only fields. This is
  `CONNECTED_KNOWN / PASS / ROLLED_BACK / WRITE 0`; the database session was
  not repeated.
- Fresh peer runtime audit result SHA-256 `737d8485…1fc6` independently proves
  API-C API and Admin unit/image/start-time/restart/health/listener state
  unchanged. Its only failure was a first-level Secret-directory path
  assumption. Hash-directed recursive follow-ups, without revealing paths or
  values, prove four distinct root-owned `0600` managed-secret hashes, one
  root-owned `0600` storage hash and two lifecycle-wrapper hashes exact.
- Canary cleanup result SHA-256 `51d5f894…b39b` records exactly one canary
  container removal and one nonrecursive removal of its previously empty,
  non-symlink data directory. Container, listener `18000` and canary data are
  absent; formal health remains `200`; database/object/provider calls and
  writes are zero. The evidence root, candidate/current image, historical
  unit and historical image are intentionally retained.
- The first final-runtime guard used `set -e` directly on the expected
  nonexistent canary inspection and stopped before validator execution.
  Explicit negation was the only correction. Final runtime result SHA-256
  `f392c3d2…3973` then passed three more live/ready/readiness-payload rounds
  with the final formal container identity unchanged since the explicit
  restart and canary/listener still absent.
- Final postcheck V1 result SHA-256 `9bc22bfc…d076` passed every runtime,
  rollback, Secret, storage, lifecycle, auth, credential, residue, listener,
  process, temporary-unit and database-connection assertion except a caller
  policy that allowed only `0600` JSON. A read-only mode census found six
  root-owned `0644` sanitized evidence JSON files; a dedicated content scan
  found parse failures, sensitive scalar values, IP addresses, complete DSNs,
  PEM material and long strings all zero. Corrected V2 binds V1 append-only
  and treats only those six scanned files as safe public-mode evidence.
  Result SHA-256 `a98f5778…6b7f` is `PASS`: all required result hashes,
  installed/rollback units, current/old images, one formal container, final
  health, three Secret hashes, seven-key storage and two lifecycle hashes are
  exact; canary/unexpected container/`18000`/auth/RSA/cipher/backup/process/
  temporary-unit/established-DB-connection residue is zero.
- Final control-plane reads again prove one Running PostgreSQL 16 instance,
  one private and zero public endpoint, accounts `8/1/0`, available accounts
  `8`, task residue zero and production-VPC ALB zero. The bounded backup
  evidence from the fresh Stage C baseline remains seven successful automated
  full snapshots within seven days with the latest about nineteen hours old;
  a later Explorer-only refresh was not accepted because its date control did
  not produce a response, so no newer backup claim was substituted.

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

- focused privileged-owner/readiness tests: `31/31`;
- disposable PostgreSQL 16 privileged-owner chain: `1/1`;
- full Python suite: `1119/1119`, 28 explicit skips;
- API-F focused evidence/internal/production gate tests: `45/45`;
- production readiness gate: `109/109 PASS`;
- internal readiness: fail-closed `19/29 = 66%`;
- public readiness: `19/38 = 50%`;
- independent read-only API-F evidence/verifier adversarial audit: `PASS`;
- one local JSON-format check initially invoked unavailable bare `python`
  after compilation had already passed; the same JSON and compile checks were
  rerun with `.venv/bin/python` and passed, with no remote or production action;
- zero-DSN import, Python compile, runner shell syntax, JSON parses and
  `git diff --check`: pass;
- disposable PostgreSQL containers/network/volume: zero;
- temporary package removed from active paths and Colima restored stopped;
- 004 production database connection: one forced-readonly transaction,
  terminal rollback, database write zero;
- 004 account/cloud/service/provider/public-traffic mutations: zero.
- 005 production database connection: exactly one forced-readonly transaction,
  terminal rollback, independently validated 4,111-byte result and database
  write zero;
- 005 final cleanup: accounts `3/1/0`, task account/RSA/ciphertext/package/
  result/container/process/Cloud Shell residue zero, RDS/API public endpoints
  zero, API-C/API-F/Admin active/ready/loopback-only.
- V5 production pre-dispatch: exactly one forced-readonly connection,
  terminal rollback, ledger `0001`-`0008` and database write zero.
- V5 production apply: exactly one dispatch, deterministic `COMMITTED`,
  database writes `18`, automatic retry zero.
- V5 independent outcome: exactly one forced-readonly connection,
  deterministic `COMMITTED`, terminal audit rollback and the complete
  post-commit negative matrix verified.
- V5 final cleanup: accounts `3/1/0`, task account/RSA/ciphertext/source/
  sentinel/result/error/container/process/Cloud Shell residue zero and
  API-C/API-F/Admin active/ready/loopback-only.
- Managed Secrets production transaction: exactly one dispatch,
  deterministic `COMMITTED`, five LOGIN and five password mutations, zero
  membership/ACL/schema/business-row writes and automatic retry zero.
- Managed Secrets independent audit: seven role-bound forced-readonly
  connections plus one global forced-readonly verifier; full negative matrix,
  five LOGIN roles, one NOLOGIN dispatcher and database write zero.
- Managed Secrets final cleanup: accounts `8/1/0` with five expected runtime
  accounts and zero unexpected/task accounts; node execution roots, RSA,
  ciphertext, source, sentinels, results, errors, task containers/processes
  and Cloud Shell task files zero; seven final root-only files and four
  lifecycle tool installations verified; API-C/API-F/Admin non-regression.
- Private storage final cleanup: two sub-64-byte synthetic objects deleted,
  prefix inventory zero, exact Cloud Shell task files zero, node task roots,
  transfer material, containers and processes zero; private OSS/RAM/IMDSv2,
  fresh RDS backup and API-C/API-F/Admin non-regression independently verified.

ROOT-CAUSE-003 was committed and pushed normally at `ed5e699`.
The 004 source was committed and pushed normally at `51ae877`.
The 004 outcome/evidence was committed and pushed normally at `8a533ac`.
The 005 production source/import fix was committed and pushed normally at
`7c4204f`.
The 005 verified outcome/evidence was committed and pushed normally at
`465505e`.
The corrected V5 runner was committed at `efeb5bb`; it supersedes the unsafe
intermediate `fa2ebae` and must be included by the next pushed source
checkpoint.
The API-F exact-current runtime evidence/verifier/readiness checkpoint was
committed and pushed normally at
`216be18bab10e5e0358e1f61e3f6b70bd207a8a8`; branch, upstream and HEAD were
equal with divergence `0/0` immediately afterward.

## 9. Admin exact-current Stage C fresh baseline

- The sole serial task is now
  `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Internal readiness remains
  `19/29 = 66%` and public readiness remains `19/38 = 50%`; no Admin credit
  has been claimed.
- The immutable Admin target is revision
  `b55f11882100e9ef919522540729e366a511f88f`, manifest
  `sha256:271a089e4e5ae7da3635b14d2ce8d5195955e7d74225723a4308d0c99cb79e56`
  and config
  `sha256:fac78f71d7b123621962738d2a93532ff98f2302232562dc75b6a8e0016b7626`.
  Its role/platform/entrypoint/command are exactly
  `admin`, `linux/amd64`, `/app/scripts/docker_entrypoint.sh` and
  `/app/scripts/render_start_admin.sh`.
- The rollback anchors are the installed unit SHA-256
  `c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2`,
  historical manifest
  `sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733`,
  historical config
  `sha256:2283095764622e373e30b51ba749819751e6bfb0c37c6bb82e2d3bfe4937760f`
  and revision `a635692a899ee02c6905cd694611c14e0da4594a`.
  The old Admin is active/enabled, systemd result success, Docker restart
  zero, live/ready `200` and loopback-only on `8001`; `18001` is absent.
- The installed Admin container remains exactly one `role=admin` generation,
  user `999:999`, running/healthy, read-only root, unprivileged,
  `no-new-privileges`, all capabilities dropped, `1 GiB / 1 CPU / 512 PIDs`,
  private IPC, bridge network, a read-only `/app/model/data` mount, a
  `512 MiB` noexec/nosuid/nodev `/tmp` tmpfs and no automatic restart.
  Its Secret-free container-identity hash is
  `38bfd55d88df86031a431edf8be808ba4e87cff33c492024e4a8bcd0f95fd66a`.
- `/etc/noteai/admin.env` is a regular non-symlink, root-owned `0600` file
  with SHA-256
  `ddf4ef6f19a3234e077d08bb09faef23219299184213edc32aed085d34775d2a`
  and exactly `DATABASE_URL` plus `ADMIN_PASSWORD`. The staged database
  identity is exactly `noteai_admin_runtime` with a nonempty password.
  The historical running container still carries the old `noteai_app`
  database identity, as expected before its first managed restart.
- Protected-file state is unchanged: the Admin node has five expected
  root-only files with aggregate hash
  `fe67cb77e04653a7501c69df6f1f2d7783e3352370eaedfe5604adc492f29663`;
  the two lifecycle wrappers have aggregate hash
  `24348af5ce3ce80301d570d1406974a42ce5fa89bba11ee2ee54c20778732196`.
  Registry-auth, task-root, backup, canary and `18001` residue are zero,
  the target Admin image is not yet cached, and bounded capacity is
  sufficient.
- Fresh peer checks bind API-C and API-F to their exact current units and
  shared current API config image, active/enabled, Docker restart zero,
  formal live/ready `200`, loopback-only `8000` and no canary listener.
  Their Secret-free container-identity hashes are respectively
  `3e0e26942e2352ee0b7f6e1540c2233b7634530e7e845848832be6a059362b53`
  and
  `9b9d3da2c4031609f7f9a70128376b707dfc00daaa5dd5d1cfbcf3bb13778dca`.
  API-F's four protected files and both lifecycle wrappers remain exact.
- The accepted immediately preceding API-F control-plane closeout proves one
  Running PostgreSQL 16 instance, VPC/Intranet networking, one private and
  zero public endpoint, accounts `8/1/0`, all eight accounts available, task
  residue zero, production-VPC ALB zero, and seven successful automated full
  backups in seven days with the latest about nineteen hours old.
- A fresh read-only RDS Explorer refresh loaded the intended
  `DescribeDBInstances` action but its first call produced no result link.
  After proving there was no response residue, only one read-only retry was
  issued; it again produced no parsable result and no authentication,
  authorization or throttling signal. This is a control-console
  result-extraction failure with cloud/database/service writes zero. The
  accepted API-F snapshot above was not replaced and no further blind retry
  is allowed.
- Three remote read-only diagnostic source variants failed before changing
  state: a Docker template applied `len` to a null field, two protected-file
  shell traversal forms exited nonzero, and one backup command was not
  dispatched. Corrected bounded variants passed. An API-F protected-file
  command that exceeded the UI-safe shape was not dispatched; its shorter
  form passed. All incidents had service/database/object/provider writes zero
  and are preserved rather than retried blindly.
- Exact Admin pull is complete. One short-lived Registry credential was
  issued, encrypted with a fresh node-local RSA-OAEP-SHA256 key, transmitted
  only as ciphertext, consumed through isolated Docker auth and
  `--password-stdin`, and used for exactly one login plus one pull.
  `pull-result.json` SHA-256 is
  `9ca9764f5567e5a5708e794edb30296f3a75539dfbe216af472fac8749c970fa`;
  it binds the exact target config image, RepoDigest, revision, `admin` role,
  `linux/amd64`, entrypoint and command. Automatic retry, database connection,
  service mutation, canary and public/provider/object writes are zero.
- Cloud Assistant's paste-content mode has a bounded `512`-character editor,
  so the locally compiled `4,432`-byte pull executor was transported as ten
  root-owned `0600` PlainText parts. The parts were individually non-overwrite
  sends, verified as a complete `00`–`09` set, assembled to exact SHA-256
  `b0412afe625a2896f424f4d7139ced21a7d70e118dfba77ff1fd25fd40cb37b1`,
  then deleted after the pull result passed. The encrypted credential was one
  separate root-owned `0600` `512`-character payload.
- The first direct SendFile wrapper selected upload/Base64 rather than the
  PlainText radio and never dispatched the file. Initial part `00` and part
  `01` wrappers likewise stopped in browser form handling; read-only absence
  checks preceded their corrected sends. Part `04` stopped before text-mode
  selection and a fresh presence bitmap proved `11110`; part `05` stopped at
  the same local mode boundary. Each missing part was then sent once, no
  existing part was overwritten, and all final sends had a success result
  row. These are append-only `PRE_CONNECT` incidents with Registry, service,
  database and provider actions zero.
- The first read-only attempt to recover the historical private image
  repository used a newline count on a scalar and failed before output. Its
  corrected single-container assertion recovered the path in memory without
  exposing it. The pull command's outer browser wait later expired and reset
  the browser-control session, but the unique existing invocation was found
  read-only as `successful` with `NOTEAI_ADMIN_PULL_V1=PASS`; it was not
  resent.
- Final exact-pull cleanup is zero for isolated Docker auth, RSA public/private
  key, ciphertext and transfer parts. A separate post-pull audit proved the
  target config image cached exactly, while the historical Admin unit,
  historical running image, Docker restart zero and live/ready `200` remained
  unchanged.
- Candidate V1 was derived from the exact `1,263`-byte historical unit by
  replacing only its one historical manifest digest. Its SHA-256 was
  `92c4f9c9c5a36d8696f2853bbffabad7f600b90eae9afb443567e06fa8af9751`
  and systemd syntax passed, but a token-level semantic audit then found the
  historical API-only
  `PGOPTIONS=-c default_transaction_read_only=on` environment item. This
  conflicts with Admin's narrowly authorized session INSERT/DELETE. Candidate
  V1 was never installed, never used for a canary and never connected to the
  database; it is append-only `PRE_CONNECT` and its staged file was deleted.
- Candidate V2 changes exactly the target manifest digest and removes exactly
  that one API-only environment item. It is `1,209` bytes, has `46` tokens and
  SHA-256
  `fc824f32d4a24fed06a2223774d2cdbc6a6652e8a37721aa219d2d5b34293062`.
  Re-inserting that token and restoring the old digest reconstructs the
  historical unit byte-for-byte; all hardening, resource, mount, env-file,
  loopback-port and service tokens are otherwise unchanged.
  `systemd-analyze verify` passed on the node. The exact historical unit is
  retained separately as root-only rollback with SHA-256
  `c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2`;
  all Candidate V1/V2 transport parts are zero.
- Admin differs intentionally from API-C/API-F: its database role must permit
  the narrowly scoped `admin_sessions` `SELECT/INSERT/DELETE`, so the session
  default must not be forced read-only. The catalog/ACL audit must instead use
  a separate explicitly read-only transaction and terminal rollback. One
  canary login may insert exactly one session; it must survive promotion and
  the one explicit restart, then logout must delete exactly one session and
  replay must return `403`. The seven mutation routes remain `409`, cookie
  update `410`, crawler mutation `409`, all five mutation capabilities false,
  and business/schema/role/object/provider/public writes zero.

Current remaining steps:

- preserve Stage A/build10, Stage B publication and Stage C ordered
  deployment/rollback/postcheck evidence; do not rebuild, rescan, republish or
  repeat API-C or API-F;
- execute only `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001` from a fresh Admin
  baseline, with exact Admin image identity, dedicated-role negative matrix,
  reversible promotion and independent API-C/API-F non-regression;
- accept Admin only after exact image/unit/hardening/loopback identity,
  the full `56 × 7 = 392` table ACL matrix, 15 sequence denials, function and
  ownership/membership negatives, bounded login/restart/logout/replay
  lifecycle, zero residue and rollback-ready evidence all pass; then wire the
  independent verifier into the readiness gates and prove focused tests,
  production gate `110/110`, internal `20/29 = 69%` and public
  `20/38 = 53%`;
- continue through the dependency graph without stopping at the checkpoint
  or task boundary.

### Admin Stage C executor gate correction (2026-07-30)

- No Admin canary, service restart, database session or production unit
  mutation has started. A fresh marker-only pre-upload audit proved the remote
  runtime executor, its compressed transport, results/state directory,
  `/run` bearer directory, canary data directory and canary residue were all
  absent. The remote Python runtime is compatible and `gzip` is available.
- A marker-only Docker inspect resolves a conflicting historical sentence:
  the current Admin `/app/model/data` bind mount is writable, and Candidate
  V2's sole `--mount` contains only the unchanged `type/src/dst` keys. The
  earlier statement describing this Admin bind mount as read-only is
  incorrect; the read-only control applies to the container root filesystem.
- The first locally compiled executor was held before upload after an
  independent read-only review found contract blockers. In particular,
  `system_settings.is_secret` is PostgreSQL `INTEGER`, and
  `noteai_admin_runtime` intentionally has exactly one incoming
  owner-management membership from `noteai_admin` with admin option true and
  inherit/set both false. The earlier shorthand “membership zero” applies to
  runtime inheritance/outgoing membership, not this accepted management
  edge.
- The corrected executor now validates the complete table, column and
  sequence privilege matrices including every grant option, zero role-scoped
  default ACL, the exact Admin RLS policy set, zero ownership/function
  execution, exact database/schema privileges and the accepted one-edge
  management topology. Its embedded Python sources compile locally and its
  ACL allowlists match `tools/production_schema_roles.py`.
- The bearer path is atomic and root-only. Runtime evidence checks that the
  raw bearer has zero database rows while exactly one SHA-256 row exists
  after login, then both are zero after logout; neither the bearer nor its
  digest is persisted in task evidence. HTTP validation now checks response
  shapes and user masking, takes database/catalog/process/data snapshots
  around all read and mutation probes, and scans bounded logs for expanded
  credential and bearer leak signatures.
- Formal promotion, formal validation, explicit restart and session-close
  failures restore the exact historical unit/image. A separate one-shot
  `abort` mode cleans the task session/canary and proves the historical
  service outcome; it refuses to turn any unresolved `CONNECTED_UNKNOWN`
  history into a successful cleanup. Result files remain immutable, so no
  failed mode is retried in place.
- Local verification currently passes Python compilation, embedded-source
  parsing, allowlist parity, atomic-token failure cleanup and preservation of
  known rollback outcomes. The corrected package is awaiting the second
  independent read-only review and has not been uploaded.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
second executor review has no blocking defect; then one exact upload,
canary/ACL/session validation, reversible promotion, explicit restart,
logout, zero-residue cleanup and independent peer/control-plane postcheck all
pass before repository evidence may count Admin as internal `20/29`.

### Admin Stage C executor upload checkpoint (2026-07-30)

- The second targeted independent read-only review completed with no
  deterministic production blocker. It confirmed that the corrected
  PostgreSQL queries match the production audit contracts and that the HTTP
  response-shape checks match the Admin source. The remaining risks are
  fail-closed false negatives, not unsafe acceptance paths.
- The first browser file-control attempt stalled before a file chooser was
  captured. A fresh control-plane view proved that the send form had not been
  submitted; this is an append-only `PRE_CONNECT` incident with remote
  write, service, database and provider mutation all zero.
- The exact audited transport was then sent once to only the API-C host. The
  control plane reports one successful target, the intended isolated stage
  directory, `root:root` and mode `0600`; overwrite remained disabled.
- The remote verification command completed with exit code zero and marker
  `NOTEAI_ADMIN_STAGE_UPLOAD_VERIFY=PASS`. It proved the compressed SHA-256
  `e76cd8216ccc35e278b08bd41f64a75cb68eb72c450db8bfbefa97d9abd927a4`,
  decompressed source SHA-256
  `c2aac4d930e061b3e9d52c3f98a334d6af8349409fd455bb0603ee24e8cf252c`,
  final ownership/mode `root:root:600`, and successful remote Python
  compilation. The compressed transfer and generated bytecode cache were
  removed after verification.
- No Admin canary, formal service restart, production unit replacement or
  database session has started at this checkpoint. Readiness remains
  internal `19/29`, public `19/38`, production gate `109/109`.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
run the immutable `canary-start`, `canary-validate`, `acl-audit` and
`session-open` modes exactly once each; require their exact PASS markers,
zero connected-unknown state and no peer regression before formal promotion
is eligible.

### Admin Stage C V1 pre-connect failure and abort checkpoint (2026-07-30)

- The unique immutable V1 `canary-start` invocation returned `FAILED` before
  its mode-local result counters were created. Its secret-free result records
  `failure_detail_code=candidate_mount`, `connected_unknown_count=0` and
  `automatic_retry_count=0`. No canary container was created or started, no
  formal service or unit was mutated, and no database connection or write was
  attempted.
- The failure is a local executor/parser defect, not a production runtime
  fault. Candidate V2's already proved exact mount uses the historical
  `type/src/dst` spellings, while V1's canary transformer required
  `source/target`. V1 was not retried and its immutable failure result remains
  preserved.
- The unique V1 `abort` mode then passed. Its immutable result records
  `cleanup_status=PASS`, `service_outcome=KNOWN_ROLLED_BACK`, formal rollback
  restart `0`, canary remove `0`, connected unknown `0`, automatic retry `0`,
  three formal health rounds, zero canary/container/listener/data/token
  residue, complete prior-failure side-effect evidence with zero detected
  side effects, API peer health true, and systemd
  active/enabled/result-success with restart/status `0/0`.
- Readiness is unchanged at internal `19/29`, public `19/38`, production gate
  `109/109`. The V1 stage directory and results are evidence and must not be
  overwritten.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
make the minimal `type/src/dst` mount-parser correction locally, compile and
independently review the full V2 executor, upload it under a fresh V2 stage
root, and require the fresh immutable `canary-start` PASS before any later
Admin mode or formal promotion is eligible.

### Admin Stage C V2 executor pre-upload checkpoint (2026-07-30)

- The V2 executor uses fresh, non-overlapping stage, runtime-token, canary and
  label namespaces. It preserves V1's immutable failure and abort results.
- The only behavioral correction is fail-closed parsing of the already proved
  Candidate V2 mount form. Both the canary transformer and runtime shape
  verifier now require exactly three `key=value` segments with the exact
  `type/src/dst` key set, `type=bind` and
  `dst=/app/model/data`; the transformer changes only `src`.
- Local positive and negative tests passed for the exact historical form and
  rejection of `source/target`, duplicate `src`, an extra bare flag, the
  wrong mount type and the wrong destination. Python compilation and package
  round-trip also passed.
- The targeted independent read-only re-review of exact source SHA-256
  `ff36c70b4765b0ca96f9ab9c1bb3a85c7dc7bc5f9645ca57309a77b485c7e3f7`
  found no blocker, no stale V1 namespace or `source/target` assumption, and
  confirmed that canary, formal and final-cleanup paths reuse the complete
  mount-shape gate. Its only non-blocking observation was that `src` is not
  checked separately for an empty value; the exact candidate SHA binds a
  non-empty source and later Docker/shape gates remain fail-closed.
- The deterministic compressed transport is `18,877` bytes with SHA-256
  `03c472bfab573d533858323ded43e071f8822dc92f1611db401248c7ec6e1837`;
  its decompressed bytes are the exact audited `95,053`-byte source.
  Readiness remains internal `19/29`, public `19/38`, production gate
  `109/109`.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
create one fresh root-only V2 stage from the already verified candidate and
rollback unit, upload and remotely compile the exact audited package once,
then require the fresh immutable V2 `canary-start` PASS before dispatching
any later mode.

### Admin Stage C V2 executor upload checkpoint (2026-07-30)

- One fresh root-only V2 stage was created after proving the V2 stage,
  runtime-token root, canary name and port were absent and the historical
  formal live/ready endpoints were healthy. The exact candidate and rollback
  units were copied from the preserved V1 stage and reverified against their
  accepted SHA-256 values; V1 files and results were not changed.
- The exact audited V2 compressed transport was sent once to only the API-C
  host with overwrite disabled, root ownership and mode `0600`. The
  control-plane file result completed successfully.
- The remote verification command returned
  `NOTEAI_ADMIN_STAGE_V2_UPLOAD_VERIFY=PASS`. It proved the compressed and
  decompressed SHA-256 values, installed the exact audited executor as
  root-only mode `0600`, compiled it in memory, removed the compressed
  transport and left exactly the candidate, rollback and executor files in
  the fresh V2 stage.
- No V2 canary, formal service restart, unit replacement or database session
  has started. Readiness remains internal `19/29`, public `19/38`,
  production gate `109/109`.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
run the fresh immutable V2 `canary-start` exactly once and require PASS,
three health rounds, zero database/service mutations and zero peer regression
before `canary-validate` is eligible.

### Admin Stage C V2 canary identity checkpoint (2026-07-30)

- The fresh immutable V2 `canary-start` ran exactly once and returned
  `NOTEAI_ADMIN_STAGE_CANARY_START=PASS`. The corrected exact-mount path
  created and started the isolated Canary and passed its bounded health gate;
  the formal service and installed unit were not mutated.
- The fresh immutable V2 `canary-validate` then ran exactly once and returned
  `NOTEAI_ADMIN_STAGE_CANARY_VALIDATE=PASS`. It accepted the exact target
  Admin image/revision/runtime identity, hardening, loopback port, writable
  model-data bind shape, bounded clean logs, empty Canary data directory and
  three live/ready/readiness-payload rounds.
- Neither mode made a database connection or write, provider call, object
  write or formal service mutation. Readiness remains internal `19/29`,
  public `19/38`, production gate `109/109`.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
run the immutable V2 `acl-audit` once inside its forced read-only transaction
and require the complete table/column/sequence/function/ownership/membership
negative matrix PASS with terminal rollback before `session-open` is
eligible.

### Admin Stage C V2 ACL mismatch and abort checkpoint (2026-07-30)

- The unique immutable V2 `acl-audit` returned
  `NOTEAI_ADMIN_STAGE_ACL_AUDIT=FAIL`. Its immutable result is
  `failure_detail_code=acl_matrix` with `connected_unknown_count=0`; it was
  not retried. The formal service, installed unit and task session were not
  mutated.
- A targeted read-only diagnosis reused the exact audit source in a separate
  forced read-only transaction and terminal rollback. Its secret-free
  mismatch set contained only
  `visible_system_settings_exact=false`; the command printed that complete
  result and then returned nonzero solely because its trailing heredoc
  delimiter was parsed as Python. A first narrow follow-up heredoc stopped at
  Python parsing before opening a database connection.
- A final compact narrow query opened one read-only transaction, selected only
  `system_settings.key,is_secret`, rolled back and closed before printing. It
  returned `VISIBLE_COUNT=0`, an empty key list and
  `NOTEAI_ADMIN_STAGE_V2_SETTINGS_DIAG_COMPACT=PASS`; no setting value,
  Secret, user data or credential was read or printed.
- The unique V2 `abort` then returned
  `NOTEAI_ADMIN_STAGE_ABORT=PASS`. The Canary and port were removed, token/data
  residue is zero, the historical formal service remains the known healthy
  outcome and V2 failure evidence is preserved.
- This is now a precise production RLS/visibility-contract question, not an
  unknown runtime state. Readiness remains internal `19/29`, public `19/38`,
  production gate `109/109`.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
reconcile the zero visible `system_settings` rows against the versioned
migrations, `production_schema_roles` contract, Admin source and tests; make
no production ACL or data mutation until that read-only reconciliation proves
whether the defect is the deployment state or the executor expectation.

### Admin Stage C settings reconciliation and truthful-status blocker (2026-07-30)

- Three independent read-only audits and the main-source review agree that
  V2's exact-two-row expectation is false. Migrations `0001`–`0016` never seed
  `model_registry` or `crawler_config`; the RLS policy only filters existing
  rows. The disposable PostgreSQL contract intentionally inserts one eligible
  row and expects one visible row, while the production restricted-read
  contract permits zero rows, uses bundled fallback data and forbids lazy
  persistence.
- V3 must therefore accept an empty or partial visible subset only when every
  visible row is a non-Secret member of the exact two-key allowlist. It must
  also bind the `system_settings` policy's table, command, PUBLIC role,
  predicate and no-`WITH CHECK` shape instead of using data cardinality as a
  proxy. No production setting row, ACL or policy change is authorized or
  needed.
- An optional API-role aggregate command was abandoned after its compact
  Python payload failed syntax parsing before connecting to the database. It
  was not retried; database connections, transactions and writes were zero.
  The accepted V5 ledger/migration hashes, complete runtime grant matrix,
  exact policy-name set and successful runtime SELECT already distinguish the
  observed empty set from a missing table grant.
- Independent review found a separate real release blocker. With zero
  `crawler_config` rows, b55 production Admin falls back to the bundled
  `model/crawler_config.json`, whose `enabled=true` is rendered by the Admin
  UI as “running”, although Trends and Tracking are not started. This is a
  truthful-status defect and blocks Admin credit even though the ACL itself is
  safe.
- The smallest non-data repair is to change the bundled fallback to
  suspended-by-default and add a production restricted-read regression test.
  It requires a fresh Admin-only immutable build/publication/deployment
  identity; the historical V1/V2 failure and abort evidence remains preserved.
  Readiness remains internal `19/29`, public `19/38`, production gate
  `109/109`.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
implement and verify the suspended-by-default fallback with the smallest
source/test diff, create a clean pushed checkpoint, then build and publish a
fresh Admin-only artifact before any new Stage C canary or formal promotion.

### Admin truthful-status source checkpoint (2026-07-30)

- The bundled fallback now sets `enabled=false` and `last_run=null`; no
  runtime code, database row, migration, ACL, provider path or public surface
  was changed. With no production settings row, Admin therefore reports the
  actual suspended/not-started state instead of a synthetic running state.
- The existing production restricted-read test now proves both the helper
  fallback and the real `/admin/crawler/status` response return
  `enabled=false` and `last_run=null` without lazy persistence or Cookie
  setting access.
- Targeted verification passed: Admin first-launch contract `10/10`, API
  contracts `156/156`, frontend static `18/18`, Render deployment `17/17`,
  full Python suite `1119/1119` with `28` expected skips, production gate
  `109/109`, and internal readiness gate remains `19/29` / public `19/38`.
- A targeted independent read-only diff review found the source change
  minimal and sufficient. Its one blocking test-coverage request was the real
  endpoint assertion above, which is now implemented and passing. It also
  confirmed that the Tracking worker safely remains disabled by default;
  any future Tracking promotion must explicitly and audibly enable it.
- Readiness is intentionally unchanged. The current historical Admin image
  remains in production, while the new source must first receive a clean
  checkpoint and a fresh Admin-only immutable build/publication identity.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
commit and push the exact four-file source/risk/handoff/test checkpoint, then
perform an Admin-only AMD64 build, scan and bounded private publication without
rebuilding or redeploying API-C/API-F.

### Admin truthful-status pushed checkpoint (2026-07-30)

- Commit `5335bdaed933b1f999b5f819c047ec50c11821ae` contains exactly the
  suspended-by-default fallback, the endpoint regression assertions and the
  associated Secret-free handoff/risk records. It was pushed normally to
  `origin/codex/quality-stabilization-real-chain`.
- Local HEAD, the upstream tracking ref and the exact pushed commit match;
  ahead/behind is `0/0` and the tracked worktree is clean. No force-push,
  merge, production resource mutation or deployment occurred.
- The Docker build context excludes `.codex`, tests and evidence files. Of
  the four checkpoint files, only `model/crawler_config.json` enters the
  runtime image; the independent `admin-runtime` target permits a fresh
  Admin-only build without rebuilding API-C, API-F or any worker role.
- Readiness remains internal `19/29`, public `19/38`, production gate
  `109/109`. The historical Admin service and image remain active and
  unchanged.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
prove the isolated AMD64 builder, source, scanner cache and private Registry
baseline read-only; then build, inspect, SBOM/scan and publish exactly one new
immutable Admin tag with no API build, database access, service mutation or
public endpoint.

### Admin builder availability reconciliation checkpoint (2026-07-30)

- Fresh ECS detail is authoritative over the stale three-row list: the
  isolated AMD64 builder is stopped and explicitly marked insufficient
  account balance. It therefore has no eligible Cloud Assistant target or
  remote session. Its persistent disk and historical Build10/publication
  evidence were not deleted, overwritten or read after the stop.
- The builder remains the historical temporary pay-as-you-go 4-vCPU/16-GiB
  x86_64 host. It has no RAM role or key pair; the prior temporary publisher,
  private Registry link and Docker auth remain absent by the last accepted
  cleanup evidence. No start, recharge, credential, role, endpoint, command
  or Registry action was attempted in this reconciliation.
- Local Docker has no running daemon and Colima is stopped. Project rules
  require explicit confirmation before starting a Docker service, so neither
  was started. The local architecture is arm64 and is not accepted as native
  release evidence.
- The existing GitHub Actions release path is authenticated, native x86_64,
  checksum-pins Syft and Trivy, performs no login/push/container start and
  retains evidence for fourteen days. The smallest safe continuation is a
  source-tree-external exact-list reduction of the canonical five-role script
  to Admin only, preserving exact `5335bda` source cleanliness and the raw
  vulnerability gate. It does not authorize Registry publication or
  deployment.
- Production API-C, API-F and historical Admin were not touched. Readiness
  remains internal `19/29`, public `19/38`, production gate `109/109`.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
run one native GitHub Admin-only build against exact `5335bda`, download and
independently validate its exact eleven-file evidence bundle, then establish
a funded/private publication path before any Registry or service mutation.

### Admin native-evidence trigger correction checkpoint (2026-07-30)

- Independent review identified one deterministic pre-dispatch blocker:
  `workflow_dispatch` currently cannot be the Admin trigger because the active
  workflow does not exist on the repository's `main` default branch. The
  historical manual run proves only its historical control state and was not
  treated as current authorization. No workflow was dispatched.
- The corrected feature-branch contract adds one Secret-free request file.
  Only a push event whose head commit first adds that exact path maps the
  release ref to exact `5335bda` and scope to `admin`; ordinary workflow/script
  pushes retain the existing exact-head five-role behavior.
- Before build, the workflow verifies the push event, branch, request path,
  exact release commit and request JSON. After exact-source checkout with full
  history, it reads the request from the controller commit, fixes its SHA-256
  and requires all Registry, deployment, database, service and public-traffic
  authorizations false.
- The Admin evidence summary binds the trigger event, controller commit,
  request path/hash and both canonical/executed script hashes. The five-role
  artifact name remains backward compatible; only Admin appends `-admin`.
- Local syntax simulation of the external Admin script and its summary
  constraint passed. Workflow tests, readiness integration, Admin/Render
  regression, YAML parsing, production gate and diff checks remain green.
  A final independent narrow review found deterministic blocker count `0`;
  the canonical request SHA-256 is
  `3b71fd07baa0a7bb80affb906c3ef0dfbc539429071c9f877431e575a2cb8c50`.
  No GitHub run, Registry action, database access or service mutation has yet
  occurred.

Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is:
commit and push the one-shot request/controller checkpoint once, observe the
single exact-source Admin run to a terminal artifact state without rerun, then
download and independently accept or reject the eleven-file bundle.

### Admin native-evidence V1 trigger incident and V2 correction checkpoint (2026-07-30)

- The reviewed V1 controller was committed and pushed once as exact
  `e7766ab903a2f2721521552c62a18573bc9990de`; local and upstream were clean at
  `0/0`. GitHub created exactly one target push run, `30549134106`. Its
  revision, checkout, native-runner, scanner, build/inspect/scan and artifact
  upload steps all completed; only the terminal zero-Critical/High gate failed.
- Terminal artifact metadata and downloaded contents exposed a scope error
  before acceptance: the artifact was named for `e7766ab`, contained `43`
  files and all five roles, and its summary bound release commit `e7766ab`
  with no Admin control block. Job environment evidence showed
  `NOTEAI_RELEASE_SCOPE=five`. GitHub had evaluated the pre-checkout
  `github.event.head_commit.added` expression false and the workflow had
  silently selected its ordinary five-role fallback.
- This 43-file bundle is retained only as failure diagnosis. It is not exact
  `5335bda` Admin evidence, gives no release authorization or readiness credit,
  and will not be rerun. Registry login/push, private publication, deployment,
  database, service, provider and public-traffic actions remained zero.
- The local V2 correction removes all event-payload file inference. It first
  checks out the controller commit with full history, then fail-closed resolves
  the release from real Git objects: one parent, exactly one newly added and
  non-renamed V2 request, regular-blob mode, exact ten-key schema, fixed
  request SHA-256, exact `5335bda` ancestry and one-time addition history.
  Registry publication, deployment, database, service mutation and public
  traffic remain explicitly false. Only after those checks does a second
  checkout select exact `5335bda` and externalize the canonical Admin-only
  script transformation.
- The V2 request is
  `.github/release-requests/admin-5335bda-v2.json`, schema `2`, with SHA-256
  `c5bd56148af0d780d3955ebb9ed5dafe0c7507ba6974da86b5830323c77009ef`.
  Static workflow/request tests pass `7/7`; combined readiness tests pass
  `65/65`; production gate passes `109/109`; YAML/JSON parse and diff checks
  pass. The exact control shell was also executed from a synthetic child
  commit containing the staged tree: it resolved exact `5335bda`, scope
  `admin`, the V2 path/hash and the synthetic controller commit. A deliberately
  wrong pinned hash failed closed, while a no-request historical commit
  resolved to its own SHA and five-role compatibility. This pre-push
  simulation also caught and removed a local Bash `mapfile` portability
  dependency. Independent review requires this two-checkout controller
  contract and confirms the V1 artifact cannot be reused. Its final audit of
  the staged implementation found deterministic blocker count `0` and
  required correction count `0`.

Readiness remains internal `19/29=66%`, public `19/38=50%`; the last credited
item remains `api_f_current_release=VERIFIED`. Current exact task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is to
form the V2 controller commit, execute its resolver locally against that exact
commit, independently review blocker count `0`, push once, and accept only an
eleven-file artifact bound to exact `5335bda`, Admin-only scope and the fixed
V2 request hash.
