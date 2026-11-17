"""users 仓库：开发用户幂等初始化（B1 补 D5）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UsersRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_email(self, email: str) -> User | None:
        return (await self.session.execute(
            select(User).where(User.email == email)
        )).scalar_one_or_none()

    async def get_or_create_dev_user(self, email: str) -> User:
        """单用户模式：不存在则创建（并发依赖 email 唯一约束兜底）。"""
        user = await self.get_by_email(email)
        if user is not None:
            return user
        user = User(email=email, display_name="开发用户", is_active=True, role="owner")
        self.session.add(user)
        await self.session.flush()
        return user
