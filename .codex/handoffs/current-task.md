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
- Recovery source checkpoint:
  `d763cccd471d0d97e4aac57a822137cf6eb64242`.
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

`PROD-FIRST-LAUNCH-LEGACY-RUNTIME-ROLE-CORRECTION-001`

- Parent schema task:
  `PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`.
- Status: `BLOCKED / CONNECTED_KNOWN / NO AUTOMATIC RETRY`.
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
  incident may resume only with either a true PostgreSQL superuser or an
  existing protected executor proven to be the exact membership grantor with
  `CREATEROLE` and `ADMIN OPTION` on `noteai_app`. Grantor identity alone is
  insufficient for the `NOINHERIT` change. Interactive login or a new
  credential remains a product-owner stop.
- A post-checkpoint `PRE_CONNECT`, control-plane-only authority audit exhausted
  the available no-database evidence without proving that complete capability:
  - RDS SQL audit is disabled;
  - `6,060` retained error-log records contain zero exact membership-grant
    statement matches;
  - `1,152` records in the migration window contain zero runtime-role name
    matches and zero relevant role co-occurrences;
  - no database client, connection, transaction or write was started.
- Zero log matches do not prove that a credential or grantor does not exist.
  The control plane cannot prove either a true PostgreSQL superuser or the
  complete non-superuser capability set. The original correction incident
  remains `CONNECTED_KNOWN / NO RETRY`; the new authority audit itself is
  `PRE_CONNECT`.
- `PROD-FIRST-LAUNCH-MANAGED-SECRETS-001` received a fresh Secret-free
  production audit but cannot proceed independently:
  - API-C API/Admin and API-F API final-named files are distinct,
    root:root/`0600`, with zero duplicate/rejected key names;
  - API-F legacy `xhs.env` is root-only but does not satisfy final split;
  - Payment, AI Worker, Trends and Tracking files are absent;
  - rotation and revocation tools are absent on both nodes;
  - the four missing files require dedicated database roles from migrations
    `0009`–`0016`, so its dependency now correctly includes
    `production_schema_roles`.
- This audit is discovery evidence, not managed-secret acceptance: it does not
  inspect or compare values, prove non-placeholder content or target database
  usernames, reject legacy/cross-role credential reuse by value, or execute
  rotation/revocation behavior. The three observed copies are only
  final-named files, not proof of final role credentials.
- The only other dependency-ready control is `legal_provider_approval`,
  execution class `professional_review`; it is not a technical substitute.

## 4. Evidence and cleanup

- Current Secret-free identity artifact:
  `deploy/production/evidence/production-legacy-runtime-role-identity-20260728.json`.
- Current correction-rejection artifact:
  `deploy/production/evidence/production-legacy-runtime-role-correction-rejected-20260728.json`.
- Current managed-secret audit artifact:
  `deploy/production/evidence/production-managed-secret-distribution-audit-20260728.json`.
- Current no-database authority audit artifact:
  `deploy/production/evidence/production-schema-role-resume-authority-audit-20260728.json`.
  Its SHA-256 is
  `d7810f8b5c7c0dc3e1f9ea35d080acbae05590892f46a79edf0bd5202cce1c99`.
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
- Managed-secret audit candidate SHA-256 values are:
  - auditor `4f51f1bd0e1220c0b5e856eef1c9157189accabc524fbd8ed53b512f7ca9ead4`;
  - role-key validator `0089e3a5736e675a45c8caa5452b3ec3919b64a8697a6b4272a900983402c875`;
  - local audit test `b59e68c93b6299beec870b3ce02a5fb207f035a3ea49b178bb4424b684db8d7f`;
  - two-file archive `78b35095e086b7584f8d55c72938cc9a81ad91c01c0469bb4dc732fef7713bad`.
