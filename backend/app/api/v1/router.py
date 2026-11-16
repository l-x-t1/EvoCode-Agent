"""v1 路由汇总：B1 起按域注册（dashboard/tasks/runs/approvals/system/health）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import approvals, context, dashboard, health, memory, runs, skills, system, tasks

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(system.router)
api_router.include_router(dashboard.router)
api_router.include_router(tasks.router)
api_router.include_router(runs.router)
api_router.include_router(approvals.router)
api_router.include_router(context.router)
api_router.include_router(skills.router)
api_router.include_router(memory.router)
