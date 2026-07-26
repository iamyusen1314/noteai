# NoteAI Production Deployment Execution Plan

Status: `PLANNED / NOT AUTHORIZED FOR EXECUTION`

Date: 2026-07-24

Task: `PROD-DEPLOY-PLAN-001`

This document is a read-only release plan. It does not authorize an ACR
access, image pull, container/service start, database write, Alibaba Cloud
mutation, provider call, ALB/TLS/DNS change, or production traffic.

## 1. Immutable release set

All production pulls must use the private VPC registry hostname and the exact
manifest digest. Tags may be displayed for operators, but may not be used as
the deployed identity.

| Role | Private immutable image |
|---|---|
| API | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:17706e1802afc136ac8f9a621d4199a7f9749da733290e923e42268eff42e0d1` |
| Admin | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:d94bc4581e85a5b507415da2abc284c26e46288a746f91e951a43380d670c733` |
| XHS HTTP | `noteai-prod-shenzhen-registry-vpc.cn-shenzhen.cr.aliyuncs.com/noteai/app@sha256:452c2faf7853ce58d93e43c05fb6217a9a6cc1e4c81345d8cef2f50acabd79af` |

Every image must report `linux/amd64`, application/OCI revision
`a635692a899ee02c6905cd694611c14e0da4594a`, source
`https://github.com/iamyusen1314/noteai`, version
`git-a635692-amd64-r1`, non-root user `noteai` / UID/GID `999`, and its
expected `api`, `admin`, or `xhs-http` role marker. Local Docker image IDs are
not registry digests.

## 2. Proposed first-release placement

| Host | Initial service | Initial exposure |
|---|---|---|
| API-C | API canary, then accepted API; Admin only after both APIs pass | API canary on loopback; Admin loopback-only until a later ALB approval |
| API-F | API canary, then accepted API; XHS services only after separate XHS/DB-write approval | API canary on loopback; XHS exposes no HTTP port |

API-C is deployed and accepted first. API-F is never deployed merely because
API-C succeeded; it has its own digest/config/readiness acceptance. Admin is
single-instance for the first internal release and remains unreachable from
the public Internet. The XHS image supplies two process roles,
`xhs-trends` and `xhs-tracking`; both stay stopped until their separate gate.

This placement uses existing paid ECS capacity and does not create a Worker
host. CPU, memory, disk and failure-domain suitability must be rechecked before
execution. If either host lacks headroom, stop and request a capacity decision;
do not silently colocate more roles or buy capacity.

## 3. Blocking findings before any deployment

1. `PROD-DEPLOY-ENV-SPLIT-001` closes the original repository-side shared
   env-file defect. The later Tracking contract further splits Trends and
   Tracking, so API, Admin, Trends and Tracking now use four distinct inputs;
   `scripts/validate_production_env_files.py` rejects unknown, duplicate or
   cross-role Secret key names without printing values. The live files and
   their permissions still require read-only verification on API-C/API-F.
2. API-C/API-F Docker, disk, current containers, service definitions, ports,
   private ACR DNS, registry-auth method and runtime-env metadata are not
   currently re-observed. A read-only node audit is mandatory.
3. RDS current availability, backup/PITR state and schema versions `0001`-
   `0008` need a fresh read-only check. Ordinary API/Admin start must not run
   migration. `scripts/render_predeploy.py` also writes the managed Prompt
   baseline and is therefore excluded without a separate database-write
   approval.
4. The Admin listener placement is intentionally loopback-only for this
   internal stage. Public/private ALB exposure requires a later listener,
   security-group and authentication review.
5. `NOTEAI_XHS_COLLECTION_SUSPENDED=1` prevents real XHS collection, but the
   market worker can still write baseline/freshness state to PostgreSQL and a
   local snapshot. XHS service start therefore needs an explicit bounded
   production-write approval even while external collection remains suspended.
6. ALB, TLS binding, DNS cutover, real provider checks, payment and public
   traffic are outside this plan.

## 4. Serial rollout gates

### Gate 0 — read-only production preflight

- Reconfirm exact host IDs/names and that only API-C/API-F are in scope.
- Record Docker/Compose versions, architecture, free disk/memory, current
  container/image/service state, bound ports and existing release paths.
