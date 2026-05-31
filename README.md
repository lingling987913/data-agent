# Data Agent — 工程文档数据智能体

**Data Agent** 是一套面向工程文档的数据智能体系统：负责多格式文档理解、任务规划编排、质量评测与可审计交付。本项目以**面向航天器 GNC 分系统设计要素的智能审查**为主要示范场景；通用数据能力（格式自愈、指代消解、DAG 编排、五维评测）沉淀在 `data_agent/agents/`，领域流程通过 `integrations/` 装配接入。

版本：**0.1.0**（见 `pyproject.toml`）

## 评审与提交包

不含完整源代码的正式提交材料位于 **[提交材料/](提交材料/)**，包括技术报告、本地部署说明、5 组任务示例与测试/Golden 结果。评审请从 [提交材料/README.md](提交材料/README.md) 开始，部署步骤见 [提交材料/部署与运行说明.md](提交材料/部署与运行说明.md)。

---

## 功能特性

### 通用数据智能体（`data_agent/agents/`）

| 组件 | 职责 |
| --- | --- |
| **FormatGuard** | 格式检测与 LLM 自愈（HTML/LaTeX 等） |
| **ContextResolver** | 跨页/跨文档指代消解与实体关联 |
| **PipelineOrchestrator** | 确定性规则 + LLM 双路规划、DAG 编排与执行 |
| **QualityInspector** | 五维质量评测、Token/耗时/成本追踪 |
| **DomainSpecialist** | 领域专长（当前：`integrations/satellite_review/`） |

### 文档解析

- **Office 本地解析**：`.doc` / `.docx` / `.xlsx` / `.xls` / `.csv` / `.ppt` / `.pptx`
- **PDF / 图片**：本地 MinerU HTTP → MinerU 在线 API（v4 / agent）→ `pdftotext` 三档降级（`parser_type=auto`）
- **其他**：`.html` / `.htm`、`.txt` / `.md`
- **结构化输出**：章节树、证据池、解析 trace；可选 VLM 图块描述与格式自愈

### 审查与编排

- **Review-Plus**：11 步审查链路（材料分类 → 场景识别 → 文档解析 → 结构化 → 总师组会 → 规则抽取 → 章节映射 → 逐项审查 → 追溯矩阵 → 跨文档审查 → 报告生成）
- **GNC 设计审查**：独立 10 步 workflow，REST 前缀 `/api/v1/gnc-review`
- **Super Agent**：统一门面（材料包自举、路由、Review-Plus / GNC 委托、质量评分）
- **竞赛任务 API**：一键式异步三端点（`submit` / `status` / `result`），内部走 Review-Plus workflow

---

## 架构与目录

```
data-agent/
├── data_agent/              # 后端 Python 包（FastAPI 入口 main.py）
│   ├── agents/              # 通用数据智能体
│   ├── parsing/             # 多格式解析、MinerU 路由、结构化
│   ├── integrations/        # 领域装配（当前：satellite_review/）
│   ├── review_plus/         # Review-Plus 服务与 11 步 workflow
│   ├── super_agent/         # Super Agent 门面
│   ├── api/                 # REST 路由
│   ├── workflows/           # Agno workflow 定义
│   ├── evaluation/          # 评测指标与 trace
│   └── services/            # 竞赛任务、材料处理等
├── web/                     # Next.js 15 工作台（Bun）
├── benchmark/               # 离线 Golden 门禁与压测脚本
├── config/domains/          # 领域 JSON 配置
├── data/                    # 审查模板、知识库等静态数据
├── scripts/                 # dev.sh / prod.sh 一键启停
├── storage/                 # 运行时上传、trace、run 数据（gitignore）
└── 提交材料/              # 组委会提交包（报告、示例、部署说明）
```

**分层原则**

- `agents/`：与具体业务流程解耦的通用能力
- `integrations/`：领域规划规则、DAG 步骤、Prompt Profile 与 ToolHandler；新增领域时在此注册，而非修改 `agents/`
- `parsing/`：格式路由与 MinerU 降级链，供 API、Review-Plus、Super Agent 共用

---

## 环境要求

