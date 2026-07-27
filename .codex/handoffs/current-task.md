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
  new product decision or a public-launch-complete declaration.
- Never print, persist, commit or document Secret values, private keys,
  passwords, cookies, complete connection strings, IP addresses, resource IDs,
  user data or long raw logs.

## 2. Git and release truth

- Expected branch: `codex/quality-stabilization-real-chain`.
- Parent documentation checkpoint:
  `692b9428c5a75d01eb6a2e1af3854578e62d0fb7`.
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
  `REPOSITORY + DISPOSABLE POSTGRESQL VERIFIED / PRODUCTION UNAPPLIED`.
- Production remains at migrations `0001`–`0008`.
- Migrations `0009`–`0016` and the final runtime role/ACL matrix remain
  unapplied.
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

- A fresh successful RDS backup was confirmed before the interrupted staging.
- The resumption after `e5883ab` failed only during import packaging, before
  `_connect()`. It created no database connection, transaction or business
  write and did not reach the executor.
- Before this Handoff was written, the unused task-scoped temporary Super
  account was deleted. Control-plane read-back is:
  `3 total accounts / 1 Super / 0 task accounts`.
- API-C protected task directory, encrypted credential, RSA material, source
  bundle and `runner.env` are absent.
- API-C/API-F task maintenance-container residue is zero.
- Cloud Shell task runner, gate bundle and registry bundle are absent.
- API-C and API-F API services and API-C Admin remain active, ready and
  loopback-only. No service was restarted or redeployed during cleanup.
- No provider call, registry access, public traffic change or production
  business-row write occurred during the interrupted resumption or cleanup.
- Production therefore remains at the last verified `0001`–`0008` state.

## 7. Exact resume sequence

1. Fully read `AGENTS.md`, this file,
   `.codex/notes/architecture-summary.md`,
   `.codex/notes/risk-register.md` and the readiness manifest/verifier.
2. Start three read-only Subagents:
   - Handoff/Git/Readiness Auditor;
   - Schema/Role Execution Verifier;
   - Runtime/Cleanup Evidence Auditor.
3. Re-observe Git and the cleanup baseline. Do not assume browser or Cloud
   Shell memory survived.
4. Reconfirm an eligible fresh successful RDS backup, zero task
   accounts/directories/containers, and unchanged loopback API/Admin health.
   Treat `0001`–`0008` as the last verified ledger state until a new protected
   privileged read-only pre-dispatch check is available.
5. Rebuild the minimal executor package only from exact Git source
   `e5883ab`: executor, preflight gate, migrations `0001`–`0016`, credential-free
   runtime-role SQL and exact registry evidence.
6. Verify every file hash. Registry evidence expected SHA-256 is
   `b44b8861202d97b9f0784dd89f3b6056e5fc4af2b6939d28bdfe1b2f49b540f3`.
7. In a no-DSN environment, require
   `import tools.production_schema_roles` to pass before creating any temporary
   privileged credential. A missing import dependency is a packaging failure,
   not permission to connect to the database.
8. Only after zero-DB import acceptance, create one new short-lived
   task-described Super account and ephemeral RSA transport. Never expose the
   plaintext credential.
9. Transfer and hash-verify exact files on API-C; require `runner.env=0`,
   maintenance container `0`, API/Admin unchanged and the exact new backup.
10. With the protected temporary credential, force one read-only
    pre-dispatch check that proves the production ledger is still exactly
    `0001`–`0008` and every executor precondition is unchanged. A failure stops
    the task and prohibits automatic retry.
11. Execute at most one newly authenticated bounded production transaction.
    After any database connection, failure or unknown outcome prohibits
    automatic retry.
12. Exact approved write ceilings:
    - 8 fixed legacy ledger SHA backfills;
    - 8 migration-ledger rows for `0009`–`0016`;
    - 2 fixed service-state seeds;
    - retention backfill `0`;
    - existing business-row updates `0`.
13. Independently force read-only verification of migration hashes, inventory,
    role/column/sequence negatives, zero elevation and exact counters.
14. Save only Secret-free reduced evidence before cleanup.
15. Delete the task account, RSA/cipher/source directory, runner environment,
    maintenance container and Cloud Shell task files; read back the exact
    cleanup baseline and unchanged API-C/API-F/Admin health.
16. Update the evidence artifact, readiness manifest, Handoff and risk register;
    run focused tests, readiness gates and `git diff --check`; commit with
    `[skip render]` and push normally.
17. Select the next unique task from the validated dependency graph and
    continue until internal readiness is genuinely `100%`.

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
