"""进程内请求度量（B1：api.latencyMs 从「恒 0」改为真实度量）。

- HTTP 中间件在每笔请求完成后记录耗时
- 健康检查读取最近一笔请求的延迟（无请求时如实返回 0，不虚构）
- 进程级单例即可：MVP 单进程部署；多进程部署时改为聚合存储（记录在案）
"""

from __future__ import annotations

import time

_last_request_latency_ms: int = 0
_last_request_at: float = 0.0


def record_request_latency(latency_ms: int) -> None:
    global _last_request_latency_ms, _last_request_at
    _last_request_latency_ms = max(0, latency_ms)
    _last_request_at = time.perf_counter()


def last_request_latency_ms() -> int:
    return _last_request_latency_ms
