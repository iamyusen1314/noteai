# Production Read-only Preflight Evidence

Task: `PROD-FIRST-LAUNCH-SEC-COMPLIANCE-PROD-PREFLIGHT-001`

Status: `COMPLETE / VERIFIED / FINAL MACHINE ARTIFACT PASS`

Observed: 2026-07-27 (Asia/Shanghai)

## Authenticated read-only observations

- A fresh authenticated Alibaba session observed API-C, API-F, ACR, RDS and
  the production PostgreSQL migration/role metadata without opening image
  layers, credentials, environment values or business rows.
- At the initial preflight observation, the newest immutable AMD64 tags mapped
  as follows:

| Role | Historical tag | Registry digest |
|---|---|---|
| API | `git-a635692-amd64-api-r1` | `sha256:17706e1802afc136ac8f9a621d4199a7f9749da733290e923e42268eff42e0d1` |
| Admin | `git-a635692-amd64-admin-r1` | `sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733` |
| XHS HTTP | `git-a635692-amd64-xhs-http-r1` | `sha256:452c2faf7853ce58d93e43c05fb6217a9a6cc1e4c81345d8cef2f50acabd79af` |

- Each visible role reports `linux/amd64`, normal status and an immutable tag.
- Revision `b06671f` first obtained a separately verified GitHub-native
  five-role source-candidate identity/SBOM/VEX bundle. A successor publication
  task has now rebuilt it on the retained isolated AMD64 builder and bound
  five unique immutable ACR manifest digests. The GitHub and ACR local-image
  identities remain separate.
- API-C and API-F remain private, in the same VPC as the ACR private endpoint,
  and their historical managed services remain stable. API-C, API-F and Admin
  retain loopback-only listeners. No XHS, payment or AI Worker service is
  running and no retained Session Manager, temporary authentication, command
  or diagnostic resource was found.
- The ACR VPC endpoint is `RUNNING` in the expected VPC. Recreating only that
  exact endpoint binding with the documented
  `EnableCreateDNSRecordInPvzt=true` flag restored it after the owner corrected
  the billing state. The DNS console shows one product-managed zone, one
  record and one production-VPC binding. Sanitized Cloud Assistant probes on
  both nodes return exactly one private address row. Existing services were
  not restarted.
- The same two-node probes independently passed active API service,
  loopback-only `8000/8001`, zero XHS/Tracking/Payment/AI Worker container,
  zero temporary ACR auth and live/ready health checks.
- RDS is PostgreSQL 16, high availability, private/VPC-only, SSL-enabled and
  exposes a connection limit of 1,600. Data and log backup retention are both
  fourteen days, log backup remains enabled and the existing Snapshot
  method/schedule is preserved. Service-key disk encryption is enabled and the
  instance is `Running`.
- The single encryption request caused the documented bounded restart. Its
  client timed out after server acceptance and was not retried. Later
  control-plane reads proved one encryption key and `Running`; post-change
  Cloud Assistant checks returned two successful exit-zero rows and two
  complete API health/isolation markers.
- The production database has exactly migrations `0001`–`0008`; the
  migration-ledger proof was read in an explicit read-only transaction and
  rolled back. All fifteen fixed source-data aggregate blockers are zero and
  no business row value was returned.
- Current runtime role metadata matches the historical application and XHS
  baseline. The managed RDS administrator named `noteai_admin` owns objects
  and has management elevation. It cannot be used as the Admin application
  role. Repository commit `b06671f` closes the name collision with the
  dedicated `noteai_admin_runtime` contract, but migrations `0009`–`0016` and
  the new role/ACL remain unapplied in production.
- A fresh bounded database collection after the network interruption returned
  all fifteen predefined source aggregates at zero and exact table/sequence
  privilege matrices. Before the bounded ACL closure it found two real
  preflight mismatches:
  `noteai_app` and `noteai_xhs` each inherit database `TEMP` through the
  current database ACL. The application credential remains intentionally
  unable to read `schema_migrations`; that is not to be fixed by granting
  migration-ledger access to a runtime role.
- `PROD-FIRST-LAUNCH-PREFLIGHT-TEMP-ACL-CLOSE-001` then executed one exact
  transaction that revoked only database `TEMPORARY` from `PUBLIC`.
  Preconditions proved both runtime roles had effective TEMP and no CREATE;
  postconditions proved both TEMP capabilities were false and CREATE remained
  false. The task performed no migration or business-row write. Its exact
  rollback was available but not needed.
- The final database collector ran exactly once after that closure. It forced
  session and transaction read-only mode, returned all fifteen source
  aggregates plus ownership/elevation/unexpected-grant counts at zero, and
  retained the independently accepted exact `0001`–`0008` hashes as
  `pinned_legacy_versions` without granting migration-ledger access.
- The first host collection produced one false temporary-process count because
  broad command-line matching saw the accepted historical Canary name inside
  API-C's persistent data-mount argument. The collector now matches only
  known Worker script identities and Docker `--name` temporary objects.
  Recollection on both production nodes returned zero temporary processes,
  containers, listeners and authentication entries.

## Safety and disposition

The preflight itself performed no registry login, manifest pull, publication,
SSH, Session Manager, provider call, application service start/restart,
database write, ALB/TLS/public-DNS change or traffic operation. Cloud
Assistant ran only bounded sanitized DNS/readiness probes with command
retention disabled. The database observation forced read-only mode and
rollback. No Secret, user data, connection value, host identity or network
address is recorded here.

