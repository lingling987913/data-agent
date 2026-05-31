#!/usr/bin/env bash
# 从 ywdata/ 或 提交材料/评审材料/ 复制至 示例 01–04 的 测试数据/
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
YWDATA="${YWDATA:-$REPO_ROOT/ywdata}"
TOREVIEW="${TOREVIEW:-$REPO_ROOT/提交材料/评审材料}"
EXAMPLES="$REPO_ROOT/提交材料/示例"

SOURCE_Q1=""
SOURCE_LABEL=""

if [[ -d "$YWDATA/doc/q1" ]]; then
  SOURCE_Q1="$YWDATA/doc/q1"
  SOURCE_LABEL="ywdata/doc/q1"
elif [[ -d "$TOREVIEW/月兔一号" ]]; then
  SOURCE_Q1="$TOREVIEW/月兔一号"
  SOURCE_LABEL="提交材料/评审材料/月兔一号"
else
  echo "错误: 未找到 测试数据 来源" >&2
  echo "  - 仓库根 ywdata/doc/q1，或" >&2
  echo "  - 提交材料/评审材料/月兔一号（比赛提交包测试材料）" >&2
  echo "无上述目录时可运行: python3 提交材料/示例/脚本/生成最小测试数据.py" >&2
  exit 1
fi

echo "测试数据 来源: $SOURCE_LABEL"

copy_q1() {
  local dest="$1"
  mkdir -p "$dest"
  cp -f "$SOURCE_Q1/产品保证工作检查单（公开）.docx" "$dest/月兔一号_产品保证检查单.docx"
  cp -f "$SOURCE_Q1/月兔一号飞行器飞轮研制任务书.docx" "$dest/月兔一号_飞轮研制任务书.docx"
  cp -f "$SOURCE_Q1/月兔一号飞行器飞轮可靠性安全性设计与分析报告.docx" "$dest/月兔一号_飞轮设计分析报告.docx"
  cp -f "$SOURCE_Q1/文档检查需求（公开）.xlsx" "$dest/月兔一号_文档检查需求.xlsx"
  echo "  q1 四件套 -> $dest"
}

copy_pdf() {
  local dest="$1"
  mkdir -p "$dest"
  local src="$YWDATA/pdf/CMG50验收报告20231018（公开）.pdf"
  if [[ ! -f "$src" ]]; then
    echo "警告: 未找到 $src，跳过 PDF（示例 02 仍使用现有 测试数据）" >&2
    return 1
  fi
  cp -f "$src" "$dest/CMG50_验收报告.pdf"
  echo "  CMG50 PDF -> $dest"
}

copy_q1 "$EXAMPLES/01-多格式结构化/测试数据"
copy_q1 "$EXAMPLES/04-规划与编排/测试数据"
mkdir -p "$EXAMPLES/03-跨文档指代/测试数据"
cp -f "$EXAMPLES/01-多格式结构化/测试数据/月兔一号_飞轮研制任务书.docx" \
  "$EXAMPLES/03-跨文档指代/测试数据/"
cp -f "$EXAMPLES/01-多格式结构化/测试数据/月兔一号_飞轮设计分析报告.docx" \
  "$EXAMPLES/03-跨文档指代/测试数据/"
if [[ -d "$YWDATA/pdf" ]]; then
  copy_pdf "$EXAMPLES/02-PDF验收解析/测试数据" || true
fi

echo "完成。映射说明见 提交材料/示例/业务数据映射表.md；测试材料入口见 提交材料/评审材料/"
