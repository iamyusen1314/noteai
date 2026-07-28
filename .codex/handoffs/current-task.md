# NoteAI Internal Production Readiness Handoff

> Updated: 2026-07-28 (Asia/Shanghai)
>
> This concise checkpoint is the sole current Handoff instruction source.
> Earlier Handoffs and the 2026-07-27 UNKNOWN artifact remain historical
> evidence, not current database truth.

## 1. Objective, authority and safety

- Umbrella task: `PROD-COMPLETE-FIRST-LAUNCH-001`.
- Goal: continue finite, bounded and reversible work until internal deployment
  readiness is `29/29`.
- The Main CTO may approve bounded internal-production work without repeated
  approval. Stop for interactive login/new credentials, public DNS or real
  traffic, irreversible destruction, uncapped cost, a new product decision,
  a public-launch-complete declaration, a real security conflict, a database
  connection with an unknown result or a genuine technical inability.
- Never print, persist or commit Secret values, private keys, passwords,
  cookies, full connection strings, IP addresses, cloud resource IDs, user
  data or long raw logs.
- No force push, direct merge to `main`, concurrent production writes or
  automatic retry after a database-connected failure.

## 2. Git and readiness truth

- Branch: `codex/quality-stabilization-real-chain`.
- Parent checkpoint before this evidence:
  `4c6f7c05a304abf5bc2f07341f64e830d393b805`.
- Schema executor repair:
  `e5883abc01c4b009907bee550209d7036d383771`.
- Immutable application revision:
  `b06671fbcca51f884b04c86edcf116e373c6cfa8`.
- Repository/isolated: `12/12 = 100%`.
- Internal runtime: `2/17 = 12%`.
- Internal deployment: `14/29 = 48%`.
- Complete public launch: `14/38 = 37%`.
- No current application image was deployed; API-C/API-F/API-C-Admin still run
  the accepted historical loopback-only services.
- Re-observe branch, HEAD, status and upstream divergence before any resumed
  work. A checkpoint is a recovery safeguard, not a reason to stop.

## 3. Unique current task and known production state

`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`

- Status:
  `INVESTIGATING / CONNECTED_KNOWN CONFLICT / NO RETRY`.
- One newly reviewed forced-read-only audit completed successfully and
  deterministically classified production as `CONFLICT`.
- Exact schema observation:
  - migration ledger is canonical `0001`–`0008`;
  - no `sha256` ledger column or constraint;
  - 30 public tables and 5 public sequences;
  - no migrations `0009`–`0016`, new runtime roles, schema seeds or retention
    table survived;
  - zero business-row values were read.
- Exact role observation:
  - only historical `noteai_app` and `noteai_xhs` are present;
  - runtime elevation count is `1`;
  - bidirectional runtime membership count is `1`;
  - ownership count and new-role login count are `0`.
- The conflict origin is not proven. Do not assume which historical role,
  attribute or membership edge is involved.
- The former production preflight omitted `rolinherit` from its elevated
  attribute count and checked membership only where a runtime role was the
  member. It therefore did not cover the completed audit's full negative
  matrix.

## 4. Evidence and cleanup

- Current Secret-free artifact:
  `deploy/production/evidence/production-schema-roles-conflict-20260728.json`.
- Historical UNKNOWN artifact:
  `deploy/production/evidence/production-schema-roles-unknown-20260727.json`.
- Outcome auditor:
  `tools/production_schema_outcome_audit.py`.
- The executed auditor snapshot had SHA-256 `aa133f52…e612`. The checkpoint
  tool changes only failure reporting so proven pre-connect failures emit
  `PRE_CONNECT`; its database queries and three outcome classifications are
  unchanged.
- The actual outcome audit used one read-only database connection, enforced
  session and transaction read-only, returned exit `30`, wrote zero database
  rows and was not retried.
- The reduced 950-byte outcome had SHA-256
  `3ebf703ac3387528e219bf31e8b6a5fa8c294d9a8d43549b8463360eac2357b2`.
