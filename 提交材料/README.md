# 面向航天器 GNC 分系统设计要素智能审查的数据智能体 — 比赛提交包

本目录为**评审材料落点**，不含系统源代码。完整实现见仓库根目录 `data_agent/`、`web/`。

## 材料索引

| 材料 | 路径 | 说明 |
| --- | --- | --- |
| **测试 / 评审材料（业务文档真源）** | **[评审材料/](./评审材料/)** | 组委会正式测试文档（月兔一号、蓬莱一号）；**测试数据 同步入口** |
| **技术报告（正式版，Word）** | [技术报告.docx](./技术报告.docx) | 组委会技术报告正式稿（源文件：仓库根 `面向GNC设计要素审查的数据智能体技术报告-正式版.docx`） |
| **技术报告（正式版，Markdown）** | [技术报告-正式版.md](./技术报告-正式版.md) | Markdown 版；图片见 [技术报告附件/](./技术报告附件/) |
| 部署与运行说明 | [部署与运行说明.md](./部署与运行说明.md) | 架构、环境、本地验收、FAQ |
| 测试日志与结果说明 | [测试与日志说明.md](./测试与日志说明.md) | 任务追溯字段、日志落盘位置 |
| 竞赛任务 API | [API接口说明.md](./API接口说明.md) | task/submit、status、result 与认证 |
| OpenAPI 分组 | 在线 `/docs` 或仓库根启动后 `/openapi.json` | 全量接口标签；本包未单独附 OpenAPI 文档时以运行实例为准 |
| 典型任务示例（5 组） | [示例/](./示例/) | 工程验证示例；测试数据 可由 [评审材料/](./评审材料/) 同步，见 [业务数据映射表.md](./示例/业务数据映射表.md) |
| 测试日志与结果 | [测试结果/](./测试结果/) | golden 实跑 JSON、pytest 摘要、脱敏 trace |

### 示例输出说明

| 文件 | 性质 |
| --- | --- |
| `示例/*/输出样例.json` | **字段示意**（`_example: true`），便于对照 API/工作流字段 |
| `测试结果/基准运行摘要.json` | **本机实跑**离线基准汇总（见 [测试结果/README.md](./测试结果/README.md)） |
| `测试结果/*跟踪样例.json` | **脱敏**执行/降级 trace 样例，结构对齐 `storage/runs/` |

## 五大评价维度快速入口

技术报告正文（Word）含五大评价维度与附录检查单。比赛提交包内工程证据入口：

| 维度 | 分值 | 快速入口 |
| --- | ---: | --- |
| 1 复杂文档理解与结构化 | 20 | 示例 [01](./示例/01-多格式结构化/)–[03](./示例/03-跨文档指代/) |
| 2 难点场景与创新 | 15 | 示例 [02](./示例/02-PDF验收解析/) |
| 3 Agent 规划与执行 | 30 | 示例 **[04](./示例/04-规划与编排/)** |
| 4 稳定与可复现 | 20 | [测试结果/](./测试结果/) · 示例 [05](./示例/05-离线基准稳定性/) |
| 5 开源与产业生态 | 15 | 仓库 `data_agent/`、`tests/`、`benchmark/` |

## 五组示例

| 示例 | 支撑能力 | 竞赛任务 | 一句话 |
| --- | --- | --- | --- |
| [01 多格式结构化](./示例/01-多格式结构化/) | 场景一 / 多源结构化 | 任务一 | Word + Excel 多源解析与 bundle |
| [02 PDF 验收解析](./示例/02-PDF验收解析/) | 场景一 / PDF 降级 | 任务一 | PDF 降级链与验收材料 |
| [03 跨文档指代](./示例/03-跨文档指代/) | 场景三 / 跨材料追溯 | 任务一 | 双 docx 合并与追溯候选 |
| [04 规划与编排](./示例/04-规划与编排/) | 场景二/三 / 审查编排 | 任务二 | 规划 DAG + Review-Plus + 降级 |
| [05 离线基准稳定性](./示例/05-离线基准稳定性/) | 稳定评测与回归门禁 | 任务三 | 离线门禁、延迟 P95、压测骨架 |

