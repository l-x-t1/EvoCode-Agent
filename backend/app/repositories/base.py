"""Repository 基座：会话持有与通用查询辅助（兑现自述分层）。

约定（repositories/__init__.py）：路由与 service 不直接触碰 Session，
统一经 Repository 访问数据。
"""

from __future__ import annotations

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.response import Page


class BaseRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _paged[T](
        self,
        stmt: Select,
        page: int,
        size: int,
    ) -> tuple[list[T], int]:
        """通用分页：返回 (items, total)；page 从 1 起。"""
        total = (await self.session.execute(
            select(func.count()).select_from(stmt.order_by(None).subquery())
        )).scalar_one()
        rows = (await self.session.execute(
            stmt.offset((page - 1) * size).limit(size)
        )).scalars().all()
        return list(rows), int(total)

    @staticmethod
    def make_page[T](items: list[T], total: int, page: int, size: int) -> Page[T]:
        return Page[T](items=items, total=total, page=page, size=size)
