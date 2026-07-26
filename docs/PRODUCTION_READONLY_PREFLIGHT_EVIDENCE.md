# Production Read-only Preflight Evidence

Task: `PROD-FIRST-LAUNCH-SEC-COMPLIANCE-PROD-PREFLIGHT-001`

Status: `PARTIAL / BLOCKED ON FRESH AUTHENTICATION AND DATABASE METADATA CREDENTIAL/SESSION`

Observed: 2026-07-27 (Asia/Shanghai)

## Read-only observations

- An existing Alibaba ACR console page for the production repository remained
  readable without opening image layers, logs, credentials or environment
  values.
- The currently visible newest immutable AMD64 tags still map as follows:

| Role | Historical tag | Registry digest |
|---|---|---|
| API | `git-a635692-amd64-api-r1` | `sha256:17706e1802afc136ac8f9a621d4199a7f9749da733290e923e42268eff42e0d1` |
| Admin | `git-a635692-amd64-admin-r1` | `sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733` |
| XHS HTTP | `git-a635692-amd64-xhs-http-r1` | `sha256:452c2faf7853ce58d93e43c05fb6217a9a6cc1e4c81345d8cef2f50acabd79af` |

- Each visible role reports `linux/amd64`, normal status and an immutable tag.
- No current-source `2fa3a55` tag or registry digest appeared in the visible
  newest-image list. This is consistent with the native-release checkpoint:
  the current candidate was built and reviewed locally in CI but was not
  published.
- A fresh ECS console navigation redirected to the Alibaba login page.
  Therefore cached ACR content is not accepted as proof of a current
  authenticated ECS/RDS session.

## Still unobserved

- Exact current API-C/API-F host identity, architecture, capacity, containers,
  services, ports, release paths and role-environment metadata.
- Fresh RDS availability, connection limits, backup/PITR status, migration
  ledger, source-data compatibility aggregates and effective runtime roles.
- Current private-network ACR resolution/routing from both nodes.
- Current loopback listeners, stopped Worker state and zero residual temporary
  access paths.

## Safety and disposition

No registry login, manifest request, pull, image publication, Cloud Assistant
command, SSH, Session Manager, database connection, provider call, service
start, configuration change, business write, ALB/TLS/DNS change or traffic
operation was performed. No Secret or user data was read or recorded.

The task remains blocked. It may resume only after a fresh Alibaba console
sign-in and an authenticated least-privilege production database metadata
credential/session are available.
The full Gate 0 checklist in `docs/PRODUCTION_DEPLOYMENT_EXECUTION_PLAN.md`
remains mandatory; this partial ACR observation satisfies none of the
host/database acceptance rows by inheritance.

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
repository-bound migration `0001`–`0008` hashes, pending `0009`–`0015`,
source-data aggregate preflight, effective-role negatives, no public edge,
zero mutation and complete cleanup. Unknown fields, instance IDs, network
addresses, connection values, private keys, long opaque values, drift,
unexpected privileges or any non-zero side effect fail closed.

Env-file checks parse only key names for allowlist and duplicate validation;
they never print, persist or compare values. The evidence records zero Secret
exposure rather than claiming the operating system did not read file bytes.

This verifier is repository/deployment-control tooling and is excluded from
the application image build context. Its existence does not unblock or verify
production Gate 0.

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
`0009`–`0015`. It reads no business row value and returns no discovered role,
table, exception or connection value outside that fixed schema. A failure
emits only a fixed error code. The current blocker is therefore no longer
missing collector design: it is the absent authenticated least-privilege
database credential/session and the expired Alibaba console login. No
production connection has been attempted by this checkpoint.

The effective-role audit compares the complete current baseline, not a sample:
30 exact public tables (including the migration ledger), five sequences,
`noteai_app`'s 82 permitted table booleans plus five sequence `USAGE`
booleans, `noteai_xhs`'s 20 permitted table booleans plus three sequence
`USAGE` booleans, and zero current runtime object privilege for
`noteai_admin`. Every other table/sequence privilege, inventory difference,
TEMP/CREATE capability, membership, ownership, elevation, grant option or
migration-ledger access increments the fail-closed mismatch count.

A disposable PostgreSQL 16.14 execution applied exact migrations
`0001`–`0008`, created only synthetic roles/data, and ran this collector
through its real Psycopg path. The fragment passed the final evidence gate
with all blockers and mismatches at zero. The exact task container used a
tmpfs database, was removed with zero labelled volumes, and Colima was
returned to its prior stopped state. This is syntax/runtime evidence only and
does not inherit as a production observation.
