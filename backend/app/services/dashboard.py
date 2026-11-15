"""Dashboard / Agents / SkillEvents 服务：全部来自真实聚合，零虚构。"""

from __future__ import annotations

from datetime import datetime, timezone

from app.repositories.dashboard import DashboardRepository
from app.schemas.dashboard import (
    AgentStatusItem,
    AgentStatusOut,
    DashboardSummaryOut,
    DashboardTrendsOut,
    SkillEventListOut,
    SkillEventOut,
    TaskTrendPoint,
    TokenTrendPoint,
)

_RANGE_DAYS = {"7d": 7, "14d": 14, "30d": 30}


class DashboardService:
    def __init__(self, session) -> None:
        self.repo = DashboardRepository(session)

    async def summary(self) -> DashboardSummaryOut:
        counts = await self.repo.task_counts()
        total = sum(counts.values())
        today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        tasks_today = await self.repo.tasks_created_since(today_start)
        tasks_running = sum(counts.get(s, 0) for s in _RUNNING_STATUSES_IMPL)
        tokens_total = await self.repo.tokens_sum()
        tokens_today = await self.repo.tokens_sum(since=today_start)
        skill_count = await self.repo.skill_count()
        evolutions = await self.repo.skill_evolutions()
        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        terminal = completed + failed
        success_rate = round(completed / terminal, 4) if terminal else 0.0
        return DashboardSummaryOut(
            tasks_total=total,
            tasks_today=tasks_today,
            tasks_running=tasks_running,
            tokens_total=tokens_total,
            tokens_today=tokens_today,
            skill_count=skill_count,
            skill_evolutions=evolutions,
            success_rate=success_rate,
        )

    async def trends(self, range_key: str) -> DashboardTrendsOut:
        days = _RANGE_DAYS.get(range_key)
        if days is None:
            from app.core.exceptions import BizException
            from app.core.response import ErrorCode

            raise BizException(
                ErrorCode.VALIDATION_ERROR,
                "range 仅支持 7d/14d/30d",
                status_code=422,
            )
        task_trend = await self.repo.task_trend(days)
        token_trend = await self.repo.token_trend(days)
        return DashboardTrendsOut(
            range=range_key,
            task_trend=[TaskTrendPoint(**p) for p in task_trend],
            token_trend=[TokenTrendPoint(**p) for p in token_trend],
        )

    async def agent_status(self) -> AgentStatusOut:
        steps = await self.repo.agent_step_counts()
        runs = await self.repo.run_counts_by_status()
        items = [
            # 名称与前端 AgentRole 中文展示对齐由前端处理；这里给稳定 id
            AgentStatusItem(name="planner", value=steps.get("planner", 0)),
            AgentStatusItem(name="executor", value=steps.get("executor", 0)),
            AgentStatusItem(name="reviewer", value=steps.get("reviewer", 0)),
            AgentStatusItem(name="replanner", value=steps.get("replanner", 0)),
        ]
        return AgentStatusOut(total=sum(i.value for i in items) + runs.get("queued", 0), items=items)

    async def skill_events(self, limit: int = 10) -> SkillEventListOut:
        rows = await self.repo.latest_skill_events(limit)
        names = await self.repo.skill_name_map()
        items: list[SkillEventOut] = []
        for obj in rows:
            created = obj.created_at
            if hasattr(obj, "version"):  # SkillVersion → created
                items.append(SkillEventOut(
                    id=obj.id,
                    skill_id=obj.skill_id,
                    type="created",
                    message=f"{names.get(obj.skill_id, 'Skill')} v{obj.version} 发布",
                    created_at=created.isoformat(),
                ))
            else:  # SkillCandidate → proposed/approved/rejected
                items.append(SkillEventOut(
                    id=obj.id,
                    skill_id=obj.skill_id,
                    type=str(obj.status) if str(obj.status) != "pending" else "proposed",
                    message=f"候选 Skill（{obj.kind}）：{obj.summary[:80]}",
                    created_at=created.isoformat(),
                ))
        return SkillEventListOut(items=items)


_RUNNING_STATUSES_IMPL = ("queued", "planning", "executing", "reviewing", "waiting_approval")
