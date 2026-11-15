"""dashboard / agents / skills-events 路由（docs/06 §3.1）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.dashboard import (
    AgentStatusOut,
    DashboardSummaryOut,
    DashboardTrendsOut,
    SkillEventListOut,
)
from app.services.dashboard import DashboardService

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
async def dashboard_summary(session: AsyncSession = Depends(get_db)) -> DashboardSummaryOut:
    return await DashboardService(session).summary()


@router.get("/dashboard/trends", response_model=DashboardTrendsOut)
async def dashboard_trends(
    range: str = Query(default="7d", pattern="^(7d|14d|30d)$"),
    session: AsyncSession = Depends(get_db),
) -> DashboardTrendsOut:
    return await DashboardService(session).trends(range)


@router.get("/agents/status", response_model=AgentStatusOut)
async def agents_status(session: AsyncSession = Depends(get_db)) -> AgentStatusOut:
    return await DashboardService(session).agent_status()


@router.get("/skills/events", response_model=SkillEventListOut)
async def skill_events(
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> SkillEventListOut:
    return await DashboardService(session).skill_events(limit)
