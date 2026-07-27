# First-launch UI and Admin contract

Status: repository contract for `PROD-FIRST-LAUNCH-UI-ADMIN-CONTRACT-001`.
It does not prove that the current production digest, database role or private
Admin network path has been promoted.

## User-visible contract

- Every visible first-launch entry must either perform the described action or
  show a truthful unavailable/empty/error state. A success toast is never a
  substitute for a result.
- Diagnose, Generate, Chat, Library, Growth profile, Pricing, Legal and Account
  remain first-launch entries. XHS Trends and Tracking remain first-launch hard
  gates and must not be hidden to bypass acceptance.
- Payment buttons remain explicitly unavailable until the merchant, callback,
  reconciliation and real-money gates pass.
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

Production/cloud Admin is a private, authenticated, loopback-first read-only
control console. The authenticated `/admin/capabilities` response is the
authoritative UI contract. The browser starts with every mutation capability
disabled and remains fail-closed if the capability request fails.

Allowed production observations are:

- aggregate users, plan distribution, usage, model-cost coverage and immutable
  confirmed-cash truth;
- masked user identity, metadata-only note statistics and bounded ledgers;
- Durable AI queue/settlement/outbox counts and oldest queued clock;
- Prompt/model registry inspection without lazy persistence;
- XHS freshness, health and redacted log summaries;
- pricing/settings display and liveness/readiness.

The following production actions return stable HTTP 409 before any database,
file or process work:

- credits, plan, quota, account enable/disable changes;
- Tracking manual requeue;
- Prompt save or rollback;
- model deploy or training;
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

## Deployment gate

The application contract requires a dedicated `noteai_admin_runtime` database
login. It needs only Admin-session `SELECT, INSERT, DELETE` plus the documented
read-only operational objects. It must not reuse `noteai_app`, must not reuse
the managed RDS administrator named `noteai_admin`, and must not use global
`default_transaction_read_only=on`, because login/logout legitimately write
only the session table.

The repository/isolated PostgreSQL gate is verified by migrations
`0015_admin_runtime_contract.sql`,
`0016_admin_runtime_role_collision.sql` and
`scripts/postgres/noteai_admin_runtime_role.sql`. The disposable proof covers an
actual role login, session create/read/delete, secret-row filtering and the
complete positive/negative table, column, sequence, DDL and role matrix.
Production migration/ACL application, immutable image deployment,
loopback HTTP login/logout/token invalidation and restart/non-regression
remain separate gates; until they pass, Admin production promotion is
unverified.
