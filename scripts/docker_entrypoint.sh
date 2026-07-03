#!/usr/bin/env sh
set -eu

cd /app/model
if [ "${NOTEAI_SKIP_MODEL_ARTIFACT_CHECK:-0}" != "1" ]; then
  python -m artifact_loader
fi

exec "$@"
