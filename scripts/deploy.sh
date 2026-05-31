#!/usr/bin/env bash
# 新人上手：依赖安装 + 环境文件初始化 + 前后端一体化启动
#
# 用法:
#   ./scripts/deploy.sh              # 首次安装依赖并生产模式启动（后端 8080 + 前端 3000）
#   ./scripts/deploy.sh --dev        # 开发模式（后端 8081 + 前端 dev server）
#   ./scripts/deploy.sh --setup-only # 只安装依赖、复制 .env，不启动服务
#   ./scripts/deploy.sh --check      # 检查必配项是否仍为占位符
#   ./scripts/deploy.sh -k           # 停止当前模式对应进程（prod 或 dev）
#   ./scripts/deploy.sh status       # 查看运行状态
#
# 配置说明见: docs/部署与配置说明.md

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CONFIG_DOC="$ROOT/docs/部署与配置说明.md"

MODE="prod"
SETUP_ONLY=0
CHECK_ONLY=0
STOP=0
STATUS=0
EXTRA_ARGS=()

usage() {
  cat <<EOF
用法:
  $0                 安装依赖 + 生产模式启动前后端
  $0 --dev           安装依赖 + 开发模式启动
  $0 --setup-only    仅安装依赖并生成 .env / web/.env.local（不启动）
  $0 --check         检查关键配置是否仍为示例占位符
  $0 -k              停止服务（与上次 --dev 无关，同时尝试 prod/dev）
  $0 status          查看 prod / dev 脚本状态

详细配置项: docs/部署与配置说明.md
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev)
      MODE="dev"
      shift
      ;;
    --setup-only)
      SETUP_ONLY=1
      shift
      ;;
    --check)
      CHECK_ONLY=1
      shift
      ;;
    -k|--kill|stop)
      STOP=1
      shift
      ;;
    status)
      STATUS=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

require_cmd() {
  local name="$1"
  local hint="$2"
  if ! command -v "$name" >/dev/null 2>&1; then
    echo "错误: 未找到 $name。$hint" >&2
    exit 1
  fi
}

ensure_env_files() {
  if [[ ! -f "$ROOT/.env" ]]; then
    cp "$ROOT/.env.example" "$ROOT/.env"
    echo "[setup] 已创建 .env（请编辑 LLM_API_KEY 等，见 ${CONFIG_DOC}）"
  else
    echo "[setup] 已存在 .env，跳过复制"
  fi

  if [[ ! -f "$ROOT/web/.env.local" ]]; then
    cp "$ROOT/web/.env.example" "$ROOT/web/.env.local"
    echo "[setup] 已创建 web/.env.local"
  else
    echo "[setup] 已存在 web/.env.local，跳过复制"
  fi
}

sync_backend() {
  require_cmd uv "安装: https://docs.astral.sh/uv/"
  echo "[setup] 安装 Python 依赖 (uv sync --extra dev)..."
  (cd "$ROOT" && uv sync --extra dev)
}

sync_frontend() {
  require_cmd bun "安装: https://bun.sh"
  echo "[setup] 安装前端依赖 (bun install)..."
  (cd "$ROOT/web" && bun install)
}

print_post_setup_hint() {
  echo
  echo "========================================"
  echo " 下一步：编辑配置后启动"
  echo "========================================"
  echo "  1. 编辑仓库根目录 .env（必看: API_TOKEN、LLM_*）"
  echo "  2. 确认 web/.env.local 中 NEXT_PUBLIC_API_TOKEN 与 API_TOKEN 一致"
  echo "  3. 需要 PDF 高精度解析时配置 MinerU（见文档 §3）"
  echo "  4. 配置检查: ./scripts/deploy.sh --check"
  echo "  5. 启动:"
  echo "       生产: ./scripts/deploy.sh"
  echo "       开发: ./scripts/deploy.sh --dev"
  echo
  echo "  完整说明: docs/部署与配置说明.md"
  echo "========================================"
}

