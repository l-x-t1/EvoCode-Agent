"""approvals 仓库（审批域）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution import Approval
from app.repositories.base import BaseRepository


class ApprovalsRepository(BaseRepository):
    async def get_approval(self, approval_id: str) -> Approval | None:
        return (await self.session.execute(
            select(Approval).where(Approval.id == approval_id)
        )).scalar_one_or_none()

    async def list_approvals(
        self, *, status: str | None = None, page: int = 1, size: int = 20
    ) -> tuple[list[Approval], int]:
        stmt = select(Approval).order_by(Approval.created_at.desc(), Approval.id.desc())
        if status:
            stmt = stmt.where(Approval.status == status)
        return await self._paged(stmt, page, size)
