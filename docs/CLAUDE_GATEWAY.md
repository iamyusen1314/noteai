# Claude Gateway deployment boundary

The Gateway is an internal, provider-only service. It must not receive browser
traffic, user bearer tokens, database credentials, Moonshot credentials, model
artifacts, or business billing state.

Requests use `claude-gateway.v2` HMAC authentication. The signature binds the
HTTP method, exact path, canonical ASCII authority, configuration epoch, key
epoch, key ID, protocol version, content type, timestamp, nonce, and
request-body SHA-256. The Gateway compares the signed context and the single
`Host` header with its own configured values. Query strings, duplicate
authentication headers, unsupported content types/versions, stale timestamps,
replayed nonces, Unicode/percent-encoded authorities, trailing-dot aliases,
and any other host fail closed before Anthropic is called. V1 is not accepted.

The Router accepts only the exact root URL `https://<configured-authority>`.
Before each real connection it resolves every A/AAAA answer and rejects the
whole set unless every answer is strict global unicast. Multicast,
unspecified, loopback, link-local, reserved, site-local, IPv4-mapped, 6to4,
Teredo, and NAT64 transition addresses are rejected even if a platform IP
classifier would otherwise accept them. It then pins the connection to one
validated IP while retaining the original authority for TLS
certificate verification, SNI, and `Host`. HTTP clients use TLS verification,
`trust_env=false`, zero transport retries, no redirects, and accept only HTTP
200 as success. This pinning depends on the guarded private transport shape in
exactly `httpcore==1.0.9`; an unexpected version or pool/backend shape fails
closed as `GATEWAY_TRANSPORT_INCOMPATIBLE`.

Async Gateway DNS resolution runs on a process-level dedicated bounded worker
pool rather than the event loop's default executor. Cancelling a timed-out DNS
lookup therefore does not make a synchronous `asyncio.run` caller wait for the
resolver thread to finish. A late resolver result is discarded before HTTP
transport construction or dispatch; this pre-dispatch case returns
`GATEWAY_PRE_DISPATCH_TIMEOUT` and does not create a missing-usage audit.

The first validated address being temporarily unreachable remains an explicit
availability residual. The Router does not retry the POST against another
address because the provider-start outcome could be uncertain.

`GET /internal/v2/readiness` is a signed, nonce-bearing challenge that does not
claim the business replay nonce, consume the business rate limit, acquire an
operation lease, or write DynamoDB. It echoes the challenge and nonce and
returns only the service/protocol, shared deployment scope, DynamoDB replay
store, config/key epochs, server time, and an HMAC attestation. It never
returns a key ID or secret. When AI readiness is required, the main API accepts
Gateway readiness only after the signed response, epochs, scope/store,
challenge, and bounded clock skew all match. The short readiness cache has a
hard expiry and never serves an expired green result. Probes are single-flight
per configuration key; generation/future ownership prevents a timed-out or
superseded probe from later caching green, and a stuck probe cannot cause
unbounded executor submissions.

Every request body also carries an opaque `operation_id`. The Router creates it
once for a logical Claude leaf call and reuses it for safe retries and safe
Claude fallback. Because it is inside the signed body, it cannot be substituted
without invalidating the HMAC. It is transport metadata and is never passed to
the Anthropic SDK.

The current signing key uses `NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID` and
`NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET`. A rotation window may additionally set
both `NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_KEY_ID` and
`NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET`. Previous-key variables are
all-or-nothing, the two key IDs must differ, and unknown key IDs fail closed.
Nonce retention lasts through at least `max(received_at, signed_timestamp) +
allowed_skew`, preventing a future-dated valid request from being replayed
after a shorter receive-time TTL.

## Control-plane modes

`NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE=memory` remains available for local or
single-process staging. Replay protection uses an in-memory nonce store scoped
to one process instance.

In memory mode `/health/ready` reports:

- `deployment_scope: single_instance_only`
- `replay_store: memory_instance_scope`
- `multi_instance_production_ready: false`

If `NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT` is not exactly `1`, readiness and
model requests fail closed. Horizontal scaling or multiple workers require a
shared atomic replay store before production approval.

