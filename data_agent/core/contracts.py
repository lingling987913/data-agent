from __future__ import annotations

from typing import Any


def success_response(
    data: Any = None,
    *,
    message: str = "ok",
    code: int = 200,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "success": True,
        "message": message,
        "data": data,
    }
    payload.update(extra)
    return payload


def paginated_response(
    items: list[Any],
    *,
    page: int,
    size: int,
    total: int,
    message: str = "ok",
) -> dict[str, Any]:
    return success_response(
        items,
        message=message,
        page=page,
        size=size,
        total=total,
        pages=(total + size - 1) // size if size else 0,
    )


def error_response(
    *,
    message: str,
    code: int = 400,
    data: Any = None,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": code,
        "success": False,
        "message": message,
        "data": data,
    }
    payload.update(extra)
    return payload
