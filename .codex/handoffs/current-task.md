# NoteAI Internal Production Readiness Handoff

> Updated: 2026-07-27 (Asia/Shanghai)
>
> This concise checkpoint is the sole current Handoff instruction source. Historical
> Handoff text is retained in Git commit `692b9428c5a75d01eb6a2e1af3854578e62d0fb7`
> and earlier commits as audit evidence only. Historical `BLOCKED`, “required
> next approval”, ACR approval and delegation statements are not current
> instructions.

## 1. Objective and authority

- Umbrella task: `PROD-COMPLETE-FIRST-LAUNCH-001`.
- Goal: continue finite, bounded and reversible work until
  `internal deployment readiness = 100%`.
- The product owner authorizes the Main CTO to approve and execute those tasks
  without repeated approval, including bounded production/cloud changes.
- Stop and request the owner only for interactive login/new credentials, public
  DNS cutover, real-user traffic, irreversible destruction, uncapped cost, a
  new product decision, a public-launch-complete declaration, a database
  connection with an unknown result, a real security conflict or a genuine
  technical inability to continue.
- Never print, persist, commit or document Secret values, private keys,
  passwords, cookies, complete connection strings, IP addresses, resource IDs,
  user data or long raw logs.

## 2. Git and release truth

- Expected branch: `codex/quality-stabilization-real-chain`.
- Parent documentation checkpoint:
  `9fcb88620e0f5781ac040a41665a6f6b65a12596`.
- Schema executor repair:
  `e5883abc01c4b009907bee550209d7036d383771`.
- Immutable application revision:
  `b06671fbcca51f884b04c86edcf116e373c6cfa8`.
- The three running loopback services still have historical OCI revision
  `a635692a899ee02c6905cd694611c14e0da4594a`; no current image is deployed.
- Five exact current application-role ACR digests and their separate
  GitHub/builder AMD64, SBOM and VEX evidence are verified but not deployed.
- At session start, re-observe branch, HEAD, upstream divergence and status.
  The expected worktree after this checkpoint is clean and upstream `0/0`.

## 3. Fail-closed readiness truth

- Repository/isolated layer: `12/12 = 100%`.
- Internal runtime layer: `2/17 = 12%`.
- Internal deployment readiness: `14/29 = 48%`; 15 controls remain.
- Complete public launch readiness: `14/38 = 37%`; this is not the current
  completion target.
- Manifest:
  `deploy/production/internal-deployment-readiness.json`.
- Verifier: `tools/internal_deployment_readiness_gate.py`.
- Repository or disposable evidence must never be promoted into a production
  row without independent production evidence.

