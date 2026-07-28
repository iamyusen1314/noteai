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
- Incident source checkpoint:
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

## 3. Unique task and mandatory stop boundary

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`

- Status: `BLOCKED / CONNECTED_UNKNOWN / NO DATABASE RETRY`.
- No schema apply was attempted in this incident.
- No accepted-risk entry is active and no readiness credit was added.
- Do not run another database connection, role audit, schema transaction or
  downstream database-dependent task.
- Read-only host/control-plane diagnosis, evidence preservation and cleanup
  are complete and do not authorize another database action.
- A later database incident requires an external deterministic resolution or
  an explicit product-owner incident decision that accounts for the unknown
  transaction/write result. It must begin from the pushed clean checkpoint and
  fresh non-database control-plane readback.

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
- Activation is false because the current audit returned no membership,
  privilege, high-inheritance, ledger or inventory result and because current
  backup/public-endpoint conditions were not independently completed.

## 5. Current incident evidence

Secret-free artifact:

`deploy/production/evidence/production-first-launch-role-risk-readonly-unknown-20260728.json`

Artifact SHA-256:

`79f869aefef5a5abd86d7d61618286217dc553d2a2c646c61505fba3e885a1b2`

Deterministic facts:

- Final source package: 24 files, 16 migrations, 23/23 manifest hashes.
- Exact registry evidence SHA-256:
  `b44b8861202d97b9f0784dd89f3b6056e5fc4af2b6939d28bdfe1b2f49b540f3`.
- Clean Linux archive: 53,830 bytes, SHA-256
  `e8c9e876d4c8934be18e7e46ac9b7a4c04daf2c246a7d853ee017208d74340b8`,
  zero AppleDouble and zero symlink.
- Local isolated zero-DSN import and remote `--network none` import passed.
- No new database account, credential, RSA or ciphertext was created.
- One final database dispatch occurred after all pre-connect checks passed.
- It created a database connection and failed at `database_read`.
- `result.json` was absent; `result.json.tmp` was 0 bytes with the empty-file
  SHA-256.
- The sanitized error was 155 bytes with SHA-256
  `e9efda9f785f95eb8df5595bd95b104ab5ca0371b80448700c990c0b08580fbb`.
- Runner result: `CONNECTED_UNKNOWN`; transaction and database-write outcomes
  are unknown; automatic retry count is zero.

Historical identity evidence remains useful context but is not current truth:

- ledger `0001`–`0008`;
- 30 public tables and 5 sequences;
- only historical `noteai_app` and `noteai_xhs`;
- `noteai_app ROLINHERIT`;
- one `noteai_xhs -> noteai_admin` membership with historical
  `ADMIN TRUE / INHERIT TRUE / SET FALSE`;
- ownership zero.

Do not promote those historical facts into the current accepted-risk profile.

## 6. PRE_CONNECT incidents

All of the following were proven before database dispatch from sentinels,
containers and result state, then materially corrected:

- source directory mode blocked the non-root import container;
- the first minimal package omitted transitive registry evidence;
- the replacement archive contained macOS AppleDouble metadata;
- one root AppleDouble metadata file survived the first exclusion pass;
- the Chrome file chooser timed out before any send-file execution.

No database connection, transaction or write occurred in those incidents.
They do not weaken the final `CONNECTED_UNKNOWN` stop.

## 7. Cleanup and non-regression

- API-C task directory, source, archives, transfer chunks, sentinels, result,
  error log, audit/import containers and runner processes: zero.
- API-F task directory, audit/import containers and runner processes: zero.
- API-C API and Admin: active, live/ready `200`, one loopback listener each,
  zero non-loopback listeners.
- API-F API: active, live/ready `200`, one loopback listener, zero non-loopback
  listeners.
- API-F API env file: root-owned `0600`, not a symlink; no value was read.
- Service restarts, deployments, provider submissions and public-traffic
  requests: zero.
- Fresh RDS control-plane overview: one instance and one running instance.
- Current automated-backup freshness and public-endpoint absence were not
  independently reverified in this incident. Historical evidence must not be
  substituted for a fresh accepted-risk activation.
- One broad control-console observation transiently emitted cloud resource
  metadata in internal tool output. It contained no Secret, credential or user
  data, was not persisted to Git, submitted to a provider or exposed publicly,
  and all subsequent output was reduced to bounded counts/booleans.

## 8. Repository checkpoint scope and verification

- `tools/production_schema_roles.py`
- `scripts/postgres/noteai_production_runtime_roles.sql`
- `tools/production_schema_outcome_audit.py`
- `tools/production_first_launch_role_risk_audit.py`
- `tools/production_first_launch_role_risk_audit_runner.sh`
- `tools/internal_deployment_readiness_gate.py`
- focused tests for the executor, outcome auditor, role-risk auditor and gate
- historical role-audit/corrector tests that preserve the e5883 hashes, require
  current source drift to fail closed, and mock source validation only when
  testing downstream incident classification
- the incident evidence, readiness manifest, this Handoff and risk register

The code allows only the exact historical first-launch profile, requires a
non-`noteai_xhs` executor, rejects any extra membership/elevation/ownership or
grant option, and leaves readiness scoring unchanged.

- Focused schema/role/outcome/readiness suites: `66/66`.
- Full Python suite: `1020/1020`, with `24` explicit skips.
- Production readiness gate: `105/105 PASS`.
- Internal readiness gate: fail-closed `14/29 = 48%`; public launch
  `14/38 = 37%`; active accepted-risk entries `0`.
- Python compile, runner shell syntax, both JSON parses, sensitive-pattern scan
  with zero matches and `git diff --check`: pass.
- No database, cloud, service, provider, public-traffic or Secret-bearing action
  occurred during repository verification.

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

1. Resolve the current checkpoint with `git log`; require clean worktree and
   upstream divergence `0/0`.
2. Do not choose or start the next database-dependent task while the UNKNOWN
   incident is open.
3. A later database incident requires an external deterministic resolution or
   an explicit product-owner incident decision that accounts for the unknown
   transaction/write result.
4. Before that later incident, freshly reverify non-database control-plane
   backup/public-endpoint, cleanup and API/Admin non-regression facts.
5. If a new database incident is validly opened, activate only the two fixed
   zero-credit `ACCEPTED_RISK` entries after the complete independent read-only
   matrix succeeds; otherwise remain blocked.
