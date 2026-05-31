#!/usr/bin/env bash
# 本地开发：一键启动 / 停止 data-agent 后端 + Next.js 前端
#
# 用法:
#   ./scripts/dev.sh          # 默认后台启动前后端（同 -d）
#   ./scripts/dev.sh -d       # 显式后台启动
#   ./scripts/dev.sh -f       # 前台启动（Ctrl+C 同时退出）
#   ./scripts/dev.sh -k       # 停止前后端
#   ./scripts/dev.sh stop     # 同 -k
#   ./scripts/dev.sh backend  # 仅后台后端
#   ./scripts/dev.sh frontend # 仅前台/后台前端
#   ./scripts/dev.sh status   # 查看状态
#
# 环境变量（可选）:
#   API_HOST=127.0.0.1   API_PORT=8081   WEB_PORT=3000
#   MINERU_LOCAL_ENABLED=0  # 默认关闭 MinerU 探活，加快启动
#   BACKEND_RELOAD=1        # 后台后端启用 uvicorn 热重载（默认关闭，避免日志/缓存触发重载循环）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$ROOT/.dev/pids"
LOG_DIR="$ROOT/.dev/logs"

API_HOST="${API_HOST:-127.0.0.1}"
API_PORT="${API_PORT:-8081}"
WEB_HOST="${WEB_HOST:-0.0.0.0}"
WEB_PORT="${WEB_PORT:-3000}"
API_ORIGIN="${DATA_AGENT_API_ORIGIN:-http://${API_HOST}:${API_PORT}}"

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
  $0 status       查看运行状态
  $0 backend      仅后台启动后端
  $0 frontend     仅后台启动前端
  $0 restart      重启（后台）

日志: $LOG_DIR/backend.log, $LOG_DIR/frontend.log, $LOG_DIR/agno.log
EOF
}

