#!/usr/bin/env sh
set -eu

cd /app/model
python /app/scripts/render_predeploy.py
exec python crawler_worker.py --once
