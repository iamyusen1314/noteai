# NoteAI Pro Deployment Notes

## Local Setup

1. Copy `model/.env.example` to `model/.env`.
2. Fill `MOONSHOT_API_KEY`, `ANTHROPIC_API_KEY`, and a strong `ADMIN_PASSWORD`.
3. Start both services with Docker Compose:

```bash
docker compose up --build
```

Main API: `http://localhost:8000`

Admin: `http://localhost:8001`

## Production Notes

- Keep `NOTEAI_ENABLE_TEST_BILLING=0` unless running a controlled local test.
- Do not commit `model/.env`; it contains live API and admin secrets.
- The API and admin services must share `model/data` and `model/artifacts` so model deployment takes effect across containers.
- GitHub production secrets and variables are documented in `docs/DEPLOYMENT_SECRETS.md`.
- V0.4 model artifact loading and object-storage fallback are documented in `docs/MODEL_ARTIFACT_CLOUD_STRATEGY.md`.
- Real payment integration still needs an order, callback, reconciliation, and subscription activation flow before paid public launch.

## Local Regression Checks

```bash
python3 -m py_compile model/*.py
.venv/bin/python -m unittest tests/test_api_contracts.py
.venv/bin/python tools/quality_gate.py quality/golden_notes.sample.json
docker compose config --quiet
```
