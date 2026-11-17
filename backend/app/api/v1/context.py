"""context 域路由（docs/06 §3.5 子集；memory/search 属 RAG，B6 提供）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.context.manager import ContextManager
from app.models.task import AgentRun, AgentTask
from app.schemas.context import (
    ContextSessionListOut,
    ContextSessionOut,
    HistorySummaryListOut,
    HistorySummaryOut,
)

router = APIRouter(prefix="/context", tags=["context"])


@router.get("/sessions", response_model=ContextSessionListOut)
async def list_context_sessions(
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> ContextSessionListOut:
    """每个 run 一个上下文会话（按 run 创建时间倒序）。"""
    runs = list((await session.execute(
        select(AgentRun).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(limit)
    )).scalars().all())
    mgr = ContextManager(session)
    items = []
    for run in runs:
        task = await session.get(AgentTask, run.task_id)
        if task is None:
            continue
        items.append(ContextSessionOut(**await mgr.session_view(run, task)))
    return ContextSessionListOut(items=items)


@router.get("/sessions/{session_id}", response_model=ContextSessionOut)
async def get_context_session(
    session_id: str,
    session: AsyncSession = Depends(get_db),
) -> ContextSessionOut:
    """session_id 即 runId；不存在的 run → 404（统一错误体）。"""
    run = await session.get(AgentRun, session_id)
    if run is None:
        raise BizException(ErrorCode.NOT_FOUND, f"上下文会话不存在: {session_id}", status_code=404)
    task = await session.get(AgentTask, run.task_id)
    mgr = ContextManager(session)
    return ContextSessionOut(**await mgr.session_view(run, task))


@router.get("/summaries", response_model=HistorySummaryListOut)
async def list_summaries(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> HistorySummaryListOut:
    """压缩摘要列表：由 context_snapshots（含 summary）派生，cursor 按快照 id 倒序翻页。"""
    from app.models.context import ContextSnapshot

    stmt = (
        select(ContextSnapshot)
        .where(ContextSnapshot.summary.is_not(None))
        .order_by(ContextSnapshot.id.desc())
    )
    if cursor:
        stmt = stmt.where(ContextSnapshot.id < cursor)
    snaps = list((await session.execute(stmt.limit(limit))).scalars().all())
    items: list[HistorySummaryOut] = []
    for s in snaps:
        run = await session.get(AgentRun, s.run_id)
        task = await session.get(AgentTask, run.task_id) if run else None
        items.append(HistorySummaryOut(
            id=s.id,
            title=(task.title if task else "未知任务")[:120],
            content=s.summary or "",
            sourceTaskId=run.task_id if run else "",
            refCount=1,
            createdAt=s.compressed_at.isoformat() if s.compressed_at else None,
        ))
    return HistorySummaryListOut(items=items)
