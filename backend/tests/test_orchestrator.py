"""编排器全流程测试（B3）：FakeLLM 注入 + 真实 PG/Redis + 真实工具执行。

场景：审批批准恢复、审批拒绝→重规划、重规划上限失败、取消、
LLM 未配置诚实失败、写盘/测试工具真实执行与事件合成。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agents.orchestrator import AgentOrchestrator
from app.core.config import get_settings
from app.core.enums import AgentRole, TaskStatus
from app.db.session import get_session_factory
from app.llm.client import BaseLLMClient, LLMResponse
from app.models.conversation import Conversation, Message
from app.models.execution import AgentExecutionLog, Approval, ToolCall
from app.models.misc import ModelUsage, Setting
from app.models.task import AgentRun, AgentTask
from app.repositories.users import UsersRepository


@pytest_asyncio.fixture(autouse=True)
async def db_stack():
    """每个用例在自己的事件循环里初始化 engine/redis（与 conftest.app_client 同语义）。

    编排器测试不经过 app_client，若不显式初始化，get_session_factory() 不可用、
    readiness 探针误报 False。teardown 对称释放。
    """
    from app.core.config import get_settings
    from app.db.redis import close_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    settings = get_settings()
    init_engine(settings)
    init_redis(settings)
    yield
    await close_redis()
    await dispose_engine()


class FakeLLM(BaseLLMClient):
    """脚本化 LLM：按序返回预设响应；异常对象直接抛出（依赖注入，非生产代码）。"""

    def __init__(self, responses: list) -> None:
        self._q = list(responses)
        self.calls: list[list[LLMMessage]] = []

    @property
    def configured(self) -> bool:
        return True

    async def chat(self, messages, *, model=None, temperature=None, max_tokens=None):
        self.calls.append(messages)
        item = self._q.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def resp(obj) -> LLMResponse:
    content = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False)
    return LLMResponse(content=content, model="glm-5.3",
                       prompt_tokens=10, completion_tokens=5, latency_ms=1)


async def _mk_task(title: str) -> str:
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title=title, description="编排器测试任务",
                         model="auto", status=TaskStatus.QUEUED,
                         created_at=datetime.now(timezone.utc),
                         updated_at=datetime.now(timezone.utc))
        session.add(task)
        await session.commit()
        return task.id


async def _wait_terminal(run_id: str, timeout: float = 30.0) -> AgentRun:
    factory = get_session_factory()
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        async with factory() as session:
            run = await session.get(AgentRun, run_id)
            if run is not None and run.status in TaskStatus.terminal():
                return run
        await asyncio.sleep(0.2)
    raise TimeoutError(f"run {run_id} 未在 {timeout}s 内到达终态")


async def _events(run_id: str) -> list[AgentExecutionLog]:
    factory = get_session_factory()
    async with factory() as session:
        rows = list((await session.execute(
            select(AgentExecutionLog).where(AgentExecutionLog.run_id == run_id)
            .order_by(AgentExecutionLog.seq.asc())
        )).scalars().all())
        for r in rows:
            session.expunge(r)
        return rows


def _mk_orch(responses: list) -> AgentOrchestrator:
    return AgentOrchestrator(session_factory=get_session_factory(),
                             redis=None, llm=FakeLLM(responses))


async def test_full_flow_with_approval_resume(deps_available: bool):
    """规划→写文件(危险→审批挂起)→批准→续跑→跑测试→复核→completed。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id = await _mk_task("B3 全流程-批准")
    orch = _mk_orch([
        resp({"steps": [{"index": 1, "title": "写入问候文件"},
                        {"index": 2, "title": "运行测试"}]}),
        resp({"action": "tool", "server": "workspace", "tool": "write_file",
              "args": {"path": "hello.txt", "content": "你好\n第二行", "create_dirs": False}}),
        resp({"action": "done", "summary": "文件已写入"}),
        resp({"action": "tool", "server": "workspace", "tool": "run_tests", "args": {}}),
        resp({"action": "done", "summary": "测试通过，步骤完成"}),
        resp({"verdict": "pass", "summary": "文件已写入且测试通过"}),
    ])
    # 预置一个会通过的测试文件（run_tests 真实执行）
    ws = Path(get_settings().WORKSPACE_BASE) / task_id
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "test_ok.py").write_text("def test_ok():\n    assert 1 + 1 == 2\n", encoding="utf-8")

    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(AgentTask, task_id)
        run, _ = await orch._create_run(session, task)
        run_id = run.id
        await session.commit()

    await orch.drive(run_id)  # 应在 write_file 审批处挂起
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        assert str(getattr(run.status, "value", run.status)) == "waiting_approval"
        apv = (await session.execute(
            select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
        )).scalar_one_or_none()
        assert apv is not None
        apv_id = apv.id

    # 批准 → 续跑到终态（后台 drive 由 resume_after_approval 调度）
    async with factory() as session:
        apv = await session.get(Approval, apv_id)
        apv.status = "approved"
        apv.resolved_by = "user"
        from datetime import datetime as dt, timezone as tz

        apv.resolved_at = dt.now(tz.utc)
        await session.commit()
    await orch.resume_after_approval(apv_id, "approved")
    run = await _wait_terminal(run_id)
    assert str(getattr(run.status, "value", run.status)) == "completed"
    assert run.replan_count == 0
    assert run.tokens_in > 0 and run.tokens_out > 0 and run.tool_calls >= 2

    # 真实写盘 + 真实测试执行 + 事件合成
    assert (Path(get_settings().WORKSPACE_BASE) / task_id / "hello.txt").exists()
    events = await _events(run_id)
    types = [e.event_type for e in events]
    assert "plan.updated" in types and "approval.requested" in types
    assert "approval.resolved" in types and "run.completed" in types
    assert "code.diff.created" in types  # write_file 合成真实 diff
    assert "test.finished" in types      # run_tests 合成测试结果
    diff_event = next(e for e in events if e.event_type == "code.diff.created")
    diff = diff_event.payload["diff"]
    assert diff["files"][0]["path"] == "hello.txt"
    assert diff["files"][0]["additions"] >= 2  # 你好/第二行
    seqs = [e.seq for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)  # 事件溯源唯一递增


