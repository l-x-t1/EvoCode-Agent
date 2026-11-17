"""Context Manager 测试（B4）：窗口组装 / token 统计 / 阈值压缩 / 快照链 / 恢复重建 / API。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.context.manager import ContextManager, estimate_tokens
from app.core.config import get_settings
from app.core.enums import AgentRole, ContextTrigger, TaskStatus
from app.db.session import get_session_factory
from app.models.context import ContextSnapshot
from app.models.conversation import Conversation, Message
from app.models.execution import ToolCall
from app.models.misc import Setting
from app.models.task import AgentRun, AgentTask, Plan, PlanStep
from app.repositories.users import UsersRepository


@pytest_asyncio.fixture(autouse=True)
async def db_stack():
    from app.db.redis import close_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    settings = get_settings()
    init_engine(settings)
    init_redis(settings)
    yield
    await close_redis()
    await dispose_engine()


def _now():
    return datetime.now(timezone.utc)


async def _mk_task_with_run(title: str, *, messages: int = 0, with_plan: bool = False,
                            with_write_call: bool = False) -> tuple[str, str]:
    """真实外键链：user→task(+conversation/messages)→run(+plan/steps/tool_calls)。"""
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title=title,
                         description="目标：修复时区缺陷；约束：不改公共 API",
                         model="auto", status=TaskStatus.EXECUTING,
                         skill_ids=[], created_at=_now(), updated_at=_now())
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=TaskStatus.EXECUTING, model="glm-5.3",
                       started_at=_now(), created_at=_now(), updated_at=_now())
        session.add(run)
        await session.flush()
        conv = Conversation(task_id=task.id, user_id=user.id, title=title)
        session.add(conv)
        await session.flush()
        for i in range(messages):
            session.add(Message(conversation_id=conv.id, run_id=None, role=AgentRole.USER,
                                content=f"历史消息 {i}：" + "上下文内容" * 30,
                                created_at=_now()))
        if with_plan:
            plan = Plan(run_id=run.id, revision=1, created_at=_now())
            session.add(plan)
            await session.flush()
            session.add(PlanStep(plan_id=plan.id, idx=1, title="已完成步骤甲",
                                 agent=AgentRole.EXECUTOR, status="done", attempt=1,
                                 tool_call_ids=[], created_at=_now()))
            session.add(PlanStep(plan_id=plan.id, idx=2, title="未完成步骤乙",
                                 agent=AgentRole.EXECUTOR, status="pending", attempt=1,
                                 tool_call_ids=[], created_at=_now()))
        if with_write_call:
            session.add(ToolCall(run_id=run.id, plan_step_id=None, server="workspace",
                                 tool="write_file", args={"path": "src/app.py"},
                                 result_summary="写入 src/app.py（100 字节）", status="succeeded",
                                 risk="gated", duration_ms=10,
                                 result={"path": "src/app.py", "bytes": 100},
                                 created_at=_now(), updated_at=_now()))
        await session.commit()
        return task.id, run.id


def _clear_system_setting() -> None:
    """用例内通过 monkeypatch 替代：这里提供删除/恢复 settings 行的辅助。"""


async def test_estimate_tokens_deterministic():
    cjk = estimate_tokens("你好世界" * 10)          # 40 个 CJK 字符
    ascii_text = estimate_tokens("a" * 400)          # 400 个 ASCII 字符
    assert cjk == 40
    assert ascii_text == 100                         # 1 token / 4 字符
    assert estimate_tokens("") == 0


async def test_assemble_segments_and_recovery_rebuild(deps_available: bool):
    """恢复重建：目标/约束、已完成与未完成步骤、工具结果、代码位置、历史全在窗口中。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id, run_id = await _mk_task_with_run(
        "B4 组装", messages=5, with_plan=True, with_write_call=True)
    factory = get_session_factory()
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        task = await session.get(AgentTask, task_id)
        window = await ContextManager(session).assemble(run, task)
    keys = {s["key"] for s in window.segments}
    assert {"system", "history", "working"} <= keys
    assert window.used_tokens == sum(s["tokens"] for s in window.segments) > 0
    assert "修复时区缺陷" in window.system_text and "不改公共 API" in window.system_text
    assert "已完成步骤" in window.working_text and "已完成步骤甲" in window.working_text
    assert "未完成步骤乙" in window.working_text
    assert "workspace.write_file" in window.working_text
    assert "src/app.py" in window.working_text          # 重要代码位置
    assert "历史消息" in window.history_text