## 测试材料与实跑验证范围

**正式测试文档**位于 [评审材料/](./评审材料/)（月兔一号/蓬莱一号四件套 Word + Excel）。同步至示例 测试数据：

```bash
bash 提交材料/示例/脚本/复制业务数据.sh   # 无 ywdata/ 时自动使用 评审材料/月兔一号
```

面向 GNC 送审文档（**PDF、Word、Excel**），由示例 **01–03** 覆盖；映射见 [业务数据映射表.md](./示例/业务数据映射表.md)。PDF（CMG50 验收报告）不在 评审材料，需 `ywdata/pdf/` 或示例 02 脱敏 PDF。

**不在任务一实跑范围**：HTML/PPT、极端 OCR、工程图/流程图独立解析（相关项见示例 05 离线基准回归）。

## 评审路径（两档）

### 5 分钟快速路径（材料存在性 + 服务可用）

无需 LLM/MinerU；验证 clone 后可启动、测试数据 可访问。

```bash
cd /path/to/data-agent
uv sync --extra dev        # 或 pip install -e ".[dev]"
cp .env.example .env       # 或使用 部署与运行说明.md §2.5 评审机最小 .env

# 测试数据：比赛提交包已含脱敏样例；有 ywdata 可 bash 提交材料/示例/脚本/复制业务数据.sh
ls 提交材料/示例/01-多格式结构化/测试数据/

uv run uvicorn data_agent.main:app --host 0.0.0.0 --port 8080
curl -s http://127.0.0.1:8080/health | python3 -m json.tool
export TOKEN=dev-token-change-me
curl -s -H "Authorization: Bearer $TOKEN" http://127.0.0.1:8080/api/v1/structuring/modes | head -c 200
```

### 30 分钟完整路径（离线基准 + 示例 API）

在 5 分钟路径基础上：

```bash
# 1) 离线基准门禁（任务三）
uv run python benchmark/run_golden.py --json-out 提交材料/测试结果/基准运行摘要.json \
  2>&1 | tee 提交材料/测试结果/基准运行.log

# 2) 推荐 pytest 子集（完整 tests/ 检出时，见 部署与运行说明.md §4.1）
uv run pytest -q tests/test_golden_benchmark.py tests/test_pdf_auto_parse_chain.py \
  tests/test_review_plus_workflow.py tests/test_gnc_workflow.py --tb=no \
  2>&1 | tee 提交材料/测试结果/单元测试摘要.txt

# 3) 任务一 structuring 冒烟（示例 01 fixture）
FIX="$(pwd)/提交材料/示例/01-多格式结构化/测试数据"
curl -s -X POST http://127.0.0.1:8080/api/v1/structuring/parse \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"file_path\":\"$FIX/月兔一号_飞轮研制任务书.docx\",\"file_name\":\"task_book.docx\",\"parser_type\":\"auto\"}" | head -c 400

# 4) 竞赛 API（示例 04 / API接口说明.md）
```

详细步骤、FAQ、竞赛 curl：[部署与运行说明.md](./部署与运行说明.md)、[API接口说明.md](./API接口说明.md)。

## 源代码位置

| 模块 | 路径 |
| --- | --- |
| 后端 API | `data_agent/` |
| 解析（路由/后处理/结构化） | `data_agent/parsing/` |
| 审查（Review-Plus、GNC workflow） | `data_agent/review_plus/`、`data_agent/integrations/satellite_review/` |
| 离线基准评测 | `benchmark/` |
| 领域装配 | `config/domains/` |
| 测试 | `tests/` |

## 外部依赖（评审须知）

- **LLM/VLM**：Review-Plus、Super Agent 等需配置；未配置时部分步骤降级。
- **MinerU**：PDF 高精度解析；不可达时降级 `pdftotext`（见示例 2）。
- **SMART 委员会**：默认关闭，需显式开启 `SMART_GENERIC_LLM_ENABLED`（见技术报告 §4.2.3）。

## 版本

- 技术报告正式版：**Word**（`技术报告.docx`，2026-05）
- 工程：**0.1.0**（`pyproject.toml`）
