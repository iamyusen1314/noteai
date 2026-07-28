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
  `a90a2ffe2be73d95df3fc3c207f1f46da77e9a2c`.
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

`PROD-FIRST-LAUNCH-MANAGED-SECRETS-001`

- The independent `managed_secret_distribution` control depends only on the
  verified production read-only preflight and is the only safe technical task
  currently ready in the dependency graph. The other ready node,
  `legal_provider_approval`, requires professional/product-owner input.
- Parent schema task
  `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001` remains blocked by
  `PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CORRECTION-001`.
- The reviewed correction preflight was executed exactly once:
  - `CONNECTED_KNOWN / READ_ONLY_REJECTED`;
  - one connection and one forced-read-only transaction;
  - transaction rolled back, database writes and business values read were 0;
  - error stage was `database_precondition`;
  - apply attempts and apply transactions were 0;
  - no automatic retry is permitted for this incident.
- The error format intentionally did not persist the exact failed predicate.
  Prior exact identity evidence was unchanged, so executor capability is the
  leading inference, not direct proof and not authorization to retry.
- Last directly verified schema/role truth therefore remains:
  - canonical migration ledger `0001`–`0008`, no ledger SHA column;
  - 30 public tables and 5 public sequences;
  - no migrations `0009`–`0016`, new runtime roles, schema seeds or retention
    table survived;
  - only historical `noteai_app` and `noteai_xhs`;
  - sole elevation `noteai_app ROLINHERIT`;
  - sole membership `noteai_xhs -> noteai_admin` with
    `ADMIN TRUE / INHERIT TRUE / SET FALSE`;
  - both endpoints LOGIN/non-superuser, ownership 0.
- Do not perform another database action for this correction incident. A later
  incident may resume only with an existing protected credential proven to be
  the recorded membership grantor or a true PostgreSQL superuser. Interactive
  login or a new credential remains a product-owner stop.

## 4. Evidence and cleanup

- Current Secret-free identity artifact:
  `deploy/production/evidence/production-legacy-runtime-role-identity-20260728.json`.
- Current correction-rejection artifact:
  `deploy/production/evidence/production-legacy-runtime-role-correction-rejected-20260728.json`.
- Parent conflict artifact:
  `deploy/production/evidence/production-schema-roles-conflict-20260728.json`.
- Historical UNKNOWN artifact:
  `deploy/production/evidence/production-schema-roles-unknown-20260727.json`.
- Outcome auditor:
  `tools/production_schema_outcome_audit.py`.
- The executed identity auditor SHA-256 was
  `3ab0ea86b85938450541149b9ef4a4be311bd6c0470b241b080ced6ab0370880`;
  its result was `1515` bytes with SHA-256
  `98b188acc1ec86bf5f0f54ba6a6aaccca122bd65397c779e484bd37d77632eba`.
- That historical runner placed the in-memory DSN in the ephemeral container
  process environment. It persisted and exposed zero Secret values, but it is
  not evidence for the new no-environment control.
- The hardened correction runner was used for this preflight. It passed
  zero-DSN import, kept the DSN out of container environment/argv/disk,
  required corrector-emitted classification markers, pinned exact source
  relative paths and shared the schema executor advisory lock. Its rejection
  is production evidence, not production acceptance.
- Current candidate SHA-256 values are:
  - auditor `195e5ff1cfec1d3a143ada91dd661663fd040ea9acf5f3a656f856a7ec2b8ab9`;
  - audit runner `43a5d59d52a4a8265bbd381f1a6c5e862be2072b43db345d3a5bb96850746988`;
  - corrector `73db08c9acc021adcc93803196503f5fbe3f04390fe83c690f9e326338a3f4ed`;
  - correction runner `6ff34363b40282d62644609291c79a6cad441eaf6f08e6f3a9b3bcee44e97f6d`.
- Cleanup was read back after the rejected preflight:
  - one running PostgreSQL instance, `2` successful full backups inside 48h,
    latest age `15h`, and RDS accounts `3 total / 1 Super / 0 task`;
  - API-C task directories, sentinels, task processes, RSA, ciphertext,
    runner, result and both named maintenance containers all zero;
  - API-F task directories and both maintenance containers zero;
  - old and replacement Cloud Shell task files zero;
  - API-C/API-F API and API-C Admin active, live, ready and loopback-only;
  - zero restart, deploy, provider, registry or public-traffic action.
- Diagnostic `grep`/`pipefail`, a stale terminal binding and a Cloud Shell VM
  expiry were `PRE_CONNECT`: the affected diagnostic/readback commands never
  dispatched a database client. Each was materially corrected and the final
  control-plane and service readbacks passed.
- Current verification:
  - correction/audit focused suite is `35/35`, repeated five consecutive
    times after making both fake Docker fixtures consume protected stdin;
  - combined schema/outcome/readiness suite is `75/75`;
  - rejection-evidence/schema/correction/readiness focused suite is `49/49`;
  - full Python suite is `1007` passed with `24` explicit skips;
  - production readiness gate is `105/105`; internal readiness remains a
    valid fail-closed `14/29`;
  - Python compile, runner syntax, JSON parse, Secret scan and
    `git diff --check` pass;
  - all three independent read-only auditors report no production-code or
    evidence blocker. The schema verifier's only test-fixture race was fixed
    and stress-retested locally before this checkpoint.

## 5. Mandatory failure classification

After any nonzero exit or tool failure, first collect Secret-free sentinel,
process, container, connection and result evidence and classify:

1. `PRE_CONNECT`: prove no database connection/transaction occurred. Account,
   exact remote command fingerprint, prepared/dispatch sentinel, process,
   container and result state must be read together. Transfer, encoding,
   quoting, permission, path, unpack and launch/exit `126/127` failures belong
   here only when that evidence proves the database client never started.
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
An outer Cloud Shell, terminal or control-plane failure never establishes
`PRE_CONNECT` by itself. Do not redispatch until the exact remote command
fingerprint, sentinels, container/process and result have been read. If the
outer layer failed but the remote command completed, recover its
`CONNECTED_KNOWN` result and never rerun it.

## 6. Exact resume boundary

- Complete local review/gates, checkpoint and normal push for the correction
  rejection. The checkpoint is recovery protection, not a stop signal.
- Continue only `PROD-FIRST-LAUNCH-MANAGED-SECRETS-001`.
- Begin with read-only discovery of current root-only API-C/API-F/Admin secret
  file distribution, ownership/modes, rotation/revocation mechanism and
  service references. Never read or emit values.
- Reuse existing protected credentials and control-plane access only. Stop
  before any interactive login, new credential, secret value rotation,
  database connection, service restart/deploy or public exposure unless a
  later bounded step is independently authorized by the standing rules.
- The schema correction incident remains closed to automatic database retry.
  Do not rebuild its package, recreate its account/RSA or rerun preflight,
  apply or audit.

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
