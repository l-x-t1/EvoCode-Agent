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
from app.core.logging import get_logger,setup_logging
from app.core.metrics import record_request_latency
from app.core.response import ErrorCode, ErrorBody, ErrorDetail
from app.db.redis import close_redis, init_redis
from app.db.session import dispose_engine, init_engine
from app.services import health as health_service

logger = get_logger(__name__)


@asynccontextmanager  #实现生命周期管理
async def lifespan(_: FastAPI) -> AsyncIterator[None]:  #应用启动和关闭时的资源管理
    settings = get_settings()
    setup_logging(settings)
    init_engine(settings)
    init_redis(settings)
    logger.info("%s v%s 启动（env=%s）", settings.APP_NAME, settings.APP_VERSION, settings.ENV)
    yield   #上面是应用启动时，下面是应用关闭时执行
    await close_redis()
    await dispose_engine()
    logger.info("应用已关闭，连接已释放")


def create_app() -> FastAPI:       #负责创建和组装 FastAPI 应用
    settings = get_settings()
    is_dev = settings.is_dev
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        lifespan=lifespan,
        # ENV=prod 不暴露交互式文档与 OpenAPI（修订要求）
        docs_url="/docs" if is_dev else None,
        openapi_url="/openapi.json" if is_dev else None,
    )

    # CORS（配置驱动，不写死来源；headers 收窄到实际使用的白名单）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=[
            "content-type",
            "authorization",
            "idempotency-key",
            "last-event-id",
            "x-request-id",
        ],
    )

    @app.middleware("http")
    async def _measure_latency(request, call_next):
        """真实请求延迟度量（供 /api/v1/health 的 api.latencyMs 使用）。"""
        import time as _time

        start = _time.perf_counter()
        response = await call_next(request)
        record_request_latency(int((_time.perf_counter() - start) * 1000))
        return response

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
