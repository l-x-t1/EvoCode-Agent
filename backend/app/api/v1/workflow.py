"""Workflow 路由（B8）：从 run 真实数据派生四角色图 + 静态模板。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.enums import AgentRole, TaskStatus
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.models.conversation import Message
from app.models.execution import ToolCall
from app.models.task import AgentRun, Plan, PlanStep
from app.schemas.workflow import (
    WorkflowEdgeOut,
    WorkflowGraphOut,
    WorkflowNodeMetrics,
    WorkflowNodeOut,
    WorkflowNodePosition,
)

router = APIRouter(prefix="/workflow", tags=["workflow"])

_POSITIONS = {
    "planner": (80, 120),
    "executor": (360, 60),
    "reviewer": (640, 120),
    "replanner": (360, 240),
}
_LABELS = {
    "planner": "Planner 规划",
    "executor": "Executor 执行",
    "reviewer": "Reviewer 复核",
    "replanner": "Replanner 重规划",
}


def _s(value) -> str:
    return str(value.value) if hasattr(value, "value") else str(value)


async def _load_run_or_404(session: AsyncSession, run_id: str) -> AgentRun:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise BizException(ErrorCode.NOT_FOUND, f"Run 不存在: {run_id}", status_code=404)
    return run


async def _graph_for_run(session: AsyncSession, run: AgentRun) -> WorkflowGraphOut:
    steps = list((await session.execute(
        select(PlanStep).where(PlanStep.plan_id.in_(
            select(Plan.id).where(Plan.run_id == run.id)))
        .order_by(PlanStep.idx.asc())
    )).scalars().all())
    by_agent: dict[str, list[PlanStep]] = {}
    for s in steps:
        by_agent.setdefault(_s(s.agent), []).append(s)
    tool_calls = (await session.execute(
        select(func.count()).select_from(ToolCall).where(ToolCall.run_id == run.id)
    )).scalar_one()
    message_counts: dict[str, int] = {}
    for role, cnt in (await session.execute(
        select(Message.role, func.count()).where(Message.run_id == run.id)
        .group_by(Message.role)
    )).all():
        message_counts[_s(role)] = int(cnt)

    def _steps_status(agent: str) -> str:
        ss = by_agent.get(agent, [])
        statuses = [_s(s.status) for s in ss]
        if not statuses:
            return "pending"
        if all(x == "done" for x in statuses):
            return "completed"
        if "failed" in statuses:
            return "failed"
        return "executing"

    run_status = _s(run.status)
    nodes = []
    # planner
    planner_status = "completed" if steps else ("executing" if run_status == "planning" else "pending")
    if run_status in ("completed", "failed", "cancelled"):
        planner_status = "completed" if run_status != "failed" else "failed"
    # executor
    executor_status = _steps_status("executor")
    if executor_status == "pending" and run_status == "executing":
        executor_status = "executing"
    # reviewer
    reviewer_status = ("completed" if run_status == "completed"
                       else "failed" if run_status == "failed"
                       else "reviewing" if run_status == "reviewing"
                       else "pending")
    # replanner
    replanner_status = "completed" if (run.replan_count or 0) > 0 else "pending"
    if run_status == "failed" and (run.replan_count or 0) >= 2:
        replanner_status = "failed"

    def _m(agent: str, tool_calls_count: int = 0) -> WorkflowNodeMetrics:
        ss = by_agent.get(agent, [])
        duration = sum(s.attempt * 100 for s in ss)  # 无步骤级耗时列，以尝试次数近似（如实）
        return WorkflowNodeMetrics(
            durationMs=duration, tokens=0,
            messages=message_counts.get(agent, 0), toolCalls=tool_calls_count)

    nodes_spec = [
        ("planner", "planner", _LABELS["planner"], planner_status, _m("planner")),
        ("executor", "executor", _LABELS["executor"], executor_status,
         _m("executor", tool_calls_count=int(tool_calls))),
        ("reviewer", "reviewer", _LABELS["reviewer"], reviewer_status, _m("reviewer")),
        ("replanner", "replanner", _LABELS["replanner"], replanner_status, _m("replanner")),
    ]
    for nid, agent, label, status, metrics in nodes_spec:
        x, y = _POSITIONS[agent]
        nodes.append(WorkflowNodeOut(
            id=nid, agent=agent, label=label, status=status,
            metrics=metrics, position=WorkflowNodePosition(x=x, y=y)))

    edges = [
        WorkflowEdgeOut(id="e1", source="planner", target="executor"),
        WorkflowEdgeOut(id="e2", source="executor", target="reviewer"),
        WorkflowEdgeOut(id="e3", source="reviewer", target="replanner", condition="review.failed"),
        WorkflowEdgeOut(id="e4", source="replanner", target="executor", condition="replan"),
    ]
    return WorkflowGraphOut(runId=run.id, nodes=nodes, edges=edges)


@router.get("/runs/{run_id}/graph", response_model=WorkflowGraphOut)
async def run_graph(run_id: str, session: AsyncSession = Depends(get_db)) -> WorkflowGraphOut:
    run = await _load_run_or_404(session, run_id)
    return await _graph_for_run(session, run)


@router.get("/template", response_model=WorkflowGraphOut)
async def workflow_template() -> WorkflowGraphOut:
    nodes = [WorkflowNodeOut(
        id=agent, agent=agent, label=_LABELS[agent], status="pending",
        metrics=WorkflowNodeMetrics(),
        position=WorkflowNodePosition(x=_POSITIONS[agent][0], y=_POSITIONS[agent][1]),
    ) for agent in ("planner", "executor", "reviewer", "replanner")]
    edges = [
        WorkflowEdgeOut(id="e1", source="planner", target="executor"),
        WorkflowEdgeOut(id="e2", source="executor", target="reviewer"),
        WorkflowEdgeOut(id="e3", source="reviewer", target="replanner", condition="review.failed"),
        WorkflowEdgeOut(id="e4", source="replanner", target="executor", condition="replan"),
    ]
    return WorkflowGraphOut(runId=None, nodes=nodes, edges=edges)


@router.get("/runs/{run_id}/task-check")
async def run_task_check(run_id: str, session: AsyncSession = Depends(get_db)) -> dict:
    """辅助端点：run 归属 task 状态（诊断用）。"""
    run = await _load_run_or_404(session, run_id)
    task = await session.get(AgentTask, run.task_id)
    return {"runId": run.id, "taskStatus": _s(task.status) if task else None}
