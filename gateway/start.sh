#!/usr/bin/env sh
set -eu

exec python -m uvicorn claude_gateway:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --no-access-log \
  --proxy-headers \
  --forwarded-allow-ips="*"
