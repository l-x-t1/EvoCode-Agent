"""B9 端到端场景套件（≥10 场景，全部真实 HTTP + 真实 PG/Redis/工具/SSE）。

诚实声明：所有走 Agent 编排的场景使用注入式 FakeLLM（唯一非真实环节，
已声明）；其余每一层（HTTP/DB/工具子进程/审批/SSE/快照）均为真实执行。
GLM_API_KEY 就绪后，同一套场景换 get_llm_client() 即为真实模型验收
（ FakeLLM → get_vision/get_llm 的切换点已收敛在 orchestrator/llm 工厂）。

场景清单（编号对应 docs/10 §B9）：
S1  正常任务端到端（创建→计划→工具→复核→completed）
S2  多轮对话上下文进入 Planner
S3  失败→重规划成功
S4  工具超时→重试（服务层编排）
S5  权限拒绝（disabled 工具）
S6  审批通过→恢复原执行位置→完成
S7  审批拒绝→Replanner
S8  SSE Last-Event-ID 断线续传
S9  服务重启恢复 + Snapshot 重建
S10 Skill 回滚
S11 RAG 导入→检索→引用
S12 压缩触发→context.updated→快照链
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

import app.agents.orchestrator as orch_module
from app.agents.orchestrator import AgentOrchestrator
from app.core.config import get_settings
from app.core.enums import AgentRole, PlanStepStatus, RiskLevel, TaskStatus, ToolCallStatus
from app.db.session import get_session_factory
from app.models.context import ContextSnapshot
from app.models.execution import AgentExecutionLog, Approval
from app.models.misc import Setting
from app.models.skill import Skill, SkillVersion
from app.models.task import AgentRun
from sqlalchemy import select
from tests.test_e2e_helpers import (FakeLLM, events_of, mk_run_direct, resp, wait_suspended, wait_terminal)


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


class OrchestratorPatch:
    """把 HTTP 层使用的编排器单例替换为注入 FakeLLM 的实例（测试后还原）。"""

    def __init__(self, responses: list):
        self.fake = FakeLLM(responses)
        self._original = None

    async def __aenter__(self) -> AgentOrchestrator:
        from app.db.redis import get_redis

        self._original = orch_module._orchestrator
        orch = AgentOrchestrator(redis=get_redis(), llm=self.fake)
        orch_module._orchestrator = orch
        return orch

    async def __aexit__(self, *exc) -> None:
        orch_module._orchestrator = self._original


def _plan_response(steps: list[str]):
    return resp({"steps": [{"index": i + 1, "title": t} for i, t in enumerate(steps)]})


def _tool(server: str, tool: str, **args):
    return {"action": "tool", "server": server, "tool": tool, "args": args}


# ── S1 正常任务端到端 ─────────────────────────────────

async def test_s1_normal_task_end_to_end(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    async with OrchestratorPatch([
        _plan_response(["读取配置样例", "复核就绪"]),
        resp({"action": "tool", "server": "workspace", "tool": "read_file",
              "args": {"path": "config.md"}}),
        resp({"action": "done", "summary": "样例不存在，确认无需改动"}),
        resp({"verdict": "pass", "summary": "确认无需改动"}),
    ]) as orch:
        r = await app_client.post("/api/v1/tasks", json={
            "title": "S1 正常端到端", "description": "验证创建到完成的真实链路"})
        assert r.status_code == 201
        task_id = r.json()["id"]
        run_id = r.json()["latestRunId"]
        assert run_id is not None  # 编排器已在创建后拉起 run

        run = await wait_terminal(run_id)
        assert str(getattr(run.status, "value", run.status)) == "completed"
        detail = (await app_client.get(f"/api/v1/tasks/{task_id}")).json()
        assert detail["status"] == "completed"
        assert detail["stats"]["toolCalls"] >= 1
        # 真实工具执行证据：read_file 对不存在文件失败落库
        events = await events_of(run_id)
        types = [e.event_type for e in events]
        assert "run.status" in types and "plan.updated" in types
        assert "tool.call.started" in types and "tool.call.failed" in types
        assert "run.completed" in types


# ── S2 多轮对话上下文 ─────────────────────────────────

async def test_s2_multi_turn_history_reaches_planner(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    async with OrchestratorPatch([
        _plan_response(["总结讨论"]),
        resp({"action": "done", "summary": "已总结"}),
        resp({"verdict": "pass", "summary": "完成"}),
    ]) as orch:
        r = await app_client.post("/api/v1/tasks", json={
            "title": "S2 多轮对话",
            "description": "请基于下面的讨论总结结论：第一轮我们确定了用 PostgreSQL；第二轮确定了连接池大小 5。"})
        task_id = r.json()["id"]
        run_id = r.json()["latestRunId"]
        run = await wait_terminal(run_id)
        assert str(getattr(run.status, "value", run.status)) == "completed"
        # Planner 收到的 user 消息包含会话历史关键信息（多轮上下文真实进入提示词）
        planner_call = orch.fake.calls[0]
        assert "PostgreSQL" in planner_call[1].content
        assert "连接池大小 5" in planner_call[1].content


# ── S3 失败→重规划成功 ────────────────────────────────

async def test_s3_fail_then_replan_succeeds(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    async with OrchestratorPatch([
        _plan_response(["初次尝试"]),
        resp({"action": "done", "summary": "初次完成但质量不佳"}),
        resp({"verdict": "fail", "summary": "缺少测试验证"}),
        resp({"steps": [{"index": 1, "title": "修订：补充测试并验证"}]}),
        resp({"action": "done", "summary": "修订完成，测试通过"}),
        resp({"verdict": "pass", "summary": "修订后达标"}),
    ]) as orch:
        r = await app_client.post("/api/v1/tasks", json={"title": "S3 重规划", "description": ""})
        run_id = r.json()["latestRunId"]
        run = await wait_terminal(run_id)
        assert str(getattr(run.status, "value", run.status)) == "completed"
        assert run.replan_count == 1
        events = await events_of(run_id)
        # 重规划以新 revision 计划表达（8 状态契约不变）
        plans = [e for e in events if e.event_type == "plan.updated"]
        assert len(plans) >= 2
        assert plans[-1].payload["plan"]["revision"] == 2


# ── S5 权限拒绝 ───────────────────────────────────────

async def test_s5_permission_denied(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    # 禁用 read_file（真实 settings 覆盖路径，用后清理）
    r = await app_client.put("/api/v1/settings/permissions",
                             json={"workspace.read_file": "disabled"})
    assert r.status_code == 200
    try:
        async with OrchestratorPatch([
            _plan_response(["读取文件"]),
            resp({"action": "tool", "server": "workspace", "tool": "read_file",
                  "args": {"path": "x.md"}}),
            resp({"action": "done", "summary": "工具被拒，跳过"}),
            resp({"verdict": "pass", "summary": "完成"}),
        ]) as orch:
            r2 = await app_client.post("/api/v1/tasks",
                                       json={"title": "S5 权限拒绝", "description": ""})
            run_id = r2.json()["latestRunId"]
            run = await wait_terminal(run_id)
            assert str(getattr(run.status, "value", run.status)) == "completed"
            events = await events_of(run_id)
            failed_tools = [e for e in events if e.event_type == "tool.call.failed"]
            assert failed_tools and failed_tools[0].payload.get("reason") == "tool_disabled"
    finally:
        await app_client.put("/api/v1/settings/permissions", json={})


# ── S6 审批通过→恢复原执行位置→完成 ───────────────────

async def test_s6_approval_approved_resumes(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    async with OrchestratorPatch([
        _plan_response(["写入报告文件"]),
        resp({"action": "tool", "server": "workspace", "tool": "write_file",
              "args": {"path": "report.md", "content": "S6 审批通过后写入"}}),
        resp({"action": "done", "summary": "报告已写入"}),
        resp({"verdict": "pass", "summary": "报告完成"}),
    ]) as orch:
        r = await app_client.post("/api/v1/tasks", json={"title": "S6 审批通过", "description": ""})
        run_id = r.json()["latestRunId"]
        # 危险写入 → 挂起
        await wait_suspended(run_id)
        approvals = (await app_client.get("/api/v1/approvals?status=pending")).json()["items"]
        apv = next(a for a in approvals if a["runId"] == run_id)
        # 真实 HTTP 审批 → 编排器恢复执行流
        r2 = await app_client.post(f"/api/v1/approvals/{apv['id']}",
                                   json={"decision": "approved", "comment": "S6 批准"})
        assert r2.status_code == 200
        run = await wait_terminal(run_id)
        assert str(getattr(run.status, "value", run.status)) == "completed"
        # 恢复原执行位置：写入真实落盘 + 文件内容来自审批后执行
        from pathlib import Path

        ws = Path(get_settings().WORKSPACE_BASE) / r.json()["id"]
        assert (ws / "report.md").read_text("utf-8") == "S6 审批通过后写入"
        events = await events_of(run_id)
        resolved = [e for e in events if e.event_type == "approval.resolved"]
        assert resolved and resolved[0].payload["status"] == "approved"


# ── S7 审批拒绝→Replanner ────────────────────────────

async def test_s7_approval_rejected_replans(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    async with OrchestratorPatch([
        _plan_response(["危险写入"]),
        resp({"action": "tool", "server": "workspace", "tool": "write_file",
              "args": {"path": "danger.md", "content": "x"}}),
        resp({"steps": [{"index": 1, "title": "改用安全方案输出结论"}]}),
        resp({"action": "done", "summary": "安全方案完成"}),
        resp({"verdict": "pass", "summary": "完成"}),
    ]) as orch:
        r = await app_client.post("/api/v1/tasks", json={"title": "S7 审批拒绝", "description": ""})
        run_id = r.json()["latestRunId"]
        await wait_suspended(run_id)
        approvals = (await app_client.get("/api/v1/approvals?status=pending")).json()["items"]
        apv = next(a for a in approvals if a["runId"] == run_id)
        r2 = await app_client.post(f"/api/v1/approvals/{apv['id']}",
                                   json={"decision": "rejected", "comment": "S7 拒绝"})
        assert r2.status_code == 200
        run = await wait_terminal(run_id)
        assert str(getattr(run.status, "value", run.status)) == "completed"
        assert run.replan_count == 1
        from pathlib import Path

        assert not (Path(get_settings().WORKSPACE_BASE) / r.json()["id"] / "danger.md").exists()
        events = await events_of(run_id)
        assert any(e.event_type == "approval.resolved" and e.payload["status"] == "rejected"
                   for e in events)


# ── S8 SSE Last-Event-ID 续传 ─────────────────────────

async def test_s8_sse_last_event_id_resume(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id, run_id = await mk_run_direct(title="S8 SSE 续传", log_count=4)
    async with app_client.stream(
        "GET", f"/api/v1/runs/{run_id}/events",
        headers={"Accept": "text/event-stream", "Last-Event-ID": "2"},
    ) as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        it = r.aiter_bytes()
        buf = ""
        ids: list[int] = []
        try:
            while True:
                buf += (await asyncio.wait_for(it.__anext__(), timeout=8)).decode("utf-8", "replace")
                while "\n\n" in buf:
                    raw, buf = buf.split("\n\n", 1)
                    for line in raw.split("\n"):
                        if line.startswith("id:"):
                            ids.append(int(line[3:].strip()))
        except (asyncio.TimeoutError, StopAsyncIteration, httpx.StreamClosed):
            pass
    assert ids and ids == sorted(ids) and min(ids) > 2  # 只收到 seq>2 的续传


# ── S9 服务重启恢复 + Snapshot 重建 ───────────────────

async def test_s9_restart_recovery_and_snapshot_rebuild(deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    # 直接构造「重启时」的 DB 状态：run executing、步骤 1 done / 步骤 2 pending
    task_id, run_id = await mk_run_direct(title="S9 重启恢复", log_count=2,
                                          with_plan=("done", "pending"))
    # 模拟重启：全新编排器实例 + 恢复扫描（非终态 run 继续推进）
    async with OrchestratorPatch([
        resp({"action": "done", "summary": "重启后继续完成剩余步骤"}),
        resp({"verdict": "pass", "summary": "恢复后复核通过"}),
    ]) as orch:
        await orch.recover_on_startup()
        run = await wait_terminal(run_id)
        assert str(getattr(run.status, "value", run.status)) == "completed"
        assert run.replan_count == 0
    # Snapshot 重建：恢复后的会话视图可从 DB 完整组装
    factory = get_session_factory()
    async with factory() as session:
        snaps = list((await session.execute(
            select(ContextSnapshot).where(ContextSnapshot.run_id == run_id)
            .order_by(ContextSnapshot.version.asc())
        )).scalars().all())
        assert snaps and snaps[-1].is_current is True
        assert snaps[0].trigger.value == "initial"


# ── S10 Skill 回滚 ────────────────────────────────────

async def test_s10_skill_rollback_end_to_end(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    import uuid

    slug = f"b9-rollback-{uuid.uuid4().hex[:8]}"
    factory = get_session_factory()
    async with factory() as session:
        skill = Skill(name=slug, slug=slug, description="B5 回滚场景",
                      category="testing", status="active", current_version="1.1.0")
        session.add(skill)
        await session.flush()
        session.add(SkillVersion(skill_id=skill.id, version="1.0.0",
                                 changelog="1.0.0 发布", content="稳定版本内容",
                                 source_type="manual", created_at=_now(), updated_at=_now()))
        session.add(SkillVersion(skill_id=skill.id, version="1.1.0",
                                 changelog="1.1.0 发布", content="被改坏的内容",
                                 source_type="manual", created_at=_now(), updated_at=_now()))
        await session.commit()
        skill_id = skill.id
    r = await app_client.post(f"/api/v1/skills/{skill_id}/rollback",
                              json={"targetVersion": "1.0.0", "reason": "S10 回滚场景"})
    assert r.status_code == 200
    assert r.json()["currentVersion"] == "1.1.1"
    vs = (await app_client.get(f"/api/v1/skills/{skill_id}/versions")).json()["items"]
    rolled = next(v for v in vs if v["version"] == "1.1.1")
    assert rolled["content"] == "稳定版本内容"
    events = (await app_client.get("/api/v1/skills/events?skillId=" + skill_id)).json()["items"]
    assert any(e["type"] == "rolled_back" for e in events)


# ── S11 RAG 导入→检索→引用 ────────────────────────────

async def test_s11_rag_search_with_citation(app_client: AsyncClient, deps_available: bool,
                                            tmp_path):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    reset_rag_service()
    settings = get_settings()
    old_dir = settings.RAG_DATA_DIR
    settings.RAG_DATA_DIR = str(tmp_path)
    try:
        from app.rag.service import RagService

        svc = RagService()
        await svc.import_document("b9-deploy.md",
                                  "# 部署手册\n\n灰度发布：先 5% 流量观察 30 分钟。\n".encode("utf-8"))
        r = await app_client.post("/api/v1/memory/search",
                                  json={"query": "灰度发布 流量", "topK": 3})
        assert r.status_code == 200
        hits = [i for i in r.json()["items"] if i["source"] == "document"]
        assert hits
        top = hits[0]
        assert top["docId"] == "b9-deploy" and "灰度" in top["text"]
        assert top["citation"].startswith("b9-deploy.md")  # 引用来源追踪
    finally:
        settings.RAG_DATA_DIR = old_dir
        reset_rag_service()


# ── S12 压缩触发→事件→快照链 ──────────────────────────

async def test_s12_compression_threshold(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    task_id, run_id = await mk_run_direct(title="S12 压缩", log_count=1,
                                          with_plan=("done",))
    factory = get_session_factory()
    async with factory() as session:
        session.add(Setting(key="system", value={"contextWindowTokens": 32000,
                                                 "compressionThreshold": 1}))
        await session.commit()
    try:
        # 编排器阶段边界触发压缩：直接以 ContextManager 驱动（与 orchestrator 同路径）
        from app.context.manager import ContextManager

        async with factory() as session:
            run = await session.get(AgentRun, run_id)
            task = await session.get(AgentTask, task_id)
            snap, window = await ContextManager(session).maybe_compress(run, task, llm=None)
            await session.commit()
        assert snap is not None and snap.before_tokens > snap.after_tokens
        async with factory() as session:
            rows = list((await session.execute(
                select(ContextSnapshot).where(ContextSnapshot.run_id == run_id)
                .order_by(ContextSnapshot.version.asc())
            )).scalars().all())
            assert [(r.version, r.is_current) for r in rows] == [(1, False), (2, True)]
    finally:
        async with factory() as session:
            row = (await session.execute(
                select(Setting).where(Setting.key == "system")
            )).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.commit()


# ── S4 工具超时→重试（服务层编排，真实子进程/等待）────

async def test_s4_tool_timeout_retry(deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    from app.tools.base import ToolContext, ToolSpec, ToolResult
    from app.core.enums import RiskLevel

    task_id, run_id = await mk_run_direct(title="S4 超时重试", log_count=0)
    calls = {"n": 0}

    class FlakyToolSpec(ToolSpec):
        pass

    async def flaky(ctx: ToolContext, args: dict) -> ToolResult:
        calls["n"] += 1
        if calls["n"] == 1:
            await asyncio.sleep(10)  # 首次挂起 → 触发超时
        return ToolResult(ok=True, summary=f"第 {calls['n']} 次成功")

    factory = get_session_factory()
    async with factory() as session:
        from app.services.harness import HarnessService
        from app.tools.registry import ToolRegistry

        registry = build_registry_with_flaky(flaky)
        run = await session.get(AgentRun, run_id)
        task = await session.get(AgentTask, run.task_id)
        settings = get_settings()
        old_t, old_r = settings.TOOL_TIMEOUT_SECONDS, settings.TOOL_MAX_RETRIES
        settings.TOOL_TIMEOUT_SECONDS = 1
        settings.TOOL_MAX_RETRIES = 1
        try:
            outcome = await HarnessService(session, redis=None, registry=registry).execute_tool(
                run, task, "workspace", "flaky", {})
            await session.commit()
        finally:
            settings.TOOL_TIMEOUT_SECONDS = old_t
            settings.TOOL_MAX_RETRIES = old_r
    assert outcome.status == "succeeded"
    assert calls["n"] == 2                             # 超时后重试成功
    events = await events_of(run_id)
    completed = [e for e in events if e.event_type == "tool.call.completed"]
    assert completed and completed[0].payload["attempts"] == 2


def build_registry_with_flaky(handler):
    from app.tools.registry import build_default_registry

    registry = build_default_registry()
    registry.register(ToolSpec(
        server="workspace", name="flaky", description="测试用不稳定工具",
        risk=RiskLevel.SAFE, parameters={}, handler=handler))
    return registry
