"""执行域：tool_calls / approvals / agent_execution_logs（docs/08 §3.3）。

- agent_execution_logs：事件溯源表，UNIQUE(run_id, seq)（额外检查 #2），
  是 SSE Last-Event-ID 断点续传的数据源（额外检查 #3）
- approvals：同一 tool_call 至多一条 pending（PG 部分唯一索引保证）
- 状态流转守卫在 service 层（额外检查 #4）
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum as SaEnum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import (
    ApprovalResolvedBy,
    ApprovalStatus,
    RiskLevel,
    ToolCallStatus,
    enum_values,
)
from app.models.base import Base, PkMixin, TimestampMixin

RISK_ENUM = SaEnum(RiskLevel, values_callable=enum_values, native_enum=False, length=16, name="risk_level")
TOOL_STATUS_ENUM = SaEnum(
    ToolCallStatus, values_callable=enum_values, native_enum=False, length=16, name="tool_call_status"
)
APPROVAL_STATUS_ENUM = SaEnum(
    ApprovalStatus, values_callable=enum_values, native_enum=False, length=16, name="approval_status"
)
APPROVAL_RESOLVED_BY_ENUM = SaEnum(
    ApprovalResolvedBy, values_callable=enum_values, native_enum=False, length=8, name="approval_resolved_by"
)


class ToolCall(PkMixin, TimestampMixin, Base):
    __tablename__ = "tool_calls"
    __id_prefix__ = "tc"
    __table_args__ = (Index("ix_tool_calls_run_id_created_at", "run_id", "created_at"),)

    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    plan_step_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("plan_steps.id", ondelete="SET NULL"), nullable=True
    )
    server: Mapped[str] = mapped_column(String(64), nullable=False)
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    args: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 原始结果（可能很大，P2 起按需查询返回）
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[ToolCallStatus] = mapped_column(
        TOOL_STATUS_ENUM, nullable=False, default=ToolCallStatus.RUNNING
    )
    risk: Mapped[RiskLevel] = mapped_column(RISK_ENUM, nullable=False, default=RiskLevel.SAFE)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Approval(PkMixin, TimestampMixin, Base):
    __tablename__ = "approvals"
    __id_prefix__ = "apv"
    __table_args__ = (
        Index("ix_approvals_status", "status"),
        # 同一工具调用至多一条待审批（PG 部分唯一索引）
        Index(
            "uq_approvals_pending_per_call",
            "tool_call_id",
            unique=True,
            postgresql_where=text("status = 'pending'"),
        ),
    )

    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    tool_call_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("tool_calls.id", ondelete="CASCADE"), nullable=False
    )
    tool: Mapped[str] = mapped_column(String(128), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    risk: Mapped[RiskLevel] = mapped_column(RISK_ENUM, nullable=False, default=RiskLevel.DANGEROUS)
    status: Mapped[ApprovalStatus] = mapped_column(
        APPROVAL_STATUS_ENUM, nullable=False, default=ApprovalStatus.PENDING
    )
    resolved_by: Mapped[ApprovalResolvedBy | None] = mapped_column(APPROVAL_RESOLVED_BY_ENUM, nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)


class AgentExecutionLog(PkMixin, Base):
    """事件溯源表：每条 SSE 事件一行；(run_id, seq) 数据库级唯一，支撑断点续传。"""

    __tablename__ = "agent_execution_logs"
    __id_prefix__ = "evt"
    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_execution_logs_run_seq"),
        Index("ix_execution_logs_run_seq", "run_id", "seq"),
    )

    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # 完整事件信封 payload（docs/06 §4 的 payload 部分）
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
