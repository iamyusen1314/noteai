#!/usr/bin/env sh
set -eu

cd /app/model
python -m artifact_loader

exec "$@"
