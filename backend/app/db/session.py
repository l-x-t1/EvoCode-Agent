"""PostgreSQL 异步连接管理（docs/08 §2 db）。

- engine 惰性建连：启动不依赖 DB 存活，健康检查如实报告
- lifespan 负责建立与释放（开发约束：必须支持异常处理和资源释放）
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

engine: AsyncEngine | None = None
session_factory: async_sessionmaker[AsyncSession] | None = None


def init_engine(settings: Settings) -> AsyncEngine:
    """创建 engine 与 session 工厂（幂等；重复调用先释放旧连接）。"""
    global engine, session_factory
    if engine is not None:
        return engine
    engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_pre_ping=True,  # 断连自愈
        pool_size=settings.DB_POOL_SIZE,
        pool_recycle=1800,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    logger.info("数据库 engine 已初始化（不主动建连）")
    return engine


async def dispose_engine() -> None:
    """释放连接池（lifespan shutdown 调用）。"""
    global engine, session_factory
    if engine is not None:
        await engine.dispose()
        logger.info("数据库连接池已释放")
    engine = None
    session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if session_factory is None:
        raise RuntimeError("数据库未初始化（lifespan 未执行或初始化失败）")
    return session_factory


async def db_session() -> AsyncIterator[AsyncSession]:
    """请求级 session：异常回滚，finally 释放。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def probe_database() -> tuple[bool, int]:
    """健康探针：SELECT 1 并测量耗时。返回 (ok, latency_ms)。"""
    if engine is None:
        return False, 0
    start = time.perf_counter()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency = int((time.perf_counter() - start) * 1000)
        return True, latency
    except Exception as exc:  # noqa: BLE001 - 健康检查必须吞掉异常并如实报告
        logger.warning("数据库探针失败: %s", exc)
        return False, int((time.perf_counter() - start) * 1000)
