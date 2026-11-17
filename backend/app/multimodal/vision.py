"""多模态视觉客户端（B7）：OCR / 图片理解 / 图表问答三个分立能力。

设计要点（修订要求）：
- 三个能力**分别建模、分别验收**，不允许用一次图片理解调用代替全部：
  每个能力有独立的提示词契约与结构化输出 schema。
- 统一输入接口 MultimodalInput（bytes + mime），base64 data URL 传入
  chat/completions 的 image_url content part（OpenAI 兼容）。
- 真实 HTTP 实现（GLMVisionClient）；GLM_API_KEY 缺失时诚实抛
  model_unavailable。**真实图片验收待 key**（当前仅 MockTransport 契约测试）。
"""

from __future__ import annotations

import base64
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from app.core.config import get_settings
from app.core.exceptions import BizException
from app.core.logging import get_logger
from app.core.response import ErrorCode

logger = get_logger(__name__)

ALLOWED_MIME = ("image/png", "image/jpeg", "image/webp")


@dataclass
class MultimodalInput:
    filename: str
    data: bytes
    mime: str

    def validate(self, max_bytes: int) -> str:
        """输入校验：mime 白名单 + 大小上限。返回 data URL。"""
        if self.mime not in ALLOWED_MIME:
            raise BizException(ErrorCode.INVALID_REQUEST,
                               f"不支持的图片类型: {self.mime}（允许 {', '.join(ALLOWED_MIME)}）",
                               status_code=422)
        if len(self.data) > max_bytes:
            raise BizException(ErrorCode.INVALID_REQUEST,
                               f"图片超过大小上限 {max_bytes} 字节", status_code=422)
        if not self.data:
            raise BizException(ErrorCode.INVALID_REQUEST, "图片内容为空", status_code=422)
        return f"data:{self.mime};base64," + base64.b64encode(self.data).decode("ascii")


@dataclass
class OcrResult:
    """OCR：图片 → 文本（含区域定位与页码来源）。"""

    text: str
    regions: list[dict] = field(default_factory=list)   # [{page, lines:[...]}]
    language: str = ""
    raw: dict = field(default_factory=dict)


@dataclass
class UnderstandingResult:
    """图片理解：结构化描述（对象/场景/文字）。"""

    description: str
    objects: list[str] = field(default_factory=list)
    scene: str = ""
    text_found: str = ""                                # 图内文字（非 OCR 语义，仅识别到的文字）
    raw: dict = field(default_factory=dict)


@dataclass
class ChartQaResult:
    """图表问答：图表图片 + 问题 → 数据级回答（含读出的数值）。"""

    answer: str
    values: list[dict] = field(default_factory=list)    # [{series, label, value}]
    chart_type: str = ""
    raw: dict = field(default_factory=dict)


def _parse_json_block(text: str) -> dict:
    """与 llm.client.extract_json_block 同语义（局部复用避免跨包耦合）。"""
    from app.llm.client import extract_json_block

    return extract_json_block(text)


class BaseVisionClient(ABC):
    @abstractmethod
    async def ocr(self, image: MultimodalInput) -> OcrResult: ...

    @abstractmethod
    async def understand(self, image: MultimodalInput) -> UnderstandingResult: ...

    @abstractmethod
    async def chart_qa(self, image: MultimodalInput, question: str) -> ChartQaResult: ...


