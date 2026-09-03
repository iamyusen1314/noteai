#!/usr/bin/env sh
set -eu

if [ "${NOTEAI_RUNTIME_ROLE:-}" != "xhs-http" ] \
  || [ "${NOTEAI_XHS_ACQUISITION_ADAPTER:-}" != "spider_xhs_http" ] \
  || [ "${NOTEAI_XHS_SERVICE:-}" != "trends" ]; then
  echo "market timing requires the pinned xhs-http runtime" >&2
  exit 78
fi

cd /app/model
exec python market_timing_worker.py --once