| 组件 | 要求 |
| --- | --- |
| Python | ≥ 3.10（`pyproject.toml`） |
| 包管理 | 推荐 [uv](https://docs.astral.sh/uv/)（仓库含 `uv.lock`）；亦可用 `pip` |
| Node.js + Bun | 仅前端 `web/` 需要 |
| poppler-utils | 可选，提供 `pdftotext` 作为 PDF 兜底 |
| LLM / VLM | Review-Plus、Super Agent 等需配置；未配置时部分步骤规则/占位降级 |
| MinerU | PDF 高精度解析；不可达时降级 `pdftotext` |

---

## 安装

```bash
# 推荐：uv
uv sync --extra dev

# 或 pip
pip install -e ".[dev]"
```

可选 TDMS 支持：`pip install -e ".[tdms]"` 或 `uv sync --extra tdms`

---

## 配置

```bash
cp .env.example .env
```

主要环境变量（完整说明见 `.env.example`）：

| 类别 | 变量 | 说明 |
| --- | --- | --- |
| 认证 | `API_TOKEN` | 默认 `dev-token-change-me`，**公网务必更换** |
| 暴露范围 | `API_EXPOSE_SCOPE` | `full`（本地默认）/ `competition` / `demo` |
| LLM | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` | 审查、编排、结构化等 |
| VLM | `VLM_API_KEY`, `VLM_BASE_URL`, `VLM_MODEL_NAME` | 嵌入图、图块描述 |
| 轻量模型 | `LIGHT_LLM_*`, `LIGHT_VLM_*` | 解析/公式优先（可选） |
| MinerU 本地 | `MINERU_LOCAL_ENABLED`, `MINERU_LOCAL_API_BASE` | 本地 HTTP `POST /file_parse` |
| MinerU 在线 | `MINERU_EXTRACT_API_*`, `MINERU_AGENT_API_*` | mineru.net v4 / agent |
| Review-Plus | `REVIEW_PLUS_AGENTS_ENABLED=1` | 启用 LLM Agent 步骤 |

前端复制 `web/.env.example` 为 `web/.env.local`，配置 `NEXT_PUBLIC_API_TOKEN` 等。

---

## 运行

### 仅后端 API

```bash
uvicorn data_agent.main:app --host 0.0.0.0 --port 8080
# 或
uv run uvicorn data_agent.main:app --host 0.0.0.0 --port 8080
```

启动后访问 `GET /health` 可查看服务状态与 MinerU 本地连通性（无需认证）。

- Swagger UI：`http://localhost:8080/docs`
- ReDoc：`http://localhost:8080/redoc`

> `python -m data_agent.main` 默认监听 **8088**；`scripts/dev.sh` 默认 **8081**；`scripts/prod.sh` 默认 **8080**。

### 前后端一键启动

```bash
# 开发（后端 8081 + 前端 3000）
./scripts/dev.sh

# 生产模式（后端 8080 + Next.js standalone）
./scripts/prod.sh

# 停止
./scripts/dev.sh -k
./scripts/prod.sh -k
```

### 仅前端

```bash
cd web
cp .env.example .env.local
bun install
bun run dev    # http://127.0.0.1:3000
```

前端通过 Next.js rewrite 将 `/api/*` 代理到后端（默认 `http://127.0.0.1:8080`；开发时由 `DATA_AGENT_API_ORIGIN` 覆盖，例如 `./scripts/dev.sh` 指向 8081）。

主要页面：

| 路径 | 说明 |
| --- | --- |
| `/super-agent` | Super Agent 向导 |
| `/review-plus-v2` | Review-Plus 交互式工作台 |
| `/comprehensive-review` | 综合审查 |
| `/review` | 统一审查入口 |

---

## MinerU 解析

PDF/图片在 `parser_type=auto` 时按三档降级（`MINERU_LOCAL_FIRST=1` 且本地已启用时优先本地）：

1. **MinerU 本地 HTTP**（`POST {MINERU_LOCAL_API_BASE}/file_parse`）
2. MinerU 在线 API（v4 extract 或 agent，见 `MINERU_API_MODE`）
3. `pdftotext` 兜底

默认配置示例（见 `.env.example`）：

```bash
MINERU_LOCAL_ENABLED=1
MINERU_LOCAL_FIRST=1
MINERU_LOCAL_API_BASE=http://127.0.0.1:8000
MINERU_LOCAL_PARSE_METHOD=auto          # 扫描件 PDF 可设 ocr
MINERU_LOCAL_BACKEND=hybrid-auto-engine # pipeline 通用；GPU 场景可选 hybrid
```

手动指定解析器：

```python
from data_agent.parsing.parser_core import parse_uploaded_document

parse_uploaded_document(path, name, parser_type="mineru")   # 强制本地 MinerU
parse_uploaded_document(path, name, parser_type="auto")     # 三档自动降级
```

---

## 应用场景

### 卫星 / GNC 设计审查（Review-Plus）

Review-Plus 11 步链路作为 **DomainSpecialist（卫星审查）** 的示范实现。规划 API 通过 `integrations/satellite_review/` 注册卫星 DAG 与 handler；竞赛 API 与 Super Agent 在文档包场景（≥4 文件）下委托该 workflow 执行。

```python
from data_agent.workflows.review_plus_workflow import run_review_plus_workflow
from data_agent.review_plus.service import get_review_plus_service
```

### GNC 十步独立审查

独立 REST 前缀 `/api/v1/gnc-review`，亦可在 Super Agent 中通过 `run_gnc_review` 委托。详见启动后 `/docs` 或 `/openapi.json` 中 `gnc-review` 标签。

---

## API 概览

认证：`Authorization: Bearer {API_TOKEN}` 或 `X-API-Key: {API_TOKEN}`（`GET /health` 除外）

完整分组说明：启动后 `/docs` 或 `/openapi.json`  
竞赛三端点详解：[提交材料/API接口说明.md](提交材料/API接口说明.md)

| 标签 | 用途 |
| --- | --- |
| `system` | 健康检查（无需认证） |
| `competition-task` | 竞赛：`submit` / `status` / `result` |
| `review-plus-*` | 审查任务 CRUD、材料、门禁、执行、结果、追溯 |
| `gnc-review` | GNC 十步独立审查 |
| `structuring` | 文档结构化、格式自愈、处理模式 |
| `planning` | DAG 规划、执行、trace |
| `evaluation` | 五维质量评估、成本 |
| `super-agent` | Super Agent 门面与 benchmark |

### 竞赛任务 API（摘要）

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/task/submit` | 提交单 PDF 或文档包 |
| GET | `/api/v1/task/status/{task_id}` | 轮询进度 |
| GET | `/api/v1/task/result/{task_id}` | 获取结果 |

### Review-Plus API（摘要）

前缀：`/api/v1/review-plus/reviews`

典型流程：创建 → 上传材料 → 分类/门禁 → `start` 启动审查 → 轮询 `findings` / `report.md`

```bash
export TOKEN=dev-token-change-me
export BASE=http://127.0.0.1:8080

curl -X POST "$BASE/api/v1/review-plus/reviews" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"文档包审查示例"}'
```

更多 curl 示例见 [提交材料/API接口说明.md](提交材料/API接口说明.md)。

---

## 基准测试

离线 Golden 门禁（无需 LLM/MinerU 亦可跑部分用例）：

```bash
uv run python benchmark/run_golden.py --fail-on-gate
uv run python benchmark/run_golden.py --json-out /tmp/golden.json --markdown-out /tmp/golden.md
```

其他脚本：

```bash
uv run python benchmark/benchmark_pdf.py
uv run python benchmark/benchmark_doc_package.py
uv run python benchmark/run_load_smoke.py --mode planning -n 8
```

说明见 [benchmark/README.md](benchmark/README.md)。示例 fixture 位于 [提交材料/示例/](提交材料/示例/)。

---

## 评审部署

评审与验收采用**本地代码部署**（非容器）。完整步骤、环境变量、测试与 FAQ 见 **[提交材料/部署与运行说明.md](提交材料/部署与运行说明.md)**。

快速启动：

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn data_agent.main:app --host 0.0.0.0 --port 8080
curl -s http://127.0.0.1:8080/health
```

---

## 开发与测试

离线验收优先使用 [benchmark/](benchmark/) 中的 Golden 门禁（见上文）。`pyproject.toml` 亦配置了 pytest（`testpaths = ["tests"]`）；若仓库中存在 `tests/` 目录，可执行：

```bash
uv run pytest
```

前端：

```bash
cd web
bun run lint
bun run typecheck
bun run test        # vitest
```

---

## 许可证

本项目采用 [GNU Affero General Public License v3.0](LICENSE)（AGPL-3.0）。
