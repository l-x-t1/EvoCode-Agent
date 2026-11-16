"""skills 域路由（docs/06 §3.4 子集，10 端点）。

注意路由声明顺序：/skills/candidates 必须先于 /skills/{skill_id} 注册，
否则 candidates 会被当作 skill_id 捕获。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.skills import (
    RollbackIn,
    SkillCandidateOut,
    SkillCandidatePage,
    SkillEventListOut,
    SkillEvaluationListOut,
    SkillOut,
    SkillPage,
    SkillReviewIn,
    SkillUsageListOut,
    SkillVersionDiffOut,
    SkillVersionListOut,
)
from app.skills.service import SkillService

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("/candidates", response_model=SkillCandidatePage)
async def list_candidates(
    status: str = Query(default="pending", pattern="^(pending|approved|rejected)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillCandidatePage:
    return await SkillService(session).list_candidates(status=status, page=page, size=size)


@router.post("/candidates/{candidate_id}/review", response_model=SkillCandidateOut)
async def review_candidate(
    candidate_id: str,
    body: SkillReviewIn,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> SkillCandidateOut:
    """候选审核（唯一发布路径）：approved → 发布正式版本；rejected → 仅记录。

    重复审核 409；未审核候选永远无法影响 skill.current_version。
    """
    return await SkillService(session).review_candidate(
        candidate_id, decision=body.decision, comment=body.comment,
        reviewer=user.display_name,
    )


@router.get("", response_model=SkillPage)
async def list_skills(
    q: str | None = Query(default=None, max_length=120),
    category: str | None = Query(default=None,
                                 pattern="^(testing|refactor|debugging|docs|workflow|other)$"),
    status: str | None = Query(default=None, pattern="^(active|draft|deprecated)$"),
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillPage:
    return await SkillService(session).list_skills(
        q=q, category=category, status=status, page=page, size=size)


@router.get("/events", response_model=SkillEventListOut)
async def list_skill_events(
    skillId: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> SkillEventListOut:
    return await SkillService(session).skill_events(skill_id=skillId, limit=limit)


@router.get("/{skill_id}", response_model=SkillOut)
async def get_skill(
    skill_id: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillOut:
    return await SkillService(session).get_skill(skill_id)


@router.get("/{skill_id}/versions", response_model=SkillVersionListOut)
async def list_versions(
    skill_id: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillVersionListOut:
    return await SkillService(session).list_versions(skill_id)


@router.get("/{skill_id}/versions/{a}/diff/{b}", response_model=SkillVersionDiffOut)
async def version_diff(
    skill_id: str, a: str, b: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillVersionDiffOut:
    return await SkillService(session).version_diff(skill_id, a, b)


@router.post("/{skill_id}/rollback", response_model=SkillOut)
async def rollback_skill(
    skill_id: str,
    body: RollbackIn,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillOut:
    """版本回滚：以新版本号发布目标版本内容（历史完整、事件可派生）。"""
    return await SkillService(session).rollback(skill_id, body.targetVersion, body.reason)


@router.get("/{skill_id}/evaluations", response_model=SkillEvaluationListOut)
async def list_evaluations(
    skill_id: str,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillEvaluationListOut:
    return await SkillService(session).list_evaluations(skill_id)


@router.get("/{skill_id}/usages", response_model=SkillUsageListOut)
async def list_usages(
    skill_id: str,
    cursor: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
) -> SkillUsageListOut:
    return await SkillService(session).list_usages(skill_id, cursor)
