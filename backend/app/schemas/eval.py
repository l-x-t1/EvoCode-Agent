"""Evaluation 响应模型（对齐前端 types/api.ts EvalOverview/ModelCompare/SkillDelta/EvalRun）。"""

from __future__ import annotations

from pydantic import BaseModel


class EvalTrendPoint(BaseModel):
    date: str
    overall: int
    byType: dict[str, int]


class EvalOverviewOut(BaseModel):
    range: str
    successRate: float
    avgDurationMs: int
    avgCostPerTask: float
    compressionRate: float
    trend: list[EvalTrendPoint] = []


class EvalModelCompareOut(BaseModel):
    model: str
    successRate: float
    avgDurationMs: int
    avgCost: float
    sampleSize: int


class EvalSkillDeltaOut(BaseModel):
    skillId: str
    name: str
    before: float
    after: float
    delta: float
    sampleSize: int


class EvalCompressionItemOut(BaseModel):
    runId: str
    version: int
    trigger: str
    beforeTokens: int | None = None
    afterTokens: int | None = None
    compressedAt: str | None = None


class EvalCompressionOut(BaseModel):
    items: list[EvalCompressionItemOut] = []


class EvalRunCaseOut(BaseModel):
    taskId: str
    title: str
    passed: bool
    tokens: int


class EvalRunOut(BaseModel):
    id: str
    suite: str
    taskCount: int
    successRate: float
    avgTokens: int
    createdAt: str | None = None
    cases: list[EvalRunCaseOut] = []


class EvalRunPage(BaseModel):
    items: list[EvalRunOut] = []
    total: int = 0
    page: int = 1
    size: int = 20