- Hash current deployment definitions and record current immutable image refs;
  do not output environment values.
- Verify each role env file is root-owned `0600`, contains only allowlisted key
  names, and has no unknown/duplicate names. Do not print values.
- Resolve the private ACR hostname from both nodes and verify intended VPC
  routing. No registry login, manifest request or pull in this gate.
- Read RDS availability, schema-migration versions, backup/PITR metadata and
  connection limits without changing data.
- Run `tools/collect_production_database_preflight.py` only through an
  authenticated least-privilege metadata credential/session. Inject its DSN
  through a hidden protected process environment; never place it in command
  arguments, evidence or logs. Require connection- and transaction-level
  read-only mode, bounded timeouts, aggregate-only source checks, rollback and
  close.
- Reduce the observation to a Secret-free JSON artifact and require
  `tools/production_readonly_preflight_gate.py` to pass. Do not record host
  IDs, IP addresses, connection values, user rows or long logs.
- Stop on any unexpected running application, public listener, mutable image
  ref, Secret exposure, low disk, architecture mismatch or unrecorded change.

### Gate 1 — deployment-template closure

- Confirm the completed role-specific env-file inputs for API, Admin and XHS.
- Run the key-name validator against all three external files before Compose
  resolution; reject unknown, duplicate or cross-role Secret names.
- Preserve UID/GID `999`, read-only root, `cap_drop: ALL`,
  `no-new-privileges`, bounded `/tmp`, no devices, no privileged mode and the
  single bounded data mount.
- Resolve the Compose file offline and verify every image matches
  `repository@sha256:<64 lowercase hex>`.
- Run the production hardening, readiness and production-readiness tests.
- Create a `[skip render]` deployment-control commit. This commit is not an OCI
  revision and does not require an image rebuild.

### Gate 2 — API-C canary and promotion

- Capture the current service/config/image state and rollback command before
  any pull.
- Authenticate only to the private VPC registry using a temporary,
  least-privilege mechanism; never reopen the public ACR endpoint.
- Pull only the exact API digest, then immediately verify RepoDigest,
  `linux/amd64`, OCI revision and role marker.
- Start a loopback-only canary on an unused port with the production runtime
  constraints. Do not run migration or any real provider call.
- Require `/health/live` HTTP `200` and `/health/ready` HTTP `200` three times
  over at least 60 seconds. Readiness must contain only healthy PostgreSQL and
  required local-model checks.
- Inspect bounded, redacted logs and prove no migration, supplier request,
  billing mutation or Secret output occurred.
- Only after independent acceptance may the same digest/config replace the
  inactive API-C production service. Keep it outside ALB.

### Gate 3 — API-F canary and promotion

- Repeat Gate 2 independently on API-F; do not copy API-C's result.
- Confirm digest and role/config parity with API-C.
- Require repeated zero-AI readiness and retain API-C as the rollback-safe
  accepted node.
- Keep API-F outside ALB until independent acceptance.

### Gate 4 — Admin internal deployment

- Pull only the exact Admin digest on API-C and verify its registry/OCI
  identity before start.
- Require the dedicated `noteai_admin` role and the accepted exact
  session/read-only operational permission matrix. Do not reuse `noteai_app`
  and do not force the entire connection read-only: login/logout require only
  `admin_sessions` `SELECT, INSERT, DELETE`, while all business mutations are
  denied independently by application capability gates and database ACL/RLS.
- Start loopback-only. Require `/health/live` HTTP `200` and
  `/health/ready` HTTP `200`; Admin readiness blocks only on PostgreSQL and a
  configured Admin credential.
- Prove one login, authenticated `/admin/capabilities` read, masked user/queue
  views, logout and token invalidation without business writes. Every mutation
  endpoint must return HTTP `409` before database/file/process work.
- Do not mutate Prompt/configuration, expose the port publicly or add it to ALB
  in this gate.

### Gate 5 — XHS HTTP processes

