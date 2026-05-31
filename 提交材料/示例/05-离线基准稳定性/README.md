# 示例 5：任务三 — GNC 审查离线基准门禁与系统稳定性评测

## 验证任务

**任务三：系统稳定性与综合能力评测** — 可重复基准、指标门禁、延迟 P95、降级率、过程日志持久化、压测骨架。

> 本示例**不以 ywdata 业务材料为主输入**；核心证据来自 `benchmark/` 合成/生成 fixture 与 `测试结果/` 真实运行摘要。任务一 **ywdata 实跑**见示例 [01](../01-多格式结构化/)、[02](../02-PDF验收解析/)、[03](../03-跨文档指代/)。

## 与任务一的关系（必读）

| 基准样例 | 任务归属 | 说明 |
| --- | --- | --- |
| `docx_parse`, `xlsx_parse`, `gnc_single_doc`, `gnc_multi_doc` | 任务三离线回归 | 运行时生成或合成 Markdown；**不等同** ywdata Word 实跑分数 |
| `html_parse`, `pptx_parse` | **仅任务三** | 运行时生成 + 合成 OCR 期望；**不属于任务一 ywdata 验证** |
| `image_degraded`, `pdf_degraded` | **仅任务三** | 允许降级通过；非真实拍照/极端 OCR 基准 |
| CMG50 PDF（示例 2 fixture） | 任务一可选对照 | ywdata 真源，**无基准逐字段对齐** |

## 离线基准样例一览（任务三）

| 样例类型 | case_id 示例 | 说明 |
| --- | --- | --- |
| 结构树 / 多文档（合成） | gnc_single_doc, gnc_multi_doc | GNC 示范审查对象 |
| Office 生成 | docx_parse, xlsx_parse | benchmark 内生成 |
| HTML/PPT（生成） | html_parse, pptx_parse | 轻量解析 + 合成 CER/WER 期望 |
| 降级探针 | image_degraded, pdf_degraded | 非真实极端样 |

## 材料来源与边界

| 类型 | 路径 | 标注 |
| --- | --- | --- |
| 基准清单 | `benchmark/golden_manifest.json` | 9 个样例，含合成/生成/inline |
| 合成 Markdown | `tests/fixtures/review_docs/*.md` | GNC 领域**示范审查对象**，非 ywdata |
| 运行时生成 | docx/xlsx/pptx/html/image 样例 | benchmark 内生成，非 ywdata |
| 真实运行摘要 | `提交材料/测试结果/基准运行摘要.json` | 2026-05-27 实跑 |
| 可选 PDF 对照 | 示例 2 的 CMG50 fixture | ywdata 真源，任务一演示用 |

## API / 工作流

### 主路径：离线基准 CLI

```bash
cd /path/to/data-agent
python3 benchmark/run_golden.py | tee 提交材料/测试结果/基准运行摘要.json
```

### 延迟与门禁字段（`基准运行摘要.json`）

| 指标 | 2026-05-27 实跑值 | 门禁 |
| --- | --- | --- |
| `pass_rate` | 1.0 | 9/9 |
| `average_structure_tree_f1` | 0.8889 | `min_average_structure_tree_f1 ≥ 0.5` ✅ |
| `p95_elapsed_ms` | 134 | `max_p95_elapsed_ms ≤ 120000` ✅ |
| `degradation_rate` | 0.2222 | pdf/image degraded 预期 |
| `gate_passed` | true | 汇总门禁 |

### 压测骨架（非 CI 必跑）

```bash
python3 benchmark/run_load_smoke.py --concurrency 4 --iterations 10
```

### 启动探针与 pytest

```bash
pytest tests/test_startup_checks.py tests/test_evaluation_metrics.py -q
# 完整摘要见 提交材料/测试结果/单元测试摘要.txt
```

### Trace 样例（脱敏）

- [任务执行跟踪样例.json](../../测试结果/任务执行跟踪样例.json)
- [解析降级跟踪样例.json](../../测试结果/解析降级跟踪样例.json)

## 可观测指标

| 指标 | 用途 |
| --- | --- |
| `structure_tree_f1` / `table_f1` | 解析能力**离线回归**（含合成样例） |
| `gate_passed` | 任务三总门禁 |
| `p95_elapsed_ms` | 延迟稳定性 |
| `degradation_rate` | parser 降级可接受性 |
| `execution_metrics_snapshot` | 三类入口字段口径一致的质量快照 |
| `schema_valid_count` | 输出 schema 一致性 |

## 能力边界

- **能演示**：可重复离线基准门禁、9 个样例全通过、延迟/过程日志/指标体系。
- **不能声称**：HTML/PPT/极端 OCR/工程图为任务一 ywdata 实跑验证；真实 OCR 生产基准；高负载 CI 压测；ywdata Word 与离线基准 F1 一一对应。
- **当前实现**：`load_smoke` 为骨架；OCR CER/WER 仅对合成 `html_parse`/`pptx_parse` 有效。

## 输出样例

[输出样例.json](./输出样例.json) — 摘自 `基准运行摘要.json` 汇总段。
