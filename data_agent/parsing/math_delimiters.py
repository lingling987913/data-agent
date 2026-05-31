"""Wrap MinerU raw LaTeX fragments with Markdown math delimiters for preview."""

from __future__ import annotations

import re

_LATEX_COMMAND = re.compile(
    r"\\(?:boldsymbol|mathbf|begin|frac|left|right|Bigg|bigg|Big|big|Phi|dot|sin|cos|tan|quad|"
    r"cdots|eta|rho|sigma|alpha|beta|gamma|delta|theta|lambda|mu|pi|partial|nabla|"
    r"sum|prod|int|sqrt|mathrm|operatorname|hat|widehat|widetilde|overline|underline|"
    r"bar|vec|ddot|approx)"
)
_DISPLAY_MATH_TRIGGER = re.compile(
    r"\\(?:begin\{|frac|Bigg|bigg|left|array)|\\\\|\n"
)
_INLINE_SUBSCRIPT = re.compile(r"\b([A-Za-z]+(?:_\{[^}]+\}|_[A-Za-z0-9]))(?=\s|[，,。；;:]|$)")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def _looks_like_latex_content(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if _LATEX_COMMAND.search(stripped):
        return True
    if stripped.startswith("\\") and re.search(r"[\\_{}^]", stripped):
        return True
    return bool(_INLINE_SUBSCRIPT.search(stripped))


def _is_fully_math_delimited(text: str) -> bool:
    stripped = text.strip()
    if stripped.startswith("$$") and stripped.endswith("$$") and len(stripped) > 4:
        return True
    if stripped.startswith(r"\[") and stripped.endswith(r"\]"):
        return True
    return False


def _has_raw_undelimited_latex(text: str) -> bool:
    scratch = text
    scratch = re.sub(r"\$\$[\s\S]*?\$\$", "", scratch)
    scratch = re.sub(r"\$[^$\n]+\$", "", scratch)
    return _looks_like_latex_content(scratch)


def _should_use_display_math(latex: str) -> bool:
    if _DISPLAY_MATH_TRIGGER.search(latex):
        return True
    return "\n" in latex.strip()


def _wrap_inline_subscripts(text: str) -> str:
    if "$" in text:
        return text
    return _INLINE_SUBSCRIPT.sub(r"$\1$", text)


def ensure_math_delimiters(text: str) -> str:
    """Ensure raw LaTeX from MinerU is wrapped for remark-math / KaTeX preview."""
    if not text:
        return text
    stripped = text.strip()
    if _is_fully_math_delimited(stripped):
        return text
    if "$" in stripped and not _has_raw_undelimited_latex(stripped):
        return text
    if not _looks_like_latex_content(stripped):
        return text

    command_match = _LATEX_COMMAND.search(stripped)
    if command_match is None and stripped.startswith("\\"):
        command_match = re.search(r"\\", stripped)

    if command_match is not None:
        prefix = stripped[: command_match.start()]
        latex = stripped[command_match.start() :].strip().rstrip("，,。；;")
        if not latex:
            return text
        if not prefix.strip():
            return f"$$\n{latex}\n$$"
        if _CJK_RE.search(prefix):
            if _should_use_display_math(latex):
                return f"{prefix.rstrip()}\n\n$$\n{latex}\n$$"
            return f"{prefix.rstrip()} ${latex}$"
        return f"$$\n{latex}\n$$"

    return _wrap_inline_subscripts(stripped)
