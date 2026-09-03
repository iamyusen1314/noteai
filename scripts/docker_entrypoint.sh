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

is_canonical_uuid() {
  [ "${#1}" -eq 36 ] || return 1
  case "$1" in
    ????????-????-????-????-????????????) ;;
    *) return 1 ;;
  esac
  case "$1" in
    *[!0-9a-f-]*) return 1 ;;
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
  durable_component="${NOTEAI_DURABLE_AI_COMPONENT:-}"
  dispatcher_acceptance=0
  case "$durable_component" in
    ''|dispatcher|worker) ;;
    *)
      echo "ai-worker runtime requires an exact durable component" >&2
      exit 78
      ;;
  esac
  if [ "$durable_component" = "dispatcher" ] \
    && { [ "${NOTEAI_PRIVATE_STORAGE_BACKEND+x}" = x ] \
      || [ "${NOTEAI_OSS_PRIVATE_BUCKET+x}" = x ] \
      || [ "${NOTEAI_OSS_REGION+x}" = x ] \
      || [ "${NOTEAI_OSS_ENDPOINT+x}" = x ] \
      || [ "${NOTEAI_OSS_RAM_ROLE+x}" = x ] \
      || [ "${NOTEAI_PRIVATE_STORAGE_KEY_EPOCH+x}" = x ] \
      || [ "${NOTEAI_OSS_KEY_PREFIX+x}" = x ]; }; then
    echo "ai-dispatcher rejects private storage configuration" >&2
    exit 78
  fi
  if [ "$durable_component" = "dispatcher" ] \
    && { [ "${NOTEAI_DURABLE_AI_ACCEPTANCE_MODE+x}" = x ] \
      || [ "${NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID+x}" = x ]; }; then
    if [ "${NOTEAI_DURABLE_AI_ACCEPTANCE_MODE:-}" != "1" ] \
      || ! is_canonical_uuid \
        "${NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID:-}"; then
      echo "ai-dispatcher acceptance requires exact bounded operation" >&2
      exit 78
    fi
    dispatcher_acceptance=1
  fi
  case "${NOTEAI_DURABLE_AI_SUSPENDED:-1}" in
    0|false|FALSE|False|no|NO|No|off|OFF|Off)
      if [ "$durable_component" = "worker" ]; then
        case "${NOTEAI_DURABLE_AI_PROCESSOR:-}" in
          production-v1) ;;
          internal-acceptance-v1)
            if [ "${NOTEAI_DURABLE_AI_ACCEPTANCE_MODE:-}" != "1" ] \
              || ! is_canonical_uuid \
                "${NOTEAI_DURABLE_AI_ACCEPTANCE_OPERATION_ID:-}"; then
              echo "ai-worker acceptance processor requires exact bounded mode" >&2
              exit 78
            fi
            ;;
          *)
            echo "ai-worker requires an exact production processor" >&2
            exit 78
            ;;
        esac
      elif [ -z "$durable_component" ] \
        && [ "${NOTEAI_DURABLE_AI_PROCESSOR:-}" != "production-v1" ]; then
          echo "ai-worker requires an exact production processor" >&2
          exit 78
      fi
      ;;
  esac
  if [ "$#" -eq 3 ] \
    && [ "$1" = "python" ] \
    && [ "$2" = "durable_ai_worker.py" ]; then
    if [ -z "$durable_component" ]; then
      case "$3" in
        --healthcheck|--once|--recover-unstarted|--reconcile-stale) command_allowed=1 ;;
      esac
    elif [ "$durable_component" = "dispatcher" ]; then
      case "$3" in
        --healthcheck|--dispatcher-once|--dispatcher-loop) command_allowed=1 ;;
      esac
      if [ "$dispatcher_acceptance" -eq 1 ] \
        && [ "$3" != "--dispatcher-once" ]; then
        command_allowed=0
      fi
    else
      case "$3" in
        --healthcheck|--worker-once|--worker-loop|--reconcile-stale) command_allowed=1 ;;
      esac
      if [ "${NOTEAI_DURABLE_AI_PROCESSOR:-}" = "internal-acceptance-v1" ] \
        && [ "$3" != "--healthcheck" ] \
        && [ "$3" != "--worker-once" ]; then
        command_allowed=0
      fi
    fi
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
