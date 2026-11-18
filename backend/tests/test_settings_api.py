"""settings 域 API 测试（B8）：默认值形状 / PUT 回读 / 422 / 冒烟 / key 不泄露 / 501。"""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.db.session import get_session_factory
from app.llm.client import LLMResponse

pytest_asyncio.fixture(autouse=True)


@pytest_asyncio.fixture(autouse=True)
async def db_stack():
    from app.db.redis import close_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    settings = get_settings()
    init_engine(settings)
    init_redis(settings)
    yield
    await close_redis()
    await dispose_engine()


MODEL_KEYS = {"keyMasked", "baseUrl", "models"}
MODEL_ENTRY_KEYS = {"id", "temperature", "maxTokens", "enabled"}
SYSTEM_KEYS = {"contextWindowTokens", "compressionThreshold", "maxRetries", "sandboxEnabled",
               "maxConcurrency"}


async def test_default_shapes(app_client: AsyncClient, deps_available: bool):
    """五域默认值形状（routing/mcp/permissions 测试从不 PUT → 恒为内置默认）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/settings/routing")
    assert r.status_code == 200
    assert r.json() == []

    r = await app_client.get("/api/v1/settings/mcp")
    assert r.status_code == 200
    assert r.json() == {"servers": []}

    r = await app_client.get("/api/v1/settings/permissions")
    assert r.status_code == 200
    assert r.json() == []

    r = await app_client.get("/api/v1/settings/system")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == SYSTEM_KEYS
    assert all(isinstance(v, (int, bool)) for v in body.values())

    r = await app_client.get("/api/v1/settings/models")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == MODEL_KEYS
    assert body["baseUrl"] == get_settings().GLM_BASE_URL
    assert isinstance(body["models"], list) and len(body["models"]) >= 1
    assert all(set(m.keys()) == MODEL_ENTRY_KEYS for m in body["models"])
    key = str(get_settings().GLM_API_KEY).strip()
    assert body["keyMasked"] == ("未配置" if not key else "***" + key[-4:])


async def test_put_get_roundtrip(app_client: AsyncClient, deps_available: bool):
    """PUT 任意 JSON 对象 → 返回存储值；GET 回读一致（models 域 keyMasked 实时覆盖）。

    用例后清理本测试写入的 settings 行（与 test_context 约定一致），避免污染其它用例。
    """
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    try:
        system_payload = {"contextWindowTokens": 32000, "compressionThreshold": 24000,
                          "maxRetries": 2, "sandboxEnabled": False, "maxConcurrency": 1}
        r = await app_client.put("/api/v1/settings/system", json=system_payload)
        assert r.status_code == 200
        assert r.json() == system_payload
        g = await app_client.get("/api/v1/settings/system")
        assert g.status_code == 200
        assert g.json() == system_payload

        models_payload = {"keyMasked": "raw-key-should-not-persist",
                          "baseUrl": get_settings().GLM_BASE_URL,
                          "models": [{"id": "glm-5.3", "temperature": 0.2, "maxTokens": 4096,
                                      "enabled": True}]}
        r = await app_client.put("/api/v1/settings/models", json=models_payload)
        assert r.status_code == 200
        # keyMasked 以服务端掩码为准（PUT 不接受/不回显客户端传值），
        # 与本用例 GET 断言及实现 docstring 的既定设计一致。
        put_key = str(get_settings().GLM_API_KEY).strip()
        expected_put_masked = "未配置" if not put_key else "***" + put_key[-4:]
        assert r.json() == {**models_payload, "keyMasked": expected_put_masked}
        g = await app_client.get("/api/v1/settings/models")
        body = g.json()
        key = str(get_settings().GLM_API_KEY).strip()
        expected_masked = "未配置" if not key else "***" + key[-4:]
        assert body["keyMasked"] == expected_masked != models_payload["keyMasked"]
        assert body["baseUrl"] == models_payload["baseUrl"]
        assert body["models"] == models_payload["models"]
    finally:
        from sqlalchemy import delete

        from app.models.misc import Setting

        factory = get_session_factory()
        async with factory() as session:
            await session.execute(delete(Setting).where(Setting.key.in_(["system", "models"])))
            await session.commit()


async def test_invalid_domain_422(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/settings/unknown")
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    r2 = await app_client.put("/api/v1/settings/unknown", json={})
    assert r2.status_code == 422


async def test_models_test_without_key(app_client: AsyncClient, monkeypatch):
    """当前环境 GLM_API_KEY 为空 → HTTP 200 携带 ok=false（monkeypatch 保证无 key 分支）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "GLM_API_KEY", "")
    r = await app_client.post("/api/v1/settings/models/test")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"ok", "model", "latencyMs", "error"}
    assert body["ok"] is False
    assert body["model"] == settings.GLM_MODEL
    assert "GLM_API_KEY 未配置" in body["error"]
    assert body["latencyMs"] is None


async def test_models_test_with_stub_client(app_client: AsyncClient, monkeypatch):
    """有 key 分支（注入 Fake GLMClient）：ok=true + latencyMs；调用失败 → ok=false 不抛异常。"""

    class FakeOkClient:
        configured = True

        async def chat(self, messages, **kw):
            return LLMResponse(content="ok", model="glm-5.3", latency_ms=42)

    class FakeFailClient:
        configured = True

        async def chat(self, messages, **kw):
            raise BizException(ErrorCode.MODEL_UNAVAILABLE, "模型服务不可达", status_code=503)

    monkeypatch.setattr("app.api.v1.settings.get_llm_client", lambda: FakeOkClient())
    r = await app_client.post("/api/v1/settings/models/test")
    assert r.status_code == 200
    body = r.json()
    # 实现为真实墙钟计时（不消费 stub 的 latency_ms 字段），只断言存在且为非负整数
    assert isinstance(body["latencyMs"], int) and body["latencyMs"] >= 0
    body.pop("latencyMs")
    assert body == {"ok": True, "model": "glm-5.3", "error": None}

    monkeypatch.setattr("app.api.v1.settings.get_llm_client", lambda: FakeFailClient())
    r2 = await app_client.post("/api/v1/settings/models/test")
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["ok"] is False
    assert body2["error"] == "模型服务不可达"
    assert body2["latencyMs"] is None


async def test_key_masked_no_leak(app_client: AsyncClient, deps_available: bool):
    """响应体任何位置都不含 GLM_API_KEY 原文。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/settings/models")
    assert r.status_code == 200
    key = str(get_settings().GLM_API_KEY).strip()
    if key:
        assert key not in r.text
        assert r.json()["keyMasked"].startswith("***")
    else:
        assert r.json()["keyMasked"] == "未配置"
    masked = r.json()["keyMasked"]
    assert masked == "未配置" or masked.startswith("***")


async def test_mcp_discover_501(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.post("/api/v1/settings/mcp/srv-1/discover")
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "mcp_unavailable"
