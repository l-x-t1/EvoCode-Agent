"""GLM 客户端契约测试（httpx.MockTransport，无网络）。

覆盖：请求构造（URL/鉴权头/模型与消息体）、响应解析、错误映射、
JSON 提取、未配置 key 的诚实失败。真实 API 冒烟待 GLM_API_KEY（未完成项）。
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.core.exceptions import BizException
from app.llm.client import GLMClient, LLMMessage, extract_json_block


def _client(transport: httpx.AsyncBaseTransport, api_key: str = "test-key") -> GLMClient:
    return GLMClient(api_key=api_key, base_url="https://fake.open.bigmodel.cn/api/paas/v4",
                     timeout=5, transport=transport)


def _ok_body(model: str = "glm-5.3") -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": "你好，计划如下"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 34},
        "model": model,
    }


async def test_request_building_and_parsing():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json=_ok_body())

    client = _client(httpx.MockTransport(handler))
    resp = await client.chat(
        [LLMMessage(role="system", content="sys"), LLMMessage(role="user", content="hello")],
        model="glm-5.3-flash", temperature=0.5, max_tokens=100,
    )
    assert captured["url"].endswith("/chat/completions")
    assert captured["auth"] == "Bearer test-key"
    assert captured["body"]["model"] == "glm-5.3-flash"
    assert captured["body"]["temperature"] == 0.5
    assert captured["body"]["max_tokens"] == 100
    assert captured["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert resp.content == "你好，计划如下"
    assert resp.prompt_tokens == 12 and resp.completion_tokens == 34
    assert resp.model == "glm-5.3"
    assert resp.latency_ms >= 0


async def test_rate_limited_429():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate"})

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(BizException) as ei:
        await client.chat([LLMMessage(role="user", content="x")])
    assert ei.value.code == "rate_limited"


async def test_auth_failure_mapped():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "bad key"})

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(BizException) as ei:
        await client.chat([LLMMessage(role="user", content="x")])
    assert ei.value.code == "model_unavailable"
    assert "test-key" not in ei.value.message  # 不泄露密钥


async def test_server_error_mapped():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(BizException) as ei:
        await client.chat([LLMMessage(role="user", content="x")])
    assert ei.value.code == "model_unavailable"


async def test_network_error_mapped():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = _client(httpx.MockTransport(handler))
    with pytest.raises(BizException) as ei:
        await client.chat([LLMMessage(role="user", content="x")])
    assert ei.value.code == "model_unavailable"
    assert ei.value.status_code == 503


async def test_timeout_mapped():
    """httpx 的 AsyncClient 超时不作用于 MockTransport（超时在真实传输层实现），
    契约测试直接模拟 TimeoutException（与真实超时走同一错误映射分支）。"""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    client = _client(httpx.MockTransport(handler), api_key="k")
    with pytest.raises(BizException) as ei:
        await client.chat([LLMMessage(role="user", content="x")])
    assert ei.value.code == "model_unavailable"
    assert ei.value.status_code == 504


async def test_unconfigured_client_fails_honestly():
    client = GLMClient(api_key="", base_url="https://fake.example", transport=httpx.MockTransport(lambda r: None))
    with pytest.raises(BizException) as ei:
        await client.chat([LLMMessage(role="user", content="x")])
    assert ei.value.code == "model_unavailable"
    assert ei.value.status_code == 503


def test_extract_json_block_variants():
    assert extract_json_block('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json_block('前言 {"a": {"b": 2}} 后记') == {"a": {"b": 2}}
    assert extract_json_block('{"steps": [1, 2]}') == {"steps": [1, 2]}
    with pytest.raises(ValueError):
        extract_json_block("完全不是 JSON")
