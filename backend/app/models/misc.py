"""杂项域：model_usage（模型调用成本）/ settings（KV+JSONB，非敏感）。"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PkMixin, TimestampMixin


class ModelUsage(PkMixin, TimestampMixin, Base):
    """每次模型调用一行：Dashboard/Evaluation 的 Token 与成本聚合源。"""

    __tablename__ = "model_usage"
    __id_prefix__ = "mu"
    __table_args__ = (Index("ix_model_usage_model_created_at", "model", "created_at"),)

    # SET NULL：运行/任务删除后成本统计保留（额外检查 #5）
    run_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True
    )
    task_id: Mapped[str | None] = mapped_column(
        String(40), ForeignKey("agent_tasks.id", ondelete="SET NULL"), nullable=True
    )
    model: Mapped[str] = mapped_column(String(40), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class Setting(PkMixin, TimestampMixin, Base):
    """非敏感配置 KV：models / routing / mcp / permissions / system（决策 #4）。

    敏感信息（GLM_API_KEY 等）只走环境变量，绝不入此表。
    """

    __tablename__ = "settings"
    __id_prefix__ = "set"
    __table_args__ = (Index("ix_settings_key", "key"),)

    key: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    # 兼容 kv 主键语义：key 唯一由应用层保证（id 仍为主键，避免改 PK 约定）
    value: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
