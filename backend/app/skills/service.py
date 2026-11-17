"""Skill 服务层（B5）：注册/版本/候选/审核/回滚 + 事件派生 + 反馈候选生成。

审核闸门（修订要求红线）：候选一经创建即为 pending，唯一发布路径是
review_candidate(approved)；任何代码路径都不允许未审核候选影响
skill.current_version。回滚通过创建新版本实现（版本历史完整、可审计）。

事件派生（无独立事件表，零迁移）：
- skill_versions → created / rolled_back（changelog 以「回滚到」开头）
- skill_candidates → proposed（pending）/ approved / rejected
"""

from __future__ import annotations

import difflib
import json
from datetime import datetime, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import (
    CandidateKind,
    CandidateStatus,
    SkillSource,
)
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.models.execution import ToolCall
from app.models.skill import Skill, SkillCandidate, SkillEvaluation, SkillVersion
from app.models.task import AgentRun, AgentTask, Plan, PlanStep, PlanStep
from app.repositories.base import BaseRepository
from app.schemas.skills import (
    DiffFileOut,
    SkillCandidateOut,
    SkillCandidatePage,
    SkillEventListOut,
    SkillEventOut,
    SkillMetricsOut,
    SkillOut,
    SkillPage,
    SkillVersionDiffOut,
    SkillVersionListOut,
    SkillVersionOut,
    SkillVersionSourceOut,
)


def _v(value) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


def _to_skill_out(skill: Skill) -> SkillOut:
    return SkillOut(
        id=skill.id,
        name=skill.name,
        slug=skill.slug,
        description=skill.description,
        category=_v(skill.category),
        status=_v(skill.status),
        currentVersion=skill.current_version,
        metrics=SkillMetricsOut(
            usage_count=skill.usage_count,
            success_rate=float(skill.success_rate),
            evolutions=skill.evolutions,
            avg_token_delta=skill.avg_token_delta,
        ),
        createdAt=skill.created_at,
        updatedAt=skill.updated_at,
    )


def _to_version_out(v: SkillVersion) -> SkillVersionOut:
    return SkillVersionOut(
        id=v.id,
        skillId=v.skill_id,
        version=v.version,
        changelog=v.changelog,
        content=v.content,
        source=SkillVersionSourceOut(type=_v(v.source_type), refId=v.source_ref_id),
        evalScore=float(v.eval_score) if v.eval_score is not None else None,
        createdAt=v.created_at,
    )


def _to_candidate_out(c: SkillCandidate) -> SkillCandidateOut:
    evaluation = None
    if isinstance(c.evaluation, dict) and c.evaluation:
        evaluation = {
            "suite": str(c.evaluation.get("suite", "")),
            "before": float(c.evaluation.get("before", 0)),
            "after": float(c.evaluation.get("after", 0)),
            "sampleSize": int(c.evaluation.get("sampleSize", 0)),
        }
    return SkillCandidateOut(
        id=c.id,
        skillId=c.skill_id,
        kind=_v(c.kind),
        proposedVersion=c.proposed_version,
        summary=c.summary,
        proposedContent=c.proposed_content,
        evidenceTaskIds=list(c.evidence_task_ids or []),
        evaluation=evaluation,
        status=_v(c.status),
        createdAt=c.created_at,
    )


def _next_patch(version: str) -> str:
    parts = version.split(".")
    if len(parts) == 3 and parts[-1].isdigit():
        return f"{parts[0]}.{parts[1]}.{int(parts[2]) + 1}"
    return version + ".1"


