"""混合检索（B6）：向量检索 + BM25 → RRF 融合 → Reranker 接口预留 → 引用命中。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.logging import get_logger
from app.rag.bm25 import BM25Index
from app.rag.embedding import BaseEmbeddingProvider
from app.rag.store import FileVectorStore

logger = get_logger(__name__)


@dataclass
class RetrievedChunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    text: str
    source: str                      # 引用来源（文件名 § 标题/页码）
    vector_rank: int | None = None
    bm25_rank: int | None = None
    vector_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float = 0.0
    meta: dict = field(default_factory=dict)


class BaseReranker:
    """Reranker 接口预留（修订要求）：MVP 默认 Noop（RRF 序即最终序）。"""

    async def rerank(self, query: str, hits: list[RetrievedChunk], top_k: int) -> list[RetrievedChunk]:
        return hits[:top_k]


class NoopReranker(BaseReranker):
    pass


def rrf_fuse(vector_ranked: list[tuple[str, float]], bm25_ranked: list[tuple[str, float]],
             k: int = 60) -> dict[str, float]:
    """Reciprocal Rank Fusion：score = Σ 1/(k + rank)；rank 从 1 起。"""
    fused: dict[str, float] = {}
    for rank, (cid, _) in enumerate(vector_ranked, start=1):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    for rank, (cid, _) in enumerate(bm25_ranked, start=1):
        fused[cid] = fused.get(cid, 0.0) + 1.0 / (k + rank)
    return fused


class HybridRetriever:
    def __init__(self, store: FileVectorStore, provider: BaseEmbeddingProvider,
                 *, rrf_k: int = 60, candidate_k: int = 20,
                 reranker: BaseReranker | None = None) -> None:
        self.store = store
        self.provider = provider
        self.rrf_k = rrf_k
        self.candidate_k = candidate_k
        self.reranker = reranker or NoopReranker()
        self.bm25 = BM25Index()
        self._rebuild_bm25()

    def _rebuild_bm25(self) -> None:
        self.bm25.build({c.id: f"{c.doc_title}\n{c.text}" for c in self.store.all_chunks()})

    def notify_corpus_changed(self) -> None:
        self._rebuild_bm25()

    async def search(self, query: str, top_k: int = 5) -> list[RetrievedChunk]:
        if not query.strip():
            return []
        # 1) 向量路
        qvec = (await self.provider.embed_texts([query]))[0]
        vector_hits = await self.store.vector_search(qvec, top_k=self.candidate_k)
        vector_ranked = [(c.id, score) for c, score in vector_hits]
        # 2) BM25 路
        bm25_ranked = self.bm25.search(query, top_k=self.candidate_k)
        # 3) RRF 融合
        fused = rrf_fuse(vector_ranked, bm25_ranked, k=self.rrf_k)
        hits: list[RetrievedChunk] = []
        vmap = {c.id: (i + 1, score) for i, (c, score) in enumerate(vector_hits)}
        bmap = {cid: (i + 1, score) for i, (cid, score) in enumerate(bm25_ranked)}
        for cid, rrf_score in sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]:
            chunk = self.store.get(cid)
            if chunk is None:
                continue
            vr, vs = vmap.get(cid, (None, None))
            br, bs = bmap.get(cid, (None, None))
            hits.append(RetrievedChunk(
                chunk_id=chunk.id, doc_id=chunk.doc_id, doc_title=chunk.doc_title,
                text=chunk.text, source=chunk.source, meta=dict(chunk.meta),
                vector_rank=vr, vector_score=vs, bm25_rank=br, bm25_score=bs,
                rrf_score=rrf_score,
            ))
        # 4) Reranker 预留接口
        return await self.reranker.rerank(query, hits, top_k)
