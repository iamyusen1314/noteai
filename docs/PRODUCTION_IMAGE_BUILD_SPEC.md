# Production image build specification

This specification is the code-level contract for `PROD-IMG-001`. It does not
authorize a build, registry login, push, deployment, service start, database
access, or provider call.

## Source and platform

- Build only from the full release-candidate commit produced after
  `PROD-PREBUILD-001`; do not use `ff030f5`, the documentation checkpoint, a
  dirty worktree, or a short SHA as provenance.
- The production output is one `linux/amd64` image. QEMU/cross-build output is
  not accepted as the primary release build; use an isolated native x86_64
  Linux builder.
- Preferred builder: a dedicated, temporary native AMD64 host in Alibaba Cloud
  Shenzhen with no production database route, runtime secrets, or provider
  credentials. A GitHub-hosted AMD64 runner is an alternative only after its
  artifact transfer and private ACR access plan are separately approved.
- Do not build on API-C or API-F.

## Immutable inputs and OCI labels

The Dockerfile pins both base-image multi-arch indexes. For an AMD64 build, the
resolved child manifests must equal the audited child digests recorded beside
each `FROM` instruction. Stop if either resolution differs.

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
2. Build locally on the approved native AMD64 host with SBOM/provenance output;
   do not push.
3. Before any push, scan the local image filesystem, config and history for
   vulnerabilities, secrets and private material; inspect platform, labels,
   non-root user, entrypoint, command, model hashes and `mttravel` files without
   executing a provider request.
4. Stop and obtain separate approval for `PROD-IMG-002`.
5. After an approved push, ACR scan and manifest/digest read-back are additional
   verification and do not replace the pre-push local scan.

Any Critical or High finding rejects the candidate. Rollback is limited to
discarding the untrusted local candidate/cache; remote tags or cloud resources
must not be deleted without separate approval.
