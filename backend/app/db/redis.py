"""Redis 连接管理（docs/08 §2 db）。

与 session.py 同风格：惰性建连、lifespan 释放、探针吞异常。
"""

from __future__ import annotations

import time

import redis.asyncio as aioredis
from redis.asyncio import Redis

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis: Redis | None = None


def init_redis(settings: Settings) -> Redis:
    global _redis
    if _redis is not None:
        return _redis
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=3,
        socket_timeout=3,
    )
    logger.info("Redis 客户端已初始化（不主动建连）")
    return _redis


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        logger.info("Redis 连接已释放")
    _redis = None


def get_redis() -> Redis:
    if _redis is None:
        raise RuntimeError("Redis 未初始化（lifespan 未执行或初始化失败）")
    return _redis


async def probe_redis() -> tuple[bool, int]:
    """健康探针：PING 并测量耗时。返回 (ok, latency_ms)。"""
    if _redis is None:
        return False, 0
    start = time.perf_counter()
    try:
        await _redis.ping()
        latency = int((time.perf_counter() - start) * 1000)
        return True, latency
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis 探针失败: %s", exc)
        return False, int((time.perf_counter() - start) * 1000)
