"""健康检查响应模型（对齐前端 SystemHealth 类型，docs/06 §3.1）。"""

from __future__ import annotations

from pydantic import BaseModel


class DependencyHealth(BaseModel):
    status: str  # ok | error | disabled
    latencyMs: int


class McpDependencyHealth(BaseModel):
    name: str
    status: str
    latencyMs: int


class SystemHealth(BaseModel):
    api: DependencyHealth
    postgres: DependencyHealth
    redis: DependencyHealth
    chroma: DependencyHealth
    mcp: list[McpDependencyHealth]


class Readiness(BaseModel):
    ready: bool
    checks: dict[str, bool]
