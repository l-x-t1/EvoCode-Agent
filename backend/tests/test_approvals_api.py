"""approvals 域 API 测试：列表 + 决策状态机守卫（B1）。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.core.enums import AgentRole, PlanStepStatus, RiskLevel, TaskStatus, ToolCallStatus
from app.db.session import get_session_factory
from app.models.execution import Approval, ToolCall
from app.models.task import AgentRun, AgentTask, Plan, PlanStep
from app.repositories.users import UsersRepository


async def _mk_approval_fixture(deps_available: bool) -> tuple[str, str]:
    """直接经 session 造 task→run→tool_call→approval（真实外键链）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        now = datetime.now(timezone.utc)
        task = AgentTask(user_id=user.id, title="审批测试任务", description="",
                         model="auto", status=TaskStatus.WAITING_APPROVAL,
                         created_at=now, updated_at=now)
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=TaskStatus.WAITING_APPROVAL,
                       model="glm-5.3", created_at=now, updated_at=now)
        session.add(run)
        await session.flush()
        plan = Plan(run_id=run.id, revision=1, created_at=now)
        session.add(plan)
        await session.flush()
        step = PlanStep(plan_id=plan.id, idx=0, title="危险写入", agent=AgentRole.EXECUTOR,
                        status=PlanStepStatus.RUNNING, attempt=1, tool_call_ids=[],
                        created_at=now)
        session.add(step)
        await session.flush()
        tc = ToolCall(run_id=run.id, plan_step_id=step.id, server="workspace",
                      tool="write_file", args={}, result_summary=None,
                      status=ToolCallStatus.RUNNING, risk=RiskLevel.DANGEROUS,
                      created_at=now, updated_at=now)
        session.add(tc)
        await session.flush()
        apv = Approval(run_id=run.id, tool_call_id=tc.id, tool="write_file",
                       summary="审批测试：危险写入", risk=RiskLevel.DANGEROUS,
                       status="pending", created_at=now, updated_at=now)
        session.add(apv)
        await session.commit()
        return apv.id, task.id


async def test_list_approvals_filter_pending(app_client: AsyncClient, deps_available: bool):
    apv_id, _ = await _mk_approval_fixture(deps_available)
    r = await app_client.get("/api/v1/approvals?status=pending")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "size"}
    assert any(a["id"] == apv_id for a in body["items"])
    fields = set(body["items"][0].keys())
    assert {"id", "runId", "toolCallId", "tool", "summary", "risk", "status",
            "createdAt", "resolvedAt", "resolvedBy"} == fields


async def test_resolve_approval_then_conflict(app_client: AsyncClient, deps_available: bool):
    """批准成功；重复决策 409；拒绝路径同样守卫。"""
    apv_id, _ = await _mk_approval_fixture(deps_available)
    r1 = await app_client.post(f"/api/v1/approvals/{apv_id}",
                               json={"decision": "approved", "comment": "ok"})
    assert r1.status_code == 200, r1.text
    body = r1.json()
    assert body["status"] == "approved"
    assert body["resolvedBy"] == "user"
    assert body["resolvedAt"] is not None
    # 终态不可逆
    r2 = await app_client.post(f"/api/v1/approvals/{apv_id}", json={"decision": "rejected"})
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "conflict"
    assert r2.json()["error"]["details"]["currentStatus"] == "approved"


async def test_resolve_rejected_path(app_client: AsyncClient, deps_available: bool):
    apv_id, _ = await _mk_approval_fixture(deps_available)
    r = await app_client.post(f"/api/v1/approvals/{apv_id}",
                              json={"decision": "rejected", "comment": "方案有风险"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"


async def test_resolve_invalid_decision_422(app_client: AsyncClient, deps_available: bool):
    apv_id, _ = await _mk_approval_fixture(deps_available)
    r = await app_client.post(f"/api/v1/approvals/{apv_id}", json={"decision": "maybe"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_resolve_not_found(app_client: AsyncClient):
    r = await app_client.post("/api/v1/approvals/apv_notexist000000000000000",
                              json={"decision": "approved"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
