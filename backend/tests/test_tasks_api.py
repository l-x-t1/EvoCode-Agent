"""tasks 域 API 测试：创建/列表/详情/取消/幂等/消息（B1）。

依赖 PG + Redis；不可用时跳过集成断言（如实跳过）。
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _create_body(**over) -> dict:
    body = {"title": "B1 测试任务", "description": "验证创建链路", "repo": None,
            "model": "auto", "skillIds": []}
    body.update(over)
    return body


TASK_FIELDS = {"id", "title", "description", "repo", "status", "model", "skillIds",
               "createdAt", "updatedAt", "stats", "latestRunId"}
STATS_FIELDS = {"durationMs", "tokensIn", "tokensOut", "toolCalls", "testPassRate"}


async def test_create_task_bare_entity(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.post("/api/v1/tasks", json=_create_body())
    assert r.status_code == 201, r.text
    body = r.json()
    assert set(body.keys()) == TASK_FIELDS
    assert body["status"] == "queued"
    assert body["model"] == "auto"
    assert set(body["stats"].keys()) == STATS_FIELDS
    assert body["id"].startswith("task_")
    # 首条用户消息落库（会话 1:1）
    m = await app_client.get(f"/api/v1/tasks/{body['id']}/messages")
    assert m.status_code == 200
    items = m.json()["items"]
    assert len(items) >= 1
    assert items[0]["role"] == "user"
    assert items[0]["content"] == "验证创建链路"


async def test_create_task_validation_error(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.post("/api/v1/tasks", json=_create_body(title=""))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
    r2 = await app_client.post("/api/v1/tasks", json=_create_body(model="gpt-4"))
    assert r2.status_code == 422


async def test_idempotency_key_replay(app_client: AsyncClient, deps_available: bool):
    """同一 Idempotency-Key 重放返回同一任务，不重复创建（docs/06 §1）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    key = "b1-test-" + uuid.uuid4().hex
    h = {"Idempotency-Key": key}
    r1 = await app_client.post("/api/v1/tasks", json=_create_body(title="幂等任务"), headers=h)
    assert r1.status_code == 201
    r2 = await app_client.post("/api/v1/tasks", json=_create_body(title="幂等任务"), headers=h)
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]
    # 不同 key 是不同任务
    r3 = await app_client.post("/api/v1/tasks", json=_create_body(title="幂等任务"),
                               headers={"Idempotency-Key": key + "-x"})
    assert r3.json()["id"] != r1.json()["id"]


async def test_list_tasks_pagination_and_filter(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    for i in range(3):
        await app_client.post("/api/v1/tasks", json=_create_body(title=f"B1 分页 {i}"))
    r = await app_client.get("/api/v1/tasks?page=1&size=2")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "size"}
    assert len(body["items"]) == 2
    assert body["page"] == 1 and body["size"] == 2
    assert body["total"] >= 3
    # 状态过滤
    r2 = await app_client.get("/api/v1/tasks?status=queued")
    assert all(t["status"] == "queued" for t in r2.json()["items"])
    # 关键词过滤
    r3 = await app_client.get("/api/v1/tasks?q=B1+分页+0")
    assert any(t["title"] == "B1 分页 0" for t in r3.json()["items"])


async def test_get_task_404_error_body(app_client: AsyncClient):
    r = await app_client.get("/api/v1/tasks/task_notexist00000000000000")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_cancel_task_state_guard(app_client: AsyncClient, deps_available: bool):
    """非终态可取消；重复取消 → 409 conflict（状态机守卫）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    created = (await app_client.post("/api/v1/tasks", json=_create_body(title="取消守卫"))).json()
    r1 = await app_client.post(f"/api/v1/tasks/{created['id']}/cancel")
    assert r1.status_code == 200
    assert r1.json() == {"ok": True}
    r2 = await app_client.post(f"/api/v1/tasks/{created['id']}/cancel")
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "conflict"
    assert r2.json()["error"]["details"]["currentStatus"] == "cancelled"


async def test_task_runs_empty_list(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    created = (await app_client.post("/api/v1/tasks", json=_create_body(title="无运行"))).json()
    r = await app_client.get(f"/api/v1/tasks/{created['id']}/runs")
    assert r.status_code == 200
    assert r.json() == []
