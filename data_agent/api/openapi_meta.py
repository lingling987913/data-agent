"""OpenAPI 分组与全局文档元数据。"""

from __future__ import annotations

OPENAPI_TAGS: list[dict[str, str]] = [
    {
        "name": "system",
        "description": (
            "服务健康与依赖连通性。"
            " `GET /health` 返回 MinerU 本地服务状态，无需认证。"
        ),
    },
    {
        "name": "competition-task",
        "description": (
            "**竞赛 API（一键式）**：提交文档后后台异步执行解析与 Review-Plus 审查，"
            "通过 `task_id` 轮询状态并获取结构化结果。"
            " 适合批量集成与自动化评测。"
        ),
    },
    {
        "name": "review-plus-lifecycle",
        "description": (
            "Review-Plus **任务生命周期**：创建、分页列表、详情、删除。"
            " 任务持久化于 `storage/runs/review_plus_tasks/`。"
        ),
    },
    {
        "name": "review-plus-materials",
        "description": (
            "**材料管理**：multipart 上传、指定解析器重解析、"
            "自动/手动角色分类、人工修正材料角色与版本基线。"
        ),
    },
    {
        "name": "review-plus-gatekeeping",
        "description": (
            "**送审包门禁**：检查四槽位齐套（规则表、检查单、任务书、专题报告）"
            " 与解析状态，返回 `blocked` / `limited` / `passed`。"
        ),
    },
    {
        "name": "review-plus-execution",
        "description": (
            "**审查执行**：`start` 启动十步 workflow（后台），"
            " `continue` 补偿续跑，`restart` 清空派生结果后重跑。"
            " 十步：分类→场景→结构化→总师组会→规则抽取→映射→Harness 审查→追溯→跨文档→报告。"
        ),
    },
    {
        "name": "review-plus-results",
        "description": (
            "**审查结果**：检查项、findings、章节映射、Harness 覆盖矩阵、"
            "结构化报告 JSON 与 Markdown 报告、Agent 运行轨迹、事件流。"
        ),
    },
    {
        "name": "gnc-review",
        "description": (
            "**GNC 设计评审**：提供单文档/多文档 GNC 设计要素知识型审查任务创建、启动、"
            "状态查询、结果获取与事件流接口；Super Agent 可按 `single_doc` / `multi_doc` "
            "模式委托该专项 workflow。"
        ),
    },
    {
        "name": "structuring",
        "description": (
            "**文档结构化自愈**：FormatDetector 检测 HTML/LaTeX 损坏；"
            " RepairAgent / AnaphoraResolver 按 `HIGH_ACCURACY` | `HIGH_SPEED` | `OPTIMAL` 三态策略调用 LLM。"
            " `POST /heal-blocks` 可对已有 blocks 调试；`GET /modes` 查看模式说明。"
        ),
    },
    {
        "name": "planning",
        "description": (
            "**任务规划与 DAG 执行**：CorePlanner 将总体指令拆解为子任务 DAG；"
            " DAGExecutor 按拓扑序/并行层级调度 ToolRouter；"
            " `POST /plan` → `POST /execute/{plan_id}` → `GET /status` / `GET /trace`。"
        ),
    },
    {
        "name": "evaluation",
        "description": (
            "**运行评测与成本追溯**：从 `storage/runs/traces/{plan_id}.json` 读取持久化 RunTrace；"
            " `GET /{plan_id}/report` 返回五维质量分；"
            " `GET /{plan_id}/trace` 返回完整 trace；"
            " `GET /{plan_id}/cost` 返回 CostSummary（含 LLM 调用明细）。"
        ),
    },
    {
        "name": "super-agent",
        "description": (
            "**Review Data Super Agent 门面**：材料包自举、规则路由、"
            "结构化 bundle、Review-Plus 委托、五维质量评分与 skill_traces。"
            " Run 持久化于 `storage/runs/review_data_agent_runs/`。"
        ),
    },
]

API_DESCRIPTION = """
# Data Agent — 航天文档智能体 API

面向航天领域文档解析与 **Review-Plus 产品保证审查** 的 REST 服务。

## 认证

除 `GET /health` 外，所有业务端点需携带以下任一凭证：

- Header: `Authorization: Bearer {API_TOKEN}`
- Header: `X-API-Key: {API_TOKEN}`

默认 Token 见环境变量 `API_TOKEN`（开发默认 `dev-token-change-me`）。

## API 如何选择

| 场景 | 推荐 API |
|------|----------|
| 竞赛/自动化：一次提交、轮询结果 | **competition-task** |
| 工作台/分步交互：上传→门禁→启动→查看中间结果 | **review-plus-*** |
| 数据智能体总入口：路由、委托、trace 与质量评分 | **super-agent** |

## 统一响应格式

```json
{
  "code": 200,
  "success": true,
  "message": "ok",
  "data": { ... }
}
```

分页列表额外包含 `page`、`size`、`total`、`pages` 字段。

## 文档与调试

- Swagger UI: `/docs`
- ReDoc: `/redoc`
- OpenAPI JSON: `/openapi.json`
"""

SECURITY_SCHEMES = {
    "BearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "description": "竞赛与 Review-Plus API Token（`API_TOKEN` 环境变量）",
    },
    "ApiKeyAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        "description": "与 Bearer 等价的 API Key 传递方式",
    },
}

DEFAULT_SECURITY = [{"BearerAuth": []}, {"ApiKeyAuth": []}]
