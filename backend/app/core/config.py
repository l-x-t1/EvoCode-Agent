"""应用配置（docs/08 §5）。

- 全部配置来自环境变量 / .env，密钥不进代码（开发约束 3）
- 敏感字段用 SensitiveStr：repr 遮蔽，日志过滤器二次兜底（额外检查 #7）
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SensitiveStr(str):
    """敏感字符串：repr 永远返回 '***'，避免被日志/异常意外泄露。"""

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return "'***'"

    def __format__(self, format_spec: str) -> str:
        return format(str(self), format_spec)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env",),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # 应用
    APP_NAME: str = "EvoCode Agent API"
    APP_VERSION: str = "0.1.0"
    ENV: str = "dev"  # dev | prod
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"

    # 数据层
    DATABASE_URL: str = "postgresql+asyncpg://evocode:evocode@localhost:5432/evocode"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 5
    REDIS_URL: str = "redis://localhost:6379/0"

    # 向量库（P3 启用）
    CHROMA_PERSIST_DIR: str = "./data/chroma"

    # CORS（逗号分隔）
    ALLOWED_ORIGINS: str = "http://localhost:5173"

    # 敏感配置（只走环境变量，绝不入库：决策 #4）
    GLM_API_KEY: SensitiveStr = SensitiveStr("")
    GLM_BASE_URL: str = "https://open.bigmodel.cn/api/paas/v4"
    MASTER_KEY: SensitiveStr = SensitiveStr("")

    @field_validator("GLM_API_KEY", "MASTER_KEY", mode="before")
    @classmethod
    def _to_sensitive(cls, v: object) -> SensitiveStr:
        """环境变量读入的 plain str 统一装箱为 SensitiveStr。"""
        if isinstance(v, SensitiveStr):
            return v
        return SensitiveStr("" if v is None else str(v))

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def is_dev(self) -> bool:
        return self.ENV == "dev"


@lru_cache
def get_settings() -> Settings:
    return Settings()
