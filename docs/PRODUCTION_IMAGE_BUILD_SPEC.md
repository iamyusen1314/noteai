# Production image build specification

This specification is the code-level contract for `PROD-IMG-001`. It does not
authorize a build, registry login, push, deployment, service start, database
access, or provider call.

## Source and platform

- Build only from the full release-candidate commit produced after
  `PROD-PREBUILD-001`; do not use `ff030f5`, the documentation checkpoint, a
  dirty worktree, or a short SHA as provenance.
- The production output is three browser-free role-specific `linux/amd64`
  images from the same exact commit: `api-runtime` for the public API,
  `admin-runtime` for Admin, and `xhs-http-runtime` for market timing and note
  tracking. QEMU/cross-build output is not accepted as
  the primary release build; use an isolated native x86_64 Linux builder.
- Preferred builder: a dedicated, temporary native AMD64 host in Alibaba Cloud
  Shenzhen with no production database route, runtime secrets, or provider
  credentials. A GitHub-hosted AMD64 runner is an alternative only after its
  artifact transfer and private ACR access plan are separately approved.
- Do not build on API-C or API-F.

## Immutable inputs and OCI labels

The Dockerfile pins both base-image multi-arch indexes. The shared Python base
is `python:3.11.15-slim-trixie` at multi-arch index
`sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93`;
its audited `linux/amd64` child is
`sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045`.
For an AMD64 build, every resolved child manifest must equal the audited child
digest recorded beside its `FROM` instruction. Stop if any resolution differs.

The approved build command must pass all four values; Dockerfile development
defaults exist only so Render Staging remains buildable:

```text
NOTEAI_OCI_REVISION=<full 40-character release commit>
NOTEAI_OCI_SOURCE=https://github.com/iamyusen1314/noteai
NOTEAI_OCI_VERSION=git-<release short sha>-amd64-r1
NOTEAI_OCI_CREATED=<release commit timestamp in RFC3339 UTC>
```

The resulting config must contain matching
`org.opencontainers.image.revision`, `source`, `version`, and `created` labels.
The revision is the new release-candidate commit, not `ff030f5` and not a
documentation-only successor.

Base indexes, model SHA256 values, the Meituan package integrity/bundle hash,
the complete source commit and the generated SBOM are the reproducibility
record. Debian package indexes and indirect package repositories mean this is
a controlled repeatable build, not a claim of bit-for-bit reproducibility; the
final local image ID and package SBOM must therefore be retained for acceptance.

## Runtime targets and role selection

- `api-runtime` installs `model/requirements-api.txt` and must contain neither
  Playwright nor Chromium. It must not add the explicit GLib/GL/X11 graphics
  stack previously carried by the combined image.
- `admin-runtime` extends the same browser-free application/runtime base and
  can start only the Admin service.
- `xhs-http-runtime` extends the browser-free base with only Node,
  `crypto-js==4.2.0`, and the two SHA-pinned Spider_XHS signer assets. It has no
  Playwright/Chromium, creator/login/write modules, xray packs or proxy code.
- `model/requirements.txt` remains the compatibility entry point for local
  development and CI and resolves to the browser-free API dependency set.
  `model/requirements-worker.txt` is explicitly legacy local tooling and is
  never installed by a production image target.
- Compose selects Docker targets directly. Render uses only the non-secret
  `NOTEAI_RUNTIME_TARGET` build argument (`api-runtime`, `admin-runtime`, or
  `xhs-http-runtime`) and
  declares the matching `NOTEAI_RUNTIME_ROLE` at runtime. Never use a credential
  or configuration secret as a build argument.

After a new exact release commit is approved for build, build the three candidates
separately on the native AMD64 builder (illustrative commands; not authorized by
this document):

