"""LLM 客户端（B3）：GLM open.bigmodel.cn OpenAI 兼容协议真实实现。

- 真实 HTTP 调用（httpx.AsyncClient），无任何模拟返回值；
- GLM_API_KEY 只从环境变量读取（SensitiveStr），不入日志；
- 未配置 key 时不假装可用：调用即抛 model_unavailable（BizException）；
- 测试策略：状态机单测注入 FakeLLM（见 tests/test_orchestrator.py），
  本模块的协议行为用 httpx.MockTransport 做契约测试（tests/test_llm_client.py），
  真实 API 冒烟在密钥配置后执行（当前记录为未完成项）。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings
from app.core.exceptions import BizException
from app.core.logging import get_logger
from app.core.response import ErrorCode

logger = get_logger(__name__)


@dataclass
class LLMMessage:
    role: str  # system | user | assistant
    content: str


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    raw: dict = field(default_factory=dict)


class BaseLLMClient(ABC):
    """Provider 抽象：换模型服务商只换实现（B6 Embedding Provider 同思路）。"""

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse: ...


def extract_json_block(text: str) -> dict[str, Any]:
    """从模型输出提取 JSON 对象：优先 ```json 围栏，其次首个平衡 {} 段。"""
    import json
    import re

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidates: list[str] = []
    if fence:
        candidates.append(fence.group(1))
    start = text.find("{")
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : i + 1])
                    break
    for c in candidates:
        try:
            obj = json.loads(c)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    raise ValueError(f"模型输出不是合法 JSON 对象: {text[:200]!r}")


class GLMClient(BaseLLMClient):
    """open.bigmodel.cn /chat/completions（OpenAI 兼容）。"""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else str(settings.GLM_API_KEY)
        self._base_url = (base_url or settings.GLM_BASE_URL).rstrip("/")
        self._timeout = timeout or settings.LLM_TIMEOUT_SECONDS
        self._transport = transport  # 仅测试注入（MockTransport）

    @property
    def configured(self) -> bool:
        return bool(self._api_key.strip())

    def _ensure_configured(self) -> None:
        if not self.configured:
            raise BizException(
                ErrorCode.MODEL_UNAVAILABLE,
                "GLM_API_KEY 未配置，无法调用真实模型（请在 backend/.env 配置后重启）",
                status_code=503,
            )

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMResponse:
        self._ensure_configured()
        settings = get_settings()
        payload = {
            "model": model or settings.GLM_MODEL,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": settings.LLM_TEMPERATURE if temperature is None else temperature,
            "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(
                base_url=self._base_url, timeout=self._timeout, transport=self._transport
            ) as client:
                resp = await client.post("/chat/completions", json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            logger.warning("LLM 调用超时: %s", exc)
            raise BizException(
                ErrorCode.MODEL_UNAVAILABLE, "模型调用超时", status_code=504
            ) from exc
        except httpx.HTTPError as exc:
            logger.warning("LLM 网络错误: %s", exc)
            raise BizException(
                ErrorCode.MODEL_UNAVAILABLE, "模型服务不可达", status_code=503
            ) from exc
        latency = int((time.perf_counter() - start) * 1000)

        if resp.status_code == 429:
            raise BizException(ErrorCode.RATE_LIMITED, "模型限流", status_code=429)
        if resp.status_code in (401, 403):
            # 不回显 key，只报语义
            raise BizException(
                ErrorCode.MODEL_UNAVAILABLE, "模型鉴权失败（检查 GLM_API_KEY）", status_code=502
            )
        if resp.status_code >= 400:
            raise BizException(
                ErrorCode.MODEL_UNAVAILABLE,
                f"模型返回异常状态 {resp.status_code}",
                status_code=502,
            )
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
            usage = data.get("usage", {})
            out = LLMResponse(
                content=content,
                model=data.get("model", payload["model"]),
                prompt_tokens=int(usage.get("prompt_tokens", 0)),
                completion_tokens=int(usage.get("completion_tokens", 0)),
                latency_ms=latency,
                raw=data,
            )
        except (KeyError, IndexError, TypeError) as exc:
            raise BizException(
                ErrorCode.MODEL_UNAVAILABLE, "模型响应格式异常", status_code=502
            ) from exc
        logger.info(
            "LLM 调用完成 model=%s tokens=%d+%d latency=%dms",
            out.model, out.prompt_tokens, out.completion_tokens, out.latency_ms,
        )
        return out


def get_llm_client() -> GLMClient:
    return GLMClient()
