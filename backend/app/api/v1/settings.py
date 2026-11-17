"""Settings 五域路由（B8）：models/routing/mcp/permissions/system KV 读写。

- GET：settings 表无行 → 代码内置默认值（models 域 keyMasked 掩码，绝不回显完整 key）
- PUT：任意 JSON 对象 upsert（服务端只存不解释）
- POST /settings/models/test：真实连通测试（key 缺失/网络错误 → ok:false，不抛 500）
- POST /settings/mcp/{id}/discover：MCP 引擎未实现 → 501 mcp_unavailable（诚实）
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.enums import TaskStatus  # noqa: F401
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.llm.client import LLMMessage, get_llm_client
from app.models.misc import Setting
from app.schemas.settings import DiscoverOut, ModelsTestOut

router = APIRouter(prefix="/settings", tags=["settings"])

DOMAINS = ("models", "routing", "mcp", "permissions", "system")

_DEFAULTS: dict[str, object] = {
    "models": {
        "keyMasked": "未配置",
        "baseUrl": "https://open.bigmodel.cn/api/paas/v4",
        "models": [
            {"id": "glm-5.3", "temperature": 0.2, "maxTokens": 4096, "enabled": True},
            {"id": "glm-5.3-flash", "temperature": 0.3, "maxTokens": 2048, "enabled": True},
        ],
    },
    "routing": [],
    "mcp": {"servers": []},
    "permissions": [],
    "system": {
        "contextWindowTokens": 32_000,
        "compressionThreshold": 24_000,
        "maxRetries": 2,
        "sandboxEnabled": False,
        "maxConcurrency": 1,
    },
}


def _mask_key(key: str) -> str:
    if not key.strip():
        return "未配置"
    tail = key[-4:] if len(key) >= 4 else key
    return f"已配置（****{tail}）"


def _masked_models_value(base: dict) -> dict:
    """models 域响应注入 keyMasked（覆盖已存值，保证不泄露真实 key）。"""
    settings = get_settings()
    value = dict(base) if isinstance(base, dict) else dict(_DEFAULTS["models"])
    value["keyMasked"] = _mask_key(str(settings.GLM_API_KEY))
    value.setdefault("baseUrl", settings.GLM_BASE_URL)
    return value


async def _read_row(session: AsyncSession, domain: str) -> Setting | None:
    return (await session.execute(
        select(Setting).where(Setting.key == domain)
    )).scalar_one_or_none()


def _domain_or_422(domain: str) -> str:
    if domain not in DOMAINS:
        raise BizException(
            ErrorCode.VALIDATION_ERROR,
            f"非法 settings 域: {domain}（允许 {', '.join(DOMAINS)}）",
            status_code=422,
        )
    return domain


@router.get("/{domain}")
async def get_settings_domain(domain: str, session: AsyncSession = Depends(get_db)) -> object:
    domain = _domain_or_422(domain)
    row = await _read_row(session, domain)
    if row is not None:
        value = row.value
    else:
        value = _DEFAULTS[domain]
    if domain == "models":
        stored = value if isinstance(value, dict) else {}
        value = _masked_models_value(stored)
    return value


@router.put("/{domain}")
async def put_settings_domain(
    domain: str, body: object, session: AsyncSession = Depends(get_db)
) -> object:
    domain = _domain_or_422(domain)
    if domain == "models" and isinstance(body, dict):
        body = _masked_models_value(body)   # keyMasked 以服务端为准（不泄露/不接受真实 key）
    row = await _read_row(session, domain)
    if row is None:
        row = Setting(key=domain, value=body)
        session.add(row)
    else:
        row.value = body
        row.updated_at = row.updated_at  # TimestampMixin onupdate 由 ORM 处理
    await session.flush()
    return body


@router.post("/models/test", response_model=ModelsTestOut)
async def test_models() -> ModelsTestOut:
    """真实连通测试：key 缺失/网络错误 → ok:false（HTTP 200 携带结果，不抛 500）。"""
    settings = get_settings()
    client = get_llm_client()
    if not client.configured:
        return ModelsTestOut(ok=False, model=settings.GLM_MODEL,
                             error="GLM_API_KEY 未配置")
    start = time.perf_counter()
    try:
        resp = await client.chat([LLMMessage(role="user", content="ping")], max_tokens=1)
        return ModelsTestOut(ok=True, model=resp.model,
                             latencyMs=int((time.perf_counter() - start) * 1000))
    except BizException as exc:
        return ModelsTestOut(ok=False, model=settings.GLM_MODEL, error=exc.message)


@router.post("/mcp/{server_id}/discover", response_model=DiscoverOut)
async def mcp_discover(server_id: str) -> DiscoverOut:
    """MCP 引擎未实现（MVP 范围外）：诚实 501，不假装发现工具。"""
    raise BizException(ErrorCode.MCP_UNAVAILABLE,
                       f"MCP 引擎未实现，无法发现 {server_id} 的工具", status_code=501)
