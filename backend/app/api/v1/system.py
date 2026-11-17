"""system 域路由：健康检查别名（前端契约 GET /system/health，docs/06 §3.1）。

与 /api/v1/health 同一实现（docs/08 §4 定稿保留双路径，避免前端改动）。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession  # noqa: F401（保持依赖注入一致性）

from app.schemas.health import SystemHealth
from app.services.health import get_system_health

router = APIRouter(tags=["system"])


@router.get("/system/health", response_model=SystemHealth)
async def system_health() -> SystemHealth:
    return await get_system_health()
