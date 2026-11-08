"""上下文域：context_snapshots（决策 #6：Run 1:N 版本化）+ memory_items。

- 每次压缩生成新快照、保留历史；is_current 部分唯一索引保证同 run 至多一个当前版本
- 记录 trigger / before_tokens / after_tokens / summary / compressed_at
- memory_items：PG 存元数据，向量在 Chroma（P3），以 id 关联
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum as SaEnum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import ContextTrigger, MemoryLayer, enum_values
from app.models.base import Base, PkMixin, TimestampMixin

# 部分唯一索引条件：仅对当前有效快照生效（is_current IS TRUE）
text_is_current = text("is_current IS TRUE")

CONTEXT_TRIGGER_ENUM = SaEnum(
    ContextTrigger, values_callable=enum_values, native_enum=False, length=16, name="context_trigger"
)
MEMORY_LAYER_ENUM = SaEnum(
    MemoryLayer, values_callable=enum_values, native_enum=False, length=16, name="memory_layer"
)


class ContextSnapshot(PkMixin, TimestampMixin, Base):
    __tablename__ = "context_snapshots"
    __id_prefix__ = "ctx"
    __table_args__ = (
        UniqueConstraint("run_id", "version", name="uq_context_snapshots_run_version"),
        # 同一 run 至多一个当前有效快照（部分唯一索引）
        Index(
            "uq_context_snapshots_current",
            "run_id",
            unique=True,
            postgresql_where=text_is_current,
        ),
        Index("ix_context_snapshots_run_version", "run_id", "version"),
    )

    run_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    window_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=128_000)
    used_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{key: system|skill|memory|history|working|compressed, tokens}]
    segments: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # 本快照产生原因与压缩记录（initial 快照这些列为空）
    trigger: Mapped[ContextTrigger] = mapped_column(
        CONTEXT_TRIGGER_ENUM, nullable=False, default=ContextTrigger.INITIAL
    )
    before_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    after_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 压缩时间：仅压缩产生的快照有值（initial 为 NULL）
    compressed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryItem(PkMixin, TimestampMixin, Base):
    __tablename__ = "memory_items"
    __id_prefix__ = "mem"
    __table_args__ = (Index("ix_memory_items_layer", "layer"),)

    layer: Mapped[MemoryLayer] = mapped_column(
        MEMORY_LAYER_ENUM, nullable=False, default=MemoryLayer.EPISODIC
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # SET NULL：任务删除后记忆仍保留（额外检查 #5）
    source_task_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("agent_tasks.id", ondelete="SET NULL"), nullable=True
    )
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False, default=0)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