- Cleanup was read back after the rejected preflight:
  - one running PostgreSQL instance, `2` successful full backups inside 48h,
    latest age `15h`, and RDS accounts `3 total / 1 Super / 0 task`;
  - API-C task directories, sentinels, task processes, RSA, ciphertext,
    runner, result and both named maintenance containers all zero;
  - API-F task directories and both maintenance containers zero;
  - old and replacement Cloud Shell task files zero;
  - API-C/API-F API and API-C Admin active, live, ready and loopback-only;
  - zero restart, deploy, provider, registry or public-traffic action.
- Fresh recovery readback after checkpoint `d763ccc`:
  - Git remained clean at `d763ccc`, upstream divergence `0/0`;
  - one running PostgreSQL instance, `2` successful backups inside 49h,
    latest completion `2026-07-27T13:08:52Z`, and accounts
    `3 total / 1 Super / 0 task`;
  - API-C API/Admin and API-F API were independently read as active,
    live/ready `200`, with one listener each and zero non-loopback listeners;
  - both hosts reported zero task directories, task material files, task
    processes and task containers;
  - Cloud Shell task files, transient task variables and control-plane query
    processes all read back zero;
  - database connections, transactions, writes, service changes, deployment,
    public traffic and emitted Secret/ID/IP values were all zero.
- Diagnostic `grep`/`pipefail`, a stale terminal binding and a Cloud Shell VM
  expiry were `PRE_CONNECT`: the affected diagnostic/readback commands never
  dispatched a database client. Each was materially corrected and the final
  control-plane and service readbacks passed.
- During the recovery readback, one local JavaScript parse error and two
  unfinished Cloud Shell input paths were classified `PRE_CONNECT`: the first
  never reached the browser and the latter two stopped at an unclosed shell
  continuation before `RunCommand`. The terminal was replaced, API-F was
  dispatched once through a split in-memory/no-literal-newline method, and the
  final host and Cloud Shell cleanup readbacks passed.
- The managed-secret audit package and two local transfer/recovery scripts were
  moved recoverably to
  `/Users/openclaw/.Trash/noteai-managed-secret-audit-20260728-1330`;
  their three precise `/tmp` paths now read back absent.
- Current verification:
  - correction/audit focused suite is `35/35`, repeated five consecutive
    times after making both fake Docker fixtures consume protected stdin;
  - combined schema/outcome/readiness suite is `75/75`;
  - rejection-evidence/schema/correction/readiness focused suite is `49/49`;
  - managed-secret auditor and role-file validator suite is `12/12`;
  - managed-secret/env/readiness combined suite is `19/19`;
  - resumed authority/readiness focused suite is `12/12`;
  - combined schema/outcome/correction/managed-secret/readiness suite is
    `80/80`;
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

- Complete local review/gates, checkpoint and normal push for the no-database
  authority audit.
- The schema correction incident remains closed to automatic database retry.
  Do not rebuild its package, recreate its account/RSA or rerun preflight,
  apply or audit.
- Resume only after a protected credential is independently proven to be the
  true PostgreSQL superuser, or the exact membership grantor with
  `CREATEROLE` and `ADMIN OPTION` on `noteai_app`. If proving or using it
  requires interactive login or a new credential, product-owner action is
  mandatory.
- If no qualifying existing protected access path can be proven, provider
  support must either execute exactly the bounded `NOINHERIT` correction and
  grantor-bound membership revoke, or provide a protected path whose complete
  capability is independently verified before a new explicit incident begins.
  Advice or permission alone is not technical capability or retry
  authorization. Do not send a credential through chat or infer authority from
  the managed-RDS account label.
- After the schema role matrix is independently verified, resume
  `PROD-FIRST-LAUNCH-MANAGED-SECRETS-001` with real final role-specific files,
  transactional rotation/revocation evidence and no placeholder or legacy
  credential reuse.
- No other internal technical task has all dependencies satisfied. External
  legal approval is a separate professional-review stop and cannot substitute
  for the schema authority requirement.

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
