# NoteAI Internal Production Readiness Handoff

> Updated: 2026-07-28 (Asia/Shanghai)
>
> This file is the sole current Handoff instruction source. Re-read it, Git,
> the readiness manifest and the risk register after any context compression.

## 1. Objective and authority

- Umbrella task: `PROD-COMPLETE-FIRST-LAUNCH-001`.
- Goal: reach internal deployment readiness `29/29` through finite, bounded,
  reversible and independently evidenced work.
- Main CTO may approve bounded internal-production actions without repeated
  approval.
- Stop for interactive login/new credentials, public DNS or real traffic,
  irreversible destruction, uncapped cost, a new product decision, public
  launch completion, a real security conflict, a database-connected UNKNOWN
  result or genuine technical inability.
- Never emit or persist Secret values, private keys, passwords, cookies, full
  connection strings, IP addresses, cloud resource IDs, user data or long raw
  logs. Never force-push, merge directly to `main`, run concurrent production
  writes or automatically retry a database-connected failure.

## 2. Git and readiness truth

- Branch: `codex/quality-stabilization-real-chain`.
- V3B source/policy checkpoint:
  `39f6d046eb22870484baadb5b745316efacd0044`.
- Resolve the current incident checkpoint from the newest pushed
  `[skip render] Record deterministic schema rollback` commit; this Handoff
  is part of that commit and must not attempt a self-referential hash.
- Deterministic rollback checkpoint:
  `7c24c81cba9237be53a6d2ec11bfa4d91e6921b0`.
- Resolve the stage-safe authority checkpoint from the newest pushed
  `[skip render] Prepare stage-safe schema authority path` commit after this
  Handoff is committed; do not embed a self-referential hash.
- Stage-safe authority checkpoint:
  `b9396ab709cf6fd2f3b9b45964617205452ee5c1`.
- Resolve the fixed V4 runner checkpoint from the newest pushed
  `[skip render] Stabilize V4 schema runner` commit after this Handoff is
  committed; do not embed a self-referential hash.
- Historical UNKNOWN incident source checkpoint:
  `a5f2961089744eb1c0bf0eb0011b93a132d6493f`.
- Schema executor repair:
  `e5883abc01c4b009907bee550209d7036d383771`.
- Upstream divergence before the incident: `0/0`.
- Repository/isolated readiness: `12/12`.
- Internal deployment readiness: `14/29 = 48%`.
- Public launch completion: false.
- This Handoff and its evidence must be committed and pushed as a new
  `[skip render]` checkpoint. Resolve that checkpoint with `git log` rather
  than assuming the incident source commit is current HEAD.

