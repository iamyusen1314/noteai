# First-launch UI and Admin contract

Status: current repository contract for `PROD-FIRST-LAUNCH-UI-ADMIN-CONTRACT-001`,
aligned with the September12–15 owner scope. Exact production versions and actual
checks remain in the existing Handoff; this document alone is not deployment proof.
The former read-only acceptance describes its historical version, not the current
owner capabilities. Historical Evidence is retained unchanged.

## User-visible contract

- Every visible first-launch entry must either perform the described action or
  show a truthful unavailable/empty/error state. A success toast is never a
  substitute for a result.
- Diagnose, Generate, Chat, Library, Growth profile, Pricing, Legal and Account
  remain first-launch entries. Approved account, media and formal business paths
  may be published independently. Unfinished public XHS Trends/Tracking remain
  explicitly unavailable; their full-commercial acceptance is not waived or scored.
- WeChat buttons remain unavailable until the approved Native payment, refund,
  bill reconciliation and sold-entitlement delivery checks pass. Alipay is
  DEFERRED/DISABLED and is not a WeChat dependency.
- The diagnosis share action creates a PNG locally in the browser. It uses the
  operating-system share sheet when file sharing is supported and otherwise
  downloads the PNG. It performs no NoteAI or supplier request and includes
  only score, category and generation date—not note text, account identity,
  URL or internal reasoning.

## Commercial wording

- Paid plans are non-recurring 30-day terms. “Month” is used only for the free
  natural-month refresh; paid balances use “30-day cycle” or “plan cycle”.
- Paid-created archives have no product expiry while the account exists. This
  is not a promise that data survives account deletion, legal deletion,
  corruption or service termination, so the product must not say “permanent”.
- Priority means at most three of every four new dispatch slots may go to the
  priority lane while at least one remains for standard work. It is not a
  provider completion-time or three-times-speed promise.
- Studio is ¥399/30 days for one NoteAI master account operating multiple XHS
  accounts. The current repository has no organization, seat or shared-team
  RBAC contract.

## Production Admin mode

Production Admin is available through the approved HTTPS entry, with its backend
bound to loopback and protected by administrator authentication. Ordinary product
accounts cannot access it. The authenticated `/admin/capabilities` response is the
authoritative UI contract. The browser starts with every mutation capability
disabled and remains fail-closed if the capability request fails.

The owner identity matching `ADMIN_USERNAME` receives only scopes explicitly enabled
by `NOTEAI_ADMIN_OPERATIONS_ENABLED=1` and `NOTEAI_ADMIN_OPERATION_SCOPES`. Other
administrators remain viewers unless their actual role grants an operation; the
public customer-service phone number is not an administrator identity.

Allowed production observations are:

- aggregate users, plan distribution, usage, model-cost coverage and immutable
  confirmed-cash truth;
- masked user identity, metadata-only note statistics and bounded ledgers;
- Durable AI queue/settlement/outbox counts and oldest queued clock;
- Prompt/model registry inspection without lazy persistence;
- XHS freshness, health and redacted log summaries;
- pricing/settings display and liveness/readiness.

Current scoped operations reuse the original management modules:

| Capability | Actual management path | Required behavior |
| --- | --- | --- |
| `entitlement_management` | `POST /admin/users/{id}/entitlements/preview` and `/apply` | Show target and before/after values; noncash trial, gift or compensation entries; no fabricated payment order or historical cash rewrite. |
| `prompt_mutation` | `PUT /admin/prompts/{key}/draft`, `POST …/publish` (including `rollback_version`) | Draft and effective content are distinct; publish/restore the actual managed Prompt, retaining built-in and version provenance. |
| `model_configuration` | `GET /admin/model-config`, `POST …/draft`, `/activate`, `/restore` | Validate and save separately from activation; retain previous usable configuration and report actual effective model. No key disclosure or silent model substitution. |
| `task_management` | `GET /admin/tasks`, task detail, `POST /admin/tasks/{id}/{pause,resume,schedule,retry}` | Manage eligible ordinary jobs only, preserving UUID and accounting. Protected/sealed jobs, dispatched provider attempts and unresolved UNKNOWN operations cannot be replayed. |

