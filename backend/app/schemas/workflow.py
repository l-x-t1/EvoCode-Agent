"""Workflow 响应模型（对齐前端 types/api.ts WorkflowGraph/Node/Edge）。"""

from __future__ import annotations

from pydantic import BaseModel


class WorkflowNodeMetrics(BaseModel):
    durationMs: int = 0
    tokens: int = 0
    messages: int = 0
    toolCalls: int = 0


class WorkflowNodePosition(BaseModel):
    x: float
    y: float


class WorkflowNodeOut(BaseModel):
    id: str
    agent: str
    label: str
    status: str  # TaskStatus | 'pending'
    metrics: WorkflowNodeMetrics
    position: WorkflowNodePosition


class WorkflowEdgeOut(BaseModel):
    id: str
    source: str
    target: str
    condition: str | None = None


class WorkflowGraphOut(BaseModel):
    runId: str | None = None
    nodes: list[WorkflowNodeOut] = []
    edges: list[WorkflowEdgeOut] = []
