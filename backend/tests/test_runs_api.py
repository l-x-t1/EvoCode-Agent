"""runs 域 API 测试：plan / tool-calls / diffs / tests / 事件历史（B1）。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.core.enums import AgentRole, PlanStepStatus, RiskLevel, TaskStatus, ToolCallStatus
from app.db.session import get_session_factory
from app.models.execution import AgentExecutionLog, ToolCall
from app.models.task import AgentRun, AgentTask, Plan, PlanStep
from app.repositories.users import UsersRepository


async def _mk_run_fixture(deps_available: bool) -> str:
    """造完整 run 链：plan(rev1) + steps + tool_calls + 事件日志（含 diff/test）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        now = datetime.now(timezone.utc)
        task = AgentTask(user_id=user.id, title="Run 测试任务", description="",
                         model="auto", status=TaskStatus.EXECUTING,
                         created_at=now, updated_at=now)
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=TaskStatus.EXECUTING, model="glm-5.3",
                       started_at=now, created_at=now, updated_at=now)
        session.add(run)
        await session.flush()
        plan = Plan(run_id=run.id, revision=1, created_at=now)
        session.add(plan)
        await session.flush()
        s1 = PlanStep(plan_id=plan.id, idx=0, title="分析", agent=AgentRole.PLANNER,
                      status=PlanStepStatus.DONE, attempt=1, tool_call_ids=[],
                      created_at=now)
        s2 = PlanStep(plan_id=plan.id, idx=1, title="实施", agent=AgentRole.EXECUTOR,
                      status=PlanStepStatus.RUNNING, attempt=1, tool_call_ids=[],
                      created_at=now)
        session.add_all([s1, s2])
        await session.flush()
        tc = ToolCall(run_id=run.id, plan_step_id=s2.id, server="workspace", tool="read_file",
                      args={"path": "app/main.py"}, result_summary="42 行",
                      status=ToolCallStatus.SUCCEEDED, risk=RiskLevel.SAFE,
                      duration_ms=12, created_at=now, updated_at=now)
        session.add(tc)
        for seq, (etype, payload) in enumerate([
            ("run.status", {"to": "executing"}),
            ("code.diff.created", {"files": [
                {"path": "app/main.py", "additions": 3, "deletions": 1, "patch": "@@ -1 +1,3 @@\n+x"},
            ]}),
            ("test.finished", {"passed": 2, "failed": 1, "skipped": 0,
                               "failures": [{"name": "t1", "message": "boom", "snippet": "x"}],
                               "logTail": "1 failed, 2 passed"}),
        ], start=1):
            session.add(AgentExecutionLog(run_id=run.id, seq=seq, event_type=etype,
                                          payload=payload, created_at=now))
        await session.commit()
        return run.id


async def test_get_run_and_plan(app_client: AsyncClient, deps_available: bool):
    run_id = await _mk_run_fixture(deps_available)
    r = await app_client.get(f"/api/v1/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert set(body["stats"].keys()) == {"durationMs", "tokensIn", "tokensOut",
                                         "toolCalls", "testPassRate", "replanCount"}
    p = await app_client.get(f"/api/v1/runs/{run_id}/plan")
    assert p.status_code == 200
    plan = p.json()
    assert plan["revision"] == 1
    assert [s["index"] for s in plan["steps"]] == [0, 1]
    assert plan["steps"][0]["agent"] == "planner"
    assert plan["steps"][0]["status"] == "done"


async def test_run_not_found(app_client: AsyncClient):
    r = await app_client.get("/api/v1/runs/run_notexist0000000000000000/plan")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_run_tool_calls_page(app_client: AsyncClient, deps_available: bool):
    run_id = await _mk_run_fixture(deps_available)
    r = await app_client.get(f"/api/v1/runs/{run_id}/tool-calls")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "size"}
    tc = body["items"][0]
    assert set(tc.keys()) == {"id", "runId", "stepId", "server", "tool", "args",
                              "resultSummary", "status", "risk", "durationMs", "createdAt"}
    assert tc["risk"] == "safe"
    assert tc["args"]["path"] == "app/main.py"


async def test_run_diffs_from_event_log(app_client: AsyncClient, deps_available: bool):
    """diffs 来自 code.diff.created 事件（事件溯源，零新表）。"""
    run_id = await _mk_run_fixture(deps_available)
    r = await app_client.get(f"/api/v1/runs/{run_id}/diffs")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    d = items[0]
    assert set(d.keys()) == {"id", "runId", "files", "createdAt"}
    assert d["files"][0]["path"] == "app/main.py"
    assert d["files"][0]["additions"] == 3


async def test_run_tests_from_event_log(app_client: AsyncClient, deps_available: bool):
    run_id = await _mk_run_fixture(deps_available)
    r = await app_client.get(f"/api/v1/runs/{run_id}/tests")
    assert r.status_code == 200
    t = r.json()["items"][0]
    assert set(t.keys()) == {"id", "runId", "passed", "failed", "skipped",
                             "failures", "logTail", "createdAt"}
    assert (t["passed"], t["failed"], t["skipped"]) == (2, 1, 0)
    assert t["failures"][0]["name"] == "t1"


async def test_run_events_history_after_seq(app_client: AsyncClient, deps_available: bool):
    """事件历史 after=seq 续传语义：after=1 只返回 seq>1。"""
    run_id = await _mk_run_fixture(deps_available)
    r1 = await app_client.get(f"/api/v1/runs/{run_id}/events")
    assert r1.status_code == 200
    all_seq = [e["seq"] for e in r1.json()["items"]]
    assert all_seq == sorted(all_seq) and len(all_seq) == 3
    r2 = await app_client.get(f"/api/v1/runs/{run_id}/events?after={all_seq[0]}")
    rest = [e["seq"] for e in r2.json()["items"]]
    assert rest == all_seq[1:]
