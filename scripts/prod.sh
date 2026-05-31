#!/usr/bin/env bash
# 生产/部署：一键启动 / 停止 data-agent 后端 + Next.js 前端
#
# 用法:
#   ./scripts/prod.sh              # 默认后台启动前后端
#   ./scripts/prod.sh -d           # 显式后台启动
#   ./scripts/prod.sh -f           # 前台启动（Ctrl+C 同时退出）
#   ./scripts/prod.sh -k           # 停止前后端
#   ./scripts/prod.sh stop         # 同 -k
#   ./scripts/prod.sh restart      # 重启（后台）
#   ./scripts/prod.sh build        # 仅构建前端生产包
#   ./scripts/prod.sh status       # 查看状态
#   ./scripts/prod.sh backend      # 仅后台后端
#   ./scripts/prod.sh frontend     # 仅后台前端
#
# 环境变量（可选）:
#   API_HOST=0.0.0.0   API_PORT=8080   WEB_HOST=0.0.0.0   WEB_PORT=3000
#   MINERU_LOCAL_ENABLED=0
#   PROD_SKIP_BUILD=1   # 跳过前端 build（.next 已存在时）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT/.prod/pids"
LOG_DIR="$ROOT/.prod/logs"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8080}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-3000}"
API_ORIGIN="${DATA_AGENT_API_ORIGIN:-http://127.0.0.1:${API_PORT}}"

BACKEND_PID_FILE="$PID_DIR/backend.pid"
FRONTEND_PID_FILE="$PID_DIR/frontend.pid"

mkdir -p "$PID_DIR" "$LOG_DIR"

usage() {
  cat <<EOF
用法:
  $0              后台启动前后端（默认，同 -d）
  $0 -d           显式后台启动前后端
  $0 -f           前台启动（Ctrl+C 同时退出）
  $0 -k           停止前后端
  $0 stop         同 -k
  $0 restart      重启（后台）
  $0 build        构建前端生产包
  $0 status       查看运行状态
  $0 backend      仅后台启动后端
  $0 frontend     仅后台启动前端

日志: $LOG_DIR/backend.log, $LOG_DIR/frontend.log
EOF
}

activate_venv() {
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    export PATH="$ROOT/.venv/bin:$PATH"
    export VIRTUAL_ENV="$ROOT/.venv"
    return 0
  fi
  echo "错误: 未找到 .venv，请先在项目根目录执行: uv sync" >&2
  exit 1
}

load_env() {
  activate_venv
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$ROOT/.env"
    set +a
  fi
  export MINERU_LOCAL_ENABLED="${MINERU_LOCAL_ENABLED:-0}"
}

is_running() {
  local pid_file="$1"
  [[ -f "$pid_file" ]] || return 1
  local pid
  pid="$(cat "$pid_file")"
  kill -0 "$pid" 2>/dev/null
}

port_in_use() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | grep -q ":$port"
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$port" -sTCP:LISTEN -t >/dev/null 2>&1
  else
    return 1
  fi
}

kill_pid_tree() {
  local pid="$1"
  [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]] || return 0
  kill "$pid" 2>/dev/null || true
  if command -v pkill >/dev/null 2>&1; then
    pkill -P "$pid" 2>/dev/null || true
  fi
  for _ in $(seq 1 20); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 0.2
  done
  kill -9 "$pid" 2>/dev/null || true
  if command -v pkill >/dev/null 2>&1; then
    pkill -9 -P "$pid" 2>/dev/null || true
  fi
}

find_kill_root() {
  local pid="$1"
  [[ -n "$pid" && "$pid" =~ ^[0-9]+$ ]] || return 0
  local current="$pid"
  local cmd ppid i
  for i in $(seq 1 12); do
    cmd="$(ps -o cmd= -p "$current" 2>/dev/null || true)"
    if [[ "$cmd" == *"next start"* || "$cmd" == *"bun run start"* \
      || "$cmd" == *"standalone/server.js"* \
      || "$cmd" == *"uvicorn data_agent.main:app"* ]]; then
      echo "$current"
      return
    fi
    ppid="$(ps -o ppid= -p "$current" 2>/dev/null | tr -d ' ')"
    [[ -z "$ppid" || "$ppid" -le 1 ]] && break
    current="$ppid"
  done
  echo "$pid"
}

