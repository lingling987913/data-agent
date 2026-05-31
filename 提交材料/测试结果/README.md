# 测试结果与实跑证据

本目录存放**评审可复现**的离线测试输出与脱敏 trace 样例。路径均以**仓库根**为当前工作目录。

## 与 评审材料 / 示例 的关系

| 目录 | 内容 | 用途 |
| --- | --- | --- |
| **[评审材料/](../评审材料/)** | 正式测试业务文档（月兔一号/蓬莱一号 Word + Excel） | **任务一/二**实跑输入真源 |
| **示例/*/测试数据/** | 英文短名 fixture（可由 评审材料 同步） | API curl、structuring、竞赛 task 演示 |
| **测试结果/**（本目录） | golden / pytest **输出** | **任务三**离线门禁与回归证据 |

- **任务一实跑**：先用 `bash 提交材料/示例/脚本/复制业务数据.sh` 从 评审材料 同步 测试数据，再按 [示例/](../示例/) 或 [部署与运行说明.md](../部署与运行说明.md) 跑 API。
- **任务三 golden**：依赖 `tests/fixtures/review_docs/*.md`（合成 Markdown），**不读取 评审材料 Word**；与 评审材料 互补、路径独立。

## 文件说明

| 文件 | 含义 |
| --- | --- |
| `基准运行摘要.json` | `python3 benchmark/run_golden.py --json-out …` 的完整 JSON 汇总 |
| `基准运行.log` | 同上命令的 stdout/stderr 原文 |
| `基准摘要.md` | 由 golden JSON 整理的可读摘要（门禁与失败 case） |
| `单元测试摘要.txt` | `python3 -m pytest -q` 输出；无 `tests/` 时可能仅含配置警告 |
| `任务执行跟踪样例.json` | 竞赛任务 / DAG 执行快照**脱敏结构样例**（对齐 `storage/runs/tasks/`、`traces/`） |
| `解析降级跟踪样例.json` | 解析器降级链**脱敏样例**（对齐 `parser_fallback_logs`） |

## 复现命令

```bash
cd /path/to/data-agent
pip install -e ".[dev]"   # 或 uv sync

# 可选：同步 评审材料 真实 测试数据（不影响 golden Markdown case）
bash 提交材料/示例/脚本/复制业务数据.sh

mkdir -p 提交材料/测试结果

python3 benchmark/run_golden.py \
  --json-out 提交材料/测试结果/基准运行摘要.json \
  2>&1 | tee 提交材料/测试结果/基准运行.log

python3 -m pytest -q \
  2>&1 | tee 提交材料/测试结果/单元测试摘要.txt
```

推荐子集（需检出 `tests/`）见 [部署与运行说明.md](../部署与运行说明.md) §4.1。

## 环境说明（2026-05-31 本机实跑）

- **golden**：9 case 中 6 通过；`gate_passed=false` 主要因 `tests/fixtures/review_docs/*.md` 未检出（`gnc_*`、`review_plus_three_slot` 等失败）。**与 评审材料 Word 材料无关**；合成 case（docx/html/pptx 等）可正常跑通。
- **pytest**：当前工作区 `testpaths` 下无测试文件时仅输出配置警告，不代表工程无测试。
- **trace 样例**：`storage/runs/` 无历史落盘时，使用本目录 `*跟踪样例.json` 说明字段结构；实跑后可用 `storage/runs/tasks/{task_id}.json` 替换。

更完整的日志与追溯字段映射见 [测试与日志说明.md](../测试与日志说明.md)。
