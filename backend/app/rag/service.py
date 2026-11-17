"""RAG 服务（B6）：文档导入（解析→分块→嵌入→入库）/ 重新向量化 / 混合检索 / 引用。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.config import get_settings
from app.core.exceptions import BizException
from app.core.logging import get_logger
from app.core.response import ErrorCode
from app.rag import parsers
from app.rag.chunker import chunk_document
from app.rag.embedding import get_embedding_provider
from app.rag.retriever import HybridRetriever, RetrievedChunk
from app.rag.store import FileVectorStore, StoredChunk

logger = get_logger(__name__)


@dataclass
class ImportResult:
    doc_id: str
    filename: str
    title: str
    chunk_count: int
    warnings: list[str] = field(default_factory=list)


@dataclass
class SearchHit:
    chunk_id: str
    doc_id: str
    doc_title: str
    source: str          # 引用来源（修订要求：引用来源追踪）
    text: str
    score: float
    ranks: dict = field(default_factory=dict)


class RagService:
    """单例由 get_rag_service 提供；语料持久化在 RAG_DATA_DIR/store.json。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.store = FileVectorStore(settings.RAG_DATA_DIR)
        self.provider = get_embedding_provider()
        self.retriever = HybridRetriever(
            self.store, self.provider,
            rrf_k=settings.RAG_RRF_K, candidate_k=max(settings.RAG_TOPK * 3, 10),
        )

    # ------------------------------------------------------------------ 导入
    async def import_document(self, filename: str, data: bytes) -> ImportResult:
        """文档导入全链路：解析 → 分块 → 嵌入 → 入库。同名文档重复导入 = 覆盖重建。"""
        parsed = parsers.parse_document(filename, data)
        settings = get_settings()
        doc_id = filename.rsplit(".", 1)[0]
        chunks = chunk_document(parsed, max_chars=settings.RAG_CHUNK_CHARS,
                                overlap=settings.RAG_CHUNK_OVERLAP)
        if not chunks:
            raise BizException(ErrorCode.INVALID_REQUEST,
                               f"文档解析后无有效内容: {filename}", status_code=422)
        vectors = await self.provider.embed_texts([c.text for c in chunks])
        stored = [StoredChunk(
            id=c.id, doc_id=c.doc_id, doc_title=c.doc_title, index=c.index,
            text=c.text, source=c.source, meta=dict(c.meta), embedding=vec,
        ) for c, vec in zip(chunks, vectors, strict=True)]
        self.store.delete_doc(doc_id)
        self.store.upsert(stored)
        self.retriever.notify_corpus_changed()
        logger.info("文档导入完成 doc=%s chunks=%d provider=%s",
                    doc_id, len(stored), self.provider.name)
        return ImportResult(doc_id=doc_id, filename=filename, title=parsed.title,
                            chunk_count=len(stored), warnings=parsed.warnings)

    async def delete_document(self, doc_id: str) -> int:
        n = self.store.delete_doc(doc_id)
        self.retriever.notify_corpus_changed()
        return n

    async def reindex(self) -> int:
        """文档重新向量化（修订要求）：换模型/换维度后全量重算。"""
        # provider 可能在 key 配置后发生变化：刷新
        self.provider = get_embedding_provider()
        n = await self.store.reembed(self.provider)
        self.retriever.notify_corpus_changed()
        return n

    def stats(self) -> dict:
        return {"docs": len(self.store.doc_ids()), "chunks": len(self.store.all_chunks()),
                "provider": self.provider.name, "dim": self.provider.dim}

    # ------------------------------------------------------------------ 检索
    async def search(self, query: str, top_k: int | None = None) -> list[SearchHit]:
        settings = get_settings()
        k = top_k or settings.RAG_TOPK
        if not self.store.all_chunks():
            return []
        hits: list[RetrievedChunk] = await self.retriever.search(query, top_k=k)
        return [SearchHit(
            chunk_id=h.chunk_id, doc_id=h.doc_id, doc_title=h.doc_title,
            source=h.source, text=h.text, score=round(h.rrf_score, 6),
            ranks={"vectorRank": h.vector_rank, "bm25Rank": h.bm25_rank,
                   "vectorScore": h.vector_score, "bm25Score": h.bm25_score},
        ) for h in hits]


_rag_service: RagService | None = None


def get_rag_service() -> RagService:
    global _rag_service
    if _rag_service is None:
        _rag_service = RagService()
    return _rag_service


def reset_rag_service() -> None:
    """测试辅助：重建单例（数据目录变更后）。"""
    global _rag_service
    _rag_service = None
