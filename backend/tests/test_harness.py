"""Harness 域测试：权限矩阵 / 幂等 / 审批闸门 / 重试 / 超时 / 步数上限 / 事件日志（B2）。

- 真实链路 fixture：session 直接造 user→task→run（真实外键链 + 真实 commit），
  仿 tests/test_approvals_api.py 的写法；PG/Redis 不可用则如实跳过。
- registry：优先 build_default_registry()（B2 workspace/git 工具模块落地后自动生效）；
  模块尚未落地时回退为等价的最小 workspace 工具集（同一 ToolSpec 契约，
  handler 经 WorkspaceGuard 访问文件），保证本测试对 Harness 逻辑的断言独立成立。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import ApprovalStatus, RiskLevel, TaskStatus, ToolCallStatus
from app.db.redis import get_redis, init_redis
from app.db.session import get_session_factory, init_engine
from app.models.execution import AgentExecutionLog, Approval, ToolCall
from app.models.misc import Setting
from app.models.task import AgentRun, AgentTask
from app.repositories.users import UsersRepository
from app.services.health import get_readiness
from app.services.harness import HarnessService
from app.tools.base import ToolResult, ToolSpec
from app.tools.registry import ToolRegistry


# --------------------------------------------------------------------------- 基建
@pytest_asyncio.fixture
async def env() -> Iterator[None]:
    """初始化 engine/redis（幂等）；PG/Redis 不可用则如实跳过；
    用例后释放连接（asyncpg 连接绑定事件循环，跨用例复用会探活失败）。"""
    from app.db.redis import close_redis
    from app.db.session import dispose_engine

    settings = get_settings()
    init_engine(settings)
    init_redis(settings)
    ready, checks = await get_readiness()
    if not ready:
        pytest.skip(f"PG/Redis 未启动: {checks}")
    yield
    await dispose_engine()
    await close_redis()


@contextmanager
def patch_settings(**overrides: Any) -> Iterator[Any]:
    """直接改 get_settings() 缓存实例属性，用例后恢复原值。"""
    s = get_settings()
    old = {k: getattr(s, k) for k in overrides}
    for k, v in overrides.items():
        setattr(s, k, v)
    try:
        yield s
    finally:
        for k, v in old.items():
            setattr(s, k, v)


# ---- 等价最小 workspace 工具（仅当 B2 工具模块未落地时使用；同一契约） ----
async def _fb_read_file(ctx, args) -> ToolResult:
    from app.core.security import WorkspaceGuard

    guard = WorkspaceGuard(ctx.workspace)
    p = guard.resolve(ctx.workspace, args["path"])
    text = p.read_text(encoding="utf-8")
    return ToolResult(ok=True, summary=f"读取 {args['path']}（{len(text)} 字符）",
                      output={"path": args["path"], "content": text})


async def _fb_write_file(ctx, args) -> ToolResult:
    from app.core.security import WorkspaceGuard

    guard = WorkspaceGuard(ctx.workspace)
    p = guard.resolve(ctx.workspace, args["path"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(args["content"], encoding="utf-8")
    return ToolResult(ok=True, summary=f"写入 {args['path']}（{len(args['content'].encode('utf-8'))} 字节）",
                      output={"path": args["path"], "bytes": len(args["content"].encode("utf-8"))})


def _fallback_registry() -> ToolRegistry:
    reg = ToolRegistry()
    reg.register(ToolSpec(server="workspace", name="read_file", description="读取工作区文件",
                          risk=RiskLevel.SAFE, parameters={"path": "string"}, required=("path",),
                          handler=_fb_read_file))
    reg.register(ToolSpec(server="workspace", name="write_file", description="写入工作区文件",
                          risk=RiskLevel.DANGEROUS, parameters={"path": "string", "content": "string"},
                          required=("path", "content"), handler=_fb_write_file))
    return reg


def make_registry() -> ToolRegistry:
    """优先默认注册表；workspace 工具缺失时回退等价实现。"""
    try:
        from app.tools.registry import build_default_registry

        reg = build_default_registry()
        names = {s.full_name for s in reg.discover()}
        if {"workspace.read_file", "workspace.write_file"} <= names:
            return reg
    except Exception:
        pass
    return _fallback_registry()


# ---- fixture 数据（各用例独立新建，真实 commit） ----
async def _mk_task_run() -> tuple[str, str]:
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user(
            f"harness-{uuid.uuid4().hex[:10]}@evocode.local")
        now = datetime.now(timezone.utc)
        task = AgentTask(user_id=user.id, title="Harness 测试任务", description="",
                         model="auto", status=TaskStatus.EXECUTING, created_at=now, updated_at=now)
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=TaskStatus.EXECUTING, model="glm-5.3",
                       started_at=now, created_at=now, updated_at=now)
        session.add(run)
        await session.flush()
        await session.commit()
        return task.id, run.id


_PERMISSIONS_ABSENT = object()  # 哨兵：恢复时需删除该行


async def _set_permissions(session, mapping: dict) -> Any:
    """upsert settings(key='permissions')，返回恢复令牌（用例后必须 _restore_permissions）。"""
    row = (await session.execute(select(Setting).where(Setting.key == "permissions"))).scalar_one_or_none()
    if row is None:
        session.add(Setting(key="permissions", value=dict(mapping)))
        await session.flush()
        return _PERMISSIONS_ABSENT
    prev = row.value
    row.value = dict(mapping)
    await session.flush()
    return prev


async def _restore_permissions(session, token: Any) -> None:
    row = (await session.execute(select(Setting).where(Setting.key == "permissions"))).scalar_one_or_none()
    if row is None:
        return
    if token is _PERMISSIONS_ABSENT:
        await session.delete(row)
    else:
        row.value = token
    await session.commit()


async def _logs(session, run_id: str) -> list[AgentExecutionLog]:
    rows = (await session.execute(
        select(AgentExecutionLog).where(AgentExecutionLog.run_id == run_id).order_by(AgentExecutionLog.seq)
    )).scalars().all()
    return rows


# --------------------------------------------------------------------------- 用例
def _task_ws(workspace_base: str, task_id: str) -> Path:
    """任务工作区绝对路径：WORKSPACE_BASE/<task_id>/（与 HarnessService._build_ctx 一致）。"""
    return Path(workspace_base) / task_id


async def test_a_read_file_succeeded_with_logs(env, tmp_path):
    """a) read_file 正常执行：succeeded、duration_ms>0、started+completed 日志。"""
    task_id, run_id = await _mk_task_run()
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        f = _task_ws(s.WORKSPACE_BASE, task_id) / "hello.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("你好 harness", encoding="utf-8")
        async with get_session_factory()() as session:
            task = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            svc = HarnessService(session, redis=None, registry=make_registry())
            outcome = await svc.execute_tool(run, task, "workspace", "read_file", {"path": "hello.txt"})
            await session.commit()
            tc = await session.get(ToolCall, outcome.tool_call_id)
            logs = await _logs(session, run_id)
    assert outcome.status == "succeeded", f"outcome={outcome}, summary={tc.result_summary}"
    assert tc.status == ToolCallStatus.SUCCEEDED
    assert tc.duration_ms is not None and tc.duration_ms > 0
    assert [lg.event_type for lg in logs] == ["tool.call.started", "tool.call.completed"]
    assert logs[0].payload["toolCallId"] == outcome.tool_call_id
    assert logs[0].payload["tool"] == "workspace.read_file"
    assert logs[0].payload["args"] == {"path": "hello.txt"}


async def test_b_write_file_requires_approval(env, tmp_path):
    """b) write_file（require_approval）：suspended + pending Approval + 日志，文件未写入。"""
    task_id, run_id = await _mk_task_run()
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        async with get_session_factory()() as session:
            task = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            svc = HarnessService(session, redis=None, registry=make_registry())
            outcome = await svc.execute_tool(run, task, "workspace", "write_file",
                                             {"path": "hello.txt", "content": "abc"})
            await session.commit()
            tc = await session.get(ToolCall, outcome.tool_call_id)
            apv = await session.get(Approval, outcome.approval_id)
            logs = await _logs(session, run_id)
            target = _task_ws(s.WORKSPACE_BASE, task_id) / "hello.txt"
    assert outcome.status == "suspended"
    assert outcome.approval_id is not None
    assert tc.status == ToolCallStatus.RUNNING
    assert apv.status == ApprovalStatus.PENDING
    assert apv.tool == "workspace.write_file"
    assert apv.risk == RiskLevel.DANGEROUS
    assert "approval.requested" in [lg.event_type for lg in logs]
    assert not target.exists()


async def test_c_approve_then_resume_writes_disk(env, tmp_path):
    """c) 批准后 resume：succeeded，文件真实写入磁盘。"""
    task_id, run_id = await _mk_task_run()
    content = "批准后写入的内容"
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        async with get_session_factory()() as session:
            task = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            svc = HarnessService(session, redis=None, registry=make_registry())
            outcome = await svc.execute_tool(run, task, "workspace", "write_file",
                                             {"path": "hello.txt", "content": content})
            assert outcome.status == "suspended"
            apv = await session.get(Approval, outcome.approval_id)
            apv.status = ApprovalStatus.APPROVED
            apv.resolved_by = "user"
            apv.resolved_at = datetime.now(timezone.utc)
            await session.commit()
            resumed = await svc.resume_tool_call(outcome.tool_call_id)
            await session.commit()
            tc = await session.get(ToolCall, outcome.tool_call_id)
            logs = await _logs(session, run_id)
            target = _task_ws(s.WORKSPACE_BASE, task_id) / "hello.txt"
    assert resumed.status == "succeeded"
    assert tc.status == ToolCallStatus.SUCCEEDED
    assert tc.duration_ms is not None and tc.duration_ms > 0
    assert target.exists() and target.read_text(encoding="utf-8") == content
    completed = [lg for lg in logs if lg.event_type == "tool.call.completed"]
    assert len(completed) == 1 and completed[0].payload["approvalResolved"] is True


async def test_d_reject_then_resume_conflict(env, tmp_path):
    """d) 拒绝路径：reject 后 Approval=rejected、ToolCall=cancelled；resume → 409。"""
    from app.core.exceptions import BizException

    task_id, run_id = await _mk_task_run()
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        async with get_session_factory()() as session:
            task = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            svc = HarnessService(session, redis=None, registry=make_registry())
            outcome = await svc.execute_tool(run, task, "workspace", "write_file",
                                             {"path": "hello.txt", "content": "x"})
            assert outcome.status == "suspended"
            rejected = await svc.reject_tool_call(outcome.tool_call_id)
            await session.commit()
            apv = await session.get(Approval, outcome.approval_id)
            tc = await session.get(ToolCall, outcome.tool_call_id)
            logs = await _logs(session, run_id)
            assert rejected.status == "cancelled"
            assert apv.status == ApprovalStatus.REJECTED
            assert apv.resolved_by == "user" and apv.resolved_at is not None
            assert tc.status == ToolCallStatus.CANCELLED
            assert {"approval.resolved", "tool.call.cancelled"} <= {lg.event_type for lg in logs}
            with pytest.raises(BizException) as ei:
                await svc.resume_tool_call(outcome.tool_call_id)
    assert ei.value.status_code == 409
    assert ei.value.code == "conflict"
    assert ei.value.details["currentStatus"] == "rejected"
    assert not (_task_ws(s.WORKSPACE_BASE, task_id) / "hello.txt").exists()


async def test_e_disabled_policy(env, tmp_path):
    """e) settings 覆盖 disabled（真实插行）：rejected + ToolCall failed。"""
    task_id, run_id = await _mk_task_run()
    token = _PERMISSIONS_ABSENT
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")):
        async with get_session_factory()() as session:
            try:
                task = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                token = await _set_permissions(session, {"workspace.read_file": "disabled"})
                await session.commit()
                svc = HarnessService(session, redis=None, registry=make_registry())
                outcome = await svc.execute_tool(run, task, "workspace", "read_file", {"path": "hello.txt"})
                await session.commit()
                tc = await session.get(ToolCall, outcome.tool_call_id)
                logs = await _logs(session, run_id)
            finally:
                await _restore_permissions(session, token)
    assert outcome.status == "rejected"
    assert tc.status == ToolCallStatus.FAILED
    assert tc.result_summary == "权限拒绝：工具已禁用"
    assert [lg.event_type for lg in logs] == ["tool.call.started", "tool.call.failed"]


async def test_f_override_require_approval(env, tmp_path):
    """f) settings 覆盖 read_file 为 require_approval：同样走审批闸门。"""
    task_id, run_id = await _mk_task_run()
    token = _PERMISSIONS_ABSENT
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        f = _task_ws(s.WORKSPACE_BASE, task_id) / "hello.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("secret", encoding="utf-8")
        async with get_session_factory()() as session:
            try:
                task = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                token = await _set_permissions(session, {"workspace.read_file": "require_approval"})
                await session.commit()
                svc = HarnessService(session, redis=None, registry=make_registry())
                outcome = await svc.execute_tool(run, task, "workspace", "read_file", {"path": "hello.txt"})
                await session.commit()
                apv = await session.get(Approval, outcome.approval_id)
                tc = await session.get(ToolCall, outcome.tool_call_id)
                logs = await _logs(session, run_id)
            finally:
                await _restore_permissions(session, token)
    assert outcome.status == "suspended"
    assert apv is not None and apv.status == ApprovalStatus.PENDING
    assert apv.tool == "workspace.read_file"
    assert tc.status == ToolCallStatus.RUNNING
    assert "approval.requested" in [lg.event_type for lg in logs]
    assert "tool.call.completed" not in [lg.event_type for lg in logs]


async def test_g_timeout_no_real_wait(env, tmp_path):
    """g) 超时：fake 挂起工具，timeout=1s、retries=0 → failed 含超时语义，且不真等 5s。"""
    task_id, run_id = await _mk_task_run()
    reg = make_registry()

    async def hang(ctx, args) -> ToolResult:
        await asyncio.sleep(5)
        raise AssertionError("不应执行到这里")

    reg.register(ToolSpec(server="test", name="hang", description="挂起工具",
                          risk=RiskLevel.SAFE, parameters={}, handler=hang))
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws"),
                        TOOL_TIMEOUT_SECONDS=1, TOOL_MAX_RETRIES=0):
        async with get_session_factory()() as session:
            token = _PERMISSIONS_ABSENT
            try:
                token = await _set_permissions(session, {"test.hang": "auto"})
                await session.commit()
                task = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                svc = HarnessService(session, redis=None, registry=reg)
                start = time.perf_counter()
                outcome = await svc.execute_tool(run, task, "test", "hang", {})
                elapsed = time.perf_counter() - start
                await session.commit()
                tc = await session.get(ToolCall, outcome.tool_call_id)
                logs = await _logs(session, run_id)
            finally:
                await _restore_permissions(session, token)
    assert outcome.status == "failed"
    assert "超时" in tc.result_summary or "timeout" in (tc.result_summary or "").lower()
    assert tc.status == ToolCallStatus.FAILED
    assert 1.0 <= elapsed < 4.5
    failed = [lg for lg in logs if lg.event_type == "tool.call.failed"]
    assert len(failed) == 1 and failed[0].payload["attempts"] == 1


async def test_h_retry_then_succeed(env, tmp_path):
    """h) 重试成功：第一次抛异常、第二次 ok，retries=1 → succeeded，日志 attempts=2。"""
    task_id, run_id = await _mk_task_run()
    reg = make_registry()
    state = {"n": 0}

    async def flaky(ctx, args) -> ToolResult:
        if state["n"] == 0:
            state["n"] = 1
            raise RuntimeError("boom")
        return ToolResult(ok=True, summary="第二次成功", output={"n": state["n"]})

    reg.register(ToolSpec(server="test", name="flaky", description="重试工具",
                          risk=RiskLevel.SAFE, parameters={}, handler=flaky))
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws"), TOOL_MAX_RETRIES=1):
        async with get_session_factory()() as session:
            token = _PERMISSIONS_ABSENT
            try:
                token = await _set_permissions(session, {"test.flaky": "auto"})
                await session.commit()
                task = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                svc = HarnessService(session, redis=None, registry=reg)
                outcome = await svc.execute_tool(run, task, "test", "flaky", {})
                await session.commit()
                tc = await session.get(ToolCall, outcome.tool_call_id)
                logs = await _logs(session, run_id)
            finally:
                await _restore_permissions(session, token)
    assert outcome.status == "succeeded"
    assert state["n"] == 1
    assert tc.status == ToolCallStatus.SUCCEEDED
    assert tc.result_summary == "第二次成功"
    completed = [lg for lg in logs if lg.event_type == "tool.call.completed"]
    assert len(completed) == 1 and completed[0].payload["attempts"] == 2


async def test_i_invalid_args_no_retry(env, tmp_path):
    """i) 参数校验失败：write_file 缺 path（覆盖为 auto 后执行）→ failed，无重试。"""
    task_id, run_id = await _mk_task_run()
    token = _PERMISSIONS_ABSENT
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        async with get_session_factory()() as session:
            try:
                task = await session.get(AgentTask, task_id)
                run = await session.get(AgentRun, run_id)
                token = await _set_permissions(session, {"workspace.write_file": "auto"})
                await session.commit()
                svc = HarnessService(session, redis=None, registry=make_registry())
                outcome = await svc.execute_tool(run, task, "workspace", "write_file", {"content": "x"})
                await session.commit()
                tc = await session.get(ToolCall, outcome.tool_call_id)
                logs = await _logs(session, run_id)
                approvals = (await session.execute(select(Approval).where(Approval.run_id == run_id))).scalars().all()
            finally:
                await _restore_permissions(session, token)
    assert outcome.status == "failed"
    assert "参数校验" in (tc.result_summary or "")
    assert tc.status == ToolCallStatus.FAILED
    assert approvals == []  # auto 策略不产生审批
    failed = [lg for lg in logs if lg.event_type == "tool.call.failed"]
    assert len(failed) == 1 and failed[0].payload["reason"] == "invalid_args"
    assert not (_task_ws(s.WORKSPACE_BASE, task_id) / "hello.txt").exists()


async def test_j_max_steps_limit(env, tmp_path):
    """j) 步数上限：TOOL_MAX_STEPS=1，第 2 次执行 → failed 含 '最大执行步数'。"""
    task_id, run_id = await _mk_task_run()
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws"), TOOL_MAX_STEPS=1) as s:
        for name in ("hello.txt", "b.txt"):
            f = _task_ws(s.WORKSPACE_BASE, task_id) / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("x", encoding="utf-8")
        async with get_session_factory()() as session:
            task = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            svc = HarnessService(session, redis=None, registry=make_registry())
            first = await svc.execute_tool(run, task, "workspace", "read_file", {"path": "hello.txt"})
            assert first.status == "succeeded"
            second = await svc.execute_tool(run, task, "workspace", "read_file", {"path": "b.txt"})
            await session.commit()
            tc = await session.get(ToolCall, second.tool_call_id)
            logs = await _logs(session, run_id)
    assert second.status == "failed"
    assert "最大执行步数" in (tc.result_summary or "")
    assert tc.status == ToolCallStatus.FAILED
    failed = [lg for lg in logs if lg.event_type == "tool.call.failed"]
    assert len(failed) == 1 and failed[0].payload["reason"] == "max_steps_exceeded"


async def test_k_redis_idempotent_replay(env, tmp_path):
    """k) Redis 幂等：同 args 两次 execute → 第二次 replayed 且 tool_call_id 相同。"""
    task_id, run_id = await _mk_task_run()
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        f = _task_ws(s.WORKSPACE_BASE, task_id) / "hello.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("idem", encoding="utf-8")
        async with get_session_factory()() as session:
            task = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            svc = HarnessService(session, redis=get_redis(), registry=make_registry())
            args = {"path": "hello.txt"}
            key = HarnessService._idem_key(run, "workspace", "read_file", args)
            try:
                first = await svc.execute_tool(run, task, "workspace", "read_file", args)
                assert first.status == "succeeded"
                second = await svc.execute_tool(run, task, "workspace", "read_file", args)
                await session.commit()
            finally:
                await get_redis().delete(key)
    assert second.status == "replayed"
    assert second.tool_call_id == first.tool_call_id
    assert second.result["toolCallStatus"] == "succeeded"


async def test_l_different_args_not_replayed(env, tmp_path):
    """l) 幂等键不同 args → 不同 tool_call（不命中 replay）。"""
    task_id, run_id = await _mk_task_run()
    with patch_settings(WORKSPACE_BASE=str(tmp_path / "ws")) as s:
        for name in ("hello.txt", "b.txt"):
            f = _task_ws(s.WORKSPACE_BASE, task_id) / name
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(name, encoding="utf-8")
        async with get_session_factory()() as session:
            task = await session.get(AgentTask, task_id)
            run = await session.get(AgentRun, run_id)
            svc = HarnessService(session, redis=get_redis(), registry=make_registry())
            k1 = HarnessService._idem_key(run, "workspace", "read_file", {"path": "hello.txt"})
            k2 = HarnessService._idem_key(run, "workspace", "read_file", {"path": "b.txt"})
            try:
                first = await svc.execute_tool(run, task, "workspace", "read_file", {"path": "hello.txt"})
                second = await svc.execute_tool(run, task, "workspace", "read_file", {"path": "b.txt"})
                await session.commit()
            finally:
                await get_redis().delete(k1, k2)
    assert first.status == "succeeded"
    assert second.status == "succeeded"  # 非 replayed
    assert second.tool_call_id != first.tool_call_id
