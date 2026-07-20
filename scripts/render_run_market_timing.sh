#!/usr/bin/env sh
set -eu

cd /app/model
exec python market_timing_worker.py --once
