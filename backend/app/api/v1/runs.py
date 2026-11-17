"""runs 域路由（只读；B3 在同路径提供 JSON / SSE 双形态事件端点）。

GET /runs/{run_id}/events 内容协商：
- 无 Accept: text/event-stream（含默认 */*）→ JSON ExecutionLogEventListOut（B1 行为不变）
- Accept 含 text/event-stream → text/event-stream 流：
  * 起点 seq = Last-Event-ID 头（非法/缺失 → query after，缺省 0）
  * 先补发 seq>起点 的历史事件（seq 升序），再每 SSE_POLL_SECONDS 轮询新事件推流
  * 静默超过 SSE_HEARTBEAT_SECONDS 发一帧 ": ping" 心跳（计时基于最后一条新事件时刻）
  * run 终态且无新事件 → 再等一轮确认后优雅关闭；客户端断开静默退出
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.core.exceptions import BizException
from app.core.logging import get_logger
from app.core.response import ErrorCode
from app.db.session import get_session_factory
from app.models.execution import AgentExecutionLog
from app.models.task import AgentRun
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
logger = get_logger(__name__)

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _sse_frame(run_id: str, event_type: str, seq: int, payload: dict, created_at: datetime) -> str:
    """一帧 SSE（前端冻结契约）：event: <type>\\nid: <seq>\\ndata: <信封JSON>\\n\\n。"""
    envelope = {
        "v": 1,
        "seq": seq,
        "ts": created_at.isoformat(),
        "runId": run_id,
        "payload": payload,
    }
    data = json.dumps(envelope, ensure_ascii=False, default=str)
    return f"event: {event_type}\nid: {seq}\ndata: {data}\n\n"


async def _event_stream(run_id: str, start_seq: int) -> AsyncIterator[str]:
    """SSE 事件流：历史补发 + 轮询推流 + 心跳 + 终态优雅关闭。

    每轮查询都用 get_session_factory() 短会话，不在流内长持 request session；
    单轮查询失败只记日志，下一轮重试，不中断流。
    """
    settings = get_settings()
    heartbeat_seconds = float(settings.SSE_HEARTBEAT_SECONDS)
    poll_seconds = float(settings.SSE_POLL_SECONDS)

    last_sent = start_seq
    last_new_event_at = time.monotonic()  # 心跳计时基于最后一条新事件时刻
    terminal_quiet_rounds = 0

    try:
        while True:
            got_new = False
            run_status: TaskStatus | None = None
            logs: list[AgentExecutionLog] = []
            try:
                factory = get_session_factory()
                async with factory() as poll_session:
                    run_status = (
                        await poll_session.execute(
                            select(AgentRun.status).where(AgentRun.id == run_id)
                        )
                    ).scalar_one_or_none()
                    logs = list(
                        (
                            await poll_session.execute(
                                select(AgentExecutionLog)
                                .where(
                                    AgentExecutionLog.run_id == run_id,
                                    AgentExecutionLog.seq > last_sent,
                                )
                                .order_by(AgentExecutionLog.seq)
                            )
                        ).scalars().all()
                    )
            except Exception as exc:  # noqa: BLE001 - 单轮查询失败不中断流，下轮重试
                logger.warning("SSE 轮询查询失败（下轮重试）: run=%s err=%s", run_id, exc)
            else:
                for log in logs:
                    yield _sse_frame(
                        run_id, log.event_type, int(log.seq), dict(log.payload or {}), log.created_at
                    )
                    last_sent = max(last_sent, int(log.seq))
                    got_new = True

                if got_new:
                    last_new_event_at = time.monotonic()
                    terminal_quiet_rounds = 0
                else:
                    # 发完一批（空批也算）后，若静默超时先补一帧心跳再继续等
                    if time.monotonic() - last_new_event_at >= heartbeat_seconds:
                        yield ": ping\n\n"
                        last_new_event_at = time.monotonic()
                    # 终态优雅关闭：无新事件时再等一轮，确保尾批事件送达后关闭
                    if run_status is not None and run_status in TaskStatus.terminal():
                        terminal_quiet_rounds += 1
                        if terminal_quiet_rounds >= 2:
                            logger.info(
                                "SSE 流终态关闭: run=%s last_seq=%d", run_id, last_sent
                            )
                            return
                    else:
                        terminal_quiet_rounds = 0

            await asyncio.sleep(poll_seconds)
    except (asyncio.CancelledError, GeneratorExit):
        # 客户端断开：静默退出，不写错误日志
        raise


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
    accept: str | None = Header(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    session: AsyncSession = Depends(get_db),
) -> ExecutionLogEventListOut | StreamingResponse:
    """事件历史/流。内容协商：Accept 含 text/event-stream → SSE；否则 JSON（B1 行为不变）。"""
    wants_sse = accept is not None and "text/event-stream" in accept
    if not wants_sse:
        # ── B1 JSON 形态：行为与历史版本完全一致 ──
        return await RunsService(session).list_events(run_id, after_seq=after)

    # ── SSE 形态：进入流之前检查 run 存在性（404 同 JSON 错误体）──
    factory = get_session_factory()
    async with factory() as check_session:
        run_exists = (
            await check_session.execute(select(AgentRun.id).where(AgentRun.id == run_id))
        ).scalar_one_or_none()
    if run_exists is None:
        raise BizException(ErrorCode.NOT_FOUND, f"Run 不存在: {run_id}", status_code=404)

    # 起点 seq：Last-Event-ID 头优先（int），非法/缺失 → query after（缺省 0）
    start_seq = after
    if last_event_id is not None:
        try:
            parsed = int(str(last_event_id).strip())
            if parsed < 0:
                raise ValueError
            start_seq = parsed
        except ValueError:
            start_seq = after

    return StreamingResponse(
        _event_stream(run_id, start_seq),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
