#!/usr/bin/env sh
set -eu

cd /app/model
# Co-located API relay deployments bind to loopback; standalone legacy services
# retain their explicit/default container bind without changing authentication.
bind_host="${NOTEAI_PAYMENT_BIND_HOST:-0.0.0.0}"
case "$bind_host" in
  127.0.0.1|0.0.0.0) ;;
  *) echo "invalid payment bind address" >&2; exit 78 ;;
esac
exec python -m uvicorn payment_runtime:app \
  --host "$bind_host" \
  --port "${PORT:-8002}" \
  --workers "1" \
  --timeout-graceful-shutdown "${NOTEAI_GRACEFUL_SHUTDOWN_SECONDS:-30}" \
  --proxy-headers \
  --forwarded-allow-ips="${NOTEAI_TRUSTED_PROXY_IPS:-127.0.0.1}"
