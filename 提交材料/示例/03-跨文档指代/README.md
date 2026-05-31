# 示例 3：任务一 — GNC 跨文档合并与追溯候选（全局指代）

## 验证任务

**任务一：数据理解与结构化处理** — 多文档 bundle 合并、需求—设计跨材料指代、追溯候选生成。

## 验证能力（ywdata 实跑）

| 能力 | 覆盖 | 说明 |
| --- | --- | --- |
| 跨文档合并与 bundle | ✅ | 双 docx → 单一 bundle |
| 全局指代 / 追溯候选 | ✅ 核心 | 任务书指标 ↔ 设计报告响应 |
| 密集数字/指标印证 | ⚠️ | 依赖正文编号体系 |
| 规范/行业标准形态 | ⚠️ | 研制任务书—设计报告链路 |

## 不在本次验证范围

工程图/流程图、极端 OCR（本示例为 Word）、HTML/PPT — 见 [业务数据映射表.md](../业务数据映射表.md)。

## 测试数据

双 docx 见 `测试数据/`；生成/复制方式同 [示例 01](../01-多格式结构化/README.md#测试数据)。

## 材料（ywdata 真源）

| fixture | ywdata 源 | 角色 |
| --- | --- | --- |
| `月兔一号_飞轮研制任务书.docx` | `doc/q1/月兔一号飞行器飞轮研制任务书.docx` | 需求/指标 |
| `月兔一号_飞轮设计分析报告.docx` | `doc/q1/...可靠性安全性设计与分析报告.docx` | 设计方案 |

**扩展（未默认启用）**：`doc/q2/` 蓬莱一号同结构文档可做跨型号对比。

## API / 工作流

```bash
TOKEN=dev-token-change-me
BASE=http://127.0.0.1:8080
DIR=提交材料/示例/03-跨文档指代/测试数据

RUN=$(curl -s -X POST "$BASE/api/v1/super-agent/runs" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "任务一-跨文档追溯候选",
    "objective": "解析任务书与设计报告并建立追溯候选",
    "requested_route": "structure",
    "processing_mode": "OPTIMAL",
    "execute": false
  }' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['run_id'])")

curl -s -X POST "$BASE/api/v1/super-agent/runs/$RUN/execute" \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@$DIR/月兔一号_飞轮研制任务书.docx" \
  -F "files=@$DIR/月兔一号_飞轮设计分析报告.docx" \
  -F "parser_type=auto"
```

**离线基准（合成 Markdown，任务三回归，非 ywdata Word）**：

```bash
python3 benchmark/run_golden.py  # case: gnc_multi_doc, min_trace_links ≥ 1
```

## 可观测指标

| 指标 | 来源 | 门禁 |
| --- | --- | --- |
| `trace_link_candidate_count` | bundle / 基准统计 | `min_trace_links ≥ 1`（合成） |
| `structure_tree_f1` | 离线基准 `gnc_multi_doc` | 合成 MD 门禁 |
| `document_count` | bundle | = 2 |
| HITL 确认 API | Review-Plus traceability | 真源 Word 链接数可能低于合成基准 |

## 能力边界

- **能演示**：双 docx 合并、`trace_link_candidates` 生成、跨文档 bundle。
- **与离线基准差异**：基准样例使用 GNC 合成 Markdown + 固定编号；ywdata Word 追溯数量依赖正文编号体系，**不与基准 F1 直接等同**。

## 输出样例

[输出样例.json](./输出样例.json)
