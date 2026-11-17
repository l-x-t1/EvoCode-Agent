"""B9 端到端场景共享辅助（FakeLLM / 等待终态 / 事件读取 / 直构 run）。"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AgentRole, PlanStepStatus, TaskStatus
from app.db.session import get_session_factory
from app.llm.client import BaseLLMClient, LLMResponse
from app.models.execution import AgentExecutionLog
from app.models.task import AgentRun, AgentTask, Plan, PlanStep
from app.repositories.users import UsersRepository


def _now():
    return datetime.now(timezone.utc)


class FakeLLM(BaseLLMClient):
    """脚本化 LLM（B9 场景声明用）：按序返回预设响应；异常对象直接抛出。"""

    def __init__(self, responses: list) -> None:
        self._q = list(responses)
        self.calls: list[list] = []

    @property
    def configured(self) -> bool:
        return True

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None):
        self.calls.append(messages)
        item = self._q.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(obj) -> LLMResponse:
    content = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return LLMResponse(content=content, model="glm-5.3",
                       prompt_tokens=10, completion_tokens=5, latency_ms=1)


async def wait_terminal(run_id: str, timeout: float = 30.0) -> AgentRun:
    factory = get_session_factory()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is not None and run.status in TaskStatus.terminal():
                return run
        await asyncio.sleep(0.2)
    raise TimeoutError(f"run {run_id} 未在 {timeout}s 内到达终态")


async def wait_suspended(run_id: str, timeout: float = 20.0) -> None:
    factory = get_session_factory()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is not None and str(getattr(run.status, "value", run.status)) == "waiting_approval":
                return
        await asyncio.sleep(0.2)
    raise TimeoutError(f"run {run_id} 未进入 waiting_approval")


async def events_of(run_id: str) -> list[AgentExecutionLog]:
    factory = get_session_factory()
    async with factory() as session:
        rows = list((await session.execute(
            select(AgentExecutionLog).where(AgentExecutionLog.run_id == run_id)
            .order_by(AgentExecutionLog.seq.asc())
        )).scalars().all())
        for r in rows:
            session.expunge(r)
        return rows


async def mk_run_direct(title: str, *, log_count: int = 0,
                        with_plan: tuple[str, ...] | None = None) -> tuple[str, str]:
    """真实外键链直接构造（S4/S8/S9/S12 使用）。"""
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title=title, description="",
                         model="auto", status=TaskStatus.EXECUTING,
                         created_at=_now(), updated_at=_now())
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=TaskStatus.EXECUTING, model="glm-5.3",
                       started_at=_now(), created_at=_now(), updated_at=_now())
        session.add(run)
        await session.flush()
        if with_plan:
            plan = Plan(run_id=run.id, revision=1, created_at=_now())
            session.add(plan)
            await session.flush()
            status_map = {"done": PlanStepStatus.DONE, "pending": PlanStepStatus.PENDING,
                          "running": PlanStepStatus.RUNNING, "failed": PlanStepStatus.FAILED}
            for idx, st in enumerate(with_plan):
                session.add(PlanStep(plan_id=plan.id, idx=idx, title=f"步骤 {idx}",
                                     agent=AgentRole.EXECUTOR, status=status_map[st],
                                     attempt=1, tool_call_ids=[], created_at=_now()))
        for seq in range(1, log_count + 1):
            session.add(AgentExecutionLog(run_id=run.id, seq=seq, event_type="run.status",
                                          payload={"status": "executing"}, created_at=_now()))
        await session.commit()
        return task.id, run.id
