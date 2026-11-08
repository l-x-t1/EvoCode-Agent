"""结构化日志（docs/08 §2 core）。

- dev：人类可读控制台格式
- prod：单行 JSON（便于采集）
- 敏感值过滤器：任何包含 GLM_API_KEY= / MASTER_KEY= 明文的行一律打码（额外检查 #7）
"""

from __future__ import annotations

import json
import logging
import re
import sys

from app.core.config import Settings

_SENSITIVE_PATTERN = re.compile(
    r"(GLM_API_KEY|MASTER_KEY|API_KEY|Authorization)\s*[=:]\s*(?!\*\*\*)(?P<secret>[^\s,&\"]+)",
    re.IGNORECASE,
)


class SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            original = record.getMessage()
            if original and _SENSITIVE_PATTERN.search(original):
                # 仅在命中敏感模式时改写，并清空 args，
                # 避免「已格式化 msg + 残留 args」导致二次取值时 % 格式化错乱
                record.msg = _SENSITIVE_PATTERN.sub(lambda m: f"{m.group(1)}=***", original)
                record.args = None
        except Exception:  # noqa: BLE001 - 过滤器绝不能影响业务
            pass
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def setup_logging(settings: Settings) -> None:
    root = logging.getLogger()
    root.setLevel(settings.LOG_LEVEL.upper())
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(SensitiveFilter())
    if settings.is_dev:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-7s %(name)s | %(message)s", "%H:%M:%S")
        )
    else:
        handler.setFormatter(JsonFormatter())
    root.addHandler(handler)

    # 收敛第三方噪音
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING if not settings.DB_ECHO else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
