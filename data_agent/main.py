from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from data_agent.api.access_control import ApiAccessControlMiddleware, warn_default_api_token_if_public
from data_agent.api.openapi import configure_openapi
from data_agent.api.openapi_meta import OPENAPI_TAGS
from data_agent.api.gnc_review_router import router as gnc_review_router
from data_agent.api.evaluation_router import router as evaluation_router
from data_agent.api.super_agent_router import router as super_agent_router
from data_agent.api.planning_router import router as planning_router
from data_agent.api.structuring_router import router as structuring_router
from data_agent.api.parsing_router import router as parsing_router
from data_agent.api.review_plus_router import router as review_plus_router
from data_agent.api.review_workbench_router import router as review_workbench_router
from data_agent.api.task_router import router as task_router
from data_agent.core.config import ensure_dirs
from data_agent.core.agno_logging import setup_agno_file_logging
from data_agent.core.startup_checks import run_startup_checks
from data_agent.parsing.parsers.mineru_local_http_parser import check_mineru_local_health

logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


_configure_logging()
setup_agno_file_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    ensure_dirs()
    mineru = check_mineru_local_health()
    if not mineru["enabled"]:
        logger.info("MinerU local service disabled (MINERU_LOCAL_ENABLED=0)")
    elif mineru["reachable"]:
        logger.info("MinerU local service reachable at %s (%s)", mineru["base_url"], mineru["detail"])
    else:
        logger.warning(
            "MinerU local enabled at %s but unreachable: %s",
            mineru["base_url"],
            mineru["detail"],
        )
    run_startup_checks()
    warn_default_api_token_if_public()
    yield


app = FastAPI(
    title="Data Agent API",
    description="工程文档解析、数据智能体编排与 Review-Plus 示例集成 REST 服务",
    version="0.1.0",
    openapi_tags=OPENAPI_TAGS,
    lifespan=lifespan,
)
configure_openapi(app)

_cors_origins = os.getenv(
    "CORS_ORIGINS",
    "http://127.0.0.1:3000,http://localhost:3000",
).split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in _cors_origins if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(ApiAccessControlMiddleware)


@app.get(
    "/health",
    tags=["system"],
    summary="健康检查",
    description="返回服务状态与 MinerU 本地解析服务连通性；无需认证。",
)
def health() -> dict:
    mineru = check_mineru_local_health()
    status = "ok"
    if mineru["enabled"] and not mineru["reachable"]:
        status = "degraded"
    return {"status": status, "mineru_local": mineru}


app.include_router(task_router)
app.include_router(review_plus_router)
app.include_router(gnc_review_router)
app.include_router(review_workbench_router)
app.include_router(structuring_router)
app.include_router(parsing_router)
app.include_router(planning_router)
app.include_router(evaluation_router)
app.include_router(super_agent_router)


def main() -> None:
    import uvicorn

    uvicorn.run("data_agent.main:app", host="0.0.0.0", port=8088, reload=False)


if __name__ == "__main__":
    main()
