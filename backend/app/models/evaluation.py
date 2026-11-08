"""评测域：eval_runs / eval_cases（docs/08 §3.3）。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SaEnum,
    ForeignKey,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import EvalRunStatus, enum_values
from app.models.base import Base, PkMixin, TimestampMixin

EVAL_STATUS_ENUM = SaEnum(
    EvalRunStatus, values_callable=enum_values, native_enum=False, length=16, name="eval_run_status"
)


class EvalRun(PkMixin, TimestampMixin, Base):
    """评测批次：对同一评测集跑一批任务，产出成功率/成本。"""

    __tablename__ = "eval_runs"
    __id_prefix__ = "eval"

    suite: Mapped[str] = mapped_column(String(120), nullable=False)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    avg_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[EvalRunStatus] = mapped_column(
        EVAL_STATUS_ENUM, nullable=False, default=EvalRunStatus.RUNNING
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class EvalCase(PkMixin, TimestampMixin, Base):
    __tablename__ = "eval_cases"
    __id_prefix__ = "ecase"

    eval_run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    task_id: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