async def test_initial_snapshot_and_compression_chain(deps_available: bool):
    """初始快照 v1 → 阈值触发压缩 → v2（before>after、摘要、is_current 链）。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id, run_id = await _mk_task_with_run("B4 压缩链", messages=8, with_plan=True)
    factory = get_session_factory()

    # 极低阈值：写入 settings 表 key='system'（真实覆盖路径；用例后必须清理，
    # 否则后续编排器测试每次执行都会触发压缩并打乱 FakeLLM 队列）
    async with factory() as session:
        session.add(Setting(key="system", value={"contextWindowTokens": 32000,
                                                 "compressionThreshold": 1}))
        await session.commit()
    try:
        await _compression_chain_assertions(task_id, run_id)
    finally:
        async with factory() as session:
            row = (await session.execute(
                select(Setting).where(Setting.key == "system")
            )).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.commit()


async def _compression_chain_assertions(task_id: str, run_id: str) -> None:
    factory = get_session_factory()
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        task = await session.get(AgentTask, task_id)
        mgr = ContextManager(session)
        snap1 = await mgr._save_snapshot(run, await mgr.assemble(run, task),
                                         trigger=ContextTrigger.INITIAL)
        assert snap1.version == 1 and snap1.is_current is True
        await session.commit()

    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        task = await session.get(AgentTask, task_id)
        snap2, window = await ContextManager(session).maybe_compress(run, task, llm=None)
        await session.commit()  # 快照持久化（新会话校验 is_current 链的前提）
    assert snap2 is not None
    assert snap2.version == 2 and snap2.is_current is True
    assert snap2.before_tokens is not None and snap2.after_tokens is not None
    assert snap2.before_tokens > snap2.after_tokens          # 压缩确实缩减
    assert snap2.summary and snap2.summary.startswith("（自动摘要）")
    assert snap2.compressed_at is not None
    # is_current 链：v1 翻为历史，v2 唯一当前
    async with factory() as session:
        rows = list((await session.execute(
            select(ContextSnapshot).where(ContextSnapshot.run_id == run_id)
            .order_by(ContextSnapshot.version.asc())
        )).scalars().all())
        flags = [(r.version, r.is_current) for r in rows]
        assert flags == [(1, False), (2, True)]
    # 压缩后组装：compressed 段出现，history 只含压缩点之后的消息
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        task = await session.get(AgentTask, task_id)
        window = await ContextManager(session).assemble(run, task)
    comp = next(s for s in window.segments if s["key"] == "compressed")
    assert comp["tokens"] > 0
    assert "（自动摘要）" in window.compressed_text


async def test_no_compress_below_threshold(deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id, run_id = await _mk_task_with_run("B4 不压缩", messages=2)
    factory = get_session_factory()
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        task = await session.get(AgentTask, task_id)
        snap, _ = await ContextManager(session).maybe_compress(run, task, llm=None)
    assert snap is None  # 默认阈值 24000，未触发


async def test_context_sessions_api(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id, run_id = await _mk_task_with_run("B4 会话API", messages=3, with_plan=True)
    r = await app_client.get("/api/v1/context/sessions?limit=20")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items"}
    mine = next((s for s in body["items"] if s["id"] == run_id), None)
    assert mine is not None
    assert mine["runId"] == run_id
    assert mine["windowTokens"] > 0 and mine["usedTokens"] > 0
    assert all(set(seg.keys()) == {"key", "tokens"} for seg in mine["segments"])
    # 详情
    r2 = await app_client.get(f"/api/v1/context/sessions/{run_id}")
    assert r2.status_code == 200
    assert r2.json()["id"] == run_id
    # 404 统一错误体
    r3 = await app_client.get("/api/v1/context/sessions/run_notexist000000000000")
    assert r3.status_code == 404
    assert r3.json()["error"]["code"] == "not_found"


async def test_summaries_api_derived_from_snapshots(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id, run_id = await _mk_task_with_run("B4 摘要API", messages=4, with_plan=True)
    factory = get_session_factory()
    async with factory() as session:
        run = await session.get(AgentRun, run_id)
        task = await session.get(AgentTask, task_id)
        mgr = ContextManager(session)
        window = await mgr.assemble(run, task)
        window.compressed_text = "（自动摘要）测试摘要内容"
        window.segments = [{"key": s["key"],
                            "tokens": 0 if s["key"] == "history" else s["tokens"]}
                           for s in window.segments]
        window.used_tokens = sum(s["tokens"] for s in window.segments)
        await mgr._save_snapshot(run, window, trigger="threshold",
                                 summary="（自动摘要）测试摘要内容",
                                 before_tokens=window.used_tokens + 100)
        await session.commit()
    r = await app_client.get("/api/v1/context/summaries")
    assert r.status_code == 200
    items = r.json()["items"]
    mine = next((s for s in items if s["sourceTaskId"] == task_id), None)
    assert mine is not None
    assert mine["content"].startswith("（自动摘要）")
    assert mine["title"] == "B4 摘要API"