- Keep both processes stopped until separately approved.
- When approved, pull the exact XHS digest on API-F and verify identity.
- Start `xhs-trends` before `xhs-tracking`, never together.
- Keep `NOTEAI_XHS_COLLECTION_SUSPENDED=1`, leave snapshot upload disabled,
  keep crawler configuration disabled, and make no real XHS request.
- Trends has no healthcheck. Tracking uses only its provider-free read-only
  schema/role healthcheck and `restart: "no"`; a failed round stays stopped
  for evidence review instead of automatically retrying. Acceptance also
  requires the expected non-root process command, bounded redacted logs and
  proof of zero external collection.
- Any database/snapshot writes must match the separately approved bounded
  list. Do not use a browser fallback, proxy rotation or challenge bypass.

### Gate 6 — later network release

ALB creation, backend registration, TLS binding, DNS cutover, public smoke and
real supplier calls are separate tasks with separate cost and production-impact
approval. No earlier gate implies approval for Gate 6.

## 5. Health and acceptance contract

| Role | Liveness | Readiness / acceptance |
|---|---|---|
| API | `/health/live`: process-only HTTP `200` | `/health/ready`: HTTP `200` only when PostgreSQL and the required local model are healthy; HTTP `503` otherwise |
| Admin | `/health/live`: process-only HTTP `200` | `/health/ready`: HTTP `200` only when PostgreSQL and Admin credential presence are healthy; HTTP `503` otherwise |
| XHS Trends | No HTTP listener or Docker healthcheck | Process/command identity, runtime constraints, suspension state, bounded logs and zero external collection |
| XHS Tracking | No HTTP listener; provider-free read-only Docker healthcheck | Exact role/schema readiness, stale/unlinked-attempt failure, suspension state, bounded logs and zero external collection |

Claude, Kimi, Amap, Meituan, XHS, market freshness, crawler and payment are not
load-balancer health dependencies and must not be called by these probes.

## 6. Rollback

- Never delete the prior image, release directory, environment metadata or
  evidence during rollout.
- A canary failure rolls back by stopping/removing only the new canary and
  restoring the recorded inactive state.
- API-C promotion failure restores its prior service/config. API-F failure
  stops API-F and retains accepted API-C.
- Admin failure stops only Admin and leaves both APIs unchanged.
- XHS failure sets/keeps collection suspended and stops only the failing XHS
  process. Do not fall back to Playwright/Chromium.
- No schema migration is included, so application rollback does not perform a
  database downgrade or destructive cleanup.
- Registry image deletion, production-data cleanup and cloud-resource deletion
  are never automatic rollback actions.

## 7. Cost and duration

- No new cloud resource is required by this plan.
- Existing fixed ECS/RDS/Tair/ACR/NAT charges continue whether deployment
  occurs or not.
- Worst-case unshared image transfer for two API copies plus one Admin and one
  XHS copy is about `4.18 GB`; shared layers should reduce actual transfer and
  disk consumption. Use only the private VPC registry path. Registry/network
  billing must be rechecked before execution.
- Reserve at least `12 GiB` free Docker storage per participating node so the
  accepted prior image/config can remain available for rollback.
- Expected operator window after all blockers close: read-only preflight
  20–30 minutes; API-C 20–30 minutes; API-F 20–30 minutes; Admin 15–20
  minutes. XHS activation is a separate window. Stop rather than compressing
  observation periods.
- No AI, map, Meituan, XHS or payment usage cost is permitted in the zero-AI
  rollout.

## 8. Approval sequence

1. `PROD-DEPLOY-ENV-SPLIT-001` — repository-only env-file separation,
   key-name validation and `[skip render]` deployment-control commit.
2. `PROD-DEPLOY-PREFLIGHT-001` — next approval: read-only
   API-C/API-F/RDS/private-network
   audit; no ACR access or production writes.
3. `PROD-API-C-ROLL-001` — exact-digest private pull, loopback canary and
   zero-AI API-C acceptance.
4. `PROD-API-F-ROLL-001` — same independent API-F rollout.
5. `PROD-ADMIN-ROLL-001` — loopback-only Admin rollout.
6. `PROD-XHS-ROLL-001` — separately bounded XHS process start and allowed
   database-write list while external collection stays suspended.
7. ALB, TLS, DNS and public/real-provider smoke remain later approvals.
