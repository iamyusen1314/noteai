#!/usr/bin/env sh
set -eu

cd /app/model
exec python -m uvicorn payment_runtime:app \
  --host 0.0.0.0 \
  --port "${PORT:-8002}" \
  --workers "1" \
  --timeout-graceful-shutdown "${NOTEAI_GRACEFUL_SHUTDOWN_SECONDS:-30}" \
  --proxy-headers \
  --forwarded-allow-ips="${NOTEAI_TRUSTED_PROXY_IPS:-127.0.0.1}"