The separately bounded publication task later used one-time ACR access to
publish the five exact manifests. It removed the publisher role/policy,
builder-side ACR link, Docker auth and temporary auth directories, restored
the production PrivateZone binding, and left API-C/API-F healthy without a
restart or redeploy. That task performed zero provider calls and zero business
database writes.

One exact ACR VPC endpoint binding was reversibly recreated during remediation
and is back in `RUNNING` state with its product-managed PrivateZone record. An
earlier user-defined PrivateZone attempt stopped before creation. A later
attempt to add the isolated builder as a second linked VPC was rejected by the
platform's one-VPC limit and changed no endpoint row. No manual zone or record
was left behind.

Gate 0 is `VERIFIED`. The combined Secret-free artifact is retained at
`deploy/production/evidence/production-preflight-b06671f.json` and passes the
offline verifier. This does not verify or authorize production migrations
`0009`–`0016`, final roles/ACL, managed Secret distribution, service promotion
or public traffic. The full checklist in
`docs/PRODUCTION_DEPLOYMENT_EXECUTION_PLAN.md` remains mandatory.

## Evidence acceptance contract

Repository checkpoint `PROD-FIRST-LAUNCH-PROD-PREFLIGHT-GATE-001` adds the
offline verifier:

```bash
.venv/bin/python tools/production_readonly_preflight_gate.py \
  /path/to/sanitized-preflight-evidence.json
```

The evidence file is created only after real observations exist. The verifier
requires exactly API-C/API-F, historical managed-runtime identities and
loopback listeners, at least 12 GiB Docker headroom, private ACR DNS/routing,
RDS PostgreSQL 16 HA/encryption/SSL/private endpoint, backup/PITR retention,
repository-bound migration `0001`–`0008` hashes, pending `0009`–`0016`,
source-data aggregate preflight, effective-role negatives, no public edge,
zero mutation and complete cleanup. Unknown fields, instance IDs, network
addresses, connection values, private keys, long opaque values, drift,
unexpected privileges or any non-zero side effect fail closed.

Env-file checks parse only key names for allowlist and duplicate validation;
they never print, persist or compare values. The evidence records zero Secret
exposure rather than claiming the operating system did not read file bytes.

This verifier is repository/deployment-control tooling and is excluded from
the application image build context. Gate 0 is verified only because the real
sanitized artifact passes it; the tool's existence alone is not evidence.

The companion host collector is:

```bash
python3 tools/collect_production_host_preflight.py --host-label API-C
python3 tools/collect_production_host_preflight.py --host-label API-F
```

It is transferred with the verifier only after authenticated Cloud Assistant
access is available, run as root on the exact selected node, and removed after
the sanitized JSON fragment is captured. It executes no shell strings, registry
requests, database commands or external calls. It records Docker/systemd
identity and hardening, loopback health, bounded log hit counts, env-file
metadata/key-name counts, capacity, private network/ACR routing and residual
temporary access without emitting environment values, raw logs, IP addresses
or host identities.

The database-side companion is:

```bash
python3 tools/collect_production_database_preflight.py
```

It accepts the connection string only through the protected process
environment name `NOTEAI_PREFLIGHT_DATABASE_URL`; the value must be injected
through a hidden operator/credential path, never placed in an argument, shell
history, evidence file or log. It enforces connection-level
`default_transaction_read_only=on` and an explicit `BEGIN TRANSACTION READ
ONLY`, uses bounded statement/lock/idle timeouts, then always rolls back and
closes the connection.

The database fragment contains only repository-bound migration SHA-256
metadata, predefined NoteAI role presence/absence, privilege/ownership counts
and the exact source-data `COUNT` aggregates required before migrations
`0009`–`0016`. It reads no business row value and returns no discovered role,
table, exception or connection value outside that fixed schema. A failure
emits only a fixed error code. The authenticated production execution has now
occurred. Its sanitized results are summarized above and the retained final
combined collector artifact passes.

The effective-role audit compares the complete current baseline, not a sample:
30 exact public tables (including the migration ledger), five sequences,
`noteai_app`'s 82 permitted table booleans plus five sequence `USAGE`
booleans, `noteai_xhs`'s 20 permitted table booleans plus three sequence
`USAGE` booleans, and zero current runtime object privilege for the
application Admin role. The managed RDS administrator is recorded
informationally and is never accepted as a runtime role. Every other
table/sequence privilege, inventory difference,
TEMP/CREATE capability, membership, ownership, elevation, grant option or
migration-ledger access increments the fail-closed mismatch count.

The TEMP closure is recorded separately from the final zero-mutation
observation window. Cleanup independently proved zero short-lived privileged
accounts, transport keys and temporary cloud files. The pre-existing
administrator password was neither reset nor exposed.

A disposable PostgreSQL 16.14 execution applied exact migrations
`0001`–`0008`, created only synthetic roles/data, and ran this collector
through its real Psycopg path. The fragment passed the final evidence gate
with all blockers and mismatches at zero. The exact task container used a
tmpfs database, was removed with zero labelled volumes, and Colima was
returned to its prior stopped state. This is syntax/runtime evidence only and
does not inherit as a production observation.
