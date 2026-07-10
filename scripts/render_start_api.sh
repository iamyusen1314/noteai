#!/usr/bin/env sh
set -eu

cd /app/model
if [ "${NOTEAI_MIGRATE_ON_START:-0}" = "1" ]; then
  python /app/scripts/render_predeploy.py
fi
exec python -m uvicorn api:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --timeout-graceful-shutdown "${NOTEAI_GRACEFUL_SHUTDOWN_SECONDS:-30}" \
  --proxy-headers \
  --forwarded-allow-ips="*"
