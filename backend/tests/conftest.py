"""pytest 公共夹具。

- app_client：带 lifespan 的 AsyncClient（lifespan 中初始化 engine/redis）
- 若 PG/Redis 可用则集成断言走 ok 分支；不可用则跳过集成用例（如实跳过，不造假）
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from app.main import app as fastapi_app
from app.services import health as health_service


@pytest_asyncio.fixture
async def app_client() -> AsyncIterator[AsyncClient]:
    async with LifespanManager(fastapi_app):
        async with AsyncClient(
            transport=ASGITransport(app=fastapi_app), base_url="http://testserver"
        ) as client:
            yield client


@pytest.fixture
async def deps_available() -> bool:
    """PG 与 Redis 是否同时可用（决定集成用例执行或跳过）。"""
    ready, _ = await health_service.get_readiness()
    return ready


@pytest.fixture(scope="session")
def anyio_backend() -> str:
    return "asyncio"