Owner selection of an object, parameters and confirmation in the authenticated UI
authorizes that scoped operation. Operations require a reason, request UUID and
current object version/fingerprint; the result and change are recorded atomically.
Repeated submissions do not apply the adjustment twice. Recovery of noncash credits
is limited to confirmed unspent grants, never historical paid funds. Verification
uses marked test objects; deployment itself does not alter real customer rights,
production model selection or task state.

The following legacy or separately restricted production actions still return
HTTP 409 before database, file or process mutation:

- the old `/admin/users/{id}/adjust` mutation and account enable/disable path;
- Tracking manual requeue;
- old Prompt update/rollback endpoints (use the scoped draft/publish path above);
- scoring-model artifact deploy or training (distinct from model route configuration);
- Crawler enable/disable.

Admin never executes a provider job. Plaintext XHS Cookie ingestion remains
HTTP 410 and the legacy in-process Crawler run remains HTTP 409.

## Authentication and data minimization

- Admin credentials remain environment-managed and are never stored in the
  database.
- A random bearer token is returned once to the browser, retained only in
  tab-scoped `sessionStorage`, and stored in `admin_sessions` only as SHA-256.
  Logout deletes the digest server-side before clearing browser state when the
  server is reachable; browser state is cleared even if it is not.
- Production Admin CORS never accepts wildcard `*`. An exact optional
  `NOTEAI_ADMIN_CORS_ORIGINS`/`CORS_ORIGINS` list may be supplied; same-origin
  operation needs no cross-origin allowlist.
- User list/detail responses exclude raw phone and email values. They expose
  only masked forms. Credit-ledger responses exclude provider payment
  references; note bodies, media, secrets, object keys and AI payloads remain
  excluded.

## Runtime permissions and verification

The application contract requires a dedicated `noteai_admin_runtime` database
login. It retains Admin-session `SELECT, INSERT, DELETE` and the documented
read-only baseline, plus only the approved scoped column permissions, RLS and
trigger restrictions. User/task locks use the dedicated lock-only functions.
User identity updates, cash-ledger writes, secret settings and historical operation
rewrites remain denied. It must not reuse `noteai_app`, must not reuse
the managed RDS administrator named `noteai_admin`, and must not use global
`default_transaction_read_only=on`, because login/logout and approved scoped
operations legitimately write their restricted objects.

The repository/isolated PostgreSQL gate is verified by migrations
`0015_admin_runtime_contract.sql`,
`0016_admin_runtime_role_collision.sql` and
`scripts/postgres/noteai_admin_runtime_role.sql`. The disposable proof covers an
actual role login, session create/read/delete, secret-row filtering and the
complete positive/negative table, column, sequence, DDL and role matrix.
Scoped operations additionally use `0024_admin_scoped_operations.sql` and the
incremental `scripts/postgres/noteai_admin_operations_acl.sql`; recovery must not
replay the global role bootstrap. Existing production application is read back,
not repeated merely because this contract changed.

Reuse `tests/test_admin_scoped_operations.py` and
`tests/test_admin_scoped_operations_postgres.py` for idempotency, preview conflicts,
configuration recovery, eligible task handling and real dedicated-role denial.
The no-capability cases in `tests/test_first_launch_ui_admin_contract.py` and
`tests/e2e/admin-production-readonly.spec.js` remain valid negative checks, not a
requirement to disable owner operations. The existing ledger, cost coverage and
Prompt preview UI tests cover their corresponding original views. Production
promotion still requires actual image/role readback, owner and ordinary-user
boundaries, logout/session invalidation and non-regression; local test results
alone do not make Item37 terminal.