class SkillService(BaseRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    # ------------------------------------------------------------------ 查询
    async def list_skills(
        self, *, q: str | None, category: str | None, status: str | None,
        page: int, size: int,
    ) -> SkillPage:
        stmt = select(Skill).order_by(Skill.updated_at.desc())
        if q:
            like = f"%{q}%"
            stmt = stmt.where(or_(Skill.name.ilike(like), Skill.description.ilike(like)))
        if category:
            stmt = stmt.where(Skill.category == category)
        if status:
            stmt = stmt.where(Skill.status == status)
        items, total = await self._paged(stmt, page, size)
        return SkillPage(items=[_to_skill_out(s) for s in items],
                         total=total, page=page, size=size)

    async def get_skill(self, skill_id: str) -> SkillOut:
        skill = await self.session.get(Skill, skill_id)
        if skill is None:
            raise BizException(ErrorCode.NOT_FOUND, f"Skill 不存在: {skill_id}", status_code=404)
        return _to_skill_out(skill)

    async def list_versions(self, skill_id: str) -> SkillVersionListOut:
        await self._require_skill(skill_id)
        rows = list((await self.session.execute(
            select(SkillVersion).where(SkillVersion.skill_id == skill_id)
            .order_by(SkillVersion.created_at.desc(), SkillVersion.id.desc())
        )).scalars().all())
        return SkillVersionListOut(items=[_to_version_out(v) for v in rows])

    async def version_diff(self, skill_id: str, a: str, b: str) -> SkillVersionDiffOut:
        await self._require_skill(skill_id)
        rows = list((await self.session.execute(
            select(SkillVersion).where(SkillVersion.skill_id == skill_id)
        )).scalars().all())
        by_ver = {v.version: v for v in rows}
        va, vb = by_ver.get(a), by_ver.get(b)
        if va is None or vb is None:
            raise BizException(ErrorCode.NOT_FOUND, "版本不存在", status_code=404,
                               details={"missing": [x for x, y in ((a, va), (b, vb)) if y is None]})
        diff = list(difflib.unified_diff(
            va.content.splitlines(), vb.content.splitlines(),
            fromfile=f"{skill_id}@{a}", tofile=f"{skill_id}@{b}", lineterm=""))
        additions = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
        deletions = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
        return SkillVersionDiffOut(
            skillId=skill_id, fromVersion=a, toVersion=b,
            files=[DiffFileOut(path=f"{skill_id}.md", additions=additions,
                               deletions=deletions, patch="\n".join(diff[:3000]))],
        )

    # ------------------------------------------------------------------ 回滚
    async def rollback(self, skill_id: str, target_version: str, reason: str | None) -> SkillOut:
        """回滚 = 以新版本号发布目标版本的内容（版本历史完整、可审计）。"""
        skill = await self._require_skill(skill_id)
        rows = list((await self.session.execute(
            select(SkillVersion).where(SkillVersion.skill_id == skill_id)
        )).scalars().all())
        by_ver = {v.version: v for v in rows}
        target = by_ver.get(target_version)
        if target is None:
            raise BizException(ErrorCode.NOT_FOUND, f"目标版本不存在: {target_version}",
                               status_code=404)
        new_version = _next_patch(skill.current_version)
        v = SkillVersion(
            skill_id=skill_id, version=new_version,
            # changelog 确定性以「回滚」开头：skill_events 以此派生 rolled_back 事件
            changelog=(f"回滚到 {target_version}" + (f"：{reason}" if reason else "")).strip(),
            content=target.content,
            source_type=SkillSource.MANUAL, source_ref_id=target.id,
        )
        skill.current_version = new_version
        skill.updated_at = datetime.now(timezone.utc)
        self.session.add(v)
        await self.session.flush()
        return _to_skill_out(skill)

    # ------------------------------------------------------------------ 候选与审核
    async def list_candidates(
        self, *, status: str | None, page: int, size: int,
    ) -> SkillCandidatePage:
        stmt = select(SkillCandidate).order_by(SkillCandidate.created_at.desc())
        if status:
            stmt = stmt.where(SkillCandidate.status == status)
        items, total = await self._paged(stmt, page, size)
        return SkillCandidatePage(items=[_to_candidate_out(c) for c in items],
                                  total=total, page=page, size=size)

    async def review_candidate(
        self, candidate_id: str, *, decision: str, comment: str | None, reviewer: str,
    ) -> SkillCandidateOut:
        """审核闸门（唯一发布路径）：

        - 仅 pending 可决策（终态不可逆，重复决策 409）；
        - approved → 立即发布：创建正式版本（proposed_version/content），
          skill.current_version 前移，evolutions+1；
        - rejected → 仅记录，不产生任何版本；
        - 未审核候选（pending）永远不会触碰正式版。
        """
        if decision not in ("approved", "rejected"):
            raise BizException(ErrorCode.VALIDATION_ERROR,
                               "decision 仅支持 approved / rejected", status_code=422)
        c = await self.session.get(SkillCandidate, candidate_id)
        if c is None:
            raise BizException(ErrorCode.NOT_FOUND, f"候选不存在: {candidate_id}", status_code=404)
        if c.status != CandidateStatus.PENDING:
            raise BizException(ErrorCode.CONFLICT,
                               f"候选已处于终态（{_v(c.status)}），不可重复审核",
                               status_code=409, details={"currentStatus": _v(c.status)})
        c.status = CandidateStatus.APPROVED if decision == "approved" else CandidateStatus.REJECTED
        c.reviewed_by = reviewer
        c.reviewed_at = datetime.now(timezone.utc)
        if decision == "approved":
            if c.skill_id is None:
                raise BizException(ErrorCode.CONFLICT,
                                   "create 类候选缺 skill_id，无法发布", status_code=409)
            skill = await self._require_skill(c.skill_id)
            v = SkillVersion(
                skill_id=c.skill_id, version=c.proposed_version,
                changelog=f"候选发布：{c.summary[:160]}" + (f"（{comment}）" if comment else ""),
                content=c.proposed_content,
                source_type=SkillSource.EVOLUTION, source_ref_id=c.id,
                eval_score=float(c.evaluation.get("after", 0)) if isinstance(c.evaluation, dict) else None,
            )
            self.session.add(v)
            skill.current_version = c.proposed_version
            skill.evolutions += 1
            skill.updated_at = datetime.now(timezone.utc)
        await self.session.flush()
        return _to_candidate_out(c)

    async def propose_candidate_from_run(self, run_id: str) -> SkillCandidateOut:
        """从任务执行反馈生成候选（MVP：确定性抽取式；LLM 增强待 GLM key）。

        证据：任务标题/失败步骤/最近工具结果。生成的候选固定 pending，
        不触发发布（审核闸门红线）。
        """
        run = await self.session.get(AgentRun, run_id)
        if run is None:
            raise BizException(ErrorCode.NOT_FOUND, f"Run 不存在: {run_id}", status_code=404)
        task = await self.session.get(AgentTask, run.task_id)
        if task is None:
            raise BizException(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
        steps = list((await self.session.execute(
            select(PlanStep).where(PlanStep.plan_id.in_(
                select(Plan.id).where(Plan.run_id == run.id)))
            .order_by(PlanStep.idx.asc())
        )).scalars().all())
        failed = [s.title for s in steps if _v(s.status) == "failed"]
        tools = list((await self.session.execute(
            select(ToolCall).where(ToolCall.run_id == run.id)
            .order_by(ToolCall.created_at.desc()).limit(5)
        )).scalars().all())
        summary = (f"任务「{task.title}」执行反馈："
                   + (f"失败步骤：{'、'.join(failed)}；" if failed else "无失败步骤；")
                   + f"涉及工具：{'、'.join(f'{t.server}.{t.tool}' for t in tools) or '无'}")
        c = SkillCandidate(
            skill_id=None, kind=CandidateKind.CREATE,
            proposed_version="0.1.0",
            summary=summary[:500],
            proposed_content=(f"# {task.title}\n\n## 适用场景\n{task.description[:300]}\n\n"
                              f"## 执行要点\n" + "\n".join(f"- {s.title}" for s in steps) +
                              ("\n\n## 注意事项\n- " + "；".join(failed) if failed else "")),
            evidence_task_ids=[task.id],
            evaluation=None,
            status=CandidateStatus.PENDING,
        )
        self.session.add(c)
        await self.session.flush()
        return _to_candidate_out(c)

    # ------------------------------------------------------------------ 事件/评估/用量
    async def skill_events(self, skill_id: str | None, limit: int = 20) -> SkillEventListOut:
        stmt = select(SkillCandidate).order_by(SkillCandidate.created_at.desc()).limit(limit)
        if skill_id:
            stmt = stmt.where(SkillCandidate.skill_id == skill_id)
        candidates = list((await self.session.execute(stmt)).scalars().all())
        vstmt = select(SkillVersion).order_by(SkillVersion.created_at.desc()).limit(limit)
        if skill_id:
            vstmt = vstmt.where(SkillVersion.skill_id == skill_id)
        versions = list((await self.session.execute(vstmt)).scalars().all())
        items: list[tuple[datetime, SkillEventOut]] = []
        for v in versions:
            rolled = v.changelog.startswith("回滚")
            items.append((v.created_at, SkillEventOut(
                id=v.id, skillId=v.skill_id,
                type="rolled_back" if rolled else "created",
                message=v.changelog[:200] or f"{v.version} 发布",
                createdAt=v.created_at)))
        for c in candidates:
            ctype = {"pending": "proposed", "approved": "approved", "rejected": "rejected"}[_v(c.status)]
            items.append((c.created_at, SkillEventOut(
                id=c.id, skillId=c.skill_id, type=ctype,
                message=f"候选（{_v(c.kind)}）：{c.summary[:160]}",
                createdAt=c.created_at)))
        items.sort(key=lambda x: x[0], reverse=True)
        return SkillEventListOut(items=[e for _, e in items[:limit]])

    async def list_evaluations(self, skill_id: str) -> SkillEvaluationListOut:
        await self._require_skill(skill_id)
        rows = list((await self.session.execute(
            select(SkillEvaluation).where(SkillEvaluation.skill_id == skill_id)
            .order_by(SkillEvaluation.created_at.desc())
        )).scalars().all())
        from app.schemas.skills import SkillEvaluationListOut, SkillEvaluationOut

        return SkillEvaluationListOut(items=[SkillEvaluationOut(
            id=e.id, skillId=e.skill_id, versionId=e.version_id,
            suite=e.suite, before=float(e.before_score), after=float(e.after_score),
            sampleSize=e.sample_size, createdAt=e.created_at,
        ) for e in rows])

    async def list_usages(self, skill_id: str, cursor: str | None, limit: int = 50):
        await self._require_skill(skill_id)
        # agent_tasks.skill_ids 为 JSONB 数组：@> 包含查询
        from sqlalchemy import text as sa_text

        stmt = select(AgentTask).where(
            sa_text("agent_tasks.skill_ids @> CAST(:pat AS jsonb)").bindparams(
                pat=json.dumps([skill_id]))
        ).order_by(AgentTask.created_at.desc(), AgentTask.id.desc())
        if cursor:
            stmt = stmt.where(AgentTask.id < cursor)
        rows = list((await self.session.execute(stmt.limit(limit))).scalars().all())
        from app.schemas.skills import SkillUsageItemOut, SkillUsageListOut

        return SkillUsageListOut(items=[SkillUsageItemOut(
            taskId=t.id, title=t.title, status=_v(t.status), createdAt=t.created_at,
        ) for t in rows])

    # ------------------------------------------------------------------ 内部
    async def _require_skill(self, skill_id: str) -> Skill:
        skill = await self.session.get(Skill, skill_id)
        if skill is None:
            raise BizException(ErrorCode.NOT_FOUND, f"Skill 不存在: {skill_id}", status_code=404)
        return skill
