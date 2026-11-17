"""settings 域 schema（B8）：与前端 types/api.ts ModelSettings/SystemParams 对齐。

settings KV 服务端「只存不解释」：PUT 接受任意 JSON 对象，GET 无行时返回内置默认值。
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class ModelEntryOut(CamelModel):
    id: str
    temperature: float
    max_tokens: int
    enabled: bool


class ModelsSettingsOut(CamelModel):
    key_masked: str
    base_url: str
    models: list[ModelEntryOut] = []


class ModelTestOut(CamelModel):
    """POST /settings/models/test：HTTP 200 携带 ok=false 表达失败，不抛异常。"""

    ok: bool
    model: str | None = None
    latency_ms: int | None = None
    error: str | None = None


# ── 内置默认值（settings 表无行时返回；keyMasked/baseUrl 由端点按环境实时计算）──

DEFAULT_MODELS_STATIC: dict = {
    "models": [
        {"id": "glm-5.3", "temperature": 0.2, "maxTokens": 4096, "enabled": True},
        {"id": "glm-5.3-flash", "temperature": 0.3, "maxTokens": 2048, "enabled": True},
    ],
}

DEFAULT_ROUTING: list = []

DEFAULT_MCP: dict = {"servers": []}

DEFAULT_PERMISSIONS: list = []

DEFAULT_SYSTEM: dict = {
    "contextWindowTokens": 32000,
    "compressionThreshold": 24000,
    "maxRetries": 2,
    "sandboxEnabled": False,
    "maxConcurrency": 1,
}

# settings 表合法 domain（非法 → FastAPI 路径校验 422 validation_error）
SETTINGS_DOMAINS = ("models", "routing", "mcp", "permissions", "system")
