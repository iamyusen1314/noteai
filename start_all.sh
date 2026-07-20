#!/bin/bash
# NoteAI Pro — 一键启动所有服务
# 用法：./start_all.sh [start|stop|status]

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$SCRIPT_DIR/model"
VENV="$SCRIPT_DIR/.venv/bin/python"
FRONTEND_PORT="${NOTEAI_FRONTEND_PORT:-5173}"
FRONTEND_PAGE="NoteAI_Pro_Demo_Framer.html"
TRENDS_INTERVAL="${NOTEAI_MARKET_TIMING_WORKER_INTERVAL_MINUTES:-60}"
TRENDS_SNAPSHOT_PATH="$MODEL_DIR/data/market_timing_snapshot.json"

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

stop_core_services() {
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

stop_existing_services() {
  stop_core_services
  stop_pid_file /tmp/noteai_trends_worker.pid "趋势 worker"
  stop_screen_session noteai-trends
  pkill -f "market_timing_worker.py.*--daemon" 2>/dev/null || true
}

ensure_local_trends_safe() {
  "$VENV" - "$MODEL_DIR/.env" <<'PY'
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:
    print("  ❌ 无法加载 dotenv，拒绝启动趋势 worker")
    sys.exit(1)

env_file = Path(sys.argv[1])
if env_file.exists():
    load_dotenv(env_file)

env_name = (
    os.environ.get("NOTEAI_ENV")
    or os.environ.get("ENVIRONMENT")
    or os.environ.get("APP_ENV")
    or "development"
).strip().lower()
if env_name in {"prod", "production"}:
    print("  ❌ 当前环境标记为 production，拒绝启动本地趋势 worker")
    sys.exit(1)

if os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_URL", "").strip():
    print("  ❌ 检测到趋势快照上传配置，拒绝以本地测试模式启动")
    sys.exit(1)

db_url = os.environ.get("DATABASE_URL", "").strip().lower()
if db_url.startswith(("postgres://", "postgresql://", "mysql://")):
    print("  ❌ 检测到远程数据库连接配置，拒绝启动本地趋势 worker")
    sys.exit(1)

print("  ✅ 趋势 worker 本地安全检查通过（只写本地 data 目录）")
PY
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

run_trends_worker() {
  cd "$MODEL_DIR"
  exec env NOTEAI_ENV_FILE="$MODEL_DIR/.env" "$VENV" -c '
import os
from dotenv import load_dotenv
import sys

load_dotenv(os.environ["NOTEAI_ENV_FILE"])
os.environ["NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_URL"] = ""

import market_timing_worker

sys.argv = [
    "market_timing_worker.py",
    "--daemon",
    "--interval", os.environ.get("NOTEAI_MARKET_TIMING_WORKER_INTERVAL_MINUTES", "60"),
    "--snapshot-path", os.environ.get("NOTEAI_MARKET_TIMING_SNAPSHOT_PATH", "data/market_timing_snapshot.json"),
    "--upload-url", "",
]
raise SystemExit(market_timing_worker.main())
'
}

launch_core_services() {
  # 主 API（port 8000）
  echo "  → 启动主 API (port 8000)..."
  launch_service noteai-api _api /tmp/noteai_api.log /tmp/noteai_api.pid

  # 管理员后台（port 8001）
  echo "  → 启动管理后台 (port 8001)..."
  launch_service noteai-admin _admin /tmp/noteai_admin.log /tmp/noteai_admin.pid

  # 前端静态页面（port 5173）
  echo "  → 启动前端页面 (port $FRONTEND_PORT)..."
  launch_service noteai-frontend _frontend /tmp/noteai_frontend.log /tmp/noteai_frontend.pid
}

print_core_ready() {
  if curl -fsS -m 3 http://localhost:8000/health/ready > /dev/null; then
    echo "  ✅ 主 API: http://localhost:8000"
  else
    echo "  ❌ 主 API 启动失败，查看 /tmp/noteai_api.log"
  fi
  if curl -fsS -m 3 http://localhost:8001/health/ready > /dev/null; then
    echo "  ✅ 管理后台: http://localhost:8001"
  else
    echo "  ❌ 管理后台启动失败，查看 /tmp/noteai_admin.log"
  fi
  if curl -s -m 3 "http://localhost:$FRONTEND_PORT/$FRONTEND_PAGE" > /dev/null; then
    echo "  ✅ 前端页面: http://localhost:$FRONTEND_PORT/$FRONTEND_PAGE"
  else
    echo "  ❌ 前端页面启动失败，查看 /tmp/noteai_frontend.log"
  fi
}

launch_trends_worker() {
  echo "  → 启动趋势 worker（本地测试模式，每 ${TRENDS_INTERVAL} 分钟）..."
  ensure_local_trends_safe
  launch_service noteai-trends _trends /tmp/noteai_trends_worker.log /tmp/noteai_trends_worker.pid
}

stop_trends_worker() {
  stop_pid_file /tmp/noteai_trends_worker.pid "趋势 worker"
  stop_screen_session noteai-trends
  pkill -f "market_timing_worker.py.*--daemon" 2>/dev/null || true
}

print_trends_status() {
  local pids
  pids="$(pgrep -f "market_timing_worker.py.*--daemon" 2>/dev/null | tr '\n' ' ' || true)"
  if [ -n "$pids" ]; then
    echo "  趋势 worker: 运行中 pid=$pids"
  else
    echo "  趋势 worker: 未运行"
  fi
  "$VENV" - "$MODEL_DIR/data/hot_keywords.db" "$TRENDS_SNAPSHOT_PATH" <<'PY'
import json
import sqlite3
import sys
from pathlib import Path

db_path = Path(sys.argv[1])
snapshot_path = Path(sys.argv[2])

if snapshot_path.exists():
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        domains = ", ".join(sorted((payload.get("domains") or {}).keys())) or "无"
        print(f"  趋势快照: 存在 | generated_at={payload.get('generated_at', '未知')} | domains={domains}")
    except Exception:
        print("  趋势快照: 存在但无法解析")
else:
    print("  趋势快照: 不存在")

if not db_path.exists():
    print("  热词库: 不存在")
    sys.exit(0)

conn = sqlite3.connect(str(db_path))
conn.row_factory = sqlite3.Row
try:
    latest = conn.execute("SELECT MAX(captured_at) latest FROM hot_keywords").fetchone()["latest"]
    print(f"  热词库最近采集: {latest or '未知'}")
    for domain in ("美食", "旅行", "穿搭", "美妆", "家居", "健身"):
        row = conn.execute(
            """
            SELECT COUNT(*) total,
                   SUM(CASE WHEN quality_score>=55 THEN 1 ELSE 0 END) qualified,
                   SUM(CASE WHEN quality_score>=74 THEN 1 ELSE 0 END) strong,
                   MAX(captured_at) latest
            FROM hot_keywords
            WHERE category IN (?, ?)
            """,
            (domain, "餐饮" if domain == "美食" else domain),
        ).fetchone()
        print(
            f"  {domain}: 样本={int(row['total'] or 0)} "
            f"合格={int(row['qualified'] or 0)} 强={int(row['strong'] or 0)} "
            f"最近={row['latest'] or '未知'}"
        )
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    if "xhs_crawler_health" in tables:
        health = conn.execute(
            """
            SELECT adapter, domain, status, evidence_count, error_code, checked_at
            FROM xhs_crawler_health
            ORDER BY checked_at DESC
            LIMIT 3
            """
        ).fetchall()
        if health:
            print("  XHS health 最近记录:")
            for item in health:
                err = f" error={item['error_code']}" if item["error_code"] else ""
                print(
                    f"    - {item['checked_at']} {item['adapter']} "
                    f"{item['domain']} status={item['status']} evidence={item['evidence_count']}{err}"
                )
        else:
            print("  XHS health: 暂无记录")
    else:
        print("  XHS health: 表尚未初始化")
finally:
    conn.close()
PY
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

  _trends)
    run_trends_worker
    ;;

  start)
    echo "🚀 启动 NoteAI Pro 服务..."
    echo "  → 清理旧本地服务进程..."
    stop_existing_services

    launch_core_services

    if [ "${2:-}" = "--with-trends" ]; then
      launch_trends_worker
    fi

    # 等待启动
    echo "  → 等待服务就绪..."
    sleep 5
    print_core_ready
    if [ "${2:-}" = "--with-trends" ]; then
      sleep 1
      print_trends_status
    fi

    echo ""
    echo "📋 管理员账号:"
    echo "   访问: http://localhost:8001"
    echo "   账号: noteai_admin"
    echo "   密码: （见 model/.env ADMIN_PASSWORD）"
    ;;

  start-full-test)
    "$0" start --with-trends
    ;;

  restart-core)
    echo "🔄 重启 API / admin / frontend（保留趋势 worker）..."
    stop_core_services
    launch_core_services
    echo "  → 等待服务就绪..."
    sleep 5
    print_core_ready
    ;;

  stop)
    echo "⏹ 停止所有服务..."
    stop_existing_services
    echo "  ✅ 已停止"
    ;;

  trends-start)
    echo "📈 启动趋势 worker..."
    stop_trends_worker
    launch_trends_worker
    sleep 2
    print_trends_status
    ;;

  trends-stop)
    echo "📉 停止趋势 worker..."
    stop_trends_worker
    echo "  ✅ 已停止"
    ;;

  trends-status)
    echo "📈 趋势 worker 状态:"
    print_trends_status
    ;;

  status)
    echo "📊 服务状态:"
    curl -fsS -m 2 http://localhost:8000/health/ready | python3 -c "import sys,json; d=json.load(sys.stdin); print('  主 API (8000):', d['status'], '| 模型:', d['checks']['model']['version'])" 2>/dev/null || echo "  主 API (8000): 未就绪"
    curl -fsS -m 2 http://localhost:8001/health/ready | python3 -c "import sys,json; d=json.load(sys.stdin); print('  管理后台 (8001):', d['status'])" 2>/dev/null || echo "  管理后台 (8001): 未就绪"
    curl -s -m 2 "http://localhost:$FRONTEND_PORT/$FRONTEND_PAGE" > /dev/null && echo "  前端页面 ($FRONTEND_PORT): 运行中" || echo "  前端页面 ($FRONTEND_PORT): 未运行"
    print_trends_status
    ;;

  *)
    echo "用法: $0 [start|start --with-trends|start-full-test|restart-core|stop|status|trends-start|trends-stop|trends-status]"
    exit 1
    ;;
esac
