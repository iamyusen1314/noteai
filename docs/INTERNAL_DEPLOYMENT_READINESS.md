# NoteAI Internal Deployment Readiness

Task: `PROD-FIRST-LAUNCH-INTERNAL-READINESS-GATE-001`

Current status (2026-09-03): internal `29/29 = 100%` accepted; public-launch
`1/9`, complete `30/38 = 79%`. Item30's canonical provider evidence is verified.
Item1–29 were not rerun. Public DNS/traffic remains unauthorized; Item31 is the
next task but is outside the current Item30-only execution scope.

Historical status (retained on 2026-09-03):
`PREFLIGHT VERIFIED / PRODUCTION SCHEMA-ROLE EXECUTOR READY`

This gate prevents three different meanings of “ready” from being collapsed
into one number. It is offline and read-only: it does not contact Alibaba
Cloud, a database, a provider or a payment service.

## Historical three-layer snapshot (retained on 2026-09-03)

| Layer | Meaning | Current evidence |
|---|---|---|
| `repository_isolated` | Code, tests, contracts and disposable-environment evidence exist | `12/12 = 100%` |
| `internal_runtime` | The current source release is built, privately deployed and accepted on managed internal production resources | `2/17 = 12%` |
| `public_launch` | Real suppliers/payment, legal confirmation, ALB/TLS, pre-DNS smoke and DNS ramp are accepted | `0/9 = 0%` |

The combined internal-deployment score is therefore `14/29 = 48%`. The
complete-public-launch score is `14/38 = 37%`. These are evidence-completion
ratios, not schedule estimates, quality grades or permission to deploy.

The older `tools/production_readiness_gate.py` verifies deployable repository
assets. Its current green `105/105` result remains useful, but it is not and never was
proof that the current release is deployed or publicly launchable.

## Fail-closed rules

- Every control is one of `verified`, `unverified` or `blocked`.
- `verified` requires an existing relative evidence file or a commit present
  in Git history. A description in chat is not evidence.
- `unverified` requires an exact blocker and next task.
- `blocked` additionally requires an observable resume condition.
- Missing files, missing commits, unknown dependencies, cycles, new status
  words or malformed JSON invalidate the entire ledger.
- A downstream task is actionable only when every declared dependency is
  `verified`.
- The ledger separately labels repository/offline work, authenticated
  production work, external/public work and professional review. Only a
  dependency-free `repository_offline` item can be selected as
  `next_safe_task` under the current execution boundary.
- Repository evidence can never satisfy an internal-runtime or public-launch
  control by inheritance.

## Commands

Validate the ledger and print current scores:

```bash
.venv/bin/python tools/internal_deployment_readiness_gate.py
```

Print machine-readable evidence:

```bash
.venv/bin/python tools/internal_deployment_readiness_gate.py --json
```

Require only the completed repository/isolated layer:

```bash
.venv/bin/python tools/internal_deployment_readiness_gate.py --require repository
```

The following commands must currently exit non-zero:

```bash
.venv/bin/python tools/internal_deployment_readiness_gate.py --require internal
.venv/bin/python tools/internal_deployment_readiness_gate.py --require public
```

## Current decision

`PROD-COMPLETE-FIRST-LAUNCH-001` remains `NO-GO` for public launch. Fresh
authenticated host, cloud-control-plane and read-only PostgreSQL observations
prove the historical private services remain stable and loopback-only, all
fixed source-data aggregate blockers are zero and the production migration
ledger is exactly `0001`–`0008`.

The authenticated baseline is now materially improved: ACR product-managed
PrivateZone resolution passes on API-C and API-F, RDS data/log backup
retention is fourteen days and service-key disk encryption is enabled. Both
API nodes passed the bounded post-encryption loopback health/isolation check.
The managed RDS administrator still occupies the former Admin runtime role
name; repository commit `b06671f` closes that collision with
`noteai_admin_runtime`, but production remains at migrations `0001`–`0008`.

`PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-OFFLINE-001` remains complete only for
its exact historical revision. Revision
`2fa3a5543876a6c8040ec17ca05a5461b101bbd7` was built as five native AMD64
roles; ordinary CI passed, `cryptography 48.0.1` is present once per role, and
the exact-product VEX binds twelve dispositions to 115 SBOM BOM-Links while
leaving the canonical `4 Critical / 19 High` per-role reports unsuppressed.
Current HEAD `b06671f` changes migration/runtime-role content. Native workflow
`30233565859` first re-earned an exact five-role GitHub source-candidate
identity. The isolated retained AMD64 builder then rebuilt the same revision
and published five role-specific immutable ACR tags. Five unique manifest
digests passed authenticated control-plane binding, canonical evidence remains
unsuppressed at `4 Critical / 19 High` per role, and the ACR-build CycloneDX
1.6 VEX validates with 115 exact BOM-Links. GitHub and ACR local image
identities remain deliberately separate.

The one-time publisher role/policy, builder ACR VPC link, Docker
authentication and temporary authentication directories are removed. The
production ACR PrivateZone binding is restored; API-C/API-F were not
restarted or redeployed and retained matching pre/post loopback health
fingerprints. No database write, provider call or public edge/traffic change
occurred. Publication is evidence, not deployment acceptance.

The production preflight is verified by the retained Secret-free artifact and
the ledger is fail-closed at `14/29`. The active dependency root is now
`PROD-FIRST-LAUNCH-PRODUCTION-SCHEMA-ROLES-001`. Production remains at
migrations `0001`–`0008`; repository/disposable evidence for the bounded
schema-role executor does not inherit into production acceptance.

The credential-free offline evidence gate is now available at
`tools/production_readonly_preflight_gate.py`. It verifies only the final
sanitized observation artifact; authenticated observations without that
retained machine artifact do not change the score. It
fails closed on missing API-C/API-F coverage, non-loopback listeners, mutable
images, insufficient host headroom, RDS/backup/PITR gaps, migration drift,
source-data blockers, unexpected runtime authority, side effects or cleanup
residue.

`tools/collect_production_host_preflight.py` is the paired node-side,
read-only collector. It emits only the exact host fragment consumed by the
gate: Docker/systemd identity and hardening, loopback health, bounded log-hit
counts, env key-name metadata, capacity, private/VPC-only network/ACR routing and
temporary-access residue. It never outputs environment values, raw logs,
addresses or instance identities and makes no registry/database/provider
request. Bounded authenticated host observations have executed and are
retained only in the reduced preflight evidence artifact.

`tools/collect_production_database_preflight.py` is the database-side
companion. It accepts a DSN only through a protected process environment,
forces both session- and transaction-level read-only mode, applies bounded
timeouts, reads only migration metadata, predefined role/privilege state and
fixed aggregate counts, and always rolls back. It emits no business row,
connection value or raw exception. Its repository verification does not
provide production acceptance by inheritance. The production read-only
execution occurred, rolled back and is accepted by the final gate.

`tools/production_schema_roles.py` is the next bounded production executor.
It requires the exact task confirmation, accepts the privileged DSN only
through a protected process environment, and commits migrations `0009`–`0016`
plus `scripts/postgres/noteai_production_runtime_roles.sql` in one
transaction. The six new identities remain `NOLOGIN`; managed credentials,
services, providers, ACR, ALB/TLS/DNS and public traffic are outside this
task. Its independent `--verify` path forces read-only mode and compares the
complete positive and negative database capability matrix.

## Updating evidence

Update
`deploy/production/internal-deployment-readiness.json` only after the exact
task has independent evidence. Preserve the task ID and dependencies, replace
the status with `verified`, remove its blocker fields, and add the exact Git or
repository evidence reference. Production evidence must first be reduced to a
secret-free repository artifact or Handoff checkpoint; do not embed host
identities, user data, credentials, connection strings or long logs.
