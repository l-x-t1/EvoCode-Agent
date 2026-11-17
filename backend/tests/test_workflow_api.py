"""workflow 域 API 测试（B8）：真实种子（user→task→run→plan/steps→messages）断言聚合。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.enums import AgentRole, PlanStepStatus, TaskStatus
from app.db.session import get_session_factory
from app.models.conversation import Conversation, Message
from app.models.task import AgentRun, AgentTask, Plan, PlanStep
from app.repositories.users import UsersRepository

pytest_asyncio.fixture(autouse=True)


@pytest_asyncio.fixture(autouse=True)
async def db_stack():
    from app.db.redis import close_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    settings = get_settings()
    init_engine(settings)
    init_redis(settings)
    yield
    await close_redis()
    await dispose_engine()


def _now():
    return datetime.now(timezone.utc)


NODE_KEYS = {"id", "agent", "label", "status", "metrics", "position"}
METRIC_KEYS = {"durationMs", "tokens", "messages", "toolCalls"}
POSITIONS = {"planner": (80, 120), "executor": (360, 60), "reviewer": (640, 120),
             "replanner": (360, 240)}


async def _seed_run_with_progress() -> str:
    """plan：planner 步骤 done + executor 步骤 running；消息 planner×1、executor×2。"""
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title="B8 工作流图种子", description="",
                         model="auto", status=TaskStatus.EXECUTING,
                         created_at=_now(), updated_at=_now())
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=TaskStatus.EXECUTING, model="glm-5.3",
                       replan_count=0, created_at=_now(), updated_at=_now())
        session.add(run)
        await session.flush()
        plan = Plan(run_id=run.id, revision=1)
        session.add(plan)
        await session.flush()
        session.add(PlanStep(plan_id=plan.id, idx=1, title="产出计划", agent=AgentRole.PLANNER,
                             status=PlanStepStatus.DONE, created_at=_now()))
        session.add(PlanStep(plan_id=plan.id, idx=2, title="执行步骤", agent=AgentRole.EXECUTOR,
                             status=PlanStepStatus.RUNNING, created_at=_now()))
        conv = Conversation(task_id=task.id, user_id=user.id, title="B8 会话")
        session.add(conv)
        await session.flush()
        session.add(Message(conversation_id=conv.id, run_id=run.id, role=AgentRole.PLANNER,
                            content="计划输出", created_at=_now(), updated_at=_now()))
        for _ in range(2):
            session.add(Message(conversation_id=conv.id, run_id=run.id, role=AgentRole.EXECUTOR,
                                content="执行消息", created_at=_now(), updated_at=_now()))
        await session.commit()
        return run.id


async def test_run_graph_nodes_and_metrics(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    run_id = await _seed_run_with_progress()
    r = await app_client.get(f"/api/v1/workflow/runs/{run_id}/graph")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["runId"] == run_id
    nodes = body["nodes"]
    assert len(nodes) == 4
    by_id = {n["id"]: n for n in nodes}
    assert set(by_id.keys()) == {"planner", "executor", "reviewer", "replanner"}
    assert all(set(n.keys()) == NODE_KEYS for n in nodes)
    assert all(set(n["metrics"].keys()) == METRIC_KEYS for n in nodes)
    # 聚合状态：planner 首步 done → completed；executor 有 running → executing
    assert by_id["planner"]["status"] == "completed"
    assert by_id["executor"]["status"] == "executing"
    assert by_id["reviewer"]["status"] == "pending"
    assert by_id["replanner"]["status"] == "pending"
    # metrics.messages：按 run_id + role 真实计数
    assert by_id["planner"]["metrics"]["messages"] == 1
    assert by_id["executor"]["metrics"]["messages"] == 2
    assert by_id["reviewer"]["metrics"]["messages"] == 0
    assert by_id["replanner"]["metrics"]["messages"] == 0
    # 静态布局
    for role, (x, y) in POSITIONS.items():
        assert by_id[role]["position"] == {"x": x, "y": y}


async def test_run_graph_edges_conditions(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    run_id = await _seed_run_with_progress()
    r = await app_client.get(f"/api/v1/workflow/runs/{run_id}/graph")
    edges = r.json()["edges"]
    pairs = {(e["source"], e["target"]): e.get("condition") for e in edges}
    assert ("planner", "executor") in pairs
    assert ("executor", "reviewer") in pairs
    assert pairs[("reviewer", "replanner")] == "review.failed"
    assert pairs[("replanner", "executor")] == "replan"
    assert all(set(e.keys()) == {"id", "source", "target", "condition"} for e in edges)


async def test_run_graph_404(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/workflow/runs/run_not_exist/graph")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


async def test_template_static_shape(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/workflow/template")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"runId", "nodes", "edges"}
    assert len(body["nodes"]) == 4
    for n in body["nodes"]:
        assert n["status"] == "pending"
        assert n["metrics"] == {"durationMs": 0, "tokens": 0, "messages": 0, "toolCalls": 0}
    pairs = {(e["source"], e["target"]): e.get("condition") for e in body["edges"]}
    assert pairs[("reviewer", "replanner")] == "review.failed"
    assert pairs[("replanner", "executor")] == "replan"
