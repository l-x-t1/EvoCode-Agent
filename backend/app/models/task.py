"""任务域：agent_tasks / agent_runs / plans / plan_steps（docs/08 §3.3）。

- AgentTask：开发任务聚合根（状态 + 统计冗余列，供 Dashboard 聚合）
- AgentRun：任务的一次执行（SSE 事件、工具调用、审批都挂在 Run 上）
- Plan/PlanStep：计划带 revision，重规划追加新 Plan
"""

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
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    AgentRole,
    PlanStepStatus,
    TaskStatus,
    enum_values,
)
from app.models.base import Base, PkMixin, TimestampMixin

TASK_STATUS_ENUM = SaEnum(
    TaskStatus, values_callable=enum_values, native_enum=False, length=32, name="task_status"
)
AGENT_ROLE_ENUM = SaEnum(
    AgentRole, values_callable=enum_values, native_enum=False, length=32, name="agent_role"
)
PLAN_STEP_STATUS_ENUM = SaEnum(
    PlanStepStatus, values_callable=enum_values, native_enum=False, length=32, name="plan_step_status"
)


class AgentTask(PkMixin, TimestampMixin, Base):
    __tablename__ = "agent_tasks"
    __id_prefix__ = "task"
    __table_args__ = (
        Index("ix_agent_tasks_status_updated_at", "status", "updated_at"),
        Index("ix_agent_tasks_user_id", "user_id"),
    )

    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    repo: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[TaskStatus] = mapped_column(
        TASK_STATUS_ENUM, nullable=False, default=TaskStatus.QUEUED
    )
    model: Mapped[str] = mapped_column(String(40), nullable=False, default="auto")
    # 引用的 Skill id 列表（MVP 用 JSONB；P3 若需反查可规范化为关联表）
    skill_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # 最近一次 Run 的冗余指针（无 FK，避免 task↔run 循环外键）
    latest_run_id: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # 聚合统计（冗余列，Run 终态时回写）
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    test_pass_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)


class AgentRun(PkMixin, TimestampMixin, Base):
    __tablename__ = "agent_runs"
    __id_prefix__ = "run"
    __table_args__ = (
        Index("ix_agent_runs_task_id_created_at", "task_id", "created_at"),
        Index("ix_agent_runs_status", "status"),
    )

    task_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[TaskStatus] = mapped_column(
        TASK_STATUS_ENUM, nullable=False, default=TaskStatus.QUEUED
    )
    model: Mapped[str] = mapped_column(String(40), nullable=False, default="glm-5.3")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replan_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_in: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tool_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    test_pass_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)


class Plan(PkMixin, Base):
    __tablename__ = "plans"
    __id_prefix__ = "plan"
    __table_args__ = (UniqueConstraint("run_id", "revision", name="uq_plans_run_revision"),)

    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PlanStep(PkMixin, Base):
    __tablename__ = "plan_steps"
    __id_prefix__ = "step"

    plan_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("plans.id", ondelete="CASCADE"), nullable=False
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent: Mapped[AgentRole] = mapped_column(AGENT_ROLE_ENUM, nullable=False)
    status: Mapped[PlanStepStatus] = mapped_column(
        PLAN_STEP_STATUS_ENUM, nullable=False, default=PlanStepStatus.PENDING
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    tool_call_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
