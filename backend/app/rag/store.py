"""向量库（B6）：VectorStore 协议 + 文件持久化实现。

- FileVectorStore：JSON 持久化（data/rag/store.json，原子写），余弦相似度检索。
  选型说明（如实声明）：任务文档允许「Chroma 或其他适合的向量数据库」；
  MVP 单进程语料规模下文件库足够，且避免引入 chromadb 重依赖与数据库迁移。
  ChromaVectorStore 为预留接口（B6 未实现，切换时调用方签名不变）。
- 文档重新向量化：reembed(provider) 全量重算并持久化（修订要求）。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.core.logging import get_logger
from app.rag.embedding import BaseEmbeddingProvider, cosine_similarity

logger = get_logger(__name__)


@dataclass
class StoredChunk:
    id: str
    doc_id: str
    doc_title: str
    index: int
    text: str
    source: str
    meta: dict = field(default_factory=dict)
    embedding: list[float] = field(default_factory=list)


class FileVectorStore:
    """JSON 文件持久化向量库（单进程 MVP；并发写由调用方保证）。"""

    def __init__(self, data_dir: str | Path) -> None:
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "store.json"
        self._chunks: dict[str, StoredChunk] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._chunks = {}
            return
        try:
            data = json.loads(self.path.read_text("utf-8"))
            self._chunks = {c["id"]: StoredChunk(**c) for c in data.get("chunks", [])}
        except (json.JSONDecodeError, TypeError, KeyError) as exc:
            logger.warning("向量库加载失败，按空库启动: %s", exc)
            self._chunks = {}

    def _save(self) -> None:
        """原子写：临时文件 + os.replace。"""
        payload = {"chunks": [asdict(c) for c in self._chunks.values()]}
        fd, tmp = tempfile.mkstemp(dir=str(self.dir), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except Exception:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    # ------------------------------------------------------------------ 操作
    def upsert(self, chunks: list[StoredChunk]) -> int:
        for c in chunks:
            self._chunks[c.id] = c
        self._save()
        return len(chunks)

    def delete_doc(self, doc_id: str) -> int:
        removed = [cid for cid, c in self._chunks.items() if c.doc_id == doc_id]
        for cid in removed:
            del self._chunks[cid]
        if removed:
            self._save()
        return len(removed)

    def all_chunks(self) -> list[StoredChunk]:
        return list(self._chunks.values())

    def get(self, chunk_id: str) -> StoredChunk | None:
        return self._chunks.get(chunk_id)

    def doc_ids(self) -> list[str]:
        return sorted({c.doc_id for c in self._chunks.values()})

    async def reembed(self, provider: BaseEmbeddingProvider) -> int:
        """文档重新向量化：全量 chunk 按当前 provider 重算（含维度校验）。"""
        chunks = list(self._chunks.values())
        if not chunks:
            return 0
        vectors = await provider.embed_texts([c.text for c in chunks])
        for c, vec in zip(chunks, vectors, strict=True):
            c.embedding = vec
        self._save()
        logger.info("重新向量化完成 n=%d provider=%s dim=%s", len(chunks),
                    provider.name, provider.dim)
        return len(chunks)

    async def vector_search(self, query_embedding: list[float], top_k: int = 5) -> list[tuple[StoredChunk, float]]:
        scored = []
        for c in self._chunks.values():
            if not c.embedding:
                continue
            scored.append((c, cosine_similarity(query_embedding, c.embedding)))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]
