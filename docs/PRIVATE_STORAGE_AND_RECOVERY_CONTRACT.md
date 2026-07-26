# Private storage and recovery contract

Version: `private-storage-recovery-v1-2026-07-26`

Status: repository/offline contract only. This document does not authorize an
OSS bucket, RAM role, KMS key, RDS snapshot/PITR restore, production migration,
service start, provider call, data write, deployment or recurring cost.

## Private object boundary

- SQL stores only opaque UUIDs, domain-separated owner hashes, object-key
  hashes, content hashes, bounded counts, fixed states and canonical UTC
  clocks. Raw object keys, filenames, URLs, pre-signed URLs, prompts, media,
  credentials and user identifiers are prohibited.
- The only production adapter is an explicitly configured private Alibaba OSS
  backend. It uses an ECS RAM Role, HTTPS/internal endpoint, conditional
  create, server-side encryption, SDK integrity checks and bounded reads. Static
  access keys are rejected.
- API and AI Worker credentials remain separate deployment identities. The
  bucket is private; neither API responses nor task messages contain an object
  key or URL.
- Local-directory and in-memory adapters exist only for isolated restart,
  cross-process and failure tests. Production rejects the legacy node-local
  video identifier.

## Write, ownership and deletion

Object creation happens before its relational metadata transaction. Any
database statement or commit failure synchronously deletes a newly created
object; failure to prove deletion is a hard integrity error. Durable admission
locks every referenced media row for the authenticated owner before billing,
then links it to the operation in the same transaction.

Reads recompute the owner hash and deterministic logical key, compare the
stored key hash, metadata, size, content hash, purpose, key epoch and expiry,
and fail as not-found for a different owner. Video objects contain only
canonical, bounded JPEG-frame bundles; original uploads are deleted after
parsing.

Expiry and account deletion delete the object first and then atomically move
metadata to `expired` or `deleted`. A missing backend keeps account deletion
pending. Orphan reconciliation is bounded, age-gated and dry-run by default;
its report contains only counts and key hashes.

## Migration and role boundary

Migration `0013_private_storage_recovery_contract.sql` adds
`private_media_refs` and `ai_operation_media_refs` and grants nothing.
`noteai_app` may insert owner media metadata, link it during admission and
perform exact lifecycle updates. `noteai_ai_worker` needs read-only access to
linked ready metadata. Dispatcher, Admin and XHS roles need no access.

Exact table/column privileges, RLS behavior, non-ownership, no DDL/TEMP,
negative role matrix and migration SHA must pass disposable PostgreSQL before
any production permission change.

## Backup/PITR restore evidence

`tools/recovery_evidence.py` is read-only. A source checkpoint and an isolated
restored checkpoint must use the same full release commit. Each database
inventory is captured in one read-only transaction; PostgreSQL additionally
uses `REPEATABLE READ` so all table hashes share one snapshot. The tool
generates:

- migration ledger and schema digest;
- per-table exact row count and row-set digest;
- request/result/media reference lifecycle aggregates;
- private-object count, byte count and aggregate digest;
- a canonical manifest digest with explicit zero-content privacy flags.

Row values and object keys are hashed only in process and never emitted. The
restore gate passes only when release, engine, schema, migrations, every table,
reference lifecycle and object inventory match exactly. “RDS available” or
“restore command succeeded” alone is not acceptance.

Evidence output is bounded, created once with mode `0600` and never overwrites
an existing path. Verification rejects unknown manifest fields, invalid
counts/clocks/digests and privacy flags even when an attacker recomputes the
outer manifest hash.

The future production drill must restore to a new isolated endpoint, block
application/provider traffic, use read-only database credentials, capture both
manifests, compare them, retain only the sanitized evidence, and then remove
the exact labelled temporary instance after separate cost/destruction
authorization. It must never overwrite the source instance.

## Rollback and remaining production gates

Before promotion, keep Durable AI admission and Workers suspended. On storage
failure stop new media admission, preserve relational evidence, and restore
the prior immutable API/Worker digest; never retry an ambiguous provider
outcome. Production still requires migration/role preflight, a private bucket
and RAM roles, immutable images, cross-node managed-runtime proof, one isolated
PITR drill, monitoring/alerts, provider-chain validation and capacity testing.