- Cleanup was read back:
  - RDS accounts `3 total / 1 Super / 0 task`;
  - API-C task directory, source, RSA, ciphertext, runner, result and
    maintenance container all zero;
  - API-F task directory and maintenance container zero;
  - Cloud Shell task files and variables zero;
  - API-C/API-F API and API-C Admin active, live, ready and loopback-only;
  - zero restart, deploy, provider, registry or public-traffic action.
- Repository verification after evidence updates:
  - focused schema/readiness plus the deterministic UTC-bucket regression
    `23/23`;
  - full Python `972` with `24` explicit skips and zero failures;
  - production readiness `105/105`;
  - internal readiness gate valid at `14/29`;
  - zero-DSN import, Python compile, JSON parse, Secret/resource-ID scan and
    `git diff --check` all pass;
  - all three independent read-only auditors report no remaining blocker.

## 5. Mandatory failure classification

After any nonzero exit or tool failure, first collect Secret-free sentinel,
process, container, connection and result evidence and classify:

1. `PRE_CONNECT`: prove account/connection/audit runner/container/dispatch
   sentinel/transaction are all zero, or otherwise prove the failure occurred
   before database connection. Transfer, encoding, quoting, permission, path,
   unpack, launch and exit `126/127` failures belong here when so proven.
   Deterministically clean them and continue only with a materially corrected
   method; never repeat the identical failed path.
2. `CONNECTED_KNOWN`: a database connection occurred and a deterministic
   result is preserved. Do not retry the failed database action. Save reduced
   evidence, clean temporary access and stop at the defined incident boundary.
3. `CONNECTED_UNKNOWN`: a connection may have occurred and commit, rollback,
   business writes or result cannot be proved. No automatic retry or new
   database action is allowed.

Read-only diagnosis of sentinels, processes, containers, connection counts,
execution status and cleanup is mandatory incident handling, not a retry.

## 6. Exact resume boundary

- Do not create another database account, connect to RDS, run apply, run
  `--verify`, rerun the completed outcome audit or select a downstream task.
- A product-owner decision is required because the current state is a real
  runtime-role security conflict and every useful next step requires another
  database connection.
- Recommended next atomic task:
  `PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CONFLICT-001`.
- If authorized, that task must:
  1. use a new reviewed forced-read-only auditor and fresh protected access;
  2. identify only the affected runtime role, the exact elevated attribute and
     the direction/category of the membership edge without exposing account
     names or IDs;
  3. prove whether the state predates the failed schema transaction;
  4. clean all temporary access and stop again before mutation;
  5. define a separate bounded corrective transaction only from that evidence.
- The failed apply and completed outcome audit are never retries for the next
  task. No schema-role readiness promotion is allowed until a later independent
  full executor `--verify` passes the complete table/column/sequence/role
  negative matrix.

## 7. Completed work not to repeat without conflict evidence

- H17–H22/R22/R23 and disposable PostgreSQL security rehearsals.
- Trends diagnostic/Canary/retry/Snapshot/entrypoint, long-run and Tracking
  repository contracts.
- Durable AI, storage/recovery, payment, UI/Admin, Admin-role/collision and
  self-hosted browser-asset repository contracts.
- Native AMD64 builds, SBOM/VEX review, five-role ACR publication and
  PrivateZone restoration.
- RDS SSL, fourteen-day backup retention, disk encryption, Gate 0 and TEMP ACL
  closure.
- Historical API-C/API-F/Admin startup, restart and recovery tests.

## 8. Continuing launch boundary

- First public cutover must include XHS Trends and Tracking; neither may be
  hidden or marked deferred to bypass launch scope.
- No public DNS, ALB/TLS exposure or real-user traffic before its separate
  gates and explicit approval.
- No real supplier/payment/AI call without a bounded cost and data-impact plan.
- Do not announce internal readiness `100%` until all 29 internal controls have
  independent evidence and the gate passes.
- Former fixed context-token stop rules remain revoked. After compaction,
  reread Git, this Handoff, the manifest and risk/evidence ledgers and continue
  from the current safe state.