The current Staging Blueprint now selects `dynamodb` and declares Render
autoscaling from two to four Starter instances, with one worker per instance.
Global provider concurrency remains `2` and the stable-principal fixed-window
rate remains `30` requests/minute; adding instances therefore improves the
availability exercise but does not increase the provider concurrency budget.
The main API remains on Local transport. Applying the Blueprint and running the
cloud exercise are explicit operator steps and are not performed by repository
tests.

`NOTEAI_CLAUDE_GATEWAY_CONTROL_MODE=dynamodb` uses one DynamoDB table for:

- atomic nonce claims keyed by a digest of a stable principal and nonce;
- one monotonic fixed-window rate item per stable principal;
- opaque operation state and fixed-slot renewable leases with fencing tokens;
- numeric terminal usage metadata.

The stable `NOTEAI_CLAUDE_GATEWAY_PRINCIPAL_ID` is independent of the current
or previous HMAC key ID, so key rotation cannot split replay or rate state.
Required settings are `NOTEAI_CLAUDE_GATEWAY_DDB_TABLE`,
`NOTEAI_CLAUDE_GATEWAY_DDB_REGION`, and the stable principal ID. Runtime AWS
identity must use `AWS_ROLE_ARN` plus Render's automatically injected
`AWS_WEB_IDENTITY_TOKEN_FILE`; credentials must report
`assume-role-with-web-identity`. Static AWS access/session keys are rejected,
and `AWS_EC2_METADATA_DISABLED` must be exactly `true`.

The operation transition is:

`CLAIMED -> PROVIDER_STARTED -> TERMINAL_USAGE | AMBIGUOUS | PARTIAL | CANCELLED`

Operation dispatch is at-most-once and fail-closed. The Gateway acquires a
bounded concurrency lease before attempting the durable operation claim. It
may proceed only when `claim_operation` both returns state `CLAIMED` and reports
that this request created the claim. Any existing claim, including a live
`CLAIMED` item with `created=false`, causes the newly acquired lease to be
released and returns `OPERATION_ALREADY_DISPATCHED`; it never enters the
provider-begin transaction.

The crash boundary has two explicit sides. **Boundary D**, after lease acquire
but before durable claim, leaves no operation ownership record; after that
lease expires, a later attempt may create the first claim and execute.
**Boundary E**, after durable claim but before provider begin, has crossed the
at-most-once ownership boundary: an abandoned `CLAIMED` item is never reclaimed
and every later use of that operation ID fails closed as
`OPERATION_ALREADY_DISPATCHED`. Once provider begin is attempted, any
non-conditional transaction failure remains `CONTROL_PLANE_OUTCOME_UNKNOWN`
with no automatic retry. In particular, `TransactionConflict` is not treated
as a harmless duplicate or downgraded to a retryable result.

The Gateway calls Anthropic only after the `PROVIDER_STARTED` transition and
its fenced lease check commit durably. Lease acquisition accepts an expiry at
the current instant, while provider start and renewal require the old lease to
be strictly unexpired. TTL attributes are cleanup only: nonce and lease
decisions check logical expiry explicitly, and `CLAIMED`/`PROVIDER_STARTED`
operations have no TTL. Only terminal operations receive the configured
retention TTL (30 days by default, capped at 90 days). The table stores
only digests, fixed states/error enums, timestamps, model names, fencing data,
and numeric usage. It never stores prompts, messages, provider output, HMAC
secrets, or raw operation/nonce/principal identifiers.

If the shared store fails before the provider-start transaction is attempted,
the fixed response is `CONTROL_PLANE_UNAVAILABLE`, which is safe for Router
retry/fallback. An uncertain provider-start transaction or any control failure
after that boundary returns `CONTROL_PLANE_OUTCOME_UNKNOWN`; it is never safe
for retry or fallback. A repeated operation already beyond `CLAIMED` returns
`OPERATION_ALREADY_DISPATCHED`, also unsafe for retry/fallback.

In DynamoDB mode `/health/ready` reports `ready_multi_instance` only when the
shared store configuration and table health probe are available. There is no
automatic fallback from DynamoDB to memory state. This health status describes
the control plane's technical capability; it is not production-scale approval.