```bash
docker build --platform linux/amd64 --target api-runtime \
  --build-arg NOTEAI_OCI_REVISION="$RELEASE_COMMIT" \
  --build-arg NOTEAI_OCI_SOURCE=https://github.com/iamyusen1314/noteai \
  --build-arg NOTEAI_OCI_VERSION="$API_VERSION" \
  --build-arg NOTEAI_OCI_CREATED="$RELEASE_CREATED" \
  -t "$API_LOCAL_TAG" .

docker build --platform linux/amd64 --target admin-runtime \
  --build-arg NOTEAI_OCI_REVISION="$RELEASE_COMMIT" \
  --build-arg NOTEAI_OCI_SOURCE=https://github.com/iamyusen1314/noteai \
  --build-arg NOTEAI_OCI_VERSION="$ADMIN_VERSION" \
  --build-arg NOTEAI_OCI_CREATED="$RELEASE_CREATED" \
  -t "$ADMIN_LOCAL_TAG" .

docker build --platform linux/amd64 --target xhs-http-runtime \
  --build-arg NOTEAI_OCI_REVISION="$RELEASE_COMMIT" \
  --build-arg NOTEAI_OCI_SOURCE=https://github.com/iamyusen1314/noteai \
  --build-arg NOTEAI_OCI_VERSION="$XHS_HTTP_VERSION" \
  --build-arg NOTEAI_OCI_CREATED="$RELEASE_CREATED" \
  -t "$XHS_HTTP_LOCAL_TAG" .
```

The Docker entrypoint fails closed before artifact loading, migration, import or
command execution if the root-owned `/etc/noteai-runtime-role` marker is missing,
unreadable, empty, invalid, or disagrees with `NOTEAI_RUNTIME_ROLE`. It uses an
exact role allowlist rather than a denylist:

- API permits only `/app/scripts/render_start_api.sh` and the exact one-time
  `python /app/scripts/render_predeploy.py` command. It also rejects
  `NOTEAI_API_STARTS_TREND_SCHEDULER=1`.
- Admin permits only its start script and exact Compose Uvicorn command. It
  cannot run collection or pre-deploy.
- XHS HTTP permits only the two packaged collection wrappers, their exact
  direct market-timing/crawler command shapes, and the no-argument fail-closed
  `/bin/false` default. It also requires
  `NOTEAI_XHS_ACQUISITION_ADAPTER=spider_xhs_http` and cannot run API, Admin or
  pre-deploy.

Unknown commands, shell wrappers, role-crossing commands and extra arguments are
rejected with exit 78. This contract protects the normal image entrypoint path;
it cannot prevent a platform administrator from explicitly replacing Docker's
entrypoint. Container-deployment IAM and service definitions remain the security
boundary for `--entrypoint` or equivalent platform overrides.

## XHS HTTP boundary

The production adapter has a fixed `edith.xiaohongshu.com` host and four API
paths covering homefeed, search recommendation, note search and note detail.
It accepts only `GET`/`POST`, disables environment proxy inheritance and
redirects, caps pagination, and fails closed on suspension, missing/expired
session, challenge, login, cooldown, signer-integrity or unknown adapter. The
signer receives `a1` on stdin only. See `SPIDER_XHS_HTTP_PROVENANCE.md` for the
upstream commit/tree, asset hashes, licensing statement and product-risk
boundary.

## Secret and context boundary

Before building, independently verify a clean worktree, materialized Git LFS
model files, `.dockerignore`, and the exact context file list. The context must
not contain `.env` files (except the value-free example), SSH/AWS/GCloud/Docker
credential stores, package-manager credentials, private keys, cookies, Secret
JSON, logs, local databases, test output, `.git`, or `.codex` state.

Production credentials are runtime-only. Do not use secret values as `ARG`,
`ENV`, labels, filenames, build logs, cache keys, or temporary copied files.

## Scan and acceptance order

1. Run repository and context secret checks before the build.
2. Build all three role-specific candidates locally on the approved native AMD64
   host with separate SBOM/provenance output; do not push.
3. Before any push, scan each local image filesystem, config and history for
   vulnerabilities, secrets and private material; inspect platform, labels,
   non-root user, entrypoint, command, immutable runtime role, model hashes and
   `mttravel` files without executing a provider request. Additionally prove the
   API, Admin and XHS HTTP images have no Playwright, Chromium, browser launch
   path or browser-specific OS stack. For the XHS image, verify the two signer
   hashes, `crypto-js` version, role marker, and offline fake-signer contract;
   do not make a real XHS request.
4. Stop and obtain separate approval for `PROD-IMG-002`.
5. After an approved push, ACR scan and manifest/digest read-back are additional
   verification and do not replace the pre-push local scan.

Any Critical or High finding rejects the candidate. Rollback is limited to
discarding the untrusted local candidate/cache; remote tags or cloud resources
must not be deleted without separate approval.
