# 面向 GNC 设计要素审查的数据智能体

围绕 **GNC 分系统设计要素审查** 业务构建的数据智能体：支撑送审材料处理、缺项检查、设计要素抽取、证据定位、问题建议与结论草稿生成，形成可进入评审准备、专业审查、质量产保自查与问题闭环的**智能辅助审查**能力。通用能力（格式自愈、指代消解、DAG 编排、五维质量评测）沉淀在 `data_agent/agents/`，GNC 专业规则、检查单与审查流程通过 `integrations/`、`review_plus/` 与 workflow 装配落地。

本系统**不是**单一文档问答工具，也**不是**仅对 PDF 做解析展示；在齐套材料与明确审查范围条件下，可将审查前准备、材料整理与证据定位压缩至小时级，使专家聚焦方案合理性、风险接受与型号放行等高价值判断。**正式评审结论仍由专家与评审组织形成**，系统输出须人工复核（见 [提交材料/技术报告-正式版.md](提交材料/技术报告-正式版.md) 第 8 章）。

版本：**0.1.0**（`pyproject.toml`）

## 建设目标（摘要）

| 目标 | 能力要求 | 主要输出 |
| --- | --- | --- |
| 材料统一处理 | PDF、Word、Excel、文本等；复杂 PDF 增强解析与降级兜底 | 结构化底稿、章节结构、解析异常清单 |
| 缺项与齐套检查 | 材料/章节/参数/依据缺项与解析质量 | 齐套性判定、缺项清单 |
| 设计要素审查 | 任务要求、参数、公式、接口、验证与质量闭环 | 要素清单、检查单响应、问题候选 |
| 多专业协同核查 | 姿态确定、姿态控制、FDIR、接口、验证、跨文档一致性 | 专业发现、合稿清单、待确认项 |
| 证据链与闭环 | 意见绑定原文、依据、整改与关闭状态 | 意见单、纪要、追溯记录 |
| 知识资产沉淀 | 专业规则、历史问题、典型缺陷与跨型号经验 | 规则库、问题库、审查知识资产 |

证据链按 **Evidence → Finding → RID → Minutes → Decision** 组织，满足审查意见可追溯要求。

## 比赛提交包

不含完整源码的正式材料见 **[提交材料/](提交材料/)**：技术报告、部署说明、5 组任务示例与 Golden 结果。评审入口：[提交材料/README.md](提交材料/README.md)；部署与 FAQ 见 [提交材料/部署与运行说明.md](提交材料/部署与运行说明.md)；竞赛 API 见 [提交材料/API接口说明.md](提交材料/API接口说明.md)。

---

## 五环节处理链路

智能审查工作台按以下环节连续运行（与技术报告 §5.1 一致）：

| 环节 | 核心目标 | 主要产物 |
| --- | --- | --- |
| 上传材料 | 接收送审包并建立运行上下文 | `run_id`、材料清单、原始包 |
| 识别与路由 | 判定材料角色与审查场景，选择处理路线 | 路由结果、审查任务板、执行计划 |
| 文档解析 | 形成结构化底稿与证据集合 | 章节结构、证据池、设计要素候选 |
| 文档审查 | 按三类路线执行核查并形成发现 | 问题候选、差异项、证据结果 |
| 审查结果 | 合稿归并并形成结论草稿与闭环材料 | 问题清单、结论草稿、质量报告 |

**Super Agent** 为统一入口，完成材料自举、场景识别与路线委托；持久化与 Trace 落在 `storage/`（`uploads`、`runs`、检查点、审查发现等）。

## 三类审查路线

| 路线 | 典型触发 | 说明 |
| --- | --- | --- |
| **GNC 设计要素审查** | GNC 设计报告、姿轨控专业送审材料 | 多步 GNC 设计要素审查 workflow：设计要素抽取、检查单匹配、专业单元核查、问题归并 |
| **文件组 / 文文一致性审查** | 任务书、设计报告、ICD、仿真、检查单等多份材料 | 要求—设计—验证追溯、跨文档指标与检查单响应一致性 |
| **智能通用化审查** | 材料不齐、目标非标准或未命中专用规则 | 动态规划与通用工具组合；输出受限说明与补充材料建议，**不等同** GNC 专业结论 |

业务侧 GNC 审查可按接收、结构化、门控、提取、匹配、核查、合稿、审定、确认与闭环等多步组织；数据智能体承担预处理、缺项检查、要素抽取、证据定位与问题草稿，专家承担专业裁定与正式结论。

## 竞赛三大任务（工程映射）

与技术报告验证场景及 [提交材料/示例/](提交材料/示例/) 对应：

