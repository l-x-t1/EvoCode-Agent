"""统一响应约定（docs/08 §1 决策 #1）。

- 成功：裸实体 JSON（**无全局包装**）
- 失败：{"error": {"code": "...", "message": "...", "details"?: ...}}
- 分页：{"items": [...], "total": n, "page": n, "size": n}
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: object | None = None


class ErrorBody(BaseModel):
    error: ErrorDetail


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    size: int


# 错误码常量（docs/06 §1）
class ErrorCode:
    INVALID_REQUEST = "invalid_request"
    VALIDATION_ERROR = "validation_error"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    NOT_READY = "not_ready"
    RATE_LIMITED = "rate_limited"
    MODEL_UNAVAILABLE = "model_unavailable"
    INTERNAL = "internal"
