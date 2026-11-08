"""健康检查业务层：聚合各依赖探针结果（路由不直接触碰连接对象）。"""

from __future__ import annotations

import time

from app.core.logging import get_logger
from app.db.redis import probe_redis
from app.db.session import probe_database
from app.schemas.health import (
    DependencyHealth,
    McpDependencyHealth,
    SystemHealth,
)

logger = get_logger(__name__)

_CHROMA_NOTE = "chroma 未启用（P3 引入依赖）"


def _probe_chroma() -> DependencyHealth:
    """Chroma P3 才启用：如实报告 disabled，不虚构连接状态。"""
    return DependencyHealth(status="disabled", latencyMs=0)


async def get_system_health() -> SystemHealth:
    """各依赖状态 + 延迟；恒 200，故障体现在子项（前端按子项渲染）。"""
    start = time.perf_counter()
    api_latency = int((time.perf_counter() - start) * 1000)

    pg_ok, pg_latency = await probe_database()
    redis_ok, redis_latency = await probe_redis()

    return SystemHealth(
        api=DependencyHealth(status="ok", latencyMs=api_latency),
        postgres=DependencyHealth(status="ok" if pg_ok else "error", latencyMs=pg_latency),
        redis=DependencyHealth(status="ok" if redis_ok else "error", latencyMs=redis_latency),
        chroma=_probe_chroma(),
        # MCP servers P3 接入；当前为空列表（前端健康面板按 mcp 数组渲染）
        mcp=[],
    )


async def get_readiness() -> tuple[bool, dict[str, bool]]:
    """就绪探针：关键依赖（PG/Redis）任一不可用 → not ready（路由层转 503）。"""
    pg_ok, _ = await probe_database()
    redis_ok, _ = await probe_redis()
    checks = {"postgres": pg_ok, "redis": redis_ok}
    ready = all(checks.values())
    if not ready:
        logger.warning("就绪检查未通过: %s", checks)
    return ready, checks
