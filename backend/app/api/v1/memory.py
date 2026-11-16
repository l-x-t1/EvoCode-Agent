"""memory 域路由（docs/06 §3.5：POST /memory/search）。

B6：混合检索 RAG 文档语料（向量+BM25+RRF）并融合 memory_items 关键词命中；
结果带引用来源（document § 文件名/段落 或 memory § layer）。
文档导入/重建向量化为服务层能力（scripts 与测试使用；上传端点随 B8 前端）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.context.manager import estimate_tokens
from app.models.context import MemoryItem
from app.rag.service import get_rag_service

router = APIRouter(prefix="/memory", tags=["memory"])


class MemorySearchIn(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    topK: int = Field(default=5, ge=1, le=20)
    layers: list[str] = Field(default_factory=list)  # core|episodic|semantic|procedural


@router.post("/search")
async def memory_search(
    body: MemorySearchIn,
    session: AsyncSession = Depends(get_db),
) -> dict:
    """混合检索：RAG 文档语料 + memory_items 关键词命中，RRF 排序、引用来源追踪。

    - document 命中：RagService（向量+BM25→RRF；Reranker 预留接口）
    - memory 命中：memory_items 内容关键词匹配（语义向量检索待 Chroma/B6+ 深化）
    layers 过滤仅作用于 memory 命中（文档命中不受 layers 影响）。
    """
    rag = get_rag_service()
    items: list[dict] = []

    # 1) 文档语料混合检索
    doc_hits = await rag.search(body.query, top_k=body.topK)
    for rank, h in enumerate(doc_hits, start=1):
        items.append({
            "source": "document",
            "id": h.chunk_id,
            "docId": h.doc_id,
            "title": h.doc_title,
            "citation": h.source,
            "content": h.text[:1200],
            "tokens": estimate_tokens(h.text),
            "score": h.score,
            "rank": rank,
        })

    # 2) memory_items 关键词命中（层过滤）
    layer_filter = [l for l in body.layers if l]
    if not layer_filter:
        layer_filter = ["core", "episodic", "semantic", "procedural"]
    rows = list((await session.execute(
        select(MemoryItem).where(MemoryItem.layer.in_(layer_filter))
        .order_by(MemoryItem.score.desc(), MemoryItem.created_at.desc())
        .limit(200)
    )).scalars().all())
    q = body.query.lower()
    matched = [m for m in rows if q in m.content.lower()][: body.topK]
    for rank, m in enumerate(matched, start=1):
        items.append({
            "source": "memory",
            "id": m.id,
            "docId": None,
            "title": f"记忆（{str(getattr(m.layer, 'value', m.layer))}）",
            "citation": f"memory:{str(getattr(m.layer, 'value', m.layer))}",
            "content": m.content[:1200],
            "tokens": estimate_tokens(m.content),
            "score": round(1.0 / (rank + 1), 6),
            "rank": len(doc_hits) + rank,
        })
    return {"query": body.query, "total": len(items), "items": items}
