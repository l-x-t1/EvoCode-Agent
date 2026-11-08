"""FastAPI 应用工厂 + lifespan（docs/08 §2）。

- lifespan：建立 DB/Redis 连接 → 服务请求 → 统一释放（开发约束：资源必须释放）
- CORS：白名单来自 ALLOWED_ORIGINS
- 异常出口统一 {"error":{...}}（docs/08 决策 #1）
- /healthz、/readyz 挂应用根（探针语义，非业务 API）
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import get_logger, setup_logging
from app.core.response import ErrorCode, ErrorBody, ErrorDetail
from app.db.redis import close_redis, init_redis
from app.db.session import dispose_engine, init_engine
from app.services import health as health_service

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:  #应用启动和关闭时的资源管理
    settings = get_settings()
    setup_logging(settings)
    init_engine(settings)
    init_redis(settings)
    logger.info("%s v%s 启动（env=%s）", settings.APP_NAME, settings.APP_VERSION, settings.ENV)
    yield
    await close_redis()
    await dispose_engine()
    logger.info("应用已关闭，连接已释放")


def create_app() -> FastAPI:       #负责创建和组装 FastAPI 应用
    settings = get_settings()
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    # CORS（配置驱动，不写死来源）
    app.add_middleware(
        CORSMiddleware,    #处理跨域访问
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/healthz", summary="存活探针（恒 200）", tags=["health"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get(
        "/readyz",
        summary="就绪探针（关键依赖不可用→503）",
        tags=["health"],
        response_model=None,
    )
    async def readyz() -> JSONResponse:
        ready, checks = await health_service.get_readiness()
        if not ready:
            body = ErrorBody(
                error=ErrorDetail(
                    code=ErrorCode.NOT_READY,
                    message="关键依赖不可用，服务未就绪",
                    details=checks,
                )
            )
            return JSONResponse(status_code=503, content=body.model_dump(exclude_none=True))
        return JSONResponse(status_code=200, content={"ready": True, "checks": checks})

    return app


app = create_app()
