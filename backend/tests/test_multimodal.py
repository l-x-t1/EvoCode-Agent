"""多模态测试（B7）：三能力 MockTransport 契约测试 + 输入校验 + OCR→RAG 关联。

真实图片验收（≥3 种截图 OCR、图表数值读取等）依赖 GLM_API_KEY，如实挂起。
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio

from app.core.config import get_settings
from app.core.exceptions import BizException
from app.multimodal.vision import GLMVisionClient, MultimodalInput
from app.rag.service import get_rag_service, reset_rag_service

PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfake-image-bytes").decode()


def _client(handler) -> GLMVisionClient:
    return GLMVisionClient(api_key="k", base_url="https://fake.example/v4",
                           model="glm-4v-plus", timeout=5,
                           transport=httpx.MockTransport(handler))


def _chat_handler(content: dict):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [
            {"message": {"content": json.dumps(content, ensure_ascii=False)}}]})
    return handler


def _inp(mime: str = "image/png") -> MultimodalInput:
    return MultimodalInput(filename="shot.png", data=b"\x89PNGfake", mime=mime)


# ── OCR ──────────────────────────────────────────────

async def test_ocr_contract_and_parsing():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content.decode("utf-8"))
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "text": "登录成功\n用户名：admin",
            "regions": [{"page": 1, "lines": ["登录成功", "用户名：admin"]}],
            "language": "zh"}, ensure_ascii=False)}}]})

    client = _client(handler)
    result = await client.ocr(_inp())
    assert captured["auth"] == "Bearer k"
    assert captured["body"]["model"] == "glm-4v-plus"
    part = captured["body"]["messages"][1]["content"][0]
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
    assert part["type"] == "image_url"
    assert result.text == "登录成功\n用户名：admin"
    assert result.regions[0]["lines"] == ["登录成功", "用户名：admin"]
    assert result.language == "zh"


# ── 图片理解 ──────────────────────────────────────────

async def test_understand_contract():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "description": "一张服务器监控仪表盘截图，含 CPU 曲线",
            "objects": ["仪表盘", "折线图", "菜单栏"], "scene": "运维监控页面",
            "text_found": "CPU 75%"}, ensure_ascii=False)}}]})

    result = await _client(handler).understand(_inp())
    assert "仪表盘" in result.description
    assert result.objects == ["仪表盘", "折线图", "菜单栏"]
    assert result.scene == "运维监控页面"
    assert result.text_found == "CPU 75%"


# ── 图表问答 ──────────────────────────────────────────

async def test_chart_qa_contract_with_values():
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode("utf-8"))
        assert body["messages"][1]["content"][1]["text"] == "图表问题：第二季度销售额是多少"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
            "answer": "第二季度销售额为 128 万元",
            "values": [{"series": "销售额", "label": "Q2", "value": 128}],
            "chart_type": "bar"}, ensure_ascii=False)}}]})

    result = await _client(handler).chart_qa(_inp(), "第二季度销售额是多少")
    assert result.answer == "第二季度销售额为 128 万元"
    assert result.values[0]["value"] == 128
    assert result.chart_type == "bar"


# ── 输入校验与诚实失败 ────────────────────────────────

async def test_input_validation():
    # 未配置 key：诚实 model_unavailable（在任何输入校验之前）
    unconfigured = GLMVisionClient(api_key="", base_url="https://fake.example")
    with pytest.raises(BizException) as ei:
        await unconfigured.ocr(_inp())
    assert ei.value.code == "model_unavailable"
    # 已配置：mime 白名单 / 空内容 / 大小上限依次校验
    client = GLMVisionClient(api_key="k", base_url="https://fake.example")
    with pytest.raises(BizException) as ei:
        await client.understand(MultimodalInput("x.gif", b"data", "image/gif"))
    assert ei.value.code == "invalid_request"
    with pytest.raises(BizException) as ei:
        await client.understand(MultimodalInput("x.png", b"", "image/png"))
    assert ei.value.code == "invalid_request"
    with pytest.raises(BizException) as ei:
        await client.ocr(MultimodalInput("big.png", b"x" * 5_000_001, "image/png"))
    assert "上限" in ei.value.message


# ── OCR → RAG 关联 ────────────────────────────────────

async def test_ocr_and_index_app_client(app_client: AsyncClient, deps_available: bool,
                                        tmp_path):
    """OCR 文字导入 RAG 语料并可被 /memory/search 命中（图片与文档关联）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    reset_rag_service()
    settings = get_settings()
    old_dir = settings.RAG_DATA_DIR
    settings.RAG_DATA_DIR = str(tmp_path)

    ocr_content = {"text": "部署检查清单：1. 确认数据库迁移已执行 2. 灰度 5% 流量",
                   "regions": [{"page": 1, "lines": ["部署检查清单"]}], "language": "zh"}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [
            {"message": {"content": json.dumps(ocr_content, ensure_ascii=False)}}]})

    # 注入带 key 的客户端（MockTransport）
    import app.api.v1.multimodal as mm

    original_factory = mm.get_vision_client
    vision = _client(handler)
    try:
        import app.api.v1.multimodal as mm

        mm.get_vision_client = lambda: vision
        r = await app_client.post("/api/v1/multimodal/ocr-and-index", json={
            "filename": "deploy-checklist.png", "dataBase64": PNG_B64, "mime": "image/png"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["ocr"]["text"].startswith("部署检查清单")
        assert body["indexed"]["chunkCount"] >= 1
        # 图片文字已入 RAG 语料：可检索命中（图片与文档关联）
        r2 = await app_client.post("/api/v1/memory/search",
                                   json={"query": "灰度 流量", "topK": 3})
        hits = [i for i in r2.json()["items"] if i["source"] == "document"
                and i["docId"].startswith("deploy-checklist")]
        assert hits, "OCR 导入的文档应可检索命中"
    finally:
        mm.get_vision_client = original_factory
        settings.RAG_DATA_DIR = old_dir
        reset_rag_service()


async def test_ocr_empty_text_rejected(app_client: AsyncClient, deps_available: bool, tmp_path):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    reset_rag_service()
    settings = get_settings()
    old_dir = settings.RAG_DATA_DIR
    settings.RAG_DATA_DIR = str(tmp_path)
    try:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                "text": "", "regions": [], "language": "zh"})}}]})

        import app.api.v1.multimodal as mm

        original_factory = mm.get_vision_client
        mm.get_vision_client = lambda: _client(handler)
        r = await app_client.post("/api/v1/multimodal/ocr-and-index", json={
            "filename": "blank.png", "dataBase64": PNG_B64, "mime": "image/png"})
        assert r.status_code == 422
        assert r.json()["error"]["code"] == "invalid_request"
    finally:
        mm.get_vision_client = original_factory
        settings.RAG_DATA_DIR = old_dir
        reset_rag_service()

