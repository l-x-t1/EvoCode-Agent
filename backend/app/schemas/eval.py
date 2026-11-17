"""eval 域 schema（B8）：与前端 types/api.ts EvalOverview/EvalModelCompare/EvalSkillDelta/EvalRun 对齐。

compression 端点前端暂无类型：形状 {items: [{runId, version, trigger, beforeTokens,
afterTokens, compressedAt}]}（context_snapshots 非 initial 行）。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.response import Page


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class EvalTrendPointOut(CamelModel):
    date: str
    overall: int
    by_type: dict[str, int] = {}


class EvalOverviewOut(CamelModel):
    range: str
    success_rate: float
    avg_duration_ms: int
    avg_cost_per_task: float
    compression_rate: float
    trend: list[EvalTrendPointOut] = []


class EvalModelCompareOut(CamelModel):
    model: str
    success_rate: float
    avg_duration_ms: int
    avg_cost: float
    sample_size: int


class EvalSkillDeltaOut(CamelModel):
    skill_id: str
    name: str
    before: float
    after: float
    delta: float
    sample_size: int


class CompressionItemOut(CamelModel):
    run_id: str
    version: int
    trigger: str
    before_tokens: int | None = None
    after_tokens: int | None = None
    compressed_at: datetime | None = None


class CompressionListOut(CamelModel):
    items: list[CompressionItemOut] = []


class EvalCaseOut(CamelModel):
    task_id: str
    title: str
    passed: bool
    tokens: int


class EvalRunOut(CamelModel):
    id: str
    suite: str
    task_count: int
    success_rate: float
    avg_tokens: int
    created_at: datetime
    cases: list[EvalCaseOut] = []


class EvalRunPage(Page[EvalRunOut]):
    """分页 {items,total,page,size}；cases 当前恒为空数组（eval_cases 未接入）。"""
