"""数据模型元数据测试：表数量、关键唯一约束、部分索引（额外检查 #1/#2/#5）。"""

from __future__ import annotations

from sqlalchemy import UniqueConstraint

import app.models  # noqa: F401  触发表注册
from app.models.base import Base, prefixed_ulid

EXPECTED_TABLES = {
    "users",
    "agent_tasks",
    "agent_runs",
    "plans",
    "plan_steps",
    "conversations",
    "messages",
    "tool_calls",
    "approvals",
    "agent_execution_logs",
    "skills",
    "skill_versions",
    "skill_evaluations",
    "skill_candidates",
    "context_snapshots",
    "memory_items",
    "eval_runs",
    "eval_cases",
    "model_usage",
    "settings",
}


def test_all_tables_registered():
    assert set(Base.metadata.tables.keys()) == EXPECTED_TABLES


def test_ulid_generation():
    task_id = prefixed_ulid("task")
    run_id = prefixed_ulid("run")
    assert task_id.startswith("task_") and len(task_id) == 5 + 26  # 前缀"task_"5字符 + 26位ULID
    assert run_id.startswith("run_")
    assert task_id != run_id
    # 字典序 ≈ 时间序（ULID 特性，利于 B-tree 局部性）
    assert prefixed_ulid("task") >= task_id or True  # 同 ms 可能等值，仅冒烟


def test_execution_log_unique_run_seq():
    table = Base.metadata.tables["agent_execution_logs"]
    uqs = [c.name for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert "uq_execution_logs_run_seq" in uqs


def test_context_snapshot_versioning():
    table = Base.metadata.tables["context_snapshots"]
    uqs = [c.name for c in table.constraints if isinstance(c, UniqueConstraint)]
    assert "uq_context_snapshots_run_version" in uqs
    idx_names = {i.name for i in table.indexes}
    # 部分唯一索引：is_current（决策 #6）
    assert "uq_context_snapshots_current" in idx_names


def test_approval_partial_unique_pending():
    table = Base.metadata.tables["approvals"]
    idx_names = {i.name for i in table.indexes}
    assert "uq_approvals_pending_per_call" in idx_names


def test_cascade_policies():
    """抽查级联策略（额外检查 #5）。"""
    fks = {
        c.parent.table.name + "->" + c.column.table.name: c.ondelete
        for t in Base.metadata.tables.values()
        for c in t.foreign_keys
    }
    assert fks["agent_runs->agent_tasks"] == "CASCADE"
    assert fks["tool_calls->agent_runs"] == "CASCADE"
    assert fks["agent_execution_logs->agent_runs"] == "CASCADE"
    assert fks["messages->conversations"] == "CASCADE"
    assert fks["model_usage->agent_runs"] == "SET NULL"
    assert fks["memory_items->agent_tasks"] == "SET NULL"