pids_on_port() {
  local port="$1"
  local pids=""
  if command -v fuser >/dev/null 2>&1; then
    pids="$(fuser "$port/tcp" 2>/dev/null | tr -s ' ' || true)"
  fi
  if [[ -z "$pids" ]] && command -v ss >/dev/null 2>&1; then
    pids="$(ss -tlnp "sport = :$port" 2>/dev/null \
      | grep -oE 'pid=[0-9]+' \
      | cut -d= -f2 \
      | sort -u \
      | tr '\n' ' ' || true)"
  fi
  if [[ -z "$pids" ]] && command -v lsof >/dev/null 2>&1; then
    pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  fi
  local filtered=""
  local p
  for p in $pids; do
    [[ "$p" =~ ^[0-9]+$ ]] && filtered="$filtered $p"
  done
  echo "$filtered"
}

stop_port() {
  local name="$1"
  local port="$2"
  local pid root
  for pid in $(pids_on_port "$port"); do
    root="$(find_kill_root "$pid")"
    if [[ "$root" == "$pid" ]]; then
      echo "[$name] 停止占用端口 $port 的进程 $pid"
    else
      echo "[$name] 停止占用端口 $port 的进程 $pid (root $root)"
    fi
    kill_pid_tree "$root"
  done
}

stop_untracked() {
  local pid cmd
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  while IFS= read -r pid; do
    [[ -z "$pid" || ! "$pid" =~ ^[0-9]+$ ]] && continue
    cmd="$(ps -o cmd= -p "$pid" 2>/dev/null || true)"
    [[ -z "$cmd" ]] && continue

    if [[ "$cmd" == *"$ROOT/web"* && "$cmd" == *"next start"* ]] \
      && [[ "$cmd" == *" -p $WEB_PORT"* || "$cmd" == *" -p$WEB_PORT"* ]]; then
      echo "[frontend] 停止未跟踪的前端进程 $pid"
      kill_pid_tree "$pid"
      continue
    fi

    if [[ "$cmd" == *"$ROOT/web"* && "$cmd" == *"standalone/server.js"* ]]; then
      echo "[frontend] 停止未跟踪的前端进程 $pid"
      kill_pid_tree "$pid"
      continue
    fi

    if [[ "$cmd" == *"bun run start"* ]] \
      && [[ "$cmd" == *" -p $WEB_PORT"* || "$cmd" == *" -p$WEB_PORT"* ]]; then
      echo "[frontend] 停止未跟踪的前端进程 $pid"
      kill_pid_tree "$pid"
      continue
    fi

    if [[ "$cmd" == *"uvicorn data_agent.main:app"* ]] \
      && [[ "$cmd" == *"--port $API_PORT"* || "$cmd" == *"--port=$API_PORT"* ]]; then
      echo "[backend] 停止未跟踪的后端进程 $pid"
      kill_pid_tree "$pid"
    fi
  done < <(pgrep -f "next start|bun run start|standalone/server.js|uvicorn data_agent.main:app" 2>/dev/null || true)
}

verify_stopped() {
  local failed=0
  if port_in_use "$API_PORT"; then
    echo "[backend] 警告: 端口 $API_PORT 仍被占用" >&2
    failed=1
  fi
  if port_in_use "$WEB_PORT"; then
    echo "[frontend] 警告: 端口 $WEB_PORT 仍被占用" >&2
    failed=1
  fi
  return "$failed"
}

stop_one() {
  local name="$1"
  local pid_file="$2"
  if is_running "$pid_file"; then
    local pid
    pid="$(cat "$pid_file")"
    echo "[$name] 停止进程 $pid"
    kill_pid_tree "$pid"
  fi
  rm -f "$pid_file"
}

stop_all() {
  load_env
  stop_one "backend" "$BACKEND_PID_FILE"
  stop_one "frontend" "$FRONTEND_PID_FILE"
  stop_port "backend" "$API_PORT"
  stop_port "frontend" "$WEB_PORT"
  stop_untracked
  stop_port "backend" "$API_PORT"
  stop_port "frontend" "$WEB_PORT"
  sleep 0.5
  verify_stopped || true
  echo "已停止所有 prod 进程"
}

ensure_python() {
  activate_venv
  if ! python -c "import uvicorn" 2>/dev/null; then
    echo "错误: 缺少 uvicorn，请执行: uv sync" >&2
    exit 1
  fi
}

ensure_node() {
  if ! command -v bun >/dev/null 2>&1; then
    echo "错误: 未找到 bun（前端使用 Bun 管理依赖，见 https://bun.sh）" >&2
    exit 1
  fi
  if [[ ! -d "$ROOT/web/node_modules" ]]; then
    echo "[frontend] 首次运行，安装依赖..."
    (cd "$ROOT/web" && bun install)
  fi
}

