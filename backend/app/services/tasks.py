"""任务域服务：创建（含 Redis 幂等）、取消（状态机守卫）、查询组装。

状态机（docs/08 §1，B1 落地部分）：
- queued → (B3) planning → executing → reviewing → completed/failed
- waiting_approval 仅由 B3 执行流进入
- queued/executing/... → cancelled：仅非终态可取消（终态迁移 409）
- 审批恢复/拒绝后续流转在 B3（执行流引擎）实现
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AgentRole, TaskStatus
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.models.task import AgentTask
from app.repositories.approvals import ApprovalsRepository
from app.repositories.runs import RunsRepository
from app.repositories.tasks import (
    ConversationsRepository,
    TasksRepository,
)
from app.schemas.common import (
    ApprovalDecisionIn,
    ApprovalOut,
    ApprovalPage,
    MessageOut,
    MessagePage,
    RunOut,
    RunStatsOut,
    TaskOut,
    TaskPage,
    TaskStatsOut,
)

logger = logging.getLogger(__name__)

IDEM_PREFIX = "idem:task:"
IDEM_TTL_SECONDS = 24 * 3600


def _stats(task: AgentTask) -> TaskStatsOut:
    return TaskStatsOut(
        duration_ms=task.duration_ms,
        tokens_in=task.tokens_in,
        tokens_out=task.tokens_out,
        tool_calls=task.tool_calls,
        test_pass_rate=float(task.test_pass_rate) if task.test_pass_rate is not None else None,
    )


def to_task_out(task: AgentTask) -> TaskOut:
    return TaskOut(
        id=task.id,
        title=task.title,
        description=task.description,
        repo=task.repo,
        status=str(task.status),
        model=task.model,
        skill_ids=list(task.skill_ids or []),
        created_at=task.created_at,
        updated_at=task.updated_at,
        stats=_stats(task),
        latest_run_id=task.latest_run_id,
    )


def to_run_out(run) -> RunOut:
    return RunOut(
        id=run.id,
        task_id=run.task_id,
        status=str(run.status),
        started_at=run.started_at,
        finished_at=run.finished_at,
        model=run.model,
        stats=RunStatsOut(
            duration_ms=run.duration_ms,
            tokens_in=run.tokens_in,
            tokens_out=run.tokens_out,
            tool_calls=run.tool_calls,
            test_pass_rate=float(run.test_pass_rate) if run.test_pass_rate is not None else None,
            replan_count=run.replan_count,
        ),
    )


class TasksService:
    def __init__(self, session: AsyncSession, redis: Redis | None) -> None:
        self.tasks = TasksRepository(session)
        self.conversations = ConversationsRepository(session)
        self.session = session
        self.redis = redis

    async def _idempotent_get(self, key_value: str) -> TaskOut | None:
        if self.redis is None:
            return None
        stored = await self.redis.get(IDEM_PREFIX + key_value)
        if not stored:
            return None
        task = await self.tasks.get_task(stored)
        return to_task_out(task) if task else None

    async def create_task(
        self,
        *,
        user_id: str,
        title: str,
        description: str,
        repo: str | None,
        model: str,
        skill_ids: list[str],
        idempotency_key: str | None,
    ) -> TaskOut:
        if idempotency_key:
            existing = await self._idempotent_get(idempotency_key)
            if existing is not None:
                logger.info("Idempotency-Key 重放：%s → %s", idempotency_key, existing.id)
                return existing

        task = await self.tasks.create_task(
            user_id=user_id,
            title=title,
            description=description,
            repo=repo,
            model=model,
            skill_ids=skill_ids,
        )
        # 会话 1:1 + 用户首条消息（先于 Run，docs/08 决策 #3）
        conv = await self.conversations.get_or_create_for_task(task)
        if description.strip():
            await self.conversations.add_message(
                conv, role=AgentRole.USER.value, content=description
            )

        # 幂等键登记（请求结束统一 commit；若 commit 失败，读路径自愈：查不到任务则下次重建）
        if idempotency_key and self.redis is not None:
            try:
                await self.redis.set(
                    IDEM_PREFIX + idempotency_key, task.id, ex=IDEM_TTL_SECONDS
                )
            except Exception:  # noqa: BLE001 - 幂等登记失败不阻塞主流程
                logger.warning("幂等键登记失败（key=%s）", idempotency_key)
        return to_task_out(task)

    async def get_task(self, task_id: str) -> TaskOut:
        task = await self.tasks.get_task(task_id)
        if task is None:
            raise BizException(
                ErrorCode.NOT_FOUND, f"任务不存在: {task_id}", status_code=404
            )
        return to_task_out(task)

    async def list_tasks(
        self,
        *,
        status: str | None,
        q: str | None,
        page: int,
        size: int,
        user_id: str | None,
    ) -> TaskPage:
        items, total = await self.tasks.list_tasks(
            status=status, q=q, page=page, size=size, user_id=user_id
        )
        return TaskPage(
            items=[to_task_out(t) for t in items], total=total, page=page, size=size
        )

    async def cancel_task(self, task_id: str) -> dict[str, bool]:
        task = await self.tasks.get_task(task_id)
        if task is None:
            raise BizException(ErrorCode.NOT_FOUND, f"任务不存在: {task_id}", status_code=404)
        if task.status in TaskStatus.terminal():
            raise BizException(
                ErrorCode.CONFLICT,
                f"任务已终态（{task.status.value}），不可取消",
                status_code=409,
                details={"currentStatus": task.status.value},
            )
        task.status = TaskStatus.CANCELLED
        task.updated_at = datetime.now(timezone.utc)
        # 活跃 run 一并终止（终态迁移守卫在 B3 执行流里细化）
        for run in await RunsRepository(self.session).list_runs_for_task(task.id):
            if run.status not in TaskStatus.terminal():
                run.status = TaskStatus.CANCELLED
                run.finished_at = datetime.now(timezone.utc)
        return {"ok": True}

    async def list_messages(self, task_id: str, cursor: str | None) -> MessagePage:
        task = await self.tasks.get_task(task_id)
        if task is None:
            raise BizException(ErrorCode.NOT_FOUND, f"任务不存在: {task_id}", status_code=404)
        conv = await self.conversations.get_or_create_for_task(task)
        msgs = await self.conversations.list_messages(conv.id, cursor)
        return MessagePage(
            items=[
                MessageOut(
                    id=m.id,
                    run_id=m.run_id,
                    role=str(m.role),
                    content=m.content,
                    created_at=m.created_at,
                    tokens=m.tokens,
                )
                for m in msgs
            ],
            total=len(msgs),
            page=1,
            size=len(msgs),
        )

    async def list_runs(self, task_id: str) -> list[RunOut]:
        task = await self.tasks.get_task(task_id)
        if task is None:
            raise BizException(ErrorCode.NOT_FOUND, f"任务不存在: {task_id}", status_code=404)
        runs = await RunsRepository(self.session).list_runs_for_task(task.id)
        return [to_run_out(r) for r in runs]


class ApprovalsService:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = ApprovalsRepository(session)
        self.session = session

    @staticmethod
    def to_out(apv) -> ApprovalOut:
        return ApprovalOut(
            id=apv.id,
            run_id=apv.run_id,
            tool_call_id=apv.tool_call_id,
            tool=apv.tool,
            summary=apv.summary,
            risk=str(apv.risk),
            status=str(apv.status),
            created_at=apv.created_at,
            resolved_at=apv.resolved_at,
            resolved_by=str(apv.resolved_by) if apv.resolved_by else None,
        )

    async def list_approvals(self, *, status: str | None, page: int, size: int) -> ApprovalPage:
        items, total = await self.repo.list_approvals(status=status, page=page, size=size)
        return ApprovalPage(
            items=[self.to_out(a) for a in items], total=total, page=page, size=size
        )

    async def resolve(self, approval_id: str, body: ApprovalDecisionIn) -> ApprovalOut:
        """审批决策（状态机守卫）：仅 pending 可决策；终态不可逆（docs/08 §8-4）。

        B3 起批准→恢复执行流原位置；拒绝→replanner。本批先落库。
        """
        if body.decision not in ("approved", "rejected"):
            raise BizException(
                ErrorCode.VALIDATION_ERROR,
                "decision 仅支持 approved / rejected",
                status_code=422,
            )
        apv = await self.repo.get_approval(approval_id)
        if apv is None:
            raise BizException(ErrorCode.NOT_FOUND, f"审批不存在: {approval_id}", status_code=404)
        if apv.status != "pending":
            raise BizException(
                ErrorCode.CONFLICT,
                f"审批已处于终态（{apv.status.value}），不可重复决策",
                status_code=409,
                details={"currentStatus": str(apv.status)},
            )
        apv.status = "approved" if body.decision == "approved" else "rejected"
        apv.resolved_at = datetime.now(timezone.utc)
        apv.resolved_by = "user"
        apv.comment = body.comment
        await self.session.flush()
        return self.to_out(apv)
