"""RAG 测试（B6）：嵌入 Provider 契约 / BM25+RRF / 混合检索端到端 / 重向量化 / API。

Embedding 说明：GLM 真实接口用 MockTransport 契约测试（key 缺失未实测，如实记录）；
端到端检索用 Hashing 兜底 provider（确定性，可断言检索命中）。
"""

from __future__ import annotations

import json

import json
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.exceptions import BizException
from app.db.session import get_session_factory
from app.rag.bm25 import BM25Index
from app.rag.chunker import chunk_document
from app.rag.embedding import GLMEmbeddingProvider, HashingEmbeddingProvider, get_embedding_provider
from app.rag.parsers import parse_document
from app.rag.retriever import HybridRetriever, rrf_fuse
from app.rag.service import RagService, reset_rag_service
from app.rag.store import FileVectorStore, StoredChunk
from app.rag.types import DocBlock, ParsedDocument


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


# ── Embedding Provider ────────────────────────────────

async def test_glm_embedding_request_contract():
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        captured["body"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"data": [
            {"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]})

    p = GLMEmbeddingProvider(api_key="k", base_url="https://fake.example/v4",
                             model="embedding-3", dim=1024, transport=httpx.MockTransport(handler))
    vecs = await p.embed_texts(["你好", "世界"])
    assert captured["url"].endswith("/embeddings")
    assert captured["auth"] == "Bearer k"
    assert captured["body"]["model"] == "embedding-3"
    assert captured["body"]["input"] == ["你好", "世界"]
    assert len(vecs) == 2 and vecs[0] == [0.1, 0.2, 0.3]


async def test_glm_embedding_unconfigured_honest():
    p = GLMEmbeddingProvider(api_key="", base_url="https://fake.example",
                             transport=httpx.MockTransport(lambda r: None))
    with pytest.raises(BizException) as ei:
        await p.embed_texts(["x"])
    assert ei.value.code == "model_unavailable"


async def test_hashing_provider_deterministic():
    p = HashingEmbeddingProvider(dim=256)
    v1 = (await p.embed_texts(["数据库连接池配置"]))[0]
    v2 = (await p.embed_texts(["数据库连接池配置"]))[0]
    assert v1 == v2                                   # 确定性
    assert len(v1) == 256
    assert abs(sum(x * x for x in v1) - 1.0) < 1e-6   # L2 归一化


async def test_provider_selection_fallback_without_key():
    if str(get_settings().GLM_API_KEY).strip():
        pytest.skip("GLM_API_KEY 已配置，兜底选择用例不适用")
    p = get_embedding_provider()
    assert isinstance(p, HashingEmbeddingProvider)    # 无 key → 如实兜底


# ── BM25 / RRF ────────────────────────────────────────

def test_bm25_ranking_sanity():
    idx = BM25Index()
    idx.build({
        "c1": "PostgreSQL 连接池配置说明 pool_size 参数",
        "c2": "Redis 缓存策略与过期时间",
        "c3": "数据库连接池与超时重试",
    })
    hits = idx.search("连接池 配置", top_k=2)
    assert len(hits) == 2
    assert {h[0] for h in hits} == {"c1", "c3"}       # 相关文档命中，c2 不在
    assert hits[0][1] >= hits[1][1]


def test_rrf_fusion_both_routes():
    fused = rrf_fuse([("a", 0.9), ("b", 0.8)], [("b", 3.2), ("c", 2.1)], k=60)
    assert fused["b"] > fused["a"] >= 0               # 双路命中得分最高
    assert fused["c"] > 0


# ── 解析 + 分块 + 端到端检索 ──────────────────────────

def _sample_md() -> bytes:
    return (
        "# 数据库运维手册\n\n## 连接池\n\nPostgreSQL 连接池默认 pool_size=5，"
        "推荐按并发调整。\n\n## 备份策略\n\n每日全量备份，保留 7 天。\n"
    ).encode("utf-8")


async def test_import_and_hybrid_search_end_to_end(tmp_path):
    """导入 → 混合检索 → 引用命中正确文档与段落（Hashing provider，确定性）。"""
    reset_rag_service()
    import app.core.config as cfg_mod

    settings = get_settings()
    old_dir = settings.RAG_DATA_DIR
    settings.RAG_DATA_DIR = str(tmp_path)
    try:
        svc = RagService()
        r1 = await svc.import_document("db-ops.md", _sample_md())
        assert r1.chunk_count >= 1 and r1.warnings == []
        await svc.import_document("redis-notes.md",
                                  "# Redis\n\n缓存使用 LRU 策略。\n".encode("utf-8"))
        assert svc.stats()["docs"] == 2

        hits = await svc.search("连接池 pool_size")
        assert hits, "应命中连接池文档"
        top = hits[0]
        assert top.doc_id == "db-ops"                     # 引用来源追踪
        assert "连接池" in top.source
        assert "pool_size" in top.text
        assert top.ranks["vectorRank"] is not None or top.ranks["bm25Rank"] is not None

        hits2 = await svc.search("备份策略 保留几天")
        assert hits2 and hits2[0].doc_id == "db-ops"
        assert "备份" in hits2[0].text
        # 无关语料检索其它主题
        hits3 = await svc.search("Redis LRU")
        assert hits3 and hits3[0].doc_id == "redis-notes"
    finally:
        settings.RAG_DATA_DIR = old_dir
        reset_rag_service()


async def test_reembed_and_store_persistence(tmp_path):
    """文档重新向量化 + 文件库持久化（跨实例加载）。"""
    reset_rag_service()
    settings = get_settings()
    old_dir = settings.RAG_DATA_DIR
    settings.RAG_DATA_DIR = str(tmp_path)
    try:
        svc = RagService()
        await svc.import_document("notes.md", "# 笔记\n\n持久化验证内容。\n".encode("utf-8"))
        n = await svc.reindex()                            # 重算（Hashing 确定性）
        assert n >= 1
        # 新实例从磁盘加载（持久化验证）
        svc2 = RagService()
        assert svc2.stats()["docs"] == svc.stats()["docs"]
        hits = await svc2.search("持久化验证")
        assert hits and "持久化" in hits[0].text
    finally:
        settings.RAG_DATA_DIR = old_dir
        reset_rag_service()


async def test_memory_search_api_fuses_docs_and_memory(app_client: AsyncClient, deps_available: bool,
                                                       tmp_path):
    """/memory/search：文档命中 + memory_items 关键词命中融合，引用来源明确。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    reset_rag_service()
    settings = get_settings()
    old_dir = settings.RAG_DATA_DIR
    settings.RAG_DATA_DIR = str(tmp_path)
    try:
        svc = RagService()
        await svc.import_document("team-handbook.md",
                                  "# 团队手册\n\n发版流程：合并主干后自动部署 staging。\n".encode("utf-8"))
        from app.models.context import MemoryItem

        factory = get_session_factory()
        async with factory() as session:
            session.add(MemoryItem(layer="episodic", content="团队约定：周五禁止发版",
                                   source_task_id=None, score=0.9, created_at=datetime.now(timezone.utc)))
            await session.commit()
        r = await app_client.post("/api/v1/memory/search", json={"query": "发版", "topK": 5})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] >= 2
        sources = {i["source"] for i in body["items"]}
        assert {"document", "memory"} <= sources
        doc_hit = next(i for i in body["items"] if i["source"] == "document")
        assert "staging" in doc_hit["content"] and doc_hit["citation"].startswith("team-handbook.md")
        mem_hit = next(i for i in body["items"] if i["source"] == "memory")
        assert "周五" in mem_hit["content"]
        r2 = await app_client.post("/api/v1/memory/search",
                                   json={"query": "发版", "topK": 5, "layers": ["core"]})
        assert all(i["source"] != "memory" or "episodic" not in i["citation"]
                   for i in r2.json()["items"])  # layers 过滤生效（core 不含该 episodic 记忆）
    finally:
        settings.RAG_DATA_DIR = old_dir
        reset_rag_service()


# ── 解析/分块冒烟（详细用例在 test_rag_parsers.py）────

def test_parse_and_chunk_smoke():
    parsed = parse_document("sample.md", _sample_md())
    assert parsed.title == "数据库运维手册"   # md 首个 heading 优先（解析层契约）
    assert any(b.type == "heading" and b.level == 1 for b in parsed.blocks)
    chunks = chunk_document(parsed, max_chars=800, overlap=50)
    assert chunks and all(c.text for c in chunks)
    assert len({c.id for c in chunks}) == len(chunks)
