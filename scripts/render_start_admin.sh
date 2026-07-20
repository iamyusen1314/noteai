#!/usr/bin/env sh
set -eu

cd /app/model
exec python -m uvicorn admin_server:admin_app \
  --host 0.0.0.0 \
  --port "${PORT:-8001}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --timeout-graceful-shutdown "${NOTEAI_GRACEFUL_SHUTDOWN_SECONDS:-30}" \
  --proxy-headers \
  --forwarded-allow-ips="*"