## 4. Unique current task

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`

- Status:
  `INVESTIGATING / ONE PRODUCTION TRANSACTION RETURNED UNKNOWN / NO RETRY`.
- The last deterministically verified production state is migrations
  `0001`–`0008`, established by the successful forced-read-only pre-dispatch.
- A single subsequent production transaction returned an executor failure with
  database outcome `UNKNOWN`. One independent forced-read-only resolution
  audit also failed with outcome `UNKNOWN`; therefore the current schema state
  must not be assumed to be either `0001`–`0008` or `0001`–`0016`.
- No further database connection, transaction, verification or retry is
  permitted without an explicit product-owner decision after this checkpoint.
- The current executor snapshots exact migration bytes, accepts only the
  reviewed legacy or complete ledger, upgrades the legacy ledger in one
  transaction, and verifies the full positive/negative role matrix.
- Six newly introduced runtime identities must remain `NOLOGIN`. Existing
  `noteai_app` and `noteai_xhs` credential state must remain unchanged.

## 5. Executor evidence already completed

- The original production invocation timed out and was not retried.
  Independent forced-read-only evidence proved its complete rollback: no new
  role, table, privilege or business-row write survived.
- Root cause was the legacy production `schema_migrations` ledger lacking the
  `sha256` column before the old executor selected it.
- Commit `e5883ab` fixes only that ordering while retaining exact migration,
  inventory and privilege gates.
- Disposable PostgreSQL `16.14` proved:
  - unexpected inventory fails before commit and rolls back;
  - eight reviewed legacy hashes are backfilled;
  - migrations `0009`–`0016` apply once;
  - two fixed service-state rows are inserted;
  - retention backfill and existing business-row updates are zero;
  - apply-twice performs zero writes;
  - 8 runtime roles, 56 tables, 5 sequences, 3,136 table checks and
    9,728 column checks pass.
- Focused schema/readiness `32/32`, full Python `964` with 24 explicit
  environment skips, production readiness `105/105`, quality, compilation and
  diff checks passed before the production resumption.

## 6. Safe transition checkpoint

- Fresh pre-attempt control-plane and host read-back on 2026-07-27 confirmed:
  one running PostgreSQL 16 RDS instance, an eligible successful backup inside
  24 hours, `3 accounts / 1 Super / 0 task`, zero task residue, and unchanged
  loopback-only API-C/API-F/API-C-Admin health.
- Exact source `e5883ab` was rebuilt into the required 21-file package. The
  first local archive was rejected before credentials because macOS `tar`
  injected 30 AppleDouble `._*` entries. The corrected archive used
  `COPYFILE_DISABLE=1` and independently verified:
  - 21 regular files, 16 migrations and zero AppleDouble entries;
  - 21/21 exact source hashes and exact registry evidence;
  - 47,121 bytes;
  - SHA-256
    `b28cccdfe7be45b0f76cec3a1cdc77dd4a78e4120a52af95617fa475a9a85901`;
  - host and network-disabled current-image imports, including `psycopg`.
- After those zero-DB gates, exactly one short-lived task-described Super
  account and one 3072-bit RSA pair were created. The DSN was encrypted into
  384 bytes; no plaintext password or connection string was printed or
  retained after staging.
- The single forced-read-only pre-dispatch passed and proved:
  - exact legacy ledger `0001`–`0008`;
  - pending `0009`–`0016`;
  - eight missing legacy hashes;
  - zero drift, source blockers, retention candidates/deadlines, unexpected
    grants, elevation and business-row values read.
- The only production apply invocation then returned:
  `executor failure / database outcome UNKNOWN / no retry`.
- Exactly one independent forced-read-only resolution audit was attempted. It
  also returned `database outcome UNKNOWN`; it was not retried. Consequently:
  - actual database write counts are unknown;
  - neither rollback nor commit may be claimed;
  - readiness remains `14/29 = 48%`;
  - `production_schema_roles` is fail-closed as `blocked`.
- Secret-free reduced evidence is stored at
  `deploy/production/evidence/production-schema-roles-unknown-20260727.json`.
- Cleanup completed and was read back:
  - `3 accounts / 1 Super / 0 task accounts`;
  - API-C task directory, RSA, ciphertext, source, runner environment and
    maintenance container all zero;
  - Cloud Shell task files and task variables zero;
  - API-C API/Admin and API-F API remain ready and loopback-only;
  - no service restart/redeploy, provider/registry call, public traffic or
    public-edge change occurred.

## 7. Exact resume sequence

1. Do not create a database account, connect to RDS, run the executor, run a
   database audit or select a downstream task while this UNKNOWN result is
   unresolved.
2. Re-observe Git and the already-clean cloud baseline read-only if work
   resumes; do not infer database state from the last successful pre-dispatch.
3. The product owner must explicitly choose the incident-resolution direction
   because all choices require a new database connection or a rollback/restore
   decision. The owner decision must define whether to:
   - authorize a new, separately designed read-only state audit;
   - restore/reconcile from the eligible backup;
   - or take another bounded incident action.
4. Any authorized audit must use a newly reviewed implementation, one new
   short-lived account and fresh encrypted transport. It must never reuse or
   retry the failed apply/audit command.
5. Only after the database outcome is independently known may
   `production_schema_roles` be accepted or a new corrective task be defined.
   Until then no dependency-graph successor is eligible.

## 8. Stop conditions for this transaction

- Any Git/SHA/inventory/role/permission/counter mismatch.
- Backup unavailable or not recent enough for the approved window.
- Any pre-existing task residue before staging, or any unexpected task residue
  or untracked cloud/service change before dispatch.
- Secret exposure, unexpected public traffic, provider/registry access or API
  service regression.
- Any write outside the exact ceilings.
- Any unknown outcome after database connection.

On a stop condition: preserve reduced evidence, do not retry, clean all
temporary resources when safe, update the Handoff/risk register and return the
task to `INVESTIGATING`.

## 9. Completed work that must not be repeated without conflicting evidence

- H17–H22/R22/R23 and disposable PostgreSQL security rehearsals.
- Trends diagnostic/Canary/retry/Snapshot/entrypoint evidence and
  `xhs_crawler_health SELECT` repair.
- Trends long-run, Tracking, Durable AI, private storage/recovery, payment,
  UI/Admin, Admin-role/collision and self-hosted browser-asset repository
  contracts.
- Native AMD64 builds, raw scans, SBOM/VEX review, five-role ACR publication
  and PrivateZone restoration.
- RDS SSL, fourteen-day backup retention, disk encryption, Gate 0 production
  preflight and TEMP ACL closure.
- Historical API-C/API-F/Admin loopback startup, restart and recovery tests.

Do not reopen a completed item merely because a new conversation starts.

## 10. Continuing safety boundaries

- No force push or direct merge to `main`/`master`.
- No public DNS, ALB/TLS exposure or real-user traffic before the separate
  public-launch gates and explicit owner approval.
- No real supplier/payment/AI call without a bounded Live Run Plan, fixed cost
  ceiling, data-impact statement and rollback.
- No concurrent production writes by Subagents. Subagents provide independent
  read-only evidence; the Main CTO owns serial execution and final acceptance.
- Do not use EntryPoint Override as a normal runtime mode.
- Do not announce internal readiness `100%` until all 29 internal controls have
  independent evidence and the gate passes.

## 11. Context-budget boundary

- Keep the main thread limited to the goal, constraints, decisions, independent
  evidence, execution results and the next action. Subagent final reports must
  stay below 1,500 Chinese characters and omit long logs/code.
- The former fixed `45K`–`50K`/`60K` stop rules are revoked. Checkpoints and
  rolling Secret-free Handoffs are recovery safeguards, not stop signals.
- Do not stop merely because exact token statistics are unavailable, a
  checkpoint was created, Handoff was updated or automatic context compaction
  occurred.
- After automatic compaction, reread Git, this Handoff and the risk/evidence
  ledgers, then continue from the current safe state.
- The database UNKNOWN stop condition in sections 4–8 is substantive and
  independent of context size.
