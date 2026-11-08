"""SQLAlchemy 声明基座（docs/08 额外检查 #1）。

- 主键：前缀 + ULID（应用侧生成，主键唯一约束兜底）
- 约束命名约定：Alembic autogenerate 稳定 diff 的前提
- 时间戳：UTC（timestamptz），created/updated 全表统一
"""

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from sqlalchemy import DateTime, MetaData, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column
from ulid import default_generator as _ulid_gen

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def prefixed_ulid(prefix: str) -> str:
    """生成 `task_01j9...` 形式的主键（26 位 ULID，输出即小写）。"""
    return f"{prefix}_{_ulid_gen.generate()}"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class PkMixin:
    """字符串主键 Mixin；子类通过 __id_prefix__ 注入前缀。"""

    __id_prefix__: ClassVar[str] = "id"

    @declared_attr
    @classmethod
    def id(cls) -> Mapped[str]:
        prefix = cls.__id_prefix__
        return mapped_column(
            String(40),
            primary_key=True,
            default=lambda: prefixed_ulid(prefix),
        )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
