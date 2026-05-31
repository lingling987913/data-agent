# 示例 4：任务二 — 复杂任务规划与多步编排

## 验证任务

**任务二：复杂任务规划与自动执行** — 目标拆解、DAG 规划、工具路由、多步工作流、批处理入口、异常降级。

本示例展示面向航天器 GNC 分系统设计要素智能审查的数据智能体在**任务二**上的规划与编排能力，覆盖竞赛任务接口、Review-Plus 11 步流程与超级智能体降级三条路径。

## 数据处理难点覆盖

本示例侧重**编排与执行**，非单点解析；解析难点由示例 1–3 承担。

## 测试数据

四件套 + 场景 C 单 docx 见 `测试数据/`；`复制业务数据.sh` 或 `生成最小测试数据.py`。

## 材料（ywdata 真源）

| 场景 | 测试数据 | ywdata 源 |
| --- | --- | --- |
| A/B 四文件包 | 3 docx + 1 xlsx | `doc/q1/` 四件套 |
| C 不完整包 | 单 `月兔一号_飞轮设计分析报告.docx` | 同 q1 设计报告 |

## 场景 A：Planning DAG（CorePlanner → DAGExecutor）

```bash
TOKEN=dev-token-change-me
BASE=http://127.0.0.1:8080
FIX=提交材料/示例/04-规划与编排/测试数据

# 1. 生成计划 DAG
PLAN=$(curl -s -X POST "$BASE/api/v1/planning/plan" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"instruction":"对飞轮文档包进行结构化解析与质量评测"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['plan_id'])")

# 2. 执行（可附带 materials 元数据）
curl -s -X POST "$BASE/api/v1/planning/execute/$PLAN" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"metadata\":{\"materials\":[{\"path\":\"$FIX/月兔一号_飞轮研制任务书.docx\"}]}}"

# 3. 状态与 trace
curl -s "$BASE/api/v1/planning/status/$PLAN" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/api/v1/planning/trace/$PLAN" -H "Authorization: Bearer $TOKEN"

# 4. checkpoint 续跑（MVP）
# curl -s -X POST "$BASE/api/v1/planning/resume/$PLAN" -H "Authorization: Bearer $TOKEN"
```

## 场景 B：竞赛任务接口批处理 + Review-Plus 委托

≥4 文件自动走 Review-Plus 路径（任务二批处理入口）：

```bash
FIX=提交材料/示例/04-规划与编排/测试数据

TASK=$(curl -s -X POST "$BASE/api/v1/task/submit" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"task_description\":\"飞轮文档包审查\",\"documents\":[
    {\"file_name\":\"月兔一号_产品保证检查单.docx\",\"content_type\":\"path\",\"content\":\"$FIX/月兔一号_产品保证检查单.docx\"},
    {\"file_name\":\"月兔一号_飞轮研制任务书.docx\",\"content_type\":\"path\",\"content\":\"$FIX/月兔一号_飞轮研制任务书.docx\"},
    {\"file_name\":\"月兔一号_飞轮设计分析报告.docx\",\"content_type\":\"path\",\"content\":\"$FIX/月兔一号_飞轮设计分析报告.docx\"},
    {\"file_name\":\"月兔一号_文档检查需求.xlsx\",\"content_type\":\"path\",\"content\":\"$FIX/月兔一号_文档检查需求.xlsx\"}
  ]}" | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['task_id'])")

curl -s "$BASE/api/v1/task/status/$TASK" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/api/v1/task/result/$TASK" -H "Authorization: Bearer $TOKEN"
```

Review-Plus 逐步接口（槽位检查 → 11 步流程 → 追溯矩阵）：

```bash
RID=$(curl -s -X POST "$BASE/api/v1/review-plus/reviews" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"任务二-Review-Plus十一步"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['review_plus_id'])")

curl -s -X POST "$BASE/api/v1/review-plus/reviews/$RID/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "files=@$FIX/月兔一号_产品保证检查单.docx" \
  -F "files=@$FIX/月兔一号_飞轮研制任务书.docx" \
  -F "files=@$FIX/月兔一号_飞轮设计分析报告.docx" \
  -F "files=@$FIX/月兔一号_文档检查需求.xlsx" \
  -F "parser_type=auto"

curl -s "$BASE/api/v1/review-plus/reviews/$RID/gatekeeping" -H "Authorization: Bearer $TOKEN"
curl -s -X POST "$BASE/api/v1/review-plus/reviews/$RID/start" -H "Authorization: Bearer $TOKEN"
curl -s "$BASE/api/v1/review-plus/reviews/$RID/traceability" -H "Authorization: Bearer $TOKEN"
```

## 场景 C：超级智能体不完整包降级（异常处理）

```bash
DOCX=提交材料/示例/04-规划与编排/测试数据/月兔一号_飞轮设计分析报告.docx

RUN=$(curl -s -X POST "$BASE/api/v1/super-agent/runs" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"任务二-不完整包降级","objective":"材料槽位不齐时智能路由","requested_route":"smart","execute":false}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['data']['run_id'])")

curl -s -X POST "$BASE/api/v1/super-agent/runs/$RUN/execute" \
  -H "Authorization: Bearer $TOKEN" -F "files=@$DOCX" -F "parser_type=auto"
```

预期：`run_review_plus` **跳过**（槽位不齐）；`run_gnc_review` 无 adapter 时跳过并记录。

## 可观测指标

| 指标 | 场景 | 说明 |
| --- | --- | --- |
| DAG `visualization.nodes` | A | 规划节点数（测试基线 6 节点） |
| `planning/trace` step 状态 | A | 每步耗时、成功/失败 |
| `task` status 迁移 | B | pending → running → completed |
| gatekeeping 槽位结果 | B | 四槽位是否齐 |
| Review-Plus 11 步 progress | B | 工作流逐步状态 |
| `execution_graph` skip | C | 不完整包降级谓词 |
| `execution_metrics_snapshot` | B/C | 执行指标快照 |

## 能力边界

| 声称 | 实际 |
| --- | --- |
| Planning + Task 统一入口 | ❌ 仍双轨（报告 §5.3.8 已标注） |
| 通用 cron/目录批处理 | ❌ 未建设 |
| GNC 十步独立 API | ✅ 代码已挂载 `/api/v1/gnc-review/*`；本示例主线仍以规划接口 / 任务接口 / Review-Plus / 超级智能体编排为主 |
| checkpoint 生产级续跑 | ⚠️ MVP（`POST /planning/resume`） |
| Review-Plus Agent 全步 | ⚠️ 无 LLM 时部分步骤降级 |

## 输出样例

[输出样例.json](./输出样例.json)
