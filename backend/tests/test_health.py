"""健康检查接口测试（docs/08 §6 完成标准 3/4）。

- 结构与语义不依赖依赖是否在线
- 集成断言（ok 分支）在 PG/Redis 可用时才执行，否则显式跳过
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_healthz(app_client: AsyncClient):
    r = await app_client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_health_shape(app_client: AsyncClient):
    r = await app_client.get("/api/v1/health")
    assert r.status_code == 200
    body = r.json()
    # 前端 SystemHealth 契约：五个键 + camelCase 延迟字段
    assert set(body.keys()) == {"api", "postgres", "redis", "chroma", "mcp"}
    for dep in ("api", "postgres", "redis", "chroma"):
        assert set(body[dep].keys()) == {"status", "latencyMs"}, f"{dep} 字段形状错误"
        assert body[dep]["status"] in ("ok", "error", "disabled")
    assert isinstance(body["mcp"], list)
    assert body["api"]["status"] == "ok"  # API 自身必然存活
    assert body["chroma"]["status"] == "disabled"  # P1 未启用，如实报告


async def test_readyz_semantics(app_client: AsyncClient, deps_available: bool):
    r = await app_client.get("/readyz")
    body = r.json()
    if deps_available:
        assert r.status_code == 200
        assert body["ready"] is True
    else:
        # 依赖不可用：503 + 统一错误体（docs/08 §4）
        assert r.status_code == 503
        assert body["error"]["code"] == "not_ready"
        assert set(body["error"]["details"].keys()) == {"postgres", "redis"}


async def test_health_integration_when_deps_up(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动（docker compose 未运行），集成断言跳过")
    r = await app_client.get("/api/v1/health")
    body = r.json()
    assert body["postgres"]["status"] == "ok"
    assert body["redis"]["status"] == "ok"
    assert body["postgres"]["latencyMs"] < 1000
