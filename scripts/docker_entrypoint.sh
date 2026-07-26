#!/usr/bin/env sh
set -eu

runtime_role_file=/etc/noteai-runtime-role
if [ ! -e "$runtime_role_file" ]; then
  echo "runtime role marker is missing" >&2
  exit 78
fi
if [ ! -r "$runtime_role_file" ]; then
  echo "runtime role marker is unreadable" >&2
  exit 78
fi
image_runtime_role=
if ! IFS= read -r image_runtime_role < "$runtime_role_file"; then
  echo "runtime role marker could not be read" >&2
  exit 78
fi
if [ -z "$image_runtime_role" ]; then
  echo "runtime role marker is empty" >&2
  exit 78
fi

case "$image_runtime_role" in
  api|admin|payment|xhs-http|ai-worker) ;;
  *)
    echo "runtime role marker is invalid" >&2
    exit 78
    ;;
esac

declared_runtime_role="${NOTEAI_RUNTIME_ROLE:-}"
if [ "$declared_runtime_role" != "$image_runtime_role" ]; then
  echo "declared runtime role does not match the image role" >&2
  exit 78
fi

is_unsigned_integer() {
  case "$1" in
    ''|*[!0-9]*) return 1 ;;
    *) return 0 ;;
  esac
}

command_allowed=0
if [ "$image_runtime_role" = "api" ]; then
  case "${NOTEAI_API_STARTS_TREND_SCHEDULER:-0}" in
    1|true|TRUE|True|yes|YES|Yes|on|ON|On)
      echo "api-runtime cannot start the trend scheduler" >&2
      exit 78
      ;;
  esac

  if [ "$#" -eq 1 ] && [ "$1" = "/app/scripts/render_start_api.sh" ]; then
    command_allowed=1
  elif [ "$#" -eq 2 ] && [ "$1" = "python" ] && [ "$2" = "/app/scripts/render_predeploy.py" ]; then
    command_allowed=1
  fi
elif [ "$image_runtime_role" = "admin" ]; then
  if [ "$#" -eq 1 ] && [ "$1" = "/app/scripts/render_start_admin.sh" ]; then
    command_allowed=1
  elif [ "$#" -eq 8 ] \
    && [ "$1" = "python" ] \
    && [ "$2" = "-m" ] \
    && [ "$3" = "uvicorn" ] \
    && [ "$4" = "admin_server:admin_app" ] \
    && [ "$5" = "--host" ] \
    && [ "$6" = "0.0.0.0" ] \
    && [ "$7" = "--port" ] \
    && [ "$8" = "8001" ]; then
    command_allowed=1
  fi
elif [ "$image_runtime_role" = "payment" ]; then
  if [ "$#" -eq 1 ] \
    && [ "$1" = "/app/scripts/render_start_payment.sh" ]; then
    command_allowed=1
  fi
elif [ "$image_runtime_role" = "xhs-http" ]; then
  if [ "${NOTEAI_XHS_ACQUISITION_ADAPTER:-}" != "spider_xhs_http" ]; then
    echo "xhs-http runtime requires the pinned acquisition adapter" >&2
    exit 78
  fi
  xhs_service="${NOTEAI_XHS_SERVICE:-}"
  case "$xhs_service" in
    trends|tracking) ;;
    *)
      echo "xhs-http runtime requires an exact service role" >&2
      exit 78
      ;;
  esac
  if [ "$#" -eq 1 ]; then
    case "$1" in
      /app/scripts/render_run_market_timing.sh)
        [ "$xhs_service" = "trends" ] && command_allowed=1
        ;;
      /app/scripts/render_run_crawler.sh)
        [ "$xhs_service" = "tracking" ] && command_allowed=1
        ;;
      /bin/false) command_allowed=1 ;;
    esac
  elif [ "$#" -eq 2 ] && [ "$1" = "python" ]; then
    case "$2" in
      market_timing_worker.py)
        [ "$xhs_service" = "trends" ] && command_allowed=1
        ;;
      crawler_worker.py)
        [ "$xhs_service" = "tracking" ] && command_allowed=1
        ;;
    esac
  elif [ "$#" -eq 3 ] && [ "$1" = "python" ]; then
    case "$2:$3" in
      market_timing_worker.py:--once|market_timing_worker.py:--healthcheck|market_timing_worker.py:--acknowledge-unknown|market_timing_worker.py:--clear-session-block)
        [ "$xhs_service" = "trends" ] && command_allowed=1
        ;;
      crawler_worker.py:--once|crawler_worker.py:--healthcheck)
        [ "$xhs_service" = "tracking" ] && command_allowed=1
        ;;
    esac
  elif [ "$#" -eq 5 ] \
    && [ "$1" = "python" ] \
    && [ "$2" = "market_timing_worker.py" ] \
    && [ "$3" = "--daemon" ] \
    && [ "$4" = "--interval" ] \
    && is_unsigned_integer "$5" \
    && [ "$xhs_service" = "trends" ]; then
    command_allowed=1
  elif [ "$#" -eq 7 ] \
    && [ "$1" = "python" ] \
    && [ "$2" = "crawler_worker.py" ] \
    && [ "$3" = "--loop" ] \
    && [ "$4" = "--interval-minutes" ] \
    && is_unsigned_integer "$5" \
    && [ "$6" = "--limit" ] \
    && is_unsigned_integer "$7" \
    && [ "$xhs_service" = "tracking" ]; then
    command_allowed=1
  fi
else
  case "${NOTEAI_DURABLE_AI_SUSPENDED:-1}" in
    0|false|FALSE|False|no|NO|No|off|OFF|Off)
      if [ "${NOTEAI_DURABLE_AI_PROCESSOR:-}" != "production-v1" ]; then
        echo "ai-worker requires an exact production processor" >&2
        exit 78
      fi
      ;;
  esac
  if [ "$#" -eq 3 ] \
    && [ "$1" = "python" ] \
    && [ "$2" = "durable_ai_worker.py" ]; then
    case "$3" in
      --healthcheck|--once|--recover-unstarted|--reconcile-stale) command_allowed=1 ;;
    esac
  fi
fi

if [ "$command_allowed" -ne 1 ]; then
  echo "command is not allowed for this runtime role" >&2
  exit 78
fi

cd /app/model
if [ "${NOTEAI_SKIP_MODEL_ARTIFACT_CHECK:-0}" != "1" ]; then
  python -m artifact_loader
fi

exec "$@"
