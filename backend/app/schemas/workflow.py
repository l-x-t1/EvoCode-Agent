"""workflow 域 schema（B8）：与前端 types/api.ts WorkflowGraph/Node/Edge 对齐。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class WorkflowNodeMetricsOut(CamelModel):
    duration_ms: int = 0
    tokens: int = 0
    messages: int = 0
    tool_calls: int = 0


class WorkflowPositionOut(CamelModel):
    x: float
    y: float


class WorkflowNodeOut(CamelModel):
    id: str
    agent: str
    label: str
    status: str
    metrics: WorkflowNodeMetricsOut
    position: WorkflowPositionOut


class WorkflowEdgeOut(CamelModel):
    id: str
    source: str
    target: str
    condition: str | None = None


class WorkflowGraphOut(CamelModel):
    run_id: str
    nodes: list[WorkflowNodeOut] = []
    edges: list[WorkflowEdgeOut] = []