| 竞赛任务 | 含义 | 本仓库验证入口 |
| --- | --- | --- |
| **任务一** | 数据理解与结构化处理 | 示例 [01](提交材料/示例/01-多格式结构化/)–[03](提交材料/示例/03-跨文档指代/)：`structuring/parse`、Super Agent `structure`、PDF 降级链 |
| **任务二** | 复杂任务规划与自动执行 | 示例 [04](提交材料/示例/04-规划与编排/)：`planning/*`、`task/submit`、`review-plus/*`、`super-agent/*` |
| **任务三** | 系统稳定性与综合能力评测 | 示例 [05](提交材料/示例/05-离线基准稳定性/)、[benchmark/](benchmark/)、[提交材料/测试结果/](提交材料/测试结果/) |

任务一 **ywdata 实跑**以 PDF / Word / Excel 送审材料为主；HTML/PPT、极端 OCR、工程图专项以任务三合成基准回归为主（见 [提交材料/示例/业务数据映射表.md](提交材料/示例/业务数据映射表.md)）。

---

## 能力特性

### 通用能力（`data_agent/agents/`）

| 组件 | 职责 |
| --- | --- |
| **FormatGuard** | 格式检测与 LLM 自愈（HTML/LaTeX 等异常版面） |
| **ContextResolver** | 跨页/跨文档指代消解与实体关联 |
| **PipelineOrchestrator** | 确定性规则 + LLM 双路规划、DAG 编排与执行 |
| **QualityInspector** | 五维质量评测、Token/耗时/成本追踪 |
| **DomainSpecialist** | 领域专长装配入口（当前：`integrations/satellite_review/`） |

领域规则、检查单、GNC 专业单元与 ToolHandler 通过 `integrations/` 注入，不固化在通用层。

### 送审材料解析

- **Office 本地解析**：`.doc` / `.docx` / `.xlsx` / `.xls` / `.csv` / `.ppt` / `.pptx`
- **PDF / 图片**：本地 MinerU HTTP → MinerU 在线 API（v4 extract / agent）→ `pdftotext` 三档降级（`parser_type=auto`）
- **其他**：`.html` / `.htm`、`.txt` / `.md`
- **结构化底稿**：章节树、证据池、参数/公式候选、解析 trace；可选 VLM 图块语义说明与格式自愈

扫描件方向归一化、硬规则预筛 + 大模型合理性校准等增强能力见技术报告 §5.6；关键参数、公式与工程图判读须保留原文并人工确认。

### 审查与编排

- **Review-Plus（文件组 / 文文一致性）**：多步审查 workflow，多 Agent 协同覆盖材料分类、解析与结构化、规则与章节映射、逐项审查、追溯矩阵、跨文档审查与报告合成等环节
- **GNC 设计要素审查**：多步 GNC 设计要素审查 workflow，REST 前缀 `/api/v1/gnc-review`
- **Super Agent**：统一入口（送审包自举、场景识别、路线委托、质量评分）
- **竞赛任务 API**：对外异步三端点（`submit` / `status` / `result`），内部走 Review-Plus workflow

---

## 系统架构与目录

技术路线：**业务流程牵引 → 通用能力支撑 → 领域装配落地 → 过程质量闭环**。

```
data-agent/
├── data_agent/              # FastAPI 后端（main.py）
│   ├── agents/              # 通用智能体：格式自愈、指代消解、编排、质量评测
│   ├── parsing/             # 多格式解析、MinerU 路由、结构化底稿
│   ├── integrations/        # 领域装配（satellite_review / GNC 等）
│   ├── review_plus/         # 文件组多步审查实现（文文一致性等）
│   ├── super_agent/         # Super Agent 统一入口
│   ├── api/                 # REST 路由
│   ├── workflows/           # 工作流定义（含 GNC 多步审查、Review-Plus 等）
│   ├── evaluation/          # 质量评测与 trace
│   └── services/            # 竞赛任务、材料处理等
├── web/                     # Next.js 智能审查工作台（Bun）
├── benchmark/               # 离线 Golden 门禁与压测
├── config/domains/          # 领域 JSON 配置
├── data/                    # 模板、知识库等静态数据
├── scripts/                 # deploy.sh / dev.sh / prod.sh 一键启停
├── docs/                    # 新人部署与配置说明
├── storage/                 # 运行时数据（gitignore）
└── 提交材料/                # 比赛提交包
```

| 层次 | 组成 | 作用 |
| --- | --- | --- |
| 工作台与接口 | `web/`、任务 API、Super Agent、解析与审查 API | 任务提交、状态流转、结果查阅 |
| 通用能力 | `agents/`、`parsing/`、编排与质量评测 | 支撑五环节链路 |
| 领域装配 | `integrations/`、`review_plus/`、GNC workflow | 三类审查路线执行 |
| 运行存储 | `storage/` | 归档、复现与审计 |

**分层原则**

