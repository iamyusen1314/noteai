# Claude Gateway deployment boundary

The Gateway is an internal, provider-only service. It must not receive browser
traffic, user bearer tokens, database credentials, Moonshot credentials, model
artifacts, or business billing state.

Requests use `claude-gateway.v1` HMAC authentication. The signature binds the
HTTP method, exact path, key ID, protocol version, content type, timestamp,
nonce, and request-body SHA-256. Query strings, duplicate authentication
headers, unsupported content types/versions, stale timestamps, and replayed
nonces are rejected.

The current signing key uses `NOTEAI_CLAUDE_GATEWAY_HMAC_KEY_ID` and
`NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET`. A rotation window may additionally set
both `NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_KEY_ID` and
`NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET`. Previous-key variables are
all-or-nothing, the two key IDs must differ, and unknown key IDs fail closed.
Nonce retention lasts through at least `max(received_at, signed_timestamp) +
allowed_skew`, preventing a future-dated valid request from being replayed
after a shorter receive-time TTL.

## Single-instance staging boundary

Replay protection currently uses an in-memory nonce store. It is scoped to one
process instance and is suitable only for the single-worker, single-instance
Render staging service declared in `render.gateway.yaml`.

`/health/ready` always reports:

- `deployment_scope: single_instance_only`
- `replay_store: memory_instance_scope`
- `multi_instance_production_ready: false`

If `NOTEAI_CLAUDE_GATEWAY_INSTANCE_COUNT` is not exactly `1`, readiness and
model requests fail closed. Horizontal scaling or multiple workers require a
shared atomic replay store before production approval.

The Gateway discards Anthropic thinking/reasoning deltas. Its NDJSON stream may
contain only `content`, `usage`, `done`, or fixed-code `error` events. Image
blocks are disabled in this protocol version, and remote URLs are always
forbidden.