class GLMVisionClient(BaseVisionClient):
    """GLM vision 模型（glm-4v-plus 等）真实实现。三个能力三种提示词契约。"""

    OCR_SYSTEM = (
        "你是 OCR 引擎。提取图片中的全部文字，保持阅读顺序。只输出 JSON："
        '{"text": "全文纯文本（保留换行）", "regions": [{"page": 1, "lines": ["区域文字"]}], '
        '"language": "主要语言代码如 zh/en"}'
    )
    UNDERSTAND_SYSTEM = (
        "你是图片理解引擎。分析图片并只输出 JSON："
        '{"description": "一段完整描述", "objects": ["对象1", "对象2"], '
        '"scene": "场景一句话", "text_found": "图中出现的文字（没有则为空字符串）"}'
    )
    CHART_SYSTEM = (
        "你是图表分析引擎。根据图表图片和用户问题回答。只输出 JSON："
        '{"answer": "针对问题的数据级回答", '
        '"values": [{"series": "系列名", "label": "横轴标签", "value": 123}], '
        '"chart_type": "bar|line|pie|other"}'
    )

    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, timeout: int | None = None,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else str(settings.GLM_API_KEY)
        self._base_url = (base_url or settings.GLM_BASE_URL).rstrip("/")
        self._model = model or settings.GLM_VISION_MODEL
        self._timeout = timeout or settings.MULTIMODAL_TIMEOUT_SECONDS
        self._transport = transport

    # ------------------------------------------------------------------ 底层
    def _ensure_configured(self) -> None:
        if not self._api_key.strip():
            raise BizException(ErrorCode.MODEL_UNAVAILABLE,
                               "GLM_API_KEY 未配置，无法调用视觉模型", status_code=503)

    async def _chat_image(self, system: str, user_text: str, data_url: str) -> dict:
        settings = get_settings()
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "image_url",
                     "image_url": {"url": data_url}},
                    {"type": "text", "text": user_text},
                ]},
            ],
            "temperature": 0.1,
            "max_tokens": settings.LLM_MAX_TOKENS,
        }
        try:
            async with httpx.AsyncClient(base_url=self._base_url, timeout=self._timeout,
                                         transport=self._transport) as client:
                resp = await client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self._api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise BizException(ErrorCode.MODEL_UNAVAILABLE, "视觉模型调用超时",
                               status_code=504) from exc
        except httpx.HTTPError as exc:
            raise BizException(ErrorCode.MODEL_UNAVAILABLE, "视觉模型服务不可达",
                               status_code=503) from exc
        if resp.status_code >= 400:
            raise BizException(ErrorCode.MODEL_UNAVAILABLE,
                               f"视觉模型返回异常状态 {resp.status_code}", status_code=502)
        try:
            content = resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise BizException(ErrorCode.MODEL_UNAVAILABLE, "视觉模型响应格式异常",
                               status_code=502) from exc
        return _parse_json_block(content)

    # ------------------------------------------------------------------ 三能力
    async def ocr(self, image: MultimodalInput) -> OcrResult:
        self._ensure_configured()
        settings = get_settings()
        url = image.validate(settings.MULTIMODAL_MAX_IMAGE_BYTES)
        data = await self._chat_image(self.OCR_SYSTEM, "请提取图片中的全部文字。", url)
        return OcrResult(
            text=str(data.get("text", "")),
            regions=[r for r in data.get("regions", []) if isinstance(r, dict)],
            language=str(data.get("language", "")),
            raw=data,
        )

    async def understand(self, image: MultimodalInput) -> UnderstandingResult:
        self._ensure_configured()
        settings = get_settings()
        url = image.validate(settings.MULTIMODAL_MAX_IMAGE_BYTES)
        data = await self._chat_image(self.UNDERSTAND_SYSTEM, "请分析这张图片。", url)
        return UnderstandingResult(
            description=str(data.get("description", "")),
            objects=[str(o) for o in data.get("objects", []) if o],
            scene=str(data.get("scene", "")),
            text_found=str(data.get("text_found", "")),
            raw=data,
        )

    async def chart_qa(self, image: MultimodalInput, question: str) -> ChartQaResult:
        self._ensure_configured()
        settings = get_settings()
        url = image.validate(settings.MULTIMODAL_MAX_IMAGE_BYTES)
        data = await self._chat_image(self.CHART_SYSTEM, f"图表问题：{question}", url)
        return ChartQaResult(
            answer=str(data.get("answer", "")),
            values=[v for v in data.get("values", []) if isinstance(v, dict)],
            chart_type=str(data.get("chart_type", "other")),
            raw=data,
        )


def get_vision_client() -> GLMVisionClient:
    return GLMVisionClient()
