"""事件写入器（B3）：run 内 seq 自增的 AgentExecutionLog 写入。

与 HarnessService._add_log 同语义；编排器独立持有以避免与 Harness
相互耦合。单进程 MVP 限制同 harness（多进程需 DB 序列，已记录）。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import AgentExecutionLog


class EventWriter:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def next_seq(self, run_id: str) -> int:
        current = (await self.session.execute(
            select(func.max(AgentExecutionLog.seq)).where(AgentExecutionLog.run_id == run_id)
        )).scalar()
        return (current or 0) + 1

    async def log(self, run_id: str, event_type: str, payload: dict) -> AgentExecutionLog:
        row = AgentExecutionLog(
            run_id=run_id, seq=await self.next_seq(run_id),
            event_type=event_type, payload=payload,
        )
        self.session.add(row)
        await self.session.flush()
        return row
