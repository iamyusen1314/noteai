# NoteAI Internal Deployment Readiness

Task: `PROD-FIRST-LAUNCH-INTERNAL-READINESS-GATE-001`

Status: `REPOSITORY GATE IMPLEMENTED / PRODUCTION NOT DEPLOYED`

This gate prevents three different meanings of “ready” from being collapsed
into one number. It is offline and read-only: it does not contact Alibaba
Cloud, a database, a provider or a payment service.

## The three layers

| Layer | Meaning | Current evidence |
|---|---|---|
| `repository_isolated` | Code, tests, contracts and disposable-environment evidence exist | `12/12 = 100%` |
| `internal_runtime` | The current source release is built, privately deployed and accepted on managed internal production resources | `1/17 = 6%` |
| `public_launch` | Real suppliers/payment, legal confirmation, ALB/TLS, pre-DNS smoke and DNS ramp are accepted | `0/9 = 0%` |

The combined internal-deployment score is therefore `13/29 = 45%`. The
complete-public-launch score is `13/38 = 34%`. These are evidence-completion
ratios, not schedule estimates, quality grades or permission to deploy.

The older `tools/production_readiness_gate.py` verifies deployable repository
assets. Its current green `102/102` result remains useful, but it is not and never was
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

`PROD-COMPLETE-FIRST-LAUNCH-001` remains `NO-GO` for public launch. The
production read-only preflight is correctly `blocked`: a cached ACR page can
show the historical `a635692` immutable digests, but fresh ECS navigation
redirects to Alibaba login and no bounded production-database metadata path
exists. Cached content is partial evidence only and cannot satisfy the host,
RDS, backup, schema or runtime controls.

`PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-OFFLINE-001` is complete. Exact revision
`2fa3a5543876a6c8040ec17ca05a5461b101bbd7` was built as five native AMD64
roles; ordinary CI passed, `cryptography 48.0.1` is present once per role, and
the exact-product VEX binds twelve dispositions to 115 SBOM BOM-Links while
leaving the canonical `4 Critical / 19 High` per-role reports unsuppressed.

There is now no dependency-free repository/offline task in the internal
runtime layer. The next dependency root remains the authenticated,
read-only `PROD-FIRST-LAUNCH-SEC-COMPLIANCE-PROD-PREFLIGHT-001`. It must resume
only after a fresh Alibaba console sign-in and a bounded database metadata path
exist. The partial evidence is recorded in
`docs/PRODUCTION_READONLY_PREFLIGHT_EVIDENCE.md`.

The credential-free offline evidence gate is now available at
`tools/production_readonly_preflight_gate.py`. It verifies only a future
sanitized observation artifact and therefore does not change the score. It
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
request. The collector and gate remain offline preparation until executed
against authenticated production.

## Updating evidence

Update
`deploy/production/internal-deployment-readiness.json` only after the exact
task has independent evidence. Preserve the task ID and dependencies, replace
the status with `verified`, remove its blocker fields, and add the exact Git or
repository evidence reference. Production evidence must first be reduced to a
secret-free repository artifact or Handoff checkpoint; do not embed host
identities, user data, credentials, connection strings or long logs.
