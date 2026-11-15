"""API 响应模型（与前端 types/api.ts 逐字段对齐，docs/06 §2）。

统一 camelCase 序列化（alias_generator=to_camel），FastAPI 默认 by_alias 输出。
时间字段为 tz-aware datetime，Pydantic 输出 ISO8601 UTC。
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.core.response import Page


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


# ── 任务与运行 ────────────────────────────────────────

class TaskStatsOut(CamelModel):
    duration_ms: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    tool_calls: int = 0
    test_pass_rate: float | None = None


class TaskOut(CamelModel):
    id: str
    title: str
    description: str
    repo: str | None = None
    status: str
    model: str
    skill_ids: list[str] = []
    created_at: datetime
    updated_at: datetime
    stats: TaskStatsOut
    latest_run_id: str | None = None


class TaskPage(Page[TaskOut]):
    """分页响应 {items,total,page,size}（docs/06 §1）。"""


class RunStatsOut(TaskStatsOut):
    replan_count: int = 0


class RunOut(CamelModel):
    id: str
    task_id: str
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    model: str
    stats: RunStatsOut


class PlanStepOut(CamelModel):
    id: str
    index: int
    title: str
    detail: str | None = None
    agent: str
    status: str
    attempt: int
    tool_call_ids: list[str] = []


class PlanOut(CamelModel):
    id: str
    run_id: str
    revision: int
    steps: list[PlanStepOut] = []


class MessageOut(CamelModel):
    id: str
    run_id: str | None = None
    role: str
    content: str
    created_at: datetime
    tokens: int | None = None


class MessagePage(Page[MessageOut]):
    pass


class ToolCallOut(CamelModel):
    id: str
    run_id: str
    step_id: str | None = None
    server: str
    tool: str
    args: dict = {}
    result_summary: str | None = None
    status: str
    risk: str
    duration_ms: int | None = None
    created_at: datetime


class ToolCallPage(Page[ToolCallOut]):
    pass


class DiffFileOut(CamelModel):
    path: str
    additions: int
    deletions: int
    patch: str


class CodeDiffOut(CamelModel):
    id: str
    run_id: str
    files: list[DiffFileOut] = []
    created_at: datetime


class CodeDiffListOut(CamelModel):
    items: list[CodeDiffOut] = []


class TestFailureOut(CamelModel):
    name: str
    message: str
    snippet: str | None = None


class TestResultOut(CamelModel):
    id: str
    run_id: str
    passed: int
    failed: int
    skipped: int
    failures: list[TestFailureOut] = []
    log_tail: str | None = None
    created_at: datetime


class TestResultListOut(CamelModel):
    items: list[TestResultOut] = []


class ExecutionLogEventOut(CamelModel):
    """事件历史（GET /runs/:id/events?after=）：SSE 信封的数据源形态。"""

    seq: int
    event_type: str
    payload: dict = {}
    created_at: datetime


class ExecutionLogEventListOut(CamelModel):
    items: list[ExecutionLogEventOut] = []


# ── 审批 ─────────────────────────────────────────────

class ApprovalOut(CamelModel):
    id: str
    run_id: str
    tool_call_id: str
    tool: str
    summary: str
    risk: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolved_by: str | None = None


class ApprovalPage(Page[ApprovalOut]):
    pass


class ApprovalDecisionIn(CamelModel):
    decision: str  # approved | rejected
    comment: str | None = None
