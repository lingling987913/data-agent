"""自定义 OpenAPI schema：分组标签、安全方案、全局描述。"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi

from data_agent.api.openapi_meta import (
    API_DESCRIPTION,
    DEFAULT_SECURITY,
    OPENAPI_TAGS,
    SECURITY_SCHEMES,
)


def configure_openapi(app: FastAPI) -> None:
    """注册自定义 OpenAPI 生成器。"""

    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=API_DESCRIPTION,
            routes=app.routes,
            tags=OPENAPI_TAGS,
        )
        schema.setdefault("components", {})
        schema["components"]["securitySchemes"] = SECURITY_SCHEMES

        for path_item in schema.get("paths", {}).values():
            for operation in path_item.values():
                if not isinstance(operation, dict):
                    continue
                if operation.get("tags") and operation["tags"][0] != "system":
                    operation.setdefault("security", DEFAULT_SECURITY)

        app.openapi_schema = schema
        return app.openapi_schema

    app.openapi = custom_openapi  # type: ignore[method-assign]
