#!/usr/bin/env sh
set -eu

cd /app/model
python /app/scripts/render_predeploy.py
exec python market_timing_worker.py --once
