"""会话域：conversations / messages（docs/08 决策 #3）。

- Conversation = 对话线程（消息挂在它下面）
- MVP 与 AgentTask 1:1 由 service 层保证；task_id 只建普通索引不建 UNIQUE，
  为未来「一任务多会话」保留迁移零成本的扩展空间
"""

from __future__ import annotations

from sqlalchemy import Enum as SaEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import AgentRole, enum_values
from app.models.base import Base, PkMixin, TimestampMixin

AGENT_ROLE_ENUM = SaEnum(
    AgentRole, values_callable=enum_values, native_enum=False, length=32, name="agent_role"
)


class Conversation(PkMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __id_prefix__ = "conv"
    __table_args__ = (Index("ix_conversations_task_id", "task_id"),)

    task_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_tasks.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")


class Message(PkMixin, TimestampMixin, Base):
    __tablename__ = "messages"
    __id_prefix__ = "msg"
    __table_args__ = (Index("ix_messages_conversation_created_at", "conversation_id", "created_at"),)

    conversation_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    # 用户首条消息先于 Run 产生，因此可空
    run_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=True
    )
    role: Mapped[AgentRole] = mapped_column(AGENT_ROLE_ENUM, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
