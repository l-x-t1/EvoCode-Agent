"""Skill 域响应模型（对齐前端 types/api.ts，docs/06 §2/§3.4）。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel

from app.core.response import Page
from app.schemas.common import CamelModel


class SkillMetricsOut(CamelModel):
    usage_count: int
    success_rate: float
    evolutions: int
    avg_token_delta: int


class SkillOut(CamelModel):
    id: str
    name: str
    slug: str
    description: str
    category: str
    status: str
    currentVersion: str
    metrics: SkillMetricsOut
    createdAt: datetime
    updatedAt: datetime


class SkillPage(Page[SkillOut]):
    pass


class SkillVersionSourceOut(CamelModel):
    type: str  # task | evolution | manual
    refId: str | None = None


class SkillVersionOut(CamelModel):
    id: str
    skillId: str
    version: str
    changelog: str
    content: str
    source: SkillVersionSourceOut
    evalScore: float | None = None
    createdAt: datetime


class SkillVersionListOut(CamelModel):
    items: list[SkillVersionOut] = []


class DiffFileOut(CamelModel):
    path: str
    additions: int
    deletions: int
    patch: str


class SkillVersionDiffOut(CamelModel):
    skillId: str
    fromVersion: str
    toVersion: str
    files: list[DiffFileOut] = []


class SkillCandidateEvaluationOut(CamelModel):
    suite: str
    before: float
    after: float
    sampleSize: int


class SkillCandidateOut(CamelModel):
    id: str
    skillId: str | None = None
    kind: str  # create | revise
    proposedVersion: str
    summary: str
    proposedContent: str
    evidenceTaskIds: list[str] = []
    evaluation: SkillCandidateEvaluationOut | None = None
    status: str  # pending | approved | rejected
    createdAt: datetime


class SkillCandidatePage(Page[SkillCandidateOut]):
    pass


class SkillReviewIn(CamelModel):
    decision: str  # approved | rejected
    comment: str | None = None


class SkillEventOut(CamelModel):
    id: str
    skillId: str | None = None
    type: str  # proposed | approved | rejected | rolled_back | created
    message: str
    createdAt: datetime


class SkillEventListOut(CamelModel):
    items: list[SkillEventOut] = []


class SkillEvaluationOut(CamelModel):
    id: str
    skillId: str
    versionId: str | None = None
    suite: str
    before: float
    after: float
    sampleSize: int
    createdAt: datetime


class SkillEvaluationListOut(CamelModel):
    items: list[SkillEvaluationOut] = []


class SkillUsageItemOut(CamelModel):
    taskId: str
    title: str
    status: str
    createdAt: datetime


class SkillUsageListOut(CamelModel):
    items: list[SkillUsageItemOut] = []


class RollbackIn(CamelModel):
    targetVersion: str
    reason: str | None = None
