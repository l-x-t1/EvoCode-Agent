"""Context / Memory 域响应模型（对齐前端 types/api.ts，docs/06 §2）。"""

from __future__ import annotations

from datetime import datetime

from app.schemas.common import CamelModel


class ContextSegmentOut(CamelModel):
    key: str  # system | skill | memory | history | working | compressed
    tokens: int


class CompressionEventOut(CamelModel):
    id: str
    reason: str
    trigger: str  # threshold | manual | routing
    beforeTokens: int | None = None
    afterTokens: int | None = None
    summaryId: str | None = None
    createdAt: str | None = None


class ContextSessionOut(CamelModel):
    """MVP：一个 run 一个上下文会话，id 即 runId（深链 /context/:runId）。"""

    id: str
    runId: str
    windowTokens: int
    usedTokens: int
    segments: list[ContextSegmentOut] = []
    compressionEvents: list[CompressionEventOut] = []
    updatedAt: datetime | None = None


class ContextSessionListOut(CamelModel):
    items: list[ContextSessionOut] = []


class HistorySummaryOut(CamelModel):
    id: str
    title: str
    content: str
    sourceTaskId: str
    refCount: int = 1
    createdAt: str | None = None


class HistorySummaryListOut(CamelModel):
    items: list[HistorySummaryOut] = []
