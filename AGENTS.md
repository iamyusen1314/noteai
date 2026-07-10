# AGENTS.md

## Project Overview

- Project name: NoteAI Pro.
- Goal: build a commercial SaaS system for Xiaohongshu/RedNote content diagnosis, high-quality post generation, score-driven rewriting, creator memory, and admin/cost operations.
- Current functional scope: static web frontend, FastAPI user API, FastAPI admin API, SQLite persistence, V0.4 composite quality scoring/model artifacts, multi-agent Claude/Kimi generation and diagnosis, screenshot/video understanding, fact enrichment, market timing evidence, subscription/credit accounting, model/training tooling, Docker deployment support, GitHub CI.

## Tech Stack

- Frontend framework: no confirmed frontend framework; current UI is a single static HTML/CSS/JavaScript file `NoteAI_Pro_Demo_Framer.html`.
- Frontend libraries confirmed from code/dependencies: Three.js, ECharts, Lucide icons, Playwright for e2e tests.
- Backend framework: FastAPI with Uvicorn.
- Database: SQLite via Python stdlib `sqlite3` for local development; PostgreSQL via Psycopg for Render/cloud.
- ORM / schema tool: none; local SQLite schema is implemented in `model/db.py`, and versioned PostgreSQL SQL migrations live under `model/migrations/postgres/`.
- Package managers: `pip` for Python dependencies, `npm` for Node/Playwright dependencies.
- Runtime: Python 3.11 in Docker/CI; local `.venv` also exists. Node.js is used for e2e tooling.
- Deployment: Dockerfile, `docker-compose.yml`, Render Blueprint `render.yaml`, GitHub Actions CI, private S3/Git LFS model artifact strategy. Current target is a Render staging environment.

## Common Commands

Install / setup:

```bash
python -m pip install -r model/requirements.txt
npm install
cp model/.env.example model/.env
npx playwright install chromium
```

Local development:

```bash
./start_all.sh start
./start_all.sh status
./start_all.sh stop
python3 -m http.server 5173 --bind 127.0.0.1
```

Tests and checks:

```bash
.venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python -m unittest tests.test_api_contracts
.venv/bin/python -m unittest tests.test_frontend_report_static
npm run test:e2e
npm run test:e2e:headed
npm run test:e2e:ui
python -m py_compile model/*.py
.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json
.venv/bin/python tools/production_readiness_gate.py
docker compose config --quiet
NOTEAI_PUBLIC_API_BASE=https://api.example.invalid ./scripts/build_render_frontend.sh
python scripts/migrate_sqlite_to_postgres.py
```

Deployment-related commands:

```bash
docker compose up --build
python scripts/render_predeploy.py
```

`scripts/migrate_sqlite_to_postgres.py` is dry-run by default. Its `--apply` mode, `scripts/render_predeploy.py`, deployment, Docker service starts, DB-affecting actions, admin user adjustments, model deploy/train, crawler run, and billing/top-up mutation commands require explicit user confirmation.

No confirmed lint, typecheck, or frontend build command exists in `package.json`.

PostgreSQL migrations use `python scripts/render_predeploy.py`. There is no standalone seed command. Local SQLite initialization remains embedded in `model/db.py` and may mutate local SQLite files.

## Coding Rules

- Read `AGENTS.md`, `.codex/handoffs/current-task.md`, `.codex/notes/architecture-summary.md`, and `.codex/notes/risk-register.md` before non-trivial work.
- Understand the existing code path before editing.
- Prefer the smallest viable change.
- Do not do unrelated refactors.
- Do not format unrelated files.
- Do not add production dependencies unless the user explicitly confirms.
- Keep existing code style and naming.
- Keep API routes, response shapes, persisted data, permissions, and billing semantics backward compatible unless the user explicitly requests a breaking change.
- After every code change, state which files changed, why they changed, and how the change was verified.
- If tests, lint, typecheck, build, or e2e checks fail, explain the failure and propose the smallest fix plan before widening the scope.

## Full-stack Safety Rules

Do not casually modify these areas:

- Authentication, login, session, user token, admin token, password hashing.
- Permission checks and admin-only endpoints.
- Billing, subscription, credits, usage records, top-up, refund, cost calculation.
- Database schema, idempotent migrations, SQLite data files, table deletion, data cleanup.
- File upload, screenshot OCR, video upload/understanding, base64 handling.
- Production environment configuration, `.env`, GitHub secrets, Docker deployment variables.
- Third-party service configuration for Claude, Kimi/Moonshot, Amap, Meituan, trend sources, model artifacts.
- Model artifact loading, model registry, training/release reports, Git LFS behavior.
- Crawler and market timing scheduler/worker behavior.

Current modules exist for all of the above except a confirmed real payment gateway callback/reconciliation flow, which is not yet confirmed.

## Workflow Rules

Before starting any non-small task:

1. Read `AGENTS.md`.
2. Read `.codex/handoffs/current-task.md`.
3. Read `.codex/notes/architecture-summary.md`.
4. Read `.codex/notes/risk-register.md`.
5. Check Git status.
6. Output a plan before editing, unless the task is very small and low risk.

After every meaningful stage:

1. Update `.codex/handoffs/current-task.md`.
2. Record changed files.
3. Record test/build/check results.
4. Record remaining risks and next steps.