async def test_approval_rejected_triggers_replan(deps_available: bool):
    """拒绝→replanner 修订→完成，replan_count=1。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id = await _mk_task("B3 拒绝重规划")
    orch = _mk_orch([
        resp({"steps": [{"index": 1, "title": "危险写入"}]}),
        resp({"action": "tool", "server": "workspace", "tool": "write_file",
              "args": {"path": "danger.txt", "content": "x"}}),
        resp({"steps": [{"index": 1, "title": "安全方案：直接记录结论"}]}),
        resp({"action": "done", "summary": "改用安全方案完成"}),
        resp({"verdict": "pass", "summary": "安全方案完成"}),
    ])
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(AgentTask, task_id)
        run, _ = await orch._create_run(session, task)
        run_id = run.id
        await session.commit()
    await orch.drive(run_id)
    async with factory() as session:
        apv = (await session.execute(
            select(Approval).where(Approval.run_id == run_id, Approval.status == "pending")
        )).scalar_one_or_none()
        apv_id = apv.id
    # 路由会先置 rejected；此处模拟路由后的状态，再由编排器恢复
    async with factory() as session:
        apv = await session.get(Approval, apv_id)
        apv.status = "rejected"
        apv.resolved_by = "user"
        await session.commit()
    await orch.resume_after_approval(apv_id, "rejected")
    run = await _wait_terminal(run_id)
    assert str(getattr(run.status, "value", run.status)) == "completed"
    assert run.replan_count == 1
    assert not (Path(get_settings().WORKSPACE_BASE) / task_id / "danger.txt").exists()
    events = await _events(run_id)
    assert any(e.event_type == "approval.resolved" and e.payload.get("status") == "rejected"
               for e in events)


async def test_replan_limit_fails(deps_available: bool):
    """复核连续失败达 AGENT_MAX_REPLANS → failed，不再无限重规划。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id = await _mk_task("B3 重规划上限")
    fail_review = {"verdict": "fail", "summary": "仍未达标"}
    plan = {"steps": [{"index": 1, "title": "尝试修复"}]}
    orch = _mk_orch([
        resp(plan), resp({"action": "done", "summary": "尝试完成"}), resp(fail_review),
        resp(plan), resp({"action": "done", "summary": "再次尝试"}), resp(fail_review),
        resp(plan), resp({"action": "done", "summary": "第三次尝试"}), resp(fail_review),
    ])
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(AgentTask, task_id)
        run, _ = await orch._create_run(session, task)
        run_id = run.id
        await session.commit()
    await orch.drive(run_id)
    run = await _wait_terminal(run_id)
    assert str(getattr(run.status, "value", run.status)) == "failed"
    assert run.replan_count == get_settings().AGENT_MAX_REPLANS


