# 示例 1：任务一 — 多源多格式结构化（Word + Excel）

## 验证任务

**任务一：数据理解与结构化处理** — 多源识别、信息抽取、格式转换、元数据挂接、统一 bundle 输出。

> 本示例聚焦 GNC 送审材料在组委会「任务一」**Word + Excel** 路径上的可观测结构化能力，为设计要素识别与跨材料追溯提供底稿。

## 验证能力（ywdata 实跑）

| 能力 | 覆盖 | 说明 |
| --- | --- | --- |
| 多格式识别与 bundle | ✅ | 3× docx + 1× xlsx → 统一 `ReviewDocumentBundle` |
| 复杂表格（表格为主） | ✅ | 检查单表格、文档检查需求 xlsx |
| 密集数字/指标 | ⚠️ | 任务书/设计报告工程指标；需人工对照，非专项 anti-hallucination 集 |
| 规范/行业标准形态 | ⚠️ | 产品保证检查单、文档检查需求表 |
| 信息抽取与元数据 | ✅ | evidence_pool、章节树、规则抽取 MVP 字段 |

## 不在本次验证范围

HTML/PPT、极端 OCR、工程图/流程图独立解析 — 见 [业务数据映射表.md](../业务数据映射表.md) 与示例 5（任务三合成基准样例）。

## 测试数据

| 来源 | 命令 |
| --- | --- |
| 脱敏最小样例（默认） | 已包含于 `测试数据/`；重新生成：`python3 提交材料/示例/脚本/生成最小测试数据.py` |
| 真实 ywdata | `bash 提交材料/示例/脚本/复制业务数据.sh` |

## 材料（ywdata 真源）

| fixture | ywdata 源 | 格式 | 角色 |
| --- | --- | --- | --- |
| `月兔一号_产品保证检查单.docx` | `doc/q1/产品保证工作检查单（公开）.docx` | Word | 审查规则/检查单 |
| `月兔一号_飞轮研制任务书.docx` | `doc/q1/月兔一号飞行器飞轮研制任务书.docx` | Word | 研制任务书 |
| `月兔一号_飞轮设计分析报告.docx` | `doc/q1/月兔一号飞行器飞轮可靠性安全性设计与分析报告.docx` | Word | 设计分析报告 |
| `月兔一号_文档检查需求.xlsx` | `doc/q1/文档检查需求（公开）.xlsx` | Excel | 文档检查需求表 |

四文件为完整 q1 包；评审可仅跑任务书 + xlsx 子集以缩短时间。

## API / 工作流

**推荐路径（任务一直接观测）**：逐文件 Structuring API，或 Super Agent `route=structure`。

```bash
TOKEN=dev-token-change-me
BASE=http://127.0.0.1:8080
FIX=提交材料/示例/01-多格式结构化/测试数据

# Word 示例
curl -s -X POST "$BASE/api/v1/structuring/parse" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"file_path\":\"$FIX/月兔一号_飞轮研制任务书.docx\",\"file_name\":\"task_book.docx\",\"parser_type\":\"auto\"}"

# Excel 示例
curl -s -X POST "$BASE/api/v1/structuring/parse" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"file_path\":\"$FIX/月兔一号_文档检查需求.xlsx\",\"file_name\":\"requirements.xlsx\",\"parser_type\":\"auto\"}"
```

**离线基准对照（合成 fixture，任务三回归，非本示例 ywdata 主路径）**：

```bash
python3 benchmark/run_golden.py  # case: xlsx_parse, docx_parse（合成生成）
```

## 可观测指标

| 指标 | 来源 | 门禁/期望 |
| --- | --- | --- |
| `structure_tree_f1` | API 返回 / 合成 docx 基准 | `min_structure_tree_f1`（合成） |
| `table_f1` | xlsx 基准样例 | `min_table_f1=1.0`（合成） |
| `evidence_count` / `extracted_parameter_count` | bundle stats | 实跑可记录 |
| `parser_trace_summary` | 解析 trace | 记录 parser 选择与降级 |

## 能力边界

- **能演示**：Word/Excel 多格式解析、bundle 字段、表格行抽取、章节树、行业表单结构。
- **不能由本示例单独证明**：跨文档指代（见示例 3）、PDF 跨页（见示例 2）、HTML/PPT、极端 OCR、工程图解析。

## 输出样例

[输出样例.json](./输出样例.json)（`_example: true`）
