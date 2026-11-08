"""Skill 域：skills / skill_versions / skill_evaluations / skill_candidates（docs/08 §3.3）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum as SaEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    CandidateKind,
    CandidateStatus,
    SkillCategory,
    SkillSource,
    SkillStatus,
    enum_values,
)
from app.models.base import Base, PkMixin, TimestampMixin

SKILL_CATEGORY_ENUM = SaEnum(
    SkillCategory, values_callable=enum_values, native_enum=False, length=32, name="skill_category"
)
SKILL_STATUS_ENUM = SaEnum(
    SkillStatus, values_callable=enum_values, native_enum=False, length=16, name="skill_status"
)
SKILL_SOURCE_ENUM = SaEnum(
    SkillSource, values_callable=enum_values, native_enum=False, length=16, name="skill_source"
)
CANDIDATE_KIND_ENUM = SaEnum(
    CandidateKind, values_callable=enum_values, native_enum=False, length=8, name="candidate_kind"
)
CANDIDATE_STATUS_ENUM = SaEnum(
    CandidateStatus, values_callable=enum_values, native_enum=False, length=16, name="candidate_status"
)


class Skill(PkMixin, TimestampMixin, Base):
    __tablename__ = "skills"
    __id_prefix__ = "skill"
    __table_args__ = (Index("ix_skills_status_category", "status", "category"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    category: Mapped[SkillCategory] = mapped_column(
        SKILL_CATEGORY_ENUM, nullable=False, default=SkillCategory.OTHER
    )
    status: Mapped[SkillStatus] = mapped_column(
        SKILL_STATUS_ENUM, nullable=False, default=SkillStatus.ACTIVE
    )
    current_version: Mapped[str] = mapped_column(String(20), nullable=False, default="0.1.0")

    # 指标列（评测/进化回写）
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    evolutions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_token_delta: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SkillVersion(PkMixin, TimestampMixin, Base):
    __tablename__ = "skill_versions"
    __id_prefix__ = "sver"
    __table_args__ = (UniqueConstraint("skill_id", "version", name="uq_skill_versions_skill_version"),)

    skill_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    changelog: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_type: Mapped[SkillSource] = mapped_column(
        SKILL_SOURCE_ENUM, nullable=False, default=SkillSource.MANUAL
    )
    source_ref_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    eval_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)


class SkillEvaluation(PkMixin, TimestampMixin, Base):
    __tablename__ = "skill_evaluations"
    __id_prefix__ = "seval"

    skill_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="CASCADE"), nullable=False
    )
    version_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("skill_versions.id", ondelete="SET NULL"), nullable=True
    )
    suite: Mapped[str] = mapped_column(String(120), nullable=False)
    before_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    after_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class SkillCandidate(PkMixin, TimestampMixin, Base):
    """候选 Skill 审核队列（进化闭环的人工闸门）。"""

    __tablename__ = "skill_candidates"
    __id_prefix__ = "cand"
    __table_args__ = (Index("ix_skill_candidates_status", "status"),)

    # 为空 = 新增 Skill
    skill_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("skills.id", ondelete="CASCADE"), nullable=True
    )
    kind: Mapped[CandidateKind] = mapped_column(
        CANDIDATE_KIND_ENUM, nullable=False, default=CandidateKind.CREATE
    )
    proposed_version: Mapped[str] = mapped_column(String(20), nullable=False, default="1.0.0")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence_task_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # {suite, before, after, sampleSize}，评测完成后回填
    evaluation: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[CandidateStatus] = mapped_column(
        CANDIDATE_STATUS_ENUM, nullable=False, default=CandidateStatus.PENDING
    )
    reviewed_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
