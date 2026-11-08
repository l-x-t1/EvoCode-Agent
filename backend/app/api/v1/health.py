"""健康检查接口（/api/v1/health，docs/08 §4）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.health import SystemHealth
from app.services import health as health_service

router = APIRouter(tags=["health"])


@router.get("/health", response_model=SystemHealth, summary="系统健康（各依赖状态与延迟）")
async def health() -> SystemHealth:
    """恒 200：故障体现在各子项 status（前端徽标按子项渲染）。"""
    return await health_service.get_system_health()
