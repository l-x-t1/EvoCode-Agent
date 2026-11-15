"""runs / plans / tool_calls / execution_logs 仓库（runs 域）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import AgentExecutionLog, ToolCall
from app.models.task import AgentRun, Plan, PlanStep
from app.repositories.base import BaseRepository


class RunsRepository(BaseRepository):
    async def get_run(self, run_id: str) -> AgentRun | None:
        return (await self.session.execute(
            select(AgentRun).where(AgentRun.id == run_id)
        )).scalar_one_or_none()

    async def list_runs_for_task(self, task_id: str) -> list[AgentRun]:
        stmt = (
            select(AgentRun)
            .where(AgentRun.task_id == task_id)
            .order_by(AgentRun.created_at.desc(), AgentRun.id.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def latest_plan(self, run_id: str) -> Plan | None:
        """最新 revision 的 Plan（重规划追加新 Plan）。"""
        return (await self.session.execute(
            select(Plan)
            .where(Plan.run_id == run_id)
            .order_by(Plan.revision.desc())
            .limit(1)
        )).scalar_one_or_none()

    async def list_steps(self, plan_id: str) -> list[PlanStep]:
        stmt = (
            select(PlanStep)
            .where(PlanStep.plan_id == plan_id)
            .order_by(PlanStep.idx.asc(), PlanStep.id.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_tool_calls(
        self, run_id: str, cursor: str | None, limit: int = 100
    ) -> list[ToolCall]:
        stmt = select(ToolCall).where(ToolCall.run_id == run_id)
        if cursor:
            stmt = stmt.where(ToolCall.id > cursor)
        stmt = stmt.order_by(ToolCall.created_at.asc(), ToolCall.id.asc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_execution_logs(
        self,
        run_id: str,
        *,
        event_types: list[str] | None = None,
        after_seq: int | None = None,
        limit: int | None = None,
    ) -> list[AgentExecutionLog]:
        stmt = select(AgentExecutionLog).where(AgentExecutionLog.run_id == run_id)
        if event_types:
            stmt = stmt.where(AgentExecutionLog.event_type.in_(event_types))
        if after_seq is not None:
            stmt = stmt.where(AgentExecutionLog.seq > after_seq)
        stmt = stmt.order_by(AgentExecutionLog.seq.asc())
        if limit:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
