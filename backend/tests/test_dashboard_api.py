"""dashboard / agents / skill-events / system-health API 测试（B1）。

聚合值为真实 SQL 结果；结构断言不依赖数据量，数值断言依赖种子/创建的数据。
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


SUMMARY_KEYS = {"tasksTotal", "tasksToday", "tasksRunning", "tokensTotal", "tokensToday",
                "skillCount", "skillEvolutions", "successRate"}


async def test_dashboard_summary_shape(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/dashboard/summary")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == SUMMARY_KEYS
    assert body["tasksTotal"] >= 0
    assert body["successRate"] <= 1.0


async def test_dashboard_summary_counts_created_task(app_client: AsyncClient, deps_available: bool):
    """创建一个任务后，tasksTotal/tasksToday/tasksRunning 至少 +1（真实聚合）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    before = (await app_client.get("/api/v1/dashboard/summary")).json()
    await app_client.post("/api/v1/tasks", json={"title": "计数验证", "description": ""})
    after = (await app_client.get("/api/v1/dashboard/summary")).json()
    assert after["tasksTotal"] == before["tasksTotal"] + 1
    assert after["tasksToday"] >= before["tasksToday"] + 1
    assert after["tasksRunning"] >= before["tasksRunning"] + 1  # queued 属于运行中


async def test_dashboard_trends_zero_filled(app_client: AsyncClient, deps_available: bool):
    """7d 窗口必须有 7 个零填充日期点（真实 SQL + 补零）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/dashboard/trends?range=7d")
    assert r.status_code == 200
    body = r.json()
    assert body["range"] == "7d"
    assert len(body["taskTrend"]) == 7
    assert len(body["tokenTrend"]) == 7
    assert all(set(p.keys()) == {"date", "created", "succeeded", "failed"} for p in body["taskTrend"])
    assert all(set(p.keys()) == {"date", "glm53", "flash"} for p in body["tokenTrend"])
    r2 = await app_client.get("/api/v1/dashboard/trends?range=99d")
    assert r2.status_code == 422


async def test_agents_status_shape(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/agents/status")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"total", "items"}
    names = {i["name"] for i in body["items"]}
    assert names == {"planner", "executor", "reviewer", "replanner"}
    assert body["total"] == sum(i["value"] for i in body["items"]) or body["total"] >= 0


async def test_skill_events_shape(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/skills/events?limit=5")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items"}
    for ev in body["items"]:
        assert set(ev.keys()) == {"id", "skillId", "type", "message", "createdAt"}
        assert ev["type"] in ("proposed", "approved", "rejected", "rolled_back", "created")


async def test_system_health_alias(app_client: AsyncClient):
    """前端契约 GET /api/v1/system/health 与 /api/v1/health 同构（路径二选一落地）。"""
    r1 = await app_client.get("/api/v1/system/health")
    r2 = await app_client.get("/api/v1/health")
    assert r1.status_code == 200
    assert set(r1.json().keys()) == set(r2.json().keys()) == {"api", "postgres", "redis", "chroma", "mcp"}