async def test_model_unavailable_fails_honestly(deps_available: bool):
    """LLM 调用失败（如 key 缺失）→ run 真实 failed + run.failed 事件，不假装完成。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    from app.core.exceptions import BizException
    from app.core.response import ErrorCode

    task_id = await _mk_task("B3 模型不可用")
    orch = _mk_orch([BizException(ErrorCode.MODEL_UNAVAILABLE, "GLM_API_KEY 未配置", status_code=503)])
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(AgentTask, task_id)
        run, _ = await orch._create_run(session, task)
        run_id = run.id
        await session.commit()
    await orch.drive(run_id)
    run = await _wait_terminal(run_id)
    assert str(getattr(run.status, "value", run.status)) == "failed"
    events = await _events(run_id)
    assert any(e.event_type == "run.failed" for e in events)


async def test_cancel_cooperative(deps_available: bool):
    """用户取消：waiting_approval 挂起状态取消后，drive 协作式退出不改终态。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id = await _mk_task("B3 取消")
    orch = _mk_orch([
        resp({"steps": [{"index": 1, "title": "危险写入"}]}),
        resp({"action": "tool", "server": "workspace", "tool": "write_file",
              "args": {"path": "c.txt", "content": "x"}}),
    ])
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(AgentTask, task_id)
        run, _ = await orch._create_run(session, task)
        run_id = run.id
        await session.commit()
    await orch.drive(run_id)
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        assert str(getattr(run.status, "value", run.status)) == "waiting_approval"
        # 用户取消（与 POST /tasks/:id/cancel 的终态迁移一致）
        run.status = TaskStatus.CANCELLED
        run.finished_at = datetime.now(timezone.utc)
        task = await session.get(AgentTask, task_id)
        task.status = TaskStatus.CANCELLED
        await session.commit()
    await orch.drive(run_id)
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        assert str(getattr(run.status, "value", run.status)) == "cancelled"


async def test_compression_integration_context_updated(deps_available: bool):
    """B4 集成：阈值触发压缩 → context.updated 事件 + executor 提示词携带摘要块。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id = await _mk_task_with_long_history("B4 压缩集成")
    factory = get_session_factory()
    # 极低阈值触发压缩（用例后清理，避免污染其它用例）
    async with factory() as session:
        session.add(Setting(key="system", value={"contextWindowTokens": 32000,
                                                 "compressionThreshold": 1}))
        await session.commit()
    orch = _mk_orch([
        resp({"steps": [{"index": 1, "title": "读取缺失文件"}]}),
        resp("压缩摘要包含重要标记：此前历史已压缩"),
        resp({"action": "done", "summary": "完成"}),
        resp({"verdict": "pass", "summary": "完成"}),
    ])
    try:
        async with factory() as session:
            task = await session.get(AgentTask, task_id)
            run, _ = await orch._create_run(session, task)
            run_id = run.id
            await session.commit()
        await orch.drive(run_id)
        run = await _wait_terminal(run_id)
        assert str(getattr(run.status, "value", run.status)) == "completed"
        # context.updated 事件已发出
        events = await _events(run_id)
        ctx_events = [e for e in events if e.event_type == "context.updated"]
        assert len(ctx_events) >= 1
        session_payload = ctx_events[-1].payload["session"]
        assert {"id", "runId", "windowTokens", "usedTokens", "segments",
                "compressionEvents"} <= set(session_payload.keys())
        # executor 提示词携带压缩摘要块（FakeLLM.calls: [planner, summarize, executor, reviewer]）
        executor_call = orch._llm.calls[2]
        assert "压缩摘要包含重要标记" in executor_call[1].content
    finally:
        async with factory() as session:
            row = (await session.execute(
                select(Setting).where(Setting.key == "system")
            )).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.commit()


async def _mk_task_with_long_history(title: str) -> str:
    now = datetime.now(timezone.utc)
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title=title, description="长历史压缩集成测试",
                         model="auto", status=TaskStatus.QUEUED,
                         created_at=now, updated_at=now)
        session.add(task)
        await session.flush()
        conv = Conversation(task_id=task.id, user_id=user.id, title=title)
        session.add(conv)
        await session.flush()
        for i in range(6):
            session.add(Message(conversation_id=conv.id, run_id=None, role=AgentRole.USER,
                                content=f"历史片段 {i}：" + "多轮上下文素材" * 40,
                                created_at=now))
        await session.commit()
        return task.id


async def test_api_create_stays_queued_without_key(app_client, deps_available: bool):
    """GLM_API_KEY 为空：POST /tasks 不启动 run（诚实保持 queued，不假装执行）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    if str(get_settings().GLM_API_KEY).strip():
        pytest.skip("GLM_API_KEY 已配置，『无密钥不启动』用例不适用")
    r = await app_client.post("/api/v1/tasks", json={"title": "无密钥不启动", "description": ""})
    assert r.status_code == 201
    task_id = r.json()["id"]
    await asyncio.sleep(1.5)  # 给 bootstrap 充分时间（若错误启动会出现 run）
    factory = get_session_factory()
    async with factory() as session:
        task = await session.get(AgentTask, task_id)
        assert str(getattr(task.status, "value", task.status)) == "queued"
        assert task.latest_run_id is None
