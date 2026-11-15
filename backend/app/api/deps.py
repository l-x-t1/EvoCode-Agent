"""依赖注入：请求级 DB session + 单用户身份解析（B1 补 D5）。

- get_db：请求级 session（事务边界在 db_session）
- get_current_user：MVP 无鉴权（docs/08 决策记录），解析为幂等创建的
  开发用户（dev@evocode.local）；接入真实鉴权时仅需替换本依赖实现，
  所有路由签名不变。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import db_session
from app.repositories.users import UsersRepository

DEV_USER_EMAIL = "dev@evocode.local"


async def get_db(session: AsyncSession = Depends(db_session)) -> AsyncIterator[AsyncSession]:
    yield session


async def get_current_user(session: AsyncSession = Depends(get_db)):
    """单用户模式身份解析：不存在则幂等创建开发用户（B1 补 D5）。"""
    repo = UsersRepository(session)
    return await repo.get_or_create_dev_user(DEV_USER_EMAIL)
