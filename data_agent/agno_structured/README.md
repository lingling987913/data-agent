# Agno Structured Output Adaptation Layer

可复用的 Agno 结构化输出适配层，用于评估和集成国产模型（Qwen、GLM、MiniMax）。

## 模块结构

```
data_agent/agno_structured/
├── schemas.py                    # Pydantic 模型与能力画像
├── provider_capability_probe.py  # 能力探测（mock + 可选 live）
├── level_adapter.py              # A/B/C/D 四级策略路由
├── validation.py                 # Schema 校验与修复、失败日志
├── examples/                     # Agent / Team / parser_model / strict tool 示例
└── scripts/smoke_test.py         # 离线 smoke test
```

## Agno 结构化输出能力摘要

| Agno 参数 | 用途 |
|-----------|------|
| `output_schema` | Pydantic 模型，约束最终输出结构 |
| `use_json_mode=True` | 提示词 + `json_object`，非 API 级 schema 校验 |
| `supports_native_structured_outputs` | OpenAI `json_schema` strict（Level A） |
| `strict_output` | OpenAIChat 上控制 json_schema strict |
| `parser_model` | 主模型推理，副模型 structured 收口（Level C） |
| `output_model` | 单模型流水线中的格式化模型 |
| `Agent.run(..., output_schema=...)` | 单次 run 覆盖 schema |
| `Team.output_schema` / `team.run(..., output_schema=...)` | Team 级 structured 输出 |
| `@tool(strict=True)` | strict tool schema fallback（Level D） |

## 四级策略

| Level | 策略 | 适用场景 |
|-------|------|----------|
| **A** | Native JSON Schema strict | OpenAI 官方端点 |
| **B** | `use_json_mode` + Pydantic 校验/修复 | Qwen/GLM/MiniMax 兼容端点 |
| **C** | `parser_model` 收口 | 主模型推理强、直接 structured 弱 |
| **D** | `@tool(strict=True)` fallback | 上述均不可靠时 |

**原则：**
- 主模型：复杂推理、工具调用、业务逻辑
- `parser_model`：structured 收口（推荐 LIGHT_LLM / 小模型）
- `output_schema`：最终 Pydantic 校验
- 思考链模式可能破坏 JSON 输出 → 通过 `extra_body` 关闭

## 运行 Smoke Test

```bash
# 离线（无需 API Key）
uv run python data_agent/agno_structured/scripts/smoke_test.py

# 含 live agent 调用
AGNO_STRUCTURED_SMOKE_LIVE=1 uv run python data_agent/agno_structured/scripts/smoke_test.py
```

## 运行能力探测

```bash
# Mock 探测（默认，基于 provider 启发式）
uv run python -c "
from data_agent.agno_structured import probe_provider_capabilities, build_capability_matrix
from data_agent.agno_structured.provider_capability_probe import build_capability_matrix
cap = probe_provider_capabilities()
print(build_capability_matrix([cap]))
"

# Live 探测（需要 .env 中 LLM_* 配置）
AGNO_STRUCTURED_LIVE_PROBE=1 uv run python -c "
from data_agent.agno_structured import probe_provider_capabilities
from data_agent.agno_structured.provider_capability_probe import build_capability_matrix
cap = probe_provider_capabilities()
print(cap.model_dump())
print(build_capability_matrix([cap]))
"
```

## 环境变量

沿用 `.env.example` 中的 `LLM_*` / `LIGHT_LLM_*`：

| 变量 | 说明 |
|------|------|
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME` | 主模型 |
| `LLM_EXTRA_BODY` | 关闭思考链，如 `{"chat_template_kwargs":{"enable_thinking":false}}` |
| `LIGHT_LLM_*` | parser_model 轻量模型 |
| `AGNO_STRUCTURED_LIVE_PROBE=1` | 启用 live 能力探测 |
| `AGNO_STRUCTURED_SMOKE_LIVE=1` | smoke test 中运行 live agent |

## 模型推荐（模板）

| Provider | 主模型 | parser_model | 推荐 Level | 备注 |
|----------|--------|--------------|------------|------|
| Qwen | Qwen3.5+ | Qwen3.5-4B | B/C | 关闭 thinking |
| GLM | GLM-4 系列 | GLM-4-Flash | B/C | `thinking.type=disabled` |
| MiniMax | abab 系列 | 同系列小模型 | B | OpenAI 兼容，system role |
| OpenAI | gpt-4o+ | gpt-4o-mini | A | native json_schema |

> 实际能力以 `probe_provider_capabilities()` 结果为准。

## pytest

```bash
uv run pytest tests/test_agno_structured_*.py -v
```