frontend_build_ready() {
  [[ -f "$ROOT/web/.next/BUILD_ID" && -f "$ROOT/web/.next/standalone/server.js" ]]
}

prepare_standalone_assets() {
  local web="$ROOT/web"
  if [[ ! -d "$web/.next/standalone" ]]; then
    return 0
  fi
  mkdir -p "$web/.next/standalone/.next"
  if [[ -d "$web/.next/static" ]]; then
    rm -rf "$web/.next/standalone/.next/static"
    cp -r "$web/.next/static" "$web/.next/standalone/.next/"
  fi
  if [[ -d "$web/public" ]]; then
    rm -rf "$web/.next/standalone/public"
    cp -r "$web/public" "$web/.next/standalone/"
  fi
}

build_frontend() {
  ensure_node
  echo "[frontend] 构建生产包..."
  (
    cd "$ROOT/web"
    export DATA_AGENT_API_ORIGIN="$API_ORIGIN"
    bun run build
  )
  prepare_standalone_assets
}

frontend_baked_api_origin() {
  local manifest="$ROOT/web/.next/routes-manifest.json"
  [[ -f "$manifest" ]] || return 1
  python3 - <<'PY' "$manifest"
import json
import sys

manifest_path = sys.argv[1]
with open(manifest_path, encoding="utf-8") as handle:
    manifest = json.load(handle)

for rewrite in manifest.get("rewrites", {}).get("afterFiles", []):
    if rewrite.get("source") != "/api/:path*":
        continue
    destination = str(rewrite.get("destination") or "")
    marker = "/api/"
    if marker not in destination:
        continue
    print(destination.split(marker, 1)[0].rstrip("/"))
    raise SystemExit(0)

raise SystemExit(1)
PY
}

ensure_frontend_build() {
  if [[ "${PROD_SKIP_BUILD:-0}" == "1" ]] && frontend_build_ready; then
    local baked_origin=""
    baked_origin="$(frontend_baked_api_origin 2>/dev/null || true)"
    if [[ -n "$baked_origin" && "$baked_origin" != "$API_ORIGIN" ]]; then
      echo "[frontend] 构建中的 API 代理 ($baked_origin) 与当前 API_ORIGIN ($API_ORIGIN) 不一致，重新构建..."
      build_frontend
    else
      prepare_standalone_assets
    fi
    return 0
  fi
  if ! frontend_build_ready; then
    build_frontend
    return 0
  fi
  local baked_origin=""
  baked_origin="$(frontend_baked_api_origin 2>/dev/null || true)"
  if [[ -n "$baked_origin" && "$baked_origin" != "$API_ORIGIN" ]]; then
    echo "[frontend] 构建中的 API 代理 ($baked_origin) 与当前 API_ORIGIN ($API_ORIGIN) 不一致，重新构建..."
    build_frontend
  else
    prepare_standalone_assets
  fi
}

run_frontend_server() {
  cd "$ROOT/web"
  export DATA_AGENT_API_ORIGIN="$API_ORIGIN"
  export HOSTNAME="$WEB_HOST"
  export PORT="$WEB_PORT"
  exec node .next/standalone/server.js
}

start_backend() {
  ensure_python
  if is_running "$BACKEND_PID_FILE"; then
    echo "[backend] 已在运行 (pid $(cat "$BACKEND_PID_FILE"))"
    return
  fi
  if port_in_use "$API_PORT"; then
    echo "[backend] 端口 $API_PORT 已被占用，请修改 API_PORT 或先执行 ./scripts/prod.sh -k" >&2
    exit 1
  fi

  echo "[backend] 启动 http://${API_HOST}:${API_PORT}"
  (
    cd "$ROOT"
    export MINERU_LOCAL_ENABLED
    exec python -m uvicorn data_agent.main:app --host "$API_HOST" --port "$API_PORT" \
      >>"$LOG_DIR/backend.log" 2>&1
  ) &
  echo $! >"$BACKEND_PID_FILE"

  local ready=0
  for _ in $(seq 1 30); do
    if ! is_running "$BACKEND_PID_FILE"; then
      break
    fi
    if port_in_use "$API_PORT"; then
      ready=1
      break
    fi
    sleep 0.5
  done

  if [[ "$ready" != "1" ]]; then
    echo "[backend] 启动失败，查看 $LOG_DIR/backend.log" >&2
    tail -20 "$LOG_DIR/backend.log" >&2 || true
    exit 1
  fi
  echo "[backend] pid $(cat "$BACKEND_PID_FILE") | 日志 $LOG_DIR/backend.log"
  echo "[backend] Swagger: http://127.0.0.1:${API_PORT}/docs"
}