## 3. Unique task and current incident boundary

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V4-001`

- Status:
  `PRE_CONNECT / PACKAGE VERIFIED / NOT DISPATCHED / CLEAN`.
- Parent task:
  `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`.
- Repository authority-resolution task
  `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-AUTHORITY-RESOLUTION-002` is complete:
  fixed stage-safe failure codes, independent tests, disposable PostgreSQL 16
  integration and the non-mutating managed-RDS authority plan passed without
  changing migration or runtime-ACL bytes.
- The historical read-only artifact remains exactly
  `CONNECTED_UNKNOWN`; its database and transaction outcomes remain
  `UNKNOWN`, and it has not been reclassified or retried.
- Product-owner/CTO authorization operationally closes only that historical
  read-only incident as `HISTORICAL_CLOSED_BY_AUTHORIZED_IMPACT_BOUND`.
  The bound is source-proven: the pinned auditor contains only fixed session
  `SET`, `SHOW`, catalog `SELECT` and built-in privilege `SELECT` statements;
  its runner invokes no schema executor; schema apply count was zero.
- A materially different database incident is now opened. It is not an
  automatic retry and must use new audit/run IDs, directory, sentinels,
  application name, fixed set-based SQL and a separate evidence artifact.
- Exactly two fixed accepted-risk entries are active with zero readiness
  credit. Neither is `VERIFIED_FIXED`, neither authorizes a database action,
  and both are reviewed 30 days after first public launch.
- New read-only incident:
  `PROD-FIRST-LAUNCH-LEGACY-ROLE-RISK-SET-AUDIT-002`;
  run `PROD-FIRST-LAUNCH-LEGACY-ROLE-RISK-SET-AUDIT-RUN-001`;
  directory `/var/lib/noteai/role-risk-set-audit-v2`;
  application name `noteai_role_risk_set_audit_v2`.
- Before its one permitted connection, the main CTO must finish local
  PostgreSQL 16 validation and rebuild a minimal hash-verified package.
- The new database path is limited to one connection and one
  `REPEATABLE READ READ ONLY` transaction with fixed stages:
  `session`, `ledger_inventory`, `role_graph`, `xhs_acl`, terminal `ROLLBACK`.
- The new audit completed all stages with terminal `ROLLBACK`, one connection,
  database writes zero and a deterministic `CONNECTED_KNOWN` result. It must
  not be repeated.
- Production schema V3B apply used one connection and one bounded transaction.
  Its runner returned the fixed `execution_failed` code after dispatch and was
  not retried. The independent forced-readonly outcome audit deterministically
  classified the database transaction `ROLLED_BACK`.
- Production remains exactly at migrations `0001`-`0008`, 30 public tables,
  5 sequences and the 2 historical runtime roles. New roles, new tables,
  migration SHA backfills, new ledger rows, seed rows, retention backfill,
  existing business-row updates and total database writes are all zero.
- The next task is the separately named
  `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V4-001`. It may start only after
  the stage-safe source, plan and tests are committed and pushed. It is a new
  incident, cannot inherit V3B retry authority and permits at most one schema
  transaction.

## 4. Product-owner first-launch risk decision

- Alibaba provider support is optional after launch and is not an internal
  readiness or first-launch hard blocker.
- Existing `noteai_xhs -> noteai_admin` membership may be accepted for first
  launch only after fresh read-only proof of the exact
  `ADMIN / INHERIT / SET` options and complete effective privilege matrix.
- Existing `noteai_app ROLINHERIT` may be accepted only after fresh proof that
  it inherits zero high-privilege roles.
- The decision authorizes no new role, `ADMIN OPTION`, DDL, role management or
  extra database privilege for `noteai_xhs`.
- The two findings must be `ACCEPTED_RISK`, never `VERIFIED_FIXED`, receive
  zero readiness credit and be reviewed 30 days after first public launch.
- Repository gate support is limited to the fixed profile
  `FIRST_LAUNCH_LEGACY_ROLE_RISK_V1` and exactly two fixed risk IDs. There is
  no global waiver.
- Activation is true only for the exact observed tuple
  `ADMIN TRUE / INHERIT FALSE / SET FALSE` and for `noteai_app ROLINHERIT`
  with incoming membership zero and high-privilege inheritance zero. Backup
  freshness, zero public RDS endpoint, protected runtime env metadata and
  loopback-only services are freshly proven.

## 5. Current incident evidence

Current Secret-free artifact:

`deploy/production/evidence/production-first-launch-role-risk-accepted-20260728.json`

Artifact SHA-256:

`2f25268539ee48d73bb6dcbff9af7ef8a9115d2e8a542f93fff29b9fa9b44c97`

Deterministic facts:

- Metadata-free ustar package: 25 files, 16 migrations, 24/24 hashes,
  62,275 bytes, SHA-256
  `84cfdea3f218168daa929f4f27536d13965999d7f1f6db84d5d1de588a1faa7a`.
- Local zero-DSN import and remote `--network none` import passed.
- One short-term protected Super account and one 3072-bit RSA pair were
  created; plaintext persistence/environment/argv/log exposure counts are 0.
- The audit made one database connection and one four-query
  `REPEATABLE READ READ ONLY` transaction, then rolled back.
- Result: 3,845 bytes, SHA-256
  `59475549a9c969c9edd9019e656456861ac00bcadc09e7e1b13c30dadd645400`;
  database writes 0, business-row values read 0, automatic retries 0.
- Ledger is exactly `0001`–`0008`; inventory is 30 tables and 5 sequences;
  new roles/tables, legacy SHA column/constraint and retention sources are 0.
- The only legacy membership is
  `noteai_xhs -> noteai_admin / ADMIN TRUE / INHERIT FALSE / SET FALSE`.
- `noteai_app` incoming membership and high-privilege inheritance are both 0.
- XHS database/schema/table/column/sequence/function/ownership/default-ACL
  negative matrix is exact with mismatch and grantable counts 0.
- The raw auditor returned `state_changed` only because its pre-observation
  profile pinned historical `INHERIT TRUE`. Session, ledger and XHS ACL all
  passed. The fixed accepted-risk profile is now narrowed to observed
  `INHERIT FALSE`; migration bytes and SHA values are unchanged.
- Focused repository tests: `38/38`; disposable PostgreSQL 16 complete
  apply/apply-twice/six-negative-mutation integration: `1/1`; local task
  container count 0 and Colima restored stopped.

The old
`production-first-launch-role-risk-readonly-unknown-20260728.json` remains
historical and unchanged. It is not reclassified or used as current evidence.

## 6. PRE_CONNECT incidents

All of the following were proven before database dispatch from sentinels,
containers and result state, then materially corrected:

- source directory mode blocked the non-root import container;
- the first minimal package omitted transitive registry evidence;
- the replacement archive contained macOS AppleDouble metadata;
- one root AppleDouble metadata file survived the first exclusion pass;
- the Chrome file chooser timed out before any send-file execution.

No database connection, transaction or write occurred in those incidents.
They do not weaken either the preserved historical `CONNECTED_UNKNOWN` record
or the fresh deterministic `CONNECTED_KNOWN` audit.

Current resume-stage failures were also bounded `PRE_CONNECT` with database
connection/transaction/write all zero:

- the first V4 archive omitted the read-only preflight module and the fixed
  registry evidence that module reads at import time;
- the in-app browser had no authenticated Alibaba session;
- the initial ECS topology filter included one non-API node;
- three Cloud Assistant control attempts omitted the required Base64
  `ContentEncoding` declaration or inherited that output-contract error;
- two failure branches exited the temporary Cloud Shell before the wrapper was
  isolated in a subshell.
- one result parser used an unavailable remote command path and exited `127`
  after the database audit had already produced its immutable result;
- two parser dispatch wrappers selected the Cloud Shell UI region instead of
  the business ECS region and exited before remote dispatch.

The material correction uses the existing authenticated Chrome session,
project-and-zone API-node selection, explicit `ContentEncoding=Base64`,
`InvocationStatus=Success` plus exit-code-zero validation, and isolated
Secret-free failure handling. These incidents did not create a database
account, DSN, transaction, host task directory, persistent command file or
service change.

## 7. V3B transaction, cleanup and non-regression

- Secret-free incident artifact:
  `deploy/production/evidence/production-schema-role-apply-rolled-back-20260728.json`.
  Artifact SHA-256:
  `c7011ea6d248e18414d74b3bb62d8d4d86834cf9ef884823d861b0934f5e9887`.
- The V3B package had 25 files, 16 migrations and 24/24 registry hashes.
  Its manifest, executor, outcome-auditor and runtime-ACL hashes matched;
  local zero-DSN import, remote network-none import and the corrected
  byte-oriented network-none DSN validator passed.
- The first validator failures were `PRE_CONNECT`: generated Python source
  contained a literal newline. The material fix removed that escape boundary;
  connection, transaction and write counts for those failures were zero.
- The production runner SHA-256 was
  `f252ede25bf5760b2a550348f606ad818eddebafa4f86cb342c0088749743f2a`.
  It created prepared and dispatch sentinels, then returned the 51-byte fixed
  `execution_failed` error with SHA-256
  `2d5512e8d01ce69b325d7a48b10f2515080c1888d20acabe78b752808aa7fdb3`.
  Automatic retries were zero.
- The independent forced-readonly outcome audit used one connection with
  `default_transaction_read_only=on`; its transaction rolled back and its
  1,410-byte result SHA-256 was
  `f7107f1c29d44904a4b71906f8f2ceead1d138685694838d396f59793baa95f3`.
  The deterministic outcome is `ROLLED_BACK`, not `UNKNOWN`.
- A supplemental aggregate authority diagnostic failed after a read-only
  connection with sanitized class `UndefinedColumn`. It had no mutation path,
  wrote zero rows, left zero container/process residue and was not repeated.
- The short-term Super account was deleted and the control plane read back
  `3 accounts / 1 Super / 0 task accounts`.
- API-C's fixed task directory was deleted. RSA/private-key, ciphertext,
  source package, result/error/sentinel files, task containers and task
  processes are all zero.
- API-F task directories, task containers and task processes are zero.
- API-C API and Admin: active, live/ready `200`, one loopback listener each,
  zero non-loopback listeners.
- API-F API: active, live/ready `200`, one loopback listener, zero non-loopback
  listeners.
- Service restarts, deployments, provider submissions and public-traffic
  requests: zero.
- Final RDS control plane: one instance/one running, one network record/zero
  public endpoint, two successful full backups inside 48 hours and newest
  full-backup age zero hours at readback.
- Cloud Shell task files and task variables are zero.
- Post-incident focused schema/outcome/readiness tests: `30/30`.
- Production readiness gate: `105/105 PASS`; internal readiness remains
  fail-closed `14/29 = 48%`; public launch readiness remains `14/38 = 37%`.
- Both JSON parses, Python compile, changed-file Secret/resource scan,
  `git diff --check` and upstream pre-commit baseline `0/0`: pass.
- Secret-free baseline artifact:
  `deploy/production/evidence/production-schema-role-resume-baseline-20260728.json`.
  SHA-256:
  `d22d5f061d61c34fa03eaa6102ddab8da57439a5f1237834ee9da4308fda2355`.
- Secret-free authority-resolution plan:
  `deploy/production/evidence/production-schema-authority-resolution-plan-20260728.json`.
  Artifact SHA-256:
  `e567d0918c8e47e4351430d3a0be799e831c76ba605ce19bd69576082f01b7b9`.
  It records zero database/cloud/service/provider actions, 16 fixed failure
  stages, unchanged migration/runtime-ACL hashes, the official managed-RDS
  privileged-account authority path and a three-part bounded Cloud Assistant
  `SendFile` transfer design. Provider support is not required.
- The V4 package is now rebuilt only from pushed checkpoint
  `8f6b8b68e24726ab6a57abfb805b9fd222238d0f`: 26 source files including
  its manifest, 25/25 hashes, 16 migrations, 64,252 bytes and deterministic
  archive SHA-256
  `0e16fd34404319902b1f15b9b1bccce6394f0ade5fb09ca0dd3979e1158bac5a`.
  It has 34 ustar entries, zero AppleDouble/nonregular members and three
  bounded parts with maximum raw/Base64 sizes 23,000/30,668 bytes, below the
  documented 32,768-byte Base64 SendFile limit.
- Explicit local import from the package itself passed with every supported
  database URL and confirmation environment variable removed. The preceding
  package omitted the transitive read-only preflight module and its fixed
  registry evidence dependency; it is classified `PRE_CONNECT` with account,
  database connection, transaction, write and cloud mutation counts all zero.
- Fixed runner SHA-256:
  `d104aafbd93b81c3250db1bb2aefbf39ddf5e22c5ec42a5739b9b8743e36c300`.
  Its four modes are `prepare`, `preflight`, `apply` and `outcome`.
  `prepare` performs the one network-none import without database material
  and binds its sentinel to the package manifest SHA. Database modes receive
  the protected value only through RSA-OAEP-SHA256 decrypt-to-stdin; the value
  is never placed in environment variables, argv or result logs.
- Stage-safe executor unit tests passed `15/15`; the disposable PostgreSQL 16
  first-apply/apply-twice/outcome/six-negative-mutation integration passed
  `1/1`. The exact task container was deleted and Colima restored stopped.
- One broad control-console observation transiently emitted cloud resource
  metadata in internal tool output. It contained no Secret, credential or user
  data, was not persisted to Git, submitted to a provider or exposed publicly,
  and all subsequent output was reduced to bounded counts/booleans.

## 8. Repository checkpoint scope and verification

- `tools/production_schema_roles.py`
- `scripts/postgres/noteai_production_runtime_roles.sql`
- `tools/production_schema_outcome_audit.py`
- `tools/production_schema_roles_runner.sh`
- `tools/production_first_launch_role_risk_set_audit.py`
- `tools/production_first_launch_role_risk_set_audit_runner.sh`
- `tools/production_first_launch_role_risk_audit.py`
- `tools/production_first_launch_role_risk_audit_runner.sh`
- `tools/internal_deployment_readiness_gate.py`
- `deploy/production/evidence/production-schema-authority-resolution-plan-20260728.json`
- `tests/test_production_schema_roles.py`
- `tests/test_internal_deployment_readiness_gate.py`
- focused tests for the executor, outcome auditor, role-risk auditor and gate
- historical role-audit/corrector tests that preserve the e5883 hashes, require
  current source drift to fail closed, and mock source validation only when
  testing downstream incident classification
- the incident evidence, readiness manifest, this Handoff and risk register

The current code allows only the exact historical first-launch profile,
requires unchanged `session_user/current_user/current_role` and a
non-`noteai_xhs` executor, and rejects any extra membership, elevation,
ownership, table/column/sequence/function privilege, grant option or default
ACL. The write executor takes the advisory lock first, locks the exact ledger,
inventory, role fingerprint and zero retention source before DDL, verifies
exact rowcounts, exact seed fields and the full negative matrix, and leaves
readiness scoring unchanged.

Unexpected executor failures now become a fixed
`apply_<stage>_failed` code across 16 bounded stages; pre-connection failures
become `database_connection_failed`. Existing fail-closed contract codes are
preserved, and exception text, DSNs and Secret material are never emitted.

- Historical focused schema/role/outcome/readiness suites: `66/66`.
- Current role-policy delta suites: `38/38`.
- Initial stage-safe checkpoint suites: `35/35`.
- Current fixed-runner schema/outcome/readiness suites: `37/37`.
- Full Python suite: `1035/1035`, with `25` explicit skips.
- Disposable PostgreSQL 16 integration: one complete legacy setup, fixed
  `INHERIT FALSE` risk profile, fixed read-only audit, exact first apply,
  apply-twice, independent outcome audit, six negative mutations and final
  clean outcome: pass.
- Exact first-apply writes: 8 legacy SHA updates, 8 migration ledger inserts,
  2 seed inserts, retention backfill 0, existing business-row updates 0.
- Apply-twice writes: all five categories 0.
- Production readiness gate: `105/105 PASS`.
- Internal readiness gate: fail-closed `14/29 = 48%`; public launch
  `14/38 = 37%`; active accepted-risk entries `2`, readiness credit `0`.
- Python compile, runner shell syntax, both JSON parses, sensitive-pattern scan
  with zero matches and `git diff --check`: pass.
- No database, cloud, service, provider, public-traffic or Secret-bearing action
  occurred during repository verification. The disposable local PostgreSQL
  container was deleted and Colima restored to its stopped baseline.
- Secret-free local validation artifact:
  `deploy/production/evidence/production-schema-role-v2-local-validation-20260728.json`.
  SHA-256:
  `08b9eb81a1943c06da47bf55d6cedc68f4e32e3a185e38a74c03c596d94d02e7`.

## 9. Mandatory failure classification

After any failure, collect Secret-free command fingerprint, sentinel, process,
container, connection, transaction and result evidence before classifying:

1. `PRE_CONNECT`: prove connection/transaction/write are zero. Clean exact
   transient material and continue only after a material fix.
2. `CONNECTED_KNOWN`: preserve the deterministic result, never retry that
   database action, clean and stop at its incident boundary.
3. `CONNECTED_UNKNOWN`: no automatic retry or new database action. Preserve
   evidence, clean and wait for the allowed external resolution/product-owner
   incident decision.

An outer browser, terminal or control-plane failure does not establish
`PRE_CONNECT` by itself.

## 10. Exact resume boundary

1. Preserve both historical UNKNOWN artifacts and the new V3B
   `CONNECTED_KNOWN / ROLLED_BACK` artifact without reclassification.
2. Never retry
   `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V3B-001`.
3. Keep the two fixed zero-credit `ACCEPTED_RISK` entries active exactly as
   observed; neither is `VERIFIED_FIXED` and neither authorizes a database
   action.
4. Treat
   `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-AUTHORITY-RESOLUTION-002` as complete
   only after its stage-safe source, tests and Secret-free plan are committed
   and pushed.
5. Open
   `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-V4-001` only from that pushed
   checkpoint. First re-prove fresh backup, private RDS, zero task residue,
   API-C/API-F/Admin non-regression, exact `0001`-`0008` ledger and the two
   accepted-risk tuples.
6. Build one metadata-free minimal archive from the pushed checkpoint, split
   it into bounded hash-addressed parts and use Cloud Assistant `SendFile`
   rather than terminal-embedded source chunks. The local deterministic build
   and zero-DSN import are complete; verify each remote part, reconstructed
   archive and network-none import before any protected account is created.
7. Create one new short-term managed RDS privileged account only after the
   zero-DSN and network-none imports pass. Permit one schema transaction, zero
   automatic retries and no owner or accepted-risk role changes.
8. A connected failure may be followed only by the predeclared independent
   forced-readonly outcome audit needed to classify `COMMITTED`,
   `ROLLED_BACK` or `UNKNOWN`; it never authorizes another mutation.
9. Until V4 independently verifies the committed state, production remains
   `0001`-`0008`, `production_schema_roles` remains blocked and internal
   readiness remains `14/29`.
