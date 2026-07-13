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

The current Staging Blueprint now selects `dynamodb`, while retaining its
single-instance scale with one Render instance and one worker. This validates
the shared control-plane path
without changing the staging scale. Production deployment at 2–4 instances is
not approved or verified; enabling that scale requires a separate production
verification and approval step.

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
Blueprint remains one Render instance and one worker; the authority, epochs,
and timeout values are locked for staging. Production deployment at 2–4
instances is still not approved or verified and remains a separate exercise.

The Gateway discards Anthropic thinking/reasoning deltas. Its NDJSON stream may
contain only `content`, `usage`, `done`, or fixed-code `error` events. Image
blocks are disabled in this protocol version, and remote URLs are always
forbidden.
