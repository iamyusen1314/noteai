#!/bin/bash
# NoteAI Pro — 一键启动所有服务
# 用法：./start_all.sh [start|stop|status]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$SCRIPT_DIR/model"
VENV="$SCRIPT_DIR/.venv/bin/python"
FRONTEND_PORT="${NOTEAI_FRONTEND_PORT:-5173}"
FRONTEND_PAGE="NoteAI_Pro_Demo_Framer.html"

stop_pid_file() {
  local pid_file="$1"
  local label="$2"
  if [ ! -f "$pid_file" ]; then
    return
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null || true)"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    echo "  停止 $label pid=$pid"
  fi
  rm -f "$pid_file"
}

stop_screen_session() {
  local session="$1"
  if command -v screen >/dev/null 2>&1; then
    screen -S "$session" -X quit >/dev/null 2>&1 || true
  fi
}

stop_port_listener() {
  local port="$1"
  local label="$2"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ' || true)"
  if [ -z "$pids" ]; then
    return
  fi
  echo "  → 清理 $label 端口 $port listener: $pids"
  kill $pids 2>/dev/null || true
  sleep 1
  local remaining
  remaining="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | tr '\n' ' ' || true)"
  if [ -n "$remaining" ]; then
    echo "  → 强制清理 $label 端口 $port listener: $remaining"
    kill -9 $remaining 2>/dev/null || true
  fi
}

stop_existing_services() {
  stop_pid_file /tmp/noteai_api.pid "主 API"
  stop_pid_file /tmp/noteai_admin.pid "管理后台"
  stop_pid_file /tmp/noteai_frontend.pid "前端页面"
  stop_screen_session noteai-api
  stop_screen_session noteai-admin
  stop_screen_session noteai-frontend
  pkill -f "uvicorn.run(\"api:app\"" 2>/dev/null || true
  pkill -f "from admin_server import admin_app" 2>/dev/null || true
  pkill -f "http.server $FRONTEND_PORT" 2>/dev/null || true
  stop_port_listener 8000 "主 API"
  stop_port_listener 8001 "管理后台"
  stop_port_listener "$FRONTEND_PORT" "前端页面"
}

launch_service() {
  local session="$1"
  local internal_cmd="$2"
  local log_file="$3"
  local pid_file="$4"
  if command -v screen >/dev/null 2>&1; then
    screen -S "$session" -X quit >/dev/null 2>&1 || true
    screen -dmS "$session" bash -c "cd \"$SCRIPT_DIR\" && exec \"$SCRIPT_DIR/start_all.sh\" \"$internal_cmd\" > \"$log_file\" 2>&1"
  else
    nohup "$0" "$internal_cmd" > "$log_file" 2>&1 &
    echo $! > "$pid_file"
  fi
}

run_api() {
  cd "$MODEL_DIR"
  exec env NOTEAI_ENV_FILE="$MODEL_DIR/.env" "$VENV" -c '
import os
from dotenv import load_dotenv
import uvicorn

load_dotenv(os.environ["NOTEAI_ENV_FILE"])
uvicorn.run("api:app", host="127.0.0.1", port=8000)
'
}

run_admin() {
  cd "$MODEL_DIR"
  exec env NOTEAI_ENV_FILE="$MODEL_DIR/.env" "$VENV" -c '
import os
from dotenv import load_dotenv
import uvicorn
from admin_server import admin_app

load_dotenv(os.environ["NOTEAI_ENV_FILE"])
uvicorn.run(admin_app, host="127.0.0.1", port=8001)
'
}

run_frontend() {
  cd "$SCRIPT_DIR"
  exec python3 -m http.server "$FRONTEND_PORT" --bind 127.0.0.1
}

case "${1:-start}" in
  _api)
    run_api
    ;;

  _admin)
    run_admin
    ;;

  _frontend)
    run_frontend
    ;;

  start)
    echo "🚀 启动 NoteAI Pro 服务..."
    echo "  → 清理旧本地服务进程..."
    stop_existing_services

    # 主 API（port 8000）
    echo "  → 启动主 API (port 8000)..."
    launch_service noteai-api _api /tmp/noteai_api.log /tmp/noteai_api.pid

    # 管理员后台（port 8001）
    echo "  → 启动管理后台 (port 8001)..."
    launch_service noteai-admin _admin /tmp/noteai_admin.log /tmp/noteai_admin.pid

    # 前端静态页面（port 5173）
    echo "  → 启动前端页面 (port $FRONTEND_PORT)..."
    launch_service noteai-frontend _frontend /tmp/noteai_frontend.log /tmp/noteai_frontend.pid

    # 等待启动
    echo "  → 等待服务就绪..."
    sleep 5
    if curl -s -m 3 http://localhost:8000/health > /dev/null; then
      echo "  ✅ 主 API: http://localhost:8000"
    else
      echo "  ❌ 主 API 启动失败，查看 /tmp/noteai_api.log"
    fi
    if curl -s -m 3 http://localhost:8001/admin/health > /dev/null; then
      echo "  ✅ 管理后台: http://localhost:8001"
    else
      echo "  ❌ 管理后台启动失败，查看 /tmp/noteai_admin.log"
    fi
    if curl -s -m 3 "http://localhost:$FRONTEND_PORT/$FRONTEND_PAGE" > /dev/null; then
      echo "  ✅ 前端页面: http://localhost:$FRONTEND_PORT/$FRONTEND_PAGE"
    else
      echo "  ❌ 前端页面启动失败，查看 /tmp/noteai_frontend.log"
    fi

    echo ""
    echo "📋 管理员账号:"
    echo "   访问: http://localhost:8001"
    echo "   账号: noteai_admin"
    echo "   密码: （见 model/.env ADMIN_PASSWORD）"
    ;;

  stop)
    echo "⏹ 停止所有服务..."
    stop_existing_services
    echo "  ✅ 已停止"
    ;;

  status)
    echo "📊 服务状态:"
    curl -s -m 2 http://localhost:8000/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('  主 API (8000):', d['status'], '| 模型:', d['model'])" 2>/dev/null || echo "  主 API (8000): 未运行"
    curl -s -m 2 http://localhost:8001/admin/health | python3 -c "import sys,json; d=json.load(sys.stdin); print('  管理后台 (8001):', d['status'])" 2>/dev/null || echo "  管理后台 (8001): 未运行"
    curl -s -m 2 "http://localhost:$FRONTEND_PORT/$FRONTEND_PAGE" > /dev/null && echo "  前端页面 ($FRONTEND_PORT): 运行中" || echo "  前端页面 ($FRONTEND_PORT): 未运行"
    ;;

  *)
    echo "用法: $0 [start|stop|status]"
    exit 1
    ;;
esac