load_env() {
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
    if [[ "$cmd" == *"npm run dev"* || "$cmd" == *"bun run dev"* || "$cmd" == *"next dev"* || "$cmd" == *"uvicorn data_agent.main:app"* ]]; then
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

stop_untracked_dev() {
  local pid cmd
  if ! command -v pgrep >/dev/null 2>&1; then
    return 0
  fi

  while IFS= read -r pid; do
    [[ -z "$pid" || ! "$pid" =~ ^[0-9]+$ ]] && continue
    cmd="$(ps -o cmd= -p "$pid" 2>/dev/null || true)"
    [[ -z "$cmd" ]] && continue

    if [[ "$cmd" == *"$ROOT/web"* && "$cmd" == *"next dev"* ]] \
      && [[ "$cmd" == *" -p $WEB_PORT"* || "$cmd" == *" -p$WEB_PORT"* ]]; then
      echo "[frontend] 停止未跟踪的前端进程 $pid"
      kill_pid_tree "$pid"
      continue
    fi

    if [[ "$cmd" == *"npm run dev"* || "$cmd" == *"bun run dev"* ]] \
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
  done < <(pgrep -f "next dev|npm run dev|bun run dev|uvicorn data_agent.main:app" 2>/dev/null || true)
}

verify_stopped() {
  local failed=0
  if port_in_use "$API_PORT"; then
    echo "[backend] 警告: 端口 $API_PORT 仍被占用" >&2
    if command -v ss >/dev/null 2>&1; then
      ss -tlnp "sport = :$API_PORT" 2>/dev/null >&2 || true
    fi
    failed=1
  fi
  if port_in_use "$WEB_PORT"; then
    echo "[frontend] 警告: 端口 $WEB_PORT 仍被占用" >&2
    if command -v ss >/dev/null 2>&1; then
      ss -tlnp "sport = :$WEB_PORT" 2>/dev/null >&2 || true
    fi
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
  # 清理 pid 文件未跟踪的孤儿进程（如手动 npm run dev、子进程残留）
  stop_port "backend" "$API_PORT"
  stop_port "frontend" "$WEB_PORT"
  stop_untracked_dev
  stop_port "backend" "$API_PORT"
  stop_port "frontend" "$WEB_PORT"
  sleep 0.5
  if ! verify_stopped; then
    echo "正在重试清理残留进程..." >&2
    stop_untracked_dev
    stop_port "backend" "$API_PORT"
    stop_port "frontend" "$WEB_PORT"
    sleep 0.5
    verify_stopped || true
  fi
  echo "已停止所有 dev 进程"
}

ensure_python() {
  if ! command -v python3 >/dev/null 2>&1; then
    echo "错误: 未找到 python3" >&2
    exit 1
  fi
  if ! python3 -c "import uvicorn" 2>/dev/null; then
    echo "错误: 缺少 uvicorn，请执行: pip install -e '.[dev]'" >&2
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

start_backend() {
  ensure_python
  if is_running "$BACKEND_PID_FILE"; then
    echo "[backend] 已在运行 (pid $(cat "$BACKEND_PID_FILE"))"
    return
  fi
  if port_in_use "$API_PORT"; then
    echo "[backend] 端口 $API_PORT 已被占用，请修改 API_PORT 或先执行 ./scripts/dev.sh -k" >&2
    exit 1
  fi

  echo "[backend] 启动 http://${API_HOST}:${API_PORT}"
  (
    cd "$ROOT"
    export MINERU_LOCAL_ENABLED
    backend_cmd=(python3 -m uvicorn data_agent.main:app --host "$API_HOST" --port "$API_PORT")
    if [[ "${BACKEND_RELOAD:-0}" == "1" ]]; then
      backend_cmd+=(--reload-dir "$ROOT/data_agent" --reload)
    fi
    exec "${backend_cmd[@]}" >>"$LOG_DIR/backend.log" 2>&1
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
  echo "[backend] Swagger: http://${API_HOST}:${API_PORT}/docs"
}

start_frontend() {
  ensure_node
  if is_running "$FRONTEND_PID_FILE"; then
    echo "[frontend] 已在运行 (pid $(cat "$FRONTEND_PID_FILE"))"
    return
  fi
  if port_in_use "$WEB_PORT"; then
    echo "[frontend] 端口 $WEB_PORT 已被占用，请修改 WEB_PORT 或先执行 ./scripts/dev.sh -k" >&2
    exit 1
  fi

  echo "[frontend] 启动 http://${WEB_HOST}:${WEB_PORT} (API -> $API_ORIGIN)"
  (
    cd "$ROOT/web"
    export DATA_AGENT_API_ORIGIN="$API_ORIGIN"
    exec bun run dev -- -H "$WEB_HOST" -p "$WEB_PORT"
  ) >>"$LOG_DIR/frontend.log" 2>&1 &
  echo $! >"$FRONTEND_PID_FILE"
  sleep 1.5
  if ! is_running "$FRONTEND_PID_FILE"; then
    echo "[frontend] 启动失败，查看 $LOG_DIR/frontend.log" >&2
    tail -20 "$LOG_DIR/frontend.log" >&2 || true
    exit 1
  fi
  echo "[frontend] pid $(cat "$FRONTEND_PID_FILE") | 日志 $LOG_DIR/frontend.log"
  echo "[frontend] Super Agent: http://${WEB_HOST}:${WEB_PORT}/super-agent"
}

start_foreground() {
  load_env
  ensure_python
  ensure_node

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
  echo " Data Agent 开发环境（前台）"
  echo " Backend : http://${API_HOST}:${API_PORT}/docs"
  echo " Frontend: http://${WEB_HOST}:${WEB_PORT}/super-agent"
  echo " Ctrl+C 停止"
  echo "========================================"

  (
    cd "$ROOT"
    export MINERU_LOCAL_ENABLED
    python3 -m uvicorn data_agent.main:app --host "$API_HOST" --port "$API_PORT"
  ) &
  BACKEND_PID=$!

  (
    cd "$ROOT/web"
    export DATA_AGENT_API_ORIGIN="$API_ORIGIN"
    bun run dev -- -H "$WEB_HOST" -p "$WEB_PORT"
  ) &
  FRONTEND_PID=$!

  wait -n "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || wait
}

start_detached() {
  load_env
  start_backend
  start_frontend
  echo
  echo "前后端已在后台运行。停止: ./scripts/dev.sh -k"
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
    restart|status|backend|frontend)
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
    echo "日志: $LOG_DIR/backend.log, $LOG_DIR/frontend.log, $LOG_DIR/agno.log"
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac
