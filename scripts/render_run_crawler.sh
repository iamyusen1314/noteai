#!/usr/bin/env sh
set -eu

if [ "${NOTEAI_RUNTIME_ROLE:-}" != "xhs-http" ] \
  || [ "${NOTEAI_XHS_ACQUISITION_ADAPTER:-}" != "spider_xhs_http" ]; then
  echo "tracking requires the pinned xhs-http runtime" >&2
  exit 78
fi

cd /app/model
exec python crawler_worker.py --once
