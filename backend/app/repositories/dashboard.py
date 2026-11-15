"""Dashboard 聚合仓库：全部为真实 SQL 聚合，不虚构数字。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.misc import ModelUsage
from app.models.skill import Skill, SkillCandidate, SkillVersion
from app.models.task import AgentRun, AgentTask, PlanStep
from app.repositories.base import BaseRepository

_RUNNING_STATUSES = ("queued", "planning", "executing", "reviewing", "waiting_approval")


class DashboardRepository(BaseRepository):
    async def task_counts(self) -> dict[str, int]:
        rows = (await self.session.execute(
            select(AgentTask.status, func.count()).group_by(AgentTask.status)
        )).all()
        return {str(s): int(n) for s, n in rows}

    async def tasks_created_since(self, since: datetime) -> int:
        return int((await self.session.execute(
            select(func.count()).select_from(AgentTask)
            .where(AgentTask.created_at >= since)
        )).scalar_one())

    async def tokens_sum(self, *, since: datetime | None = None) -> int:
        stmt = select(
            func.coalesce(func.sum(ModelUsage.prompt_tokens), 0)
            + func.coalesce(func.sum(ModelUsage.completion_tokens), 0)
        ).select_from(ModelUsage)
        if since is not None:
            stmt = stmt.where(ModelUsage.created_at >= since)
        return int((await self.session.execute(stmt)).scalar_one())

    async def skill_count(self) -> int:
        return int((await self.session.execute(
            select(func.count()).select_from(Skill).where(Skill.status == "active")
        )).scalar_one())

    async def skill_evolutions(self) -> int:
        """已批准的候选 = 已发生的进化次数。"""
        return int((await self.session.execute(
            select(func.count()).select_from(SkillCandidate)
            .where(SkillCandidate.status == "approved")
        )).scalar_one())

    async def task_trend(self, days: int) -> list[dict[str, Any]]:
        """近 N 天（UTC 日）：created/succeeded/failed，缺数据日补零。"""
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days - 1)
        day = func.date_trunc("day", AgentTask.created_at).label("day")
        rows = (await self.session.execute(
            select(
                day,
                func.count().label("created"),
                func.sum(case((AgentTask.status == "completed", 1), else_=0)).label("succeeded"),
                func.sum(case((AgentTask.status == "failed", 1), else_=0)).label("failed"),
            )
            .where(AgentTask.created_at >= start)
            .group_by(day)
        )).all()
        by_date = {r.day.date().isoformat(): r for r in rows}
        out: list[dict[str, Any]] = []
        for i in range(days):
            d = (start + timedelta(days=i)).date().isoformat()
            r = by_date.get(d)
            out.append({
                "date": d,
                "created": int(r.created) if r else 0,
                "succeeded": int(r.succeeded or 0) if r else 0,
                "failed": int(r.failed or 0) if r else 0,
            })
        return out

    async def token_trend(self, days: int) -> list[dict[str, Any]]:
        start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=days - 1)
        day = func.date_trunc("day", ModelUsage.created_at).label("day")
        rows = (await self.session.execute(
            select(
                day,
                ModelUsage.model,
                func.coalesce(func.sum(ModelUsage.prompt_tokens + ModelUsage.completion_tokens), 0),
            )
            .where(ModelUsage.created_at >= start)
            .group_by(day, ModelUsage.model)
        )).all()
        acc: dict[str, dict[str, int]] = {}
        for r in rows:
            d = r.day.date().isoformat()
            acc.setdefault(d, {"glm53": 0, "flash": 0})
            if r.model == "glm-5.3":
                acc[d]["glm53"] += int(r[2])
            elif r.model == "glm-5.3-flash":
                acc[d]["flash"] += int(r[2])
        out: list[dict[str, Any]] = []
        for i in range(days):
            d = (start + timedelta(days=i)).date().isoformat()
            v = acc.get(d, {"glm53": 0, "flash": 0})
            out.append({"date": d, **v})
        return out

    async def agent_step_counts(self) -> dict[str, int]:
        """按角色聚合 plan_steps（Agent 状态环图的真实数据源）。"""
        rows = (await self.session.execute(
            select(PlanStep.agent, func.count()).group_by(PlanStep.agent)
        )).all()
        return {str(a): int(n) for a, n in rows}

    async def run_counts_by_status(self) -> dict[str, int]:
        rows = (await self.session.execute(
            select(AgentRun.status, func.count()).group_by(AgentRun.status)
        )).all()
        return {str(s): int(n) for s, n in rows}

    async def latest_skill_events(self, limit: int) -> list[Any]:
        """Skill 事件流：skill_versions(created) + skill_candidates(proposed/approved/rejected)
        按 created_at 取最新 limit 条。"""
        versions = (await self.session.execute(
            select(SkillVersion).order_by(SkillVersion.created_at.desc()).limit(limit)
        )).scalars().all()
        candidates = (await self.session.execute(
            select(SkillCandidate).order_by(SkillCandidate.created_at.desc()).limit(limit)
        )).scalars().all()
        items: list[tuple[datetime, Any]] = [
            (v.created_at, v) for v in versions
        ] + [(c.created_at, c) for c in candidates]
        items.sort(key=lambda x: x[0], reverse=True)
        return [obj for _, obj in items[:limit]]

    async def skill_name_map(self) -> dict[str, str]:
        rows = (await self.session.execute(select(Skill.id, Skill.name))).all()
        return {r.id: r.name for r in rows}
