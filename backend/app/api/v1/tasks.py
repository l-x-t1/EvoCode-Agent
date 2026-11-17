"""tasks 域路由（docs/06 §3.2 子集；Idempotency-Key 见 POST /tasks）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.db.redis import get_redis
from app.models.user import User
from app.schemas.common import (
    MessagePage,
    RunOut,
    TaskOut,
    TaskPage,
)
from app.services.tasks import TasksService

router = APIRouter(prefix="/tasks", tags=["tasks"])


class TaskCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = ""
    repo: str | None = Field(default=None, max_length=255)
    model: str = Field(default="auto", pattern="^(glm-5\\.3|glm-5\\.3-flash|auto)$")
    skillIds: list[str] = Field(default_factory=list)


@router.get("", response_model=TaskPage)
async def list_tasks(
    status: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=120),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TaskPage:
    return await TasksService(session, _redis_or_none()).list_tasks(
        status=status, q=q, page=page, size=size, user_id=None
    )


@router.post("", response_model=TaskOut, status_code=201)
async def create_task(
    body: TaskCreateIn,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TaskOut:
    out = await TasksService(session, _redis_or_none()).create_task(
        user_id=user.id,
        title=body.title,
        description=body.description,
        repo=body.repo,
        model=body.model,
        skill_ids=body.skillIds,
        idempotency_key=idempotency_key,
    )
    # B3：任务创建后拉起 Agent run（编排器内部等待事务可见；LLM 未配置时保持 queued）
    from app.agents.orchestrator import get_orchestrator

    get_orchestrator().schedule_start(out.id)
    return out


@router.get("/{task_id}", response_model=TaskOut)
async def get_task(
    task_id: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> TaskOut:
    return await TasksService(session, _redis_or_none()).get_task(task_id)


@router.post("/{task_id}/cancel", response_model=dict[str, bool])
async def cancel_task(
    task_id: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> dict[str, bool]:
    return await TasksService(session, _redis_or_none()).cancel_task(task_id)


@router.get("/{task_id}/messages", response_model=MessagePage)
async def list_task_messages(
    task_id: str,
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> MessagePage:
    return await TasksService(session, _redis_or_none()).list_messages(task_id, cursor)


@router.get("/{task_id}/runs", response_model=list[RunOut])
async def list_task_runs(
    task_id: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> list[RunOut]:
    return await TasksService(session, _redis_or_none()).list_runs(task_id)


def _redis_or_none():
    """幂等键依赖 Redis；Redis 不可用时降级为无幂等（如实记录）。"""
    try:
        return get_redis()
    except RuntimeError:
        return None