start_frontend() {
  ensure_node
  ensure_frontend_build
  if is_running "$FRONTEND_PID_FILE"; then
    echo "[frontend] 已在运行 (pid $(cat "$FRONTEND_PID_FILE"))"
    return
  fi
  if port_in_use "$WEB_PORT"; then
    echo "[frontend] 端口 $WEB_PORT 已被占用，请修改 WEB_PORT 或先执行 ./scripts/prod.sh -k" >&2
    exit 1
  fi

  echo "[frontend] 启动 http://${WEB_HOST}:${WEB_PORT} (API -> $API_ORIGIN)"
  (
    run_frontend_server
  ) >>"$LOG_DIR/frontend.log" 2>&1 &
  echo $! >"$FRONTEND_PID_FILE"
  sleep 1.5
  if ! is_running "$FRONTEND_PID_FILE"; then
    echo "[frontend] 启动失败，查看 $LOG_DIR/frontend.log" >&2
    tail -20 "$LOG_DIR/frontend.log" >&2 || true
    exit 1
  fi
  echo "[frontend] pid $(cat "$FRONTEND_PID_FILE") | 日志 $LOG_DIR/frontend.log"
  echo "[frontend] 工作台: http://${WEB_HOST}:${WEB_PORT}/super-agent"
}

start_foreground() {
  load_env
  ensure_python
  ensure_node
  ensure_frontend_build

  if port_in_use "$API_PORT"; then
    echo "[backend] 端口 $API_PORT 已被占用" >&2
    exit 1
  fi
  if port_in_use "$WEB_PORT"; then
    echo "[frontend] 端口 $WEB_PORT 已被占用" >&2
    exit 1
  fi

  cleanup() {
    echo
    echo "正在退出..."
    [[ -n "${BACKEND_PID:-}" ]] && kill "$BACKEND_PID" 2>/dev/null || true
    [[ -n "${FRONTEND_PID:-}" ]] && kill "$FRONTEND_PID" 2>/dev/null || true
    wait 2>/dev/null || true
  }
  trap cleanup INT TERM EXIT

  echo "========================================"
  echo " Data Agent 生产环境（前台）"
  echo " Backend : http://${API_HOST}:${API_PORT}/docs"
  echo " Frontend: http://${WEB_HOST}:${WEB_PORT}/super-agent"
  echo " Ctrl+C 停止"
  echo "========================================"

  (
    cd "$ROOT"
    export MINERU_LOCAL_ENABLED
    python -m uvicorn data_agent.main:app --host "$API_HOST" --port "$API_PORT"
  ) &
  BACKEND_PID=$!

  (
    run_frontend_server
  ) &
  FRONTEND_PID=$!

  wait -n "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || wait
}

start_detached() {
  load_env
  start_backend
  start_frontend
  echo
  echo "前后端已在后台运行。停止: ./scripts/prod.sh -k"
  echo "日志目录: $LOG_DIR"
}

MODE="detached"
CMD=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    -d|--detach|--detached)
      MODE="detached"
      shift
      ;;
    -f|--foreground|--fg)
      MODE="foreground"
      shift
      ;;
    -k|--kill)
      stop_all
      exit 0
      ;;
    start)
      CMD="start"
      shift
      ;;
    stop)
      stop_all
      exit 0
      ;;
    restart|status|backend|frontend|build)
      CMD="$1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "未知参数: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

CMD="${CMD:-start}"

case "$CMD" in
  start)
    if [[ "$MODE" == "foreground" ]]; then
      start_foreground
    else
      start_detached
    fi
    ;;
  backend)
    load_env
    start_backend
    ;;
  frontend)
    load_env
    start_frontend
    ;;
  build)
    load_env
    build_frontend
    ;;
  restart)
    stop_all
    start_detached
    ;;
  status)
    load_env
    if is_running "$BACKEND_PID_FILE"; then
      echo "[backend] running pid $(cat "$BACKEND_PID_FILE") -> http://${API_HOST}:${API_PORT}"
    else
      echo "[backend] stopped"
    fi
    if is_running "$FRONTEND_PID_FILE"; then
      echo "[frontend] running pid $(cat "$FRONTEND_PID_FILE") -> http://${WEB_HOST}:${WEB_PORT}"
    else
      echo "[frontend] stopped"
    fi
    echo "日志: $LOG_DIR/backend.log, $LOG_DIR/frontend.log"
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
