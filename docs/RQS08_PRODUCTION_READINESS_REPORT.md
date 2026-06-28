# RQS-08 Production Readiness Report

Created at: `2026-06-29`

Gate: `PASS`

## Scope

RQS-08 covers the deployability guardrails around the current quality core:

- GitHub branch protection and security settings
- GitHub Actions CI
- production Secrets and Variables inventory
- V0.4 model artifact loading and checksum verification
- Docker startup behavior
- tracked-file hygiene and obvious secret-value scan
- RQS-07 real-chain acceptance evidence

It does not replace product/business launch work such as payment reconciliation, subscription activation, custom domain setup, or production traffic monitoring.

## Local Gate

`tools/production_readiness_gate.py` was added as the offline deploy gate. It makes no LLM, fact-search, payment, or GitHub API calls.

Current result:

- checks: `42`
- failed: `0`
- model artifact SHA256: `pass`
- model registry and manifest alignment: `pass`
- V0.4 training report deployable: `pass`
- V0.4 readiness reports: `production_ready`
- RQS-07 report gate: `PASS`
- tracked forbidden paths: `0`
- obvious tracked secret values: `0`

Command:

```bash
python tools/production_readiness_gate.py
```

## CI

`.github/workflows/ci.yml` now runs on:

- push to `main`
- push to `codex/**`
- pull request to `main`

The `test` job includes:

- Git LFS pull
- Python dependency install
- Python syntax check
- shell syntax check
- model artifact SHA256 verification
- full unit test discovery
- offline quality gate
- production readiness gate
- Docker Compose config validation

## GitHub Repository Settings

Verified with GitHub CLI on `2026-06-29`:

- repository: `iamyusen1314/noteai`
- visibility: `public`
- default branch: `main`
- merge commit: disabled
- squash merge: enabled
- rebase merge: enabled
- delete branch on merge: enabled

`main` branch protection:

- required status check: `test`
- strict up-to-date checks: enabled
- pull request required: enabled
- stale review dismissal: enabled
- admins enforced: enabled
- linear history: enabled
- force push: disabled
- branch deletion: disabled
- conversation resolution: required

Security:

- secret scanning: enabled
- push protection: enabled
- Dependabot security updates: enabled
- Dependabot PR schedule: configured in `.github/dependabot.yml`

## Production Environment Inventory

GitHub Environment: `production`

Secrets configured:

- `ADMIN_PASSWORD`
- `AMAP_WEB_KEY`
- `ANTHROPIC_API_KEY`
- `MEITUAN_OPEN_TOKEN`
- `MOONSHOT_API_KEY`

Variables configured:

- `ADMIN_PORT=8001`
- `ADMIN_USERNAME=noteai_admin`
- `NOTEAI_ENABLE_TEST_BILLING=0`
- `NOTEAI_FACT_SEARCH=1`
- `NOTEAI_FACT_SEARCH_CACHE_TTL=0`
- `NOTEAI_FACT_SEARCH_PROVIDER=auto`
- `NOTEAI_MEITUAN_TRAVEL_ENABLED=1`
- `NOTEAI_MEITUAN_TRAVEL_TIMEOUT=45`
- `NOTEAI_MODEL_ARTIFACT_REQUIRED=1`
- `NOTEAI_USE_V04_COMPOSITE=1`
- `PORT=8000`

`NOTEAI_MODEL_ARTIFACT_BASE_URL` is intentionally not configured yet. The current strategy is Git LFS first; if the deployment platform cannot materialize LFS files, upload the V0.4 artifacts to object storage and set this variable before production deploy.

## Model Artifact Startup

Docker now uses `/app/scripts/docker_entrypoint.sh` as entrypoint. Every API/admin container runs:

```bash
python -m artifact_loader
```

before starting the service command. With `NOTEAI_MODEL_ARTIFACT_REQUIRED=1`, missing or checksum-mismatched model files fail startup instead of silently falling back.

## Residual Launch Risks

- Payment remains a product launch blocker for paid public launch: order creation, callback verification, reconciliation, and subscription activation still need a production payment flow.
- `NOTEAI_MODEL_ARTIFACT_BASE_URL` must be configured if the final deployment platform does not support Git LFS checkout.
- `MEITUAN_OPEN_TOKEN` is configured and the code also supports `MEITUAN_AI_HUB_TOKEN` as an alias. No value was printed or committed.