DynamoDB SDK calls use short connect/read timeouts, one total SDK attempt, and
an outer control deadline. In DynamoDB mode the provider also has one total
deadline across the whole non-stream or stream operation. The Anthropic SDK
uses an explicit bounded timeout and zero retries. The production Gateway
budget is ordered as provider `180s` < Router-to-Gateway HTTP `190s` < Gateway
mode business/stream boundary `210s`. Gateway synchronous, asynchronous, and
stream paths use cancellable async transport under one total `210s` boundary;
the inner Router-to-Gateway HTTP operation remains capped at `190s`. Local
synchronous transport keeps its existing code path and Local transport retains
its existing `30/45/55/180s` task budgets.

For public non-stream, stream, and `stream_chat` routes that contain Claude,
the `210s` boundary is one absolute deadline created before semaphore waiting,
attempts, retry backoff, and model fallback. Every later await uses only the
remaining budget, including Claude-to-Kimi and Sonnet-to-Haiku fallback. Once
the deadline is exhausted no further attempt or fallback starts. Pre-dispatch
expiry does not create a Claude usage audit; cancellation after possible
provider dispatch fails closed as `CLAUDE_OUTCOME_UNKNOWN` and records exactly
one missing-usage audit. Local routes and Gateway Kimi-only routes keep their
existing behavior.
The renewable lease default remains longer than the provider deadline plus a
safety margin.

The Staging API Blueprint remains explicitly `NOTEAI_CLAUDE_TRANSPORT=local`.
It does not cut business traffic over to the Gateway. The separate Gateway
Blueprint declares a two-instance minimum, four-instance maximum, one worker
per instance, and a 240-second maximum shutdown delay. The authority, epochs,
timeouts, global provider concurrency, and rate values remain locked for
staging. This declaration is a prerequisite for the controlled rehearsal, not
production traffic approval.

The real Gateway Blueprint has **Auto Sync = No**, changed and re-verified by
the CTO on 2026-07-13 before any commit containing this scale change was pushed.
After the push, sync only through **Manual Sync** inside the separately approved
staging window. Whether Auto Sync is restored after acceptance is a later
explicit decision. Do not record, copy, or disclose a deploy hook, sync hook,
token, or other secret while changing this control.

## Staging shell-only zero-Claude rehearsal

`/app/rehearsal.py` is a shell-only operator tool. It adds no HTTP route, has no
runtime feature flag, is not imported by `/app/start.sh`, and does not change
the normal Gateway provider. It may run only when all of these guards match:

- Render identifies the exact `noteai-staging-claude-gateway` service and exact
  `noteai-staging-claude-gateway.onrender.com` external hostname;
- control mode is `dynamodb`, the declared instance count is `2`, provider
  concurrency is `2`, rate is `30`, worker count is `1`, and DynamoDB region is
  exactly `ap-southeast-1`;
- the normal stable principal, syntactically valid table and IAM role are
  present; web identity is configured, EC2 metadata is disabled, and every
  static AWS access, secret, and session key variable is empty;
- Render supplies a nonempty valid instance ID and an exact 40-hex Git commit;
- the operator explicitly sets
  `NOTEAI_GATEWAY_REHEARSAL_ACK=staging-zero-claude` in that Render Shell.

Any mismatch returns only the fixed `REHEARSAL_GUARD_REJECTED` result. The
acknowledgement variable is intentionally absent from the Blueprint so the
tool cannot become part of normal service startup.

Operation/rate mode injects a fixed FakeProvider before it sends any ASGI
request and independently replaces both `AnthropicProvider._get_client` and
the Anthropic client constructor with hard failures. Fake usage is always zero.
Those requests still traverse the same FastAPI authentication, nonce, global
rate, operation claim, fenced lease, provider-start and terminal-state chain,
but no Anthropic client can be created. Their only external state is the
Gateway's shared DynamoDB control table. Load mode has no I/O path. The tool
does not import or access the NoteAI business database.

The output has a fixed JSON field set: mode, status codes, fixed error enums,
FakeProvider call count, a one-way hashed instance marker, a commit prefix, and
a one-way control-configuration marker. The last marker covers the configured
table, role, region, stable principal, authority, and epochs without revealing
their raw values. Every participating shell must report the same commit and
control-configuration marker and a different instance marker. `unknown` or a
duplicate instance marker is not evidence. The tool never prints the request
body, nonce, raw operation ID, rehearsal namespace, table, role, principal,
HMAC material, URL, provider output, token path/content, or exception text.

