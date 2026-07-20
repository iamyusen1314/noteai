#!/usr/bin/env sh
set -eu

cd /app/model
exec python crawler_worker.py --once
