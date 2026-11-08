"""统一错误体测试（docs/08 决策 #1）：所有错误出口必须是 {"error":{...}}。"""

from __future__ import annotations

from httpx import AsyncClient


async def test_404_error_envelope(app_client: AsyncClient):
    r = await app_client.get("/nonexistent")
    assert r.status_code == 404
    body = r.json()
    assert set(body.keys()) == {"error"}
    assert body["error"]["code"] == "not_found"
    assert "message" in body["error"]


async def test_422_validation_error_envelope(app_client: AsyncClient):
    # 触发查询参数校验失败：P1 无参数接口，用不存在的方法探测 405 也走错误体
    r = await app_client.post("/healthz")
    assert r.status_code == 405
    body = r.json()
    assert body["error"]["code"] == "invalid_request"


async def test_success_is_bare_entity(app_client: AsyncClient):
    """成功响应为裸实体（无 {code,data} 包装）。"""
    r = await app_client.get("/healthz")
    assert "error" not in r.json()
    assert "code" not in r.json()
