"""Runs 域服务：plan / tool-calls / diffs / tests / 事件历史。

diffs 与 tests 从事件溯源表 agent_execution_logs 读取（B3 执行流写入
`code.diff.created` / `test.finished` 事件），不引入新表（零迁移）。
"""

from __future__ import annotations

from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.repositories.runs import RunsRepository
from app.schemas.common import (
    CodeDiffListOut,
    CodeDiffOut,
    DiffFileOut,
    ExecutionLogEventListOut,
    ExecutionLogEventOut,
    MessageOut,
    MessagePage,
    PlanOut,
    PlanStepOut,
    RunOut,
    TestFailureOut,
    TestResultListOut,
    TestResultOut,
    ToolCallOut,
    ToolCallPage,
)
from app.services.tasks import to_run_out


class RunsService:
    def __init__(self, session) -> None:
        self.runs = RunsRepository(session)

    async def _get_run_or_404(self, run_id: str):
        run = await self.runs.get_run(run_id)
        if run is None:
            raise BizException(ErrorCode.NOT_FOUND, f"Run 不存在: {run_id}", status_code=404)
        return run

    async def get_run(self, run_id: str) -> RunOut:
        return to_run_out(await self._get_run_or_404(run_id))

    async def get_plan(self, run_id: str) -> PlanOut | None:
        await self._get_run_or_404(run_id)
        plan = await self.runs.latest_plan(run_id)
        if plan is None:
            return None
        steps = await self.runs.list_steps(plan.id)
        return PlanOut(
            id=plan.id,
            run_id=plan.run_id,
            revision=plan.revision,
            steps=[
                PlanStepOut(
                    id=s.id,
                    index=s.idx,
                    title=s.title,
                    detail=s.detail,
                    agent=str(s.agent),
                    status=str(s.status),
                    attempt=s.attempt,
                    tool_call_ids=list(s.tool_call_ids or []),
                )
                for s in steps
            ],
        )

    async def list_tool_calls(self, run_id: str, cursor: str | None) -> ToolCallPage:
        await self._get_run_or_404(run_id)
        rows = await self.runs.list_tool_calls(run_id, cursor)
        return ToolCallPage(
            items=[
                ToolCallOut(
                    id=tc.id,
                    run_id=tc.run_id,
                    step_id=tc.plan_step_id,
                    server=tc.server,
                    tool=tc.tool,
                    args=dict(tc.args or {}),
                    result_summary=tc.result_summary,
                    status=str(tc.status),
                    risk=str(tc.risk),
                    duration_ms=tc.duration_ms,
                    created_at=tc.created_at,
                )
                for tc in rows
            ],
            total=len(rows),
            page=1,
            size=len(rows),
        )

    async def list_diffs(self, run_id: str) -> CodeDiffListOut:
        await self._get_run_or_404(run_id)
        logs = await self.runs.list_execution_logs(run_id, event_types=["code.diff.created"])
        items: list[CodeDiffOut] = []
        for log in logs:
            payload = log.payload or {}
            files = [
                DiffFileOut(
                    path=f.get("path", ""),
                    additions=int(f.get("additions", 0)),
                    deletions=int(f.get("deletions", 0)),
                    patch=str(f.get("patch", "")),
                )
                for f in payload.get("files", [])
            ]
            items.append(CodeDiffOut(
                id=log.id,
                run_id=log.run_id,
                files=files,
                created_at=log.created_at,
            ))
        return CodeDiffListOut(items=items)

    async def list_tests(self, run_id: str) -> TestResultListOut:
        await self._get_run_or_404(run_id)
        logs = await self.runs.list_execution_logs(run_id, event_types=["test.finished"])
        items: list[TestResultOut] = []
        for log in logs:
            payload = log.payload or {}
            items.append(TestResultOut(
                id=log.id,
                run_id=log.run_id,
                passed=int(payload.get("passed", 0)),
                failed=int(payload.get("failed", 0)),
                skipped=int(payload.get("skipped", 0)),
                failures=[
                    TestFailureOut(
                        name=f.get("name", ""),
                        message=f.get("message", ""),
                        snippet=f.get("snippet"),
                    )
                    for f in payload.get("failures", [])
                ],
                log_tail=payload.get("logTail"),
                created_at=log.created_at,
            ))
        return TestResultListOut(items=items)

    async def list_events(self, run_id: str, after_seq: int = 0) -> ExecutionLogEventListOut:
        """事件历史（SSE 断线续传的数据源；B3 提供同路径 text/event-stream）。"""
        await self._get_run_or_404(run_id)
        logs = await self.runs.list_execution_logs(run_id, after_seq=after_seq)
        return ExecutionLogEventListOut(
            items=[
                ExecutionLogEventOut(
                    seq=log.seq,
                    event_type=log.event_type,
                    payload=dict(log.payload or {}),
                    created_at=log.created_at,
                )
                for log in logs
            ]
        )