- `agents/`：与具体审查业务流程解耦的通用能力
- `integrations/`：领域规划规则、DAG 步骤、Prompt Profile 与 ToolHandler；新增 GNC/型号领域时在此注册，而非修改 `agents/`
- `parsing/`：格式路由与 MinerU 降级链，供 API、Review-Plus、Super Agent 共用

---

## 环境要求

| 组件 | 要求 |
| --- | --- |
| Python | ≥ 3.10（`pyproject.toml`） |
| 包管理 | 推荐 [uv](https://docs.astral.sh/uv/)（仓库含 `uv.lock`）；亦可用 `pip` |
| Node.js + Bun | 仅前端 `web/` 需要 |
| poppler-utils | 可选，提供 `pdftotext` 作为 PDF 兜底 |
| LLM / VLM | 审查、编排、图块描述等；未配置时部分步骤规则/占位降级 |
| MinerU | 复杂 PDF/扫描件主通道；不可达时降级 `pdftotext` |

---

## 新人上手（前后端一体化）

刚 clone 仓库时，在根目录执行：

```bash
chmod +x scripts/deploy.sh scripts/prod.sh scripts/dev.sh
./scripts/deploy.sh              # 安装依赖 + 生成 .env + 生产模式启动（8080 + 3000）
./scripts/deploy.sh --setup-only # 只装依赖、复制环境文件，不启动
./scripts/deploy.sh --dev        # 开发模式（8081 + 3000）
./scripts/deploy.sh --check      # 检查必配项是否为占位符
./scripts/deploy.sh -k           # 停止
```

**需要改哪些配置**（必配 Token、建议 LLM/MinerU、公网暴露等）见 **[docs/部署与配置说明.md](docs/部署与配置说明.md)**。

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
| LLM | `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL_NAME` | 审查、编排、结构化底稿等 |
| VLM | `VLM_API_KEY`, `VLM_BASE_URL`, `VLM_MODEL_NAME` | 嵌入图、图块描述 |
| 轻量模型 | `LIGHT_LLM_*`, `LIGHT_VLM_*` | 解析/公式优先（可选） |
| MinerU 本地 | `MINERU_LOCAL_ENABLED`, `MINERU_LOCAL_API_BASE` | 本地 HTTP `POST /file_parse` |
| MinerU 在线 | `MINERU_EXTRACT_API_*`, `MINERU_AGENT_API_*` | mineru.net v4 / agent |
| Review-Plus | `REVIEW_PLUS_AGENTS_ENABLED=1` | 启用 LLM Agent 审查步骤 |

前端复制 `web/.env.example` 为 `web/.env.local`，配置 `NEXT_PUBLIC_API_TOKEN` 等与后端一致的认证信息。

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
# 新人推荐（含依赖安装 + .env 初始化）
./scripts/deploy.sh

# 开发（后端 8081 + 前端 3000）
./scripts/dev.sh
# 或
./scripts/deploy.sh --dev

# 生产模式（后端 8080 + Next.js standalone）
./scripts/prod.sh

# 停止
./scripts/deploy.sh -k
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

智能审查工作台主要页面：

| 路径 | 说明 |
| --- | --- |
| `/super-agent` | Super Agent 统一入口向导 |
| `/review-plus-v2` | 文件组 / 文文一致性交互式审查工作台 |
| `/comprehensive-review` | 综合审查 |
| `/review` | 统一审查入口 |

---

## 文档解析与 MinerU

送审材料须转为**结构化底稿**（章节、表格、公式、图片、参数候选、证据集合）方可进入审查环节。PDF/图片在 `parser_type=auto` 时按三档降级（`MINERU_LOCAL_FIRST=1` 且本地已启用时优先本地）：

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
MINERU_API_MODE=extract
```

程序化指定解析器：

```python
from data_agent.parsing.parser_core import parse_uploaded_document

parse_uploaded_document(path, name, parser_type="mineru")   # 强制本地 MinerU
parse_uploaded_document(path, name, parser_type="auto")     # 三档自动降级
```

---

## 审查应用场景

### 文件组 / 文文一致性审查（Review-Plus）

Review-Plus 多步审查 workflow 作为 **DomainSpecialist（卫星/GNC 送审包审查）** 的领域实现，由多 Agent 协同编排各审查环节。规划 API 通过 `integrations/satellite_review/` 注册审查 DAG 与 handler；竞赛 API 与 Super Agent 在送审包场景（通常 ≥4 份材料）下委托该 workflow 执行。

```python
from data_agent.workflows.review_plus_workflow import run_review_plus_workflow
from data_agent.review_plus.service import get_review_plus_service
```

### GNC 设计要素多步独立审查

独立 REST 前缀 `/api/v1/gnc-review`，亦可在 Super Agent 中通过 `run_gnc_review` 委托。接口分组与请求体见启动后 `/docs` 或 `/openapi.json` 中 `gnc-review` 标签。

---

## API 概览

认证：`Authorization: Bearer {API_TOKEN}` 或 `X-API-Key: {API_TOKEN}`（`GET /health` 除外）。

完整分组说明：启动后 `/docs` 或 `/openapi.json`。竞赛三端点字段与 curl 详解：[提交材料/API接口说明.md](提交材料/API接口说明.md)。

| 标签 | 用途 |
| --- | --- |
| `system` | 健康检查（无需认证） |
| `competition-task` | 竞赛：`submit` / `status` / `result` |
| `super-agent` | 统一入口、能力查询与 benchmark |
| `structuring` | 文档结构化、格式自愈、处理模式 |
| `planning` | DAG 规划、执行、trace |
| `review-plus-*` | 文件组审查任务 CRUD、材料、门禁、执行、结果、追溯 |
| `gnc-review` | GNC 设计要素多步审查 workflow |
| `evaluation` | 五维质量评估、成本 |

### 竞赛任务 API（摘要）

内部走 Review-Plus 工作流，对外仅暴露三端点：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/v1/task/submit` | 提交单 PDF 或送审文档包 |
| GET | `/api/v1/task/status/{task_id}` | 轮询审查进度 |
| GET | `/api/v1/task/result/{task_id}` | 获取审查结果与证据摘要 |

### Review-Plus API（摘要）

前缀：`/api/v1/review-plus/reviews`

典型流程：创建审查任务 → 上传送审材料 → 分类/门禁 → `start` 启动审查 → 轮询 `findings` / `report.md`

```bash
export TOKEN=dev-token-change-me
export BASE=http://127.0.0.1:8080

curl -X POST "$BASE/api/v1/review-plus/reviews" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name":"GNC送审包审查示例"}'
```

更多 curl 与响应字段见 [提交材料/API接口说明.md](提交材料/API接口说明.md)。

---

## 验证与基准测试

技术报告 §6 五类验证场景：多格式结构化、GNC 设计文档审查、文件组文文一致性、通用化智能审查、质量产保与问题闭环。离线 Golden 门禁（**任务三**，部分用例无需 LLM/MinerU）：

```bash
uv run python benchmark/run_golden.py --fail-on-gate
uv run python benchmark/run_golden.py --json-out /tmp/golden.json --markdown-out /tmp/golden.md
```

其他专项脚本：

```bash
uv run python benchmark/benchmark_pdf.py
uv run python benchmark/benchmark_doc_package.py
uv run python benchmark/run_load_smoke.py --mode planning -n 8
```

说明见 [benchmark/README.md](benchmark/README.md)；示例 fixture 位于 [提交材料/示例/](提交材料/示例/)；实跑摘要见 [提交材料/测试结果/](提交材料/测试结果/)。

---

## 评审部署与故障排查

评审与验收采用**本地代码部署**（非容器）。完整步骤、环境变量、测试方法与 FAQ 见 **[提交材料/部署与运行说明.md](提交材料/部署与运行说明.md)**。

评审机快速启动：

```bash
uv sync --extra dev
cp .env.example .env
uv run uvicorn data_agent.main:app --host 0.0.0.0 --port 8080
curl -s http://127.0.0.1:8080/health
```

常见问题速查（详见部署说明 §9）：

| 现象 | 处理要点 |
| --- | --- |
| 401 / Invalid API token | 前后端 `API_TOKEN` / `NEXT_PUBLIC_API_TOKEN` 一致 |
| 端口连不上 | 确认实际监听端口（8080/8081/8088）与 curl 地址一致 |
| 测试数据找不到 | 按 [业务数据映射表](提交材料/示例/业务数据映射表.md) 复制 ywdata |
| MinerU 不可用 / health degraded | 检查 `MINERU_LOCAL_*` 或接受 `pdftotext` 降级 |
| 竞赛 result 409 | 任务未完成或失败，先查 `status` 再取 `result` |

---

## 开发与测试

离线验收优先使用 [benchmark/](benchmark/) 中的 Golden 门禁（见上文）。`pyproject.toml` 配置了 pytest（`testpaths = ["tests"]`）；若仓库中存在 `tests/` 目录，可执行：

```bash
uv run pytest
```

推荐子集（与比赛提交包一致）：

```bash
uv run pytest -q tests/test_golden_benchmark.py tests/test_pdf_auto_parse_chain.py \
  tests/test_review_plus_workflow.py tests/test_gnc_workflow.py
```

前端：

```bash
cd web
bun run lint
bun run typecheck
bun run test        # vitest
```

过程日志与 trace 字段说明：[提交材料/测试与日志说明.md](提交材料/测试与日志说明.md)。

---

## 许可证

本项目采用 [GNU Affero General Public License v3.0](LICENSE)（AGPL-3.0）。
