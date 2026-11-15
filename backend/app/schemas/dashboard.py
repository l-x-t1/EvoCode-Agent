"""Dashboard / Agents / SkillEvents 响应模型（对齐前端 types/api.ts）。"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.common import CamelModel


class DashboardSummaryOut(CamelModel):
    tasks_total: int
    tasks_today: int
    tasks_running: int
    tokens_total: int
    tokens_today: int
    skill_count: int
    skill_evolutions: int
    success_rate: float


class TaskTrendPoint(CamelModel):
    date: str  # YYYY-MM-DD（UTC）
    created: int
    succeeded: int
    failed: int


class TokenTrendPoint(CamelModel):
    date: str
    glm53: int
    flash: int


class DashboardTrendsOut(CamelModel):
    range: str  # 7d | 14d | 30d
    task_trend: list[TaskTrendPoint] = []
    token_trend: list[TokenTrendPoint] = []


class AgentStatusItem(BaseModel):
    name: str
    value: int


class AgentStatusOut(CamelModel):
    total: int
    items: list[AgentStatusItem] = []


class SkillEventOut(CamelModel):
    """Skill 事件流（Dashboard）：由 skills/skill_versions/skill_candidates
    真实行派生（无独立事件表，避免改 schema）。"""

    id: str
    skill_id: str | None = None
    type: str  # proposed | approved | rejected | rolled_back | created
    message: str
    created_at: str  # ISO8601


class SkillEventListOut(CamelModel):
    items: list[SkillEventOut] = []
