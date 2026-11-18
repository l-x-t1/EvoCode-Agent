"""Evaluation 路由（B8）：全 SQL 真实聚合，零虚构。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.context import ContextSnapshot
from app.models.misc import ModelUsage
from app.models.skill import Skill, SkillEvaluation
from app.models.task import AgentRun, AgentTask
from app.schemas.eval import (
    EvalCompressionItemOut,
    EvalCompressionOut,
    EvalModelCompareOut,
    EvalOverviewOut,
    EvalRunOut,
    EvalRunPage,
    EvalSkillDeltaOut,
    EvalTrendPoint,
)

router = APIRouter(prefix="/eval", tags=["evaluation"])

_RANGES = {"7d": 7, "30d": 30, "90d": 90}


def _range_or_422(range: str) -> int:
    days = _RANGES.get(range)
    if days is None:
        from app.core.exceptions import BizException
        from app.core.response import ErrorCode

        raise BizException(ErrorCode.VALIDATION_ERROR,
                           f"range 仅支持 {', '.join(_RANGES)}", status_code=422)
    return days


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0) - timedelta(days=days - 1)


@router.get("/overview", response_model=EvalOverviewOut)
async def eval_overview(
    range_: str = Query(default="7d", alias="range", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> EvalOverviewOut:
    days = _range_or_422(range_)
    since = _since(days)
    counts = dict((await session.execute(
        select(AgentTask.status, func.count()).group_by(AgentTask.status)
    )).all())
    counts = {str(s): int(n) for s, n in counts.items()}
    completed = counts.get("completed", 0)
    failed = counts.get("failed", 0)
    terminal = completed + failed
    success_rate = round(completed / terminal, 4) if terminal else 0.0

    avg_duration = int((await session.execute(
        select(func.coalesce(func.avg(AgentRun.duration_ms), 0))
        .where(AgentRun.status == "completed", AgentRun.finished_at >= since)
    )).scalar_one())
    cost_total = float((await session.execute(
        select(func.coalesce(func.sum(ModelUsage.cost), 0))
        .where(ModelUsage.created_at >= since)
    )).scalar_one())
    tasks_total = sum(counts.values())
    avg_cost = round(cost_total / tasks_total, 6) if tasks_total else 0.0
    compressions = int((await session.execute(
        select(func.count()).select_from(ContextSnapshot)
        .where(ContextSnapshot.trigger != "initial", ContextSnapshot.created_at >= since)
    )).scalar_one())
    compression_rate = round(compressions / max(len((await session.execute(
        select(AgentRun.id))).scalars().all()), 1), 4)

    # 按日趋势（created/succeeded/failed，零填充）
    day = func.date_trunc("day", AgentTask.created_at).label("day")
    rows = (await session.execute(
        select(day,
               func.count().label("created"),
               func.sum(case((AgentTask.status == "failed", 1), else_=0)).label("failed"))
        .where(AgentTask.created_at >= since).group_by(day)
    )).all()
    by_date = {r.day.date().isoformat(): r for r in rows}
    trend = []
    for i in range(days):
        d = (_since(days) + timedelta(days=i)).date().isoformat()
        r = by_date.get(d)
        trend.append(EvalTrendPoint(
            date=d, overall=int(r.created) if r else 0,
            byType={"created": int(r.created) if r else 0,
                    "failed": int(r.failed or 0) if r else 0}))
    return EvalOverviewOut(
        range=range_, successRate=success_rate, avgDurationMs=avg_duration,
        avgCostPerTask=avg_cost, compressionRate=compression_rate, trend=trend)


@router.get("/models", response_model=list[EvalModelCompareOut])
async def eval_models(
    range: str = Query(default="30d", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> list[EvalModelCompareOut]:
    days = _range_or_422(range)
    rows = (await session.execute(
        select(AgentRun.model, func.count(), func.avg(AgentRun.duration_ms),
               func.sum(case((AgentRun.status == "completed", 1), else_=0)))
        .group_by(AgentRun.model)
    )).all()
    out: list[EvalModelCompareOut] = []
    for model, sample, avg_dur, succeeded in rows:
        cost = float((await session.execute(
            select(func.coalesce(func.sum(ModelUsage.cost), 0))
            .where(ModelUsage.run_id.in_(select(AgentRun.id).where(AgentRun.model == model)))
        )).scalar_one())
        out.append(EvalModelCompareOut(
            model=str(model), sampleSize=int(sample),
            successRate=round(float(succeeded or 0) / int(sample), 4) if sample else 0.0,
            avgDurationMs=int(avg_dur or 0), avgCost=round(cost / int(sample), 6) if sample else 0.0))
    return out


@router.get("/skills", response_model=list[EvalSkillDeltaOut])
async def eval_skills(
    range: str = Query(default="30d", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> list[EvalSkillDeltaOut]:
    _range_or_422(range)
    rows = (await session.execute(
        select(SkillEvaluation, Skill.name).join(Skill, SkillEvaluation.skill_id == Skill.id)
        .order_by(SkillEvaluation.created_at.desc())
    )).all()
    return [EvalSkillDeltaOut(
        skillId=e.skill_id, name=name, before=float(e.before_score),
        after=float(e.after_score), delta=round(float(e.after_score) - float(e.before_score), 4),
        sampleSize=e.sample_size) for e, name in rows]


@router.get("/compression", response_model=EvalCompressionOut)
async def eval_compression(
    range: str = Query(default="30d", pattern="^(7d|30d|90d)$"),
    session: AsyncSession = Depends(get_db),
) -> EvalCompressionOut:
    days = _range_or_422(range)
    rows = (await session.execute(
        select(ContextSnapshot)
        .where(ContextSnapshot.trigger != "initial", ContextSnapshot.created_at >= _since(days))
        .order_by(ContextSnapshot.compressed_at.desc())
        .limit(50)
    )).scalars().all()
    return EvalCompressionOut(items=[EvalCompressionItemOut(
        runId=s.run_id, version=s.version, trigger=str(s.trigger.value),
        beforeTokens=s.before_tokens, afterTokens=s.after_tokens,
        compressedAt=s.compressed_at.isoformat() if s.compressed_at else None,
    ) for s in rows])


@router.get("/runs", response_model=EvalRunPage)
async def eval_runs(
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> EvalRunPage:
    """评测批次：eval_runs 表当前无写入路径（评测器属后续批次），如实返回空。"""
    from app.models.evaluation import EvalRun as EvalRunModel  # 评测批次表（写入属后续批次）

    try:
        total = (await session.execute(
            select(func.count()).select_from(EvalRunModel))).scalar_one()
    except Exception:  # noqa: BLE001 - 表不存在/未启用时如实返回空
        return EvalRunPage(items=[], total=0, page=page, size=size)
    if total == 0:
        return EvalRunPage(items=[], total=0, page=page, size=size)
    rows = list((await session.execute(
        select(EvalRunModel).offset((page - 1) * size).limit(size))).scalars().all())
    return EvalRunPage(items=[EvalRunOut(
        id=r.id, suite=r.suite, taskCount=r.task_count, successRate=float(r.success_rate),
        avgTokens=r.avg_tokens, createdAt=r.created_at.isoformat() if r.created_at else None)
        for r in rows], total=int(total), page=page, size=size)
