"""settings 域路由（B8）：GET/PUT /settings/{domain} + models/test + mcp discover。

- KV 服务端只存不解释：PUT 接受任意 JSON 对象并 upsert settings 表
- GET 无行时返回内置默认值；models 域的 keyMasked 每次按环境实时计算，
  绝不返回 GLM_API_KEY 原文
- MCP 引擎未实现：discover 诚实返回 501 mcp_unavailable（不虚构工具列表）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.config import get_settings
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.llm.client import GLMClient, LLMMessage
from app.models.misc import Setting
from app.schemas.settings import (
    DEFAULT_MCP,
    DEFAULT_MODELS_STATIC,
    DEFAULT_PERMISSIONS,
    DEFAULT_ROUTING,
    DEFAULT_SYSTEM,
    SETTINGS_DOMAINS,
    ModelTestOut,
)

router = APIRouter(prefix="/settings", tags=["settings"])

_DOMAIN_PATTERN = "|".join(SETTINGS_DOMAINS)

_DEFAULTS: dict[str, Any] = {
    "routing": DEFAULT_ROUTING,
    "mcp": DEFAULT_MCP,
    "permissions": DEFAULT_PERMISSIONS,
    "system": DEFAULT_SYSTEM,
}


def _mask_key() -> str:
    """GLM_API_KEY 已配置 → '***'+末4位；未配置 → '未配置'。绝不返回完整 key。"""
    key = str(get_settings().GLM_API_KEY).strip()
    if not key:
        return "未配置"
    return "***" + key[-4:]


async def _get_row(session: AsyncSession, domain: str) -> Setting | None:
    return (await session.execute(select(Setting).where(Setting.key == domain))).scalar_one_or_none()


@router.get("/{domain}")
async def get_settings_domain(
    domain: str = Path(pattern=f"^({_DOMAIN_PATTERN})$"),
    session: AsyncSession = Depends(get_db),
) -> Any:
    row = await _get_row(session, domain)
    if domain == "models":
        stored = dict(row.value) if row is not None and isinstance(row.value, dict) else {}
        merged = {**DEFAULT_MODELS_STATIC, **stored}
        # keyMasked 永远实时计算，覆盖任何历史存储值（防止 key 原文被存入/回显）
        merged["keyMasked"] = _mask_key()
        merged.setdefault("baseUrl", get_settings().GLM_BASE_URL)
        return merged
    if row is not None:
        return row.value
    return _DEFAULTS[domain]


@router.put("/{domain}")
async def put_settings_domain(
    payload: dict = Body(..., description="任意 JSON 对象，服务端只存不解释"),
    domain: str = Path(pattern=f"^({_DOMAIN_PATTERN})$"),
    session: AsyncSession = Depends(get_db),
) -> dict:
    row = await _get_row(session, domain)
    if row is None:
        session.add(Setting(key=domain, value=payload, note=f"{domain} 配置（settings API）"))
    else:
        row.value = payload
    return payload


@router.post("/models/test", response_model=ModelTestOut)
async def test_models() -> ModelTestOut:
    """真实冒烟：无 key 如实 ok=false；有 key 发一条 1-token 消息测时延。"""
    settings = get_settings()
    client = GLMClient()
    if not client.configured:
        return ModelTestOut(ok=False, model=settings.GLM_MODEL, error="GLM_API_KEY 未配置")
    try:
        resp = await client.chat(
            [LLMMessage(role="user", content="ping")], max_tokens=1
        )
        return ModelTestOut(ok=True, model=resp.model, latency_ms=resp.latency_ms)
    except BizException as exc:
        return ModelTestOut(ok=False, model=settings.GLM_MODEL, error=exc.message)
    except Exception as exc:  # noqa: BLE001 - 冒烟端点不抛异常，HTTP 200 携带 ok=false
        return ModelTestOut(ok=False, model=settings.GLM_MODEL, error=f"模型调用失败: {exc}")


@router.post("/mcp/{server_id}/discover")
async def discover_mcp(server_id: str) -> None:
    """诚实实现：MCP 引擎未实现，直接 501，不虚构工具发现结果。"""
    raise BizException(
        ErrorCode.MCP_UNAVAILABLE,
        f"MCP 引擎未实现，无法发现 server={server_id} 的工具",
        status_code=501,
    )
