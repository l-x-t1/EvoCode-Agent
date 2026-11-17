"""workflow 域路由（B8）：运行图（四角色节点聚合）+ 静态模板。

节点状态聚合（零虚构，全部来自 plans/plan_steps/messages/tool_calls 真实查询）：
- planner：plan 存在且首个 planner 步骤 done → completed，否则 executing
- executor：有失败步骤 → failed；全 done → completed；有 pending/running → executing；无步骤 → pending
- reviewer：run completed → completed；failed → failed；否则 pending
- replanner：run.replan_count > 0 → completed，否则 pending
plan_steps 无角色级耗时/Token 列 → durationMs/tokens 如实为 0。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.models.conversation import Message
from app.models.execution import ToolCall
from app.models.task import AgentRun, Plan, PlanStep
from app.schemas.workflow import (
    WorkflowEdgeOut,
    WorkflowGraphOut,
    WorkflowNodeMetricsOut,
    WorkflowNodeOut,
    WorkflowPositionOut,
)

router = APIRouter(prefix="/workflow", tags=["workflow"])

_POSITIONS = {
    "planner": (80, 120),
    "executor": (360, 60),
    "reviewer": (640, 120),
    "replanner": (360, 240),
}
_LABELS = {
    "planner": "规划器",
    "executor": "执行器",
    "reviewer": "评审器",
    "replanner": "重规划器",
}
_EDGES = [
    WorkflowEdgeOut(id="planner-executor", source="planner", target="executor"),
    WorkflowEdgeOut(id="executor-reviewer", source="executor", target="reviewer"),
    WorkflowEdgeOut(
        id="reviewer-replanner", source="reviewer", target="replanner", condition="review.failed"
    ),
    WorkflowEdgeOut(
        id="replanner-executor", source="replanner", target="executor", condition="replan"
    ),
]


def _nodes(status_by_role: dict[str, str], metrics_by_role: dict[str, WorkflowNodeMetricsOut]) -> list[WorkflowNodeOut]:
    return [
        WorkflowNodeOut(
            id=role,
            agent=role,
            label=_LABELS[role],
            status=status_by_role[role],
            metrics=metrics_by_role[role],
            position=WorkflowPositionOut(x=_POSITIONS[role][0], y=_POSITIONS[role][1]),
        )
        for role in ("planner", "executor", "reviewer", "replanner")
    ]


def _zero_metrics() -> WorkflowNodeMetricsOut:
    return WorkflowNodeMetricsOut()


def _empty_graph(run_id: str) -> WorkflowGraphOut:
    """静态模板：节点 pending、metrics 全零（GET /workflow/template）。"""
    zero = _zero_metrics()
    return WorkflowGraphOut(
        run_id=run_id,
        nodes=_nodes(
            status_by_role={r: "pending" for r in _POSITIONS},
            metrics_by_role={r: zero.model_copy() for r in _POSITIONS},
        ),
        edges=[e.model_copy() for e in _EDGES],
    )


def _executor_status(statuses: list[str]) -> str:
    if not statuses:
        return "pending"
    if "failed" in statuses:
        return "failed"
    if all(s == "done" for s in statuses):
        return "completed"
    if any(s in ("pending", "running") for s in statuses):
        return "executing"
    return "executing"


@router.get("/template", response_model=WorkflowGraphOut)
async def workflow_template() -> WorkflowGraphOut:
    return _empty_graph("")


@router.get("/runs/{run_id}/graph", response_model=WorkflowGraphOut)
async def workflow_run_graph(
    run_id: str, session: AsyncSession = Depends(get_db)
) -> WorkflowGraphOut:
    run = await session.get(AgentRun, run_id)
    if run is None:
        raise BizException(ErrorCode.NOT_FOUND, f"运行 {run_id} 不存在", status_code=404)

    rows = (
        await session.execute(
            select(PlanStep.agent, PlanStep.status, PlanStep.idx, Plan.revision)
            .join(Plan, PlanStep.plan_id == Plan.id)
            .where(Plan.run_id == run_id)
            .order_by(Plan.revision, PlanStep.idx)
        )
    ).all()

    by_role: dict[str, list[str]] = {"planner": [], "executor": [], "reviewer": [], "replanner": []}
    for agent, status, _idx, _rev in rows:
        role = str(agent)
        if role in by_role:
            by_role[role].append(str(status))

    run_status = str(run.status)
    # planner：run/plan 存在且首个 planner 步骤 done → completed，否则 executing
    planner_first_done = bool(by_role["planner"]) and by_role["planner"][0] == "done"
    status_by_role = {
        "planner": "completed" if planner_first_done else "executing",
        "executor": _executor_status(by_role["executor"]),
        "reviewer": (
            "completed" if run_status == "completed"
            else "failed" if run_status == "failed"
            else "pending"
        ),
        "replanner": "completed" if run.replan_count > 0 else "pending",
    }

    msg_rows = (
        await session.execute(
            select(Message.role, func.count())
            .where(Message.run_id == run_id)
            .group_by(Message.role)
        )
    ).all()
    msg_counts = {str(role): int(n) for role, n in msg_rows}

    tool_calls = int(
        (
            await session.execute(
                select(func.count()).select_from(ToolCall).where(ToolCall.run_id == run_id)
            )
        ).scalar_one()
    )

    metrics_by_role = {
        "planner": WorkflowNodeMetricsOut(messages=msg_counts.get("planner", 0)),
        "executor": WorkflowNodeMetricsOut(messages=msg_counts.get("executor", 0), tool_calls=tool_calls),
        "reviewer": WorkflowNodeMetricsOut(messages=msg_counts.get("reviewer", 0)),
        "replanner": WorkflowNodeMetricsOut(messages=msg_counts.get("replanner", 0)),
    }
    return WorkflowGraphOut(
        run_id=run_id,
        nodes=_nodes(status_by_role, metrics_by_role),
        edges=[e.model_copy() for e in _EDGES],
    )
