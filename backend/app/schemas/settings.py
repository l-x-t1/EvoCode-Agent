"""Settings 五域响应模型（对齐前端 types/api.ts ModelSettings/SystemParams 等）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SettingsDomainValue(BaseModel):
    """域值统一以 JSON 对象/数组透传（PUT 只存不解释；GET 返回默认或已存值）。"""

    domain: str
    value: object


class ModelsTestOut(BaseModel):
    ok: bool
    model: str
    latencyMs: int | None = None
    error: str | None = None


class DiscoverOut(BaseModel):
    ok: bool
    error: str | None = None


class DomainPath(BaseModel):
    domain: str = Field(pattern="^(models|routing|mcp|permissions|system)$")
