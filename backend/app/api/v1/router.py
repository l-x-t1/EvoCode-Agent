"""v1 路由汇总（docs/06 §3：P2 起按域注册 tasks/runs/skills/...）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import health

api_router = APIRouter()
api_router.include_router(health.router)
