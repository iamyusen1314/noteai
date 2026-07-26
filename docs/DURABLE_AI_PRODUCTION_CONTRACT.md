# Durable AI production execution contract

Version: `durable-ai-v1-2026-07-26`

Status: repository and isolated-database contract. This document does not
authorize a production migration, role change, object-store credential,
provider call, image build, service start, traffic change or recurring cost.
No production queue publisher, dispatcher process, object-store adapter or AI
processor is selected in this phase. The Compose AI Worker profile is a
fail-closed runtime skeleton and its current `--once` command exits with a
configuration error rather than processing work.

## Admission and persistence boundary

The public contract is asynchronous:

1. an authenticated user supplies a mandatory `X-Request-ID`;
2. the API validates an operation-specific request and rejects inline image,
   video or node-local file identifiers;
3. a configured private `PayloadStore` writes canonical request JSON and
   returns an owner-bound opaque reference;
4. one database transaction creates the idempotency claim, charge/usage row,
   queued operation, request-ref metadata, settlement row and content-free
   Outbox row;
5. the API returns HTTP `202` with only operation/status/billing state.

The feature flag `NOTEAI_DURABLE_AI_ADMISSION_ENABLED` defaults to `0`.
No storage adapter is inferred from environment variables. A missing adapter
fails before billing or database admission.
If billing, validation, a database statement or the database commit fails
after a new object was created, the object must be synchronously deleted
before the request fails. The same compensation applies to a newly created
result object when its terminal database transaction does not commit. A
failed compensation is a hard storage-integrity error, never a successful
admission.

The database may contain only canonical UUIDs, SHA-256 digests, fixed enums,
bounded counts and explicitly zoned timestamps. It must never contain a raw
request/result, prompt, reasoning trace, provider envelope, object key, URL,
pre-signed URL, media bytes, Secret, Cookie, owner token or exception text.
All persisted durable-contract clocks are canonical UTC (`Z` or `+00:00`) so
lease and lifecycle ordering cannot change with an offset representation.
The object-store record is bound to a domain-separated user subject, purpose,
content hash, size, count, schema version, encryption mode, key epoch and TTL.

## Shared media contract

Durable AI rejects the existing inline fields `cover_image`, `cover_images`,
`extra_images`, `image_base64` and node-local `video_file_id` when non-empty.
The only future-compatible surface is at most ten canonical opaque
`media_refs`. Creation, ownership, purpose, encryption, lifecycle and
cross-node recovery of those refs belongs to
`PROD-FIRST-LAUNCH-STORAGE-RECOVERY-001`; until that adapter exists, media
jobs fail closed and text-only admission is the only valid path.

## Queue, Outbox and fairness

PostgreSQL remains the authoritative state. The Outbox message contains one
operation UUID and nothing else. A dispatcher claims with a hashed owner
token, expiring lease and monotonic fence, publishes only the UUID, and marks
delivery only under the same live fence.

Priority users are `pro_plus` and `studio`. When priority and standard work
are both runnable, at most three of each four new dispatch slots are priority
and at least one is standard. FIFO is preserved inside each lane. A priority-
only backlog advances the streak to three so the next newly available
standard job cannot be starved.

## Worker and provider side effects

The exact runtime identity is `ai-worker`; API, Admin and XHS images cannot
substitute for it. The Worker is default-suspended, has no port, uses a
read-only root filesystem, drops all capabilities, has no writable bind
mount, uses `restart: "no"` and is capped at 1 CPU, 1536 MiB and 96 PIDs.
Unsuspending requires the exact processor identity `production-v1`.

Every provider call writes a durable `provider_started` attempt immediately
before invocation while holding the same per-user database fence used by
account deletion. A known failure may be followed by an explicitly selected
fallback. An ambiguous outcome moves the job and billing settlement to
`needs_manual`; it is never automatically retried or refunded. Multiple
provider calls in one Analyze/Generate/Rewrite operation therefore have
separate attempts, hashes and terminal states.

## Atomic terminal and replay contract

Success requires a successful final provider attempt and an owner-bound ready
result reference. In one database transaction the operation becomes
`succeeded`, the result reference is linked, the idempotency claim becomes
`completed`, and settlement becomes `completed`.

A definitive pre-provider or known-provider failure atomically changes the
operation to `failed`/`cancelled`, refunds the exact admission charge,
terminalizes the idempotency claim and changes settlement to `refunded`.
Failure in any part rolls the whole transition back.

Account deletion atomically cancels, invalidates the lease/Outbox row and
refunds queued or running work whose provider phase is still `not_started`.
Once provider admission is durable, deletion waits for the known terminal
transition or manual resolution; it cannot race a real provider call. External
request/result objects are erased before the owner join is removed.

Users can read only their fixed status projection, bounded events without
detail hashes, and their result through the owner-bound store. Cross-account
and nonexistent IDs both return not found. Admin receives only aggregated
operation/settlement/Outbox counts and the oldest queued timestamp.

## Runtime database identities

Long-lived production must use three distinct roles:

- `noteai_app`: authenticates users, writes private request objects, performs
  admission/charge, and reads owner-scoped status/result metadata;
- `noteai_ai_dispatcher`: claims/acknowledges only Outbox rows and reads only
  operation UUID plus priority needed for the 3:1 decision;
- `noteai_ai_worker`: claims/fences jobs, reads opaque refs, records provider
  attempts/numeric usage, writes result-ref metadata and runs the reviewed
  terminal settlement transaction.

Migration `0012_durable_ai_execution_contract.sql` grants nothing. Exact
column/table/function permissions must be applied and independently verified
in a later production role task. None of the three roles may own public
objects, read `schema_migrations`, create schema objects, alter default
privileges, truncate tables, grant roles, bypass RLS or read XHS auth data.

## Health, alert and rollback gates

Health is provider-free and read-only. Readiness fails on any
`needs_manual` settlement, exhausted Outbox row or ready ref past TTL.
Alerts must cover queue age, Outbox attempt exhaustion, manual outcomes,
payload lifecycle failures, worker crashes, provider latency/error/cost and
database pool pressure without logging content.

Rollback order is:

1. set admission and Worker suspension to true;
2. stop only dispatcher/Worker; leave API status/result reads available;
3. retain operation, attempt, settlement and object evidence;
4. refund only definitively unstarted/failed work through the atomic path;
5. do not retry or delete unknown-outcome evidence;
6. restore the previous immutable API/Worker digests and exact role matrix.

## Remaining production gates

This repository contract is not service promotion. Before enabling admission:

- implement and independently verify the private OSS adapter and owner-bound
  media references, lifecycle/reconciliation and cross-node recovery;
- integrate the existing Analyze/Generate/Chat pipelines as the exact Worker
  processor without reintroducing synchronous billing or raw payload logs;
- apply migration `0012` and exact roles after production read-only preflight
  and backup evidence;
- build immutable API/Admin/Worker digests and keep admission suspended;
- pass provider-free restart/kill/fence/result-replay and rollback tests;
- then run separately approved, capped real Claude/Kimi validation and the
  100-user capacity gate.
