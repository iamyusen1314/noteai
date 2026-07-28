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
- Current pushed pre-policy checkpoint:
  `54914710be70b9bcafb80be8b74da21c04da5e11`.
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

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`

- Status: `IN PROGRESS / ROLE RISK ACCEPTED / SCHEMA WRITE NOT STARTED`.
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
- Production schema apply is now the next separately named write incident. It
  remains forbidden until the exact policy checkpoint is committed/pushed and
  a new hash-verified package from that checkpoint passes zero-DSN validation.

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

## 7. Active temporary material and non-regression

- Cleanup is intentionally deferred until the separately named schema
  transaction and outcome audit finish.
- API-C has exactly one task directory containing the verified v2c source,
  protected RSA/ciphertext and immutable read-only result; audit/import
  containers and runner processes are zero.
- API-F task directory, audit/import containers and runner processes: zero.
- API-C API and Admin: active, live/ready `200`, one loopback listener each,
  zero non-loopback listeners.
- API-F API: active, live/ready `200`, one loopback listener, zero non-loopback
  listeners.
- API-F API env file: root-owned `0600`, not a symlink; no value was read.
- Service restarts, deployments, provider submissions and public-traffic
  requests: zero.
- Fresh RDS control plane: one instance/one running, one network record/zero
  public endpoint, two successful full backups inside 48 hours, newest backup
  under 24 hours, data/log retention both 14 days, and
  `4 accounts / 2 Super / 1 task account`.
- Fresh API-C: API and Admin active, live/ready pass, loopback-only, root-owned
  `0600` non-symlink env metadata pass; the only task residual is the exact
  active role/schema task directory.
- Fresh API-F: API active, live/ready pass, loopback-only, root-owned `0600`
  non-symlink env metadata pass, fixed task residual zero.
- Cloud Shell home retains four known task uploads; no Secret plaintext is
  stored there. They must be removed during final cleanup.
- Secret-free baseline artifact:
  `deploy/production/evidence/production-schema-role-resume-baseline-20260728.json`.
  SHA-256:
  `d22d5f061d61c34fa03eaa6102ddab8da57439a5f1237834ee9da4308fda2355`.
- One broad control-console observation transiently emitted cloud resource
  metadata in internal tool output. It contained no Secret, credential or user
  data, was not persisted to Git, submitted to a provider or exposed publicly,
  and all subsequent output was reduced to bounded counts/booleans.

## 8. Repository checkpoint scope and verification

- `tools/production_schema_roles.py`
- `scripts/postgres/noteai_production_runtime_roles.sql`
- `tools/production_schema_outcome_audit.py`
- `tools/production_first_launch_role_risk_set_audit.py`
- `tools/production_first_launch_role_risk_set_audit_runner.sh`
- `tools/production_first_launch_role_risk_audit.py`
- `tools/production_first_launch_role_risk_audit_runner.sh`
- `tools/internal_deployment_readiness_gate.py`
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

- Historical focused schema/role/outcome/readiness suites: `66/66`.
- Current role-policy delta suites: `38/38`.
- Full Python suite: `1028/1028`, with `25` explicit skips.
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

1. Preserve the old UNKNOWN artifact and its exact classification/outcomes.
2. Treat the new set-based read-only audit as a fresh incident, never as a
   retry of the historical auditor.
3. Implement fixed-length set-based SQL and repair the schema executor before
   any production database action. This is complete on disposable PostgreSQL
   16.
4. Rebuild the minimal package from the exact committed source, require all
   hashes, registry evidence, zero-DSN import and network-none import.
5. Only then create the minimum short-term protected access material and run
   the single new read-only connection. DSN must enter by protected stdin or
   another ephemeral no-environment channel and must never be emitted.
6. The two fixed zero-credit `ACCEPTED_RISK` entries are now active. Preserve
   them as risk records, never as readiness credit or `VERIFIED_FIXED`.
7. Commit and push the exact policy checkpoint, rebuild the minimal package
   from that commit, verify every hash and both zero-DSN imports, then open the
   separate write incident with an advisory lock and locked precondition before
   the first DDL/DML. Its exact write ceiling remains 8 legacy SHA updates,
   8 migration ledger inserts and 2 fixed seed inserts; retention backfill and
   existing business-row updates remain zero.
