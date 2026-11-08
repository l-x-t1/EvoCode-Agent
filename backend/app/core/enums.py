"""共享枚举：取值与前端 types/api.ts 逐字一致（docs/08 §1）。

使用 StrEnum：value 即存储值，配合 SQLAlchemy Enum(values_callable=...) 入库。
"""

from __future__ import annotations

import enum


class TaskStatus(enum.StrEnum):
    QUEUED = "queued"
    PLANNING = "planning"
    EXECUTING = "executing"
    REVIEWING = "reviewing"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @classmethod
    def terminal(cls) -> tuple["TaskStatus", ...]:
        return (cls.COMPLETED, cls.FAILED, cls.CANCELLED)


class AgentRole(enum.StrEnum):
    PLANNER = "planner"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    REPLANNER = "replanner"
    USER = "user"
    SYSTEM = "system"


class RiskLevel(enum.StrEnum):
    SAFE = "safe"
    GATED = "gated"
    DANGEROUS = "dangerous"


class ToolCallStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class ApprovalResolvedBy(enum.StrEnum):
    USER = "user"
    AUTO = "auto"


class PlanStepStatus(enum.StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"
    REPLANNED = "replanned"


class SkillCategory(enum.StrEnum):
    TESTING = "testing"
    REFACTOR = "refactor"
    DEBUGGING = "debugging"
    DOCS = "docs"
    WORKFLOW = "workflow"
    OTHER = "other"


class SkillStatus(enum.StrEnum):
    ACTIVE = "active"
    DRAFT = "draft"
    DEPRECATED = "deprecated"


class SkillSource(enum.StrEnum):
    TASK = "task"
    EVOLUTION = "evolution"
    MANUAL = "manual"


class CandidateKind(enum.StrEnum):
    CREATE = "create"
    REVISE = "revise"


class CandidateStatus(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ContextTrigger(enum.StrEnum):
    """ContextSnapshot 产生原因（决策 #6：1:N 版本化）。"""

    INITIAL = "initial"
    THRESHOLD = "threshold"
    MANUAL = "manual"
    ROUTING = "routing"


class MemoryLayer(enum.StrEnum):
    CORE = "core"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"


class EvalRunStatus(enum.StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def enum_values(enum_cls: type[enum.StrEnum]) -> list[str]:
    """SQLAlchemy Enum 入库值列表（存 value 而非 name）。"""
    return [m.value for m in enum_cls]
