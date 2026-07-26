# Production runtime hardening

This document defines the deployment boundary for the browser-free
`api-runtime`, `admin-runtime`, and `xhs-http-runtime` images. It does not
authorize an image build, registry login/push, deployment, production access,
provider call, VEX statement, or production exception.

## Required runtime boundary

Every production container must run with all of the following controls:

- numeric user and group `999:999`;
- a read-only root filesystem;
- all Linux capabilities dropped and none added back;
- `no-new-privileges`;
- no privileged mode, device mappings, host PID/IPC/network namespaces, or
  host block-device mounts;
- one bounded `/tmp` tmpfs with `noexec`, `nosuid`, and `nodev`;
- only the role-specific data bind mount writable.

The production Compose template is
`deploy/production/docker-compose.yml`. It accepts only repository and digest
variables separately so the resulting image reference always contains
`@sha256:`. Each `*_IMAGE_DIGEST_HEX` value must be exactly 64 lowercase
hexadecimal characters and must not include `sha256:`, a tag, or repository
text.
The four role environment files are external to the repository, must resolve
to distinct regular files, and must have no group/world permission bits. API
uses `/etc/noteai/api.env`, Admin uses `/etc/noteai/admin.env`, Trends uses
`/etc/noteai/xhs-trends.env`, and Tracking uses
`/etc/noteai/xhs-tracking.env`. Never reuse a shared runtime env file, print a
file, or pass its values through image build arguments.

The API and Admin model artifacts remain the immutable files carried by the
approved image. Production cloud model mutation stays disabled. API video
cache and role data use `/app/model/data`; operators must create the host data
directory owned by UID/GID `999` before any separately approved start.

Tracking is additionally fail-stopped: its production template uses
`restart: "no"` so a failed supplier round cannot immediately restart against
another due row. Its Docker healthcheck invokes only
`crawler_worker.py --healthcheck`, performs read-only Tracking schema/role
queries, and never calls XHS. A stale or structurally unlinked started attempt
makes readiness fail until evidence is retained and an operator explicitly
uses the provider-free stale reconciler or corrects the integrity fault.

## Pre-deployment validation

Resolve the template without starting containers, using non-secret values:

```bash
NOTEAI_API_IMAGE_REPOSITORY=registry.example.invalid/noteai/api \
NOTEAI_API_IMAGE_DIGEST_HEX=<64-lowercase-hex-characters> \
NOTEAI_ADMIN_IMAGE_REPOSITORY=registry.example.invalid/noteai/admin \
NOTEAI_ADMIN_IMAGE_DIGEST_HEX=<64-lowercase-hex-characters> \
NOTEAI_AI_WORKER_IMAGE_REPOSITORY=registry.example.invalid/noteai/ai-worker \
NOTEAI_AI_WORKER_IMAGE_DIGEST_HEX=<64-lowercase-hex-characters> \
NOTEAI_XHS_IMAGE_REPOSITORY=registry.example.invalid/noteai/xhs-http \
NOTEAI_XHS_IMAGE_DIGEST_HEX=<64-lowercase-hex-characters> \
NOTEAI_API_ENV_FILE=/path/to/api.env \
NOTEAI_ADMIN_ENV_FILE=/path/to/admin.env \
NOTEAI_AI_WORKER_ENV_FILE=/path/to/ai-worker.env \
NOTEAI_XHS_TRENDS_ENV_FILE=/path/to/xhs-trends.env \
NOTEAI_XHS_TRACKING_ENV_FILE=/path/to/xhs-tracking.env \
docker compose -f deploy/production/docker-compose.yml config --quiet
```

Before resolving Compose, run
`scripts/validate_production_env_files.py --api ... --admin ...
--ai-worker ... --xhs-trends ... --xhs-tracking ...`.
The validator reads key names only for its decision, never prints values, and
rejects duplicate/invalid names, overexposed permissions, unknown
Secret-like names, and cross-role Secret injection. The canonical role
allowlists are documented in `docs/DEPLOYMENT_SECRETS.md`.

An independent reviewer must then inspect the fully resolved configuration and
verify every resolved image against
`^[^[:space:]@]+@sha256:[0-9a-f]{64}$`. Reject it if an image lacks that
immutable digest form, if any container gains a capability/device/privileged
mode, or if any writable mount extends beyond the explicit NoteAI data path.
`docker-compose.yml` remains the developer topology; the production contract
is exclusively `deploy/production/docker-compose.yml`.

## Non-invasive constrained proof

The evidence phase may use only retained local images and must use
`--network none`, UID/GID `999`, read-only root, the bounded `/tmp` tmpfs,
all capabilities dropped, and `no-new-privileges`. Use SBOM/package ownership
and ELF `DT_NEEDED` metadata only. Do not run a vulnerability trigger, PoC,
malformed input, symbol probe, provider request, real XHS call, database
connection, or production service.

Record effective container inspect fields for user, read-only state,
capability drop/add, security options, privileged mode, devices and mounts.
`libblkid` or `libacl` remains `under_investigation` unless the complete
allowlisted runtime dependency graph and deployment constraints support an
independent conclusion.

## Rollback

Before production deployment, rollback is simply rejection of the deployment
configuration; existing images are unchanged. After a separately approved
deployment, rollback must restore the last independently accepted immutable
image digest and deployment configuration without weakening any runtime
security control.
