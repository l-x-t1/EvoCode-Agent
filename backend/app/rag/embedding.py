"""Embedding Provider 抽象（B6，修订要求：独立于主对话模型）。

- BaseEmbeddingProvider：name / dim / embed_texts(list[str]) -> list[list[float]]
- GLMEmbeddingProvider：open.bigmodel.cn OpenAI 兼容 /embeddings 真实实现；
  **接口未经实测（GLM_API_KEY 缺失）**，本批以 httpx.MockTransport 契约测试
  覆盖请求构造/响应解析/错误映射；真实调用冒烟列为未完成项。
- HashingEmbeddingProvider：确定性本地兜底（字符 2-gram 哈希 → 固定维度，
  L2 归一化）。**仅保证离线可用与可复现，不具备语义检索质量**——用于
  单元测试与 GLM key 就绪前的开发环境，如实标注，不冒充语义检索。

选择逻辑（get_embedding_provider）：优先 GLM（key 已配置），否则 Hashing
兜底（日志如实告警）。向量维度管理：provider.dim 声明，store 重建时校验。
"""

from __future__ import annotations

import hashlib
import math
import time
from abc import ABC, abstractmethod

import httpx

from app.core.config import get_settings
from app.core.exceptions import BizException
from app.core.logging import get_logger
from app.core.response import ErrorCode

logger = get_logger(__name__)


class BaseEmbeddingProvider(ABC):
    name: str = "base"
    dim: int = 0

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]: ...


class HashingEmbeddingProvider(BaseEmbeddingProvider):
    """确定性字符 2-gram 哈希嵌入（离线兜底/测试用；非语义质量，如实声明）。"""

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @property
    def name(self) -> str:  # noqa: D102
        return f"hashing-{self.dim}"

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        vectors = []
        for text in texts:
            vec = [0.0] * self.dim
            t = text.strip().lower()
            grams = [t[i : i + 2] for i in range(max(0, len(t) - 1))] or ([t] if t else [])
            for g in grams:
                h = int(hashlib.md5(g.encode("utf-8")).hexdigest(), 16)
                vec[h % self.dim] += 1.0
                vec[(h >> 32) % self.dim] += 0.5   # 双槽降低碰撞
            norm = math.sqrt(sum(x * x for x in vec)) or 1.0
            vectors.append([x / norm for x in vec])
        return vectors


class GLMEmbeddingProvider(BaseEmbeddingProvider):
    """open.bigmodel.cn /embeddings（OpenAI 兼容）。未实测：key 缺失（如实声明）。"""

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, dim: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else str(settings.GLM_API_KEY)
        self._base_url = (base_url or settings.GLM_BASE_URL).rstrip("/")
        self._model = model or settings.GLM_EMBEDDING_MODEL
        self.dim = dim or settings.GLM_EMBEDDING_DIM
        self._transport = transport

    @property
    def name(self) -> str:
        return f"glm-{self._model}"

    def _ensure_configured(self) -> None:
        if not self._api_key.strip():
            raise BizException(ErrorCode.MODEL_UNAVAILABLE,
                               "GLM_API_KEY 未配置，无法调用 embedding 接口", status_code=503)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self._ensure_configured()
        if not texts:
            return []
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=30,
                                         transport=self._transport) as client:
                resp = await client.post(
                    "/embeddings",
                    headers={"Authorization": f"Bearer {self._api_key}",
                             "Content-Type": "application/json"},
                    json={"model": self._model, "input": texts, "dimensions": self.dim},
                )
        except httpx.HTTPError as exc:
            logger.warning("embedding 调用失败: %s", exc)
            raise BizException(ErrorCode.MODEL_UNAVAILABLE, "embedding 服务不可达",
                               status_code=503) from exc
        latency = int((time.perf_counter() - start) * 1000)
        if resp.status_code >= 400:
            raise BizException(ErrorCode.MODEL_UNAVAILABLE,
                               f"embedding 返回异常状态 {resp.status_code}", status_code=502)
        data = resp.json()
        try:
            vectors = [item["embedding"] for item in data["data"]]
        except (KeyError, TypeError) as exc:
            raise BizException(ErrorCode.MODEL_UNAVAILABLE, "embedding 响应格式异常",
                               status_code=502) from exc
        if len(vectors) != len(texts):
            raise BizException(ErrorCode.MODEL_UNAVAILABLE,
                               f"embedding 数量不匹配 {len(vectors)} != {len(texts)}",
                               status_code=502)
        logger.info("embedding 完成 n=%d dim=%s latency=%dms", len(texts),
                    len(vectors[0]) if vectors else 0, latency)
        return vectors


def get_embedding_provider() -> BaseEmbeddingProvider:
    """Provider 选择：GLM（key 已配置）优先，否则确定性哈希兜底（如实告警）。"""
    settings = get_settings()
    if str(settings.GLM_API_KEY).strip():
        return GLMEmbeddingProvider()
    provider = HashingEmbeddingProvider()
    logger.warning("GLM_API_KEY 未配置，RAG 使用 Hashing 兜底嵌入（非语义质量，仅离线可用）")
    return provider


def cosine_similarity(a: list[float], b: list[float]) -> float:
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return num / (na * nb)
