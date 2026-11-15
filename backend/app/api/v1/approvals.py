"""approvals 域路由（docs/06 §3.3）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.common import ApprovalDecisionIn, ApprovalOut, ApprovalPage
from app.services.tasks import ApprovalsService

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("", response_model=ApprovalPage)
async def list_approvals(
    status: str = Query(default="pending", pattern="^(pending|approved|rejected|expired)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
) -> ApprovalPage:
    return await ApprovalsService(session).list_approvals(status=status, page=page, size=size)


@router.post("/{approval_id}", response_model=ApprovalOut)
async def resolve_approval(
    approval_id: str,
    body: ApprovalDecisionIn,
    session: AsyncSession = Depends(get_db),
) -> ApprovalOut:
    """审批决策：仅 pending 可决策，重复决策 409（状态机守卫，docs/08 §8-4）。"""
    return await ApprovalsService(session).resolve(approval_id, body)
