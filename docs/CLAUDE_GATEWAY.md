# Claude Gateway deployment boundary

The Gateway is an internal, provider-only service. It must not receive browser
traffic, user bearer tokens, database credentials, Moonshot credentials, model
artifacts, or business billing state.

Requests use `claude-gateway.v1` HMAC authentication. The signature binds the
HTTP method, exact path, key ID, protocol version, content type, timestamp,
nonce, and request-body SHA-256. Query strings, duplicate authentication
headers, unsupported content types/versions, stale timestamps, and replayed
nonces are rejected.

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
deadline across the whole non-stream or stream operation. The renewable lease
default is longer than that provider deadline plus a safety margin. Memory mode
keeps its existing provider behavior; final cross-layer timeout tuning
remains part of ARCH-002P-C.

The Gateway discards Anthropic thinking/reasoning deltas. Its NDJSON stream may
contain only `content`, `usage`, `done`, or fixed-code `error` events. Image
blocks are disabled in this protocol version, and remote URLs are always
forbidden.
