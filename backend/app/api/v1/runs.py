"""runs 域路由（只读，B3 增加 SSE 流式端点）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import (
    CodeDiffListOut,
    ExecutionLogEventListOut,
    PlanOut,
    RunOut,
    TestResultListOut,
    ToolCallPage,
)
from app.services.runs import RunsService

router = APIRouter(prefix="/runs", tags=["runs"])


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: str, session: AsyncSession = Depends(get_db)) -> RunOut:
    return await RunsService(session).get_run(run_id)


@router.get("/{run_id}/plan", response_model=PlanOut | None)
async def get_run_plan(run_id: str, session: AsyncSession = Depends(get_db)) -> PlanOut | None:
    return await RunsService(session).get_plan(run_id)


@router.get("/{run_id}/tool-calls", response_model=ToolCallPage)
async def list_run_tool_calls(
    run_id: str,
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> ToolCallPage:
    return await RunsService(session).list_tool_calls(run_id, cursor)


@router.get("/{run_id}/diffs", response_model=CodeDiffListOut)
async def list_run_diffs(run_id: str, session: AsyncSession = Depends(get_db)) -> CodeDiffListOut:
    return await RunsService(session).list_diffs(run_id)


@router.get("/{run_id}/tests", response_model=TestResultListOut)
async def list_run_tests(run_id: str, session: AsyncSession = Depends(get_db)) -> TestResultListOut:
    return await RunsService(session).list_tests(run_id)


@router.get("/{run_id}/events", response_model=ExecutionLogEventListOut)
async def list_run_events(
    run_id: str,
    after: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> ExecutionLogEventListOut:
    """事件历史（JSON）。B3 在同路径提供 text/event-stream + Last-Event-ID。"""
    return await RunsService(session).list_events(run_id, after_seq=after)