check_config() {
  local issues=0
  echo "[check] 配置检查（占位符 / 一致性）"
  echo

  if [[ ! -f "$ROOT/.env" ]]; then
    echo "  ✗ 缺少 .env，请执行: ./scripts/deploy.sh --setup-only" >&2
    issues=$((issues + 1))
  else
    # shellcheck disable=SC1091
    source "$ROOT/.env" 2>/dev/null || true

    if [[ "${API_TOKEN:-}" == "dev-token-change-me" ]]; then
      echo "  ⚠ API_TOKEN 仍为默认值（内网开发可接受；公网部署必须修改）"
    else
      echo "  ✓ API_TOKEN 已自定义"
    fi

    if [[ "${LLM_API_KEY:-}" == "" || "${LLM_API_KEY:-}" == *"your-"* ]]; then
      echo "  ⚠ LLM_API_KEY 未配置或为占位符 — Review/Super-Agent/编排等 LLM 步骤将降级"
      issues=$((issues + 1))
    else
      echo "  ✓ LLM_API_KEY 已设置"
    fi

    if [[ "${VLM_API_KEY:-}" == "" || "${VLM_API_KEY:-}" == *"your-"* ]]; then
      echo "  ⚠ VLM_API_KEY 未配置 — 图块/嵌入图描述不可用"
    else
      echo "  ✓ VLM_API_KEY 已设置"
    fi

    if [[ "${MINERU_LOCAL_ENABLED:-0}" == "1" ]]; then
      local base="${MINERU_LOCAL_API_BASE:-http://localhost:8000}"
      if curl -sf --max-time 3 "${base%/}/health" >/dev/null 2>&1 \
        || curl -sf --max-time 3 "${base%/}/docs" >/dev/null 2>&1; then
        echo "  ✓ MinerU 本地服务可达 ($base)"
      else
        echo "  ⚠ MINERU_LOCAL_ENABLED=1 但无法访问 $base（将降级在线/pdftotext）"
      fi
    else
      echo "  · MinerU 本地未启用 (MINERU_LOCAL_ENABLED≠1)"
    fi
  fi

  if [[ -f "$ROOT/web/.env.local" ]]; then
    local web_token
    web_token="$(grep -E '^NEXT_PUBLIC_API_TOKEN=' "$ROOT/web/.env.local" 2>/dev/null | cut -d= -f2- | tr -d '"' || true)"
    local api_token="${API_TOKEN:-}"
    if [[ -n "$web_token" && -n "$api_token" && "$web_token" != "$api_token" ]]; then
      echo "  ✗ 前后端 Token 不一致: API_TOKEN ≠ NEXT_PUBLIC_API_TOKEN" >&2
      issues=$((issues + 1))
    elif [[ -n "$web_token" && -n "$api_token" ]]; then
      echo "  ✓ 前后端 API Token 一致"
    fi
  else
    echo "  ⚠ 缺少 web/.env.local，请执行 --setup-only"
    issues=$((issues + 1))
  fi

  echo
  if [[ "$issues" -gt 0 ]]; then
    echo "[check] 发现 ${issues} 项需处理（详见 ${CONFIG_DOC}）"
    return 1
  fi
  echo "[check] 核心项通过（LLM 未配时部分能力仍受限，见文档「可选配置」）"
  return 0
}

run_setup() {
  require_cmd python3 "需要 Python ≥ 3.10"
  ensure_env_files
  sync_backend
  sync_frontend
}

if [[ "$STOP" -eq 1 ]]; then
  "$ROOT/scripts/prod.sh" -k 2>/dev/null || true
  "$ROOT/scripts/dev.sh" -k 2>/dev/null || true
  exit 0
fi

if [[ "$STATUS" -eq 1 ]]; then
  echo "--- prod ---"
  "$ROOT/scripts/prod.sh" status 2>/dev/null || echo "(未运行)"
  echo "--- dev ---"
  "$ROOT/scripts/dev.sh" status 2>/dev/null || echo "(未运行)"
  exit 0
fi

if [[ "$CHECK_ONLY" -eq 1 ]]; then
  check_config
  exit $?
fi

echo "========================================"
echo " Data Agent 一体化部署"
echo "========================================"

run_setup

if [[ "$SETUP_ONLY" -eq 1 ]]; then
  print_post_setup_hint
  check_config || true
  exit 0
fi

check_config || echo "[hint] 可先 ./scripts/deploy.sh --check，再编辑 .env 后 restart" >&2

if [[ "$MODE" == "dev" ]]; then
  echo
  echo "[deploy] 开发模式: 后端 8081 + 前端 3000"
  exec "$ROOT/scripts/dev.sh" "${EXTRA_ARGS[@]}"
else
  echo
  echo "[deploy] 生产模式: 后端 8080 + 前端 3000 (Next.js standalone)"
  exec "$ROOT/scripts/prod.sh" "${EXTRA_ARGS[@]}"
fi