Operation mode requires an operator-created ID beginning with `rehearsal_` or
`rehearsal-`, a namespace beginning with `rehearsal-`, and optionally a future
Unix `--start-at` within ten minutes. `--hold-seconds` is bounded to 170 seconds.
Use the same synthetic operation ID, namespace, and future start time in every
participating instance shell:

```bash
export NOTEAI_GATEWAY_REHEARSAL_ACK=staging-zero-claude
python /app/rehearsal.py operation \
  --namespace rehearsal-<window-label> \
  --operation-id rehearsal_<synthetic-id> \
  --start-at <future-unix-seconds> \
  --hold-seconds 30
```

Across those outputs, exactly one process may report `fake_provider_calls: 1`
and HTTP 200. Every competing process must report zero FakeProvider calls and a
fixed pre-provider rejection such as `OPERATION_ALREADY_DISPATCHED` or
`CONCURRENCY_LIMIT`.

Rate mode sends correctly signed but deliberately invalid JSON through the
same ASGI chain. It derives a shared rehearsal-only principal from the supplied
namespace and accepts a bounded request count. Begin in a clean rate window and
aggregate results from every shell: exactly the first 30 requests must be
`INVALID_JSON`; every remaining request in that window must be `RATE_LIMIT`,
with `fake_provider_calls: 0` throughout:

```bash
export NOTEAI_GATEWAY_REHEARSAL_ACK=staging-zero-claude
python /app/rehearsal.py rate \
  --namespace rehearsal-<window-label> \
  --start-at <future-unix-seconds> \
  --request-count 31
```

Load mode is separate from the ASGI modes. It performs no HTTP request, no
DynamoDB call, no Anthropic construction, and no business-database access. It
runs a bounded local CPU loop at a fixed approximately 95% duty cycle, yielding
at least once per 100 ms cycle so health serving is not monopolized. A future
`--start-at` is required and duration is strictly 60–600 seconds:

```bash
export NOTEAI_GATEWAY_REHEARSAL_ACK=staging-zero-claude
python /app/rehearsal.py load \
  --start-at <future-unix-seconds> \
  --duration-seconds 480
```

Run this command concurrently from Render Shells attached to the two existing
instances, first confirming their output/evidence instance markers are
different. Use the same future start and about 5–8 minutes (300–480 seconds).
This is intentional CPU load solely to exercise the CPU autoscaling rule. It
does not establish that real Claude network-bound traffic will trigger that
rule automatically.

### Controlled 2→4→2 sequence

1. Confirm Auto Sync is No and the approved Manual Sync produced the expected
   commit. Confirm the main API still reports Local Claude transport. Confirm
   Gateway readiness is shared-control-plane green, two instances are healthy,
   each has one worker, and no real Claude smoke is scheduled for the window.
2. Choose new synthetic operation IDs. Use one shared rehearsal namespace for
   every process whose rate state must be aggregated. Confirm matching commit
   and control-configuration markers and two different instance markers. Never
   use a business operation ID or business principal.
3. At two instances, open one Render Shell per instance and schedule operation
   mode for the same future start. Verify exactly one FakeProvider call across
   all fixed outputs. Run rate mode in a clean window; across all shells verify
   exactly 30 `INVALID_JSON`, then only `RATE_LIMIT`, and zero provider calls.
4. From the two different original instances, schedule load mode for the same
   start and 5–8 minute interval. Observe Render's real autoscaler create four
   live instances. Stop load after four distinct healthy instance markers are
   observed. If four real instances are not reached, the scale-up exercise
   failed. Do not manually set four instances and call that autoscaler evidence.
5. At four instances, wait for readiness and repeat the two-slot test with three
   different held synthetic operations: exactly two may enter FakeProvider and
   the third must be `CONCURRENCY_LIMIT`. Then repeat exact-one operation and
   clean-window rate aggregation with fresh synthetic IDs/namespaces.
6. With load stopped, wait for the platform autoscaler itself to return the
   service to two live instances. A manual reduction is not scale-down evidence.
   After readiness settles, repeat once with another fresh operation ID.
7. End the window with two healthy instances and main API Local. Removing the
   shell acknowledgement ends access to the tool; no runtime setting remains.

### Controlled resilience matrix

- **Rolling deploy:** with Auto Sync still No, Manual Sync an approved commit,
  retain fixed JSON from old/new commits, and verify readiness, two-slot limits,
  shared replay/rate state, distinct instance markers, and converged commit and
  configuration markers after drain. Mixed commits are a transition only, not
  an accepted terminal state.
- **Single-instance restart:** restart one staging Gateway instance through the
  approved Render control, keep the other healthy, and verify the replacement
  has a new instance marker, the approved commit/configuration markers, shared
  state, and recovered readiness. Do not kill processes from the shell.
- **DynamoDB outage boundaries:** repository automation must not damage the real
  shared table or IAM. Exercise failure before provider begin and uncertain
  failure after begin only with an isolated rehearsal role/table, or with local
  injected stores. Pre-begin must be `CONTROL_PLANE_UNAVAILABLE`; post-begin
  uncertainty must be `CONTROL_PLANE_OUTCOME_UNKNOWN` and must not retry. After
  restoring the isolated dependency, require readiness recovery and reconcile
  every uncertain operation before continuing. Never delete, stop, throttle, or
  change permissions on the shared staging table for this test.
- **OIDC refresh:** observe natural web-identity credential refresh over a long
  enough approved window and verify readiness remains green. Never open or read
  `AWS_WEB_IDENTITY_TOKEN_FILE`, and never inject static credentials.
- **HMAC rotation:** current and previous key IDs may overlap only under the same
  config/key epoch during the bounded rotation window. An epoch upgrade must use
  blue/green or a full drain so no accepted request crosses mixed epochs; remove
  the previous key only after drain and replay/rate reconciliation.
- **Rollback under mixed configuration:** stop immediately, drain or isolate the
  mixed cohort, reconcile all operation outcomes, and converge commit, epochs,
  principal, table/role configuration marker, concurrency, and rate before any
  rehearsal resumes.

### Executable rollback

A Git revert or old-image rollback does **not** clear Render's active
autoscaling configuration. First use the Render Dashboard to disable
autoscaling and explicitly set manual instances to `1`; confirm exactly one
healthy instance and readiness. Then revert and Manual Sync a single-instance
Blueprint that explicitly sets `numInstances: 1` and
`NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT=1`, and roll back the image if required.
Do not rely on merely omitting `scaling` or omitting `numInstances`: absence is
not a rollback action. Reconfirm main API Local, one Gateway instance, memory or
approved control mode, epochs, worker count, and readiness before closing the
rollback. Keep Auto Sync No until a separate decision explicitly restores it.

Stop immediately and do not continue scaling if any of the following occurs:

- the guard rejects an environment expected to be staging;
- operation-mode FakeProvider calls sum to anything other than one;
- three held operations cause a third FakeProvider call instead of a fixed
  `CONCURRENCY_LIMIT`;
- rate mode enters the provider, or any Anthropic request/usage appears;
- an output contains an unexpected status/error enum;
- instance/commit/control-configuration markers are `unknown`, instance markers
  are duplicated, commits/configuration markers disagree outside a controlled
  rolling transition, or the expected autoscaler transition never reaches four;
- static AWS credentials appear; OIDC, region, table, role, or stable principal
  drifts; or any process attempts to read the web-identity token;
- readiness loses the DynamoDB shared scope, control-plane outcome becomes
  unknown, instances disagree on commit/config/key epochs, or main API transport
  ceases to be Local;
- any operation state remains unreconciled after a fault/rollback;
- global concurrency, RPM, worker count, shutdown delay, or reported
  concurrency/rate behavior drifts from the locked Blueprint values.

Rehearsal terminal operation state is retained for 24 hours, rather than the
normal 30-day Gateway default. DynamoDB TTL cleanup is asynchronous, so never
reuse a synthetic operation ID even after that interval.

Passing this exercise proves only shared nonce/rate/operation/lease behavior
during the observed staging scale transitions. It is
not a 1,000-user capacity proof and does not raise the global concurrency of
two, does not validate the
Alibaba business queue/result-replay path, and does not authorize production
cutover or real Claude traffic.

The Gateway discards Anthropic thinking/reasoning deltas. Its NDJSON stream may
contain only `content`, `usage`, `done`, or fixed-code `error` events. Image
blocks are disabled in this protocol version, and remote URLs are always
forbidden.
