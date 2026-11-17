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

    # B2 工具执行与隔离（应用层访问控制，非 OS 级沙箱；容器 Provider 见 core/sandbox.py）
    WORKSPACE_BASE: str = "./data/workspace"
    TOOL_TIMEOUT_SECONDS: int = 30
    TOOL_MAX_RETRIES: int = 2
    TOOL_MAX_STEPS: int = 20
    TOOL_OUTPUT_LIMIT_BYTES: int = 1_000_000

    # B3 LLM / Agent 编排（真实模型参与决策；GLM_API_KEY 走环境变量，绝不入代码/日志）
    GLM_MODEL: str = "glm-5.3"
    GLM_FLASH_MODEL: str = "glm-5.3-flash"
    LLM_TIMEOUT_SECONDS: int = 60
    LLM_TEMPERATURE: float = 0.2
    LLM_MAX_TOKENS: int = 4096
    AGENT_MAX_REPLANS: int = 2
    AGENT_STEP_TURNS: int = 6          # 单个 step 内最多 LLM 决策轮数
    SSE_HEARTBEAT_SECONDS: int = 15
    SSE_POLL_SECONDS: float = 0.5

    # B6 RAG（Embedding Provider 独立抽象，不与主对话模型强绑定）
    GLM_EMBEDDING_MODEL: str = "embedding-3"
    GLM_EMBEDDING_DIM: int = 1024
    RAG_DATA_DIR: str = "./data/rag"
    RAG_CHUNK_CHARS: int = 800
    RAG_CHUNK_OVERLAP: int = 100
    RAG_TOPK: int = 5
    RAG_RRF_K: int = 60

    # B7 多模态（OCR / 图片理解 / 图表问答为三个分立能力，分别验收）
    GLM_VISION_MODEL: str = "glm-4v-plus"
    MULTIMODAL_TIMEOUT_SECONDS: int = 60
    MULTIMODAL_MAX_IMAGE_BYTES: int = 5_000_000
    MULTIMODAL_ALLOWED_MIME: str = "image/png,image/jpeg,image/webp"

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
