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
- Internal deployment readiness: `17/29 = 59%`.
- Public launch readiness: `17/38 = 45%`.
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
  must fail closed on cache, image, seven-file prefix, scanner or report
  drift, and must produce a new complete 43-file bundle before publication;
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
- Status remains `17/29 = 59%` internal and `17/38 = 45%` complete-public.
  The only task remains `PROD-FIRST-LAUNCH-API-C-INTERNAL-001`; the next
  acceptance boundary is a hash-bound offline continuation producing a
  complete independent 43-file five-role bundle. Publication, deployment,
  service mutation and public traffic have not started.

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
- full Python suite: `1081/1081`, 28 explicit skips;
- production readiness gate: `105/105 PASS`;
- internal readiness: fail-closed `17/29 = 59%`;
- public readiness: `17/38 = 45%`;
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

Current remaining steps:

- keep the pushed `d66827f` control checkpoint and the recovered build9
  evidence immutable while preparing a fresh verified scanner cache;
- execute only `PROD-FIRST-LAUNCH-API-C-INTERNAL-001`: privately publish the
  exact current immutable API product, then reuse the existing schema/roles,
  managed secrets and private storage; establish a fresh read-only baseline
  before any service mutation, preserve the historical release for
  deterministic rollback and keep the service loopback-only with public
  traffic zero;
- continue through the dependency graph without stopping at the checkpoint
  or task boundary.
