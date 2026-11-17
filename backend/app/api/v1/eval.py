"""eval 域路由（B8）：overview / models / skills / compression / runs。

全部真实 SQL 聚合（date_trunc UTC 日风格与 dashboard repo 一致），零虚构：
- eval_runs 当前为空表 → /eval/runs 如实返回 items=[]、total=0
- compression：context_snapshots 非 initial 行（前端暂无类型，形状见 schemas/eval.py）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.context import ContextSnapshot
from app.models.evaluation import EvalRun
from app.models.misc import ModelUsage
from app.models.skill import Skill, SkillEvaluation
from app.models.task import AgentRun, AgentTask
from app.schemas.eval import (
    CompressionItemOut,
    CompressionListOut,
    EvalModelCompareOut,
    EvalOverviewOut,
    EvalRunPage,
    EvalRunOut,
    EvalSkillDeltaOut,
    EvalTrendPointOut,
)

router = APIRouter(prefix="/eval", tags=["eval"])

_RANGE_DAYS = {"7d": 7, "30d": 30, "90d": 90}


def _window_start(range_key: str) -> datetime:
    days = _RANGE_DAYS[range_key]
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ) - timedelta(days=days - 1)


def _trend_points(rows: list[Any], days: int, start: datetime) -> list[EvalTrendPointOut]:
    by_date = {r.day.date().isoformat(): r for r in rows}
    out: list[EvalTrendPointOut] = []
    for i in range(days):
        d = (start + timedelta(days=i)).date().isoformat()
        r = by_date.get(d)
        out.append(
            EvalTrendPointOut(
                date=d,
                overall=int(r.created) if r else 0,
                by_type={
                    "created": int(r.succeeded or 0) if r else 0,
                    "failed": int(r.failed or 0) if r else 0,
                },
            )
        )
    return out


@router.get("/overview", response_model=EvalOverviewOut)
async def eval_overview(
    range: str = Query(default="7d", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> EvalOverviewOut:
    start = _window_start(range)
    days = _RANGE_DAYS[range]

    counts = {
        str(s): int(n)
        for s, n in (
            await session.execute(
                select(AgentTask.status, func.count())
                .where(AgentTask.created_at >= start)
                .group_by(AgentTask.status)
            )
        ).all()
    }
    completed, failed = counts.get("completed", 0), counts.get("failed", 0)
    terminal = completed + failed
    success_rate = round(completed / terminal, 4) if terminal else 0.0

    task_count = int(
        (
            await session.execute(
                select(func.count()).select_from(AgentTask).where(AgentTask.created_at >= start)
            )
        ).scalar_one()
    )
    run_count = int(
        (
            await session.execute(
                select(func.count()).select_from(AgentRun).where(AgentRun.created_at >= start)
            )
        ).scalar_one()
    )

    avg_duration = (
        await session.execute(
            select(func.avg(AgentRun.duration_ms))
            .where(AgentRun.created_at >= start, AgentRun.status == "completed")
        )
    ).scalar_one()
    avg_duration_ms = int(round(float(avg_duration))) if avg_duration is not None else 0

    cost_sum = (
        await session.execute(
            select(func.coalesce(func.sum(ModelUsage.cost), 0)).where(ModelUsage.created_at >= start)
        )
    ).scalar_one()
    avg_cost = float(cost_sum) / task_count if task_count else 0.0

    compressed = int(
        (
            await session.execute(
                select(func.count())
                .select_from(ContextSnapshot)
                .where(ContextSnapshot.created_at >= start, ContextSnapshot.trigger != "initial")
            )
        ).scalar_one()
    )
    compression_rate = round(compressed / max(run_count, 1), 4)

    day = func.date_trunc("day", AgentTask.created_at).label("day")
    trend_rows = (
        await session.execute(
            select(
                day,
                func.count().label("created"),
                func.sum(case((AgentTask.status == "completed", 1), else_=0)).label("succeeded"),
                func.sum(case((AgentTask.status == "failed", 1), else_=0)).label("failed"),
            )
            .where(AgentTask.created_at >= start)
            .group_by(day)
        )
    ).all()

    return EvalOverviewOut(
        range=range,
        success_rate=success_rate,
        avg_duration_ms=avg_duration_ms,
        avg_cost_per_task=round(avg_cost, 6),
        compression_rate=compression_rate,
        trend=_trend_points(trend_rows, days, start),
    )


@router.get("/models", response_model=list[EvalModelCompareOut])
async def eval_models(
    range: str = Query(default="7d", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> list[EvalModelCompareOut]:
    start = _window_start(range)
    rows = (
        await session.execute(
            select(
                AgentRun.model,
                func.count().label("sample_size"),
                func.sum(case((AgentRun.status == "completed", 1), else_=0)).label("completed"),
                func.avg(AgentRun.duration_ms).label("avg_duration"),
            )
            .where(AgentRun.created_at >= start)
            .group_by(AgentRun.model)
        )
    ).all()
    cost_rows = {
        r.model: float(r.cost_sum or 0)
        for r in (
            await session.execute(
                select(
                    AgentRun.model,
                    func.coalesce(func.sum(ModelUsage.cost), 0).label("cost_sum"),
                )
                .join(ModelUsage, ModelUsage.run_id == AgentRun.id, isouter=True)
                .where(AgentRun.created_at >= start)
                .group_by(AgentRun.model)
            )
        ).all()
    }
    out: list[EvalModelCompareOut] = []
    for r in rows:
        n = int(r.sample_size)
        out.append(
            EvalModelCompareOut(
                model=str(r.model),
                success_rate=round(int(r.completed or 0) / n, 4) if n else 0.0,
                avg_duration_ms=int(round(float(r.avg_duration))) if r.avg_duration is not None else 0,
                avg_cost=round(cost_rows.get(str(r.model), 0.0) / n, 6) if n else 0.0,
                sample_size=n,
            )
        )
    return out


@router.get("/skills", response_model=list[EvalSkillDeltaOut])
async def eval_skills(
    range: str = Query(default="7d", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> list[EvalSkillDeltaOut]:
    start = _window_start(range)
    rows = (
        await session.execute(
            select(SkillEvaluation, Skill.name)
            .join(Skill, SkillEvaluation.skill_id == Skill.id)
            .where(SkillEvaluation.created_at >= start)
            .order_by(SkillEvaluation.created_at.desc())
        )
    ).all()
    out: list[EvalSkillDeltaOut] = []
    for ev, name in rows:
        before, after = float(ev.before_score), float(ev.after_score)
        out.append(
            EvalSkillDeltaOut(
                skill_id=ev.skill_id,
                name=name,
                before=before,
                after=after,
                delta=round(after - before, 4),
                sample_size=int(ev.sample_size),
            )
        )
    return out


@router.get("/compression", response_model=CompressionListOut)
async def eval_compression(
    range: str = Query(default="7d", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> CompressionListOut:
    start = _window_start(range)
    rows = (
        await session.execute(
            select(ContextSnapshot)
            .where(ContextSnapshot.created_at >= start, ContextSnapshot.trigger != "initial")
            .order_by(ContextSnapshot.compressed_at.desc().nullslast(), ContextSnapshot.created_at.desc())
            .limit(200)
        )
    ).scalars().all()
    return CompressionListOut(
        items=[
            CompressionItemOut(
                run_id=s.run_id,
                version=int(s.version),
                trigger=str(s.trigger),
                before_tokens=s.before_tokens,
                after_tokens=s.after_tokens,
                compressed_at=s.compressed_at,
            )
            for s in rows
        ]
    )


@router.get("/runs", response_model=EvalRunPage)
async def eval_runs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> EvalRunPage:
    total = int(
        (
            await session.execute(select(func.count()).select_from(EvalRun))
        ).scalar_one()
    )
    rows = (
        await session.execute(
            select(EvalRun)
            .order_by(EvalRun.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).scalars().all()
    return EvalRunPage(
        items=[
            EvalRunOut(
                id=r.id,
                suite=r.suite,
                task_count=int(r.task_count),
                success_rate=float(r.success_rate),
                avg_tokens=int(r.avg_tokens),
                created_at=r.created_at,
                cases=[],  # eval_cases 未接入，如实返回空数组
            )
            for r in rows
        ],
        total=total,
        page=page,
        size=size,
    )
