"""users：预留鉴权主体（P1 无鉴权，seed 本地用户）。"""

from __future__ import annotations

from sqlalchemy import Boolean, String, false
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, PkMixin, TimestampMixin


class User(PkMixin, TimestampMixin, Base):
    __tablename__ = "users"
    __id_prefix__ = "user"

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False, default="local")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=false())
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="owner")
