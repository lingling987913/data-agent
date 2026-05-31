# 示例 2：任务一 — GNC 验收 PDF 解析与降级链

## 验证任务

**任务一：数据理解与结构化处理** — **常规** PDF 版面解析、多级 parser 降级、验收确认类材料抽取。

> 材料为 CMG50 **常规扫描/电子版** PDF，覆盖任务一 PDF 路径；**不**承担极端 OCR 或工程图专项评测。

## 验证能力（ywdata 实跑）

| 能力 | 覆盖 | 说明 |
| --- | --- | --- |
| 常规 PDF 解析与降级链 | ✅ | MinerU 本地 → 在线 → `pdftotext` |
| 跨页段落/表格合并 | ⚠️ | 18 页验收 PDF |
| 复杂表格（表格为主） | ⚠️ | 验收数据页与表格 |
| 密集数字/指标 | ⚠️ | 测试数据与指标；需人工对照 |
| 规范/行业标准形态 | ✅ | 航天零组件验收报告惯例 |

## 不在本次验证范围

极端 OCR（模糊拍照、光线不均、手写、签章重叠）、工程图/流程图独立解析、HTML/PPT — 见 [业务数据映射表.md](../业务数据映射表.md)。

## 测试数据

脱敏 PDF 见 `测试数据/CMG50_验收报告.pdf`；真实 CMG50 见 `复制业务数据.sh`（需 `ywdata/pdf/`）。

## 材料（ywdata 真源）

| 项 | 值 |
| --- | --- |
| fixture | `测试数据/CMG50_验收报告.pdf` |
| ywdata 源 | `pdf/CMG50验收报告20231018（公开）.pdf`（~614 KB，18 页） |

备选（未纳入提交包）：`4122Y016(H)004验收报告`、`20-82C` 验收报告；`J180YTSF`（~14 MB 过大）。

## API / 工作流

```bash
TOKEN=dev-token-change-me
BASE=http://127.0.0.1:8080
PDF=提交材料/示例/02-PDF验收解析/测试数据/CMG50_验收报告.pdf

curl -s -X POST "$BASE/api/v1/structuring/parse" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{
    \"file_path\": \"$PDF\",
    \"file_name\": \"CMG50_验收报告.pdf\",
    \"processing_mode\": \"OPTIMAL\",
    \"parser_type\": \"auto\"
  }"
```

PDF parser 降级链：MinerU 本地 → MinerU 在线 → `pdftotext`。

## 可观测指标

| 指标 | 来源 | 说明 |
| --- | --- | --- |
| `parser_trace_summary` | API 返回 | 记录实际降级路径 |
| `structure_tree_f1` | 离线基准 `pdf_degraded`（任务三） | 伪 PDF 样例，允许降级通过 |
| `degraded` / `degradation_rate` | 离线基准汇总（任务三） | 无 MinerU 时预期降级 |
| `evidence_count` | bundle stats | 验收指标抽取数量 |

## 能力边界

- **能演示**：常规 PDF 多级降级、章节/证据抽取、跨页材料、trace 可复现。
- **不能由 ywdata 证明**：极端 OCR；独立工程图还原；离线基准中的 `html_parse`/`pptx_parse`/`image_degraded` 为**任务三合成样例**，不属于本示例。

## 输出样例

[输出样例.json](./输出样例.json)
