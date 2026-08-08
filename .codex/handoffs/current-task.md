# NoteAI Internal Production Readiness Handoff

> Updated: 2026-08-08 (Asia/Shanghai)
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
- Internal deployment readiness: `20/29 = 69%`.
- Public launch readiness: `20/38 = 53%`.
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

### Admin exact 5335 native source-candidate acceptance checkpoint (2026-07-30)

- V2 controller `e7039a3fe73b539325593cf1ba78dcd4a9949910` was committed,
  locally executed against its own exact Git object, and pushed once. Its
  resolver returned exact release `5335bdaed933b1f999b5f819c047ec50c11821ae`,
  scope `admin`, V2 request path and SHA-256
  `c5bd56148af0d780d3955ebb9ed5dafe0c7507ba6974da86b5830323c77009ef`.
  Local/upstream divergence returned to `0/0`.
- GitHub created exactly one V2 run, `30550548144`, job `90897767171`.
  Controller checkout, Git-object resolution, exact-source checkout, native
  source/model verification, pinned scanner installation, Admin build/inspect/
  inventory/scan and artifact upload all passed. The run's only failure was
  the intentionally unsuppressed terminal zero-Critical/High gate.
- The artifact identity is
  `native-amd64-release-evidence-5335bdaed933b1f999b5f819c047ec50c11821ae-admin`.
  It contains exactly eleven regular files; summary SHA-256 is
  `19cbf14415e05d614e7e70caed67ecfefac2c12ae726edaae7a3525cb88d38f7`.
  The fresh local Admin image ID is
  `sha256:9ab915287427e58b1be80faa3a4252eb98463519967aad0e18329ad74d6d8cf7`,
  distinct from both reviewed b55 Admin build identities.
- Independent raw review found content blocker count `0`: linux/amd64,
  `noteai`, Admin label/environment, exact OCI revision/source/version/created,
  entrypoint/CMD, Buildx config, Trivy metadata and eighteen RootFS DiffIDs
  cross-link. Base indices and AMD64 children remain pinned; SBOM has `3076`
  components; the exact 23 raw vulnerability rows remain equal to b55 at
  `4 Critical / 19 High`, fixed-version empty, with zero secret/browser/
  forbidden-OS findings and exactly one `cryptography 48.0.1`.
- The full b55-to-5335 image-context delta is exactly
  `model/crawler_config.json`; its fallback is `enabled=false` and
  `last_run=null`. Dockerfile, API requirements, entrypoint, Admin start,
  compose hardening and production process-call graph remain unchanged.
- Secret-free GitHub run/artifact receipt is
  `deploy/production/evidence/production-admin-native-source-candidate-verified-20260730.json`.
  Exact-product source VEX, review and verifier are:
  `security/vex/5335bda-admin-github-native-release-evidence.json`,
  `security/vex/5335bda-admin-github-native-release.vex.cdx.json`,
  `security/vex/5335bda-admin-github-native-release-review.json`, and
  `tools/verify_5335_admin_native_release_vex.py`.
- The verifier binds all eleven raw hashes, run/job/artifact receipt,
  controller/workflow/request/canonical/executed-script hashes, exact image
  and scan identities, one-file delta, prior-row equality and historical
  identity separation. Registry digest remains null; Registry publication,
  deployment, database, service mutation and public traffic authorizations
  are all false. The historical b55 publication authorization is not reused.
- Focused Admin VEX/readiness tests pass `23/23`; production readiness tests
  pass `20/20`; production gate is `110/110 PASS`; JSON, compile and diff
  checks pass. The full Python regression passes `1128/1128` with `28`
  intentional skips. The internal ledger now cites the source-candidate
  evidence but deliberately keeps `admin_current_release=UNVERIFIED`, internal
  `19/29=66%` and public `19/38=50%`.
- Independent read-only publication-path audit found no compliant continuation
  that avoids new authority or cost: repository and branch environments expose
  no ACR/Aliyun/OIDC publication credential names; the GitHub artifact is
  evidence-only and contains no relayable OCI image; API-C/API-F are expressly
  excluded from build/publish duty; and the stopped arm64 local runtime cannot
  provide native AMD64 or private-Registry evidence. The retained isolated
  AMD64 publisher remains stopped for insufficient account balance. No local
  Docker/builder start, cloud/Registry write or production-host mutation was
  performed during that audit.

Current exact task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`; the last
credited item remains `api_f_current_release=VERIFIED`. The next acceptance
boundary is a fresh, separately authorized private Admin publication:
re-establish a funded native AMD64 publisher, bind a new local/config identity
and fresh scan/SBOM to one new immutable Admin tag, perform one no-retry
push/readback with no public endpoint, then clean all temporary access before
any V3 canary or service mutation.

### Admin funded native-builder attempt blocked and cleaned (2026-07-31)

- The product owner confirmed the balance was effective and authorized only
  the existing 4-vCPU/16-GiB x86_64 pay-as-you-go builder for at most two
  hours, one Admin private publication and full cleanup. The cost window was
  fixed at `2026-07-30T22:59:08+08:00` through
  `2026-07-31T00:59:08+08:00`; no new paid resource, production service,
  database or public-traffic authority was added.
- Fresh builder preflight proved native `x86_64`, Docker active, available
  memory `15028 MiB`, available disk `83010 MiB`, and zero running container,
  Docker auth entry, build/push process or database connection. Both retained
  b55 repositories had exact HEAD and only the three expected materialized
  LFS model files. Their credential-free HTTPS origins agreed and resolved
  exact upstream checkpoint `1c7c9c5`; a new root-only task clone checked out
  exact `5335bda` tree `38e574e…37cd` and independently verified the three
  model artifacts.
- Historical acceptance, publication and scanner-cache hashes remained
  present. One exact fresh cache copy retained DB
  `43c58b4…bfa0` and metadata `c22e061…9f59`; its update/download ages were
  under 24 hours and next update remained in the future. Fixed local Trivy
  `0.72.0` and Syft `1.49.0`, the canonical script `639941a…7d3a`, exact
  Admin transform `a242097…22c`, empty Docker config and restricted offline
  Trivy shim were independently accepted before build.
- Build attempt 1 ran once and failed after `61` seconds before image build:
  direct `buildx imagetools inspect` could not reach Docker Hub. Its only
  evidence file was an empty Python base-index file; local image, scan,
  Registry login/push, database connection and service mutation counts were
  all zero. Anonymous bounded probes confirmed Docker Hub Registry and token
  endpoints unreachable while GHCR and Public ECR returned expected
  unauthenticated responses; the daemon had one configured mirror.
- The only corrected path preserved the canonical script and
  `buildx build --pull` bytes. It copied two independently accepted historical
  raw base-index documents and installed a hash-bound Docker wrapper that
  served only the canonical Python/Node inspect calls; every other Docker
  command passed unchanged to `/usr/bin/docker`. Negative and passthrough
  checks passed before the corrected build.
- Corrected attempt 2 ran once with an independent `1800`-second hard timeout.
  Both exact base-index calls passed, then the build remained in the pinned
  Admin Python dependency-install step and was canceled at exactly
  `30:00 / exit 124` while downloading the public dependency set. It produced
  no local image and no scan. The retained log SHA-256 is
  `f46e646…3722`; the two index hashes are `8fc034c…c8bc` and
  `2cbba3a…587d`. Automatic and manual retry counts remained zero.
- Post-timeout audit proved task/running containers, build/push processes,
  database connections, Docker auth, target image and Trivy calls all zero.
  Registry repository/tag reads, token issuance, login, push, manifest
  readback, ACR/IAM/VPC-link changes and production mutations were never
  started. Therefore no Stage-A sidecar or private publication identity
  exists and no readiness credit is possible.
- Eight exact top-level temporary task paths—source, tools, scanner cache,
  binary/wrapper directory, base-index cache, Docker config, build
  environment and Admin script—were removed without touching
  historical b55 evidence or Docker cache. Only two root-only failure
  directories remain: six regular files, five directories, zero links,
  special files, unsafe modes or credential-pattern matches. The builder was
  stopped in saving mode and read back `已停止` before the two-hour deadline.
- Secret-free receipt and fail-closed verifier:
  `deploy/production/evidence/production-admin-private-publication-attempt-blocked-clean-20260731.json`
  and `tools/verify_admin_private_publication_attempt_evidence.py`.
- Final local verification passed: exact receipt verifier; `10/10`
  receipt mutation/duplicate-key tests; combined readiness-focused tests
  `46/46`; production gate `111/111`; internal gate `19/29`; full repository
  suite `1138/1138` with `28` expected skips; JSON parse, `py_compile`,
  `git diff --check` and Secret-free document scan. The independent read-only
  audit first found partial-field and duplicate-key fail-open paths, then
  confirmed blocker `0` after canonical semantic hashing, strict duplicate-key
  rejection, sensitive-value scanning, exact time/source/cleanup binding and
  exhaustive mutation tests.
- Atomic evidence/check cleanup checkpoint:
  `f2c4b0b3da83c522a762a6ec878276b6fb94865b`.

Readiness truth remains internal `19/29=66%`, public `19/38=50%`; the last
credited item remains `api_f_current_release=VERIFIED`. Current exact task
remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. A new builder-cost
authorization is not yet actionable: first establish, offline and
independently, a package-download or prewarmed-cache path that preserves exact
source/model bytes, pinned base identities, canonical `--pull`, unsuppressed
raw scans and a fresh Registry identity. Only then may a new bounded native
build precede Stage A and the still-unattempted single private push.

### Admin dependency-cache export and transfer plan prepared, not activated (2026-07-31)

- Takeover began from exact local/upstream checkpoint
  `8c983d3fc15a33065df5319470729f82d5e2c2a4`, clean `0/0`. The prior
  two-hour builder authority had already expired; the stopped builder and
  zero-publication cleanup evidence were re-used rather than rerun. No active
  cache request, executable dependency-cache job, provider artifact,
  authenticated download, builder start, Registry action or production
  mutation was created in this stage.
- The inert V2 controller is
  `.github/workflows/admin-dependency-cache-export.yml`; its only trigger is a
  future one-file addition of
  `.github/release-requests/admin-5335bda-dependency-cache-v2.json`.
  `tools/verify_admin_dependency_cache_export_plan.py` distinguishes
  `PREPARED_NOT_TRIGGERED`, `ARMED_OR_TRIGGERED_EXACT`,
  `CONSUMED_OR_INVALID` and `INVALID` from real Git history. A request must be
  the unique regular-file change in a single-parent child of the reviewed
  plan and must remain an unchanged `100644` blob in current HEAD; reruns,
  deletion/untracked recreation and request-path reuse are rejected. ARMED
  never claims a provider result.
- The first pushed inert checkpoint `c0d049b56aa6efaff7133ac44a9fef7f010cd097`
  exposed a GitHub parser-context false negative that local YAML parsing had
  missed: run record `30572921215` rejected job-level
  `${{ runner.temp }}` before job creation. The record has `jobs=[]`,
  `artifacts=[]`, ran for zero billable job minutes, made no network build or
  resource mutation and was not rerun. `DOCKER_CONFIG` is now defined only in
  the four step scopes where GitHub permits the `runner` context, and the plan
  verifier has a regression gate against job-level reuse.
- Corrected core checkpoint
  `dd3cdce4692a40b5e2bfb9c786dcb4da55aa6fb6` was accepted by GitHub's
  parser and path filter: no dependency-cache workflow run exists for that
  SHA. The repository's ordinary push run `30573970320` and pull-request run
  `30573973644` each completed all CI steps successfully in `2m22s`. No
  activation request or cache artifact was created.
- The export builds only exact Dockerfile lines `1-80` with the two
  requirements files, pinned Python/Node indices, canonical `--pull`,
  `linux/amd64`, max provenance, raw progress and a local cache-only output.
  An isolated empty Docker config proves zero BuildKit auth entry; no
  `--secret` or `--ssh` input exists. The actual `runtime-common` graph has
  exactly three network-bearing dependency vertices: Meituan npm, apt and
  pip. The pruned CryptoJS stage is deliberately not claimed.
- A distinct fresh consumer validates the complete OCI descriptor and
  BuildKit cache-config graph, including unique root-layer descriptors,
  complete parent closure, reachability of every layer and reachability of
  every record from a result-bearing record through input links. It imports
  the local cache, requires those three vertices cached, removes the external
  cache, then performs a second build with no `--cache-from` against the exact
  full Dockerfile and full release context through `runtime-common` line
  `100`. That replay must again cache the same three network vertices. It
  truthfully consumes application/model source context but exports neither a
  consumer cache nor an image.
- Strict validators reject duplicate/non-finite JSON, unexpected files,
  unreferenced or internally invalid OCI/cache-config records, unsafe or
  sparse tar members, path traversal, hard/special links, excessive expansion
  and non-contiguous chunks. The gzip is capped at `3.5 GiB`, raw tar at
  `5 GiB`, complete upload input at `3.75 GiB`, each non-chunk file at
  `128 MiB`, and the provider artifact at `4 GiB` with reserved headroom.
  Cleanup of both builders, all transient Docker objects and the empty Docker
  config precedes the only one-day public-repository upload.
- Artifact-contained helpers are evidence only. The workflow executes
  separately hash-pinned controller copies with explicit `bash`. A later
  authenticated local step must use `gh` to read and validate the exact
  artifact metadata before issuing the ZIP request; missing, expired,
  oversized or identity-drifted metadata fails closed. The ZIP is then
  received through a declared-size-bounded stream and must match the
  provider-returned SHA-256 and byte size before any extraction. Artifact/run
  identity, control commit, request and final sums are bound into a separately
  hashed Secret-free receipt. Only after that proof is the original ZIP split
  into receipt-bound contiguous `256 MiB` transport parts; the original
  multi-gigabyte ZIP is not sent as one cross-provider file. The target
  builder accepts only the receipt trust root, rechecks every part, reassembles
  and revalidates the exact ZIP in task-local storage, recreates the exact
  recorded BuildKit daemon image, and requires
  `BUILDX_BUILDER == NOTEAI_BUILDX_BUILDER`.
- The unchanged canonical Admin build must inherit that same
  `BUILDX_BUILDER` in the same newly authorized builder window. Cache import
  is not a release credit: a new Admin image, fresh SBOM/raw Trivy scan,
  immutable private push/readback, Stage A, dedicated runtime, ACL negative
  matrix, reversible promotion, API-C/API-F non-regression and complete
  cleanup remain mandatory.
- Local verification passes the plan verifier in
  `PREPARED_NOT_TRIGGERED`; corrected focused
  cache/export/provider/readiness tests `74/74`; production gate `112/112`;
  internal gate `19/29`; full Python regression `1176/1176` with `28` skips;
  shell syntax, Python compile, strict JSON/YAML parsing and
  `git diff --check`. Three bounded independent read-only delta audits against
  the corrected hashes each returned
  `Critical 0 / High 0 / Medium 0 / Low 0`; none repeated the full matrix or
  changed local/remote state.

Readiness remains internal `19/29=66%`, public `19/38=50%`; the most recent
credit is still `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary requires
new explicit authority for exactly one GitHub-hosted run capped at `120`
minutes, the one-day public-repository artifact up to the stated limits, and
one authenticated local download/cross-provider transfer. A subsequent
fresh PAYG builder window and one Admin private publication must be separately
authorized because the prior two-hour builder authority is exhausted.

### Admin dependency-cache one-day retention hardening checkpoint (2026-07-31)

- The product owner explicitly authorized one GitHub-hosted dependency-cache
  run capped at `120` minutes, one public-repository artifact retained for at
  most one day with its internal gzip capped at `3.5 GiB`, complete upload
  input capped at `3.75 GiB` and outer provider ZIP capped at `4 GiB`, one
  authenticated download and cross-provider transfer, followed on cache
  acceptance by one new
  `4-vCPU / 16-GiB / AMD64` builder window capped at two hours, one Admin
  private publication and complete cleanup.
- Before any external activation, the exact parent-bound request was generated
  only as an untracked local file. A bounded independent read-only audit found
  that the provider metadata, preflight receipt and final transfer receipt
  accepted a retention interval of up to two days, despite the authorization,
  template and workflow all requiring one day.
- The untracked request was deleted before staging, commit or push. Therefore
  its addition history remains zero and GitHub Actions, artifact creation,
  authenticated download, builder start, Registry action, production service,
  database and public-traffic mutation all remain zero. The one-shot
  authorization has not been consumed.
- `tools/verify_admin_dependency_cache_provider_download.py` now uses one
  `86,400`-second maximum for metadata, preflight and receipt validation.
  Exactly one day passes and one day plus one second fails. The plan verifier
  rejects the historical two-day literal and requires the one-day control.
- The updated workflow SHA-256 is
  `d01bf03d4725bb82c2ff34d35aeb0379a6987200278321a436d77d0b7fcd4870`;
  the provider verifier SHA-256 is
  `ca05697d12b8c02b183b1c611c33781d63641c5369bc54b2508a538591a0986b`.
  Focused cache/export/provider tests pass `40/40`, production readiness gate
  passes `112/112`, Python/YAML parsing and `git diff --check` pass.
- The first full-suite run exposed one deterministic local evidence-list
  expectation that did not yet include the new one-day retention regression
  test path. It made no external action and was corrected only by adding that
  path to the exact manifest expectation. The second full Python regression
  passes `1178/1178` with `28` intentional skips.

Readiness remains internal `19/29=66%`, public `19/38=50%`; the last credited
item remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is a
normal correction checkpoint with green remote CI, followed by exactly one
new request-only child whose direct parent and bytes are freshly rebound to
that checkpoint. No pre-fix request SHA may be reused.

### Admin dependency-cache V2 terminal failure and inert V3 recovery checkpoint (2026-07-31)

- Read-only takeover started on
  `codex/quality-stabilization-real-chain` at exact local/upstream
  `83b89262a33aed2cfa9fd623f232a66824398c2e`, clean `0/0`. The retained V2
  request remains the unique `100644` request-only addition at that commit;
  the V2 workflow, template, request and verifier are frozen byte-exact.
- The authorized one-shot V2 execution is terminal:
  GitHub run `30591103183`, job `91033410635`, attempt `1`, exact control
  commit `83b89262a33aed2cfa9fd623f232a66824398c2e`, conclusion `failure`.
  Controller/release checkout, request resolution, immutable source checks
  and isolated builder creation passed. Export stopped at post-build evidence
  validation with `FAIL: BuildKit platform changed`; portability, final
  validation, upload and provider confirmation were skipped. Cleanup also
  failed with `rmdir: Directory not empty`. The provider artifact API returned
  `total_count=0`, and the attempt was never rerun.
- Source-level reconciliation proves two control defects rather than a source
  or target-architecture drift. BuildKit `v0.31.2` emits SLSA V0.2
  `invocation.environment` with exact builder host
  `platform=linux/amd64` and reviewed `dockerfileVersion=1.25.0`; V2 compared
  that complete object to a one-field object. The real target remains
  independently bound by the hash-pinned `--platform linux/amd64`, exact
  LLB `op.platform` objects and pinned base-image identities. Buildx also
  writes client state under `DOCKER_CONFIG/buildx` unless `BUILDX_CONFIG` is
  separate, so V2's empty-config `rmdir` assumption was invalid.
- Secret-free terminal evidence is
  `deploy/production/evidence/admin-dependency-cache-v2-attempt1-failed-20260731.json`,
  with exact verifier
  `tools/verify_admin_dependency_cache_v2_failure_evidence.py`. It binds
  artifacts/upload/provider confirmation/authenticated download/cross-cloud
  transfer to zero; new cloud-builder start, Admin ACR private-repository
  read/token/login/push/manifest operations, production service, database and
  public-traffic mutations also remain zero. Public base-image and dependency
  reads inside the GitHub cache build are not misclassified as zero. Ordinary
  push and PR CI runs `30591103151` and `30591105105` passed for the V2
  activation commit.
- The single GitHub-run authorization is consumed and V2 attempt 1 is
  permanently no-rerun. The unused artifact download/transfer and conditional
  new `4-vCPU / 16-GiB / AMD64` builder/Admin ACR publication authority remain
  dormant because cache acceptance did not pass; no builder may start from
  that condition now.
- Append-only V3 is an inert recovery plan, not an active request.
  `.github/release-requests/admin-5335bda-dependency-cache-v3.json` does not
  exist and has no addition history; the verified state is
  `PREPARED_V3_NOT_TRIGGERED`. V3 pins the BuildKit `v0.31.2` multi-architecture
  digest, requires exact host/frontend environment and exact
  `Architecture=amd64 / OS=linux` LLB target objects, and reuses the frozen
  deep V2 OCI/cache/archive validation only after that independent proof.
- Docker authentication and Buildx client state now use distinct fixed
  `RUNNER_TEMP` children. The V3 transient-state verifier requires an exact
  empty Docker auth file, bounded regular Buildx state, safe ownership modes,
  no links/special files/hardlinks and no credential-like content. Cleanup
  aggregates builder-removal, Docker-object parity, state-validation and root
  removal failures while still attempting both task-root removals; upload is
  impossible unless cleanup and final portable-bundle validation both pass.
  The reviewed one-day retention, `3.5-GiB` gzip, `3.75-GiB` upload-input,
  `4-GiB` provider and authenticated receipt-bound transfer limits are
  unchanged.
- A bounded technical delta audit then exposed four source-level proof gaps
  before any V3 activation: cleanup could stop before removing both roots
  when its verifier was absent or drifted; duplicate-key or otherwise opaque
  Buildx JSON was not constrained by an exact schema; platform semantics had
  only synthetic tests; and the copied V3 wrapper plus frozen V2 base
  verifier had no runtime-shape regression test. The corrected cleanup now
  treats only an unresolved, redirected or non-task-owned `RUNNER_TEMP` as an
  early stop, aggregates verifier/builder/snapshot/parity failures, and still
  attempts both root removals. Behavior tests prove success, missing/drifted
  validation, builder/snapshot/parity failure and symlinked-root handling.
  The transient verifier now rejects duplicate/non-finite JSON, caps the
  Docker config at 128 bytes with exact `{"auths": {}}`, and accepts only the
  pinned BuildKit image plus official Buildx store/local-state path and field
  shapes; embedded config/key material, extra driver options and opaque files
  fail closed. A truthfully labeled
  `SOURCE_PROJECTED_NOT_RETAINED_RUNTIME_METADATA` fixture records the pinned
  BuildKit source boundary without claiming retained V2 runtime metadata, and
  subprocess tests prove the copied two-file verifier trust root passes only
  with the exact frozen base verifier.
- The final reviewed V3 hashes are workflow
  `60b48606e98ce9ea8b81b6afcc910701798cd3dff307661e11ff383dbb2eed39`,
  template
  `2ddca5c392f21cfa3b623197d07c2f8a983715a95ec58042aa0eece8930cd2f3`,
  plan verifier
  `f1de65d37f7bac35fcf1df7ac490a69df0057bef4d0800fbbdaa0ce0b4c85924`,
  bundle verifier
  `c2e318d5d9cbe196d8b9294277c85e1ee986ccb3e1970b3d25a31d28c8da0fef`,
  transient verifier
  `da19c4908fc73ee7bdd74342cf0c626a2db79299672ba5aa0511a7c9d92baae0`
  and cleanup helper
  `b6115cc641c563f90236bcbdea432e0ca18ff9908834f663c6eeadd27ffa3101`.
  Focused cache/readiness tests pass `110/110`; cleanup behavior passes
  `6/6`; production gate passes `114/114`; final full Python regression
  passes `1212/1212` with `28` intentional skips. Bash/Python syntax,
  strict JSON/YAML parsing, `git diff --check`, frozen V2 byte comparison,
  Secret-pattern scan and V3 zero-addition checks pass. The final bounded
  read-only technical re-audit closed M1/M2/L1/L2 at
  `Critical 0 / High 0 / Medium 0 / Low 0`.
- The inert V3 core checkpoint is
  `8434da99b70b3623d619d0fafdac893a97e7b0e3`. GitHub ordinary push CI
  `30595340831` and pull-request CI `30595343141` both completed
  successfully. A fresh Actions API query filtered to
  `.github/workflows/admin-dependency-cache-export-v3.yml` returned an empty
  run list. The core checkpoint therefore installed the request-only
  controller without consuming a V3 run, creating an artifact or activating
  download/transfer/builder/ACR authority.
- The readiness manifest now includes the exact V2 failure receipt and inert
  V3 recovery controls. Production readiness passes `114/114`; internal
  readiness remains fail-closed `19/29=66%` and complete-public readiness
  remains `19/38=50%`. The most recent credited control remains
  `api_f_current_release=VERIFIED`.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The inert V3
checkpoint, ordinary remote CI and zero-run acceptance are complete. The next
acceptance boundary is new explicit authority for exactly one V3 GitHub run.
Only a successful nonzero provider artifact,
fresh-consumer portability, complete cleanup, authenticated bounded
download/transfer and target-side revalidation can activate the conditional
builder path; Admin build/scan/private publication/runtime acceptance and
complete cleanup remain required before readiness may become `20/29`.

### Product-owner delegation and V3 execution authority (2026-07-31)

- The product owner explicitly delegated to the main CTO the authority to
  approve and execute subsequent bounded, previously defined and reversible
  release stages without asking again. This supersedes the prior V3
  authorization stop. It does not authorize fabricating credentials,
  bypassing interactive login, unbounded spend, destructive data actions,
  public DNS/real-user traffic cutover or a false production-complete claim.
- The CTO now authorizes exactly one append-only V3 GitHub
  dependency-cache run capped at `120` minutes, one public-repository
  artifact retained for at most one day with the reviewed
  `3.5-GiB` gzip / `3.75-GiB` upload-input / `4-GiB` provider limits, and
  one authenticated download plus receipt-bound cross-cloud transfer. The
  previously unused transfer authority is explicitly rebound to this V3
  run.
- Only successful fresh-consumer portability, complete transient cleanup,
  nonzero authenticated provider identity and target-side reassembly/import/
  cacheless replay may activate one new `4-vCPU / 16-GiB / AMD64` builder
  window capped at two hours, one Admin ACR private publication and complete
  cleanup. Registry publication remains distinct from deployment acceptance.
- At this authorization checkpoint, branch and upstream are exact
  `e869b146080f3b2b34f3db77ed9916cdcc118b7f`, clean `0/0`; the V3 active
  request is absent, all-ref addition history is zero, the V3 Actions run
  list is empty and plan state is `PREPARED_V3_NOT_TRIGGERED`. Readiness
  remains `19/29`; no external action or credit is claimed by authorization
  alone. The next atomic action is a single-parent request-only child bound
  to the final authorization checkpoint.

### Admin dependency-cache V3 terminal failure receipt (2026-07-31)

- The exact request-only control commit
  `443bb1e534f98232541f44b744d753bfa7c09168` triggered exactly one V3
  workflow run `30596283342`, job `91049234229`, attempt `1`. Controller,
  parent-bound request, exact `5335bda` release checkout and immutable-source
  checks passed. Both pinned BuildKit `v0.31.2` builders bootstrapped, then
  the post-create transient-state check failed closed before export with
  `Buildx state ...flags changed`.
- The job's exact `ubuntu-24.04` image `20260720.247.2` manifest identifies
  Docker Buildx `0.35.0`. Official tag `v0.35.0` (tag object
  `151a9220…75f`, commit `a319e5b1…782`) proves that an empty-config
  `docker-container` create stores exactly one ordered default flag:
  `--allow-insecure-entitlement=network.host`. The V3 verifier incorrectly
  accepted only null/empty flags. This daemon capability is not exercised:
  the frozen export/import commands contain no build-level
  `--allow network.host`, and `security.insecure` remains forbidden.
- Cleanup preserved its initial fail-closed count, removed the two builders
  far enough for the second transient-state validation to pass, attempted
  Docker parity and both fixed-root removals without another observed error,
  and the ephemeral runner completed. Export, portability, final validation,
  upload and provider confirmation were skipped. The provider API returned
  exactly `total_count=0`; authenticated download, cross-cloud transfer, new
  builder start, Admin ACR private read/token/login/push/manifest and all
  production mutations remain zero. V3 is consumed and must never be rerun.
- Ordinary push CI `30596283325` and PR CI `30596285651` each ran `1212`
  tests with `28` skips and had the same sole failure: the inert V3 state
  test still expected `PREPARED_V3_NOT_TRIGGERED` after the retained exact
  activation correctly became `V3_ARMED_OR_TRIGGERED_EXACT`. The assertion
  now binds the retained activation; this is an evidence-state correction,
  not a product-code regression.
- Secret-free terminal evidence is
  `deploy/production/evidence/admin-dependency-cache-v3-attempt1-failed-20260731.json`
  with strict verifier
  `tools/verify_admin_dependency_cache_v3_failure_evidence.py`; their
  SHA-256 values are respectively `6ea71731…6425c` and
  `74c2b3e2…7a012`. The focused failure/plan/readiness tests pass `51/51`,
  production readiness passes `115/115`, JSON and diff checks pass, and the
  internal gate remains `19/29` / public `19/38`. No failed run adds credit.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next
acceptance boundary is an append-only inert V4 plan that asserts exact Buildx
`v0.35.0`/commit before creation and accepts only the one source-proven ordered
default flag while rejecting all additional, reordered or privileged variants.
It must pass local and ordinary remote CI with zero V4 workflow runs before the
main CTO authorizes one new request-only activation under the delegated bounds.

### Inert Admin dependency-cache V4 local acceptance (2026-07-31)

- The V3 terminal receipt checkpoint is
  `10a05ebc5857ece9307af207753b36845b47d704`. Its ordinary push CI
  `30597178856` and pull-request CI `30597180914` both completed
  successfully. The retained V3 activation remains consumed and must never be
  rerun.
- Append-only V4 is prepared on that clean upstream parent but remains inert.
  The active path
  `.github/release-requests/admin-5335bda-dependency-cache-v4.json` is absent;
  local/all-ref and GitHub path addition history are zero; the Actions API
  workflow-path query is zero; and the verified state is
  `PREPARED_V4_NOT_TRIGGERED`. No V4 run, artifact, authenticated download,
  transfer, cloud builder, Admin ACR operation or production mutation exists.
- The workflow binds runner Buildx module/version and a `7`-to-`40`-character
  revision prefix to official Buildx `v0.35.0` source commit
  `a319e5b15052cf6557ceb666eb8ff6e32380b782` before either builder is
  created. Both creates explicitly pass only
  `--allow-insecure-entitlement=network.host`; the transient verifier accepts
  only that exact one-element ordered array and rejects null, empty, split,
  reordered, additional or `security.insecure` flags, embedded config,
  unsafe paths, links and credential-like state.
- The immutable Dockerfile and frozen export/import helpers are checked before
  builder creation for any build-level `--allow network.host`,
  `--allow=network.host` or `--network host` request. V4 preserves the exact
  `5335bda` source, pinned BuildKit `v0.31.2`, separate host/frontend and
  `linux/amd64` target proof, fresh-consumer portability, deep OCI/cache/tar
  validation, one-day retention, `3.5-GiB` gzip, `3.75-GiB` upload-input,
  `4-GiB` provider ceiling and authenticated receipt-bound transfer.
- Cleanup remains aggregate and fail-closed: it attempts both builder removals,
  four Docker-object parity checks, both transient validations and deletion of
  both exact V4 task roots, and it runs before final validation/upload.
  Workflow permissions are only `contents: read`; Registry publication,
  deployment, database, service and public-traffic mutation remain false.
- Final reviewed V4 SHA-256 values are workflow
  `5331e03b…304cc`, request template `6e2a7ba6…614da`, plan verifier
  `b8f05cc1…b9fbf`, transient verifier `a6578845…ea432` and cleanup helper
  `6cc13038…23ab2`. The independent read-only split audit returned
  `Critical 0 / High 0 / Medium 0 / Low 0`, confirmed V2/V3 byte locks and
  zero V4 local/GitHub history/runs, and made no repository or external
  mutation.
- Focused V4/readiness tests pass `62/62`; full repository regression passes
  `1243/1243` with `28` intentional skips; production readiness passes
  `116/116`; internal readiness remains `19/29` and public readiness
  `19/38`. Bash/Python syntax, strict JSON/YAML parsing and
  `git diff --check` pass. The audit also caught a non-core readiness detail
  that would have said the request was absent after a valid activation; the
  text is now state-neutral and a `V4_ARMED_OR_TRIGGERED_EXACT` regression
  test passes in the `21/21` production-gate suite.
- The exact inert checkpoint is
  `7b65c480604ab3aa3381d81e9692d2ed94f7c23c`. Ordinary push CI
  `30598540875` and pull-request CI `30598541927` both completed
  successfully with unit, quality, production-readiness and Docker Compose
  steps green. The active request and local/all-ref/GitHub path addition
  history remain zero; the global Actions inventory filtered by
  `.github/workflows/admin-dependency-cache-export-v4.yml` remains zero.
  Installing the workflow therefore consumed no V4 run or downstream
  authority.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`; no readiness
credit is added by an inert controller. The inert checkpoint, ordinary remote
CI and exact zero-run acceptance are complete. Under the product owner's
standing delegation, the next atomic action is a Secret-free receipt
checkpoint followed by exactly one single-parent, request-only V4 activation
without asking again. Only successful portability, cleanup, nonzero provider
identity, authenticated bounded download/transfer and target-side
reassembly/import/cacheless replay may unlock the conditional `4-vCPU /
16-GiB / AMD64` builder and one Admin ACR private publication.

### Admin dependency-cache V4 terminal failure receipt (2026-07-31)

- The single-parent request-only control commit
  `d5aa7e537590ed138d254b9909a1ac105ee321ce`, whose direct parent is the
  accepted plan checkpoint `afeba532e9dee9c8fa27dfccadcb9f2414534451`,
  triggered exactly one V4 workflow run `30599069993`, job `91057664696`,
  attempt `1`. The active request is the controller's sole added file and
  remains byte-exact at SHA-256
  `ad398386b7f01e8481a741c634da8e66ff1ba1d091bfaf0dff2f719b29172ec4`.
  V4 is consumed, has no rerun authority and must never be rerun.
- Controller checkout, parent-bound request resolution, exact `5335bda`
  release checkout, immutable-source verification and both isolated pinned
  BuildKit builder bootstraps passed. The dependency build command completed,
  after which the hash-pinned verifier failed with
  `FAIL: BuildKit builder environment changed`. Portability, final bundle
  validation, upload and provider identity confirmation were skipped. The
  artifact API returned exact `total_count=0` and an empty list, so
  authenticated download, cross-cloud transfer, the conditional cloud
  builder, Admin ACR publication and all production mutations remain zero.
  Public base/dependency reads may have occurred during the completed build
  and are not misreported as zero network activity.
- The actual runner was Ubuntu `24.04.4`, image
  `ubuntu-24.04/20260726.254.1`, which differs from the request's historical
  recovery-basis observation `20260720.247.2`. Its referenced
  included-software manifest still
  binds Buildx `0.35.0` and Docker client/server `28.0.4`; the runtime
  module/version/revision-prefix gate and both BuildKit
  `v0.31.2`/`linux/amd64` bootstrap gates passed. The image-version drift is
  recorded truthfully but is not classified as the primary failure.
- Independent pinned-source review determines the primary export failure
  without fabricating the unretained runtime object. Buildx `v0.35.0` commit
  `a319e5b1…782` defaults the docker-container driver to
  `writeProvenanceGHA=true`; V4 supplied no `provenance-add-gha=false`
  override. In a GitHub Actions push this installs at least
  `github_event_name` and `github_event_payload` under the BuildKit
  provenance directory. BuildKit `v0.31.2` commit `e42e1bfd…85e9` reads that
  directory and flattens the custom environment into SLSA
  `invocation.environment`. The frozen V3 bundle verifier instead requires
  exact equality to only `platform` and `dockerfileVersion`, so the mismatch
  is deterministic. The complete dynamic event payload was not retained or
  observed and is not claimed.
- Cleanup failed closed twice with
  `FAIL: Docker config contains Buildx or unexpected state`. The helper did
  attempt two builder removals, four Docker-object parity checks and both
  fixed task-root removals, but it suppressed their individual outcomes.
  Therefore builder removal, Docker parity, exact task-root deletion and
  persistent zero residue remain `NOT_INDEPENDENTLY_OBSERVED`; only the
  runner-local bundle cleanup and terminal job completion are proven.
  Cleanup's secondary root cause remains undetermined.
- Ordinary push CI `30599069949` / job `91057664385` and pull-request CI
  `30599071395` / job `91057668298` both passed. Each ran `1244` tests with
  `28` intentional skips and zero failures; quality, production-readiness and
  Docker Compose checks were green.
- Secret-free terminal evidence is
  `deploy/production/evidence/admin-dependency-cache-v4-attempt1-failed-20260731.json`
  at SHA-256 `237891f4…6fb1`. Its strict semantic/file/Git-closure verifier is
  `tools/verify_admin_dependency_cache_v4_failure_evidence.py` at SHA-256
  `79805c3e…6b21`; it rejects duplicate/non-finite JSON, any nested or outcome
  mutation, a fabricated runtime payload, upgraded cleanup claims, the old
  runner version, downstream activity or false readiness credit. Focused
  receipt/readiness tests pass `44/44`; production readiness passes
  `117/117`; the full repository regression passes `1251/1251` with `28`
  intentional skips. JSON, Python compile and diff checks pass.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Internal
readiness remains `19/29`, public readiness remains `19/38`, and the latest
credited item remains `api_f_current_release=VERIFIED`. The next acceptance
boundary is an append-only inert V5 that freezes V4, disables Buildx GitHub
provenance injection for both builders before spending the build budget,
disables BuildKit client-token authority, requires the Docker config to remain
the exact empty-auth state, strictly handles Buildx's source-proven phase
transition for `.buildNodeID`, and makes every cleanup outcome observable
without exposing state contents. It must pass
local and ordinary remote CI with exact V5 run zero before the main CTO uses
the standing bounded delegation for one successor activation; no further
product-owner prompt is required inside those reviewed limits.

### Inert Admin dependency-cache V5 local acceptance (2026-07-31)

- The V4 terminal-receipt checkpoint is
  `3501b242b17e30ddf004a73882ecf588c428800b`. Ordinary push CI
  `30600946535` / job `91063262924` and pull-request CI `30600949389` /
  job `91063271596` both completed successfully. The branch and upstream
  were clean `0/0` before V5 work; a fresh Actions inventory still showed
  exactly one V4 run, `30599069993` / attempt `1` / failure. V4 must never
  be rerun.
- Append-only V5 is locally prepared but remains inert. The active request
  `.github/release-requests/admin-5335bda-dependency-cache-v5.json` is
  absent, all-ref addition history is zero and plan state is
  `PREPARED_V5_NOT_TRIGGERED`. No V5 run, artifact, authenticated download,
  transfer, cloud builder, Admin ACR action or production mutation is
  claimed. Remote checkpoint CI and workflow-path run-zero acceptance are
  still pending.
- The local V5 workflow/template/plan-verifier/transient-verifier/cleanup/
  source-fixture SHA-256 values are respectively
  `a784ed67…3546a`, `766a87ae…dfad`, `78d58b5b…86ef`,
  `4b81fb25…cb5f`, `a291c724…f239` and `33de770d…999d`.
- The V5 workflow gives both isolated builders the exact ordered driver
  options `image=<pinned digest>` and `provenance-add-gha=false`; it retains
  max provenance and the exact V3 two-key bundle verifier. After both pinned
  BuildKit containers bootstrap and before the first dependency build, a
  silent two-builder gate rejects any direct regular, hidden or linked
  provenance JSON drop-in without printing filenames or contents.
- A job-wide source-proven client-auth control prevents the BuildKit client
  token seed path. The exact empty Docker config remains at the frozen
  helper-compatible `0700/0600` modes; any seed, lock or other entry fails
  closed. This deliberately avoids forking the large frozen export/import
  helpers merely to make the config read-only. The new wrapper hash-locks the
  frozen V4 verifier and adds required `pre-build`, `post-build` and
  `cleanup-active` phases. `.buildNodeID` is forbidden before build, required
  after a successful build and, if present, must be a single-link regular
  `0600` file containing exactly 16 lowercase hexadecimal bytes. No value or
  hash is reported.
- A pre-activation cleanup audit found three High and three Medium evidence
  gaps without consuming a remote run. This atomic hardening changed only the
  V5 workflow/template/plan verifier/cleanup helper and their V5 tests, plus
  this Handoff, the risk register and the existing readiness description.
  The first workflow step now anchors absolute `5700`-second pre-cleanup and
  `6300`-second cleanup deadlines before either checkout; export/import are
  bounded to `3600/900` seconds and cleanup external calls to `15` seconds.
  No later step can reset those deadlines.
- All four Docker baselines are written to `0600` temporary files and become
  trusted only after the final completion marker is atomically moved after
  the last snapshot. An absent, partial, linked, hard-linked, malformed or
  mode-drifted baseline forbids image-difference deletion. Cleanup continues
  all new-image removal attempts after an individual failure; builder
  inventory distinguishes `already_absent` from
  `rm_nonzero_absent_after`; exact owner-nonwritable roots are reopened only
  for bounded deletion. It also removes its diagnostic files and publishes a
  schema-checked `0600` receipt atomically. A final compact-read failure can
  never print PASS.
- Cleanup records deadline validity, baseline validity, builder remove plus
  independent absence readback, new-image removal, four Docker-object parity
  results, diagnostic-file and both exact-root removals, pre/post client-state
  classification, cleanup effectiveness and overall status. Drift or a
  nonzero builder remove remains a run failure even when physical cleanup is
  independently effective.
- Revised V5 plan/transient/cleanup/bundle behavior passes `45/45`; the
  combined plan/production-gate/internal-readiness modules pass `53/53`.
  The complete repository regression passes `1297/1297` with `28`
  intentional skips in `400.091` seconds.
  Production readiness passes `118/118`, internal/public readiness remains
  `19/29` / `19/38`, and ten workflow run scripts, shell syntax, Python
  compile, strict JSON/YAML and `git diff --check` pass. The prior
  `1289/1289` result is superseded by this post-audit full run.
- Two final read-only split audits close the runtime implementation and
  future semantic-regression coverage at `Critical 0 / High 0 / Medium 0 /
  Low 0`. Behavior tests prove a blocked Docker call still yields root
  deletion and a receipt, an incomplete baseline issues no image removal,
  first-image failure still attempts all remaining IDs, owner-nonwritable
  roots are removed, and receipt-directory/final-`jq` failures never claim
  success.
- The source fixture is explicitly classified
  `SOURCE_PROVEN_CONFIGURATION_CONTRACT_NOT_V5_RUNTIME_EVIDENCE`; it binds
  Buildx `v0.35.0` and BuildKit `v0.31.2` tag/commit/blob coordinates without
  retaining or simulating an event payload. The one disposable V5 run is
  still required to prove real post-build metadata, client state and Docker
  parity.
- Internal readiness remains `19/29`, public readiness remains `19/38`, and
  the latest credited item remains `api_f_current_release=VERIFIED`. No plan,
  authority, failed attempt or cleanup implementation earns readiness credit.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next
acceptance boundary is to commit and push this inert V5 closure, pass ordinary
push/PR CI, and prove exact remote V5 workflow run zero. The main CTO may then
create exactly one request-only activation under the standing bounded
delegation without asking the product owner again.

### Inert V5 checkpoint tracked-file hygiene correction (2026-07-31)

- The inert V5 closure was committed as
  `b503caf5d2774a9a73a215f3229edda1229e5be5` and pushed with the active
  request still absent. Its ordinary push CI `30604681282` / job
  `91074418049` and pull-request CI `30604682784` / job `91074422409`
  both reached Unit tests and failed the same single repository-hygiene
  assertion after `1297` tests with `28` intentional skips. This was not a
  V5 cache workflow run: exact V5 workflow-path inventory remained zero, so
  no cache-run, artifact, download/transfer, builder, ACR or production
  authority was consumed.
- The exact failure was
  `tracked_files_no_obvious_secret_values`: once the previously untracked V5
  files became tracked, the heuristic scanner interpreted the public control
  sentinel `BUILDKIT_NO_CLIENT_TOKEN` and one test-only mutation expression as
  secret values. Local pre-checkpoint full regression could not expose that
  tracked-file-only transition.
- The minimal correction does not change the V5 workflow, template, plan
  verifier, transient verifier, cleanup helper or source fixture, so all six
  audited V5 hashes remain unchanged. The scanner allowlists only the exact
  lowercase public sentinel value `buildkit_no_client_token`; it does not
  allowlist the variable name or arbitrary token-like values. The two
  mutation tests now construct their keys at runtime. Regression assertions
  prove a realistic fake value and `unexpected` client-token value are still
  rejected.
- The corrected scanner regression passes `1/1`, direct tracked-file hygiene
  passes, the combined V5 plan/production-gate/internal-readiness modules pass
  `53/53`, and production readiness passes `118/118`. The complete repository
  regression passes `1297/1297` with `28` intentional skips in `395.234`
  seconds. Final syntax, strict-data, diff and V5 run-zero checks remain
  required before the corrective checkpoint is pushed.

Readiness remains internal `19/29`, public `19/38`, and the latest credited
item remains `api_f_current_release=VERIFIED`. The sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is a
single corrective inert checkpoint, ordinary push/PR CI green and exact V5
workflow run zero; only then may the main CTO create the one request-only V5
activation under the standing bounded delegation.

### Corrective inert V5 remote acceptance (2026-07-31)

- The tracked-file hygiene correction is checkpoint
  `706235945cad4844050d9d11a0082d3bb45ad6a6`. Branch HEAD and upstream are
  identical with ahead/behind `0/0` and a clean worktree before this receipt.
- Exact-HEAD push CI `30605675715` / job `91077293078` and pull-request CI
  `30605677994` / job `91077299035` both completed `success`. Checkout,
  dependencies, Python and shell syntax, model artifacts, all Unit tests,
  quality gate, production readiness gate and Docker Compose validation all
  passed.
- The V5 active request remains absent locally and on the remote branch.
  Local/all-ref and GitHub path history are both zero. A fresh fully paginated
  Actions inventory filtered by the exact V5 workflow path is also zero, so
  neither ordinary CI run consumed the one V5 cache-run authorization.
- V5 artifact, authenticated download, cross-cloud transfer, conditional
  4C16G AMD64 builder, Admin ACR and production mutations remain zero. The
  six audited V5 core hashes remain the local-acceptance hashes recorded
  above.
- This remote acceptance closes the inert V5 installation boundary but earns
  no readiness credit. Internal/public readiness remains `19/29` / `19/38`
  and the latest credited item remains `api_f_current_release=VERIFIED`.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. This
Secret-free receipt must be checkpointed without the active request, pass its
ordinary remote CI with exact V5 run zero, and then the main CTO will create
the unique single-parent/request-only V5 activation under the standing
bounded delegation. No further product-owner prompt is required.

### V5 unique attempt terminal closure and append-only V6 boundary (2026-07-31)

- Branch `codex/quality-stabilization-real-chain` is at the V5 request-only
  controller `58871b0be3427ed643f44bc198c9fe3c87a01600`; before this local
  receipt work, HEAD and upstream were identical at ahead/behind `0/0`.
  The controller has the single direct parent
  `ec4b806ea7ffe24de6f8005d077bb6d81a0ec1c9` and added only
  `.github/release-requests/admin-5335bda-dependency-cache-v5.json`.
- Exact workflow run `30606218502`, job `91078891364`, run number `1`,
  attempt `1` is the sole V5 run and completed `failure`. Rerun count is zero
  and V5 is permanently consumed/no-rerun. Controller, request/source
  binding, both pinned BuildKit builders, provenance/client-token controls
  and the dependency build passed. The frozen bundle verifier then failed
  with its first network-vertex unique-match assertion before portability,
  portable archive generation, upload or provider confirmation.
- Pinned Buildx `v0.35.0` source proves `--progress rawjson` serializes one
  `client.SolveStatus` per line with top-level
  `vertexes/statuses/logs/warnings`. The frozen verifier only reads a
  top-level `vertex` or `id`, so its aggregated map and first marker match
  count are deterministically zero. This is source-proven parser behavior,
  not retained V5 runtime metadata. Because raw progress was removed and
  artifact count is zero, the actual nested vertex count, names and IDs
  remain `UNKNOWN`; no runtime name-drift, duplicate or actual-zero claim is
  permitted. The source projection is retained locally as
  `tests/fixtures/admin_dependency_cache_buildx_v0.35.0_rawjson_schema_projection.json`
  with SHA-256 `44429de5…245ce` and is explicitly labeled source evidence,
  never V5 runtime evidence.
- The same source proves `VertexLog.data` is JSON Base64. The frozen replay
  scanner searches the encoded raw JSON without decoding, so it cannot
  reliably reject package-network output. V5 never reached replay. Any
  successor must strictly parse original nested SolveStatus records, strictly
  Base64-decode and scan original logs including cross-chunk matches, bind
  the three dependency roles structurally, and fail closed on malformed,
  ambiguous, incomplete or non-cached evidence.
- V5 cleanup completed successfully with schema-v2 receipt:
  both builders are removed and absent; image/container/volume/network
  snapshots match the trusted atomic baselines; Docker and Buildx task roots
  and diagnostic files are absent; `cleanup_effective=true` and
  `overall_pass=true`. Public base or dependency reads may have occurred and
  are not misreported as zero network activity.
- GitHub artifact API returned `total_count=0`. Artifact upload/provider
  confirmation, authenticated download, cross-cloud transfer, conditional
  4C16G AMD64 builder, Admin ACR repository/token/login/push/readback,
  production service/database and public-traffic mutations remain zero in
  the authorized chain. Unrelated external cloud activity was not
  independently observed and is not claimed globally absent.
- A fully paginated read-only GitHub inventory at
  `2026-07-31T05:50:02Z` still showed exactly one V5 workflow run. The
  control HEAD had exactly three Actions runs: V5 plus the ordinary push and
  pull-request CI, with no additional downstream workflow in that observed
  scope.
- Activation push CI `30606218457` and PR CI `30606220764` each ran `1297`
  tests with one identical failure: the old test required the active V5
  request to remain absent. The corrected test now accepts both the exact
  inert state and the exact single request-only retained activation; existing
  Git parent, byte, mode, uniqueness and all-ref history checks remain
  fail-closed.
- Secret-free terminal evidence is
  `deploy/production/evidence/admin-dependency-cache-v5-attempt1-failed-20260731.json`;
  its verifier and seven mutation/Git tests pass. The combined V5 plan and
  receipt suite passes `22/22`; internal-readiness tests pass `16/16`;
  production-readiness tests pass `22/22`; production readiness passes
  `119/119`. The verifier also reconstructs the exact 20-field compact
  cleanup JSON and its `66150b14…b5194` SHA instead of trusting the claimed
  hash alone. The final full repository regression passes `1304/1304` with
  `28` intentional skips in `421.792` seconds; two independent final delta
  audits report `C0/H0/M0/L0`. Internal/public readiness remains `19/29` /
  `19/38`, and the latest credited item remains
  `api_f_current_release=VERIFIED`.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The current
atomic work is to checkpoint this V5 terminal receipt and pass ordinary
remote CI, then implement and independently audit append-only inert V6. Its
next acceptance condition is green focused/full local verification, green
ordinary push/PR CI and exact V6 workflow/request history/run zero. The main
CTO may then directly approve exactly one bounded V6 successor under the
standing delegation; V2-V5 must never be rerun.

### Append-only V6 inert local engineering closure (2026-07-31)

- Read-only takeover reconfirmed branch
  `codex/quality-stabilization-real-chain` at
  `17cac5eea2f8cb5aadef86ab78eee3e735c9ee1e`, with upstream ahead/behind
  `0/0` before the V6 local work. That V5 terminal checkpoint was already
  pushed, and exact-HEAD push CI `30608407375` plus pull-request CI
  `30608409341` both completed `success`, closing the prior section's remote
  acceptance boundary without adding readiness credit. The worktree contains
  only the expected inert V6 workflow/template/verifiers/tests/source
  projection plus the production/internal-readiness and Secret-free ledger
  updates. The active V6 request is absent; no V6 run or external mutation is
  claimed at this local stage.
- V6 outer workflow/template SHA-256 are
  `65afd81d42dbe16d3b4054aecc10e2c5861c9454cc8ec061c7227056292bb26b`
  and
  `fe34f3b07102478aa6e99e98b0deb399aeb95c0955ebd2ad8ce9ecc1afefd196`.
  The outer trigger, concurrency, artifact and request identities are V6,
  while the reviewed V5 transient verifier, cleanup helper, builder names,
  Docker/Buildx roots, baseline marker, four object snapshots and cleanup
  receipt remain byte-for-byte in the frozen V5 runtime namespace.
- The new core verifier SHA-256 is
  `86d93114e804bf6a51fdb160651d6a20c555f107b88020e0f8d811d0f0d358e5`;
  its BuildKit v0.31.2 structural source projection SHA-256 is
  `4b7a087c813b82085dd8ccb1255b8e873e834510ee652d12ff9443b72a29dac5`.
  It strictly parses original nested SolveStatus records, uses only
  `vertexes[].digest` as vertex identity, binds each unique dependency role
  through `digestMapping -> llbDefinition -> sole Exec`, verifies exact
  linux/amd64 platform, strict RFC3339 lifecycle/completion/cache state,
  strictly decodes Base64 logs/warnings and scans decoded cross-chunk
  network evidence. Original metadata/progress are same-FD stable-byte
  captured and hash-rechecked unchanged.
- The frozen V3 and V2 verifiers are loaded from same-FD captured,
  hash-verified bytes. V6 creates a private deterministic three-record legacy
  shim only after original evidence validation, checks the exact frozen V3
  result, removes the shim fail-closed, scopes delegate patching under a
  lock, and converts unexpected exceptions to a fixed bounded Secret-free
  diagnostic without traceback or task path disclosure.
- V6 plan verifier SHA-256 is
  `c9b89f85eab789cc967ce70d864a9a71d07526aaf63ef4bb00511ec4776b33d1`.
  It freezes V5 control/run/evidence and the V2/V3/V6 verifier trust chain,
  requires the exact singleton branch and request-path trigger, preserves the
  frozen V5 transient/cleanup namespace, and retains one 120-minute run,
  one-day retention, 3.5/3.75/4-GiB bounds, one authenticated download and
  one receipt-bound transfer, with registry/deploy/database/service/
  public-traffic actions disabled.
- Local acceptance is complete: the V2/V3/V5/V6 bundle chain passes `40/40`;
  V6 plan mutation tests pass `19/19`; production-readiness and
  internal-readiness tests pass `39/39`; the full repository regression
  passes `1338/1338` with `28` intentional skips in `656.938` seconds.
  Production readiness passes `120/120`; internal/public readiness remains
  `19/29` / `19/38`. Full Python and shell syntax, all three JSON documents,
  V6 YAML and its ten Bash blocks, staged tracked-file Secret hygiene,
  model-artifact verification, quality gate, Docker Compose and cached-diff
  checks pass. The latest credited item remains
  `api_f_current_release=VERIFIED`; an inert plan earns no credit.
  Independent security review reports no P0/P1 after the strict RFC3339
  correction; its singleton trigger P2 is also closed by an exact semantic
  assertion and two negative mutations.
- GitHub artifact/provider confirmation, authenticated download,
  cross-cloud transfer, a new 4C16G AMD64 builder, Admin ACR publication,
  production service/database and public-traffic mutations remain zero in
  the authorized chain. V2-V5 are permanently consumed and must not be
  rerun.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next
acceptance boundary is an inert V6 checkpoint with green ordinary push/PR CI
and exact V6 workflow/request history/run zero. The main CTO will then create
exactly one request-only V6 activation under the standing bounded
authorization without another product-owner prompt, monitor it without blind
duplicate/rerun, and only after cache acceptance proceed to the authorized
authenticated transfer, new 4C16G AMD64 builder, single Admin ACR private
publication and full cleanup.

### V6 inert checkpoint remote acceptance (2026-07-31)

- Inert V6 checkpoint
  `ff6e2d6e3849541f1d204769ea2052f850e783cd` contains the reviewed thirteen
  files and no active request. It was pushed from a clean worktree; branch and
  upstream returned to ahead/behind `0/0`.
- Exact-HEAD ordinary push CI `30612580553` / job `91098507401` completed
  `success` at `2026-07-31T07:26:07Z`. Checkout, Git LFS, Python/Node setup,
  dependency installation, Python/shell syntax, model artifacts, all unit
  tests, quality gate, production readiness and Docker Compose validation
  passed.
- Exact-HEAD ordinary pull-request CI `30612583077` / job `91098515480`
  completed `success` at `2026-07-31T07:26:21Z` with the same complete step
  matrix. The only annotation is GitHub's Node 20 action-runtime deprecation
  notice; it is not a check failure and does not weaken V6 acceptance.
- A fully paginated repository Actions read at
  `2026-07-31T07:27:08Z`, filtered by the exact
  `.github/workflows/admin-dependency-cache-export-v6.yml` path, returned
  run count `0`. The exact HEAD has only the two successful ordinary CI runs.
  The V6 active request is absent on the remote branch and local worktree,
  its all-ref addition history remains `0`, and the plan state remains
  `PREPARED_V6_NOT_TRIGGERED`.
- This closes only the inert V6 installation boundary. V6 Admin authorization
  remains unconsumed; artifact/provider confirmation, authenticated download,
  cross-cloud transfer, new 4C16G AMD64 builder, Admin ACR publication and
  production mutations remain zero. Internal/public readiness remains
  `19/29` / `19/38`, with latest credited item
  `api_f_current_release=VERIFIED`.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. This
Secret-free remote receipt must be checkpointed without the active request,
pass its ordinary remote CI with exact V6 run zero, and then the main CTO will
create the unique single-parent/request-only V6 activation under the standing
bounded delegation. V2-V5 remain permanently no-rerun, and V6 must not be
blindly duplicated or rerun.

### V6 unique attempt terminal closure and append-only V7 boundary (2026-07-31)

- The one-shot activation is permanently consumed. Control commit
  `5770f00d7e5756302d34b5f9159066dc3fd5d36d` has the single direct parent
  `4455af46c775eb68cff3a7356324bae99263013b` and adds only the regular
  `100644` request
  `.github/release-requests/admin-5335bda-dependency-cache-v6.json`.
  Its request SHA-256 is
  `e44ea8fa685d7a605d6cf37ec0e389189a804b5790e07ea3edb0bc5b5f176341`
  and its bytes equal the frozen V6 template after the sole parent
  placeholder is replaced.
- GitHub workflow `324291491` has exactly one fully paginated run:
  `30613707689` / job `91101989637` / run number `1` / attempt `1`,
  event `push`, terminal `failure`. It started at
  `2026-07-31T07:41:43Z`; the job ran from `07:41:46Z` through
  `07:43:14Z`. Rerun count is zero and V6 may never be rerun.
- Controller checkout, exact request/source resolution, both isolated
  fixed BuildKit builders and the dependency build/local-cache command
  passed. The export step then stopped in the hash-pinned V6 verifier with
  `RAWJSON_VERTEX_CONFLICT` / `FAIL: BuildKit vertex updates conflict`
  before portability, portable archive generation, final validation,
  upload or provider confirmation.
- The retained Secret-free diagnostic binds the original progress to
  `171396` bytes and SHA-256
  `e514e5752560f140ed5ddd305f70254df737400e7a58d00d83d8a61cfde9582a`.
  It observed three nonblank SolveStatus events and accepted two vertex
  updates before a repeated update for the same digest conflicted on the
  third candidate. Nonblank/event/status/log/warning/decoded-record counts
  are processed-prefix counters; role results, unique-digest count, decoded
  byte totals and package-network result are defaults whose final evaluation
  was not reached. Original metadata and progress were intentionally removed;
  the exact repeated digest and whether `name`, `started` or `completed`
  crossed the limit remain `UNKNOWN_NOT_RETAINED`. No name drift, duplicate
  role-marker/provenance classification, zero-network, structural-role or
  cache-result claim is inferred.
- Fixed BuildKit `v0.31.2` commit
  `e42e1bfd389af7203238cce77b1f7dad447285e9` and Buildx `v0.35.0` commit
  `a319e5b15052cf6557ceb666eb8ff6e32380b782` source establish that the same
  digest legitimately receives incremental updates and multiple lifecycle
  intervals. V6 instead rejects incremental same-digest updates through a
  single-value cardinality invariant over name/start/completion. This general
  implementation-level root cause is determined without selecting or
  reconstructing the missing dynamic field.
- Cleanup completed successfully. Both GitHub-hosted ephemeral Buildx builders were
  removed and proved absent; image/container/volume/network baselines match;
  the fixed Docker and Buildx roots plus enumerated cleanup-helper diagnostic
  files are absent; and `cleanup_effective/overall_pass=true`. This does not
  claim a global `RUNNER_TEMP` inventory or hosted-VM physical destruction.
  The exact no-newline cleanup receipt derives SHA-256
  `66150b14b5a1dc05b73125403610c1ab94ec7a4dba9cddd28735b9af612b5194`.
- Artifact API is exactly `total_count=0`. Upload/provider confirmation,
  authenticated download, cross-cloud transfer, the conditional new 4C16G
  AMD64 builder, Admin ACR repository/token/login/push/readback and all
  production service/database/public-traffic mutations remain zero. The two
  GitHub-hosted ephemeral Buildx builders are recorded separately. External
  network reads are known nonzero from checkout and the fixed BuildKit image;
  the exact count and public base/dependency subset remain unknown.
- Exact-control-HEAD ordinary push CI `30613707809` / job `91101990101`
  and pull-request CI `30613710360` / job `91101997460` both completed
  `success`; each ran `1338/1338` tests with `28` intentional skips and the
  prior production gate `120/120`. A fully paginated exact-HEAD inventory at
  `2026-07-31T07:52:37Z` contains exactly those two ordinary runs and the
  unique V6 run.
- Added and verified the Secret-free terminal evidence
  `deploy/production/evidence/admin-dependency-cache-v6-attempt1-failed-20260731.json`,
  its strict verifier
  `tools/verify_admin_dependency_cache_v6_failure_evidence.py`, and eight
  fail-closed tests. Evidence file/semantic/verifier SHA-256 are respectively
  `d3902b323dd4e214b06c5674098d5c113a3b6571e21c4eb3c7ccfcd42ec16a11`,
  `15d2f88390985773261ca4b8cd6b921e4b2a28bf2da8191748b3d26a11861f5a`
  and
  `a8a37c466a73d25a0d481504890e227a1b9dfb0f3cca964f4e17a846ff27679e`.
  The full repository passed `1346/1346` with `28` intentional skips in
  `597.919` seconds before the final fact-wording hardening; all affected
  evidence/internal/production tests then passed `47/47`. The evidence is
  integrated into repository production readiness, which passes `121/121`;
  the deployment score remains truthfully `19/29` internal / `19/38` public.
  The latest credited item remains
  `api_f_current_release=VERIFIED`.
- Files changed in this atomic terminal stage are the V6 evidence, verifier
  and tests; production readiness gate and tests; internal readiness
  manifest and exact-evidence-list test; this handoff; and the risk ledger.
  No workflow, V6 request, frozen V6 verifier, export/import helper, cloud
  resource or production runtime was modified.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next
acceptance boundary is an append-only inert V7 that keeps every V6 byte and
terminal fact frozen, models lifecycle intervals under digest identity
fail-closed, preserves provenance/decoded-log/cache/cleanup controls, and
passes local plus ordinary remote CI with V7 workflow/request history/run
zero. Under the standing bounded delegation, the main CTO will then authorize
and create exactly one V7 request-only activation without another
product-owner prompt. V2-V6 are permanently no-rerun.

### V6 terminal checkpoint remote acceptance (2026-07-31)

- Secret-free terminal checkpoint
  `65b79e14baf4ec9a2ea65442226de7c12f64f611` is pushed; the worktree is
  clean and branch/upstream ahead/behind is `0/0`.
- Exact-HEAD ordinary push CI `30616546023` / job `91110951533` completed
  `success`; it ran `1346/1346` tests in `180.610` seconds with `28`
  intentional skips and production readiness `121/121`.
- Exact-HEAD ordinary pull-request CI `30616549483` / job `91110962291`
  completed `success`; it ran `1346/1346` tests in `187.601` seconds with
  `28` intentional skips and production readiness `121/121`.
- A fully paginated read at `2026-07-31T08:35:07Z` found exactly those two
  ordinary Actions runs for the checkpoint HEAD. The V6 workflow inventory
  remains exactly one consumed run `30613707689`, run number/attempt `1/1`,
  terminal `failure`, rerun count zero.
- This remote receipt adds no deployment credit. Artifact upload/download,
  cross-cloud transfer, the conditional Alibaba 4C16G AMD64 builder, Admin
  ACR and production mutations remain zero; internal/public readiness remains
  `19/29` / `19/38`.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Proceed directly
to append-only inert V7 implementation and independent review; do not modify
or rerun V2-V6.

### Append-only V7 inert local engineering closure (2026-07-31)

- The append-only V7 recovery is locally
  `PREPARED_V7_NOT_TRIGGERED`. The active request
  `.github/release-requests/admin-5335bda-dependency-cache-v7.json` is absent
  and its local all-ref addition history is zero. No GitHub Admin run,
  artifact, authenticated download, cross-cloud transfer, conditional new
  4C16G AMD64 builder, Admin ACR publication or production mutation occurred.
- The V7 workflow/template/core verifier/plan verifier/source-projection
  SHA-256 values are respectively
  `3b4ec5ed8841253afe62ff54b7de7dfdd523d48d9dd3ce5837394fb4c5e9c427`,
  `e690b968c935ffa721535a0282b3d108fe6ce651431622f262894225cd0a29e7`,
  `76af4aa0c8dbe68b46cc71fb74f1582030c5f28a7218a2ee04bcbde5f4198cd7`,
  `bed5ee29dd367caa4faafb7c711fd4d97d740319622aa459fcc5000a866ebc6b`
  and
  `fb5c944a0006cb8e04f32e3ac98e949e27036b10077e4ce10bc0a6c8b4fb5de1`.
- V7 preserves the frozen V6 evidence and verifier bytes, then executes the
  V2/V3/V6/V7 verifier chain in each export/import/final stage. It accepts
  legitimate same-digest incremental updates only by full-copying structural
  provenance and recording every exact UTC epoch-nanosecond lifecycle
  interval; every bound interval must close in-window, while terminal-to-open,
  terminal-to-announcement, conflicting completion/cache, truncated
  nanoseconds, malformed/orphan provenance, invalid Base64 and forbidden
  network evidence remain fail-closed. The latest-started interval controls
  the final cached result.
- The V5 transient and cleanup namespace remains byte-stable. The provider
  artifact name intentionally remains the frozen legacy
  `admin-dependency-prefix-cache-5335bda-v2`, because both the authenticated
  download helper and provider verifier bind that exact name; V7 identity is
  additionally bound by request, run, control commit and archive digest.
- Independent read-only core and control-plane audits found no P0 or P1
  blocker. The final read-only control-plane delta audit found
  `P0=0 / P1=0 / P2=0`; it independently passed V7 plan `20/20`,
  provider/download `9/9`, V6 failure evidence `8/8`, V5
  transient/cleanup `27/27`, all workflow Bash blocks, JSON/YAML and Python
  compile. V7 core tests pass `15/15`, internal-readiness tests pass `16/16`,
  production-readiness tests pass `24/24`, and production readiness passes
  `122/122`.
- The full repository passes `1382/1382` with `28` intentional skips in
  `1057.716` seconds. These are local inert engineering results and add no
  deployment credit.
- Files changed in this atomic stage are the V7 workflow and inert request
  template; V7 core and plan verifiers plus their tests; the fixed BuildKit
  incremental-update source projection; the production readiness gate and
  tests; the internal readiness manifest and exact-evidence-list test; this
  handoff; and the risk ledger.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`. The sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next push the inert V7 checkpoint and
require green ordinary remote CI plus a fully paginated exact V7 workflow run
count of zero. Only after that boundary may the main CTO create the unique
single-parent, request-only V7 activation. V2-V6 remain permanently no-rerun.

### V7 inert checkpoint remote acceptance (2026-07-31)

- Secret-free inert checkpoint
  `27dcccf1736c40a832a3ca4875aa9ff7bdbe72d5` is pushed. Before the push the
  active V7 request was absent and its local all-ref addition history was zero;
  branch/upstream returned to `0/0` after the push.
- Exact-HEAD ordinary push CI `30621850312` / job `91128010222` completed
  `success`; it ran `1382/1382` tests in `213.893` seconds with `28`
  intentional skips and passed production readiness `122/122`, quality and
  Docker Compose validation.
- Exact-HEAD ordinary pull-request CI `30621853278` / job `91128020032`
  completed `success`; it ran `1382/1382` tests in `247.202` seconds with
  `28` intentional skips and passed production readiness `122/122`, quality
  and Docker Compose validation.
- A fully paginated repository Actions-ledger read at
  `2026-07-31T10:04:00Z` found exactly those two ordinary runs for the exact
  checkpoint HEAD and zero run whose workflow path is
  `.github/workflows/admin-dependency-cache-export-v7.yml`. The remote V7
  request-path commit history is also zero.
- No Admin cache authorization was consumed. Artifact upload/download,
  cross-cloud transfer, the conditional new 4C16G AMD64 builder, Admin ACR and
  production mutations remain zero. Internal/public readiness remains
  `19/29` / `19/38`.

The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit and push
this Secret-free remote receipt, require its own ordinary CI to pass while the
fully paginated V7 run count remains zero, then create the unique
single-parent, request-only V7 activation directly under the standing bounded
authorization. V2-V6 remain permanently no-rerun.

### V7 unique attempt terminal closure and append-only V8 boundary (2026-07-31)

- The unique V7 request-only control commit is
  `4494f50bf9a18422cef6252792bb9c6bbeaf1135`, with direct parent
  `71692d5f25f6a2d3f248cc62a568f4a2bd5af2cd`. Its only file addition is
  `.github/release-requests/admin-5335bda-dependency-cache-v7.json`, mode
  `100644`, SHA-256
  `161dc1cfbc8683cbc18816baffd01edfa50c5d4fca8edb2e85054fb79eeb37dd`.
- Workflow `324378036` ran exactly once as run `30622876575`, job
  `91131267190`, run number/attempt `1/1`, event `push`, and completed
  `failure`. Controller/request/release checkout/source checks, both fixed
  BuildKit builder checks and the producer dependency build passed. The V7
  verifier then failed with `PROVENANCE_LOCATION_INVALID` and
  `BuildKit source location changed for step9`. `step9` is a BuildKit LLB
  provenance identifier, not a GitHub workflow step number.
- Strict producer rawjson parsing completed before structural binding failed:
  progress is `171061` bytes with SHA-256
  `ce0d2cc10f6a3e4922d9d6515e37c761d88989b0a1dc55b5fd5284a6688ec9db`;
  the complete parsed counts are `525` nonblank records, `83` vertex updates,
  `18` unique digests, `95` statuses, `404` log/decoded-log records,
  `34495` decoded-log bytes, zero warnings/decoded-warning bytes, `36`
  lifecycle intervals, `18` repeated digests and maximum `9` intervals per
  digest.
- The exact rejected child predicate and actual `step9` source-location
  payload are `UNKNOWN_NOT_RETAINED`. Role classification and package-network
  scanning were not reached, so the initialized unresolved/zero/false fields
  are not runtime results. No zero-network, role-cache or completed-window
  claim is made; `primary_root_cause_determined=false` and
  `root_cause_class=null` remain frozen in terminal evidence.
- Import, final verification, upload and provider confirmation were skipped.
  The artifact API count is exactly zero. Authenticated download, cross-cloud
  transfer, the conditional new 4C16G AMD64 builder, Admin ACR publication
  and all production mutations remain zero.
- Cleanup completed successfully. Compact cleanup receipt SHA-256 is
  `66150b14b5a1dc05b73125403610c1ab94ec7a4dba9cddd28735b9af612b5194`;
  it proves both ephemeral Buildx builders removed and absent, Docker
  image/container/volume/network baseline parity, fixed Docker/Buildx roots
  and enumerated diagnostic files absent, and
  `cleanup_effective/overall_pass=true`. It does not prove hosted-VM physical
  destruction or a global temporary-directory inventory.
- Exact-control-HEAD ordinary push run `30622876687` / job `91131268889`
  and pull-request run `30622878997` / job `91131274377` both completed
  `success`, ran `1382/1382` tests with `28` intentional skips, and passed
  production readiness `122/122`. A fully paginated read at
  `2026-07-31T10:20:34Z` found exactly the single V7 run above; rerun count is
  zero. V7 is permanently consumed and must not be rerun.
- Added Secret-free terminal evidence
  `deploy/production/evidence/admin-dependency-cache-v7-attempt1-failed-20260731.json`,
  strict verifier
  `tools/verify_admin_dependency_cache_v7_failure_evidence.py`, and eight
  fail-closed tests. Their file SHA-256 values are respectively
  `91950799263f19b8422534b685cd1e46856e9d03137976ccec08ce1d644e3ed4`,
  `c1ae9caa594c48ff1a6d46f78d4aef84cb3a33e410ea9c2ae6bb2c17bf6ae476`
  and
  `5a27c7cc2ecba378f42d38272a3b1091c8bb516ca994abb6cec877c6924f4a95`;
  the evidence semantic SHA-256 is
  `6ea653978234820dad155784d22887dfd61352e28f97571e3a18423b3893ad9a`.
  The combined evidence, production-readiness and internal-readiness tests
  pass `48/48` in `365.782` seconds; the repository production gate passes
  `123/123`. The full repository passes `1390/1390` with `28` intentional
  skips in `1052.050` seconds. The final independent read-only terminal delta
  audit found `P0=0 / P1=0 / P2=0`, no required correction, independently
  reran V7 evidence plus internal-readiness `24/24`, and passed production
  readiness `123/123`.
- Independent fixed BuildKit v0.31.2 source review proves a deterministic
  implementation explanation for V8: a vertex without source ranges can
  legitimately serialize as an exact empty location wrapper `{}`, while
  frozen V7 requires a nonempty `locations` list. This is
  source-proven contract evidence, not reconstruction of removed V7 runtime
  metadata. The minimum append-only V8 change must accept only exact `{}` as a
  nonbinding empty range and freeze all populated-location, role, interval,
  cache, network, archive, trust-chain and cleanup semantics.

Files changed in this terminal stage are the V7 evidence, verifier and tests;
the production readiness gate and tests; the internal readiness manifest and
exact-evidence-list test; this handoff; and the risk ledger. No V7 workflow,
request, frozen verifier, cloud builder, registry, database, service or
production runtime is modified.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`. The sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next commit and push this Secret-free
V7 terminal checkpoint, require its own ordinary CI to pass and fully
paginate the V7 ledger as exactly one attempt with no rerun, then proceed
directly to append-only inert V8. V2-V7 are permanently no-rerun.

### V7 terminal checkpoint remote acceptance (2026-07-31)

- Secret-free V7 terminal checkpoint
  `6102ac231b68e3bc6b69db817fd834da0e37e1b9` is pushed; branch/upstream is
  `0/0` and the worktree was clean immediately after the push.
- Exact-HEAD ordinary push CI `30625742881` / job `91140465238` completed
  `success`; it ran `1390/1390` tests in `255.880` seconds with `28`
  intentional skips, passed production readiness `123/123`, quality,
  required model-artifact validation and Docker Compose validation.
- Exact-HEAD ordinary pull-request CI `30625746116` / job `91140475239`
  completed `success`; it ran `1390/1390` tests in `265.219` seconds with
  `28` intentional skips and passed the same production readiness
  `123/123`, quality, model-artifact and Compose checks.
- A fully paginated repository Actions-ledger read at
  `2026-07-31T11:11:02Z` found exactly those two ordinary runs for the
  checkpoint HEAD. A fully paginated workflow-id `324378036` read still found
  exactly V7 run `30622876575`, run number/attempt `1/1`, terminal
  `failure`, rerun count zero. Its artifact API remains exactly zero.
- The V7 request path still has exactly one addition commit, control
  `4494f50bf9a18422cef6252792bb9c6bbeaf1135`, with direct parent
  `71692d5f25f6a2d3f248cc62a568f4a2bd5af2cd`. No request edit/re-add,
  workflow rerun, authenticated download, cross-cloud transfer, conditional
  new 4C16G AMD64 builder, Admin ACR publication or production mutation
  occurred.

This remote receipt adds no deployment credit. Internal/public readiness
remains `19/29` / `19/38`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit and push this Secret-free
receipt, require its ordinary CI to remain green while the fully paginated V7
ledger remains run1/rerun0, then proceed directly to append-only inert V8.
V2-V7 are permanently no-rerun.

### Append-only V8 inert local engineering closure (2026-07-31)

- The V7 terminal remote-receipt checkpoint is
  `3714cc2feec65d3059325d0d869ad007083b0276`, directly parented by terminal
  evidence checkpoint `6102ac231b68e3bc6b69db817fd834da0e37e1b9`.
  Exact-HEAD ordinary push CI `30626288688` / job `91142231451` and
  pull-request CI `30626291782` / job `91142240612` both completed `success`,
  each passing `1390/1390` tests with `28` intentional skips and production
  readiness `123/123`. Fully paginated reads at
  `2026-07-31T11:19:41Z` retained exactly V7 run `30622876575`,
  run/attempt `1/1`, terminal `failure`, rerun zero and artifact zero.
- Append-only V8 is locally `PREPARED_V8_NOT_TRIGGERED`. The active request
  `.github/release-requests/admin-5335bda-dependency-cache-v8.json` is absent
  and its all-ref addition history is zero. No GitHub Admin run, artifact,
  authenticated download, cross-cloud transfer, conditional 4C16G AMD64
  builder, Admin ACR publication or production mutation occurred in this
  stage.
- V8 accepts only an exact empty BuildKit source-location wrapper `{}` as a
  nonbinding location. An empty wrapper cannot satisfy a dependency role.
  Null, empty arrays, nested empty location groups, unknown keys and explicit
  `sourceIndex` remain rejected. Every populated location, incremental
  interval, structural role, decoded-log/network, cache, archive and cleanup
  rule delegates to the hash-frozen V7 chain.
- The exact V8 workflow/template/source-fixture/core-verifier/plan-verifier
  SHA-256 values are respectively
  `370e17b59ce457efda8b5a6cd23d40937379d23d1a2aeb3f36ac7b88f72333b3`,
  `ba2f705eff90285e377e8d683a059f7f23aef088dc7df2498d167909fff48e7c`,
  `b5f5e806b7e822b536a850eca8861bb7b6f8934832d7bdb4e898e698d7f20eeb`,
  `b07f9dee54862969fe90ef438c357a3445a9fe9574b69a9f87440e3ed9920300`
  and
  `69fde0852832a2b6cdfc4e3542b835a74c3c939377220deb3009430292ef5915`.
  Export, import and final validation each bind copied V2/V3/V6/V7/V8
  verifier files; the V5 transient/cleanup namespace and legacy provider
  artifact name `admin-dependency-prefix-cache-5335bda-v2` remain frozen.
- Local verification passes V8 core `8/8`, V8 plan mutation
  `20/20` in `380.181` seconds, internal readiness `16/16`, production
  readiness tests `25/25` in `521.457` seconds, production gate `124/124`,
  strict JSON/Python compilation, workflow YAML parsing and all `10` Bash
  blocks. The full repository passes `1419/1419` with `28` intentional skips
  in `1662.362` seconds. After two test-expectation P1 items found during the
  initial audit were corrected, the final independent control-plane and
  integration/readiness/documentation audits each found
  `P0=0 / P1=0 / P2=0`, no required correction and no blocker.

Files changed in this atomic stage are the inert V8 workflow and request
template; the exact-empty BuildKit source projection; V8 core and plan
verifiers plus tests; the production readiness gate and tests; the internal
readiness manifest and exact-evidence-list test; this handoff; and the risk
ledger. The active V8 request is deliberately not among the changed files.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`. The sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next commit/push the inert V8
checkpoint, require green ordinary remote CI plus fully paginated V8 run
count zero, checkpoint that receipt and reaccept its own CI/run-zero boundary,
then create exactly one single-parent request-only V8 activation under the
standing bounded authorization. V2-V7 remain permanently no-rerun.

### V8 inert checkpoint remote acceptance (2026-07-31)

- Secret-free inert V8 checkpoint
  `3381c2fdbcb32480bb364a400250f8d24de74c84` is pushed with direct parent
  `3714cc2feec65d3059325d0d869ad007083b0276`; branch/upstream is `0/0`.
  The commit changes exactly the 13 reviewed inert V8/integration files and
  does not contain
  `.github/release-requests/admin-5335bda-dependency-cache-v8.json`.
- Exact-HEAD ordinary push CI `30630764584` / job `91156306054` completed
  `success`; it ran `1419/1419` tests in `356.752` seconds with `28`
  intentional skips, passed production readiness `124/124`, quality,
  required model-artifact validation and Docker Compose validation.
- Exact-HEAD ordinary pull-request CI `30630767695` / job `91156315674`
  completed `success`; it ran `1419/1419` tests in `376.915` seconds with
  `28` intentional skips and passed the same production readiness `124/124`,
  quality, model-artifact and Compose checks.
- Fully paginated repository Actions reads at
  `2026-07-31T12:37:24Z` found exactly those two ordinary runs for the
  checkpoint HEAD and zero runs whose path is
  `.github/workflows/admin-dependency-cache-export-v8.yml`. The remote branch
  has zero commits touching the V8 request path, and the exact remote tree
  contains the V8 workflow but no V8 request.
- The same ledger read retained exactly V7 run `30622876575`, run
  number/attempt `1/1`, terminal `failure`; its artifact API remains exactly
  zero. No V2-V7 rerun, authenticated download, cross-cloud transfer, new
  4C16G AMD64 builder, Admin ACR publication or production mutation occurred.

This remote acceptance adds no deployment credit. Internal/public readiness
remains `19/29` / `19/38`, the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next commit and push this Secret-free
receipt, require its own ordinary CI to remain green while fully paginated V8
workflow history remains run zero, then create exactly one single-parent,
request-only V8 activation under the standing bounded authorization. V2-V7
are permanently no-rerun.

### V8 unique attempt terminal closure and append-only V9 boundary (2026-07-31)

- Read-only takeover found branch
  `codex/quality-stabilization-real-chain` at exact local/upstream HEAD
  `354bec3b2d36bfaabc5c3307d49f5dc66255cbbf`, ahead/behind `0/0`.
  Inert-receipt commit `cf253f9b42b096f45405ac55fe546c281a2a748d`
  had green exact-HEAD push CI `30631461469` and pull-request CI
  `30631464114`; the fully paginated V8 workflow inventory was run zero
  before activation. No related live local process, container, builder,
  listener, Git operation or open temporary-file handle remained.
- Single-parent request-only control
  `354bec3b2d36bfaabc5c3307d49f5dc66255cbbf` added exactly
  `.github/release-requests/admin-5335bda-dependency-cache-v8.json` with
  SHA-256
  `5283d1044e3fb783e4951019f2c137a23530fb6c09fc290718c305ee3e449cd5`.
  It created exactly workflow run `30632611051`, job `91162335850`, run
  number/attempt `1/1`, which is terminal `failure`; V8 is consumed and must
  never be rerun.
- The producer build and strict producer verification passed twice with an
  identical Secret-free diagnostic: `169136` progress bytes, `80` vertex
  updates, `18` unique digests, `85` statuses, `415` logs, `34495` decoded
  bytes, zero warnings, `35` lifecycle intervals, all three dependency roles
  exact and uncached, and package-network output observed. The portable core
  bundle was generated with `13` files and two archive chunks.
- The fresh-consumer core validation and first import build completed. Strict
  import parsing then failed closed at processed vertex update `43` with
  `RAWJSON_VERTEX_INPUT_CONFLICT` / `BuildKit vertex inputs conflict`.
  Import parsing, role/log/cache validation, cacheless replay, portability
  proof, final validation and upload did not complete. The exact conflicting
  digest, prior/current vectors and actual transition were not retained or
  reconstructed; therefore no runtime root-cause shape is claimed.
- Cleanup completed successfully: both ephemeral builders were removed and
  absent, Docker object parity and fixed state-root/diagnostic absence passed,
  and `cleanup_effective=true` / `overall_pass=true`. Artifact API count is
  zero; authenticated download, cross-provider transfer, conditional 4C16G
  builder, Admin ACR publication, database/service/public-traffic mutation
  and production write counts remain zero.
- Exact control-HEAD ordinary push CI `30632610976` and pull-request CI
  `30632616052` both passed `1419/1419` tests with `28` intentional skips and
  production readiness `124/124`. Fully paginated reads observed exactly one
  V8 workflow run, rerun zero and artifact zero.
- Independent fixed-source review found BuildKit rawjson is an incremental
  event stream: nonempty structural inputs appear as an ordered vector, while
  a zero-input structural event or a same-digest cache/lifecycle controller
  event can serialize with `inputs` absent; this fixed rawjson path performs
  no field-level merge. The append-only V9 boundary is therefore narrow:
  missing `inputs` is nonbinding; an explicit nonempty ordered vector binds
  once and must remain byte-for-byte/order identical; explicit empty, null,
  non-list, oversized, invalid or drifting vectors fail closed. Omission-only
  remains UNKNOWN and cannot prove a leaf. Location, role, lifecycle,
  network, cache, archive, trust-chain and cleanup semantics remain frozen.
- Secret-free V8 terminal evidence, its hash/semantic/Git-chain verifier and
  mutation tests are integrated into both readiness gates. Targeted Python
  compilation, the V8 evidence suite, internal readiness suite and production
  readiness suite passed `52/52` in `572.702` seconds; the production gate is
  `125/125`. The final full repository suite passed `1430/1430` with `28`
  intentional skips in `1881.891` seconds. This evidence adds no deployment
  credit.

Files changed in this atomic stage are the V8 terminal evidence, verifier and
tests; the production readiness gate and tests; the internal readiness
manifest and exact-evidence-list test; this handoff; and the risk ledger. No
V2-V8 workflow, frozen verifier, cache request, cloud builder, registry,
database, service or production runtime is modified.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`. The sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next commit/push this Secret-free V8
terminal checkpoint, require its own ordinary remote CI to pass and fully
paginate V8 as exactly run1/rerun0/artifact0, then checkpoint that receipt
before implementing inert append-only V9. V2-V8 are permanently no-rerun.

### V8 terminal checkpoint remote acceptance (2026-07-31)

- Secret-free terminal checkpoint
  `6961876b35aba5e52fc7e44a59a4881469d0064f` is pushed with single direct
  parent `354bec3b2d36bfaabc5c3307d49f5dc66255cbbf`; its exact nine-file delta
  contains the terminal evidence/integration closure and does not modify any
  V2-V8 workflow, frozen verifier or release request. Branch/upstream is
  `0/0` and the worktree is clean.
- Exact-HEAD push CI `30639974456` / job `91187110993` completed `success`;
  it passed `1430/1430` tests with `28` intentional skips in `401.883`
  seconds, production readiness `125/125`, quality, required model artifacts
  and Docker Compose validation.
- Exact-HEAD pull-request CI `30639976664` / job `91187118526` completed
  `success`; it passed `1430/1430` tests with `28` intentional skips in
  `329.737` seconds and the same production readiness `125/125`, quality,
  model-artifact and Compose checks.
- Fully paginated reads at `2026-07-31T14:54:38Z` found exactly those two
  ordinary runs for terminal-checkpoint HEAD. Workflow id `324467538` still
  has exactly V8 run `30632611051`, run number/attempt `1/1`, terminal
  `failure`, rerun zero. Its artifact API is exactly zero. Relevant local
  process count is zero.
- No authenticated download, cross-provider transfer, conditional 4C16G
  builder, Admin ACR publication, database/service/public-traffic mutation or
  production write occurred. This remote acceptance adds no deployment
  credit.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next commit/push this Secret-free
terminal receipt, require its own ordinary CI to pass while a fully paginated
ledger remains V8 run1/rerun0/artifact0, then proceed directly to inert V9.
V2-V8 are permanently no-rerun.

### V8 terminal receipt acceptance and inert V9 local closure (2026-07-31)

- Read-only takeover reconciled branch
  `codex/quality-stabilization-real-chain` at exact local/upstream HEAD
  `72f36354471e2d56ea77760d50417bf09b5cd9e1`, ahead/behind `0/0`, with a
  clean starting worktree. The receipt has single direct parent
  `6961876b35aba5e52fc7e44a59a4881469d0064f`.
- Exact receipt-HEAD push CI `30640810703` / job `91189970727` completed
  `success`, passing `1430/1430` tests with `28` intentional skips in
  `381.082` seconds and production readiness `125/125`. Pull-request CI
  `30640814504` / job `91189983479` also completed `success`, passing the
  same `1430/1430`, `28` skips and readiness `125/125` in `397.407`
  seconds. A fully paginated read at `2026-07-31T15:05:30Z` retained exactly
  one V8 run `30632611051`, run number/attempt `1/1`, terminal `failure`,
  rerun zero and artifact zero.
- Append-only V9 is installed only as inert local engineering. The active
  path `.github/release-requests/admin-5335bda-dependency-cache-v9.json`
  remains absent and its all-ref addition history is zero, so state is
  `PREPARED_V9_NOT_TRIGGERED`; no V9 workflow run, artifact, authenticated
  download, transfer, conditional builder, Registry publication, database,
  service or public-traffic mutation has occurred.
- The V9 compatibility contract is intentionally narrower than the unknown
  V8 runtime transition. A missing `inputs` member is nonbinding before and
  after a binding; the first explicit nonempty ordered digest vector binds;
  later explicit vectors must be exactly value- and order-identical.
  Explicit empty, null, non-array, oversized, invalid, drifting or reordered
  vectors fail closed. Omission-only remains unbound/UNKNOWN and does not
  prove a leaf or zero inputs. Location, lifecycle, role, decoded-log,
  network, cache, archive, trust-chain and cleanup semantics remain delegated
  to the frozen V8 chain.
- The V9 workflow remains exact-branch/exact-request-path push-only with no
  dispatch, pull-request, schedule or repository-dispatch trigger. It copies
  and binds the V2/V3/V6/V7/V8/V9 six-layer verifier chain for producer,
  fresh-consumer import and final verification, requires a nonzero mixed
  present/omitted input diagnostic on import, retains the frozen V5 cleanup
  and transient-state contract, uses the legacy provider artifact protocol,
  and preserves the one-run, attempt-one, deadline, size, retention, cleanup,
  cost and no-production-mutation bounds.
- Final local SHA-256 closure currently is: workflow
  `ece8eb8e9c9d8a8997faa838c87a3a06a407bc3382670bf8f294433982e62f34`;
  request template
  `ae5114d66eb2aedd4db875b857974b0631caa1a39ad75a16e22ccbaecc424a3b`;
  fixed-source projection
  `3738f1b5bea4490c063cee7749fe39134b0f63005201496ac74aa1d125efb9fd`;
  core verifier
  `a69103e899dc74b4d34e4837e29f40284be9b252281fed262a2dd1afee3d6032`;
  plan verifier
  `d3d4b32d3a2f98b4311d1576e7c69446b9e95cbd1e92a85b7562fe9a4d7bb0d0`.
- Initial independent read-only audits found no P0/P1 and three P2
  fail-closed gaps. The main CTO serially closed them by guarding the complete
  V8/V7/V6/V3/V2 module-global keysets, identities and links before patching
  and after full restoration; freezing activation-time request bytes/mode
  plus the actual-parent and activation
  blobs/hashes/modes of workflow/template/source/core, and allowing the
  repository Gate to pass only `PREPARED_V9_NOT_TRIGGERED` or
  `V9_ARMED_OR_TRIGGERED_EXACT`. The reproduced forged-summary,
  activation-repair, executable-mode-repair, INVALID and consumed-state
  attacks are now negative tests. Core tests pass `12/12`, plan/history tests
  pass `15/15`, internal-readiness tests pass `16/16`, and the full production
  readiness suite passes `27/27` in `819.745` seconds. JSON, workflow YAML and
  diff checks pass, the repository production gate is `126/126`, and the
  final full repository suite passes `1459/1459` with `28` intentional skips
  in `2135.126` seconds. Both final independent read-only correction audits
  report `P0=0 / P1=0 / P2=0 / P3=0`.
- A third independent read-only release-boundary audit reports the same all-zero
  severity tally and explicitly accepts checkpointing after verifying the
  exact 13-file inert delta, request/history zero, six-layer wiring,
  trigger/deadline/artifact/cleanup/cost/no-production-mutation bounds and
  unchanged `19/29` credit. Its focused verification passed `43/43`.

Files changed in this local atomic stage are the V9 fixed-source projection,
core verifier and tests, inert request template, request-only workflow, plan
verifier and tests; the production readiness gate and tests; the internal
readiness manifest and exact-evidence-list test; this handoff; and the risk
ledger. The V9 active request is deliberately not among them.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit/push the Secret-free inert V9
checkpoint, require its own ordinary push/PR CI and fully paginated V9 run
zero while V8 remains run1/rerun0/artifact0, then checkpoint and remotely
accept that receipt under the same zero-run boundary before creating exactly
one single-parent, request-only V9 activation. V2-V8 are permanently
no-rerun.

### V9 inert checkpoint remote acceptance (2026-07-31)

- Secret-free inert checkpoint
  `590ffc863d7475b5637e644461c7ac7e8612052b` is pushed with single direct
  parent `72f36354471e2d56ea77760d50417bf09b5cd9e1`. Its exact 13-file delta
  installs the V9 workflow/template/source/verifiers/tests and readiness
  integration but does not add the V9 active request. Local and upstream HEAD
  are equal and the worktree is clean.
- Exact-HEAD push CI `30649974618` / job `91220550087` completed `success`;
  it passed `1459/1459` tests with `28` intentional skips in `467.799`
  seconds and production readiness `126/126`, plus syntax, model, quality and
  Docker Compose gates. Exact-HEAD pull-request CI `30649977007` / job
  `91220557919` also completed `success`; it passed the same `1459/1459`,
  `28` skips and readiness `126/126` in `336.367` seconds with every ordinary
  step successful.
- Fully paginated reads at `2026-07-31T17:18:19Z` found exactly those two
  ordinary CI runs for checkpoint HEAD. The V9 workflow path has run count
  zero. V8 workflow id `324467538` remains exactly run `30632611051`, run
  number/attempt `1/1`, terminal `failure`, rerun zero; its artifact API count
  remains exactly zero. Branch/upstream is `0/0`.
- No V9 artifact, authenticated download, cross-provider transfer,
  conditional builder, Admin ACR publication, database/service/public-traffic
  mutation or production write occurred. This remote acceptance adds no
  deployment credit.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit/push this Secret-free inert
receipt, require its own ordinary push/PR CI and fully paginated V9 run zero
while V8 remains run1/rerun0/artifact0, then create exactly one
single-parent, request-only V9 activation. V2-V8 are permanently no-rerun.

### V9 unique attempt terminal closure and append-only V10 boundary (2026-07-31)

- Inert receipt `c2aebc9bdae9cc26c6c29d994bf55b547349e231` was
  remotely accepted before exact request-only activation. Control commit
  `fbe629daad669191d4ea9903ffb488c98055f000` has that receipt as its single
  direct parent and adds only
  `.github/release-requests/admin-5335bda-dependency-cache-v9.json`, mode
  `100644`, SHA-256
  `57c1506bb6e483e2e9f74e510847e278dbe336869cdc113ecc0230aebabd07d6`.
- The fully paginated V9 workflow ledger contains exactly workflow
  `324655362` run `30651679657`, job `91226182660`, run number/attempt
  `1/1`, terminal `failure`; attempt two is absent and rerun count is zero.
  V9 is consumed and must never be rerun.
- Producer build, strict verification and portable core generation passed
  with `13` files and two archive chunks. The producer diagnostic occurred
  twice identically: `168894` progress bytes, `81` vertex updates, `18`
  digests, `35` intervals, `414` logs, `34495` decoded bytes, zero warnings,
  all three exact roles uncached as expected, and package-network output
  observed.
- Fresh-consumer core validation and the import build completed. The full V9
  parser exercised one digest with mixed omitted/explicit inputs and thereby
  crossed V8's input-conflict boundary. Its complete import diagnostic binds
  `62137` progress bytes, `90` updates, `18` digests, `43` intervals and all
  three exact/completed roles; `meituan_npm_pack` and `runtime_apt` were
  cached, while `runtime_pip` had cached count zero. The frozen cache predicate
  failed with `NETWORK_VERTEX_NOT_CACHED` and
  `FAIL: BuildKit runtime_pip vertex was not cached`.
- Cacheless replay, portability proof, final bundle validation, upload and
  provider identity confirmation were not reached. Raw metadata/progress,
  the role-bound digest and ordered interval details were removed, so the
  dynamic cause remains `UNKNOWN_NOT_RETAINED`; zero decoded import logs and
  zero package-network output do not authorize treating the miss as a hit.
- Cleanup passed: both GitHub-hosted ephemeral builders were removed and
  absent; image/container/volume/network baseline parity and fixed
  Docker/Buildx/diagnostic-root absence passed; `cleanup_effective` and
  `overall_pass` are true. Artifact API count, authenticated download,
  cross-provider transfer, conditional builder, Admin ACR, database, service,
  production write and public-traffic mutation counts are zero.
- Activation-HEAD push CI `30651677386` / job `91226175143` and pull-request
  CI `30651679124` / job `91226180370` each ran `1459` tests with one failure
  and `28` skips in `462.291` and `447.442` seconds. The sole failure was the
  V9 plan test still requiring an absent request after valid activation;
  quality/readiness/Compose steps were skipped. The history is retained as
  red. The test now accepts and verifies both exact PREPARED and exact ARMED
  lifecycle states; its local suite passes `15/15`.
- Secret-free V9 terminal evidence, strict semantic/hash/Git-chain verifier
  and mutation tests are integrated with the readiness gates. The evidence
  suite passes `9/9`; combined evidence/plan/internal readiness tests pass
  `40/40`, the production readiness suite passes `27/27` in `939.095`
  seconds, and the repository production gate passes `127/127`. The final
  full repository suite passes `1468/1468` with `28` skips in `2232.945`
  seconds on the exact pre-checkpoint source snapshot.
- Fixed-source review does not claim a V9 historical root cause. In pinned
  BuildKit commit `e42e1bfd389af7203238cce77b1f7dad447285e9`,
  `solver/jobs.go::sharedOp.LoadCache` emits cached=true, while
  `solver/progress.go::vertexStream.append` can also infer an unfinished input
  as cached when a child starts. The bounded append-only V10 direction
  therefore keeps the producer graph and all cache requirements frozen and
  adds a consumer-only, zero-network, deliberately uncached observer child.
  That child must execute and make `runtime_pip` non-terminal; V10 will still
  fail if pip is noncached, and will retain canonical role/interval evidence
  instead of relaxing the predicate.

Files in this terminal atomic stage are the V9 evidence, verifier and tests;
the production readiness gate and tests; the internal readiness manifest and
exact evidence-list test; the state-aware V9 plan test; this handoff; and the
risk ledger. No V9 request/workflow/core/helper, cloud builder, Registry,
database, service or production runtime is modified.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next commit and push the exact
ten-file Secret-free terminal checkpoint, require its own
ordinary push/PR CI to pass while fully paginated V9 history remains
run1/attempt1/failure/rerun0/artifact0, then commit the four-file terminal
receipt before append-only V10. V2-V9 are permanently no-rerun.

### V9 terminal checkpoint remote acceptance (2026-07-31)

- Secret-free terminal checkpoint
  `0e35e7dca22064402f8a7b569c6b966e4c6ec1a3` is pushed with single direct
  parent `fbe629daad669191d4ea9903ffb488c98055f000`. Its exact ten-file delta
  freezes the V9 failure evidence/verifier/tests, readiness integration and
  state-aware activation test; it does not modify any V9 request, workflow,
  template, core verifier or helper. Local and upstream HEAD are equal and
  the worktree was clean before this receipt stage.
- Exact-HEAD push CI `30657325032` / job `91244859680` completed `success`;
  it passed `1468/1468` tests with `28` intentional skips in `480.065`
  seconds and production readiness `127/127`, plus syntax, model, quality and
  Docker Compose gates. Exact-HEAD pull-request CI `30657329972` / job
  `91244875610` also completed `success`; it passed the same `1468/1468`,
  `28` skips and readiness `127/127` in `456.938` seconds with every ordinary
  step successful.
- Fully paginated reads after `2026-07-31T19:08:15Z` found exactly those two
  ordinary CI runs for checkpoint HEAD. V9 workflow `324655362` still has
  exactly run `30651679657`, run number/attempt `1/1`, terminal `failure`;
  attempt two is absent, rerun count is zero and the artifact API count is
  exactly zero. Branch/upstream is `0/0`.
- No V9 rerun, artifact, authenticated download, cross-provider transfer,
  conditional builder, Admin ACR publication, database/service/public-traffic
  mutation or production write occurred. This remote acceptance adds no
  deployment credit.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit/push this exact four-file
Secret-free terminal receipt, require its own ordinary push/PR CI while V9
remains run1/attempt1/failure/rerun0/artifact0, then proceed directly to
append-only inert V10. V2-V9 are permanently no-rerun.

### V9 terminal receipt remote acceptance and inert V10 local closure (2026-08-01)

- Secret-free V9 terminal receipt
  `512638647c5851aa3258cd472da42894110465af` is pushed with single direct
  parent `0e35e7dca22064402f8a7b569c6b966e4c6ec1a3` and exact four-file scope.
  Its push CI `30658134722` / job `91247556880` completed `success` with
  `1468/1468` tests, `28` intentional skips, `486.917` seconds and production
  gate `127/127`. Pull-request CI `30658136947` / job `91247564136` also
  completed `success` with `1468/1468`, `28` skips, `450.453` seconds and
  production gate `127/127`.
- Fully paginated readback retained exactly one V9 workflow run:
  `30651679657` / job `91226182660`, run number/attempt `1/1`, terminal
  `failure`. Attempt two is absent, rerun count and artifact count remain
  zero. No authenticated download, transfer, conditional cloud builder,
  Admin ACR, database, service, production write or public-traffic mutation
  occurred.
- Append-only V10 is locally `PREPARED_V10_NOT_TRIGGERED`: the active request
  is absent and all-ref addition history is zero. The producer Dockerfile
  prefix, producer build projection and original full replay are frozen;
  only the fresh consumer derives target `noteai-cache-observer`, whose
  `RUN --network=none` must execute uncached with the exact marker and direct
  `runtime_pip` parent. Producer role intervals must all remain uncached,
  imported-replay role intervals must all remain cached, and the cacheless
  post-pip witness must execute uncached. No predicate, no-cache filter,
  GitHub provenance injection, credential behavior or production authority
  was relaxed.
- Frozen V10 SHA-256 values are workflow
  `fd9570833c35aa3fc0d8632d26d68cca9ef33e960c26c4f4410eaaa6f7572d96`,
  template
  `2ac7f6ed83be057ffc79ca349888e8691d9324f3474942fe65571055e59c8bcc`,
  import helper
  `d8388ff776290b05aa699f3a09363fc2087c3b8bd5ada23b556d6cb14953b85f`,
  source projection
  `f743084bb704d0fd6858510d81ebe6479ac0c6baae982b353715c328bc6fcd27`,
  bundle verifier
  `77c2410406448998c81d09b04d93d12db1cb3a4a032a0b78d9fc25626014758f`
  and plan verifier
  `6e89496a983151a953560083c7c327d7c98847f77ed09cb027755f8f1d65c136`.
- After the fail-closed, frozen-origin, mode-matrix, nested-dispatch and final
  control-history repairs, the V10 plan reports
  `PREPARED_V10_NOT_TRIGGERED` and the V10/V9 focused plan/bundle regression
  passes `70/70`. The remote controller now uses the same merge-aware,
  deduplicated all-ref request-addition rule as the local verifier, freezes
  its five runtime files at one common regular-file addition anchor through
  activation, and rejects any post-receipt touch to the same explicit
  recursive 70-path V2-V9 authority union as the local verifier. Before any
  resource creation, a fixed lifecycle-wide concurrency group and a bounded,
  paginated Actions-read ledger require the entire V10 workflow history to
  contain exactly the current run ID, SHA, branch, push event and attempt one;
  zero visibility is polled only within 60 seconds and duplicate runs fail
  immediately. The local verifier also rejects symlink/mode substitution,
  broken links, FIFO reads and non-single-parent frozen anchors. Three
  independent read-only audits of the core, workflow/plan and control plane
  all report P0/P1/P2/P3 zero. They independently replayed the producer,
  observer and full projections, exercised the Actions ledger state machine,
  and rechecked the exact frozen hashes and 14-file scope without modifying
  project files.
- Final frozen-snapshot validation passed: V10/V9 focused plan/bundle
  `70/70` in `26.648` seconds; internal readiness `16/16`; production
  readiness `29/29` in `1342.428` seconds; repository production gate
  `128/128`; and the full repository suite `1513/1513` with `28` intentional
  skips in `2730.589` seconds. The independent control-plane integration run
  also passed `45/45` in `1349.927` seconds. These test counts do not create
  deployment credit.

Files in this inert atomic stage are exactly eight new V10 workflow/template/
source/helper/verifiers/tests plus the production gate and tests, internal
readiness manifest and exact-evidence-list test, this Secret-free handoff and
risk ledger. The V10 active request is deliberately absent. Internal/public
readiness remains `19/29` / `19/38`; the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Local regression and independent
read-only audits are complete; commit/push the exact 14-file inert V10
checkpoint. Require its own ordinary push/PR CI and fully paginated V10 run
zero with the V9 ledger unchanged, then commit and remotely accept a
Secret-free inert receipt before creating exactly one single-parent,
request-only V10 activation. V2-V9 are permanently no-rerun.

### V10 inert checkpoint remote acceptance (2026-08-01)

- Secret-free inert checkpoint
  `9199fb598790a03302c21dd3968c63b58d03f2c2` is pushed with single direct
  parent `512638647c5851aa3258cd472da42894110465af` and exact 14-file scope.
  Its delta contains the eight new V10 workflow/template/source/helper/
  verifier/test files plus production-gate integration, the readiness
  manifest and exact-evidence-list test, this handoff and the risk ledger.
  The active V10 request is absent.
- Exact-HEAD push CI `30670568835` / job `91287217391` completed `success`
  with `1513/1513` tests, `28` intentional skips, `547.582` seconds and
  production gate `128/128`. Pull-request CI `30670570806` / job
  `91287223709` also completed `success` with `1513/1513`, `28` skips,
  `574.873` seconds and production gate `128/128`; every ordinary job step
  succeeded in both runs.
- Fully paginated repository Actions reads after
  `2026-07-31T22:49:06Z` found exactly those two ordinary CI runs for the
  checkpoint SHA and zero records whose workflow path is
  `.github/workflows/admin-dependency-cache-export-v10.yml`. V9 workflow
  `324655362` still has exactly run `30651679657`, run number/attempt `1/1`,
  terminal `failure`; attempt two is absent and its artifact API result is
  empty. Branch/upstream is `0/0`.
- No V10 workflow run, cache artifact, authenticated download, transfer,
  conditional builder, Admin ACR, database, service, production write or
  public-traffic mutation occurred. This remote acceptance adds no
  deployment credit.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit/push this exact four-file
Secret-free inert receipt and require its own ordinary push/PR CI, fully
paginated V10 run zero and unchanged V9 ledger. Then create exactly one
single-parent, request-only V10 activation. V2-V9 are permanently no-rerun.

### V10 unique attempt terminal closure and append-only V11 boundary (2026-08-01)

- Read-only takeover reconfirmed branch
  `codex/quality-stabilization-real-chain`, activation HEAD
  `ea2a3b489e74b21a88ea21ecd243cd6a433c7fac`, upstream equality and the
  single-parent control chain `9199fb598790a03302c21dd3968c63b58d03f2c2`
  → `b02c4a18d6b77024f17d0e56c1d081a578854b1f` → `ea2a3b489…c7fac`.
  The controller adds only the regular `100644` V10 request with SHA-256
  `4b3c8950bea4a0e9cdc578a69f193fb63cccb5be447bba777951718249d96db0`.
- Fully paginated V10 workflow `324820330` history has exactly run
  `30672160324` / job `91291967175`, run number/attempt `1/1`, terminal
  `failure`; attempt two is absent, rerun count is zero and the artifact API
  is empty. Producer build and both strict diagnostics passed, and export
  produced `13` files in `2` archive chunks. The fresh-consumer observer
  build and V10 parse completed, then the unchanged all-interval predicate
  rejected `runtime_pip` with `NETWORK_VERTEX_NOT_CACHED` before the V9
  delegate, cacheless replay, portability proof, final validation or upload.
- Producer V10 diagnostic SHA is
  `c226196068788b3c84f5235e9e40b24f55c2294a1b1cc546858922426ec8f3c8`;
  import failure diagnostic SHA is
  `2b4e6b26d2fa5897624cbdadd420e67a3b0765a82a57322b986edbadd86548ac`.
  The latter proves the rejecting V10 verifier boundary, not the underlying
  cache mechanism. V10 added an observer only to the consumer graph; the
  producer still exported with pip terminal, so the producer-terminal-result
  hypothesis was not tested and remains plausible. Import pip digest and
  intervals, observer details, decoded dependency logs and cache record/result
  mapping were not retained; root cause remains `UNKNOWN_NOT_RETAINED`.
- Cleanup canonical SHA is
  `66150b14b5a1dc05b73125403610c1ab94ec7a4dba9cddd28735b9af612b5194`
  for `558` bytes and every enumerated field passes. Both ephemeral builders,
  Docker object deltas, fixed roots, diagnostics and the runner-local bundle
  were removed. Authenticated download, cross-provider transfer, conditional
  builder, Admin ACR, database, service, production-write and public-traffic
  counts remain zero.
- Activation push CI `30672160310` / job `91291967030` passed `1513/1513`
  tests with `28` skips in `582.253` seconds and production gate `128/128`.
  Pull-request CI `30672161852` / job `91291971809` retained an accurate red
  result: its three failures all arose because synthetic merge
  `6dbf0daddd308a8501aea1ea53a23981ab4550ef` was misclassified as a second
  request addition. The terminal fix now defines a true origin as a commit
  whose result contains the path while every parent lacks it, and checks
  post-anchor changes only against parents in the anchor-descended lineage.
  Regression coverage accepts the unchanged GitHub synthetic merge and still
  rejects merge-only real additions, merged side-branch changes and
  change-then-revert histories.
- Secret-free evidence
  `deploy/production/evidence/admin-dependency-cache-v10-attempt1-failed-20260731.json`,
  its strict semantic/file/Git-chain verifier and mutation tests are integrated
  with the production and internal readiness gates. The evidence file SHA is
  `9b8a1e3a28c5ca2e1a6d4c495e2404f7ea027abf42bfa27ccd4649909f043103`
  and semantic SHA is
  `352debb0294df5c442bf1b0ea0594576e49f649c830c2e1f568d4f0a4e9e4336`;
  all three diagnostic hashes and the cleanup hash recompute exactly. Focused
  V10 plan/evidence regression passes `38/38` after the lineage optimization.
- The first full-repository pre-checkpoint run completed `1525` tests with
  `28` intentional skips and exactly one failure in
  `test_monthly_refund_is_bound_to_original_subscription_period`. The test's
  hard-coded supposed next period was `2026-08-01T00:00:00+00:00`, which
  became equal to the real UTC monthly charge period on 2026-08-01; the
  production refund code correctly matched that period and reduced usage to
  zero. The fixture now derives a different next-month period from the period
  captured by the claim. The focused case passes `1/1` and the complete
  idempotency module passes `25/25`; a fresh full-repository run must pass
  before this checkpoint is committed.

Files in this terminal atomic stage are the V10 terminal evidence, verifier
and tests; the lineage-aware V10 plan verifier and tests; the production gate
and tests; the internal readiness manifest and exact evidence-list test; this
handoff; the risk ledger; and the deterministic subscription-period test
fixture: exactly twelve paths. No production billing code or V10 runtime
workflow, template, import helper, source projection or bundle verifier is
modified.

Internal/public readiness remains `19/29` / `19/38`; the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next validate the exact twelve-file
snapshot, commit and push it as the V10 terminal checkpoint, require its own
ordinary push/PR CI to pass while fully paginated V10 remains
run1/attempt1/failure/rerun0/artifact0 and V9 is unchanged, then commit the
exact four-file terminal receipt. Continue directly to append-only V11 with a
producer export-anchor and distinct consumer observer; V2-V10 are permanently
no-rerun.

### V10 terminal checkpoint synthetic-merge test isolation correction (2026-08-01)

- Terminal checkpoint `8c8567b99541f1f260d988754daa88f97f00f68e`
  has direct parent `ea2a3b489e74b21a88ea21ecd243cd6a433c7fac`
  and the exact twelve-path delta described above. Its push CI
  `30678246254` / job `91309786181` passed `1525/1525` tests with `28`
  intentional skips in `591.848` seconds and production gate `129/129`.
- Pull-request CI `30678248247` / job `91309792275` checked out synthetic
  merge `d3bbb785aeb3bf11eac5ed1303a582240c415fa3`, whose parents are main
  `5afc1717f09618de7ed7a191133a087d83317e39` and checkpoint `8c8567b…f68e`
  and whose tree equals the checkpoint tree. Its sole error after `1525`
  tests and `28` skips was a test-only `KeyError`: the parent-drift mutation
  test mocked `_commit_parents` with a finite map but did not isolate
  `_true_additions`, so the real synthetic merge candidate reached that map.
  The verifier itself had already accepted the synthetic merge, and no cache,
  evidence, billing or production predicate failed.
- The corrective test now mocks `_true_additions` to the already-covered
  valid control origin while mutating only the controller parent under test.
  Independent tests continue to cover synthetic merges, merge-only real
  additions, descendant side-branch changes and tamper/revert histories.
  The V10 failure-evidence suite passes `9/9`; no verifier or production code
  is changed.

The corrective atomic delta is exactly four paths: the one test plus this
handoff, the readiness manifest and the risk ledger. Commit it without amend
or rerun, require its own ordinary push/PR CI to pass, then fully paginate the
V9/V10 ledgers and create the exact four-file terminal receipt. Readiness
remains `19/29` internal / `19/38` public and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`; V2-V10 are permanently no-rerun.

### V10 corrective checkpoint remote acceptance and terminal receipt boundary (2026-08-01)

- Corrective checkpoint `b01c65d507cf087bea0d80038eafdb08a8e23bf1`
  has direct parent `8c8567b99541f1f260d988754daa88f97f00f68e`
  and exactly four changed paths: the failure-evidence test, this handoff,
  readiness and the risk ledger. It does not modify any verifier, workflow,
  request, runtime helper, evidence bytes or production source.
- Exact-HEAD push CI `30678960987` / job `91311902300` and pull-request CI
  `30678962485` / job `91311907477` both completed successfully. Each passed
  `1525/1525` tests with `28` intentional skips and production gate `129/129`;
  unit-test times were `641.156` and `594.765` seconds. A fully paginated
  repository Actions read found exactly those two ordinary runs for the
  corrective HEAD.
- Fully paginated V10 workflow `324820330` history remains exactly run
  `30672160324`, run/attempt `1/1`, terminal failure at activation
  `ea2a3b489…c7fac`; its artifact API remains empty. V9 workflow `324655362`
  likewise remains exactly run `30651679657`, run/attempt `1/1`, terminal
  failure at `fbe629da…f000`, with an empty artifact API. Neither attempt was
  rerun. Branch and upstream are equal at `b01c65d…23bf1` with `0/0` drift.
- No cache artifact, authenticated download, transfer, conditional builder,
  Admin ACR, database, service, production-write or public-traffic action was
  introduced by either terminal checkpoint.

This Secret-free terminal receipt changes exactly this handoff, readiness,
the risk ledger and the internal readiness exact-evidence test. It adds the
two terminal checkpoint SHAs to the manifest evidence list without deployment
credit. Commit and push the receipt, require its own ordinary push/PR CI and
unchanged fully paginated V9/V10 ledgers, then continue directly to append-only
V11 with a distinct producer export-anchor and consumer observer. Readiness
remains `19/29` internal / `19/38` public, the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`, and V2-V10 are permanently no-rerun.

### V10 terminal receipt takeover and inert V11 local closure (2026-08-01)

- Read-only takeover reconciled branch
  `codex/quality-stabilization-real-chain`, local HEAD and upstream at the
  V10 terminal receipt `458f2482f9a3267bb9050a274f33ae21fc546ed7`, and
  ahead/behind `0/0`. The worktree initially contained only nine untracked
  V11 control/runtime/test files; no active V11 request, runtime output,
  provider artifact, credential or production mutation was present.
- Append-only V11 is locally `PREPARED_V11_NOT_TRIGGERED`. Both producer and
  consumer construct the same exact `5191`-byte / `86`-line Dockerfile at
  SHA-256 `c665ac4356bec6751d44878a416bbaa278a77df77754f5461ba0adb13f43c2a0`.
  `noteai-cache-export-anchor` and `noteai-cache-import-observer` are distinct
  sibling `--network=none` children of `runtime_pip`; each solve targets only
  its own child. The original release Dockerfile and V10 full replay remain
  byte-frozen.
- The V11 verifier preserves all three role interval vectors, bounded decoded
  log projections, child identity and producer/consumer pair diagnostics
  before enforcing cache predicates. It follows the extracted BuildKit OCI
  `index → root manifest → cacheconfig` chain and requires unique,
  result-bearing anchor and `runtime_pip` records joined by exactly one direct
  identity input link. Pair outcomes are limited to `DIGEST_DRIFT`,
  `SAME_DIGEST_NONCACHED` and `SAME_DIGEST_CACHED`; only the last can pass.
  Historical V10 root cause remains `UNKNOWN_NOT_RETAINED`.
- The workflow preserves the V10 concurrency group and performs two fresh,
  fully paginated V2-V11 run/artifact ledgers: once before any builder or
  resource exists and again after cleanup immediately before final validation
  and upload. V2-V10 must retain their exact unique attempt-1 terminal states;
  V11 must contain only its current run/attempt and artifact zero. Git history
  uses all-parent true-origin and anchor-lineage comparisons so unchanged
  GitHub synthetic merges pass while merge-only additions, side-branch touches
  and tamper/revert histories fail closed.
- Frozen V11 authority SHA-256 values are workflow
  `61d72e35823730851e45900219935e12324ff42862fd9920285ade5ececbaca6`,
  template `ca97b59c409e478a5f375a9446a580415004f90451d2219a3a8abf432b43c0ac`,
  export helper `40618ad0db154061b1480dfd7b1e630fd6cc2f1529b54407509b412efb90b141`,
  import helper `e131246229e90ecb81dea1957d3ebe72173562a47803f67213b9eedddb1f31df`,
  source fixture `70e38ea8f77db46dd9a2325ac7fda22428c17dfe6d9318c7244107699ae9eb49`,
  bundle verifier `27c3788bce8065440ccf370cf3a7192c227546d30ed96c612f9acadebca97ca7`
  and plan verifier
  `be6203f63a1c35603c1e7a851cd0a4fe0577807a28bf64c10e87530f953a28fe`.
- Independent review found and the main CTO closed all control/runtime
  gaps before checkpointing: exact-15 and exact-4 Git deltas, partial-authority
  rejection, exact receipt parentage, `100644` modes, optimization-safe ledger
  assertions, two bounded 60-second snapshots, late-snapshot failure handling,
  and durable pre-predicate/pair/final diagnostics. Combined-prefix success now
  also delegates through the frozen V2-V9 provenance/package-network chain;
  unlocated sibling children fail closed, original metadata/progress bytes are
  re-read unchanged, and the retained pre-predicate object is reconstructed
  exactly from the regenerated final diagnostic so extra keys, wrong self-hash
  or role-vector drift cannot pass final validation.
- The control state machine also requires the exact checkpoint, receipt and
  activation to remain the latest canonical stage, accepts only GitHub's
  verified pull-request synthetic-merge projection, freezes all eleven
  non-receipt checkpoint paths after their common addition anchor, and treats
  Git history enumeration errors as hard failures. A side-chain no-ff merge,
  post-stage commit, mode drift or post-anchor touch cannot satisfy the plan.
- V11 bundle and plan mutation suites pass `45/45`; the combined V9/V10/V11
  bundle/plan regression set passes `118/118`; the exact-state test now accepts
  both the inert and unique armed state so activation cannot inherit a stale
  request-absent assertion. Shell syntax, strict JSON/YAML,
  extracted workflow Bash/Python syntax and optimized-mode plan validation
  pass. Internal readiness passes `16/16`, the repository production gate is
  `130/130`, and the plan reports `PREPARED_V11_NOT_TRIGGERED`. The dedicated
  production-readiness unit set passes `31/31` with no skip in `2134.918`
  seconds; full repository validation passes `1572/1572` with 28 skips in
  `3619.271` seconds. Final independent read-only review reports
  `P0=0/P1=0/P2=0/P3=0`. The added V11 gate is engineering evidence only and
  adds no deployment credit.

The locally accepted inert checkpoint changes exactly fifteen paths: the nine new V11
files plus production gate/test, internal readiness manifest/test, this
handoff and the risk ledger. The V11 active request remains absent. Complete
the final post-ledger focused/internal/direct-gate byte check, then commit and
push this exact snapshot. Require its own ordinary push and pull-request CI,
fully paginated V11 run zero and unchanged V2-V10 ledgers; then create an exact
four-file Secret-free inert receipt and require the same remote boundary before
the sole request-only V11 activation.
The current V11 control contract ends at that exact activation commit. After
activation, make no further commit while the run is executing; collect its
result read-only. The first later write must atomically introduce a separately
versioned and reviewed terminal-supersession contract that binds the activation
commit, all seven frozen authority hashes and the exact terminal deltas. It may
not silently relax or edit the V11 activation contract; designing and accepting
that terminal contract is the first task after the run reaches a terminal
state.
Internal/public readiness remains `19/29` / `19/38`, the latest credited item
remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

### V12 layered-state correction remote acceptance and receipt (2026-08-01)

- Correction checkpoint `81730a511acb553c9a1e29af834924f71650dc9a`
  is the direct child of structural terminal receipt
  `37c3b3fdc24ad90ff6135a7f1e254f92062470b3` and changes exactly the seven
  declared integration/ledger paths. V11, the V12 request/workflow/runtime
  and the three terminal authorities remain unchanged.
- Exact-HEAD push CI `30698294887` / job `91364781788` completed success in
  `15m11s`: `1622/1622` tests, `28` skips, unit time `832.703s`, production
  gate `132/132`, quality and Docker success. Pull-request CI `30698296274` /
  job `91364785205` completed success in `15m29s`: `1622/1622`, `28` skips,
  unit time `845.056s`, gate `132/132`, quality and Docker success.
- Fresh five-page Actions pagination observed `474/474` unique runs. V11
  workflow-path run count remains zero. V12 remains exactly workflow
  `325026609`, run `30696298423`, run number/attempt `1/1`, failure, job
  `91359681758`, artifact zero. The correction SHA produced only its two
  ordinary CI runs and no V12 run.
- Normal/optimized V12 failure and plan verifiers report
  `V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT`; the legacy
  `plan_state()` remains `V12_ARMED_OR_TRIGGERED_EXACT`, while
  `effective_plan_state()` carries the terminal release truth.

This exact-four Secret-free snapshot is the layered-state correction receipt
candidate and updates only handoff, risk, readiness and internal-readiness
test. It adds no readiness credit or execution authority. Require its own
ordinary push/PR CI and unchanged V11/V12 ledgers; then use the accepted
receipt as the single direct parent of the inert V13 exact-13 checkpoint.
V13 local design and ordinary CI are allowed, but its exact-one activation
and external run require a new explicit authorization. Readiness remains
`19/29` / `19/38`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

### V12 layered-state ordinary-CI correction candidate (2026-08-01)

- The exact-four direct child `37c3b3fdc24ad90ff6135a7f1e254f92062470b3`
  records efef713's ordinary-CI
  compatibility failure and is the structural V12 terminal receipt. It
  changes only the handoff, risk ledger, readiness manifest and internal
  readiness test; all V12 terminal authorities and runtime files remain
  byte-identical.
- The correction does not edit the frozen V11 test. V12 `plan_state()` now
  deliberately remains the backward-compatible request-activation view and
  returns `V12_ARMED_OR_TRIGGERED_EXACT` for the retained exact request.
  New `effective_plan_state()` returns the authoritative terminal execution
  outcome. The V12 command-line verifier and production readiness gate use
  the effective state; frozen V11 callers continue using the legacy state.
  Invalid evidence or Git state remains `INVALID` in both views.
- The changed implementation surface is limited to the V12 plan verifier,
  its test and the production gate. Together with the four required ledgers,
  this correction candidate is an exact seven-file descendant after the
  receipt. It adds no dependency, permission, trigger, runtime action or
  readiness credit.

Before acceptance, require normal/optimized V12 terminal and plan verifiers,
the V11/V12/failure/readiness focused suites, repository gate `132/132`, then
new exact-HEAD ordinary push and PR CI. Do not rerun efef713, its failed CI or
the V12 workflow. Readiness remains `19/29` / `19/38`; the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

### V11 remote acceptance, deterministic ledger defect and append-only V12 (2026-08-01)

- Read-only takeover reconciled branch
  `codex/quality-stabilization-real-chain`, local HEAD and upstream at
  `606c474d347b4dad4e08e6f9fd038a82bdae5315` with ahead/behind `0/0`.
  That commit is the single direct child of V10 receipt
  `458f2482f9a3267bb9050a274f33ae21fc546ed7`, changes exactly the fifteen
  frozen V11 checkpoint paths, and records every path as a regular `100644`
  blob. The V11 request is absent, its all-ref addition history is zero, and
  no V11 receipt or activation exists.
- Exact-HEAD push CI `30686018935` / job `91331830809` completed `success`
  with `1572/1572` tests, `28` intentional skips, unit time `747.326s` and
  production gate `130/130`. Pull-request CI `30686020149` / job
  `91331834394` also completed `success` with `1572/1572`, `28` skips, unit
  time `774.185s` and gate `130/130`. Job wall times were `827s` and `857s`.
  Five fully paginated repository Actions pages contained `463` records and
  exactly zero records whose path is
  `.github/workflows/admin-dependency-cache-export-v11.yml`.
- Independent read-only reconciliation found a deterministic pre-resource
  V11 defect before any bounded run was consumed. Workflow `323980939` has
  two immutable records, not one: parser-context run `30572921215` at
  `c0d049b56aa6efaff7133ac44a9fef7f010cd097` is push/attempt-1/failure with
  zero jobs and artifacts; terminal run `30591103183` at
  `83b89262a33aed2cfa9fd623f232a66824398c2e` is
  push/attempt-1/failure with unique job `91033410635` and artifact zero.
  Both duplicated V11 ledgers require `len(runs) == 1`, so V11 would fail
  before builder creation. V3 through V10 each retain their one exact
  attempt-1 failure/job/artifact-zero record. V11 is therefore permanently
  untriggered and explicitly superseded; never create its request or run it.
- Append-only V12 reuses and hash-binds the reviewed V11 workflow data plane:
  export/import helpers, source projection and bundle verifier are unchanged.
  The only runtime-control correction is one executable ledger implementation
  that performs two fresh, complete and duplicate-rejecting API snapshots. It
  binds both V2 records and their exact job vectors, each V3-V10 record and
  job, zero artifacts for every legacy run, repository-wide V11 path run zero,
  and the sole current V12 push/attempt-1/artifact-zero run. The second read
  occurs after cleanup and before upload and requires the canonical legacy
  projection to be byte-equivalent to the first.
- The V12 Git contract is
  `606c474…5315 → exact-11 checkpoint → exact-4 receipt → exact-1 request`.
  Its checkpoint contains four new V12 workflow/template/verifier/test files
  and seven controlled modifications: the V11 supersession test, production
  gate/test, readiness manifest/test, this handoff and the risk ledger. Four
  authorities must share one addition anchor; the seven non-receipt paths are
  immutable afterward. Partial sets, wrong parents or modes, side-chain
  merges, post-stage commits, touch/revert history, reruns, API field/count/
  pagination drift and optimized-Python assertion removal all fail closed.
  The final V12 focused suite passes `37/37`, including V2 dual-record,
  V3-V10, V11-zero, V12-current, pagination, duplicate, pre/post, private
  snapshot, standalone-release-checkout, no-cache and bounded-response tests.
  The preserved V11 suite passes `25/25`, internal readiness passes `16/16`,
  normal and optimized-Python V12 verification both report
  `PREPARED_V12_NOT_TRIGGERED`, all thirteen workflow Bash blocks pass syntax,
  and the repository gate passes `131/131`. Independent read-only runtime
  review reports `P0/P1/P2/P3=0`. The first production-gate mutation run found
  one wording-only `supersedes` / `superseded` assertion mismatch; the
  one-line detail correction passed its target test `1/1` in `52.598s` and
  the full suite then passed `34/34` in `2354.577s`. Only ordinary remote CI
  remains for checkpoint acceptance.

At this exact-11 checkpoint snapshot no V11/V12 workflow, artifact,
authenticated download, cross-provider transfer, cloud builder, Admin ACR,
database, service, production write or public-traffic mutation has occurred,
and the standing bounded authorization is unconsumed. If Git later contains
the exact request-only A12, `V12_ARMED_OR_TRIGGERED_EXACT` and immutable
Git/API evidence supersede this historical zero-run snapshot; no documentation
commit is allowed during the run. Internal/public readiness remains `19/29` /
`19/38`, the latest
credited item remains `api_f_current_release=VERIFIED`, and the sole task
remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit/push the exact-11
checkpoint, require its own ordinary push/PR CI plus fresh V11 run-zero and
unchanged V2-V10 ledgers, then create and remotely accept the exact-four
receipt before the sole request-only V12 activation.

### V12 exact-11 checkpoint remote acceptance and R12 receipt (2026-08-01)

- C12 `8b1f197141b9c84b4ffa812080ecabd6af1bbbce` is the direct child of
  C11 `606c474d347b4dad4e08e6f9fd038a82bdae5315` and contains exactly the
  eleven contracted regular `100644` paths. The worktree is clean and
  branch/upstream are `0/0`. The V11 verifier remains byte-identical at
  `be6203f63a1c35603c1e7a851cd0a4fe0577807a28bf64c10e87530f953a28fe`;
  V11 is `V11_UNTRIGGERED_SUPERSEDED_EXACT` and V12 remains
  `PREPARED_V12_NOT_TRIGGERED`.
- Exact-HEAD push CI `30691062509` / job `91345758810` completed success
  with `1612/1612` tests, `28` skips, unit time `808.792s` and production
  gate `131/131`; the job completed in `14m39s`. Pull-request CI
  `30691063859` / job `91345762808` also completed success with
  `1612/1612`, `28` skips, unit time `819.750s`, gate `131/131` and job
  time `14m46s`.
- The V12 verifier's strict fresh API replay observed `465` fully paginated
  repository runs. V2 remains exactly runs `30572921215` and `30591103183`
  with parser jobs zero and terminal unique job `91033410635`; V3-V10 each
  retain their exact unique attempt-1 failure job and artifact zero. V11 and
  V12 workflow-path run counts are both zero across repeated fresh
  observations. No recovery authorization has been consumed.

This four-file Secret-free snapshot is the exact R12 receipt candidate and
changes only this handoff, the risk ledger, the readiness manifest and its
test. It adds no deployment credit: internal/public readiness remains
`19/29` / `19/38`, the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Require R12's own exact-HEAD push/PR
CI plus unchanged V2-V10 and V11/V12 run zero; only then create the exact-one
request A12. No V11/V12 workflow, artifact, authenticated download, transfer,
cloud builder, Admin ACR, database, service or public-traffic mutation has
occurred.

### V12 exact-one activation, unique failed attempt and terminal supersession candidate (2026-08-01)

- R12 `328c07ed173754585c635ebb7b1d8c2587cadf57` was remotely accepted before
  activation. Its exact-HEAD push CI `30695599968` / job `91357836237` and
  pull-request CI `30695601555` / job `91357839993` both passed `1612/1612`
  tests, `28` skips and repository gate `131/131`.
- A12 `2883d3e216fd64a70b94b1ba27b0838dca280f61` is R12's single-parent,
  request-only child. The sole added `100644` request is `14221` bytes,
  SHA-256 `1bfd1be7c6a03042397c57e2788180a92c51e4843890d141671cc4b29eff432e`
  and blob `5d3112b41ea654479d68b46099f67b5cbe8816b6`. A12 push CI
  `30696298410` / job `91359681561` and pull-request CI `30696299851` / job
  `91359684931` both passed `1612/1612`, `28` skips and gate `131/131`.
- The one authorized V12 workflow attempt is permanently consumed. Run
  `30696298423`, workflow `325026609`, job `91359681758`, run number `1`,
  attempt `1` completed failure. The producer reached its export verifier;
  `Export V12 dependency-only BuildKit local cache` failed exactly once with
  `FAIL: BuildKit anchor cache record binding changed`. The fresh consumer,
  final validation, upload and provider identity steps were never reached.
  Provider artifact count is exactly zero, and rerun is forbidden.
- Resource cleanup passed after the failure: two ephemeral builders were
  created and two removed; builder, image, container, volume and network
  parity passed; the compact 20-field cleanup payload is `558` bytes with
  SHA-256 `66150b14b5a1dc05b73125403610c1ab94ec7a4dba9cddd28735b9af612b5194`.
  Both in-workflow fresh ledgers passed. A later uncached full pagination
  observed `470/470` unique repository runs with immutable V2-V10 records,
  V11 path run zero and exactly this one V12 failure/artifact-zero run.
- Retained producer diagnostics prove V9 and V11 completed their own checks,
  but no cache-record projection or consumer observation was retained. The
  exact runtime portability verdict is therefore `UNKNOWN_NOT_REACHED`.
  Independent source review at BuildKit v0.31.2 commit
  `e42e1bfd389af7203238cce77b1f7dad447285e9` found the verifier defect:
  cache-config `records[].digest` is a cache-key/rootKey identity, whereas
  progress `vertex_digest` is an LLB vertex identity. BuildKit does not define
  those fields as equal. V12's equality predicate was unsupported and failed
  before testing the portable cache itself.
- Secret-free terminal evidence is versioned at
  `deploy/production/evidence/admin-dependency-cache-v12-attempt1-failed-20260801.json`.
  Its strict verifier binds the exact activation lineage, run/job/log,
  diagnostic self-hashes, six pinned BuildKit sources, cleanup, ledger,
  artifact-zero, ordinary CI and authorization boundaries. The direct-child
  terminal checkpoint must contain exactly eleven `100644` paths and report
  `V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT`; its direct-child
  four-file receipt must report
  `V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_RECEIPT_EXACT`. The three added V12
  terminal authorities remain immutable, while later explicitly versioned
  successors may evolve shared gate and ledger integrations after the receipt.

This terminal candidate changes exactly the contracted eleven files: this
handoff, the risk ledger, readiness manifest, V12 plan verifier/test, new V12
failure evidence/verifier/test, production gate/test and internal-readiness
test. Focused and repository verification must be recorded after the commit;
no V12 rerun, download, transfer, cloud builder, Admin ACR, database, service
or public-traffic action is authorized. Readiness remains `19/29` internally
and `19/38` publicly; the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. After exact-11 and exact-four remote
acceptance, continue immediately with append-only V13 using the source-backed
structural cache-config contract and fresh-consumer `SAME_DIGEST_CACHED`
acceptance. A V13 external run requires a new explicit authorization; local
design, tests and ordinary CI do not.

### V12 terminal checkpoint ordinary-CI compatibility failure (2026-08-01)

- Terminal checkpoint `efef71395fce4319ef11c8065b45db482ba12669`
  remains the exact eleven-file, all-`100644`, direct child of A12. Its
  failure/plan verifiers pass in normal and optimized Python and report
  `V12_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT`; focused V12
  terminal/plan/readiness tests passed `61/61`, production gate passed
  `132/132`, and the three new production-gate state tests passed `3/3`.
- Exact-HEAD ordinary push CI `30697559060` / job `91362907859` nevertheless
  failed after `1621` tests passed, `28` skipped and one assertion failed
  (`708.903s`; job `12m56s`). Pull-request CI `30697560965` / job
  `91362912909` failed identically after `1621` passed, `28` skipped and one
  failure (`826.110s`; job `14m36s`). Quality, repository gate and Docker
  steps were skipped, so no gate count exists for either run.
- The sole failure is an old V11 compatibility assertion: it calls V12's
  public `plan_state()` and only accepts the historical request-lifecycle
  values `PREPARED_V12_NOT_TRIGGERED` and `V12_ARMED_OR_TRIGGERED_EXACT`.
  It does not question V12 evidence, Git lineage, cleanup, artifact zero or
  the BuildKit root cause. The V11 test is a frozen authority and cannot be
  edited after activation.
- Fresh five-page Actions reconciliation observed `472/472` unique runs.
  V11 workflow-path run count remains zero; V12 remains exactly run
  `30696298423`, attempt one, failure, job `91359681758`, artifact zero.
  The efef checkpoint triggered only its two ordinary CI runs and did not
  trigger or rerun V12.

This exact-four Secret-free descendant records the failed remote acceptance
without changing runtime or terminal authorities. The minimal append-only
correction will preserve `plan_state()` as the legacy request-activation
lifecycle API for frozen V11 consumers, add a distinct effective terminal
state API, and make the production gate/main V12 verifier consume that
effective state. It will update only permitted integration surfaces plus the
four ledgers, then obtain new ordinary push/PR CI; it will not modify V11,
V12 evidence/workflow/request/runtime, rerun either failed CI, or rerun V12.
Readiness remains `19/29` / `19/38`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

### V12 correction-receipt acceptance and inert V13 checkpoint candidate (2026-08-01)

- Read-only takeover reconciled branch
  `codex/quality-stabilization-real-chain` at local/upstream
  `ae7ce751d842b2880cdb2d31213a983bcb1f7484`, ahead/behind `0/0` before
  V13 work. The commit is the exact four-file correction receipt and direct
  child of `81730a511acb553c9a1e29af834924f71650dc9a`.
- Exact-HEAD push CI `30698918645` / job `91366363365` passed in `14m57s`
  with `1622/1622` tests, `28` skips and production gate `132/132`.
  Pull-request CI `30698919672` / job `91366366249` passed in `15m48s`
  with the same `1622/28/132` boundary. Fresh five-page reconciliation
  observed `476/476` unique Actions runs: V11 path remains zero and V12
  remains exactly run `30696298423`, attempt one, failure, job
  `91359681758`, artifact zero. V12 must never be rerun.
- The append-only V13 candidate corrects only the unsupported V12 evidence
  predicate. Pinned BuildKit v0.31.2 source commit
  `e42e1bfd389af7203238cce77b1f7dad447285e9` proves cache-config
  `records[].digest` and progress `vertex_digest` are different identity
  domains. V13 therefore validates the cache config as a bounded DAG with
  closure, reachability, result/link and depth limits; runtime portability is
  accepted only when a fresh isolated consumer reports
  `SAME_DIGEST_CACHED` for the same runtime-pip vertex digest.
- The V13 verifier binds producer, cache record, index, root manifest,
  config and consumer summaries to the exact bytes parsed. Descriptor blobs
  are opened through directory file descriptors with `O_NOFOLLOW`, bounded
  before reading, and rejected on parent/final symlink, hardlink, size,
  digest or in-read mutation. Core validation exports the exact retained
  cache-record SHA to the frozen import helper and final portability check.
- The V13 control plane uses two fresh, duplicate-rejecting and bounded GitHub
  API snapshots. It fixes the full canonical V2-V12 ledger, repository-wide
  V11 zero, the unique V12 failure and the unique current V13 run; the
  private `0400` contract copy and `0600` snapshots remain in runner temp.
  The trigger is only the exact addition of
  `.github/release-requests/admin-5335bda-dependency-cache-v13.json`.
- The inert Git contract is
  `ae7ce75…7484 → exact-14 checkpoint → exact-4 receipt → exact-1 request`.
  Eight V13 authorities share one addition anchor; ten checkpoint
  non-receipt paths are immutable afterward. The candidate introduces no
  request, run, builder, artifact, download, transfer, ACR publication,
  database/service mutation or traffic authority. Bundle verification passes
  normal and optimized Python `21/21`; plan verification passes normal and
  optimized Python `11/11`; readiness, gate and full-suite
  results are recorded before commit and remote acceptance.

This Secret-free checkpoint adds no readiness credit: internal/public
readiness remains `19/29` / `19/38`, the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit and push only the exact
14-file inert checkpoint, require its own ordinary push/PR CI, then create
and accept the exact-four receipt. Creating the exact-one V13 request and
consuming its single external run require a new explicit user authorization;
no V12 or failed ordinary-CI rerun is permitted.

### V13 inert-checkpoint CI hermeticity failure and structural receipt (2026-08-01)

- C13 `4df6a77e39f2488b852414bb0649babbb37eb98a` is the exact fourteen-file,
  all-`100644`, direct child of the accepted V12 correction receipt
  `ae7ce751d842b2880cdb2d31213a983bcb1f7484`. Before any receipt write, its
  local full suite completed `1655/1655` with `28` intentional skips in
  `6209.827s`; focused V13 normal and optimized-Python suites remained
  `32/32`, and the repository gate remained `133/133`.
- C13 ordinary push CI `30701666137` / job `91373623999` completed failure in
  `17m29s`: `1655` tests, `28` skips and exactly one failure in `994.470s`.
  Pull-request CI `30701667259` / job `91373626894` completed the identical
  one-failure boundary in `14m40s`, with unit time `826.474s`. In both jobs,
  Quality gate, Production readiness gate, Docker Compose and the two post
  setup steps were skipped, so neither run has a readiness check count.
- The sole failure is
  `test_admin_dependency_cache_export_plan_v13.AdminDependencyCacheExportPlanV13Tests.test_exact_checkpoint_receipt_and_activation_git_history`
  at line `522`. Its first temporary-repository validation inherited the
  outer runner's `GITHUB_ACTIONS=true` and C13 `GITHUB_SHA`, then correctly
  rejected that real checkout SHA as unequal to the synthetic temporary
  repository HEAD. The frozen V13 verifier, cache predicates and production
  boundaries did not fail; a CI-hermetic invocation with the four checkout
  context variables removed passes the exact test `1/1`.
- Fresh five-page reconciliation at `2026-08-01T13:45:54Z` observed
  `478/478` unique repository Actions records. C13 has only those two ordinary
  CI runs; V11 workflow-path run count remains zero; V12 remains exactly run
  `30696298423`, run/attempt one, failure, unique job `91359681758` and
  artifact zero. V13 workflow-path run count is zero, and its active request
  is absent from the C13 tree with C13-ancestry addition count zero.

This exact-four Secret-free descendant changes only this handoff, the risk
ledger, the readiness manifest and its test. It is a structural failure
receipt, not a green remote acceptance: `V13_INERT_CHECKPOINT_CI_HERMETICITY_FAILED_RECEIPT_EXACT`.
To avoid blindly reproducing the same deterministic red run, this receipt is
not pushed as an exact remote HEAD. It must be followed locally by an
append-only V14 checkpoint, and only the V14 HEAD will receive the next
ordinary push/PR CI. V13 is permanently untriggered and must never receive a
request or run. No cache artifact, builder, authenticated download, transfer,
Admin ACR, database, service, production write or public-traffic mutation
occurred. Internal/public readiness remains `19/29` / `19/38`; the latest
credited item remains `api_f_current_release=VERIFIED`, and the sole task
remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

### Append-only V14 inert checkpoint candidate (2026-08-01)

- R13 `585edfcb2789b112bbf559bf1d6d75e1843dd54c` is the exact four-file,
  all-`100644`, direct child of failed C13. It records
  `V13_INERT_CHECKPOINT_CI_HERMETICITY_FAILED_RECEIPT_EXACT`, is not a green
  acceptance and is intentionally not pushed alone. V13 remains permanently
  request-zero/run-zero and must never activate.
- C14 is constrained to the exact eleven-file direct child of R13: this
  handoff, the risk register, the V14 workflow/template/plan verifier/test,
  `.github/workflows/ci.yml`, the readiness manifest/test and the production
  gate/test. Its four new V14 authorities share one addition anchor; the seven
  non-receipt checkpoint paths are immutable after C14. R14 must be the exact
  four-file direct child and any later A14 must be a single request-only
  direct child of R14.
- V14 reuses the V13 import helper, source fixture, bundle verifier, bundle
  test and runtime cache-record schema byte-for-byte. The frozen V13 plan
  verifier is loaded lazily by exact SHA-256 and revalidated without current
  Git integration; V13's eight core authorities retain their single C13
  addition anchor and zero post-anchor changes.
- The CI correction preserves real GitHub checkout context for ambient tests
  and the Production Gate. Only the frozen V13 test module runs with
  `GITHUB_ACTIONS`, `GITHUB_SHA`, `GITHUB_EVENT_NAME` and `GITHUB_REF`
  removed. V14's temporary-Git test controls that context within its own
  scope and proves a real synthetic pull-request checkout projects the second
  parent. The entire Unit-test YAML block and CI SHA-256
  `cf21455c03887657ecafb0c4a224144bf4fbe63c3a5de204ffdb31fd0480201e`
  are frozen and mutation-tested.
- The V14 live ledger contains twelve immutable legacy entries V2-V13 plus
  the unique V14 current entry. It requires V11 and V13 repository-wide
  workflow-path run counts zero, the unique V12 attempt-one failure and
  artifact zero, and a unique V14 push/attempt-one/artifact-zero run only
  after authorization. The V13 full plan CLI is forbidden in the V14
  workflow; standalone live-ledger mode does not load repository modules.
- Frozen hashes are: workflow
  `98850e28f74d5b4d4bafacffed07d118cba3378c81a0c93457cb46dc83ac7db1`,
  template
  `9fd2f7d07eb7d9495ba4b27b2b71e6df650d8ef6dd6f599fb8a0da2edeadb4ca`,
  V14 plan test
  `f908bf33fda2e6c49e95fda43589a9f3376aec9681a038245b12ac55d9055a7d`
  and legacy-ledger canonical projection
  `168c17c5f14e1dbf69fe4b4e1ae84fb7335b00eef06bb55ebd23657699537ea2`.
  Independent read-only review found no remaining P0/P1 mechanical or runtime
  defect. V14 plan tests pass normal and optimized Python `12/12`, simulated
  ambient-push execution passes `12/12`, the frozen V13 suite passes `11/11`,
  all thirteen workflow Bash blocks pass syntax, and internal readiness tests
  pass `16/16`.

This candidate adds no readiness credit or production authority. Internal /
public readiness remains `19/29` / `19/38`, the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. A disposable clone committed these
exact eleven candidate paths over R13, reported
`PREPARED_V14_NOT_TRIGGERED`, and passed the repository production gate
`133/133`; both temporary clones were moved to Trash after the check. Commit
and push C14 once, require exact-HEAD push/PR CI plus fresh
V11/V12/V13/V14 ledger reconciliation, form and accept exact-four R14, and
continue to the authorization boundary. Creating A14 or consuming its one
external cache-export run requires new explicit user authorization; no
V12/V13 rerun, production deployment, database, service, ACR or public-traffic
mutation is authorized.

### V14 inert-checkpoint PR-context failure and structural receipt (2026-08-02)

- C14 `e18d24a204c33127a95fe3035b7fce43bdb0b4f8` is the exact eleven-file,
  all-`100644`, direct child of the V13 structural receipt
  `585edfcb2789b112bbf559bf1d6d75e1843dd54c`. Its ordinary push CI
  `30706546764` / job `91386553347` passed in `18m02s`: ambient regression
  `1657/1657` with `28` skips in `1001.153s`, frozen V13 `11/11` in
  `1.266s`, Quality, production gate `133/133` and Docker Compose all passed.
- C14 pull-request CI `30706547955` / job `91386556528` completed failure in
  `19m01s`. Ambient regression still passed `1657/1657` with `28` skips in
  `1077.223s`; the separately invoked frozen V13 suite had exactly one of
  eleven tests fail, after which Quality, production readiness and Docker
  were skipped. The failure was
  `test_reviewed_authorities_validate_without_git_state`: clearing the four
  GitHub checkout variables for the entire V13 module removed the synthetic
  PR merge's second-parent projection needed by V13's real-repository V12
  predecessor validation. The push checkout is linear, so it did not expose
  this boundary.
- Fresh five-page reconciliation at `2026-08-01T16:09:19Z` observed
  `480/480` unique repository Actions records. C14 has exactly those two
  ordinary CI records; V11, V13 and V14 workflow-path run counts remain zero.
  V12 remains exactly run `30696298423`, run/attempt one, failure, unique job
  `91359681758` and artifact zero. V13/V14 active requests are absent and
  their addition histories remain zero.

This exact-four Secret-free descendant changes only this handoff, the risk
ledger, the readiness manifest and its test. It records
`V14_INERT_CHECKPOINT_PR_CONTEXT_FAILED_RECEIPT_EXACT`, is not green remote
acceptance and adds no readiness credit. C14 will not be rerun and this known
red receipt will not be pushed alone. V14 is permanently untriggered and must
never receive a request or run. Its append-only V15 successor must exclude
the frozen V13 and V14 modules from ambient discovery, run V13's ten
real-repository tests with ambient GitHub context, run only V13's temporary-
repository history test with the four checkout variables removed, and
validate the complete frozen V14 suite against the exact C14 tree. No cache
artifact, builder, authenticated download, transfer, Admin ACR, database,
service, production write or public-traffic mutation occurred. Internal /
public readiness remains `19/29` / `19/38`; the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

### Append-only V15 inert checkpoint candidate (2026-08-02)

- R14 `1ca885d61c48f3cfdb4e99eeedc6fb9f17238bb4` is the exact four-file,
  all-`100644`, direct child of C14. It records
  `V14_INERT_CHECKPOINT_PR_CONTEXT_FAILED_RECEIPT_EXACT`, is intentionally
  not pushed alone, adds no readiness credit, and permanently keeps V14 at
  request zero / workflow-run zero.
- C15 is constrained to the exact eleven-file direct child of R14: the four
  ledgers, V15 workflow/template/plan verifier/test, `.github/workflows/ci.yml`
  and the production gate/test. R15 must be the exact four-file direct child;
  any later A15 may add only the single V15 request after new explicit user
  authorization.
- CI now excludes the frozen V13 and V14 modules from ambient discovery. Ten
  V13 real-repository tests retain the real checkout context; only V13's
  temporary-repository history test clears `GITHUB_ACTIONS`, `GITHUB_SHA`,
  `GITHUB_EVENT_NAME` and `GITHUB_REF`. The complete V14 suite is run from a
  detached clone of exact C14, so its historical CI contract is evaluated
  against the tree it actually froze. The unit-test timeout is 25 minutes.
- V15 validates the C14 exact-eleven / R14 exact-four first-parent chain,
  historical C14 CI bytes, current V14 authority bytes and `0644` modes, and
  V14 request/run zero without invoking V14's current-Git/full-plan APIs.
  Its live ledger contains thirteen immutable V2-V14 entries plus the unique
  V15 current run, with V11/V13/V14 repository workflow-path counts fixed at
  zero and V12 fixed to its sole attempt-one failure/artifact-zero record.
- Frozen candidate hashes are: workflow
  `33a57116c7462bb4f73f48f0d94f41158b8bf676886c19518610d172fc6ba457`,
  template
  `b89820b318f98363b768a43663bdf6c730a4d78894c3d1c28547fdb86e42d777`,
  V15 plan verifier
  `6c22eb50b04c3e7ff4a6957554a705179b3d5c5998a670969acafcd6c67e72e5`,
  V15 plan test
  `8e739cd5edc97a33db34ce1fcf5086671101a629a5aa2fb80ae03c6aa1f7c024`,
  CI `d4830c55563e18304c60c04cbe729e9d6c657c2fb5caa61d983eef50fe8a28e9`
  and legacy-ledger canonical projection
  `056103160f2ba8521032073ae7b5e523e82716ba1ae264b2a6b44a788ce30fe9`.
  V15 plan tests pass normal and optimized Python `14/14`; its workflow's
  thirteen Bash blocks and CI's eleven Bash blocks pass syntax; the split
  V13 `10/10 + 1/1` and detached-C14 V14 `12/12` tests pass.

This Secret-free candidate creates no request, external cache run, builder,
artifact, authenticated download, transfer, ACR publication, deployment,
database/service write or public traffic. Internal/public readiness remains
`19/29` / `19/38`, the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. A disposable clone committed the
exact eleven staged paths over R14, reported `PREPARED_V15_NOT_TRIGGERED`
and passed the repository production gate `133/133`; the clone was moved to
Trash after the check. Commit and push C15 once, then require its own
exact-HEAD push/PR CI and fresh V11/V12/V13/V14/V15 ledger reconciliation.
No C14, V12, V13 or V14 workflow rerun is permitted.

### V15 inert checkpoint remote acceptance and R15 receipt (2026-08-02)

- C15 `90f9606d6eb860572814cc3ccc0731fb9d366a5a` is the exact eleven-file,
  all-`100644`, direct child of R14
  `1ca885d61c48f3cfdb4e99eeedc6fb9f17238bb4`. Its active V15 request is
  absent and its V15 workflow-path run count is zero.
- Exact-HEAD push CI `30709036776` / job `91393091573` completed attempt one
  `success`. Ambient regression passed `1659/1659` with `28` skips in
  `1137.047s`; V13 passed `10/10` with ambient context plus the isolated
  temporary-Git test `1/1`; detached exact-C14 V14 passed `12/12`. Quality,
  production readiness `133/133` and Docker Compose all passed.
- Exact-HEAD pull-request CI `30709038582` / job `91393095974` also completed
  attempt one `success`. Ambient regression passed `1659/1659` with `28`
  skips in `1076.818s`; V13 passed `10/10 + 1/1`, detached exact-C14 V14
  passed `12/12`, and Quality, production readiness `133/133` and Docker
  Compose all passed. Each ordinary run therefore executed `1682` tests.
- Fresh no-cache pagination observed five pages and
  `482/482/482` advertised/fetched/unique Actions records. C15 has exactly
  those two ordinary attempt-one success records. Repository workflow-path
  counts remain V11 `0`, V12 `1`, V13 `0`, V14 `0`, V15 `0`; V12 remains
  exactly run `30696298423`, attempt one, failure, unique job
  `91359681758` and artifact zero.

This exact-four Secret-free descendant records the accepted inert checkpoint
without changing any of its seven non-receipt authorities. It adds no
readiness credit and creates no V15 request, external cache run, builder,
artifact, download, transfer, ACR publication, deployment, database/service
write or public traffic. Internal/public readiness remains `19/29` / `19/38`,
the latest credited item remains `api_f_current_release=VERIFIED`, and the
sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. A disposable clone
committed these exact four paths over C15, reported
`PREPARED_V15_NOT_TRIGGERED` and passed production readiness `133/133`; it
was moved to Trash after validation. Commit and push only this exact-four R15
receipt and require its own exact-HEAD push/PR CI plus a fresh unchanged
ledger. After R15 remote acceptance, the sole next write is the exact-one V15
request; creating it and consuming the unique external cache-export run
require new explicit user authorization. No historical checkpoint, receipt
or workflow may be rerun.

### V15 exact-one activation and terminal failure checkpoint candidate (2026-08-02)

- R15 `788a2b48d3dc04bea0f7c26fe7207887131436a7` is the accepted exact-four
  inert receipt. A15 `c61ba14ab77f98dbc63697dc2b3cbe26afdf9df1` is its direct
  exact-one child and adds only
  `.github/release-requests/admin-5335bda-dependency-cache-v15.json` as a
  `100644` blob. The request is `16424` bytes, SHA-256
  `0de3959f100e272e98b19238b670b99dd8fa096ad49179375014063420c37c4a`
  and has one true addition with no later touch.
- A15 created exactly three attempt-one records. Ordinary push CI
  `30724578299` / job `91433793813` and pull-request CI `30724579324` /
  job `91433796451` both passed exact A15. Each ran ambient `1659` tests
  with `28` skips, V13 `10 + 1`, detached exact-C14 V14 `12`, for `1682`
  tests total, then passed Quality, production readiness `133/133` and
  Docker Compose.
- The one authorized V15 workflow run `30724578319` / job `91433793914`,
  workflow `325309521`, run one / attempt one, completed `failure`. Export,
  source validation, both live-ledger snapshots and cleanup passed. The sole
  failed step was fresh-consumer import/cacheless replay, exit `3`, code
  `V13_PAIR_CACHE_PREDICATE_FAILED`: producer `runtime_pip` digest
  `sha256:f3c7f2ff52b744ba6773ea26aa2a853092202fdc86e7679e93f44646eedb0c9a`
  drifted to consumer digest
  `sha256:8ed38b7ab56a85d1783d009e5ffbedf0d4fe769254004b1ef220c98152357e8a`.
  The consumer had `23` completed intervals, only `1` cached and `22`
  noncached, so `SAME_DIGEST_CACHED` was correctly rejected.
- The imported cache structure itself remained bounded and valid: config
  SHA-256 `eb3ea9fcc5872a0732915d99b5f58727c46038e570896a5fd288e39c2bd94e20`,
  `4873` bytes, `17` records, `10` result-bearing records, `17` links and
  `19` layers; DAG and reachability checks passed. This does not prove
  runtime portability. Cacheless replay, final validation and upload were
  not reached; artifact/download/transfer counts are zero.
- Cleanup removed both ephemeral builders and restored image, container,
  volume and network parity. Fresh no-cache pagination at
  `2026-08-02T00:28:03Z` observed five pages and `487/487/487`
  advertised/fetched/unique runs. V11/V13/V14 workflow paths remain zero,
  V12 remains its sole failure, and V15 has exactly this one failure, unique
  job and artifact zero. V15 must never be rerun.
- The dynamically proven boundary is `runtime_pip DIGEST_DRIFT`. Fixed
  BuildKit source explains a high-confidence mechanism: separate local main
  contexts carry per-solve session identity into the first local `COPY` and
  downstream LLB digest. V15 did not retain the two actual session values or
  the two `COPY requirements` vertex digests, so those values are not claimed
  as directly observed. The consumer emitted zero decoded pip log bytes;
  actual dependency download or network execution is also not claimed.
- The minimal V16 direction keeps the combined Dockerfile byte-exact but uses
  the same full-commit Git main context for both solves, adds a bounded
  source-to-COPY-to-pip identity projection, and retains the strict fresh
  consumer `SAME_DIGEST_CACHED` predicate. It may not accept digest drift,
  noncached intervals, a structural-DAG-only result or zero logs as a cache
  hit.

This exact-eleven candidate adds the Secret-free evidence JSON, its verifier
and test, and updates only the four ledgers plus the V15 plan/gate verifier
and tests. It is the required first post-activation write and adds no readiness
credit. Internal/public readiness remains `19/29` / `19/38`, the latest
credited item remains `api_f_current_release=VERIFIED`, and the sole task
remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit and push only this
exact-eleven terminal checkpoint, require its exact-HEAD ordinary push/PR CI
and fresh ledger, then create the exact-four terminal receipt and continue to
the separately versioned V16 inert checkpoint. Any V16 external run requires
new explicit user authorization; no V15 or historical workflow rerun is
permitted.

### V15 terminal checkpoint remote acceptance and exact-four receipt (2026-08-02)

- T15 `46595fef4916ca2881dd38c0a14ee630bba79c32` is the exact eleven-file,
  all-`100644`, direct child of A15
  `c61ba14ab77f98dbc63697dc2b3cbe26afdf9df1`. The three terminal
  evidence/verifier/test additions share T15 as their sole addition anchor;
  the V15 request, workflow, template, CI and frozen V13 data plane were not
  changed.
- Exact-HEAD push CI `30727588135` / job `91442042559` completed attempt one
  `success`. Ambient regression passed `1669/1669` with `28` skips in
  `1003.458s`; V13 passed `10/10` plus its isolated temporary-Git test `1/1`,
  and detached exact-C14 V14 passed `12/12`, for `1692` tests total. Quality
  (`7` pass plus one expected-fail fixture), production readiness `134/134`
  and Docker Compose all passed.
- Exact-HEAD pull-request CI `30727589274` / job `91442045947` also completed
  attempt one `success`. Ambient regression passed `1669/1669` with `28`
  skips in `1036.600s`; V13 passed `10/10 + 1/1`, detached exact-C14 V14
  passed `12/12`, and Quality, production readiness `134/134` and Docker
  Compose all passed. The jobs completed in about `18m10s` and `18m36s`,
  below the fixed `25m` limit.
- Fresh no-cache pagination observed five pages and `489/489/489`
  advertised/fetched/unique Actions records. T15 has exactly those two
  ordinary attempt-one success records. Workflow-path counts remain V11 `0`,
  V12 `1`, V13 `0`, V14 `0`, V15 `1`; V15 is still exactly run
  `30724578319`, attempt one, failure, unique job `91433793914`, rerun zero
  and artifact `0`.

This exact-four Secret-free descendant records T15 acceptance without changing
the V15 request, workflow, terminal evidence/verifier/test or any other
nonreceipt authority. It adds no readiness credit and performs no workflow,
builder, artifact, download, transfer, ACR, deployment, database/service or
public-traffic action. Internal/public readiness remains `19/29` / `19/38`,
the latest credited item remains `api_f_current_release=VERIFIED`, and the
sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

The prior V15 step label `cacheless replay` means only that the exported local
cache directory was removed before a replay on the same consumer builder; it
does not prove that builder's internal cache was empty. V15 never reached that
replay, so its terminal verdict is unchanged. V16 must call this an
`external-cache-removed same-consumer-builder replay`, or create and clean a
third fresh builder before claiming a true empty-cache replay. V16 must also
use a fixed full-commit Git main context for both solves and may keep the
combined Dockerfile as a separately decoded, byte-bound local input. Its
checkpoint path count must follow the independently tested authority set; it
must not be forced into an eleven-file shape by embedding data-plane logic in
the workflow or by changing frozen V15 authorities. Commit and push only this
exact-four receipt, accept its own ordinary CI and unchanged ledger, then
continue directly to the separately versioned V16 inert control plane. Any
V16 external run still requires new explicit authorization; no V15 or
historical workflow may be rerun.

### Append-only V16 inert Git-context recovery checkpoint candidate (2026-08-02)

- The accepted V15 terminal receipt is
  `a94ee2b2feb81eafbcb523be2c95da4ee952cbc4`. V15 remains permanently
  terminal: its only workflow run is `30724578319` / job `91433793914`,
  run one / attempt one / failure, with artifact zero and no rerun. No V15
  authority is changed by V16.
- The V16 checkpoint authority is exactly sixteen `100644` paths: the four
  Secret-free ledgers, one inert workflow, one request template, two shell
  helpers, one fixed BuildKit Git-context projection fixture, two bundle
  verifier/test files, one plan verifier/test pair, CI, and the production
  readiness gate/test. The later terminal receipt is exactly the same four
  ledgers; a future activation may add only one release-request file.
- Producer and fresh consumer are bound to the same immutable full-commit Git
  main context for commit `5335bdaed933b1f999b5f819c047ec50c11821ae`.
  The combined Dockerfile remains byte-bound as the only local named input.
  V16 additionally binds the Git source identity, both `COPY` vertices and
  `runtime_pip`, and still accepts only the same `runtime_pip` digest with
  every completed interval cached and zero noncached intervals.
- The frozen V13 structural verifier is reused only through an explicitly
  hashed compatibility projection. V16 separately records the frozen V13
  verdict hash and the transformed projection hash, rebinds the actual V16
  producer raw-byte SHA in the cache-record adapter, rereads source metadata
  to close the validation/use gap, and fails closed on explicit-input or
  platform drift.
- Deleting the exported directory and replaying on the same consumer is named
  only `external-cache-removed same-consumer-builder replay` and sets
  `true_empty_cache_replay_claimed=false`. V16 makes no true empty-cache
  claim and may not treat digest drift, noncached work, a structural DAG or
  zero logs as a cache hit.
- The live ledger is append-only length fourteen: V11 at index nine, V12 at
  ten, V13 at eleven, V14 at twelve and terminal V15 at thirteen. V11, V13
  and V14 retain repository workflow-path count zero; V12 and V15 retain
  their single immutable attempt-one failures. The only current-generation
  workflow inventory is V16, with request absent and run count zero.
- Local verification currently passes V16 bundle contracts `9/9`, V16 plan
  contracts `13/13`, internal readiness contracts `16/16`, JSON parsing,
  frozen V13 compatibility contracts `21/21`, V15 terminal evidence `5/5`
  and three selected production-gate contracts `3/3` in `325.549s`, plus
  optimized-Python V16 contracts `22/22`, Quality Gate (`7` passing samples
  plus one expected-fail sample), Docker Compose configuration, Python
  compilation and both helper shell syntax checks. The one diagnostic line
  emitted by the bundle tests is an expected fail-closed V13 structure
  fixture, not an external call or a repository mutation.
- The first real post-commit Git-topology evaluation correctly exposed an
  over-broad predecessor call: frozen V15's verifier was evaluating its CI
  immutability against the V16 branch head instead of the accepted V15
  receipt. V16 now runs the hash-pinned V15 semantic verifier without mutable
  current-head Git state, then evaluates its unchanged historical Git
  contract at fixed receipt `a94ee2b2…cbc4`. V16 plan tests remain `13/13`
  and the real evaluator reports `PREPARED_V16_NOT_TRIGGERED`; no historical
  hash or path-set condition was relaxed.
- The first full 135-check report then exposed the same stale V15 scope in
  the gate's separate evidence call plus one false-positive scan of the
  literal control name `BUILDKIT_NO_CLIENT_TOKEN`. The gate now requests
  semantic-only evidence because the fixed-receipt predecessor check already
  owns Git history, while the control token is represented in the same
  scanner-safe form used by earlier frozen verifiers. Ambient CI excludes
  V15's HEAD-bound terminal test and executes the full V15 plan/evidence
  suites in a detached exact-`a94ee2b2…cbc4` clone; that projection passes
  `22/22`. Secret scanning remains unchanged and no exception was added. The
  corrected final local production-readiness report passes all `135/135`
  checks with zero failures.

This prepared checkpoint creates no request and performs no cache workflow,
builder, artifact, download, transfer, ACR, deployment, database/service or
public-traffic action. It earns no readiness credit: internal/public
readiness remains `19/29` / `19/38`, the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next acceptance boundary is an
exact-sixteen direct child of the accepted V15 receipt, followed by its own
ordinary exact-HEAD push and pull-request CI, fresh fully paginated ledgers,
and an exact-four Secret-free receipt. Any exact-one V16 activation and its
single external cache-export run require a new explicit user authorization;
the already consumed V15 authorization cannot be reused.

### V16 inert checkpoint remote acceptance and exact-four receipt candidate (2026-08-02)

- C16 `b6f642e68c21341c90bb3c66f810945ada4e084a` is the exact-sixteen,
  all-`100644`, direct child of accepted V15 terminal receipt
  `a94ee2b2feb81eafbcb523be2c95da4ee952cbc4`. Its active V16 request is
  absent and V16's workflow-path run count is zero.
- Exact-HEAD push CI `30731965367` / job `91453812740` completed run one /
  attempt one `success`. Ambient regression passed `1669/1669` with `28`
  skips in `1147.429s`; V13 passed `10/10` plus its isolated exact-Git test
  `1/1`, detached exact-C14 V14 passed `12/12`, and detached exact-a94 V15
  plan/evidence passed `22/22`, for `1714` tests total. Quality Gate passed
  seven delivery samples plus one expected-fail sample, production readiness
  passed `135/135`, and Docker Compose configuration passed. The sole `test`
  job ran from `2026-08-02T04:12:29Z` to `04:33:00Z` and produced no
  artifact.
- Exact-HEAD pull-request CI `30731966620` / job `91453816296` also completed
  run one / attempt one `success`. Ambient regression passed `1669/1669`
  with `28` skips in `979.317s`; V13 passed `10/10 + 1/1`, detached V14
  `12/12`, detached V15 `22/22`, and Quality, production readiness `135/135`
  and Docker Compose all passed. The sole `test` job ran from
  `2026-08-02T04:12:26Z` to `04:30:13Z` and produced no artifact.
- Fresh no-cache pagination observed five pages and `493/493/493`
  advertised/fetched/unique Actions records. C16 has exactly those two
  ordinary attempt-one success records. Workflow-path counts remain V11 `0`,
  V12 `1`, V13 `0`, V14 `0`, V15 `1` and V16 `0`; V12 remains exactly run
  `30696298423` / attempt one / failure, and V15 remains exactly run
  `30724578319` / job `91433793914` / attempt one / failure. The V16 request
  addition history and V16 external-run count are both zero.

This exact-four Secret-free receipt candidate changes only Handoff, Risk,
Readiness and its internal-readiness test. It does not change the twelve V16
nonreceipt authorities and creates no request, cache workflow, builder,
artifact, download, transfer, ACR publication, deployment, database/service
write or public traffic. It adds no readiness credit: internal/public
readiness remains `19/29` / `19/38`, the latest credited item remains
`api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Commit and push only this exact-four
direct child, then require its own ordinary exact-HEAD push/PR CI and a fresh
unchanged ledger. Creating the future exact-one V16 request and consuming a
single V16 external cache-export run still require new explicit user
authorization; no historical workflow may be rerun.

### V16 exact-one activation and terminal failure checkpoint candidate (2026-08-02)

- Accepted V16 inert topology is C16
  `b6f642e68c21341c90bb3c66f810945ada4e084a` -> R16
  `095529e03f735494a98ce2302a6e1be570291d8c`. Authorized A16
  `fd1444d0a62549b3c353cbc1188e6ba25a77e96e` is R16's direct single-parent,
  exact-one child and adds only the immutable `100644` V16 request: `18,342`
  bytes, SHA-256 `65f606db…ff28`, blob `3353fa69…491f`.
- A16 ordinary push CI `30739167685` / job `91473336783` and pull-request CI
  `30739168799` / job `91473339876` both completed run one / attempt one
  `success`. Each ran ambient `1669` tests with `28` skips, V13 `10+1`,
  detached V14 `12` and detached V15 `22`, for `1714` total, then passed
  Quality, production readiness `135/135` and Docker Compose. Their artifact
  inventories are both zero.
- The authorized external execution is exactly one V16 run `30739167701` /
  job `91473336858`, run one / attempt one / `failure`, at A16. Buildx and the
  local cache export completed, then producer evidence validation failed
  closed with `FAIL: BuildKit git_main_context lifecycle changed`, correlated
  to `NETWORK_VERTEX_LIFECYCLE_OUTSIDE_BUILD` in the frozen V13 interval
  predicate. No metadata, raw JSON, identity projection or lifecycle timestamp
  diagnostic survived, so evidence cannot distinguish early start, late
  completion or missing completion and must not invent actual interval values.
- Cleanup-active validation separately reported
  `FAIL: transient_state_contract_changed`. Fixed Buildx v0.35.0 source gives
  a high-confidence explanation that the remote Git context is persisted as a
  non-absolute `LocalPath`, but the runtime ref payload was not retained; this
  is source-proven likely, not an observed field value.
- Consumer import, external-cache-removed same-consumer-builder replay, final
  validation and upload were not reached. Portability is therefore
  `UNKNOWN_NOT_REACHED`. Provider artifact, authenticated download, transfer,
  ACR, deployment, production database/service and public-traffic mutations
  are all zero.
- Cleanup removed both ephemeral builders and new images; both builders are
  absent, enumerated image/container/volume/network parity passed, and Docker,
  Buildx and diagnostic roots are absent. `cleanup_effective=true`, but the
  receipt remains correctly fail-closed with `overall_pass=false` because
  `pre_state=drift`; it is not a cleanup PASS claim.
- Fresh no-cache pagination at `2026-08-02T08:33:00Z` observed five pages and
  `498/498/498` advertised/fetched/unique repository Actions records. A16 has
  exactly its two ordinary CI successes and this one V16 failure. Workflow
  counts are V11 `0`, V12 `1`, V13 `0`, V14 `0`, V15 `1`, V16 `1`; V16 has
  no attempt two, rerun, duplicate or artifact.
- Local terminal validation passes the final focused contract set `43/43` in
  `18.438s`, optimized-Python V16 plan/evidence `21/21` in `2.115s`, JSON,
  Python compilation, diff hygiene, all eight frozen-authority hashes and the
  real precommit evaluator (`V16_ARMED_OR_TRIGGERED_EXACT`). A combined local
  legacy production-gate sweep was stopped after the 25-minute observation
  boundary while still repeatedly evaluating frozen V4-V10 Git history; the
  first `45` tests had no failure, sampling showed active controlled Git
  subprocesses, and no external action occurred. Exact-HEAD remote CI remains
  the required full-suite/gate acceptance for the terminal commit.

The V16 one-shot authorization is consumed and V16 may never be rerun. This
exact-eleven terminal supersession candidate changes only the three new
Secret-free failure authorities, the four versioned plan/gate authorities and
the four ledgers; all request/workflow/CI/template/helper/fixture/bundle
authorities remain frozen. It adds no credit: readiness remains `19/29` /
`19/38`, latest credit remains `api_f_current_release=VERIFIED`, and the sole
task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. After exact-eleven commit,
push, exact-HEAD ordinary CI, artifact-zero and fresh ledger acceptance, form
the exact-four terminal receipt and continue append-only V17. V17 must retain a
bounded Secret-free pre-assertion Git SourceOp lifecycle diagnostic, model Git
frontend timing separately from network ExecOps, and accept only the exact
canonical HTTPS Git query in transient validation. Any V17 external run needs
new explicit user authorization.

### V16 terminal checkpoint remote acceptance and exact-four receipt candidate (2026-08-02)

- T16 `4c2df3b19b4f5493adba78eed89c3a015d76972d` is A16's direct
  single-parent, exact-eleven, all-`100644` terminal supersession. The committed
  failure verifier reports
  `V16_TRIGGERED_ATTEMPT1_FAILED_TERMINAL_SUPERSESSION_EXACT`; all eight frozen
  authorities and the immutable V16 request remain byte-exact.
- Exact-HEAD push CI `30741594513` / job `91479900314` completed run one /
  attempt one `success`. Ambient regression passed `1680/1680` with `28` skips
  in `1089.286s`; V13 passed `10/10` in `0.660s` plus its isolated exact-Git
  test `1/1` in `0.911s`, detached V14 passed `12/12` in `1.297s`, and
  detached V15 passed `22/22` in `4.263s`, for `1725` tests total. Quality,
  production readiness `136/136` and Docker Compose passed. The job ran from
  `2026-08-02T09:21:11Z` to `09:40:47Z` and produced no artifact.
- Exact-HEAD pull-request CI `30741595902` / job `91479904223` also completed
  run one / attempt one `success`. Ambient regression passed `1680/1680` with
  `28` skips in `1052.530s`; V13 passed `10/10` in `0.665s` plus isolated
  `1/1` in `0.851s`, detached V14 `12/12` in `1.198s`, detached V15 `22/22`
  in `3.958s`, for `1725` total. Quality, production readiness `136/136` and
  Docker Compose passed. The job ran from `2026-08-02T09:21:15Z` to
  `09:40:17Z` and produced no artifact.
- Fresh no-cache pagination at `2026-08-02T09:42:05Z` observed five pages and
  `500/500/500` advertised/fetched/unique repository Actions records. T16 has
  exactly those two ordinary attempt-one success records. Workflow-path counts
  remain V11 `0`, V12 `1`, V13 `0`, V14 `0`, V15 `1`, V16 `1`; the unique
  V16 run remains `30739167701` / job `91473336858` / attempt one / failure /
  artifact zero with no rerun or duplicate. Local, upstream and remote branch
  heads all resolve T16.

This exact-four Secret-free terminal receipt candidate may change only Handoff,
Risk, Readiness and its internal-readiness test. It records T16 acceptance,
adds no readiness credit and performs no request, cache workflow, builder,
artifact, download, transfer, ACR, deployment, database/service or public-
traffic action. Internal/public readiness remains `19/29` / `19/38`, latest
credit remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. It must be T16's first first-parent
successor. After its own exact-HEAD ordinary CI and fresh ledger acceptance,
continue to the independently audited exact-eighteen V17 inert checkpoint and
exact-four receipt. Stop before any exact-one V17 request: a V17 external run
requires new explicit user authorization, and V16 may never be rerun.

### V16 terminal receipt remote acceptance and V17 exact18 inert candidate (2026-08-02)

- TR16 `751da973dd7136d792adfafa11e50f5e5e0bd689` is T16's first
  first-parent successor and exact-four, all-`100644` Secret-free terminal
  receipt. Exact-HEAD push CI `30742513491` / job `91482331187` and
  pull-request CI `30742515068` / job `91482335383` both passed run one /
  attempt one. Each ran ambient `1680` tests with `28` skips, V13 `10+1`,
  detached V14 `12` and detached V15 `22`, for `1725` total, then passed
  Quality, production readiness `136/136` and Docker Compose with artifact
  count zero.
- Fresh no-cache reconciliation observed six pages and identical
  `502/502/502` advertised/fetched/unique Actions records. TR16 has exactly
  those two ordinary successes. Workflow-path counts are V11 `0`, V12 `1`,
  V13 `0`, V14 `0`, V15 `1`, V16 `1`, V17 `0`; the unique V16 attempt-one
  failure remains unchanged, and V17 request/history/run counts remain zero.
- C17 is now a local, uncommitted exact-eighteen direct-child candidate of
  TR16: eleven new V17 authorities and seven existing CI/gate/ledger
  authorities, all intended mode `100644`. It keeps the V5 cleanup namespace,
  accepts only the byte-exact canonical remote-Git query, records bounded
  `0600` Secret-free pre-assertion Git lifecycle diagnostics and command
  envelopes, separates Git frontend timing from the frozen network ExecOp and
  FileOp predicates, rereads all bound inputs against TOCTOU, and validates
  V16 only through the fixed TR16 terminal authority.
- Local focused validation is transient-state `12/12`, bundle-verifier
  `12/12`, V17 plan `13/13`, plus Bash syntax, Python compilation, YAML parse
  and static no-Git plan validation. One real current-repository production
  readiness gate test also passed before ledger insertion; the full gate will
  be rerun once C17 is committed so its exact Git topology is observable.
- No V17 request exists and no cache-export workflow, builder, provider
  artifact, authenticated download, transfer, ACR publication, deployment,
  database/service mutation or public-traffic action has occurred. Readiness
  remains `19/29` internal and `19/38` public; no credit is added and the sole
  task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

Next, validate and commit only the exact18 C17 direct child, push it, require
its exact-HEAD push/PR CI plus a fresh unchanged ledger, then form the exact4
R17 receipt and repeat remote acceptance. V16 is permanently non-rerunnable.
Creating an exact-one A17 request or triggering any V17 external cache-export
run remains outside current authority and requires a new explicit user
authorization.

The C17/R17 instructions immediately above are historical and are superseded
by the terminal V17 record below. Do not execute them.

### V17 minimal native-control activation and terminal run (2026-08-02)

- C17 `7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e` is the immutable V17
  data-plane anchor. Minimal control-plane simplification commit
  `d930990d6a4393c565927306d7ae6b5db1ec4e88` removed R17 and the custom
  ledger/receipt/topology prerequisites from only the V17 workflow, request
  template, plan verifier/tests and production-gate hash/tests. The six
  C17 build/import/cleanup workflow steps and all seven C17 data-plane witness
  files remained byte-identical; no image, build content or production
  resource changed.
- D930 exact-HEAD push CI `30747482874` / job `91495423631` and pull-request
  CI `30747484142` / job `91495426765` both passed attempt one. Each completed
  the ambient `1696`-test suite with `28` skips, frozen-chain total `1762`,
  Quality, production readiness `137/137` and Docker Compose.
- Exact-one activation commit `6b8fba3dd8eb5b387b890f7b486a4cfa5e373f36`
  is D930's direct child and adds only
  `.github/release-requests/admin-5335bda-dependency-cache-v17.json`. It
  created exactly one native V17 workflow run: run `30748098684`, job
  `91497111488`, push event, run attempt one, head SHA `6b8fba3…73f36`.
- The activation head's ordinary push CI `30748098675` / job `91497111413`
  and pull-request CI `30748100955` / job `91497116914` both passed attempt
  one. Each passed ambient `1696` tests with `28` skips, frozen-chain total
  `1762`, Quality, production readiness `137/137` and Docker Compose; both
  ordinary runs have artifact count zero.
- The producer BuildKit build and local cache-export command completed, and
  the V17 Git SourceOp lifecycle predicate passed. The immediately following
  frozen V13 → V9 → V6 → V3 compatibility path rejected the first-run
  evidence as `FROZEN_V9_EVIDENCE_INVALID` /
  `FROZEN_V3_VALIDATION_FAILED`. The available log cannot identify a narrower
  V3 subfield because raw metadata was not uploaded. Packaging/upload and the
  fresh-builder import were not reached.
- Native acceptance evidence is therefore: workflow run ID present
  (`30748098684`), fixed C17 SHA present (`7ee9a154…2d6e`), artifact digest
  absent (`artifact_count=0`), and fresh-builder import success absent. The
  one-shot V17 authorization is consumed. V17 will not be rerun; no R17 or V18
  will be created.
- Cleanup removed both builders and all new images; image, container, volume
  and network parity, Docker/Buildx roots and diagnostic-file absence all
  passed. `cleanup_effective=true`; `overall_pass=false` only because the
  cleanup step entered with `pre_state=drift`. There was no artifact download,
  transfer, ACR publication, deployment, database/service or public-traffic
  mutation.
- Readiness remains `19/29` internal and `19/38` public. The sole current task
  remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. V17's immediate unmet hard
  condition is one uploaded cache artifact plus a successful import by a fresh
  builder; item 20's ultimate hard condition remains the real private Admin
  current-release deployment with negative runtime, health and rollback
  acceptance. No implementation change is authorized from this failed run.

### Item 20 exact-5335 Admin Stage A attempt 1 failed before Docker build (2026-08-03)

- Read-only takeover reconfirmed branch
  `codex/quality-stabilization-real-chain`, local/upstream HEAD
  `da59c425c1faef02b7c1349ceb16b818ff47fdda`, divergence `0/0` and a
  clean tracked worktree. Item 20 remains the only task; V17 is not an Item 20
  prerequisite and will not be rerun. No R17 or V18 was created.
- Existing isolated AMD64 PAYG builder
  `i-wz99180s9ig5ecq10uaj` passed the bounded read-only preflight after one
  controlled reboot: `x86_64`, Docker active, zero running containers, zero
  Docker auth/helper/store entries, zero build processes, at least `82,899`
  MiB free disk and `15,032` MiB available memory. No new builder was created.
- Secret-free Stage A script `/root/admin_item20_stage_a_v1.sh` was sent to
  that builder only by Cloud Assistant file invocation
  `f-sz06stvaenzfp4w`. The accepted file contract was root/root mode `0600`,
  `16,776` bytes and SHA-256
  `0843d51302f01e9e865e0f0c6bb864a7a29d98c73079a5c58b189892cb9d2342`.
- Exactly one execution was submitted: Cloud Assistant invocation
  `t-sz06stvryp6jaww`, command `c-sz06stvryorjwu8`, name
  `noteai-admin-item20-stage-a-execute-v1`, created
  `2026-08-03T08:37:01+08:00`, completed
  `2026-08-03T08:37:05+08:00`, duration three seconds, exit code `1`.
  API-F and API-C were not selected. Automatic retry, manual rerun and a
  second execution are all zero.
- The attempt failed closed in `model_materialization` before any Docker build.
  The exact failing entrypoint was
  `python3 scripts/fetch_model_artifacts.py --check-only --required`; the
  builder host interpreter rejected `from __future__ import annotations` as
  an undefined future feature. This proves the preflight omitted a required
  host-Python compatibility check. `docker buildx build`, native release
  evidence, ACR login/push/readback, Admin canary, service mutation, database
  writes and public-traffic mutation were not reached.
- Failure cleanup reported
  `NOTEAI_ADMIN_STAGE_A_CLEANUP target_images=absent task_root=absent running=0`.
  The wrapper returned normally through its unconditional uploaded-file EXIT
  trap. The builder was then observed `已停止 / 节省停机模式` at
  `2026-08-03T08:43:57+08:00`. No candidate image, registry tag/digest,
  provider artifact, production resource or residual running container was
  created.
- Secret-free checkpoint validation passed JSON parsing, all `16/16` focused
  internal-readiness tests, the internal gate at `19/29` / `19/38`, the full
  production gate at `137/137` and `git diff --check`.
- This attempt earns no credit. Internal/public readiness remains `19/29` /
  `19/38`, latest credit remains `api_f_current_release=VERIFIED`, and the sole
  task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

The current bounded external attempt is consumed and must not be retried under
the same authority. The smallest technical correction is to remove the legacy
host-Python dependency from all Stage A validation snippets, or prove a
compatible interpreter before any paid execution; the current script also has
a later `datetime.fromisoformat` host-version dependency, so changing only the
first failing line would be insufficient. Before any new external attempt, the
corrected validation path must be versioned and pass offline syntax/fixture
checks. A new explicit bounded authority is then required for exactly one
corrected Stage A execution. Its next hard acceptance condition is still the
immutable ACR manifest digest for exact source
`5335bdaed933b1f999b5f819c047ec50c11821ae`; only after that digest exists may
the audited Admin canary, negative runtime matrix and component rollback run.

### Item 20 Admin Stage A V2 host-compatibility checkpoint candidate (2026-08-03)

- CTO takeover reconfirmed branch `codex/quality-stabilization-real-chain`,
  local/upstream HEAD `78887aab7878ac58882b16ca23ab6210569f6b84`,
  divergence `0/0` and a clean starting worktree. The prior checkpoint's push
  CI `30775349836` / job `91569707920` and pull-request CI `30775350973` /
  job `91569711063` both passed run one / attempt one at that exact HEAD.
- The deleted V1 source was recovered read-only from the Codex patch record and
  accepted only after recomputing the already recorded contract: exactly
  `16,776` bytes and SHA-256
  `0843d51302f01e9e865e0f0c6bb864a7a29d98c73079a5c58b189892cb9d2342`.
  An independent read-only subagent confirmed the same byte/hash contract and
  enumerated all five direct host-Python call sites. No external command ran.
- The corrected executor is now versioned at
  `deploy/production/admin_item20_stage_a_v2.sh`: `22,254` bytes, SHA-256
  `85e4e60e40e2a3f00c7fe9d1220ec37fdce2eb2772b8ce74ee92b0249755abd6`.
  It replaces both Docker-auth snippets, model-artifact verification, exact
  Admin-role projection and Trivy-metadata freshness with explicit fail-closed
  shell/jq/sed checks. Direct host `python3` calls are zero.
- Independent review found and the main CTO fixed two additional host-control
  edges before publication: runtime Trivy freshness can no longer be overridden
  by an environment timestamp, and a fixed `jq fromdateiso8601` capability
  assertion now runs before source fetch, Trivy download or Docker build.
- Exact data-plane anchors remain unchanged: source
  `5335bdaed933b1f999b5f819c047ec50c11821ae`, tree
  `38e574e56406ba3380acb78edbe784508cc537cd`, Dockerfile SHA
  `ed6282c4…21b447`, native evidence input SHA `639941a2…7d3a2`, projected
  Admin-only SHA `a2420972…df22c`, OCI version
  `git-5335bda-amd64-r1`, canonical/local image tags, pinned base indexes,
  one native build/scan invocation and all scan/evidence acceptance predicates.
  The script contains no ACR login/push, production service, database or public
  traffic mutation.
- Offline acceptance currently passes Bash syntax, positive and negative
  fixtures, the new focused test `3/3`, combined Stage-A/readiness tests
  `19/19`, `git diff --check`, the full production gate at `137/137`, and the
  internal gate at `19/29` / `19/38`.
  Builder start, upload, Cloud Assistant execution, Docker build, ACR publish,
  production deployment, database/service mutation and public traffic mutation
  counts for V2 remain zero.
- Standing CTO authority now covers the remaining bounded chain without further
  stepwise confirmation: exact-HEAD push/PR CI; one corrected Stage A execution
  on the existing isolated builder; one private ACR publication/readback; then
  API-C Admin loopback canary, negative runtime matrix, reversible promotion,
  explicit restart, component rollback and cleanup, including exactly one
  bounded `admin_sessions` INSERT+DELETE. It does not authorize public traffic,
  schema/business writes, paid AI/crawler work, V17 rerun, R17 or V18.

Readiness remains `19/29` internal and `19/38` public with
`api_f_current_release=VERIFIED` as the latest credit. The sole current task is
still `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next, commit and push only this
V2 compatibility checkpoint, require its exact-HEAD push and PR CI, then start
the existing stopped builder and submit exactly one V2 execution. Its immediate
hard acceptance is the exact 5335 local Admin image plus native evidence; the
following hard acceptance remains one immutable private ACR manifest digest.

### Item 20 Admin Stage A V2 attempt 1 failed cleanly in source fetch (2026-08-03)

- Checkpoint `eea0504acf8b6253d066116a5278833dc681ff74` was already pushed before
  any external action. Its exact-HEAD push CI `30777395304` / job
  `91575375837` and pull-request CI `30777397136` / job `91575380930` both
  passed run one / attempt one. Each completed `1765` tests, Quality,
  production readiness `137/137` and Docker Compose; artifact count was zero.
- The frozen `22,254`-byte V2 executor with SHA-256
  `85e4e60e40e2a3f00c7fe9d1220ec37fdce2eb2772b8ce74ee92b0249755abd6`
  was sent once to only the existing isolated builder. The file invocation
  succeeded; remote path was `/root/admin_item20_stage_a_v2.sh`, owner/group
  `root:root`, mode `0600`. API-C and API-F were not selected.
- Exactly one Stage A execution was submitted, created
  `2026-08-03T10:05:30+08:00` and completed
  `2026-08-03T10:07:32+08:00`. Duration was `122` seconds and exit code was
  `128`. The wrapper's frozen-SHA precheck passed. Automatic retry, manual
  rerun and a second Stage A execution are all zero.
- The exact terminal output was limited to the SHA precheck plus
  `error: RPC failed; curl 52 Empty reply from server`,
  `fatal: expected 'packfile'`,
  `NOTEAI_ADMIN_STAGE_A_FAIL phase=source_fetch exit=128` and
  `NOTEAI_ADMIN_STAGE_A_CLEANUP target_images=absent task_root=absent running=0`.
  This identifies an upstream Git transport connection termination during the
  single shallow fetch. Checkout, model materialization, Trivy DB download,
  Docker build/scan, native evidence, ACR and all production actions were not
  reached.
- Failure cleanup removed the task root and left both target images absent with
  zero running containers. The upload wrapper contained an unconditional EXIT
  trap; script-file removal was not separately probed because that would have
  required an extra external command. The first console stop used ordinary
  mode, so the CTO performed one start with no script or Stage A command and
  immediately stopped again after explicitly selecting
  `节省停机模式（原停机不收费）`. Final observed state at
  `2026-08-03T10:18:44+08:00` was `已停止 / 节省停机模式`, with public IPv4
  released. These two extra power transitions were cost cleanup only, not a
  Stage A retry.
- No image, scan evidence, registry tag/digest, provider artifact, ACR auth or
  publication, production deployment, database/service mutation, schema or
  business write, business-provider call, paid-AI/crawler call or public-traffic
  mutation occurred. The single GitHub source-fetch read is the only external
  data access performed by the executor. This attempt earns no credit.
  Readiness remains `19/29` internal and `19/38` public; the sole task remains
  `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

Next, version the smallest error-classified source-fetch recovery: only the
observed transient transport signature may receive a bounded clean-room retry;
non-transient failures must still stop immediately. Prove positive,
transient-then-success and non-transient fixtures offline, preserve every 5335
data-plane/build/image anchor, then require exact-HEAD push and PR CI before a
new bounded execution. The standing CTO authority covers that root-cause fix
and gated retry without another stepwise user confirmation. No blind retry is
authorized. The immediate success condition remains the exact 5335 local Admin
image plus 11 native evidence files; the next external hard condition remains
one immutable private ACR manifest digest.

### Item 20 Admin Stage A V3 bounded source-fetch recovery candidate (2026-08-03)

- The append-only V2 failure checkpoint is committed and pushed at
  `df9fb2b5167285aedb6fd618d9b819e082fd067e`. Its push CI
  `30779761306` and pull-request CI `30779762936` both passed run one / attempt
  one with `1765` total tests, `28` ambient skips, Quality, production
  readiness `137/137`, Docker Compose and artifact count zero. Neither run was
  rerun.
- V2 remains frozen historical evidence. Its successor is
  `deploy/production/admin_item20_stage_a_v3.sh`: `31,609` bytes, SHA-256
  `562cceb3f6b08da0b8e0723e4b636d664b6fc67cf622c6da3061601ee8b3f31a`.
  The only runtime change is source transport recovery. A retry is possible
  only when attempt one exits `128`, stdout is empty, and stderr—after removing
  only terminal CR from CRLF—contains exactly, and only, the two observed
  `curl 52 Empty reply from server` / `fatal: expected 'packfile'` lines.
  Every other exit, missing/extra/reordered line, stdout byte, embedded CR,
  timeout, TLS, authentication, repository/ref, permission or disk failure
  stops after one attempt.
- The maximum is two fetch attempts. Before each, the exact V3 source root is
  removed only after a fixed path/symlink safety gate, recreated at mode `0700`,
  initialized as a new Git repository and given only the fixed GitHub origin.
  Both transports are byte-identical: HTTP/1.1, `GIT_HTTP_MAX_REQUESTS=1`, Git
  `http.maxRequests=1`, no tags, depth one, exact release and a fixed two-second
  delay. No mirror, proxy, credential, source URL, TLS verification or build
  input changed; no third attempt is expressible.
- Offline acceptance passes Bash 3.2 syntax/runtime, `16` source-fetch fixture
  scenarios and focused tests `5/5`. Fixtures prove first-attempt success,
  exact transient then success, CRLF acceptance, embedded-CR rejection,
  exact transient twice then stop, near/non-transient one-attempt stop,
  clean-room removal of sentinel/FETCH_HEAD/partial objects and byte-identical
  transport arguments. One independent auditor found the initial all-CR
  normalization too broad; the main CTO narrowed it to terminal CR only, added
  the embedded-CR negative fixture, reran `5/5`, and the auditor returned PASS.
  A second independent audit also returned PASS.
- Data-plane immutability is independently proven: the checkout identity block
  is the same `316` bytes / SHA-256 `8e2fc83b…e238467`; model materialization
  through success cleanup is the same `12,143` bytes / SHA-256
  `bbb1975a…c0e3a8`; source/tree, Dockerfile, OCI/image tags, native script
  `639941a2…7d3a2`, projected Admin script `a2420972…df22c`, build/scan and all
  11-file acceptance predicates are unchanged.
- V3 external counts are all zero: builder start, file upload, command
  execution, source fetch, Docker build, ACR login/publication, production
  connection/deployment/database/service/public-traffic mutation. This
  preparation earns no credit; readiness remains `19/29` internal and `19/38`
  public, with sole task `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`.

Next, commit and push this exact V3 successor and require its exact-HEAD push
and pull-request CI to pass on first attempt. The standing CTO authorization
then permits exactly one V3 external execution on the existing isolated builder
without another stepwise confirmation. The immediate hard acceptance is the
exact 5335 local Admin image plus all 11 native evidence files; the following
hard acceptance is one immutable private ACR manifest digest. A terminal V3
failure authorizes no additional Stage A execution. Mirror/proxy/credential,
source change, expanded cost/scope, public traffic, schema/business writes,
V17 rerun, R17 and V18 remain outside authority.

### Item 20 Admin Stage A V3 exact-HEAD CI hermeticity correction (2026-08-03)

- V3 checkpoint `682a18d94322eaae38bcd341e3fd2d741e73580d` was pushed with a
  clean/upstream-equal worktree. Pull-request CI `30780947418` / job
  `91585310629` passed run one / attempt one with `1770` total tests, `28`
  ambient skips, Quality, production readiness `137/137`, Docker Compose and
  artifact count zero.
- Push CI `30780944104` / job `91585301363` was not rerun. It completed run one /
  attempt one with one failure in the ambient suite: the historical
  `test_one_hundred_distinct_admissions_are_bounded_and_make_no_provider_attempts`
  measured `2.383247239` seconds against an arbitrary shared-runner SQLite
  wall-clock limit of `2.0` seconds. It completed `1704` ambient tests with `28`
  skips, then correctly skipped later gates; artifact count remained zero.
- This is not an Admin V3 or production-capacity regression. The exact same
  HEAD passed PR CI; `682a18d` changes no admission, billing or database code;
  both direct-predecessor CIs passed; main local repetition passed `5/5` at
  about `0.22` seconds and an independent read-only audit passed `20/20` at
  `0.163`–`0.195` seconds. The test measured 100 serial local SQLite
  transactions on a shared runner, not 100 concurrent PostgreSQL admissions.
- The smallest correction removes only that non-hermetic wall-clock oracle and
  renames the test to state its actual contract. All deterministic assertions
  remain: 100/100 admitted, the five durable tables each contain exactly 100
  rows, provider attempts and model calls remain zero, and usage context is
  cleared. The `capacity_100_jobs` readiness item remains unverified and still
  requires its later managed concurrent admission/recovery/accounting proof;
  no latency SLA was relaxed or credited.
- The V3 executor remains byte-for-byte `31,609` bytes / SHA-256
  `562cceb3f6b08da0b8e0723e4b636d664b6fc67cf622c6da3061601ee8b3f31a`.
  Builder starts, uploads, Cloud Assistant commands, source fetches, builds,
  ACR and production actions for V3 remain zero. Readiness remains `19/29`
  internal and `19/38` public.

Next, commit and push this scheduler-hermetic test-only successor, require its
fresh exact-HEAD push and pull-request CI to pass, then execute V3 exactly once
under the existing standing authority. Do not rerun either `682a18d` CI.

### Item 20 Admin Stage A V3 unique external attempt failed closed (2026-08-03)

- Scheduler-hermetic successor `6951a003097599f8c82fb46cbdc84b316238ff05`
  is pushed and equals local/upstream HEAD. Push CI `30782246083` / job
  `91589070216` and pull-request CI `30782247926` / job `91589075091` both
  passed run one / attempt one at that exact HEAD. Each completed `1770`
  tests with `28` ambient skips, Quality, production readiness `137/137`,
  Docker Compose and artifact count zero. Neither run was rerun.
- The frozen V3 executor remains exactly `31,609` bytes / SHA-256
  `562cceb3f6b08da0b8e0723e4b636d664b6fc67cf622c6da3061601ee8b3f31a`.
  It was compressed into one `8,851`-byte archive with SHA-256
  `a36777a59d5bd364e6757e6abfa697b7e44517427e50386407f235e0c4201c8e`.
  Exactly one root-owned mode-`0600` file was sent to only the existing
  isolated builder; API-C and API-F were not selected. The exact command
  wrapper was independently SHA-checked locally, verified archive/executor
  owner, mode, size and SHA before execution, ran exactly one `bash`, and has
  an unconditional EXIT cleanup for both transferred files.
- Exactly one command named `noteai-admin-item20-stage-a-execute-v3` was run
  as root in immediate Shell mode with a `7200`-second timeout and ProcessTree
  termination. It ran `1m31s`, returned exit `128`, and was not retried or
  rerun. Transfer and decompression verification passed before the executor
  emitted `NOTEAI_ADMIN_STAGE_A_V3_TRANSFER_SHA=OK`.
- Source fetch attempt one then returned a new fail-closed signature:
  `fatal: unable to access` the fixed GitHub source with
  `Empty reply from server`. It did not contain the exact two-line
  `curl 52` / `expected 'packfile'` signature authorized for V3's single
  conditional clean-room retry, so no second fetch was attempted. The executor
  correctly reported `phase=source_fetch exit=128` after one attempt.
- Checkout, model materialization, Trivy DB download, Docker build/scan,
  native evidence, ACR login/publication/readback, Admin canary, production
  database/service mutation and public traffic were not reached. Failure
  cleanup proved both target images absent, the V3 task root absent and zero
  running containers. The verified wrapper EXIT trap removed the archive and
  executor; this file removal was not separately probed by another external
  command.
- The builder was explicitly returned to `已停止 / 节省停机模式`. At
  `2026-08-03T12:13:42+08:00`, its public IP field was `-` and only the
  bind/allocate actions remained, proving the temporary public IPv4 had been
  released. No new builder, image, registry object, production resource or
  provider artifact was created.
- The Secret-free checkpoint changes only Handoff, Risk, Readiness and its
  internal-readiness test. JSON parsing, `git diff --check`, the combined
  focused set `21/21`, the internal gate at `19/29` / `19/38` and the full
  production gate at `137/137` all pass. The two local transfer-only temporary
  files were hash-checked and deleted after their contracts were recorded.

The exact-one V3 external authority is consumed and V3 must not be rerun.
Stage B and Stage C remain blocked because there is no exact 5335 local Admin
image, no 11-file native evidence set and no immutable private ACR manifest
digest. Readiness therefore remains `19/29` internal and `19/38` public, latest
credit remains `api_f_current_release=VERIFIED`, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. In plain terms, the one missing hard
condition is: an authorized builder execution must actually receive the exact
5335 source and finish producing the Admin image plus its 11 proofs; without
that image, neither private publication nor production canary is admissible.

### Item 20 Admin Stage A V4 local-bundle recovery candidate (2026-08-03)

- The user explicitly authorized the main CTO to continue the bounded release
  chain autonomously. V3 remains terminal and may not be rerun. The successor
  is a new exact-one V4 execution after its own exact-HEAD push and pull-request
  CI; this does not authorize R17, V18, public traffic, schema/business writes,
  paid AI or crawler work.
- V4 removes the failed builder-to-GitHub source transport entirely. It requires
  the retained b55 repository at exact commit
  `b55f11882100e9ef919522540729e366a511f88f` / tree
  `ad3c949ae585ed529854d47a8599b7cb36a25ab2`, then imports one local-only
  incremental Git bundle containing the exact 11-commit successor ref. Two
  independent shared-bare views produced byte-identical `159,507`-byte bundles
  with SHA-256 `4e62b0627b4be73d7ccc14d821d34f01894340297729456f9f3e22b45a6e75b3`.
  A clean recipient seeded only with b55 verified the bundle and recovered exact
  HEAD `5335bdaed933b1f999b5f819c047ec50c11821ae`, tree
  `38e574e56406ba3380acb78edbe784508cc537cd`, parent
  `216be18bab10e5e0358e1f61e3f6b70bd207a8a8`, delta count `11`, full history
  count `197`, no remote, clean status and strict/full fsck.
- The current executor is
  `deploy/production/admin_item20_stage_a_v4.sh`, `30,980` bytes, SHA-256
  `2b811021305e81c3250c4b72f7707ac5f8d4c5fcd87ab0ae93e5c671086a8c75`.
  It accepts only the fixed root-owned bundle path and modes, has no HTTP source
  fetch, retry, mirror, proxy or credential path, and preserves the fixed 5335
  Dockerfile, model materialization, Admin-only native build/scan and 11-file
  evidence contract.
- Independent read-only review found one latent pre-build failure inherited from
  the unexecuted tail of V2/V3: the executor pre-created the evidence directory,
  while the fixed native evidence entry point requires it not to exist and
  creates it itself. V4 now creates only the task root; a regression assertion
  freezes both sides of that contract. Combined V2/V3/V4 focused tests pass
  `13/13`, Bash syntax and `git diff --check` pass. Final independent re-review
  returned PASS with no additional blocker; Readiness tests pass and production
  readiness remains `137/137`.
- No builder start, upload, Cloud Assistant command, source-network request,
  Docker build, ACR action, production connection, database/service write or
  public-traffic mutation has occurred for V4. This preparation adds no credit;
  readiness remains `19/29` internal and `19/38` public.

Next, commit and push only the reconciled V4 checkpoint. Require fresh exact-HEAD
push and pull-request CI before starting the existing builder. In that same
builder start, first perform the remaining read-only retained-b55 repository
preflight; only a passing preflight may admit the single V4 execution. The
immediate external acceptance condition is the exact 5335 Admin local image plus
all 11 native evidence files; no V4 rerun is implied by a failure.

### Item 20 Admin Stage A V4 unique terminal attempt (2026-08-03)

- Exact controller checkpoint
  `bc14c6aa6d129816a307b5ffa5241e6882e3e97c` passed its ordinary push CI
  `30788036947` / job `91605487114` and pull-request CI `30788039997` / job
  `91605496219`, both on attempt one. Each ran `1774` tests with `28` ambient
  skips, production readiness `137/137` and artifact zero. No CI rerun occurred.
- The existing builder was started once. Eight root-only file sends delivered
  one `168,179`-byte payload, SHA-256
  `911b0fefb3501d15d9f2070202e0db0bf4216df23aeb7eb96967c5b3cb9b70e4`,
  containing the fixed `30,980`-byte executor and `159,507`-byte Git bundle.
  The single `noteai-admin-item20-stage-a-execute-v4` command started at
  `2026-08-03T14:29:49+08:00`, terminated after `306` seconds with exit `1`,
  and was not retried or rerun.
- V4 emitted `NOTEAI_ADMIN_STAGE_A_V4_PREFLIGHT=PASS`. The retained b55
  repository, bundle, exact 5335 source identity, host and collision gates all
  passed. Source import, model materialization and tool preparation completed.
  Docker build, the 11-file native evidence set, ACR login/publication and all
  production actions were not reached.
- The terminal phase is `scanner_db_refresh`. Trivy logged the GHCR database
  download at `14:29:54` and its own `context deadline exceeded` at `14:34:54`.
  The executor supplied an outer GNU timeout of `1200` seconds but omitted
  Trivy's own `--timeout`, leaving Trivy 0.72 at its `5m0s` default. The outer
  timeout was therefore not reached. Because the invocation also used
  `--no-progress`, the retained log cannot distinguish a stalled transfer from
  a slow transfer and does **not** prove zero progress. The normalized outcome
  is `trivy_internal_default_timeout_progress_unknown`, not a proven GHCR
  outage or a proven zero-throughput download.
- Historical project evidence proves the same GHCR path was reachable: one
  bounded anonymous download completed within a `15m` upper bound into a
  task-owned cache and was followed by a successful offline scan. It does not
  retain enough throughput evidence to label that prior download slow. Those
  old database bytes were freshness-bound and are not automatically reusable
  now; the relevant lesson is to give a fresh download enough observable time,
  not to weaken freshness or scan gates.
- Failure cleanup reported target images absent, task root absent and running
  containers zero. The transfer cleanup marker was observed. The builder was
  returned to `已停止 / 节省停机模式` at
  `2026-08-03T14:40:22+08:00`, with its temporary public IPv4 released. New
  builder, image, native evidence, registry object, database connection/write,
  service mutation and public-traffic mutation counts are all zero.
- The Secret-free failure checkpoint changes only this Handoff, the risk
  register, internal readiness and its gate test. JSON parsing and
  `git diff --check` pass; the focused set passes `21/21`, internal readiness
  reports `19/29` / `19/38`, production readiness passes `137/137`, and the
  hash-recorded local transfer directory has been deleted.

The exact-one V4 authority is consumed and V4 must not be rerun. Readiness stays
`19/29` internal and `19/38` public; the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next hard acceptance condition is
still one exact 5335 Admin AMD64 local image plus all 11 native evidence files.
Any separately authorized successor must keep the existing `1200`-second outer
bound, set Trivy's internal timeout explicitly below it, and retain observable
download progress; only after Stage A succeeds may private ACR publication and
Stage C begin.

### Item 20 Admin Stage A V5 timeout-corrected successor candidate (2026-08-03)

- The V4 terminal correction checkpoint is pushed at
  `2cc6bf72258464a6754ee4594a721f64a247cdcd`; branch/upstream is `0/0`.
  Its exact HEAD has exactly two ordinary CI runs and no other workflow run:
  push `30792006004` / job `91617330241` and pull request `30792008479` /
  job `91617338071`. Both completed success on attempt one, each passing
  `1775` total tests with `28` ambient skips, Quality, production readiness
  `137/137` and Docker Compose; artifact count and rerun count are zero.
- The timeout-corrected successor is the direct executor
  `deploy/production/admin_item20_stage_a_v5.sh`, `31,071` bytes, SHA-256
  `4f2e6c116694347cbfb748ac486f1ab391f9e346df155b50d45c6f158db3a249`.
  It has a distinct V5 task/transfer/container namespace and success invocation,
  so terminal V4 is not rewritten or rerun.
- The scanner delta is intentionally small: require the Trivy help surface to
  expose `--timeout`, set the Trivy internal timeout explicitly to `15m` below
  the unchanged GNU outer bound of `1200` seconds, remove `--no-progress`, and
  stream while retaining the same scanner log through `tee`. The script already
  uses `set -Eeuo pipefail`, so a failed or timed-out Trivy process remains a
  failed pipeline and enters the existing cleanup trap.
- Exact source commit/tree/parent and Git bundle, Dockerfile, model
  materialization, build arguments, image tags, GHCR database repository,
  database freshness validation, offline scan, Admin projection and 11-file
  native evidence contract are unchanged. No ACR, database, service, public
  traffic, custom ledger, receipt or topology logic was added.
- Bash syntax, the offline self-test, exact V4-to-V5 delta assertion, timeout /
  progress contract and mutation-boundary tests pass `4/4`. Independent
  read-only re-review found the test had not pinned the historical V4 SHA; the
  main CTO added that one assertion without changing the executor. Final
  re-review is PASS with `P0=0 / P1=0 / P2=0`. The combined focused set passes
  `25/25`, JSON and diff checks pass, production readiness remains `137/137`,
  V5 external scope remains zero and the score stays `19/29` / `19/38`.

Under the main CTO's standing finite, bounded internal authority, V5 may execute
exactly once only after its own exact-HEAD push and pull-request CI pass. It has
no automatic retry. V4 remains permanently non-rerunnable. The immediate hard
acceptance condition remains a fresh Trivy database, exact 5335 Admin AMD64
local image and all 11 unchanged native evidence files; only success admits
private ACR Stage B and reversible Stage C.

### Item 20 Admin Stage A V5 unique terminal attempt (2026-08-03)

- The V5 candidate was committed and pushed at
  `cfa7ad336e01befccfd0e9a0dace19761d36fa2e`. Its exact-HEAD push CI
  `30794361508` / job `91624483011` and pull-request CI `30794364596` / job
  `91624493517` both completed success on attempt one. Each passed `1779`
  total tests with `28` ambient skips, Quality, production readiness `137/137`
  and Docker Compose; artifact and rerun counts were zero.
- The existing AMD64 builder was started once. Eight root-only Cloud Assistant
  file sends delivered one deterministic `168,202`-byte transfer payload,
  SHA-256
  `ba6115299a308d3791a65da42ac980be99fa96efdc315a336f03c2d9b3dfe805`,
  containing the unchanged `159,507`-byte Git bundle and the fixed V5
  executor. The final collision-safe transfer wrapper was `4,529` bytes,
  SHA-256
  `94f3f2253d437077058d94df8746faa96ed988347da7677078ad89576125e5a8`.
  The unique `noteai-admin-item20-stage-a-execute-v5` command was dispatched
  exactly once, ran for `905` seconds and exited `1`; automatic retry, manual
  retry and rerun counts are zero.
- V5 passed the retained-b55 repository, deterministic bundle, exact 5335
  source, host and collision gates. Source import, model materialization and
  tool preparation completed. The terminal phase was again
  `scanner_db_refresh`; Docker build, native evidence generation, private ACR,
  database, service and public-traffic actions were not reached.
- The complete retained Trivy progress stream corrects the initial truncated
  view: this was **not** a zero-progress or silent download. From
  `2026-08-03T16:28:58+08:00`, the official GHCR artifact target was
  `103.39 MiB`; by the `15m` absolute Trivy deadline it had reached
  `8.61 MiB / 8.33%`, with the final displayed rate about `9.89 KiB/s`.
  Trivy then emitted `context deadline exceeded`. At that observed rate a full
  transfer would take roughly three hours. The `15m` flag is a whole-command
  context budget, not an inactivity timer, so the exact failure is severe
  builder-to-GHCR blob throughput under the bounded Stage A window, not a
  stalled process and not a source/build defect.
- Trivy 0.72 does not retain the failed partial blob for resume. Its documented
  multi-repository fallback is not a reliable recovery after a slow body copy
  consumes the whole context deadline. The official alternative candidate is
  `public.ecr.aws/aquasecurity/trivy-db:2`; historical project evidence proves
  anonymous Public ECR reachability from this builder, but does not yet prove
  current DB blob throughput. No repository or executor change is authorized
  merely from endpoint reachability.
- Failure cleanup reported target images absent, task root absent and running
  containers zero. Transfer cleanup reported chunks zero and transfer root
  absent. The builder returned to stopped saving mode and its temporary public
  IPv4 was released. The two exact local transfer directories were moved out
  of `/private/tmp` to Trash and remain recoverable. Production database
  connections/writes, ACR logins/publications, service mutations and public
  traffic mutations are all zero.
- The V5 exact-one authority is consumed. V5 must not be rerun; V4/V17 remain
  non-rerunnable, and R17/V18 remain forbidden. This checkpoint uses only the
  existing Handoff, risk register, readiness manifest and readiness test; it
  adds no custom ledger, receipt or topology layer and adds no readiness credit.

Readiness remains `19/29` internal and `19/38` public; the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. In plain terms, the one missing hard
condition is now: a complete fresh `103.39 MiB` Trivy database must reach the
builder over an official route fast enough for bounded Stage A, after which the
unchanged exact 5335 Admin image and all 11 native evidence files must pass.
The next action is one bounded, download-only throughput probe against the
official Public ECR repository. It must not build an image, touch ACR or
production, or repeat V5. Only a demonstrated adequate blob path may justify
the minimal scanner-repository transport change.

### Item 20 official Public ECR probe and repository-only successor (2026-08-03)

- The authorized download-only probe ran exactly once against
  `public.ecr.aws/aquasecurity/trivy-db:2`: the full fresh `103.39 MiB`
  target completed in `26s`, Trivy/tee/command all returned `0`, and
  freshness validation passed. The unpacked DB was `1,223,847,936` bytes,
  SHA-256 `4f61ad6f60fe87055d2a9d43ab43e9da0f76a219f5aa6d59167e387cce2b5285`;
  metadata SHA-256 was
  `5f4a6c2cf1c0650a50f2c46d5c41849fd36ff37bc8b1b64268a1351ed7859d83`.
- Cleanup proved the probe root absent; Docker build, ACR and production
  actions were zero. The builder returned `已停止 / 节省停机模式` and released
  its temporary public IPv4. This closes the diagnosis as GHCR-route severe
  slowness; the official Public ECR route is adequate and the probe will not
  rerun.
- The repository-only successor
  `deploy/production/admin_item20_stage_a_public_ecr.sh` is `31,143` bytes,
  SHA-256 `a7cf0f48e23171aef3774f2f6db2620f90ccbb8d35b48dadeb0b039a5ff99259`.
  Relative to frozen V5, only its isolated namespace and DB repository change.
  Exact source/tree/bundle, Dockerfile, model materialization, image tags,
  build arguments, timeout/freshness/offline-scan and 11-file evidence
  contracts remain fixed. Its exact-delta test passes `4/4`; combined focused
  tests pass `29/29` and production readiness passes `137/137`. No workflow,
  custom ledger, receipt or topology layer was added.

Readiness remains `19/29` internal and `19/38` public; the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next require the successor's exact-HEAD
push/PR CI, then execute Stage A once and produce the exact 5335 Admin AMD64
local image plus all 11 unchanged native evidence files; continue to private
ACR and reversible Stage C after that acceptance.

### Item 20 Public ECR Stage A unique terminal attempt (2026-08-03)

- Checkpoint `c3de9ed3030b5d581d398ceb494d2f5677e6a753` passed
  exact-HEAD push run `30804908699` and pull-request run `30804912220`,
  both on attempt one.
- The unique Stage A execution ran `1298s` and exited `1` at
  `admin_build_scan`. Public ECR first delivered the full `103.39 MiB`
  Trivy target and the freshness gate passed; Dockerfile line 76 then failed
  on a pip/urllib3 read timeout from `files.pythonhosted.org`. This was not a
  Trivy stall and does not prove a permanent package-host outage.
- No Admin image or complete accepted 11-file evidence set was produced. Two
  pre-build base-index files existed temporarily and were removed with the task
  root. ACR, database, service and public-traffic mutations were zero. Target
  images, task and remote-transfer roots are absent, running containers are
  zero, the local transfer root is in recoverable Trash, and the builder is
  saving-stopped with its temporary public IPv4 released.
- The execution authority is consumed and the failed command will not rerun.
  Readiness remains `19/29` internal and `19/38` public, with no credit.
  The sole task remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`; its hard
  condition is the exact 5335 Admin AMD64 image plus the complete accepted
  11-file native evidence set.

The direct P2 recovery is now implemented without changing C17, Dockerfile or
`requirements-api.txt` bytes. V17 is a manual-only native workflow that
predownloads the official PyPI Linux/AMD64 wheelhouse with a 300-second
no-data timeout, four pip retries and at most two whole-download attempts. Its
configured hard-call envelope is 5700 seconds inside the 120-minute job, and
two distinct BuildKit builders each prove a no-cache, network-none import.
Stage A accepts the resulting ZIP only with an independently obtained GitHub
native artifact digest, safely extracts it, compares the exact Dockerfile and
requirements bytes, and uses one derived network-none/no-index pip RUN. The
old custom V17 recovery-plan check was removed from the production gate; no
new version, ledger, receipt, topology or gate was added.

Focused validation passes `12/12`, including the current repository gate
report, plus Bash/YAML-shell syntax and `git diff --check`. One accidentally
over-broad historical gate-test module was interrupted after 17 minutes while
still traversing frozen V12 Git evidence; it had no assertion failure and was
replaced by the targeted current-report test rather than restarted. No full
readiness gate was repeated during implementation. The single post-fix local
complete gate then passed `136/136` with zero failures; the prior custom V17
recovery-plan check is the removed 137th check. Next is exactly one push/PR CI
pair, then exactly one V17 `workflow_dispatch` within 120 minutes. Accept only
its authenticated run ID, fixed C17 SHA, native artifact digest and
fresh-builder success; never derive the expected digest from the downloaded
ZIP. Stage B/C remain closed until Stage A succeeds.

### Item 20 V17/Stage A closure and authorized Stage B scheme one (2026-08-04)

- V17 is terminal and accepted from four native facts: workflow run
  `30816912157`, fixed C17
  `7ee9a15425c38e8f0d5382cba488bd4a6ce92d6e`, artifact digest
  `sha256:742a01d2f4f1dc14cb6a9bf620591d1fc7288dbc64113ba0db9d223d6e6ee139`
  and successful fresh-builder network-none import. Dispatch count is one and
  rerun count is zero; R17/V18 remain forbidden.
- Stage A then completed exactly once and accepted release
  `5335bdaed933b1f999b5f819c047ec50c11821ae`, the Admin `linux/amd64` local
  image and all 11 native evidence files. Python installation used only the
  builder-local wheelhouse with BuildKit network-none and pip no-index. The
  temporary builder IAM was removed after the three input SHA checks; the
  three private objects and bucket were removed after success. Registry,
  service, database and public-traffic actions were zero.
- Fresh Stage B reads found `noteai/app` private, normal and tag-immutable,
  with `git-5335bda-amd64-admin-r1` absent and the public Registry endpoint
  disabled. Because the existing private endpoint permits one linked VPC and
  the isolated builder is elsewhere, the user explicitly authorized scheme
  one: snapshot/remove the production link, attach the isolated builder,
  publish once, remove the builder link and restore the exact production link.
- The minimal Admin-only publisher is
  `deploy/production/admin_item20_stage_b_private_acr.sh`, SHA-256
  `0342f9ebadda91a8131930170fbc9ee4d116b58286da1a3049b8f02bfb3fd624`.
  It allows one private push, keeps credentials off argv/env/logs, binds the
  Stage A image and 11-file evidence, compares push/descriptor/config digests
  and always removes task-local auth and its remote alias. Publisher tests pass
  `6/6`, combined focused tests pass `12/12`, and the only complete local
  readiness gate passes `136/136`; an independent read-only security review
  reports GO with no P0/P1. No cloud write or registry login/push has occurred
  in this checkpoint.

Readiness remains `19/29` internal and `19/38` public. The sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. Next, pass exactly one exact-HEAD
push/PR CI pair, execute the authorized swap and one push, obtain the native
control-plane digest, require all three registry digests plus the local config
identity to agree, and restore the exact production link and API-C/API-F health
before Stage B is accepted and Stage C opens.

### Item 20 Stage B scheme-one first invocation and clean recovery point (2026-08-04)

- Exact publisher checkpoint `ec5b81df466613fc7c3ff145026d7ef490f0efde`
  passed push run `30862102590` and pull-request run `30862105246`, both on
  attempt one. Each ran `1781` tests and passed production readiness `136/136`,
  Quality and Docker Compose; rerun count is zero.
- Scheme one was executed once: the frozen production ACR VPC link was removed,
  the isolated builder link reached `RUNNING`, and the public Registry endpoint
  remained disabled. The single publisher invocation exited in `preflight`
  with `push_started=0` and `published=0`; Docker login, tag, push and registry
  publication were not reached. Native `GetRepoTag` still reports the target
  tag absent.
- Failure recovery completed before diagnosis: the builder link was removed,
  the exact frozen production link was restored to `RUNNING`, and API-C/API-F
  live/ready returned `200` over loopback with private Registry DNS restored.
  The temporary builder role and custom policy were detached and deleted; a
  fresh control-plane read reports no builder role and both IAM objects absent.
- Secret-free diagnosis is complete. Correctly Base64-decoded grouped checks
  passed system, runtime state, image identity, 11 evidence files and evidence
  semantics (`5/5`). A same-ECS-role token-shape probe performed no login/tag/
  push and proved a nonempty length-12 username that matches the current
  publisher regex with no control or CR/LF characters; its temporary IAM was
  immediately removed. The six publisher evidence hash reads also pass `6/6`.
  Therefore no persistent username/code defect is proved and the publisher,
  image, dependencies, tests and gates remain unchanged. The historical
  preflight failure is classified as an unattributed transient, not permission
  to add a new control layer or repeat CI/full readiness.

Readiness remains `19/29` internal and `19/38` public, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The next hard condition is one recovery
execution that remains the first actual Registry push: require push,
manifest-descriptor and native control-plane digests to agree, require manifest
config to equal the accepted local image ID, then remove temporary IAM/link and
restore the exact production link plus API-C/API-F health before Stage C opens.

### Item 20 Stage B recovery dispatch blocked before execution (2026-08-04)

- The recovery wrapper was dispatched only after a fresh safe-state check and
  after the isolated builder link reached `RUNNING`. Alibaba Cloud terminated
  the remote task as `InstanceNotRunning` with `Repeats=0`: it has no start or
  finish time, exit code or output, so the wrapper and publisher did not execute
  and the actual Registry push count remains zero.
- Recovery was immediate and complete. The builder link was removed, the exact
  frozen production link was restored to `RUNNING`, the public Registry endpoint
  remains disabled, API-C/API-F live/ready are `200` over loopback/private DNS,
  and the temporary builder role and policy are absent. The one required native
  post-terminal tag read reports the target tag absent.
- A subsequent `StartInstance` call was rejected with `403 InstanceExpired`.
  A zero-cost read-only billing query confirms the account has no positive
  available balance. No paid action, new instance, code change, CI rerun, full
  readiness rerun, Docker login, tag or push was performed.

Readiness therefore remains `19/29` internal and `19/38` public. The sole task
remains `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The only external hard condition
is for the account owner to clear the Alibaba Cloud billing lock so the existing
on-demand builder can start. After it reaches stable `Running`, first inspect
shutdown scheduling and the local Stage A image/evidence; only then recreate the
temporary IAM/link and perform the still-first actual private Registry push.

### Item 20 Stage B post-top-up preflight found production runtime loss (2026-08-04)

- After the account owner replenished the account, `StartInstance` returned
  `200`; the existing builder reached stable `Running` with empty
  `AutoReleaseTime`. Read-only lifecycle checks found no systemd, cron or `at`
  shutdown schedule. Runtime state was clean, both accepted Stage A image tags
  still resolve to one `linux/amd64` Admin image, and no Docker auth, container,
  build/push process, database connection or remote Registry alias exists.
- The fresh evidence check isolated two metadata-only deviations:
  `admin-build-metadata.json` was `0644` instead of the publisher contract's
  `0600`, and the exact publisher was `0600` instead of executable `0700`.
  One bounded repair changed only those two modes; SHA-256 before/after was
  identical. The final combined preflight then passed lifecycle, runtime,
  image identity, all 11 evidence files, six evidence hash reads and the exact
  publisher SHA/offline self-test.
- The fresh cloud preflight passed: `noteai/app` is `PRIVATE`, `NORMAL` and
  tag-immutable; the fixed target tag remains absent; the public Registry
  endpoint remains disabled; the frozen production link is `RUNNING` with
  default access disabled; and both temporary IAM objects remain absent. No
  IAM or VPC-link write, Registry login, tag, push or production database/
  public-traffic action occurred.
- The mandatory production health baseline failed before any Stage B control
  mutation. API-C and API-F ECS instances are both `Running`, but each has no
  `8000`/`8001` listener, no running container, no installed or retained NoteAI
  systemd unit, and no live/ready response. Each node still retains `35` NoteAI
  images. This state therefore predates and blocks the proposed link swap; it
  was not caused by this Stage B attempt.
- A normal stop of the still-billable isolated builder was prepared, but
  Alibaba Cloud account security verification appeared before submission.
  No verification message was sent and `StopInstance` was not called. The
  builder is still `Running`; the verification page is handed back to the
  account owner.

Readiness remains `19/29` internal and `19/38` public, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. First complete the Alibaba Cloud account
security verification so the builder can be stopped. Continuing Stage B also
requires new explicit authority for the smallest production recovery that
recreates the missing API-C/API-F units from the already accepted images and
restores loopback live/ready `200`, without database or public-traffic changes.

### Item 20 builder stop verified; production runtime recovery remains blocked (2026-08-04)

- After the account owner completed Alibaba Cloud account security verification,
  the already-prepared `StopInstance` request returned success with one native
  request ID observed. No duplicate stop submission was made. A separate ECS
  console read then confirmed the existing builder is `已停止 / 普通停机模式`.
  This record does not claim saving-stop mode, public-IP release or zero billing.
- This stop phase created no IAM role or policy, changed no ACR VPC link, and
  performed no Registry login, tag, push, database, production-service or
  public-traffic action. The actual Registry push count therefore remains zero;
  no readiness credit is added.
- Stage A temporary IAM, its three private OSS objects and bucket were already
  removed after Stage A success. Stage B temporary IAM and the builder ACR link
  remain absent; the restored production ACR link is retained. The stopped
  builder and the accepted images retained on API-C/API-F are not cleanup
  targets.

Readiness remains `19/29` internal and `19/38` public, and the sole task remains
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001`. The account-verification stop blocker is
closed. The only next hard condition is explicit authority for the minimum
production recovery that recreates the missing API-C/API-F units from already
accepted images and restores loopback live/ready `200` on ports `8000`/`8001`,
with database and public-traffic changes remaining zero. Until that baseline is
restored, temporary Stage B IAM/link creation and the still-first actual private
Registry push remain closed.

The post-stop read-only recovery audit found no safe byte-reuse path. The three
accepted API-C/API-F systemd unit byte streams are absent from both current Git
refs and the two hosts; only their hashes, sizes and semantic contracts remain.
The tracked production Compose file is not an admissible substitute because its
API default bind, restart policy, resource bounds and container identities do
not match the accepted loopback-hardened services. Therefore the single missing
implementation condition is a minimal deterministic three-unit recovery
executor/template, offline-verified before use and limited to the already
accepted API image on API-C/API-F plus the accepted historical Admin image on
API-C. Creating or running that production-recovery path requires explicit
authority; no recovery code or production service mutation has been made.

### Minimal three-unit production recovery implementation checkpoint (2026-08-04)

- The account owner explicitly authorized one minimum recovery: API-C API plus
  historical Admin, and API-F API, using only accepted cached images and only
  `127.0.0.1:8000/8001`. Database writes, public traffic, ACR/IAM/link/push,
  builder startup and unrelated production resources remain forbidden.
- `deploy/production/recover_minimal_api_runtimes.sh` is the new semantic
  recovery executor, SHA-256
  `62645404c4734dfce3f3e57a4fd98ae8a25df336cc9d9a25c9552838cb0ec7a5`.
  It does not claim any lost historical unit SHA. It binds the accepted b55 API
  RepoDigest/config/revision and historical a635 Admin RepoDigest/config/
  revision, requires the exact API-C four-file or API-F three-file Secret
  topology, discovers exactly one seven-key OSS runtime file and validates
  `aliyun_oss`, regional internal HTTPS endpoint and exact normalized prefix
  without emitting values.
- Generated units use `--pull=never`, an exact recovery ownership label,
  Docker auto-remove/restart `no`, user `999:999`, read-only rootfs, cap-drop
  ALL, no-new-privileges, private IPC, bridge networking, accepted CPU/memory/
  PID/tmpfs/data-mount bounds, API-only scheduler disablement and direct
  `PGOPTIONS=-c default_transaction_read_only=on`. Host publishing is only
  `127.0.0.1:8000` and API-C Admin `127.0.0.1:8001`.
- Unit staging passes `systemd-analyze verify` before mutation. Installation is
  pre-registered, exact-hash-bound and no-overwrite; API-C's two units are one
  rollback group. Cleanup only removes exact labeled containers and exact-hash
  units, proves enable symlinks/temp units/containers/listeners absent and
  reports `CLEANUP_UNKNOWN` rather than false success.
- Focused tests pass `9/9`; offline unit rendering passes; the production
  rollback function passes seven injected boundaries plus a cleanup-failure
  fail-closed case. Two independent read-only reviews now report GO with no
  remaining P0/P1. `bash -n` and `git diff --check` pass.
- No production file, unit, container, listener, database, Registry, IAM, link,
  OSS or builder mutation has occurred in this implementation checkpoint.
  Readiness remains internal `19/29` and public `19/38`.

The exact task is now in execution: create a local checkpoint, send these exact
audited bytes once to each production API node, execute API-C and API-F once,
and require three rounds of live/ready `200`, exact runtime identity/hardening,
loopback-only listeners and zero prohibited actions before recording recovery.

### Three-unit production runtime baseline reconciled and accepted (2026-08-04)

- The first plain `SendFile` request was rejected by the Alibaba control plane
  with `FileSize.ExceedLimit` before an instance file was created. The same
  executor was gzip-compressed to `8,195` bytes; compressed SHA-256
  `cfde3919def7acff1d80f91e4f7eac41e89f256f8cd43316e5ae4baaf89a8801`
  and decompressed executor SHA-256
  `62645404c4734dfce3f3e57a4fd98ae8a25df336cc9d9a25c9552838cb0ec7a5`
  were both fixed before dispatch. Native file invocation
  `f-sz06sza0iodrg8w` completed `Success` on API-C with overwrite disabled.
- The exact-one API-C semantic executor invocation
  `t-sz06sza74dxwjk0` exited `1` in `host_preflight` with `missing_command`.
  A separate read-only diagnostic identified only host `jq` as missing. This
  phase precedes task-root creation and every unit/container/listener mutation;
  the uploaded gzip and task root are both absent. No automatic or manual
  recovery rerun was made and API-F executor invocation count is zero.
- The same read-only diagnostic found API-C's two NoteAI units already
  `loaded/active/enabled`, result `success`, with exactly the API and Admin
  containers present. Direct host hashes then reconciled them to the historical
  accepted byte anchors: API-C API
  `364a5e539b14a83d24ef9c1726ee3e14b988c398206b2711db5613b9e0a1fc77`
  and historical Admin
  `c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2`.
  API-F independently matched its accepted current unit SHA-256
  `23750496447ad6e31ad27b1461f1164bbf14c28296a0ac28be7e5886eb4e65c1`.
- This is a current-state acceptance, not an executor-installation claim. The
  new semantic template contains a recovery label and therefore cannot have
  produced those three historical SHA-256 byte identities. The actor or command
  that restored the accepted bytes is not attributed. Exact accepted unit bytes
  plus current systemd/container/image/health evidence are sufficient for the
  user's recovery outcome; custom recovery labels or new template mount/env
  spellings are not additional acceptance conditions.
- API-C read-only acceptance invocation `t-sz06szau74b8hz4` and API-F
  invocation `t-sz06szb2ykb45j4` both exited zero. API-C has exactly two managed
  containers and loopback listeners `127.0.0.1:8000/8001`; API-F has exactly one
  managed container and `127.0.0.1:8000`. All three use the previously accepted
  config/image digests and hardening. API-C API/Admin and API-F API each passed
  three fresh live/ready rounds with HTTP `200` and exact ready-check sets.
  Host established PostgreSQL connections were zero after each acceptance.
- Recovery-phase counts are database write commands `0`, public-network
  commands `0`, ACR/IAM/VPC-link actions `0`, Registry pushes `0`, builder
  starts `0`, service/unit/container/listener mutations by the attempted
  executor `0`, and one temporary compressed transfer file write with final
  residue `0`. Readiness remains internal `19/29` and public `19/38`; baseline
  restoration adds no duplicate credit.
- The direct production finding was fixed locally without adding a dependency
  or control layer: health JSON validation now uses the already accepted
  container's Python standard library through stdin, and host `jq` is no longer
  required. Current executor SHA-256 is
  `b8e6c977c8b0a27fc69b75297a2afe1d5fdaca89ef11d18b6603ac08cc68d4f3`;
  focused tests pass `11/11`, including exact API/Admin positive fixtures and
  malformed/wrong/extra/false negative fixtures. `bash -n`, offline render,
  seven-boundary rollback, cleanup-failure fail-closed and `git diff --check`
  pass; the complete production readiness gate also passes once. Because exact
  accepted runtimes are present, this fixed executor must not be dispatched to
  either node.
- Secret-free durable evidence is
  `deploy/production/evidence/production-minimal-runtime-baseline-reconciled-20260804.json`.
  The recovery precondition is closed. The sole task returns to the already
  authorized exact-one Stage B Scheme One private Admin publication; it must
  begin with a fresh read-only builder/repository/link/runtime preflight and
  must not repeat any accepted Stage A build, scan or recovery execution.

### Stage B first actual private push denied and cleanly closed (2026-08-04)

- The fresh builder, repository, private-link and production-runtime preflight
  passed. The exact accepted publisher and all 11 Stage A evidence files passed
  again without repeating Stage A, CI or the full readiness gate. The target
  immutable Admin tag was absent both before the control mutation and directly
  before publication.
- One `RepeatMode=Once` wrapper invoked the publisher once. STS token retrieval
  and private Registry login succeeded; the only `docker push` reached layer
  preparation and then returned repository authorization `denied`. The attempt
  ended with `push_started=1`, `published=0`, retry count zero, no manifest and
  the target tag still absent. The original exact-one attempt is consumed and
  may not be relabelled as unexecuted or replayed.
- Two independent read-only audits agree on the direct cause: the temporary RAM
  policy used the personal-style repository Resource shape and omitted the ACR
  Enterprise instance segment. The official Enterprise repository shape is
  `repository/<enterprise-instance-id>/<namespace>/<repository>`.
  `GetAuthorizationToken` remains scoped to `*`; `PullRepository` and
  `PushRepository` remain scoped only to the one exact instance-qualified
  repository. No wildcard repository permission, publisher, image, build,
  Stage A, test, CI or gate change is required.
- Failure cleanup completed before diagnosis: the builder link was removed,
  the exact production link restored, temporary role/policy detached and
  deleted, builder role binding/Docker auth/task roots/containers/push
  processes/database connections/remote alias returned to zero, and the
  builder is stopped in normal mode. API-C/API-F retain the exact accepted
  units and passed three fresh loopback live/ready `200` rounds after link
  restoration; the public Registry endpoint remains disabled.
- Secret-free evidence is
  `deploy/production/evidence/production-admin-stage-b-private-push-denied-clean-20260804.json`.
  Readiness remains internal `19/29` and public `19/38`; Stage C remains closed.

The standing CTO authority in this Handoff covers the finite, reversible,
private-only correction. A new attempt
`PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001_STAGE_B_CORRECTED_001` is therefore
self-authorized with an execution limit of one: rebuild only the ephemeral
least-privilege policy with the exact Enterprise instance-qualified repository
Resource, read it back, obtain fresh STS/Registry credentials, confirm the tag
remains absent, perform one private push, then require native digest agreement,
exact production-link restoration, cleanup and API-C/API-F non-regression.
This is not a retry of the consumed attempt and does not authorize any code,
image, Stage A, database, public endpoint, public traffic or production-runtime
change. Continue immediately without another product-owner pause.

### Corrected Stage B private publication and terminal cleanup accepted (2026-08-05)

- Corrected attempt
  `PROD-FIRST-LAUNCH-ADMIN-INTERNAL-001_STAGE_B_CORRECTED_001` used one
  temporary least-privilege role and policy whose repository Resource included
  the exact Enterprise ACR instance segment. The corrected wrapper changed one
  role-name literal only; publisher bytes remained the accepted 13,754-byte
  SHA-256 `0342f9ebadda91a8131930170fbc9ee4d116b58286da1a3049b8f02bfb3fd624`.
  Exact offline preflight invocation `t-sz06szkh5thlse8` exited zero.
- Native tag read `019FCD44-C001-554E-BDB0-D4FBE7E984AC` proved the immutable
  target absent immediately before publication. The one corrected publisher
  invocation `t-sz06szktwe51hj4` / command `c-sz06szktwdnk740` then ran once,
  exited zero and reported `PUSH_MANIFEST_PASS`; publisher count, Docker push
  count and published count are each one, with automatic and manual retry count
  zero.
- Push digest, manifest descriptor digest and native ACR tag digest all equal
  `sha256:d417718ff16ae9a456d2e099182661d320283c2755d3b3978eb82a5cee928c2a`.
  Manifest config, native ImageId and accepted local image config all equal
  `sha256:fa0e658cba59a0adda16f64efb9bdfe543f459d90fe35997bd39046eb7743bd4`.
  Native post-push `GetRepoTag` request
  `019FCD4D-7E99-5E38-A8FA-36077EE88871` returned `NORMAL` for the exact tag.
- The builder ACR link was removed and the exact production VPC/vSwitch link
  restored `RUNNING`, with `DefaultAccess=false` and the public Registry
  endpoint still disabled. The builder role was detached; the temporary policy
  and role were detached/deleted. Docker auth, publisher/task roots, remote
  alias, containers, push processes and database connections are absent on the
  builder; accepted local images remain.
- After link restoration, API-C invocation `t-sz06szo4d9qegao` and API-F
  invocation `t-sz06sznzne00dfk` each exited zero. The three exact accepted
  units/containers/listeners passed three fresh live/ready rounds with HTTP
  `200`, loopback-only listeners and zero established PostgreSQL connections.
  These checks made no service, unit, container, listener, database, ACR, IAM,
  link, public-traffic or builder-start mutation.
- After account verification, exact-ID `DescribeInstances` request
  `019FCF49-7F5C-5EE6-92DC-84A364522D5C` returned HTTP `200` and proved the
  existing builder was still `Running`. An earlier `StopInstance` request
  `019FCF45-0CA5-5130-8B03-F7581F063AA0` had carried a UI-inserted trailing
  newline, returned `404 InvalidInstanceId.NotFound` and changed no resource;
  it is not counted as a valid stop submission.
- The one valid graceful `StopInstance` request
  `019FCF4C-0AE1-511B-9F30-71359AB13864` returned HTTP `200` with `ForceStop`
  unset/false. Post-stop exact-ID `DescribeInstances` request
  `019FCF4D-63FF-5647-929E-7DA060C7955E` returned HTTP `200` and native state
  `Stopped`. The builder remains without a RAM role or builder ACR link; no
  second valid stop was submitted.
- Secret-free evidence is
  `deploy/production/evidence/production-admin-stage-b-private-publication-verified-20260804.json`.
  Terminal cleanup is complete. Readiness remains internal `19/29` and public
  `19/38` because Stage B adds no duplicate credit; Admin Stage C is now open.
  Continue directly with the private-digest canary, negative matrix, reversible
  promotion and non-regression acceptance without repeating Stage A, CI, the
  full readiness gate or the publication.

### Admin Stage C V3 implementation checkpoint (2026-08-05)

- A fresh read-only Cloud Assistant retrieval of the installed historical Admin
  unit completed through command `c-sz06t11wuzyyigw` / invocation
  `t-sz06t11wv0gfsw0`; the returned 1,263-byte stream matched accepted SHA-256
  `c299059d167eab0863639355a6485094e58e3dca6bcec7adbe9f78a3857a1ab2`.
  Two preceding Workbench form submissions were rejected in the control plane
  (`InvalidInstance.NotFound` and `InvalidRepeatMode.NotFound`) and did not reach
  the host or mutate a resource.
- The Stage C candidate is a deterministic 1,209-byte transform that replaces
  only the historical private manifest and removes the one direct
  `PGOPTIONS=-c default_transaction_read_only=on` token. Its SHA-256 is
  `101f8814d89736c2aa920f3107916b9b1ab53cabffdde0d69908285fd6d1fe8a`;
  the inverse transform reproduces the historical unit byte-for-byte.
- `deploy/production/admin_stagec_runtime.py` binds the accepted 5335 revision,
  private manifest `sha256:d417718ff16ae9a456d2e099182661d320283c2755d3b3978eb82a5cee928c2a`,
  config `sha256:fa0e658cba59a0adda16f64efb9bdfe543f459d90fe35997bd39046eb7743bd4`,
  fresh V3 namespace and exact candidate SHA. Source SHA-256 is
  `503aed01467a1571d5985982505471edf6e10cac07d9c3a28171dfec2046149a`;
  deterministic transport gzip SHA-256 is
  `bc8c5619a14365fab31e4ab06283b49deb487db7dd3c9d779677f35edf264f82`
  and decompresses to the same source SHA.
- The runtime keeps the previously audited bounded mode order, rollback,
  session and cleanup behavior. The only contract correction accepts the
  permitted empty/partial non-secret settings subset and requires the exact
  PostgreSQL 16 `system_settings` SELECT policy shape, including exact PUBLIC
  role, canonical qualifier and null `WITH CHECK`. Independent authority and
  contract audits report GO. Focused normal and optimized tests pass `6/6`,
  embedded sources compile and `git diff --check` passes.
- One optional narrow read-only policy query completed through command
  `c-sz06t13jte9lb0g` / invocation `t-sz06t13jter2lfk` with exit zero but empty
  output, so it is inconclusive and will not be retried. No production unit,
  container, listener, database row, Registry, IAM, link or builder state was
  changed by this implementation checkpoint. Readiness remains `19/29`
  internal and `19/38` public.

The exact task continues without another pause: perform one fresh API-C
preflight, transfer only the fixed V3 executor and candidate, pull only the
accepted private digest if absent, then execute the bounded canary, ACL/RLS
negative audit, one normal Admin login/logout session, reversible promotion,
one explicit restart, cleanup and independent API-C/API-F non-regression.

### Admin Stage C V3 failure truth and minimal V4 correction (2026-08-05)

- The accepted Admin image was initially absent from API-C. Exactly one
  short-lived Registry credential was issued. The first login reached a host
  pre-pull check that incorrectly required host `jq`, so it performed no pull;
  cleanup was exact. The same still-valid credential was reused without a new
  token, and exactly one real private `docker pull` cached the accepted
  manifest/config. Two independent read-only inspections verified the exact
  `linux/amd64` Admin identity. Aggregate Registry token/login/pull counts are
  `1/2/1`; automatic retry, push, tag, IAM, link and builder-start counts are
  zero, and auth/key/cipher residue is zero.
- V3 `canary-start`, `canary-validate` and `acl-audit` passed. Its single
  `session-open` then failed with `subprocess_failed` after one normal session
  INSERT. Failure cleanup deleted that same task session, leaving residue zero
  and `CONNECTED_UNKNOWN=0`. The one V3 `abort` restored the historical Admin,
  removed canary/listener/token residue and correctly kept release acceptance
  false because the side-effect baseline had not completed. V3 was not rerun
  and its failed result was not rewritten.
- The deterministic cause was a `dict_row` query result accessed as positional
  index `[0]` in `side_effect_snapshot`. The only data-path correction aliases
  the value as `xid` and reads `["xid"]`; V4 changes only the fresh task/canary
  namespace needed to preserve V3 result immutability. Candidate unit, image,
  database contract, hardening and production resource semantics are
  unchanged. Independent read-only review returned GO.
- V4 runtime SHA-256 is
  `f8ccd0cc2bd1c939e23986719c7c64c663183f2e4fb8ee856ebf3215d8ae2356`;
  deterministic transport gzip is
  `24a40d73a07fbad669598e0a859c17da60a04946f7901ea2c849cb6a8fc6ffac`.
  Focused normal and optimized tests pass `8/8`; Python compile and diff check
  pass. No V5/V18, workflow, template, ledger, receipt or topology layer was
  added.

### Admin current release accepted; readiness 20/29 (2026-08-05)

- Fresh V4 preflight proved the historical Admin active/enabled/healthy, the
  V4 namespace/canary/`18001` listener absent and the exact target image cached.
  The rollback unit, candidate unit and runtime transport were each verified on
  API-C by their fixed SHA and root-only mode before execution.
- The nine modes executed once in the fixed order
  `canary-start -> canary-validate -> acl-audit -> session-open -> promote ->
  formal-validate -> explicit-restart -> session-close -> cleanup`. Every mode
  exited zero with `PASS`, `Repeats=1`, automatic retry zero and
  `CONNECTED_UNKNOWN=0`.
- Canary creation/start/restart was `1/1/0`; canary and formal validation each
  completed three live/ready `200` rounds against the exact target image and
  loopback ports. ACL audit covered `56` tables / `392` table checks, `2,432`
  column checks and `5` sequences / `15` sequence checks; all mismatch and
  grantable counts were zero, the transaction rolled back and XID remained
  unassigned.
- The normal Admin session completed one login and exactly one controlled
  session INSERT. Eight exact side-effect observation rounds found zero
  business tuple, catalog, process, provider or object effect. Promotion
  installed candidate unit SHA
  `101f8814d89736c2aa920f3107916b9b1ab53cabffdde0d69908285fd6d1fe8a`
  with one service restart and no rollback. One explicit restart changed the
  container identity and again passed three health rounds. Logout completed one
  matching DELETE; both old-token replays returned `403`, and final
  session/token residue is zero.
- Cleanup removed the single canary and left canary container/listener/data,
  token, database business writes, provider/object calls and public-traffic
  changes at zero. Independent read-only postchecks bound API-C API, target
  Admin and API-F API to their exact unit/image identities, active/enabled
  systemd state, restart zero, three fresh live/ready rounds and loopback-only
  listeners. A final exact cleanup removed only the V3/V4 temporary Stage C
  roots; both runtime roots, both canaries and `18001` are absent while API-C
  API/Admin remain healthy.
- Secret-free final evidence is
  `deploy/production/evidence/production-admin-current-release-verified-20260805.json`;
  its offline fail-closed verifier is
  `tools/verify_admin_current_release_evidence.py`. The evidence binds the
  accepted Stage B, API-C, API-F and recovery baseline file hashes and records
  native invocation IDs without credentials, tokens, DSNs or user data.
- Focused verifier tests pass `6/6`; Admin runtime tests pass normal/optimized
  `8/8`; combined Admin evidence/internal readiness tests pass `23/23`.
  Current manifest validation reports repository/isolated `12/12`, internal
  production `20/29 = 69%` and complete public launch `20/38 = 53%`. Admin
  current release is `VERIFIED`; public launch and full-system rollback remain
  unverified.
- Branch is `codex/quality-stabilization-real-chain`, HEAD before the new local
  checkpoint is `a31a29d9461a43182169d724ede03f28cb9eef0a`, upstream divergence
  `ahead 10 / behind 0`. Current changed files are the minimal V4 runtime/test,
  final Admin evidence/verifier/test, readiness manifest and its internal/
  production gate integrations/tests, plus this Handoff and the risk register.
  Do not push merely to repeat CI; create one local checkpoint after the single
  complete readiness gate passes.
- The already-running `tests.test_production_readiness_gate` process completed
  after about 64 minutes, but its detached wrapper no longer retained an exit
  status; it is therefore not counted as a passing result and was not rerun.
  The two exact Admin/readiness fail-closed tests then passed `2/2` in 75.823s.
  The single formal repository gate evaluated `137` checks and returned
  `136/137`; its only failure was the Secret scanner treating two Python code
  expressions in the immutable V4 runtime as literal Secret assignments.
- The production-bound runtime was restored byte-for-byte and again hashes to
  `f8ccd0cc2bd1c939e23986719c7c64c663183f2e4fb8ee856ebf3215d8ae2356`.
  The existing scanner now excludes only uppercase variable-reference/path
  expressions and raw/bytes source prefixes; direct literal values remain
  fail-closed and have explicit negative tests. The exact failed check then
  passed, scanner/Admin fail-closed tests passed `2/2`, Admin runtime tests
  passed normal/optimized `8/8` each, the final evidence verifier passed and
  the internal gate reports `20/29`. No second full gate was run merely to
  repeat the other `136` unchanged successful checks.
- A read-only Alibaba ECS inventory/price check after interactive verification
  found historical `ecs.c9i.xlarge` available in zone C but closed in zone F.
  The current common X86 equivalent `ecs.c9a.xlarge` is `WithStock` in C/F and
  is natively reported as `4 vCPU / 8 GiB / X86`; native monthly quotes are
  CNY `391.72` per zone, CNY `783.44` total. No order, instance, builder,
  database transaction, role, Secret, network or production resource changed.

The sole task now advances to
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. Begin with a fresh read-only audit
of the existing durable publisher/dispatcher/worker contract, accepted image,
dedicated role/Secret topology and production runtime baseline. Do not treat
this readiness checkpoint as a stop point, and do not mutate production until
the existing contract establishes the exact bounded execution plan and its
standing authority.

### Durable AI PostgreSQL-native source checkpoint (2026-08-05)

- Alibaba interactive verification is restored. A read-only
  `DescribeInstanceTypes` call for `ecs.c9a.xlarge` in Shenzhen returned native
  HTTP `200` / `调用成功`; no order, instance, IAM, link, database or service
  mutation occurred.
- The sole task remains `PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`; readiness
  remains internal `20/29` and public `20/38`. PostgreSQL is authoritative:
  dispatcher delivery and UUID-only `NOTIFY` commit together, Worker claims
  only delivered rows and lost notifications recover by polling. Exact
  acceptance dispatch does not touch unrelated Outbox rows or fairness state.
- Fixed migration `0017` SHA-256 is
  `a73cbefd853cefe7b56c42bed2c5a7f0ba1626e57755c6f9464629b49c42cbbe`.
  Its minimal owner-bound executor validates the native 0001-0016 ledger,
  applies only 0017 and one native ledger row, and compares the existing
  Dispatcher/Worker role snapshot before/after. It no longer rejects the
  legitimate Worker LOGIN or repeats the incremental ACL. Historical V5
  sources and ACL SHA remain unchanged.
- Four native systemd templates separate Dispatcher DB-only and Worker
  DB/private-storage inputs, use digest-only images, expose no ports, set
  `Restart=no`, and bound exact acceptance at 120/360 seconds. Formal units
  remain default suspended. Dispatcher storage env is rejected before model
  artifact loading; internal acceptance requires a canonical exact operation
  and once-only command.
- Independent read-only review found and the main CTO fixed four concrete
  acceptance blockers: the Worker LOGIN false assumption, duplicate ACL
  execution, takeover event count (`claimed=1`, `lease_taken_over=1`), and two
  PostgreSQL JOIN locks that incorrectly included the read-only admission
  alias. The final controller now derives refund, usage, payload deletion,
  admission/idempotency removal, deletion-request state and retained
  pseudonymous audit from exact database rows instead of hardcoded claims.
- Focused Durable AI/API/PostgreSQL-source/schema/env/runtime/account-deletion
  and exact entrypoint tests pass `223/223` with `10` approved real-PostgreSQL
  skips. Python compile, shell syntax, production Compose parse and
  `git diff --check` pass. One mistakenly broad local unittest invocation was
  interrupted after it was found to call the complete `build_report()` more
  than once; exit `130` is not counted as a test result and no formal full gate
  has been claimed.
- No production connection, transaction, row, object, role, Secret, unit,
  container, image, Registry, IAM, network or provider was changed. No custom
  ledger/receipt/topology or V18 was added. The next atomic sequence is one
  source checkpoint, one push to the existing draft PR (thereby one push/PR
  dual CI), one complete readiness gate and one native AI Worker image-evidence
  run. Production 0017, Dispatcher LOGIN/Secret, instance purchase/start and
  cross-host synthetic writes remain separately bounded production actions.

### Durable AI first dual-CI failure repair checkpoint (2026-08-05)

- Source checkpoint `80be069902c4ebb9e9931c96667227c9cbfd40b4` was pushed
  exactly once to the existing Draft PR #2. GitHub created push run
  `30978847303` and pull-request run `30978849570`; both are terminal failure
  on the same SHA and were not rerun. Each completed `1790` tests with
  `4 failures / 60 errors / 33 skipped` in the Unit tests step.
- Native logs and three independent read-only reviews reduced the output to
  three repository-only causes. Historical 0001-0016 auditors globbed the new
  independent 0017 migration and failed `source_set` (all 60 errors plus one
  protected-input test cascade); two dispatcher tests inherited blank private
  storage keys loaded from `.env.example`; and three test placeholder names
  ending in `_TOKEN` triggered the existing Secret scanner. The two CI runs
  were otherwise identical, so this was not runner or network flakiness.
- The minimal local repair keeps 0017, its executor, V5 execution semantics,
  ACL SQL, production dispatcher storage boundary and Secret scanner rules
  unchanged. Frozen auditors now select and strictly require exactly one each
  of 0001-0016 while permitting independently gated later migrations; only
  their bound runner hashes changed. The two dispatcher tests explicitly mock
  the orthogonal no-storage precondition, and all three test constants now use
  `_PLACEHOLDER` names.
- Direct regression groups pass `33/33` historical source/auditor tests and
  `7/7` dispatcher/runtime-unit tests. Database collector/schema-role runner
  coverage passes `28/28` with `3` approved real-PostgreSQL skips, and internal
  readiness passes `17/17`. Python compile, five runner shell syntax checks,
  runner-source hash parity, git hygiene/Secret scan and `git diff --check`
  pass. A complete readiness test started concurrently and completed, but its
  wrapper did not retain an exit status; it is not counted and will not replace
  the single formal gate after replacement dual CI.
- A separate read-only workflow audit found a GitHub-native hard condition:
  remote `main` contains only `ci.yml`, while
  `native-release-evidence.yml` exists only on this branch. GitHub will not
  accept its `workflow_dispatch` until that workflow exists on the default
  branch. No exploratory dispatch was sent. Once that condition is authorized
  and satisfied, the sole valid input is the exact replacement-repair commit
  that passes both CI runs, with scope `five`; artifact digest is evidence-
  bundle identity and must not be represented as a Registry manifest digest.
- Readiness remains internal `20/29`, public `20/38`. No production, Alibaba,
  Registry, database, service, IAM, Secret, Provider or public-traffic mutation
  occurred. Next: checkpoint and push this direct repair once, observe only its
  replacement push/PR runs, then execute one formal readiness gate. Do not
  dispatch native evidence or modify `main` without resolving the default-
  branch workflow hard condition.

### Durable AI replacement CI and formal gate closure (2026-08-05)

- Remote PR head is `0149888d16468c8e8ea055e62ce0aa5d56a28971`.
  Replacement push run `30980871956` and pull-request run `30980874916`
  both completed `success`, attempt `1`, on that exact SHA; their jobs are
  `92224803613` and `92224812813`. All native steps, including Unit tests,
  quality gate, production readiness gate and Compose validation, passed.
- The one reserved local formal command
  `.venv/bin/python tools/production_readiness_gate.py` completed `PASS` with
  `137/137` checks and zero failures. It was not repeated. The earlier failed
  run IDs remain terminal and were not rerun.
- Draft PR #2 is GitHub `MERGEABLE/CLEAN`, but it is still Draft and is `291`
  commits ahead of current `main`. Default-branch protection requires the
  `test` check, resolved conversations and linear history; force pushes and
  merge commits are disabled. Squash and rebase merges are enabled.
- `main` still contains only `.github/workflows/ci.yml`; there is no
  `workflow_dispatch` run for `0149888...8971`. The two historical native
  evidence runs target other SHAs and cannot be reused. No dispatch was tried.
- Readiness therefore remains internal `20/29`, public `20/38`. The sole task
  remains `PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The only immediate hard
  condition is a release-governance decision that makes the already-reviewed
  `native-release-evidence.yml` exist on protected `main` while preserving the
  dual-CI source SHA. The smallest-scope option is a dedicated workflow-only
  protected PR from `main`; merging Draft PR #2 would instead publish all 291
  accumulated commits. Either action changes the default branch and is not
  inferred from CI authorization.
- This is a Secret-free local evidence checkpoint only and must not be pushed
  merely to trigger more CI. No production, Alibaba, Registry, database,
  service, IAM, Secret, Provider or public-traffic mutation occurred.

### Durable AI native-workflow bootstrap closure (2026-08-05)

- The product owner explicitly authorized the smallest protected bootstrap PR.
  Three independent read-only audits agreed that remote `main` was
  `5afc1717f09618de7ed7a191133a087d83317e39`, source remained fixed at
  `0149888d16468c8e8ea055e62ce0aa5d56a28971`, and no bootstrap branch, PR or
  workflow dispatch for that source SHA existed.
- A fresh temporary worktree from `origin/main` added exactly one file:
  `.github/workflows/native-release-evidence.yml`. Its SHA-256 is the frozen
  source identity `6b8bacf383f1ee9b984b571d28a8a69437b8f69c949cc68a17691351180e430f`;
  the PR contained one commit, `334` additions and zero deletions. The
  bootstrap branch push produced zero workflow runs.
- Ready PR #5 passed its sole required `test` check in GitHub-native run
  `31011143306`, job `92323340988`, attempt `1`. It had zero review threads,
  was `MERGEABLE/CLEAN`, and was squash-merged through protected `main` as
  `e8fa2837566ced8fe55bdf686ade0675952b8fa3`. The unavoidable `main` push CI
  then passed in run `31011334233`, job `92323999754`, attempt `1`.
- GitHub now registers workflow ID `320926028` on the default branch, and its
  default-branch bytes retain the exact frozen SHA-256 above. The remote and
  local bootstrap branches, clean temporary worktree and two temporary text
  files were removed after merge; the original source worktree and local
  checkpoint were not changed by that cleanup.
- No native evidence dispatch has yet been submitted for `0149888...8971`.
  Readiness remains internal `20/29` and public `20/38`; the immediate next
  action is the exact-one `workflow_dispatch` with `release_scope=five`, not a
  new request commit or V18. Bootstrap changed no application source, build
  contents, image, production service, Alibaba resource, IAM, Registry,
  database, provider or public traffic.

### Durable AI exact-one native run security finding (2026-08-05)

- The sole authorized dispatch was submitted exactly once for source
  `0149888d16468c8e8ea055e62ce0aa5d56a28971` and scope `five`. GitHub-native
  run `31011637924`, job `92325049605`, workflow ID `320926028`, attempt `1`
  completed `failure`; the exact-SHA dispatch inventory contains only this
  run and it will not be rerun.
- Release-control parsing, exact-source checkout, immutable-source checks,
  checksum-pinned scanner installation, all five native builds, inspection,
  inventory/scanning and evidence upload passed. Only the final raw
  zero-Critical/High assertion failed after `summary.json.passed=false`.
  This was not a timeout, 502/504, polling difference or download stall.
- GitHub artifact `8932806283`, named
  `native-amd64-release-evidence-0149888d16468c8e8ea055e62ce0aa5d56a28971`,
  has archive digest
  `sha256:ed819cbc85228770c1ca9d3923b8e1a3a624412c2e6b03da3ae1983279ed351b`,
  contains the exact `43` regular evidence files and expires on 2026-08-19.
  The archive digest is not an OCI Registry manifest digest.
- Every role has identical normalized vulnerability rows: `4 Critical / 21
  High`, zero Secrets, zero browser components and zero forbidden OS packages.
  The canonical Debian 13.6 base contributes the existing `4 Critical / 19
  High` across twelve unique CVEs with no fixed Debian version; project policy
  keeps those raw reports unsuppressed and requires an exact-product
  CycloneDX VEX. The two newly actionable High findings are
  `CVE-2026-69247` and `CVE-2026-69249` in `cryptography 48.0.1`; covering both
  requires upstream `50.0.0`.
- The artifact contains no image tar or OCI layout and all role
  `RepoDigests` are empty. AI Worker identity
  `sha256:57ecea43bc0cb4c8a700670ce7aa7b6bd24004d5ebb4587da31256028a122c5e`
  is a runner-local image/config identity only; it is not a deployable
  Registry manifest or fresh-builder import proof.
- A source-unchanged isolated compatibility probe loaded public
  `cryptography 50.0.0` ahead of the local environment and passed the Adapay
  plus managed-Secret focused suites `42/42` with one approved environment
  skip. No `.venv`, source, image, Registry, production or Secret changed.
  The next repair is the smallest dependency/SBOM-gate update to `50.0.0`,
  followed by focused verification and one replacement source CI cycle; it
  must not weaken raw scanning or add V18/custom ledger/receipt/topology.
- Readiness remains internal `20/29` and public `20/38`. Production 0017,
  Dispatcher LOGIN/Secret, an accepted private AI Worker manifest and managed
  cross-host takeover remain open and no production/cloud mutation occurred.

### Durable AI cryptography successor repair prepared (2026-08-05)

- The actionable native finding is repaired at the dependency contract:
  `model/requirements-api.txt` now pins `cryptography 50.0.0`. No application,
  payment, Secret-envelope, database, image-base, provider or production
  runtime behavior was changed.
- Historical evidence remains immutable. The original
  `scripts/ci/native_release_evidence.sh` still has exact SHA-256
  `639941a22478cf83e1463babb9b838f8dbf951c4fcdcb8f0b4674a65bee7d3a2`
  and retains its v1/48.0.1 contract. The successor runner is the single new
  `scripts/ci/native_release_evidence_v2.sh`, SHA-256
  `35f59b31cd7038160c23746909aea6e325251d914cb91b645f65cf8bc7d509a9`;
  it requires exactly one `cryptography 50.0.0` component and emits the
  self-describing v2 fields `cryptography_version` and
  `cryptography_components` while preserving unsuppressed raw findings.
- The source workflow now invokes only the v2 runner and is manual-only. Its
  SHA-256 is
  `3b3efb3235c700ecb4f4ff91978c7a49d83a8208e000e14eae7bff824dcf3aa1`.
  Removing its legacy push trigger prevents a repair push from consuming a
  native build before replacement dual CI is accepted; permissions remain
  `contents: read`, and Registry, deployment, database, service, Secret and
  public-traffic paths remain absent.
- Focused verification passed: isolated 50.0.0 Adapay/managed-Secret suites
  `42/42` with one approved environment skip; native workflow/VEX/current
  dependency tests `17/17`; frozen Admin Stage-A v2/v3/v4/v5/public-ECR tests
  `23/23`; both runner shell syntax, Python compilation and diff checks pass.
  One ad-hoc readiness probe initially asserted the wrong result key
  (`status` instead of `passed`); its returned product value was already
  `passed=true`, and the corrected single probe passed without a product
  change or widened test run.
- Changed implementation surface is limited to the dependency pin, manual
  native workflow, successor runner, production dependency description,
  readiness predicate and directly coupled tests. No historical VEX,
  evidence, Stage-A executor, image, production resource or custom
  ledger/receipt/topology was modified.
- Readiness remains internal `20/29` and public `20/38`. The next acceptance
  condition is one source checkpoint push, its single replacement push/PR CI
  cycle, and one complete readiness gate. Only after those pass may one
  manual successor native run be submitted for the new exact SHA; run
  `31011637924` remains permanently no-rerun.

### Cryptography repair first-push CI diagnosis (2026-08-05)

- Repair checkpoint `2c490249b6f4caf9548f18b890704072f3af8c3b` was pushed
  once. GitHub CI run `31013738621`, job `92332268654`, attempt `1`, completed
  `failure` after `1791` tests with exactly one failure and `33` skips.
  Installation, LFS, Python/shell syntax and model-artifact checks passed;
  quality, readiness and Compose were skipped after the unit-test failure.
- The sole failure was
  `test_c17_release_and_dependency_inputs_stay_immutable`. It compared the
  moving HEAD `model/requirements-api.txt` to the fixed historical 5335/C17
  hash, so the intentional 50.0.0 pin produced current hash
  `7a6adb458c44521dae7aa9cfa7fc36ae0f5ff0603e810901d7ce6da2e3ae4f6a`
  instead of historical hash
  `0231c534fc2ca1ca503f5b29e19c503be995672cf20afd8203e207ffc8354ea9`.
  This is a test-source binding defect, not a cryptography compatibility,
  runtime, download or timeout failure.
- The minimal correction changes only that test to read the fixed
  `5335bdaed933b1f999b5f819c047ec50c11821ae` Dockerfile and requirements
  blobs through Git, matching the already-fixed V17 workflow semantics. C17,
  its dependency hash, workflow, artifact, image and all historical evidence
  remain unchanged. The focused V17 module passes `5/5`, Python compilation
  and diff checks pass.
- The exact repair SHA produced zero native workflow runs. PR #2 did not
  produce a pull-request CI because bootstrap PR #5 independently added the
  same workflow on `main`, leaving one add/add conflict once the source copy
  changed. A read-only three-way merge audit found exactly that one workflow
  conflict and no application, dependency or production-file conflict.
- Next, record this diagnosis, merge current protected `origin/main` into the
  source branch without force-push, resolve the one workflow conflict to the
  reviewed manual-only v2 source bytes, and push one final checkpoint. That
  final SHA must receive both push and PR CI before the single complete gate
  and exact-one manual successor native run. Readiness remains `20/29`.

### Protected-main workflow ancestry conflict closed (2026-08-05)

- Current protected `origin/main` was re-fetched and fixed at
  `e8fa2837566ced8fe55bdf686ade0675952b8fa3`. A normal non-force merge into
  the source branch produced exactly the pre-audited add/add conflict in
  `.github/workflows/native-release-evidence.yml`; the unmerged-path count was
  one and no other path changed or conflicted.
- The conflict was resolved to the reviewed source bytes: manual
  `workflow_dispatch` only and `native_release_evidence_v2.sh`. The resolved
  workflow SHA-256 remains
  `3b3efb3235c700ecb4f4ff91978c7a49d83a8208e000e14eae7bff824dcf3aa1`;
  old push activation and the legacy runner were not reintroduced.
- Merge commit `cfc838b040e2582eca199f5c4d7dea94efa97f50` has exact parents
  `92d01eadc50809774c399f97b99cdb72f4bd194f` and
  `e8fa2837566ced8fe55bdf686ade0675952b8fa3`. Its tree
  `612ebc969df8af2b6830d3c9d63b1c1dc9b183f8` is byte-identical to its first
  parent tree, proving the merge changed ancestry only. Protected main is now
  an ancestor of the source branch.
- Post-resolution workflow/V17 tests pass `13/13`; both native runner shell
  checks pass; the worktree is clean. No native run, Registry, image,
  production, database, Alibaba, Secret, provider or public-traffic action
  occurred.
- Readiness remains internal `20/29` and public `20/38`. The next exact
  condition is one final source push and one push/PR CI pair on its resulting
  exact SHA, with native run count still zero; then execute one complete
  readiness gate before the single manual successor native run.

### Cryptography successor dual-CI and formal-gate closure (2026-08-05)

- Final pushed source SHA is
  `cad5ce35664f617c6e19f90a6159285ddf975594`; local and upstream branches
  were equal and clean at dispatch inventory time. It contains the 50.0.0
  pin, frozen legacy runner, manual-only v2 successor runner, V17 historical
  blob correction and protected-main ancestry merge.
- GitHub push CI run `31015535682`, job `92338496582`, and PR CI run
  `31015538898`, job `92338506796`, both completed `success` on exact
  `cad5ce3...5594`, attempt `1`. Each passed `1857` tests
  (`1791 + 10 + 1 + 12 + 22 + 21`) with `33` approved skips and zero
  failures, the quality contract, production readiness `137/137` and Docker
  Compose validation.
- One separately executed formal local readiness gate then passed exactly
  `137/137`, failed `0`. It was run once after dual CI; no duplicate full
  local gate was run before or after it.
- Native workflow ID `320926028` has zero runs for the final SHA. The failed
  predecessor CI `31013738621` and predecessor native run `31011637924`
  remain immutable attempt-1 terminal records and were not rerun.
- No image, artifact, Registry, builder, Alibaba, production, database,
  Secret, provider or public-traffic mutation occurred in this closure.
  Readiness remains internal `20/29` and public `20/38`.
- The next and only action is one manual `workflow_dispatch` of
  `native-release-evidence.yml`, ref and `release_commit` both fixed to
  `cad5ce35664f617c6e19f90a6159285ddf975594`, scope `five`. Acceptance is
  build/inspect/SBOM/scan/upload success, exact 43-file artifact, one
  cryptography 50.0.0 component per role, zero cryptography CVEs and the
  expected unsuppressed canonical Debian `4 Critical / 19 High`; final raw
  gate failure alone is expected and is never a rerun reason.

### Durable AI cad5ce3 native successor and VEX closure (2026-08-05)

- The exact-SHA preflight found zero prior native dispatches. The approved
  `workflow_dispatch` was then submitted exactly once for
  `cad5ce35664f617c6e19f90a6159285ddf975594`, scope `five`. Run
  `31017791512`, job `92346323999`, attempt `1` is terminal and will never be
  rerun. Source checkout, all five AMD64 builds, inspection, inventory, SBOM,
  vulnerability/Secret scans and artifact upload passed; only the final raw
  zero-Critical/High assertion failed as expected.
- GitHub artifact `8935383018`, named
  `native-amd64-release-evidence-cad5ce35664f617c6e19f90a6159285ddf975594`,
  contains exactly `43` regular files, is `1,963,638` bytes and has native
  archive digest
  `sha256:281f208b3047fbff6dddb0fe0de3065203f1b507ca0f6a71381880f306390949`.
  Its `summary.json` SHA-256 is
  `f35516fb0030e16c8f392db7e308f10e2858cb8f7b9ed2fd3f10a11b0fce6160`.
  This archive digest is not an OCI Registry manifest digest.
- Every role has exactly one `cryptography 50.0.0` component and zero
  cryptography CVEs, Secrets, browser components or forbidden OS packages.
  The canonical Debian findings remain byte-consistent across all roles at
  `4 Critical / 19 High`, 23 rows and twelve unique CVEs, with no scanner
  suppression or fixed Debian version. AI Worker local image/config identity
  is
  `sha256:18db7ceff942788bc4ca1c77a466c17570c3fcc6f109957661e1a35f047ba62f`;
  it is local evidence only and has no `RepoDigest`.
- The successor CycloneDX 1.6 bundle directly binds the native run/job,
  attempt, artifact archive digest, five local image/SBOM/raw-report identities,
  twelve dispositions and `115` exact BOM-Links. It also binds all four
  production and one-shot acceptance systemd templates at the fixed release
  blob hashes and checks non-root/read-only/capability-free, no-port,
  `--pull=never`, default-suspended and bounded acceptance semantics. The VEX
  serial is `urn:uuid:04d80bd9-6213-520c-9b5f-7089ab2e8752`; evidence/VEX
  semantic SHA-256 values are `4c9d997f...9c71f` and `7ef605d1...27a9`.
- Official CycloneDX schema commit
  `55343ba19dee1785acf1ce9191540d5fd7b590db` and exact schema SHA-256
  `3e92dddb...afb93` validate the generated VEX with zero errors. Successor and
  historical focused suites pass `16/16`; all four native VEX verifiers,
  compilation, JSON parsing and diff hygiene pass. The already-running
  all-history gate-integration test completed `1/1` in `2149.503s`; it was not
  restarted or repeated. A final independent read-only audit returned `GO`
  with no P0/P1. No request, workflow, custom ledger, receipt, topology, V18,
  Registry, builder, Alibaba, production, database, Secret, provider or
  public-traffic change was made.
- The bundle remains `local-image-only`: `production_exception=false`,
  `deployment_authorization=false`, all Registry digests are null, and the
  GitHub artifact contains no OCI tar/layout. Internal readiness therefore
  remains `20/29` and public remains `20/38`. The sole task is still
  `PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`; the unique next hard condition
  is a private deployable AI Worker manifest plus a successful fresh-builder
  import. Only after that may production 0017, Dispatcher LOGIN/Secret and the
  default-suspended Stage A/B/C acceptance proceed.

### Durable AI minimum Stage A implementation checkpoint (2026-08-05)

- The cad5ce3 local-only VEX checkpoint is remotely accepted. Push run
  `31022136160` / job `92361272534` and PR run `31022140750` / job
  `92361288685` both completed `success`, attempt `1`, on exact head
  `fec23879bd54826df92f50a3bda3d1c46311f2a1`. Unit tests, Quality,
  production readiness and Compose all passed; neither run was rerun.
- The minimum Stage A implementation is exactly two executors plus one focused
  test module. `deploy/production/durable_ai_cad5_stage_a.sh` has separate
  build/publish modes; `deploy/production/durable_ai_cad5_fresh_importer.sh`
  is pull-only; `tests/test_durable_ai_cad5_stage_a.py` contains the directly
  coupled contract tests. No workflow, request, V18, R17, custom ledger,
  receipt or topology layer was added.
- Build is fixed to source commit
  `cad5ce35664f617c6e19f90a6159285ddf975594`, tree
  `a1ce9c812a74a7e3824851581d1b4b6aaaaddb1c`, the 1,513,408-byte incremental
  bundle SHA-256 `2a37c49c...bd19b`, current requirements, and the projected
  AI-Worker-only v2 native runner SHA-256 `f6793eae...36a8`. It accepts only
  the fixed source bundle, a hash-bound wheelhouse and a hash-bound scanner
  bundle. BuildKit runs with network disabled, pip uses
  `--no-index --find-links=/wheelhouse`, and Trivy uses the supplied offline
  database; there is no public PyPI or scanner-download fallback.
- Outer acceptance independently rechecks all eleven AI Worker evidence files,
  exact 4 Critical / 19 High rows, cryptography 50.0.0 exactly once and zero
  cryptography vulnerability/Secret/browser/forbidden-OS findings. It also
  binds build metadata, SBOM/report hashes, OCI labels, non-root UID/GID 999,
  entrypoint, once-only command, default suspension and `HEALTHCHECK NONE`.
  The expected raw findings remain unsuppressed and therefore do not make the
  GitHub local image ID a Registry identity.
- Publication permits exactly one push of immutable tag
  `git-cad5ce3-amd64-ai-worker-r1`. Its state remains `unknown` until push,
  digest-qualified descriptor/raw readback and manifest-config binding all
  agree. Any failure after push starts requires native control-plane
  reconciliation and forbids a rerun. The fresh importer starts from zero
  images/containers/volumes/build cache/auth, pulls the exact manifest digest
  once for `linux/amd64`, validates the separate config identity and complete
  runtime metadata, then removes the image and auth state. Any importer failure
  permanently forbids host reuse.
- Focused tests pass `10/10`; both shell syntax checks, Python compilation and
  diff hygiene pass. Two independent read-only final audits returned `GO` with
  no P0/P1. They also fixed progress observability: the single offline
  build/scan streams through `tee`, so a slow or failed cache vertex retains
  native progress instead of becoming an artificial silent timeout.
- This checkpoint made no Alibaba, IAM, ACR, Docker-daemon, production,
  database, Secret, provider or public-traffic mutation. Readiness remains
  internal `20/29` and public `20/38`. Before real execution the main CTO must
  first prove the retained BuildKit/base cache and three transferred object
  hashes, remove the transfer IAM role/policy, and use the native ACR control
  plane to prove the private NORMAL immutable repository and exact tag absence.
  After push starts there is never a second push. Freshness additionally
  requires a newly created ECS instance, native creation-time evidence and
  final instance/system-disk deletion; Docker zero-state alone is insufficient.

The task continues without a permission pause: checkpoint and push only this
minimum implementation plus Secret-free records, accept its one push/PR CI
pair, then execute Stage A in the existing 120-minute budget. Ordinary Git,
CI and Alibaba decisions are CTO-authorized; only an actual SMS/scan/face
challenge pauses for the product owner.

### Durable AI Stage A pre-build portability correction (2026-08-06)

- The existing builder received the fixed source bundle, wheelhouse and scanner
  bundle over the private OSS endpoint. Exact sizes and SHA-256 values matched
  `1,513,408 / 2a37c49c...bd19b`, `251,013,120 / e1ff9647...01cab` and
  `185,921,249 / 138cd4ff...e299`. The transfer executor was removed, then the
  builder role, attached policy, policy and role were deleted in order; native
  readback proved an empty builder role and both IAM objects absent.
- The first Stage A invocation terminated deterministically after 26 seconds at
  `offline_input_extract`, before source import or any Docker build. It created
  no target image, container, registry auth, database connection, push or
  production change. Failure cleanup removed the task root and target images;
  the hash-verified transfer inputs remain on the builder for bounded recovery.
- Two independent read-only audits plus a builder-side streaming inspection
  identified one cause: the scanner PAX archive contains twelve macOS
  AppleDouble `._*` metadata files. Linux GNU tar exposes the top-level
  `._scanner-bundle`, while local bsdtar hid it. The 119 provenance messages
  were warnings, not a network timeout. After excluding AppleDouble metadata,
  wheelhouse manifest coverage is `74/74`, scanner coverage is `6/6`, and all
  payload hashes match the already accepted archive SHA values.
- The direct correction changes only
  `deploy/production/durable_ai_cad5_stage_a.sh` and its focused test. Member
  validation permits only exact top-level `._$prefix`; extraction discards
  `._*` and `*/._*` so metadata never enters the manifest tree. C17, source and
  input hashes, dependencies, scanner payload, evidence acceptance, build
  network policy and image semantics are unchanged. Corrected script SHA-256 is
  `7ad43a31...ffe6`; focused test SHA-256 is `f3147737...cede`; tests pass
  `11/11`.
- The three private OSS objects were deleted after the definite failed
  invocation and the bucket is empty. Final empty-bucket deletion reached an
  actual Alibaba security-verification dialog and is the only interactive
  cleanup still pending. Readiness remains internal `20/29` and public
  `20/38`; the sole task remains
  `PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`.

The exact next acceptance is: finish only the interactive empty-bucket cleanup,
checkpoint and remotely accept the two-file portability correction, install the
new hash-bound script on the retained clean builder, then perform the bounded
recovery. Because the failed invocation never reached Docker, that recovery is
still the sole actual AI Worker build. Registry publication remains exact-one
and may begin only after `BUILD_PASS` plus native immutable-tag absence.

### Durable AI Stage A build-network scope correction (2026-08-06)

- The AppleDouble correction checkpoint is `e432bab15d3d6900ee243a2f13626d9c69325c8c`.
  Push run `31031575736` and PR run `31031585132` both completed `success`,
  attempt `1`, on that exact head; unit tests, Quality, production readiness and
  Compose all passed without rerun.
- The reviewed script was sent with `Overwrite=false` and atomically installed
  on the retained builder as root:root `0500`, SHA-256
  `7ad43a315f120218a4d105ad1a7f99cf5255581bf891e1d0cd5f458ddceeffe6`.
  A fail-closed installation preflight first exposed one evidence-boundary
  mistake: the outer wrapper FAIL marker was in Cloud Assistant output, not in
  the inner build logfile. Read-only reconciliation fixed the command input;
  the old logfile was then accepted by exact size/SHA and removed. No build or
  script replacement occurred during the failed preflight.
- Recovery invocation `t-sz06t3nhq4ind34` ran once and terminated in `127`
  seconds at `offline_ai_worker_build_scan`, after archive import but before any
  image, scan, publish, database or production mutation. The native output
  proves `apt-get libgomp1` could not resolve Debian and the reachable Meituan
  `npm pack` vertex was cancelled because the Docker wrapper imposed global
  `--network=none`. The three source/wheelhouse/scanner inputs remained
  byte-exact and were not removed.
- This is a deterministic network-scope defect, not a slow download. The source
  Dockerfile intentionally requires one apt package and an integrity-pinned
  Meituan npm package. None of the three retained inputs contains deb/npm
  payloads. A fully disconnected build would therefore require a new fourth
  dependency bundle, which is outside the authorized minimal recovery.
- The direct candidate changes only the Stage A wrapper and focused assertion:
  BuildKit uses standard `--network=default`; the projected pip RUN alone stays
  `--network=none --no-index --find-links=/wheelhouse`; Trivy remains in
  offline mode and uses only the supplied database. C17, cad5 source/tree,
  requirements, npm
  version/integrity/bundle SHA, input archives, target and image semantics are
  unchanged. Focused tests pass `11/11`, shell syntax and diff hygiene pass;
  candidate script/test SHA-256 values are `2540302e...e4dfd` and
  `3522ebdb...9a2d0` respectively. Independent read-only review is `GO`,
  P0/P1=`0/0`.

Readiness remains internal `20/29` and public `20/38`. The exact next
acceptance is one checkpoint and exact-head push/PR CI pair for this two-line
network-scope correction, followed by a budget-bounded recovery using the same
three retained inputs. Publication is still forbidden until `BUILD_PASS` and a
fresh native ACR tag-absence readback; push remains exact-one.

### Durable AI Stage A network-scope CI accepted; recovery timeout terminally reconciled (2026-08-06)

- The network-scope correction checkpoint is
  `2254257cedbec4bc27bdde5092ca0bed1051e617`. Push run `31035048544` / job
  `92404917241` and PR run `31035052862` / job `92404932395` both completed
  `success`, attempt `1`, on that exact head. Unit tests, Quality, production
  readiness and Compose all passed; neither run was rerun. The checkpoint and
  upstream were at divergence `0/0` before these Secret-free record updates.
- Native `DescribeInstances` first reported the retained builder
  `i-wz99180s9ig5ecq10uaj` as `Stopped` with a `financial` operation lock. The
  single bounded `StartInstance` submission was rejected before start as
  `InstanceExpired`, request `019FD348-C245-58B9-8A2F-C550016A3FD5`.
  `QueryAccountBalance` then returned cash `0.00 CNY` and available amount
  `-0.35 CNY`. Automation opened the official recharge page but did not enter
  an amount or perform payment.
- After the account owner recharged, native request
  `019FD708-86E9-5113-AE10-8EE22FBF3AC2` proved cash and available amount both
  `48.18 CNY`; request `019FD708-C579-591C-81E9-5E14B56CFA8A` proved the
  builder `Running`, no operation lock, empty auto-release time and native
  `StartTime=2026-08-06T12:22Z`. No second `StartInstance` was submitted.
- Read-only preflight invocation `t-sz06t6clvbpiozk` re-proved all three input
  size/SHA values, the old `7ad43a31...ffe6` script and exact old failed log,
  with task/image/container/auth/build/DB state all zero. SendFile invoke
  `f-sz06t6cpu9uca2o` used `Overwrite=false`; atomic install invoke
  `t-sz06t6csl3p7fnk` replaced the script with root:root `0500`, SHA-256
  `2540302e88b65927655d4284a046d0cf8f1bcd9554357492beaf5d8aab2e4dfd`,
  removed only the accepted old failed log and preserved all inputs.
- The unique recovery build invocation `t-sz06t6cy4r7jbi8` ran from
  `12:32:17Z` to `12:44:58Z`. Standard-network apt was slow but completed;
  Meituan npm was cached, and pip installed solely from the local wheelhouse.
  BuildKit wrote image
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`.
  The CTO-selected outer `720s` timeout then expired during
  `evidence_acceptance`, producing stage FAIL plus wrapper exit `124` before a
  `BUILD_PASS`. Failure cleanup removed the task root and image. This is an
  execution-timeout error after a slow but successful image build, not a
  dependency-content, pip-network or Trivy failure.
- A client stream disconnect delayed control-plane cleanup. Read-only terminal
  reconciliation invocation `t-sz06t6h6m3q1se8` nevertheless proved the three
  inputs and installed script unchanged; logfile root:root `0600` has SHA-256
  `fbb8ead8ae16fc03ba96e1dab8b586653522fb0f71a0b5db0c63c28cbc5a8def`,
  exactly one stage FAIL, zero BUILD_PASS, one wrapper FAIL and one image-write
  marker. Task root, exact image ID, canonical/local images, containers, auth,
  build processes and DB connections were all absent. Registry login/tag/push,
  IAM, ACR link, database and production mutations remained zero.
- A stopped-instance control-plane read of the prior network-failure invocation
  required no builder restart and returned actual builder version
  `github.com/docker/buildx v0.14.0 171fcbe`, request
  `019FD745-C90E-55B1-A342-F02E8541D9D3`; the same output proves
  `default` instance using the `docker` driver, not a `docker-container`
  builder. The official v0.14.0 command list and root registration contain no
  `history` command, and there is no `buildx_buildkit_*` container in which to
  run `buildctl debug histories/get`. The newer Buildx history-attachment
  forensic route is therefore unavailable through the installed native command
  surface. Installing another client, creating a Docker `/grpc` proxy or
  writing a content-store exporter would add an unaccepted recovery control
  path and is outside the owner's explicit simplification boundary.
- After the account owner completed the real security verification, the one
  prepared graceful stop succeeded with request
  `019FD73C-233D-5063-BDC1-0217FEC1B7AE`. Native read request
  `019FD73C-E527-5601-8DC5-119B45E51081` proves `Stopped / StopCharging`, no
  operation lock and empty auto-release time. This record does not claim an
  exact charge amount or that the declared 30-minute wall-clock window was met.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. Stage A is not accepted because no
BUILD_PASS, deployable manifest or fresh import exists. Two independent
read-only audits found no supported no-build recovery: the Engine image, task
root, eleven evidence files, Docker/OCI archive and Registry source are absent,
the actual v0.14.0/default-docker-driver command surface has no history export,
and retained BuildKit cache cannot materialize an Engine image without a new
build solve. Existing exact-one/no-rerun authority does not cover a second build
invocation or renewed paid builder window. The minimum required exception is one
cache-assisted rematerialization using the identical `2254257` script,
C17 source and three verified inputs, with an outer timeout that covers evidence
acceptance and cleanup; no code, CI/gate, image-semantic, V18/R17 or custom
control-layer change is permitted. Publication remains forbidden unless that
single invocation emits BUILD_PASS, reproduces the exact written image ID and
then passes native tag-absence, exact-one push and fresh import.

### Authorized cache recovery stopped before build on expired scanner metadata (2026-08-06)

- The product owner explicitly delegated continuing CTO authorization through
  `29/29`, with pauses only for interactive authentication, expired credentials
  or insufficient balance. Native balance read request
  `019FD753-FED0-5C53-BAB4-11AAFC7E24CB` returned `48.18 CNY`; instance read
  `019FD753-E670-5DAA-93E1-D3220DF93304` proved the retained builder
  `Stopped / StopCharging` without locks. The one start request
  `019FD754-4AF6-5A50-A64C-8BE30907F14A` succeeded, and read request
  `019FD754-9343-58F3-A119-D6D66AC73041` proved `Running` with native
  `StartTime=2026-08-06T13:47Z`.
- Read-only preflight invocation `t-sz06t6jvoddm51c` passed. It re-proved the
  three exact input sizes and hashes, script SHA-256
  `2540302e88b65927655d4284a046d0cf8f1bcd9554357492beaf5d8aab2e4dfd`,
  prior failure-log SHA-256
  `fbb8ead8ae16fc03ba96e1dab8b586653522fb0f71a0b5db0c63c28cbc5a8def`,
  task/image/container/auth/build/DB state all zero and `22.18GB` retained
  BuildKit cache.
- Exactly one authorized cache-recovery command was submitted: invocation
  `t-sz06t6k2kdmokjk`, command `c-sz06t6k2kd2pds0`, created
  `2026-08-06T13:52:07Z`, outer timeout `6600s`, Cloud Assistant timeout
  `7200s`. It terminated after about 52 seconds at `offline_input_extract`,
  before any Docker build, with one stage FAIL, zero BUILD_PASS and one wrapper
  FAIL. It was not resubmitted.
- Read-only terminal reconcile invocation `t-sz06t6kak5qjri8` bound the new
  failure log to SHA-256
  `480917e991b4f695c576a0c536ce2346944804e243ba92690b41366570813b2f`.
  All three input hashes remained exact; task/image/container/auth/build/DB
  state was zero and Docker had `80107MiB` free. The scanner metadata itself
  proves the deterministic cause: `UpdatedAt=2026-08-05T13:23:37.971556067Z`,
  `DownloadedAt=2026-08-05T17:05:02Z` and
  `NextUpdate=2026-08-06T13:23:37.971555767Z`, while reconciliation time was
  epoch `1786024483` (`2026-08-06T13:54:43Z`). The strict less-than-24-hour and
  future-NextUpdate predicates had both expired by about 31 minutes.
- This is a scanner-input lifecycle expiry, not archive corruption, cache miss,
  public-download timeout, pip fallback, Trivy scan failure or image change.
  Stop request `019FD75B-F5A9-5F26-8257-8584D946D55F` succeeded; read request
  `019FD75C-407E-51CE-B118-B00D588F54FF` proves the builder again
  `Stopped / StopCharging` without locks. Registry login/tag/push, IAM, ACR
  link, database and production mutations remained zero.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The direct recovery is to refresh
only the offline Trivy DB inside a new root-only scanner-bundle generation,
recompute its embedded manifest and archive SHA, then pass that new scanner SHA
to the unchanged accepted script. C17, source, wheelhouse, dependency hashes,
Dockerfile, image semantics, V18/R17 and CI/full gates remain unchanged. No new
build is authorized by this record until the refreshed bundle passes native
freshness, permission, member, manifest and hash acceptance.

### Offline scanner bundle refresh accepted (2026-08-06)

- The owner delegated continuous CTO authorization through `29/29`, pausing
  only for interactive authentication, expired credentials or insufficient
  balance. Read request `019FD76D-898E-53F3-8522-0C8D241C65A2` proved the
  retained builder `Stopped / StopCharging` without locks; balance request
  `019FD76D-BA7A-59B6-AEB3-DE42B26DA354` returned `47.20 CNY`. Start request
  `019FD770-F9E5-5B46-93F2-B8ACAAADB0F4` succeeded and read request
  `019FD771-6896-5410-B83A-1A52F91DE290` proved `Running` with native
  `StartTime=2026-08-06T14:18Z`.
- The root-only refresh payload SHA-256
  `6d45f6f8a2fba6b8c58260665d72f3d9dde3b9276044e264b4bad371511b99e7`
  passed `bash -n` and independent read-only review with P0/P1=`0/0`. It
  inherited no credentials, used an empty Docker config and only the bundled
  Trivy `0.72.0`; Public ECR was first and GHCR only a bounded fallback. It had
  no build, push, Registry login, IAM or database path.
- Two overlong pre-submit API-page navigations were reconciled as native
  `TotalCount=0`; neither created a run. The sole created refresh is command
  `c-sz06t6ms19ad8u8`, invocation `t-sz06t6ms19kcu80`, created
  `2026-08-06T14:22:28Z`. It ran once from `14:22:29Z` to `14:24:42Z`, exited
  zero and downloaded the complete `103.68MiB` Public ECR artifact in about
  31 seconds; native output has `Dropped=0`, exactly one PASS and zero FAIL.
- The accepted refreshed scanner archive is
  `186,587,382 / 1c307bf5f9031a1933b8f45397f64420aec617fc14a06af8ffb428309388d938`.
  Its DB SHA-256 is
  `bcd78f506eee5af415d6419644001d162188e2e3f0504b48e50be577a5b55121`
  and metadata SHA-256 is
  `4eacd2d4e761a8f8ad0c2d0cdaa87035a5aad4a05857440aed2a1ba4329a3d31`.
  Metadata is Version 2 with
  `UpdatedAt=2026-08-06T13:26:59.911565102Z`,
  `DownloadedAt=2026-08-06T14:23:21.499595503Z` and
  `NextUpdate=2026-08-07T13:26:59.911564962Z`. All six embedded payload hashes,
  twelve members, permissions, compression/expansion limits and the retained
  exact old backup were verified before atomic replacement. Final output
  proves build/push/auth/database counts all zero.
- A proposed extra read-only reconcile command was blocked before submission;
  native read request `019FD780-C2B8-5324-BDAF-D851E8C0E5FD` proves its exact
  CommandName has `TotalCount=0`. It was not worked around or resubmitted.
  Existing native output request `019FD781-1870-5489-B4D1-4AAE63E6491A`
  supplied the complete undropped terminal evidence instead.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The immediate acceptance is one
new-input, exact-one successor build using unchanged script SHA
`2540302e...e4dfd`, C17/source/wheelhouse and the accepted scanner SHA above,
with outer `6900s` inside Cloud Assistant `7200s`, no retry. Only BUILD_PASS
and the exact expected image identity permit native immutable-tag absence,
exact-one private push and fresh-builder import.

### Fresh DB exposed stale vulnerability-row acceptance (2026-08-06)

- The exact-one new-input successor is command `c-sz06t6picf186io`, invocation
  `t-sz06t6picfg7klc`, created `2026-08-06T14:53:05Z`. It ran once from
  `14:53:06Z` to `14:56:19Z`, `RepeatMode=Once`, `Repeats=1`, outer `6900s`,
  Cloud Assistant `7200s`, and exited `1` rather than timing out. Native
  terminal request `019FD793-DF9C-599B-931D-D746C670318B` records dropped
  progress bytes but preserves the decisive markers: all build layers were
  cached, image write reproduced exact ID
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`,
  then Stage A failed in `evidence_acceptance`. The wrapper records
  `build_exit=1`, `tee_exit=0`, no retry and no rerun. Fail-closed cleanup
  removed the task/image before any Registry login, tag, push, database or
  production mutation.
- The failure is now reproduced independently without another build. GitHub
  artifact `8935383018` supplied the immutable C17 AI Worker CycloneDX SBOM.
  Official Public ECR manifest
  `sha256:61694172fffbc56e80f347684010b479b29f2f5117279a56579e3781e9e5cbeb`
  supplied layer
  `sha256:989166d536c2f1c058895513f54d164de978f3fc03e6afda32e900d4b8730ba4`;
  its extracted DB SHA is the exact builder value
  `bcd78f506eee5af415d6419644001d162188e2e3f0504b48e50be577a5b55121`.
  Official macOS-arm64 Trivy `0.72.0` archive was checksum-verified as
  `88f208680dc05da2b459e19b4f5aa2b4dc7c2117892ba4aab2ae63baba330016`.
  Offline SBOM rescan reports exactly `0 Critical / 2 High / 2 rows`, with
  only `CVE-2026-41992 / gzip / 1.13-1 / HIGH` and
  `CVE-2026-53615 / util-linux / 2.41-5 / HIGH`; report SHA-256 is
  `077276d3ed6efb2f3cb1e4a65b9731373615ee6bc0fd0d0f4cfc157d17b379b1`.
- The sole hard mismatch is the Stage A verifier's historical old-DB contract
  of `4 Critical / 19 High / 23 rows`. The minimum direct repair changes only
  that count and exact-row set in
  `deploy/production/durable_ai_cad5_stage_a.sh`, plus its focused assertions
  in `tests/test_durable_ai_cad5_stage_a.py`. C17, source/tree, dependencies,
  Dockerfile, build/pip/Trivy network semantics, image contents, Registry,
  production resources, V18/R17 and custom control layers are unchanged.
  Shell syntax and focused Stage A tests pass `11/11`; the readiness JSON
  parses successfully and the staged diff is clean.

Readiness remains internal `20/29` and public `20/38`. Next checkpoint only
this direct two-file fix with the current Secret-free records, obtain one
exact-HEAD push/PR CI pair and one complete readiness gate, then reinstall the
hash-bound script and perform one new-code recovery. Publication remains
forbidden until BUILD_PASS, exact image identity, native immutable-tag absence,
exact-one private push and fresh-builder import all pass.

- Independent read-only review of the final two-file implementation returned
  `GO`, P0/P1=`0/0`. It independently matched the checksum-verified fresh DB
  report and confirmed that exact-row equality remains fail-closed while C17,
  source, wheelhouse, dependency, image, network and exact-one publication
  semantics are unchanged. Final candidate SHA-256 values are
  `b2b47ce6e51426646a4f0dec762da695194af6761fe70b95b602428e2cf05a1e`
  for the Stage A script and
  `ef7b8366a9c8d86f3d0dac0aee84a91c2fad1921a550f6322fb38eb55a0ef730`
  for its focused test. `bash -n`, focused `11/11`, JSON parse and
  `git diff --check` all pass. No successor recovery has been
  submitted after the terminal failed invocation; the retained builder remains
  available only for the post-CI new-code recovery.

### Fresh-DB verifier checkpoint accepted for new-code recovery (2026-08-06)

- The direct verifier checkpoint is
  `0d5179fb766163ebd2277c77046716089a66ffcf`, tree
  `8c7ce051adc3e70ab45c6250f29aa04c300371dd`, pushed to the existing branch and
  draft PR #2 at upstream divergence `0/0`. No second PR or activation version
  was created.
- The exact-HEAD push run `31115038512` / job `92662255062` is terminal
  `failure`, attempt `1`, solely in `Set up job` before Checkout. Its native log
  records `Service Unavailable`, then `Internal Server Error`, then terminal
  `Service Unavailable` while resolving action download metadata. No repository
  code or check step ran, and it was not rerun.
- The exact-HEAD PR run `31115042410` / job `92662267833` completed `success`,
  attempt `1`, in `24m35s`. Checkout, model verification, syntax, complete unit
  tests, Quality, production readiness and Compose all passed. This is the
  content-executing CI acceptance for the immutable checkpoint; the push-side
  platform 503 is retained as native infrastructure evidence rather than
  converted into a code change, V18 or rerun.
- The single local complete gate then returned
  `production_readiness=PASS`, `checks=138`, `failed=0`. No duplicate gate
  process remained. Script/test SHA-256 values remain `b2b47ce6...05a1e` and
  `ef7b8366...ef730`.
- Read-only Alibaba requests `019FD7A6-C6C4-5426-B424-6EF583983932` and
  `019FD7A6-E148-5626-B39C-78FF4AD19148` proved available balance `46.43 CNY`
  and the retained builder `Running`, no operation lock, no auto-release time,
  native `StartTime=2026-08-06T14:18Z`. No start or Cloud Assistant command was
  submitted during CI.
- The post-gate install payload is gzip
  `10,926 / 822ec9e5b0375e915daab5f3dbb21d7511cd3a592fdd732f2b2faf071d2739cb`
  expanding to the accepted script exactly. Minimal install/recovery payloads
  have SHA-256 `7e6ce65f4ec70e79108ab2d8d3a7b3e2856a40db8d6977bc3904bbef2181383e`
  and `7b67c08f4290fb3f312911c16c8f280b3ff35d090db25cde6c6eb08e480b4a11`;
  independent read-only review returned `GO`, P0/P1=`0/0`. The recovery has one
  build call, no loop/retry, a noclobber log, inner `6900s`; the Cloud Assistant
  request must itself be set to `7200s`.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. Next acceptance is a small native
preflight, one overwrite-disabled SendFile plus atomic install, then exactly one
new-code recovery invocation. Publication remains forbidden until BUILD_PASS,
the exact expected image identity and native immutable-tag absence all pass.

### New-code Stage A terminal failure and cost-safe reconciliation (2026-08-06)

- Corrected read-only preflight invocation `t-sz06t6v4pys7u2o` passed with the
  three offline input hashes unchanged, zero task/image/container/auth/build/DB
  state and the accepted old script still installed. One overwrite-disabled
  SendFile invocation `f-sz06t6vqal084cg` transferred only gzip
  `10,926 / 822ec9e5b0375e915daab5f3dbb21d7511cd3a592fdd732f2b2faf071d2739cb`;
  atomic install invocation `t-sz06t6vyb8bturk` replaced only the Stage A
  script and proved final `root:root:0500:39125 / b2b47ce6e51426646a4f0dec762da695194af6761fe70b95b602428e2cf05a1e`.
  The payload was removed and build/push/auth/database state remained zero.
- Exact pre-submit reconciliation proved no prior command with the selected
  name. The sole new-code Stage A is command `c-sz06t6wangc9e68`, invocation
  `t-sz06t6wangr8s8w`, `RepeatMode=Once`, `Repeats=1`, Cloud Assistant timeout
  `7200s` and inner timeout `6900s`. It ran from `2026-08-06T16:09:10Z` to
  `16:11:56Z`, exited `1` rather than timing out, reused all Docker build layers
  and wrote the exact expected image ID
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`.
  It then emitted exactly one Stage A FAIL at `evidence_acceptance`, zero
  BUILD_PASS and exactly one wrapper FAIL with `build_exit=1`, `tee_exit=0`,
  manual/automatic retries `0/0` and `no_rerun=1`. Registry publication was not
  entered.
- Read-only terminal reconcile command `c-sz06t6x1mbaimf4`, invocation
  `t-sz06t6x1mbuht6o`, exited zero with undropped output. It bound the failure
  log to `51,895 / e3a4e94dc7e6477a37b572d29e8f06053af7e1e171008e7afd38002ce286df63`,
  proved start/build-pass/stage-fail/wrapper-pass/wrapper-fail/image-write marker
  counts `1/0/1/0/1/1`, reverified all three offline inputs and proved final
  task/canonical-image/local-image/container/auth/build/DB state
  `0/0/0/0/0/0/0`. No ACR tag, Registry auth, database or production mutation
  exists.
- Graceful stop request `019FD7DE-CC78-584A-983F-DC3CCD0F2984` succeeded.
  Native read request `019FD7DF-D421-5C5B-ADFA-3AFEB1327922` proves the PostPaid
  builder is now `Stopped / StopCharging`, with no operation lock and no
  auto-release time.
- Final read-only Cloud Assistant request
  `019FD7E8-B7B8-58D1-9A91-E47672BC592F` re-read the terminal invocation without
  starting the builder. Its retained `24,576` output bytes contain no CVE,
  summary, Critical/High count or verifier-predicate detail; the only decisive
  tail is the exact image write followed by `phase=evidence_acceptance` and the
  no-rerun wrapper FAIL. The native record reports `Dropped=27,319`, so it
  cannot recover the file-only Trivy report.
- Independent read-only terminal audit is `NO-GO`, P0/P1=`0/1`. The locally
  rescanned GitHub artifact is CycloneDX for AI Worker image
  `sha256:18db7ceff942788bc4ca1c77a466c17570c3fcc6f109957661e1a35f047ba62f`,
  not the actual new image `sha256:1f503665...0c95`; Stage A's shared phase also
  contains summary, exact-row, inspect, SBOM, secret and base-index predicates.
  Existing read-only evidence therefore cannot prove which predicate failed.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The single missing hard fact is the
fresh native `trivy image` report for the actual immutable image—its exact
Critical/High counts and CVE row set (equivalently, the exact failed verifier
predicate). The failure cleanup removed that report, while the retained log
records only `evidence_acceptance`; the checksum-bound offline CycloneDX SBOM
rescan is useful but is not proof of the image scanner's inventory. No verifier,
image, V18/R17, ledger/receipt/topology or production change is authorized by a
guess. Stage B/C and ACR publication remain closed until this hard fact is
obtained without reinterpreting the failed invocation as BUILD_PASS.

### Evidence-preserving cache rematerialization identified both direct Stage A defects (2026-08-07)

- The owner explicitly overrode the prior exact-one/no-rerun restriction for
  one evidence-preserving cache rematerialization and delegated subsequent
  authorization to the CTO. Two independent read-only reviews accepted only
  diagnostic main script
  `40,138 / 39a700f4f1732e0147649e7748c379aad77e18876b756bce9196cb2a18273622`,
  gzip
  `11,113 / 7d3ecf262a93fb8270891bd55ad001a220bd24904bc855421e89e0dc9a45a8b9`
  and exact-one wrapper
  `2,146 / c2784e1e7f92d79cbd4a65363064742589cde845d92bdc5a35daa9b5913257a0`;
  both reviews were `GO`, P0/P1=`0/0`.
- Builder preflight invocation `t-sz06t81ea8xr4e8` returned
  `Success / ExitCode=0 / Repeats=1` with the three input hashes exact, fresh
  scanner accepted and task/image/container/auth/build/database state zero.
  Overwrite-disabled SendFile `f-sz06t81n1wkbpxc` installed only the reviewed
  gzip as `root:root:0600`; atomic install `t-sz06t81st9bw9og` returned
  `Success / ExitCode=0 / Repeats=1`, installed the exact script SHA and removed
  the gzip. Exact command-name preflight returned `TotalCount=0`.
- The sole diagnostic build is command `c-sz06t821mue5a0w`, invocation
  `t-sz06t821muvmkg0`, request
  `019FD982-696A-5202-A1A0-310E11C8E2CA`, `RepeatMode=Once`, `Repeats=1`,
  Cloud timeout `7200s`, outer `6900s`, inner `5400s`, retries `0` and
  publication disabled. It ran from `2026-08-06T23:57:11Z` to
  `2026-08-07T00:00:25Z`, exited `1` rather than timing out, reused the local
  cache and reproduced exact image ID
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`.
- Native diagnostic evidence proves the actual image has exactly
  `4 Critical / 19 High / 23 rows`, vulnerability report SHA-256
  `ea1ca715e3ccb21c29b2d8372dbccc6513164dfd3de2f3f39d5b100e7b14798e`,
  no secrets and the expected cryptography `50.0.0`. Its sorted 23-row set is
  byte-identical to GitHub native run `31017791512`; the prior `0/2` contract
  came from a different-image CycloneDX rescan and is not valid image-scan
  evidence. The first failed verifier command was the exact `0600` mode check,
  because Buildx atomically creates `--metadata-file` as `0644` independently
  of the inherited `umask`.
- Evidence reconciliation command `c-sz06t83189pff9c`, invocation
  `t-sz06t8318a4etc0`, returned `Success / ExitCode=0 / Repeats=1`. It verified
  exact 11 root-only copied evidence files and manifest SHA
  `2b36b1b4c1a19479b3a6c2c63fd6fdb948a579045a9c234999c4c5ff058a435e`,
  failure-command SHA
  `c2a153b423caa2f2cca4bd5f2add93807dd705fd7616af498a176a36a2942a90`
  and log
  `56,994 / 1e43794d1d2b1fa4e600e2ffe39aaa5376f3714b8b7101cd6e06f6c940c26cab`.
  Fail-closed cleanup left task, both images, containers, auth, build and
  database counts all zero; ACR, IAM, production and database mutations were
  zero. Stop request `019FD990-C910-58D5-8CBE-C617C81ECF1B` required owner
  verification; native read `019FD992-B432-525A-A58D-C82204A6663B` now proves
  `Stopped / StopCharging / PostPaid`, no lock and no auto-release.
- The minimum direct repair changes only
  `deploy/production/durable_ai_cad5_stage_a.sh` and
  `tests/test_durable_ai_cad5_stage_a.py`: exact 11 regular/non-symlink native
  evidence files are normalized to `0600` before first verification, and the
  verifier is restored to canonical exact `4/19/23`. C17, source/tree, three
  inputs, dependency locks, Dockerfile, image contents, build/pip/Trivy network
  semantics, workflow, Registry and production resources are unchanged.
  Candidate hashes are `e4643920...cbd18` and `ea142246...af8fc`; shell syntax,
  focused `12/12` and diff check pass.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. Next acceptance is final independent
read-only review, one checkpoint and one exact-HEAD push/PR CI pair, followed
by one complete readiness gate. Only after all pass may one recovery Stage A
be installed and executed; BUILD_PASS, exact image identity, native private-tag
absence, exact-one push and fresh-builder import remain required before Stage
B/C. No V18/R17 or custom ledger/receipt/topology expansion is permitted.

### Exact-HEAD CI timeout root cause and direct repair (2026-08-07)

- Implementation checkpoint `e3c727a35c4af5c51b46081ea45e17bc1255c7d5`
  is pushed on the existing branch with a clean `0/0` upstream. Its push CI
  `31134471751` / job `92730674731` / attempt `1` completed `success`, including
  unit, Quality, production readiness and Compose steps.
- The parallel PR CI `31134476571` / job `92730688438` / attempt `1` was not a
  code-test failure. It ran from `00:23:28Z` to `00:48:31Z` and was cancelled
  exactly at the workflow's bounded `25` minute job timeout. The last observed
  unit-test group returned `OK` immediately before native
  `The operation was canceled`; Quality, production readiness and Compose were
  skipped. The cancelled run is retained and will not be rerun.
- The direct reliability repair changes only the CI job timeout `25 -> 35` and
  the exact corresponding readiness-gate and anti-drift test assertions. It
  does not change triggers, permissions, test commands, C17, dependencies,
  builds, images, Stage A, Registry or production resources. V14-V17 historical
  hashes remain frozen and are not rewritten.
- Focused checks pass `6/6`; Python compilation, YAML parsing and
  `git diff --check` pass. New Secret-free hashes are CI
  `96821e6c...9fe1`, gate `36e8406d...7463`, and test
  `d3149dca...135b`. The reviewed recovery payload remains
  `11,187 / 4d10f148...4ec76`; preflight/install/run wrappers are independently
  `GO`, P0/P1=`0/0`, with a single build and no retry or publication.

Readiness remains internal `20/29` and public `20/38`. The next action is one
checkpoint and push of this direct timeout repair, then one new exact-HEAD
push/PR CI pair. Only after both succeed will one complete local readiness gate
run; then the retained builder may be started for the already authorized single
recovery Stage A. No V18/R17, cancelled-job rerun or custom control expansion is
permitted.

### Bounded CI repair accepted; single Stage A recovery open (2026-08-07)

- Direct timeout checkpoint `8c58995187769d2e01d7944b6a772191c4e22597`
  is on the existing branch/PR at clean upstream `0/0`. Exact-HEAD push CI
  `31136383455` / job `92736571813` and PR CI `31136385115` / job
  `92736576633` both completed `success`, attempt `1`; every Checkout,
  dependency, syntax, model, unit, Quality, production-readiness and Compose
  step passed. The cancelled predecessor was not rerun.
- The single complete local gate then returned
  `production_readiness=PASS`, `checks=138`, `failed=0`; no second gate process
  exists. C17, Stage A `40,403 / e4643920...cbd18`, test
  `ea142246...af8fc`, wheelhouse/source/scanner hashes and expected image ID are
  unchanged.
- Recovery transport is independently `GO`, P0/P1=`0/0`: reproducible gzip is
  `11,187 / 4d10f148...4ec76`; preflight/install/recovery wrappers are
  `3,742 / 5519f578...025da`, `1,930 / 9b526d9b...e82da`, and
  `2,622 / de346337...c9603`. Preflight requires scanner validity beyond the
  complete `7200s` budget; install is atomic; recovery fixes expected image ID,
  invokes one build, uses outer `6900s`/Cloud `7200s`, has zero retry and keeps
  publication disabled.

Readiness remains internal `20/29` and public `20/38`. The sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. Start only retained builder
`i-wz99180s9ig5ecq10uaj`, pass read-only preflight, transfer/install the exact
script once and submit one recovery invocation. Only BUILD_PASS plus exact image
identity opens native immutable-tag absence, exact-one private publication and
fresh-builder import; no report/checkpoint is a stopping point.

### Bounded Stage A recovery accepted; native publication open (2026-08-07)

- Native builder read `019FD9D5-14AD-5707-B82E-A49872E4115F` proved the exact
  retained PostPaid builder stopped, unlocked and without auto-release. The
  single start request `019FD9D7-C87A-5F7D-A506-7A732F14356D` reached stable
  `Running`; no second start was submitted.
- Exact-name preflight was zero before creation. Command
  `c-sz06t8bet7cmark` / invocation `t-sz06t8bet7wlhj4` finished once with
  `ExitCode=0`: all three retained offline inputs were exact, scanner validity
  exceeded the full `7200s` budget, and task/canonical image/local
  image/container/auth/build/database counts were all zero. Overwrite-disabled
  SendFile invocation `f-sz06t8br5e93h1c` delivered only reproducible gzip
  `11,187 / 4d10f148...4ec76` as root-only `0600`.
- Atomic install command `c-sz06t8c0grrtfcw` / invocation
  `t-sz06t8c0gs9aps0` finished once with `ExitCode=0`, replaced only the
  accepted Stage A script from `b2b47ce6...05a1e` to
  `40,403 / e4643920...cbd18`, removed the transfer payload and retained zero
  build, push, Registry-auth and database actions.
- Recovery command `c-sz06t8c7wqb6t4w` / invocation
  `t-sz06t8c7wqso3k0` ran from `2026-08-07T01:51:14Z` to
  `2026-08-07T01:54:32Z` and finished `ExitCode=0 / Repeats=1`. It emitted
  exactly one `BUILD_PASS` and wrapper `PASS`, zero FAIL, manual retries or
  automatic retries, and kept publication disabled. Canonical and local image
  IDs both equal
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`;
  all 11 evidence files passed. Exact inputs remain source
  `2a37c49c...bd19b`, wheelhouse `e1ff9647...01cab`, scanner
  `1c307bf5...d938`; Trivy DB/metadata remain `bcd78f50...b55121` /
  `4eacd2d4...9a3d31`. Secret-free evidence hashes are metadata
  `fec2f97e...96dc6`, inspect `4ffb4bb6...04547`, SBOM
  `d3b9678e...3f4b`, vulnerability `0c791495...63ac`, Secret
  `626bda98...25df` and summary `7b8880f2...906ad`.
- The transfer IAM role/policy and private OSS objects were already absent by
  native readback before this recovery. This stage performed no IAM, ACR link,
  Registry login/tag/push, production, database or public-traffic mutation.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. BUILD_PASS and exact local image
identity now open the next acceptance: native private-repository and immutable
tag reads, exact target-tag absence, one Scheme One private publication with
digest agreement, then a truly fresh pull/import host. Production migration
0017, dispatcher LOGIN/Secret, default-suspended units and cross-host takeover
remain required before Item 21 can become verified.

### Native private publication accepted; fresh import open (2026-08-07)

- Native ACR readback proved the exact immutable target tag absent before any
  publisher invocation. A first wrapper stopped at local preflight with
  `publisher_invocations=0`; the tag remained absent, so it consumed no push.
  The corrected wrapper then invoked the retained publisher exactly once:
  command `c-sz06t8kn3ma2k1s` / invocation `t-sz06t8kn3mrjugw` completed
  `ExitCode=0`, `Repeats=1`, `PUBLISH_PASS`, `pushes=1`, retries `0`.
- The pushed, descriptor and native ACR manifest digest all equal
  `sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b`.
  The native ACR ImageId/config and accepted Stage A local image both equal
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`;
  native tag state is `NORMAL`.
- Temporary publisher IAM and the builder ACR VPC link were removed. The sole
  production ACR VPC link was restored, the public Registry endpoint remains
  disabled, and API-C/API-F plus historical Admin passed exact-unit/image,
  active/ready, three-round HTTP 200, loopback-only, restart-zero and
  database-connection-zero postchecks.

Readiness remains internal `20/29` and public `20/38`; the sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The immediate hard condition is a
single pull by manifest digest on a host created after publication with zero
prior Docker state, no container start, exact config/OCI identity and complete
host/system-disk destruction. Item 21 still also requires production migration
0017, Dispatcher LOGIN/Secret, default-suspended units and provider-free
cross-host lease takeover. No V18/R17 or custom control expansion is permitted.

### Fresh importer prepared; balance blocks host creation (2026-08-07)

- Native reads accepted the restored production VPC path: the target vSwitch is
  `Available` in `cn-shenzhen-c`, the exact AMD64 instance type is `WithStock`,
  the private ACR link remains attached, and an available VPC-wide SNAT rule
  permits private-address package bootstrap without assigning a public IP.
- A new short-lived ECS trust role and exact pull-only policy were created and
  attached; permissions are limited to `GetAuthorizationToken` plus
  `PullRepository` on the exact Enterprise repository. A new empty temporary
  security group was also created. No instance is attached to the role or
  group, and none of these objects has billable compute or storage.
- The one idempotent `RunInstances` request
  `019FDA5E-9DF6-5BDC-998A-0FEFCC178DEF` was rejected before resource creation
  with `InvalidAccountStatus.NotEnoughBalance`. Native follow-up request
  `019FDA5F-60A7-52D0-BE16-664F0CD28271` proves the exact instance name count is
  zero; no system disk, Docker state, Registry token, pull or importer
  invocation exists. Billing read `019FDA5F-AA18-592B-9145-4F31582C8B56`
  reports available cash/credit `38.83 CNY`.

Readiness remains internal `20/29` and public `20/38`; Item 21 and the sole task
remain unchanged. This is a real external balance blocker. After recharge,
resubmit the same exact `RunInstances` payload and ClientToken, set bounded
auto-release, then continue the one-pull/no-start import and immediate IAM,
host, system-disk and security-group cleanup without repeating Stage A/B, CI or
the full readiness gate.

### Fresh C17 import accepted and all temporary resources removed (2026-08-07)

- The post-publication importer was created fresh and private, then invoked
  exactly once by command `c-sz06ta7gzar6g3k` / invocation
  `t-sz06ta7gzb8nqio`. It completed `ExitCode=0`, `Repeats=1` from
  `14:25:09Z` to `14:25:25Z`: one Registry token request, one pull, zero
  retries and zero container starts. The imported manifest is
  `sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b`;
  its config is
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`,
  exactly matching Stage A/native ACR and bound to accepted C17 commit
  `cad5ce35664f617c6e19f90a6159285ddf975594`.
- Final host audit command `c-sz06ta7xi6d5am8` / invocation
  `t-sz06ta7xi6uml1d` completed `ExitCode=0`, `Repeats=1` with upload,
  importer, CLI home, task root, Docker auth, images, containers, volumes,
  build cache and database connections all zero. Temporary RAM was detached
  and deleted. Native absence reads then proved fresh instance
  `i-wz91tijzvnfb89ygphju` and system disk `d-wz91tijzvnfb89y9zglq` both
  `TotalCount=0` (`019FDCB6-96EC-5C24-BBED-A54F93D8CA41`,
  `019FDCB6-FA4C-536A-A4A5-6D1A97D18B00`), and the role/policy both absent
  (`019FDCB7-3F23-5E34-B189-0C3E66A02D61`,
  `019FDCB7-BE22-52A7-A423-48BE7EE71932`).
- The remaining temporary security group was independently read as the exact
  import-only group with `EcsCount=0` and `RuleCount=0`
  (`019FDCB8-431C-54A4-AF01-DB353F51FD2C`), deleted once
  (`019FDCB8-BC86-52D2-AFA1-D124B336CA12`), and read back at
  `TotalCount=0` (`019FDCB8-F873-58BB-BB4C-005EAAEAE880`). The retained old
  builder and production API-C/API-F/Admin were not started or modified.

Readiness remains internal `20/29` and public `20/38`. Fresh import is now
accepted and must not be rerun. The sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`; its next hard condition is the
production-only chain: migration `0017`, Dispatcher `LOGIN` plus managed
Secret, exact default-suspended units, and provider-free cross-host lease
takeover. No V18/R17 or custom ledger/receipt/topology layer is permitted.

### Item 21 production executor candidate is locally closed (2026-08-08)

- The smallest direct production execution surface is now implemented without
  changing C17, its dependency lock/hash, image contents, production resources,
  or the accepted four systemd templates. It consists only of the fixed `0017`
  transaction/session-account check, one-role Dispatcher Secret activation,
  fixed-C17 unit installation/removal, a protected in-memory database control
  transport, and the provider-free acceptance controller/runner. There is no
  new ledger, receipt, persistent topology, automatic retry or exposed
  container-local rollback path.
- The candidate remains bound to release commit
  `cad5ce35664f617c6e19f90a6159285ddf975594`, ACR manifest
  `sha256:407eef2b50b13cefc365f9decd34de39ee0f8e327b7fbfc0eda15fa519ae321b`,
  config
  `sha256:1f503665de518d871813133335418822e9383544fbfd1cde3e2b66bb51470c95`,
  and migration payload
  `sha256:a73cbefd853cefe7b56c42bed2c5a7f0ba1626e57755c6f9464629b49c42cbbe`.
  The fixed controller source is
  `sha256:d7053597fbe60ebab78624b7cdaa74d19804f1a492afb8d679c2b700337eac1b`.
- Expanded focused regression passed `300/300`, with the existing ten
  real-PostgreSQL-only cases explicitly skipped; the final six-suite security
  review passed `67/67`. `py_compile`, four direct-script `--help` smokes and
  `git diff --check` pass. Three independent read-only reviews report
  `P0=0/P1=0`, including admission commit-acknowledgement recovery, exact
  database session identity, systemd `static/0` acceptance semantics, Secret
  confinement and mutation-unknown/no-retry behavior.
- This is local evidence only: no production connection, database/storage
  mutation, provider/public call, image operation or cloud-resource mutation
  occurred, and no readiness credit is added. Internal/public readiness stays
  `20/29` and `20/38`.

The sole task remains `PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The immediate
hard condition is one intentional source checkpoint on the existing branch,
one resulting push/PR dual-CI acceptance, and one complete readiness gate.
After those pass, execute the already bounded production sequence without
repeating Stage A/B/fresh import: apply/verify `0017`, activate/reconcile the
single Dispatcher Secret, install exact default-suspended units, prove the
provider-free Worker-C to Worker-F fenced takeover and terminal/refund/deletion
cleanup, then decide Item 21 from native evidence.

### Pre-CI synthetic Secret fixture corrected before gate execution (2026-08-08)

- Checkpoint `e78eadb6ed5980a50f03031cc80ffe478406167b` was pushed once and
  created push run `31197650583` and pull-request run `31197654370`. A read-only
  gate audit then proved four synthetic provider-key fixture values would fail
  the existing tracked-file Secret detector even though they were not real
  credentials. Both runs were cancelled during unit tests before quality,
  readiness or compose execution; they are not acceptance evidence.
- The correction changes only those four synthetic test values to existing
  approved placeholders and removes their trailing literal newline so the
  source scanner sees the placeholder exactly. No gate allowlist/hash,
  production source, C17, image, template, readiness status or cloud resource
  changed. The three affected suites pass `28/28`; the targeted git-hygiene
  slice passes `6/6`; `git diff --check` passes.

Readiness remains internal `20/29` and public `20/38`. The sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The immediate hard condition is one
minimal fixture-fix checkpoint and its resulting push/PR dual-CI success,
followed by the single complete readiness-gate run and the bounded production
acceptance chain. The cancelled pre-fix runs must not be rerun.

### Item 21 production source accepted by dual CI and complete gate (2026-08-08)

- The minimal fixture correction is checkpoint
  `f1a5cc014578e10243174a80d643a67a57921c17`. Its push CI
  `31198299691` / job `92931838012` passed every step in `23m37s`; its
  pull-request CI `31198302530` / job `92931848859` passed every step in
  `25m27s`. Both bind the exact checkpoint and include unit tests, quality,
  production-readiness and compose checks.
- After and only after both CI runs succeeded, the complete local production
  readiness gate was run once and passed `138/138`, failed `0`. The branch is
  clean at the accepted checkpoint before this Secret-free record update.
- The earlier cancelled e78eadb runs remain non-evidence and were not rerun.
  No production connection, cloud mutation, database/storage write, image
  operation or provider/public call occurred in this acceptance stage.

Readiness remains internal `20/29` and public `20/38`; source acceptance alone
does not satisfy Item 21. The sole task remains
`PROD-FIRST-LAUNCH-DURABLE-AI-RUNTIME-001`. The immediate hard condition is the
native read-only production baseline: current balance and Worker-C/Worker-F
inventory/price, RDS private/backup/task-account zero state, ACR/VPC/Worker
network path, existing API-C/API-F health, and IAM/OSS residue. Only if that
baseline passes may the bounded paid Worker and synthetic database/OSS sequence
begin; C17 and Stage A/B/fresh import remain frozen.

### Production capacity baseline corrected to bounded PostPaid execution (2026-08-08)

- Native read-only billing request
  `019FDD30-67EE-5B6E-BD6F-23373159430E` reports `102.10 CNY`
  available cash and zero credit. The point-in-time `PrePaid / 1 Month`
  quotes for exact `ecs.c9a.xlarge` Worker-C and Worker-F shapes were each
  `391.72 CNY`: four vCPU, eight GiB memory, VPC networking, zero public
  bandwidth and one 40-GiB ESSD PL0 system disk. Quote requests
  `019FDD32-A3E1-59EB-829E-573060785D5F` and
  `019FDD33-397E-59EB-97D7-B61E69D832AB` both returned no promotion. The pair
  observation was `783.44 CNY`, with an arithmetic difference of `681.34 CNY`
  from the observed cash balance. That monthly PrePaid option is rejected: it
  is not the selected execution shape, a recharge target or a funding gate.
  The required replacement is a fresh exact `PostPaid + NoSpot` quote for two
  bounded private Workers, followed by current balance/stock qualification.
- Inventory requests `019FDD33-B216-5B0A-9DDF-C3CF66BE89CE` and
  `019FDD34-C0BA-5C6C-9223-D6B1AC91EFA3` report exact c9a stock
  `Available / WithStock` in Shenzhen C and F. The production VPC has an
  `Available` switch in each zone with 249 and 251 free addresses
  (`019FDD3B-5549-5B49-95BB-1F51FD77F067`), while native ACR read
  `019FDD3A-D898-5393-87A5-80F44E33BA30` confirms the public Registry endpoint
  disabled and the VPC endpoint enabled and linked to the production VPC.
- Native RDS reads prove one `Running` PostgreSQL 16 primary on VPC/Intranet,
  seven successful automated full snapshot backups in the last seven days,
  latest backup end `2026-08-07T13:04:43Z`, eight retained accounts and zero
  exact `noteai_schema_task_durable_ai_0017` account. Their request IDs are
  `019FDD36-D4BA-5860-9F4E-9EF38B30B232`,
  `019FDD37-365A-5BEA-B911-C9F1AF7F9225` and
  `019FDD37-9D17-5305-BC2C-C4BEAD7A95B6`.
- Exact-instance status request `019FDD3A-6E20-5177-8B5E-38B686230756` reports
  API-C, API-F and the retained old builder all initially `Running`. No order,
  Worker instance, database connection, database/storage write or
  provider/public call was made during this read-only baseline.

### Retained builder stopped without deleting prepared state (2026-08-08)

- The old builder `i-wz99180s9ig5ecq10uaj` is not a production service or an
  Item 21 dependency. Fresh exact-instance, Cloud Assistant, host-process,
  Docker-credential and system-disk checks established one idle PostPaid
  instance, zero active invocation, zero running container/build/download task,
  zero Docker auth/helper/store entry, zero PostgreSQL connection, no RAM role,
  no operation lock and no automatic release. Its encrypted 120-GiB system disk
  was `d-wz99180s9ig5ecpy5cup`, attached and lock-free.
- After that read-only baseline, exactly one graceful
  `StopInstance(ForceStop=false, StoppedMode=StopCharging, Hibernate=false)`
  succeeded with request `019FDE95-3FE2-5F69-9857-7212D712DCE1`. No duplicate
  submission occurred around interactive verification. Native instance read
  `019FDE97-AA0A-50FA-95A8-656A29F14031` then proved exact state
  `Stopped / StopCharging / PostPaid`, empty operation locks and empty
  `AutoReleaseTime`; disk read `019FDE99-BD5A-50EC-87D3-9F9E1F325B2E`
  proved the same encrypted system disk remains attached and `In_use`.
- The builder instance and disk were not deleted, so its accepted local cache
  and prepared state remain recoverable. This stops compute charging only;
  retained storage may still incur cost. API-C/API-F, RDS, OSS, ACR, IAM and
  production traffic were unchanged. The read-only baseline had zero cloud
  mutation; this separate cost-control action had exactly one lifecycle
  mutation.

Readiness stays internal `20/29` and public `20/38`; Item 21 remains
`unverified`. Execution is not gated by the rejected monthly quote. Refresh the
exact `PostPaid + NoSpot` two-Worker quote, current balance/qualification and
C/F stock once, finish the remaining API-health and IAM/OSS-residue read-only
checks, then execute the bounded Worker-C/Worker-F production chain. Do not
repeat CI, the complete readiness gate, Stage A/B or fresh import.

### Item 21 API health and private-storage baseline closed (2026-08-08)

- Fresh Cloud Assistant checks accepted the current API-C API/Admin pair and
  API-F API unit without reinstalling or restarting anything. API-C command
  `c-sz06tbndawcedxc` / invocation `t-sz06tbndawovvnk` and API-F command
  `c-sz06tbnjq42jjls` / invocation `t-sz06tbnjq4k0u0w` each completed once
  with exit `0`. Their result reads were
  `019FDEB1-E951-54CB-9CCC-E02EF7920F83` and
  `019FDEB3-BB9D-55B6-9942-BDA0ED78B192`. Exact installed unit and image
  identities passed; container counts were `2/1`; all three loopback
  live/ready rounds returned `200`; listener, unit restart, container restart
  and established PostgreSQL counts were respectively loopback-only, `0`, `0`
  and `0`. Four earlier strict read-only diagnostics failed closed because they
  applied stale Admin or non-contract runtime assertions; they made no service,
  container, database, provider or public-traffic change and are not acceptance
  evidence.
- Native RAM reads proved API-C and API-F still share exactly one persistent
  private-storage ECS role, the stopped builder has none, and the account has
  exactly one NoteAI role and one NoteAI custom policy. That policy is attached
  only to the persistent role and remains two statements with the exact four
  prefix-scoped OSS actions, zero wildcard action and zero global resource.
  The bounded request set is
  `019FDEB7-249A-538F-B73D-426C6D075C4C`,
  `019FDEB7-522B-511E-B64A-39EA912FF154`,
  `019FDEB7-75C5-556B-8346-B51AAD786902`,
  `019FDEB8-45E7-586A-A635-E4A33C7B9794`,
  `019FDEB8-93D3-53A8-938F-00C0BC76E3CB`,
  `019FDEB9-1369-5729-9F76-B2C6139ED7D5`,
  `019FDEB9-64C2-52E1-BC5E-4969BD9E2FBB`,
  `019FDEBD-2A49-5A70-B8B8-1B798E25AEEE` and
  `019FDEBD-C35B-5C31-B27D-D0BC71A059EA`. Temporary NoteAI RAM role/policy
  residue is therefore `0`.
- The persistent OSS bucket remains unique, Standard/private, bucket BPA on,
  AES256 encrypted, acceleration unset/disabled, logging target empty, bucket
  policy absent, versioning unset and lifecycle restricted to
  `noteai-private/` with two-day expiry and one-day incomplete-multipart abort.
  Fresh bounded inventories proved objects `0`, versions `0`, delete markers
  `0` and multipart uploads `0`. API-C/F then passed one corrected two-node
  metadata audit: both files are root:root `0600`, have the exact seven keys,
  no static AK, the internal endpoint and the persistent role. The first
  read-only attempt failed identically on both nodes because its assertion
  confused runtime prefix `noteai-private` with lifecycle prefix
  `noteai-private/`; corrected command `c-sz06tbpp4yfu9ds` / invocation
  `t-sz06tbpp4ynbyf4` passed twice with result request
  `019FDEC9-E287-5ED5-ADF9-BAF0793F2EEC`.
- The first fresh bucket inventory found one extra NoteAI bucket created at the
  Stage A transfer timestamp, matching the historical empty-bucket deletion
  that had stopped at interactive verification. Exact reads again proved its
  objects, versions, delete markers and multipart uploads all `0` via requests
  `6A7677F0CC8CEC3034E35A47`, `6A7677FFCF2E63393096A30E` and
  `6A76780EDDD87E3034C8E2E2`. Only that distinct empty temporary bucket was
  deleted (`204`, request `6A767821ABB8F83537D6DE31`). Final inventory request
  `6A7678478A6E183238F4BA18` proves account buckets `4`, Shenzhen buckets `2`,
  the persistent bucket exactly `1`, NoteAI buckets exactly `1`, and the Stage A
  temporary bucket absent. No persistent object was put or deleted.

Readiness remains internal `20/29` and public `20/38`; the baseline and cleanup
add no duplicate credit. The remaining pre-order condition is now only one
fresh exact `PostPaid + NoSpot` balance/qualification, C/F stock/network and
hourly-price bundle. Before either Worker can consume private storage it must
receive a separate Worker IAM identity; the existing API role must not be
reused. Do not repeat the API/OSS matrix, CI, the complete readiness gate,
Stage A/B or fresh import.

### Exact PostPaid Worker quote closed; small balance gap remains (2026-08-08)

- Current billing request `019FDECD-856A-522B-942C-03060D51D424` succeeded in
  CNY and returned available cash/amount `93.36`, credit `0.00`. This is below
  the provider's `100.00` PostPaid qualification line; no order or dry run was
  submitted after that fact.
- Fresh native instance-stock requests
  `019FDED0-5D52-5C3E-ACCE-8EC748CE3309` and
  `019FDED1-07EE-585B-98ED-000C54E451A8` prove exact
  `ecs.c9a.xlarge / PostPaid / NoSpot / VPC` stock is
  `Available / WithStock` in C and F. System-disk requests
  `019FDED1-40BF-57CF-A31A-22E05D8C2C10` and
  `019FDED1-7A9A-568F-A556-26AECD15C99F` prove `cloud_essd` is available in
  both zones with supported size range `20–2048 GiB`, so exact `40 GiB / PL0`
  is valid. VPC request `019FDECE-6D4D-5F7F-BE04-1D33FC953871` read the exact
  app switches as Available with `249/251` free addresses. ECS request
  `019FDECE-DA4F-5AAD-A7FC-1BD59840459C` found exactly one
  `noteai-prod-worker-sg` in the production VPC; attribute request
  `019FDECF-744C-5AF7-B157-82E1FC2D352F` proved ingress rules `0`.
- Exact hourly quote input was one `linux/amd64` Alibaba Cloud Linux 4 image,
  `ecs.c9a.xlarge`, VPC, no public bandwidth, no data disk, one encrypted-design
  `40 GiB ESSD PL0` system disk, `PriceUnit=Hour`, `Period=1`, `Amount=1` and
  `SpotStrategy=NoSpot`, queried separately for C and F. Each response is CNY
  with original/trade price `0.8164` and zero promotion. C result-latency caused
  one additional read-only quote request before the Workbench exposed the
  first result; the accepted C request is
  `019FDED2-1086-5F66-8FE9-EA20A20C909F` and F is
  `019FDED2-7705-58FF-92DF-EC98CC9182C9`. No quote carries cost or creates a
  resource, and neither zone will be queried again in this window.
- The two-Worker hourly ceiling is therefore `1.6328 CNY`. The CTO freezes a
  four-hour acceptance envelope, giving a conservative compute/disk quote cap
  of `6.5312 CNY`. The internal funding threshold is
  `100.00 + 6.5312 = 106.5312 CNY`; against `93.36 CNY`, the exact shortfall is
  `13.1712 CNY` (`13.18 CNY` after cent rounding). This replaces—not adds to—the
  rejected `681.34 CNY` monthly arithmetic observation.

Readiness remains `20/29` and `20/38`; Item 21 remains `unverified`. The only
immediate external blocker is the small balance shortfall. After at least
`13.18 CNY` is added (recommended operational round amount `15 CNY`), refresh
balance once only. If it reaches `106.5312 CNY`, continue with exact-name
absence, bounded dry runs and the two Worker orders without repeating the
accepted stock, network, price, API, IAM/OSS, CI, gate, Stage A/B or fresh-import
checks.

### Worker capacity funded, independent IAM bound and C/F hosts retained (2026-08-08)

- One balance-only refresh, request
  `019FDEE2-36B4-542D-A662-3A24660A75F2`, returned available cash/amount
  `122.71 CNY`. The `106.5312 CNY` internal threshold therefore passed; the
  rejected monthly PrePaid arithmetic remains neither a target nor a gate.
- A separate persistent Worker storage role and custom policy were created and
  attached by requests `019FDEE8-1D86-5D4F-A8CC-7E54E069CF0F`,
  `019FDEE8-80E1-59CB-A85B-3FDBD4C06B62` and
  `019FDEE9-1883-5BD0-B34E-0817796E26A2`. Native readback proved ECS-only
  trust, one exact role attachment, zero user/group attachment, two policy
  statements, four prefix-scoped OSS actions and no wildcard action/global
  resource. The API-C/API-F storage role was not reused or changed.
- Initial Workbench DryRun calls passed, but generated-CLI inspection proved
  that the first real C payload had omitted system-disk encryption and its
  second label. Native disk read `019FDEF8-4898-539C-A3B0-16ECD9D8C35E`
  confirmed `Encrypted=false`. That new blank host had received no image,
  Secret, unit, container or task data. It was gracefully stopped
  (`019FDEFC-5046-50B7-A298-440FB555D6FF`), read back `Stopped`, released
  (`019FDEFC-F118-5314-89E1-D4DDBA9E93B5`), then independently read back as
  instance count `0` and system-disk count `0` by
  `019FDEFD-203A-5131-B734-31B06603E9DF` and
  `019FDEFD-4F78-53A9-97D5-2FB5ED5CB8F9`. This closed a known rejected
  payload; it was not an ambiguous retry.
- Corrected nested v2 C/F requests explicitly serialized encrypted system
  disks, two labels and the primary-NIC boundary. DryRun requests
  `019FDEFE-47DD-54AC-9D99-3624D93AC941` and
  `019FDEFE-C638-515E-AA0B-3EAE90CF0657` both returned
  `DryRunOperation`. The final C/F creates succeeded exactly once with requests
  `019FDEFF-8402-5440-B03E-F46420F0DDC5` and
  `019FDF00-D277-52B4-BF37-9E3ADD14AA63`.
- Retained Worker-C `i-wz98zwcdtcmxzmmoso3w` and Worker-F
  `i-wz93qgvlu1bllpjcfwfj` are `Running / PostPaid / NoSpot`, one in each
  exact C/F switch, with no public IP, the zero-ingress Worker security group,
  two exact task/node labels and no operation lock. Each has one
  `40 GiB / cloud_essd / PL0` system disk
  with `Encrypted=true`, a non-empty provider KMS identity and the independent
  Worker role. Native instance/disk/role reads are respectively
  `019FDEFF-C692-5E22-BEE4-0FB80F11F157` /
  `019FDEFF-F628-544F-B2D3-119FA9DD4E77` /
  `019FDF00-2390-5809-BAE2-891B7EDE9296` for C and
  `019FDF01-1B40-55CA-A653-D601257CCDE4` /
  `019FDF01-4A9E-5E8D-BA9E-D295EE83EDEB` /
  `019FDF01-73A0-5D02-AC4E-C8E82B80560A` for F.
- The four-hour creation guard was not allowed to become a deletion deadline.
  After the capacity checkpoint, the provider-documented cancellation form
  (omit `AutoReleaseTime`) was applied once per retained Worker. Requests
  `019FDF0D-6E53-5E4F-BBD2-FF758533764F` and
  `019FDF0E-730B-55ED-8B68-4539F43C5794` returned HTTP `200`. Exact-instance
  reads `019FDF0E-C512-5E34-88CF-8D9E66878B6D` and
  `019FDF0E-EE33-5B6C-9612-192700CE4E41` then proved both Workers still
  `Running`, with `AutoReleaseTime=""` and no runtime, disk, network or IAM
  mutation. They are retained until deliberate lifecycle cleanup; this does
  not claim compute or disk cost is zero.

Readiness remains internal `20/29` and public `20/38`; Item 21 remains
`unverified`. The immediate hard condition is a fresh three-host baseline:
Cloud Assistant readiness, time, Docker/systemd, IMDSv2-only behavior, no
unexpected workload and exact C17 image availability/transport. Only after
that passes may encrypted Worker Secret transport, task-account migration
`0017`, Dispatcher activation, default-suspended units and provider-free C-to-F
takeover proceed. Do not repeat balance, stock, quote, API/OSS, CI, gate,
Stage A/B, fresh import or the rejected v1 payload.

### Item 21 host baseline is audit-ready but requires one client-side Workbench submission (2026-08-08)

- The official ECS `RunCommand` request was not submitted. Attempting to open
  the long prefilled Workbench URL was stopped by the Codex browser safety
  boundary before any provider request, `CommandId` or `InvokeId` existed.
  This is `PRE_CONNECT`: remote command submissions, host executions, service
  mutations, database/storage calls and public/provider traffic are all `0`.
  It is not a failed Cloud Assistant invocation and must not be blindly rerun.
- A fresh API-C role read, request
  `019FDF17-415D-5993-A515-58009795C1F3`, bound the preflight to the accepted
  API storage role; the independent Worker role remains the exact C/F
  expectation. The final local, untracked, Secret-free pretransport script is
  `/tmp/noteai-item21-host-baseline.sh`, SHA-256
  `6a65678a58bfe268983f9946dc6973b2a15db3a95bf0a3e72173fe281c56b4a5`.
  Bash and embedded-Python syntax pass, and two independent read-only reviews
  report `P0=0 / P1=0 / GO`.
- The script is read-only and fail closed: it disables proxies and redirects
  for link-local IMDS, never outputs temporary credentials, never reads an env
  file or Docker auth contents, never calls API health, database, OSS,
  Registry or public endpoints, and never starts/stops/enables a service or
  container. It emits only fixed labels, counts, booleans, role hash and exact
  C17 state. `absent` is explicitly pretransport-only; `drift/unknown` fails.
- The only hard condition is one user-mechanical submission of that exact
  script in the signed-in official Alibaba Workbench to API-C, Worker-C and
  Worker-F together (`RunShellScript`, plaintext, root, `/root`, timeout 120,
  repeat once, keep-command false). This is not a request for technical
  authorization or a design decision. After the one submission, only its
  returned native IDs may be polled; no second command is permitted because of
  a disconnect, delayed output or a failing host predicate.

Readiness remains internal `20/29` and public `20/38`; Item 21 remains
`unverified`. Both Workers remain `Running` with automatic release cancelled,
so the client boundary cannot delete or invalidate their accepted capacity.

### Worker capacity preserved in StopCharging while client action is unavailable (2026-08-08)

- The user was away from the computer and explicitly authorized the CTO to
  submit the host audit, but authorization cannot override the Codex browser's
  mandatory user-action boundary. No `RunCommand` was submitted. A new native
  Cloud Assistant read, request `019FDF1D-7965-5426-AEF1-69E342B5E48F`,
  proved both Workers healthy at the agent layer with `ActiveTaskCount=0`,
  `InvocationCount=0` and empty last-invoked time.
- To avoid paying for idle compute while preserving the accepted capacity,
  Worker-C and Worker-F were each stopped once through graceful
  `ForceStop=false / StoppedMode=StopCharging` requests
  `019FDF1D-EAC4-5DC8-9C0A-FED0ADCE35E4` and
  `019FDF1E-3515-54D5-9BC7-828E11DEF955`. Exact paired read
  `019FDF1E-66E5-5663-AD60-EBA453DFB095` proved both
  `Stopped / StopCharging`, empty `AutoReleaseTime` and zero operation locks.
- Disk read `019FDF1E-977B-5C84-AAB7-4E46E4457561` proved both original
  `40 GiB / cloud_essd / PL0 / Encrypted=true` system disks still exist,
  remain attached `In_use` to the exact Workers and were not detached,
  replaced or deleted. The independent Worker IAM, VPC, zero-ingress security
  group and all capacity acceptance remain intact. StopCharging removes idle
  compute charging only; retained disks and other provider resources may
  continue to incur cost.

Item 21 remains `20/29` and `unverified`. When the user is available for the
mandatory Workbench action, the CTO may restart both exact Workers, re-read
`Running` plus Cloud Assistant idle state, and then the user submits the one
fixed-hash host baseline. No recreate, new quote, new balance check or repeated
RunCommand is permitted.

### Unique three-host pretransport invocation closed; Worker Docker bootstrap is next (2026-08-08)

- Worker-C and Worker-F were restarted only from their retained
  `Stopped/StopCharging` state. Start requests
  `019FE121-EE5B-5F1A-8A9E-05FF7E657ACF` and
  `019FE122-303C-50BE-9B94-1EABCCBC63D8`, followed by exact paired read
  `019FE122-8D0E-519C-A16F-619D3AD8055C`, proved both exact instances
  `Running`, `StoppedMode=Not-applicable`, empty `AutoReleaseTime` and zero
  operation locks. Cloud Assistant read
  `019FE122-D195-53E7-BEB1-125CDD97B1E0` proved both agents healthy and idle
  before submission (`ActiveTaskCount=0`, `InvocationCount=0`).
- The independently accepted script SHA-256
  `6a65678a58bfe268983f9946dc6973b2a15db3a95bf0a3e72173fe281c56b4a5`
  was submitted exactly once to API-C, Worker-C and Worker-F. Native request
  `019FE12B-CD7D-5C47-B409-B5769AB4BD57` returned command
  `c-sz06tdd5m0d67sw` and invocation `t-sz06tdd5m0znaww`. Read-only result
  request `019FE12D-EC83-5E85-BC02-86186B17DCDF` returned exactly three
  terminal records, each `Repeats=1`, with no dropped output. Exit code `3` is
  the script's intentional fail-closed diagnostic result and is not grounds to
  resubmit the command.
- API-C passed its exact role, IMDSv2-only, NTP, systemd, capacity, expected
  two-container, no-task/no-unit/no-task-root and zero-established-5432
  checks. Docker is `active/enabled`, server `28.3.3 / linux / amd64`, and C17
  is natively `absent`, so fixed-digest transport is required. Its sole failed
  predicate is one metadata-only Docker config-file presence signal
  (`docker_auth_file_count=1`, unsafe-file count `0`); no auth content or value
  was read. The file is not a C17-transport blocker: the already-defined
  isolated `DOCKER_CONFIG` path neither reads nor changes it. Do not delete or
  rewrite it merely to satisfy the deliberately conservative baseline; any
  later semantic audit is a separate read-only security observation.
- Worker-C and Worker-F passed exact Alibaba Cloud Linux 4/x86_64, NTP,
  systemd, IMDSv2-only, independent Worker role, valid temporary credential
  shape, roughly `7 GiB` available memory, `34,793 MiB` root free space,
  zero containers/tasks/units/task roots and zero established PostgreSQL
  connections. Both hosts lack an active/enabled Docker service, so Docker
  queries fail closed and C17 is correctly `unknown`, not `absent`. This is a
  concrete bootstrap prerequisite, not a cache-export or C17 defect.

Readiness remains internal `20/29` and public `20/38`; Item 21 remains
`unverified`. The next hard condition is one bounded, minimal Docker Engine
bootstrap on Worker-C/F followed by targeted post-bootstrap native readback.
Do not repeat this baseline invocation. After both Workers have healthy
`linux/amd64` Docker, the fixed C17 digest may be transported to the missing
hosts through isolated root-only Docker configs, still without reading or
changing API-C's existing candidate config file, starting a container or
changing API/Admin service state.

### Worker-C/F Docker bootstrap accepted; fixed C17 transport is next (2026-08-08)

- The final bootstrap payload was fixed at SHA-256
  `aac64a189accda87fc961646122d18cf554969f4802a9ce63f960df3264680a4`
  and was submitted through a 9,156-byte in-memory gzip wrapper, SHA-256
  `d24926dd485ff3fec91e8247d5028bd1c6bbeeab88f2f7ae1441706f7151c6cb`.
  The wrapper verified the 17,956-byte decoded payload and its hash before one
  `/bin/bash` child; it created no transfer file. This avoided the Workbench
  UI's observed 10,000-byte input truncation without changing execution
  semantics.
- Exact-one Cloud Assistant command `c-sz06tdguybf045c` / invocation
  `t-sz06tdguybyzaww` targeted Worker-C and Worker-F together. Native result
  requests `019FE159-DA35-5997-B392-8B97DCA9B374` and
  `019FE159-DA33-504B-9B3E-D8248C1A0754` returned two terminal records, both
  `Finished / Success / ExitCode=0 / Dropped=0 / Repeats=1`, from
  `2026-08-08T12:21:04Z` through `12:21:10Z`. Native readback reported
  `TerminationMode=Process`; because both children completed normally in six
  seconds, this is a non-impacting observed parameter fact, not grounds to
  rerun.
- Both hosts now have identical Alibaba Linux packages
  `moby`, `moby-client` and `moby-engine` at `28.3.3-4.alnx4.x86_64`.
  Docker and containerd are active, Docker is enabled, the default engine is
  `28.3.3 / linux / amd64`, the data root has `34,483 MiB` free, and TCP Docker
  listeners, containers, images, volumes, build cache, Docker auth files,
  registry logins, pulls, container starts, task paths and established `5432`
  connections are all `0`. C17 is explicitly `absent` on both Workers.
- Each host emitted the same two non-JSON `awk` warning lines from a quoting
  expression (four warning lines in aggregate); every fixed postcondition passed with
  `host_pass=true / failed_checks=[]`. The bootstrap made exactly the intended
  one package/service mutation per host, two in aggregate, and made no C17,
  database, storage-object, Registry or AI-provider call. It must not be
  repeated for warning wording.

Readiness remains internal `20/29` and public `20/38`; Item 21 remains
`unverified`. The host runtime bootstrap prerequisite is closed. The unique
next hard condition is serial private transport of the fixed C17 manifest to
Worker-C, Worker-F and API-C through per-host isolated root-only Docker
configs, with one digest pull per missing host, exact image inspection, zero
container starts and complete credential/task-root cleanup. API-C's existing
candidate Docker config path remains untouched.

### Three-host C17 transport keygen accepted; JIT pull broker is next (2026-08-08)

- The independently accepted 5,843-byte keygen payload, SHA-256
  `625b70de101bd25a732757898766b96f2d1a9c8ad408c522657affe2bc06cf6d`,
  was carried by a 3,546-byte one-line in-memory gzip wrapper, SHA-256
  `4becf54161db18ba5459dbdd2d5ce7493a9931dca8e6e346ea32724273c6f630`.
  The wrapper verified the decoded length and hash before one `/bin/bash`
  child and created no transfer file.
- Exact-one native request `019FE1B3-5B90-5A81-84E9-63D5C9D12BF7`
  returned command `c-sz06tdqd3f6wpog` and invocation
  `t-sz06tdqd3foe03k`. Read-only result request
  `019FE1B4-CDFB-5DEA-AA1D-D09DC290D8C4` returned exactly one invocation and
  three records, all `Finished / Success / ExitCode=0 / Repeats=1 /
  Dropped=0`, from `2026-08-08T14:07:37Z` through `14:07:38Z`.
- API-C, Worker-C and Worker-F each produced one canonical RSA-3072 public
  key. Their public DER hashes are respectively
  `8521a6f989194eb570f698ee59ae17dad256220c41abba19b03c2595abda4fb6`,
  `c7babaa2752547540e63e71c4788ec122d7bd1caea895b2178b2592879a3496c`
  and `e0207fe48a21b962bc6b5f84554e68bcfee4762278aff25ea24d93d318cdb46f`;
  all three are distinct and independently matched the native output. No
  private key appeared in output. Each host deliberately retains one
  root-only key root for immediate credential-envelope consumption. Because
  those roots live under volatile `/run`, API-C, Worker-C and Worker-F must not
  be stopped or rebooted until the matching transport consumes each root or a
  terminal failure is read back and its residue cleanup is closed.
- Registry credential issuance, image pulls, container starts, database
  connections and storage calls remain zero. This invocation is terminal and
  must not be repeated merely because later transport or wording fails.

Readiness remains internal `20/29` and public `20/38`; Item 21 remains
`unverified`. The unique next hard condition is a bounded temporary pull-only
broker on the retained Stopped/StopCharging builder, followed by exactly one
JIT credential and at most one fixed-digest pull per host in strict
Worker-C, Worker-F, API-C order. Every host must pass exact C17 inspection and
credential/key/task-root cleanup before the next host; pull-started UNKNOWN is
read back and never resubmitted. After all three terminal results, remove the
temporary broker IAM and return the builder to Stopped/StopCharging, then
continue Worker Secret, migration `0017`, Dispatcher, units and fenced
takeover without repeating closed stages.
