"""dashboard / agents 路由（docs/06 §3.1）。

Skill 事件流（/skills/events）自 B5 起由 skills 路由提供（支持 skillId 过滤），
此处不再重复注册——同名路由先注册者优先，会吞掉 skillId 参数导致过滤失效。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.dashboard import (
    AgentStatusOut,
    DashboardSummaryOut,
    DashboardTrendsOut,
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
