"""agent_tasks / conversations / messages 仓库（tasks 域）。"""

from __future__ import annotations

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TaskStatus
from app.models.conversation import Conversation, Message
from app.models.task import AgentTask
from app.repositories.base import BaseRepository

ACTIVE_STATUSES = (
    TaskStatus.QUEUED,
    TaskStatus.PLANNING,
    TaskStatus.EXECUTING,
    TaskStatus.REVIEWING,
    TaskStatus.WAITING_APPROVAL,
)


class TasksRepository(BaseRepository):
    def _base_query(self, *, status: str | None, q: str | None, user_id: str | None) -> Select:
        stmt = select(AgentTask)
        if status:
            stmt = stmt.where(AgentTask.status == status)
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(AgentTask.title.ilike(like), AgentTask.description.ilike(like)))
        if user_id:
            stmt = stmt.where(AgentTask.user_id == user_id)
        return stmt.order_by(AgentTask.updated_at.desc())

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        q: str | None = None,
        page: int = 1,
        size: int = 20,
        user_id: str | None = None,
    ) -> tuple[list[AgentTask], int]:
        return await self._paged(self._base_query(status=status, q=q, user_id=user_id), page, size)

    async def get_task(self, task_id: str) -> AgentTask | None:
        return (await self.session.execute(
            select(AgentTask).where(AgentTask.id == task_id)
        )).scalar_one_or_none()

    async def create_task(
        self,
        *,
        user_id: str,
        title: str,
        description: str,
        repo: str | None,
        model: str,
        skill_ids: list[str],
    ) -> AgentTask:
        task = AgentTask(
            user_id=user_id,
            title=title,
            description=description,
            repo=repo,
            status=TaskStatus.QUEUED,
            model=model,
            skill_ids=skill_ids,
        )
        self.session.add(task)
        await self.session.flush()
        return task

    async def count_by_status(self) -> dict[str, int]:
        rows = (await self.session.execute(
            select(AgentTask.status, func.count()).group_by(AgentTask.status)
        )).all()
        return {str(status): int(n) for status, n in rows}


class ConversationsRepository(BaseRepository):
    async def get_or_create_for_task(self, task: AgentTask) -> Conversation:
        """MVP 与任务 1:1（service 层保证，docs/08 决策 #3）。"""
        conv = (await self.session.execute(
            select(Conversation).where(Conversation.task_id == task.id).limit(1)
        )).scalar_one_or_none()
        if conv is not None:
            return conv
        conv = Conversation(task_id=task.id, user_id=task.user_id, title=task.title)
        self.session.add(conv)
        await self.session.flush()
        return conv

    async def add_message(
        self,
        conversation: Conversation,
        *,
        role: str,
        content: str,
        run_id: str | None = None,
        tokens: int | None = None,
    ) -> Message:
        msg = Message(
            conversation_id=conversation.id,
            run_id=run_id,
            role=role,  # type: ignore[arg-type]（StrEnum/str 均可入库）
            content=content,
            tokens=tokens,
        )
        self.session.add(msg)
        await self.session.flush()
        return msg

    async def list_messages(
        self, conversation_id: str, cursor: str | None, limit: int = 100
    ) -> list[Message]:
        """按 created_at,id 升序；cursor = 最后一条 message id（ULID 单调递增）。"""
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        if cursor:
            anchor = (await self.session.execute(
                select(Message).where(Message.id == cursor)
            )).scalar_one_or_none()
            if anchor is not None:
                stmt = stmt.where(
                    or_(Message.created_at > anchor.created_at,
                        (Message.created_at == anchor.created_at) & (Message.id > cursor))
                )
        stmt = stmt.order_by(Message.created_at.asc(), Message.id.asc()).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all())
