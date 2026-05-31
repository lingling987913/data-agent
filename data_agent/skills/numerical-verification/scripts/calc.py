"""
通用数值验证脚本 — 在 Sandbox 中安全执行

用法:
    python calc.py '{"formula": "torque * pulse / inertia * 57.3", "params": {...}, "threshold": 0.2, "compare": "lt"}'

输出:
    JSON 格式计算结果，包含 result / passed / formula / params 等字段。
"""

from __future__ import annotations

import ast
import json
import math
import sys
from typing import Any


_SAFE_BUILTINS = {
    "sqrt": math.sqrt,
    "sin": math.sin,
    "cos": math.cos,
    "tan": math.tan,
    "asin": math.asin,
    "acos": math.acos,
    "atan": math.atan,
    "atan2": math.atan2,
    "log": math.log,
    "log10": math.log10,
    "log2": math.log2,
    "exp": math.exp,
    "pow": math.pow,
    "ceil": math.ceil,
    "floor": math.floor,
    "radians": math.radians,
    "degrees": math.degrees,
    "pi": math.pi,
    "e": math.e,
    "abs": abs,
    "sum": sum,
    "min": min,
    "max": max,
    "round": round,
}

_COMPARE_OPS = {
    "lt": lambda r, t: r < t,
    "le": lambda r, t: r <= t,
    "gt": lambda r, t: r > t,
    "ge": lambda r, t: r >= t,
    "eq": lambda r, t: abs(r - t) < 1e-9,
}

_ALLOWED_AST_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Constant,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.USub,
    ast.UAdd,
    ast.List,
    ast.Tuple,
)


def validate_formula_ast(formula: str, variable_names: set[str]) -> dict[str, Any]:
    """Validate formula syntax and return referenced variables.

    Only arithmetic expressions and calls to explicitly whitelisted functions
    are allowed. Unknown names are treated as missing variables.
    """
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError as exc:
        return _error("invalid_formula", f"公式语法错误: {exc}", formula=formula)

    referenced_names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_AST_NODES):
            return _error(
                "unsafe_formula",
                f"公式包含不允许的语法节点: {type(node).__name__}",
                formula=formula,
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _SAFE_BUILTINS:
                return _error("unsafe_function", "公式调用了未授权函数", formula=formula)
        elif isinstance(node, ast.Name):
            if node.id not in _SAFE_BUILTINS:
                referenced_names.add(node.id)

    missing = sorted(name for name in referenced_names if name not in variable_names)
    if missing:
        return _error(
            "missing_variables",
            f"公式变量未绑定: {', '.join(missing)}",
            formula=formula,
            missing_variables=missing,
            execution_status="insufficient_evidence",
        )

    return {"ok": True, "variables": sorted(referenced_names)}


def evaluate_formula(spec: dict[str, Any]) -> dict[str, Any]:
    """Evaluate a scalar formula spec and return a structured result."""
    formula = str(spec.get("formula", "") or "").strip()
    params = spec.get("params", {}) or {}
    threshold = spec.get("threshold")
    compare = str(spec.get("compare", "lt") or "lt")
    unit = str(spec.get("unit", "") or "")

    if not formula:
        return _error("missing_formula", "formula 不能为空")
    if not isinstance(params, dict):
        return _error("invalid_params", "params 必须是对象", formula=formula)

    numeric_params: dict[str, float] = {}
    for key, value in params.items():
        try:
            numeric_params[str(key)] = float(value)
        except (ValueError, TypeError):
            return _error(
                "invalid_parameter_value",
                f"参数 '{key}' 无法转为数值: {value}",
                formula=formula,
                params=params,
            )

    validation = validate_formula_ast(formula, set(numeric_params))
    if not validation.get("ok"):
        validation.setdefault("params", params)
        return validation

    namespace = dict(_SAFE_BUILTINS)
    namespace.update(numeric_params)

    try:
        compiled = compile(ast.parse(formula, mode="eval"), "<formula>", "eval")
        result = float(eval(compiled, {"__builtins__": {}}, namespace))  # noqa: S307
    except Exception as exc:
        return _error("execution_error", f"公式执行失败: {exc}", formula=formula, params=params)

    passed = None
    threshold_value = None
    if threshold is not None:
        try:
            threshold_value = float(threshold)
        except (TypeError, ValueError):
            return _error("invalid_threshold", f"threshold 无法转为数值: {threshold}", formula=formula)
        op_func = _COMPARE_OPS.get(compare)
        if op_func is None:
            return _error(
                "unsupported_compare",
                f"不支持的比较方式: {compare}，可选: {list(_COMPARE_OPS.keys())}",
                formula=formula,
            )
        passed = bool(op_func(result, threshold_value))

    return {
        "result": round(result, 6),
        "unit": unit,
        "threshold": threshold_value,
        "compare": compare,
        "passed": passed,
        "formula": formula,
        "params": numeric_params,
        "variables": validation.get("variables", []),
        "execution_status": "deterministic_checked",
    }


def _error(
    code: str,
    message: str,
    *,
    execution_status: str = "error",
    **extra: Any,
) -> dict[str, Any]:
    return {
        "error": message,
        "error_code": code,
        "execution_status": execution_status,
        **extra,
    }


def main() -> None:
    raw = sys.argv[1] if len(sys.argv) > 1 else "{}"
    try:
        spec = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps(_error("invalid_json", f"JSON 解析失败: {exc}"), ensure_ascii=False))
        sys.exit(1)

    output = evaluate_formula(spec)
    print(json.dumps(output, ensure_ascii=False))
    if output.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
