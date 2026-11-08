"""依赖注入：请求级 DB session 等（docs/08 §2 api/deps）。

current_user 预留：P1 无鉴权（决策记录），P2 接入后在此挂依赖。
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import db_session


async def get_db(session: AsyncSession = Depends(db_session)) -> AsyncIterator[AsyncSession]:
    yield session
