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
| `internal_runtime` | The current source release is built, privately deployed and accepted on managed internal production resources | `0/17 = 0%` |
| `public_launch` | Real suppliers/payment, legal confirmation, ALB/TLS, pre-DNS smoke and DNS ramp are accepted | `0/9 = 0%` |

The combined internal-deployment score is therefore `12/29 = 41%`. The
complete-public-launch score is `12/38 = 32%`. These are evidence-completion
ratios, not schedule estimates, quality grades or permission to deploy.

The older `tools/production_readiness_gate.py` verifies deployable repository
assets. Its green `100/100` result remains useful, but it is not and never was
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
production read-only preflight is correctly `blocked` because this session has
no authenticated Alibaba, production-database or SSH path. The capability
check must not be repeated while that external condition is unchanged.

The first independent, dependency-free task that remains safe under the
current authority is
`PROD-FIRST-LAUNCH-IMMUTABLE-RELEASE-OFFLINE-001`: build and verify the current
source into local immutable role images without ACR access, image publication,
production deployment, provider calls or business writes. Passing that task
can close only `immutable_release_candidate`; it cannot close any managed
runtime control.

## Updating evidence

Update
`deploy/production/internal-deployment-readiness.json` only after the exact
task has independent evidence. Preserve the task ID and dependencies, replace
the status with `verified`, remove its blocker fields, and add the exact Git or
repository evidence reference. Production evidence must first be reduced to a
secret-free repository artifact or Handoff checkpoint; do not embed host
identities, user data, credentials, connection strings or long logs.
