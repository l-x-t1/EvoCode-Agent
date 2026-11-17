"""Agent 编排器（B3）：四角色状态机 + run 生命周期 + 恢复。

状态机（agent_runs.status / agent_tasks.status 同步迁移）：
  planning → executing → reviewing → completed
                ↓            │ fail
        waiting_approval    replanning（replan_count < AGENT_MAX_REPLANS）
                │ approve           │
                └──→ executing ←────┘
  任意非终态 → cancelled（用户取消，协作式退出）
  执行失败 / 重规划超限 → failed

设计说明（诚实披露）：
- 计划文档承诺引入 LangGraph；本实现为**显式四角色状态机**（语义等同），
  原因：审批挂起需要与既有 20 表持久化（agent_runs/plan_steps/approvals/
  agent_execution_logs）深度集成，LangGraph checkpointer 会引入第二套
  状态存储，收益低于风险；符合「不为技术而使用技术」原则。LangGraph
  迁移列为后续可选重构。
- 所有决策来自真实 LLM（app.llm.client），无任何固定模拟返回值；
  单元测试注入 FakeLLM（依赖注入），真实模型冒烟依赖 GLM_API_KEY。
- 事件：run.status / plan.updated / message.created / run.completed /
  run.failed（payload 形状与前端 runStore.applyEvent 对齐）。
- 恢复：服务重启后 recover_on_startup() 重扫非终态 run，从 DB 状态
  （计划/步骤/工具调用）继续推进；waiting_approval 保持挂起等审批。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.events import EventWriter
from app.agents import prompts
from app.core.config import get_settings
from app.core.enums import (
    AgentRole,
    ContextTrigger,
    PlanStepStatus,
    TaskStatus,
    ToolCallStatus,
)
from app.core.exceptions import BizException
from app.core.logging import get_logger
from app.llm.client import BaseLLMClient, LLMMessage, extract_json_block, get_llm_client
from app.models.execution import ToolCall
from app.models.misc import ModelUsage
from app.models.task import AgentRun, AgentTask, Plan, PlanStep
from app.models.conversation import Message
from app.services.harness import HarnessService
from app.tools.registry import build_default_registry

logger = get_logger(__name__)

_LOOP_CAP = 500  # 单次 drive 的最大迭代数（防呆，正常远小于此）


def _resolve_model(task_model: str) -> str:
    settings = get_settings()
    if task_model == "auto":
        return settings.GLM_MODEL
    if task_model == "glm-5.3-flash":
        return settings.GLM_FLASH_MODEL
    return task_model


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _step_dicts(steps: list[PlanStep]) -> list[dict]:
    return [
        {
            "id": s.id,
            "index": s.idx,
            "title": s.title,
            "detail": s.detail,
            "agent": str(s.agent.value) if hasattr(s.agent, "value") else str(s.agent),
            "status": str(s.status.value) if hasattr(s.status, "value") else str(s.status),
            "attempt": s.attempt,
            "toolCallIds": list(s.tool_call_ids or []),
        }
        for s in steps
    ]


def _plan_dict(plan: Plan, steps: list[PlanStep]) -> dict:
    return {"id": plan.id, "runId": plan.run_id, "revision": plan.revision,
            "steps": _step_dicts(steps)}


def _message_dict(m: Message) -> dict:
    return {
        "id": m.id, "runId": m.run_id,
        "role": str(m.role.value) if hasattr(m.role, "value") else str(m.role),
        "content": m.content,
        "createdAt": m.created_at.isoformat() if m.created_at else None,
        "tokens": m.tokens,
    }


class AgentOrchestrator:
    """四角色状态机驱动器。每个 run 一个 asyncio 任务；状态持久化在 20 表内。"""

    def __init__(
        self,
        *,
        session_factory=None,
        redis: Any = None,
        llm: BaseLLMClient | None = None,
        registry=None,
    ) -> None:
        from app.db.session import get_session_factory

        self._session_factory = session_factory or get_session_factory()
        self._redis = redis
        self._llm = llm
        self._registry = registry
        self._tasks: dict[str, asyncio.Task] = {}
        self._malformed: dict[str, int] = {}  # run_id → 连续非法 JSON 次数

    # ------------------------------------------------------------------ 协作件
    @property
    def llm(self) -> BaseLLMClient:
        if self._llm is None:
            self._llm = get_llm_client()
        return self._llm

    @property
    def registry(self):
        if self._registry is None:
            self._registry = build_default_registry()
        return self._registry

    def _harness(self, session: AsyncSession) -> HarnessService:
        return HarnessService(session, redis=self._redis, registry=self.registry)

    def _llm_ready(self) -> bool:
        try:
            return self.llm.configured
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------ 调度
    def schedule_start(self, task_id: str) -> None:
        """创建任务后后台拉起 run（等待路由事务提交后行可见）。"""
        if not self._llm_ready():
            logger.warning("LLM 未配置（GLM_API_KEY 为空），任务 %s 保持 queued，不启动 run", task_id)
            return
        task = asyncio.create_task(self._bootstrap(task_id), name=f"bootstrap:{task_id}")
        task.add_done_callback(self._done_cb)

    def schedule_drive(self, run_id: str) -> None:
        if run_id in self._tasks and not self._tasks[run_id].done():
            return
        if not self._llm_ready():
            logger.warning("LLM 未配置，run %s 暂不驱动（等待 GLM_API_KEY）", run_id)
            return
        t = asyncio.create_task(self._drive_guarded(run_id), name=f"drive:{run_id}")
        self._tasks[run_id] = t
        t.add_done_callback(self._done_cb)

    def schedule_resume(self, approval_id: str, decision: str) -> None:
        """审批决策后后台恢复（等待路由事务提交由 resume_after_approval 内部轮询）。"""
        t = asyncio.create_task(
            self.resume_after_approval(approval_id, decision),
            name=f"resume:{approval_id}",
        )
        t.add_done_callback(self._done_cb)

    def _done_cb(self, task: asyncio.Task) -> None:
        name = task.get_name()
        if name.startswith("drive:"):
            self._tasks.pop(name.split(":", 1)[1], None)
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            logger.error("后台任务 %s 异常退出: %s", name, exc)

    async def _bootstrap(self, task_id: str) -> None:
        """等待路由事务提交后建 run（行不可见时退避重试，最多 5s）。"""
        for _ in range(20):
            async with self._session_factory() as session:
                task = await session.get(AgentTask, task_id)
                if task is not None:
                    if task.latest_run_id:
                        run = await session.get(AgentRun, task.latest_run_id)
                        if run is not None and run.status not in TaskStatus.terminal():
                            self.schedule_drive(run.id)
                            return
                    run, _ = await self._create_run(session, task)
                    await session.commit()
                    self.schedule_drive(run.id)
                    return
            await asyncio.sleep(0.25)
        logger.error("任务 %s 在 5s 内不可见（事务未提交？），放弃启动", task_id)

    async def _create_run(self, session: AsyncSession, task: AgentTask) -> tuple[AgentRun, EventWriter]:
        model = _resolve_model(task.model)
        run = AgentRun(task_id=task.id, status=TaskStatus.PLANNING, model=model,
                       started_at=_now())
        session.add(run)
        await session.flush()
        task.status = TaskStatus.PLANNING
        task.latest_run_id = run.id
        # B4：初始上下文快照（version=1，trigger=initial）
        from app.context.manager import ContextManager

        try:
            await ContextManager(session)._save_snapshot(
                run, await ContextManager(session).assemble(run, task),
                trigger=ContextTrigger.INITIAL)
        except Exception:  # noqa: BLE001 - 快照失败不阻断主流程
            logger.warning("初始上下文快照失败 run=%s", run.id, exc_info=True)
        w = EventWriter(session)
        await w.log(run.id, "run.status", {"status": "planning"})
        return run, w

    async def recover_on_startup(self) -> None:
        """服务重启恢复：重扫非终态 run，按 DB 状态继续推进。"""
        async with self._session_factory() as session:
            rows = (await session.execute(
                select(AgentRun).where(AgentRun.status.not_in(TaskStatus.terminal()))
            )).scalars().all()
        if not rows:
            return
        if not self._llm_ready():
            logger.warning("重启恢复：发现 %d 个非终态 run，但 LLM 未配置，保持现状", len(rows))
            return
        for run in rows:
            if run.status == TaskStatus.WAITING_APPROVAL:
                logger.info("run %s 处于 waiting_approval，等待审批后恢复", run.id)
                continue
            logger.info("重启恢复：继续驱动 run %s（status=%s）", run.id,
                        run.status.value if hasattr(run.status, "value") else run.status)
            self.schedule_drive(run.id)

    # ------------------------------------------------------------------ 审批接缝
    async def resume_after_approval(self, approval_id: str, decision: str) -> None:
        """审批决策后的流程恢复（由 POST /approvals/:id 路由调度）。"""
        for _ in range(15):  # 等路由事务提交（最多 3s）
            async with self._session_factory() as session:
                from app.models.execution import Approval

                apv = await session.get(Approval, approval_id)
                if apv is not None and str(getattr(apv.status, "value", apv.status)) != "pending":
                    break
            await asyncio.sleep(0.2)
        else:
            logger.error("审批 %s 3s 内仍为 pending，放弃恢复", approval_id)
            return

        async with self._session_factory() as session:
            from app.models.execution import Approval

            apv = await session.get(Approval, approval_id)
            if apv is None:
                return
            run = await session.get(AgentRun, apv.run_id)
            task = await session.get(AgentTask, run.task_id) if run else None
            if run is None or task is None:
                return
            w = EventWriter(session)
            if decision == "approved":
                harness = self._harness(session)
                await harness.resume_tool_call(apv.tool_call_id)  # 真实续跑（已批准）
                run.status = TaskStatus.EXECUTING
                task.status = TaskStatus.EXECUTING
                await w.log(run.id, "run.status", {"status": "executing"})
                await w.log(run.id, "approval.resolved", {
                    "approvalId": apv.id, "status": "approved",
                    "toolCallId": apv.tool_call_id,
                })
                await session.commit()
                self.schedule_drive(run.id)
            else:
                tc = await session.get(ToolCall, apv.tool_call_id)
                if tc is not None and str(getattr(tc.status, "value", tc.status)) == "running":
                    tc.status = ToolCallStatus.CANCELLED
                if tc is not None and tc.plan_step_id:
                    step = await session.get(PlanStep, tc.plan_step_id)
                    if step is not None:
                        step.status = PlanStepStatus.FAILED
                        step.attempt += 1
                await w.log(run.id, "approval.resolved", {
                    "approvalId": apv.id, "status": "rejected",
                    "toolCallId": apv.tool_call_id,
                })
                await session.commit()
                await self._enter_replan_or_fail(session, run, task, "人工审批拒绝")
                await session.commit()
                if run.status == TaskStatus.EXECUTING:
                    self.schedule_drive(run.id)

    # ------------------------------------------------------------------ 主循环
    async def _drive_guarded(self, run_id: str) -> None:
        try:
            await self.drive(run_id)
        except BizException as exc:
            logger.error("run %s 业务异常终态化: %s", run_id, exc.message)
            try:
                async with self._session_factory() as session:
                    run = await session.get(AgentRun, run_id)
                    task = await session.get(AgentTask, run.task_id) if run else None
                    if run is not None and run.status not in TaskStatus.terminal():
                        await self._finalize(session, run, task, TaskStatus.FAILED,
                                             error=exc.message)
                        await session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("失败终态写入失败 run=%s", run_id)
        except Exception:
            logger.exception("run %s 驱动异常", run_id)
            try:
                async with self._session_factory() as session:
                    run = await session.get(AgentRun, run_id)
                    task = await session.get(AgentTask, run.task_id) if run else None
                    if run is not None and run.status not in TaskStatus.terminal():
                        await self._finalize(session, run, task, TaskStatus.FAILED,
                                             error="编排器内部错误")
                        await session.commit()
            except Exception:  # noqa: BLE001
                logger.exception("失败终态写入失败 run=%s", run_id)

    async def drive(self, run_id: str) -> None:
        for _ in range(_LOOP_CAP):
            async with self._session_factory() as session:
                run = await session.get(AgentRun, run_id)
                if run is None:
                    return
                task = await session.get(AgentTask, run.task_id)
                if task is None:
                    return
                status = run.status.value if hasattr(run.status, "value") else str(run.status)
                if status in ("completed", "failed", "cancelled") or \
                        task.status.value in ("completed", "failed", "cancelled"):
                    return
                progressed: bool | None
                try:
                    if status == "planning":
                        progressed = await self._phase_plan(session, run, task)
                    elif status == "executing":
                        progressed = await self._phase_execute(session, run, task)
                        if progressed is False:  # 审批挂起，等待人工决策
                            await session.commit()
                            return
                    elif status == "reviewing":
                        progressed = await self._phase_review(session, run, task)
                    else:  # waiting_approval 等意外状态：退出等待外部恢复
                        return
                except BizException as exc:
                    # 业务异常（如 model_unavailable）：以真实原因终态化，不假装完成
                    await self._finalize(session, run, task, TaskStatus.FAILED,
                                         error=exc.message)
                    await session.commit()
                    return
                await session.commit()
                if progressed is False:
                    return
            await asyncio.sleep(0.05)
        logger.error("run %s 达到迭代上限 %d，强制失败", run_id, _LOOP_CAP)
        async with self._session_factory() as session:
            run = await session.get(AgentRun, run_id)
            task = await session.get(AgentTask, run.task_id) if run else None
            if run is not None and run.status not in TaskStatus.terminal():
                await self._finalize(session, run, task, TaskStatus.FAILED,
                                     error="执行步数超过安全上限")
                await session.commit()

    # ------------------------------------------------------------------ LLM 记账
    async def _account(self, session: AsyncSession, run: AgentRun, resp) -> None:
        session.add(ModelUsage(
            run_id=run.id, task_id=run.task_id, model=resp.model,
            prompt_tokens=resp.prompt_tokens, completion_tokens=resp.completion_tokens,
            latency_ms=resp.latency_ms,
        ))
        run.tokens_in += resp.prompt_tokens
        run.tokens_out += resp.completion_tokens

    async def _chat_json(
        self, session: AsyncSession, run: AgentRun, *, system: str, user: str
    ) -> dict:
        resp = await self.llm.chat(
            [LLMMessage(role="system", content=system), LLMMessage(role="user", content=user)],
            model=run.model,
        )
        await self._account(session, run, resp)
        return extract_json_block(resp.content)

    # ------------------------------------------------------------------ planning
    async def _phase_plan(self, session: AsyncSession, run: AgentRun, task: AgentTask) -> bool:
        w = EventWriter(session)
        existing = (await session.execute(
            select(Plan).where(Plan.run_id == run.id).order_by(Plan.revision.desc()).limit(1)
        )).scalar_one_or_none()
        if existing is not None:  # 重启恢复：计划已存在
            steps = list((await session.execute(
                select(PlanStep).where(PlanStep.plan_id == existing.id)
                .order_by(PlanStep.idx.asc())
            )).scalars().all())
            await w.log(run.id, "plan.updated", {"plan": _plan_dict(existing, steps)})
            run.status = TaskStatus.EXECUTING
            task.status = TaskStatus.EXECUTING
            await w.log(run.id, "run.status", {"status": "executing"})
            return True

        # 会话历史：该任务会话（1:1）的用户消息（先于 Run 产生）
        from app.models.conversation import Conversation

        conv = (await session.execute(
            select(Conversation).where(Conversation.task_id == task.id).limit(1)
        )).scalar_one_or_none()
        conv_msgs: list[Message] = []
        if conv is not None:
            conv_msgs = list((await session.execute(
                select(Message)
                .where(Message.conversation_id == conv.id, Message.run_id.is_(None))
                .order_by(Message.created_at.desc())
                .limit(6)
            )).scalars().all())

        data = await self._chat_json(
            session, run,
            system=prompts.PLANNER_SYSTEM,
            user=prompts.plan_user_message(task.title, task.description,
                                           [{"role": "user", "content": m.content} for m in conv_msgs]),
        )
        raw_steps = data.get("steps") or []
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("Planner 未产出有效 steps")
        plan = Plan(run_id=run.id, revision=1)
        session.add(plan)
        await session.flush()
        steps: list[PlanStep] = []
        for i, raw in enumerate(raw_steps, start=1):
            step = PlanStep(
                plan_id=plan.id, idx=i,
                title=str(raw.get("title") or f"步骤 {i}")[:200],
                detail=str(raw.get("detail"))[:2000] if raw.get("detail") else None,
                agent=AgentRole.EXECUTOR,
                status=PlanStepStatus.PENDING, attempt=1, tool_call_ids=[],
            )
            session.add(step)
            steps.append(step)
        await session.flush()
        await w.log(run.id, "plan.updated", {"plan": _plan_dict(plan, steps)})
        conv_id = await self._conversation_id(session, task)
        msg = Message(conversation_id=conv_id, run_id=run.id, role=AgentRole.PLANNER,
                      content=f"已生成执行计划，共 {len(steps)} 步。", tokens=0)
        session.add(msg)
        await session.flush()
        await w.log(run.id, "message.created", {"message": _message_dict(msg)})
        run.status = TaskStatus.EXECUTING
        task.status = TaskStatus.EXECUTING
        await w.log(run.id, "run.status", {"status": "executing"})
        return True

    async def _conversation_id(self, session: AsyncSession, task: AgentTask) -> str:
        from app.models.conversation import Conversation

        conv = (await session.execute(
            select(Conversation).where(Conversation.task_id == task.id).limit(1)
        )).scalar_one_or_none()
        if conv is None:
            conv = Conversation(task_id=task.id, user_id=task.user_id, title=task.title)
            session.add(conv)
            await session.flush()
        return conv.id

    # ------------------------------------------------------------------ executing
    async def _phase_execute(self, session: AsyncSession, run: AgentRun, task: AgentTask) -> bool:
        """执行一个 LLM 决策轮。返回 False = 审批挂起（drive 退出）。"""
        w = EventWriter(session)
        plan = (await session.execute(
            select(Plan).where(Plan.run_id == run.id).order_by(Plan.revision.desc()).limit(1)
        )).scalar_one_or_none()
        if plan is None:
            run.status = TaskStatus.PLANNING
            return True
        steps = list((await session.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id).order_by(PlanStep.idx.asc())
        )).scalars().all())
        step = next((s for s in steps
                     if s.status in (PlanStepStatus.PENDING, PlanStepStatus.RUNNING)), None)
        if step is None:
            run.status = TaskStatus.REVIEWING
            task.status = TaskStatus.REVIEWING
            await w.log(run.id, "run.status", {"status": "reviewing"})
            return True

        if step.status == PlanStepStatus.PENDING:
            step.status = PlanStepStatus.RUNNING
            await w.log(run.id, "plan.updated", {"plan": _plan_dict(plan, steps)})
            await session.flush()

        turns = (await session.execute(
            select(func.count(ToolCall.id)).where(ToolCall.plan_step_id == step.id)
        )).scalar_one()
        if turns >= get_settings().AGENT_STEP_TURNS:
            step.status = PlanStepStatus.FAILED
            await w.log(run.id, "plan.updated", {"plan": _plan_dict(plan, steps)})
            await w.log(run.id, "message.created", {"message": {
                "id": f"sys_{step.id}", "runId": run.id, "role": "system",
                "content": f"步骤「{step.title}」达到单步决策轮数上限，标记失败。",
                "createdAt": _now().isoformat(), "tokens": None,
            }})
            return True

        recent = list((await session.execute(
            select(ToolCall).where(ToolCall.run_id == run.id)
            .order_by(ToolCall.created_at.desc(), ToolCall.id.desc()).limit(8)
        )).scalars().all())
        recent_dicts = [{
            "tool": f"{tc.server}.{tc.tool}",
            "status": str(tc.status.value) if hasattr(tc.status, "value") else str(tc.status),
            "summary": (tc.result_summary or "")[:200],
        } for tc in reversed(recent)]

        # B4：窗口组装 + 阈值压缩（压缩后发 context.updated，前端 Context Center 消费）
        from app.context.manager import ContextManager

        mgr = ContextManager(session)
        context_block = None
        try:
            snap, window = await mgr.maybe_compress(run, task, llm=self.llm)
            if snap is not None:
                await w.log(run.id, "context.updated", {
                    "session": await mgr.session_view(run, task),
                })
            context_block = window.block(limit=4000)
        except Exception:  # noqa: BLE001 - 上下文组装失败不阻断执行
            logger.warning("上下文组装/压缩失败 run=%s", run.id, exc_info=True)

        try:
            decision = await self._chat_json(
                session, run,
                system=prompts.EXECUTOR_SYSTEM_TEMPLATE.format(
                    tool_catalog=prompts.tool_catalog(self.registry)),
                user=prompts.executor_user_message(
                    step.title, step.detail, recent_dicts, turns + 1,
                    get_settings().AGENT_STEP_TURNS,
                    context_block=context_block),
            )
        except ValueError as exc:
            self._malformed[run.id] = self._malformed.get(run.id, 0) + 1
            logger.warning("Executor 决策解析失败（第 %d 次）run=%s: %s",
                           self._malformed[run.id], run.id, exc)
            if self._malformed[run.id] >= 3:
                self._malformed[run.id] = 0
                step.status = PlanStepStatus.FAILED
                await w.log(run.id, "plan.updated", {"plan": _plan_dict(plan, steps)})
            await asyncio.sleep(0.3)
            return True

        self._malformed[run.id] = 0
        action = decision.get("action")
        if action == "tool":
            outcome = await self._harness(session).execute_tool(
                run, task,
                server=str(decision.get("server") or ""),
                tool=str(decision.get("tool") or ""),
                args=decision.get("args") if isinstance(decision.get("args"), dict) else {},
                plan_step_id=step.id,
            )
            if outcome.status == "suspended":
                run.status = TaskStatus.WAITING_APPROVAL
                task.status = TaskStatus.WAITING_APPROVAL
                await w.log(run.id, "run.status", {"status": "waiting_approval"})
                return False
            return True
        if action == "done":
            step.status = PlanStepStatus.DONE
            conv_id = await self._conversation_id(session, task)
            msg = Message(conversation_id=conv_id, run_id=run.id, role=AgentRole.EXECUTOR,
                          content=str(decision.get("summary") or "步骤完成")[:2000])
            session.add(msg)
            await session.flush()
            await w.log(run.id, "message.created", {"message": _message_dict(msg)})
            await w.log(run.id, "plan.updated", {"plan": _plan_dict(plan, steps)})
            return True
        # 未知 action：视为一轮无效决策
        self._malformed[run.id] = self._malformed.get(run.id, 0) + 1
        await asyncio.sleep(0.2)
        return True

    # ------------------------------------------------------------------ reviewing
    async def _phase_review(self, session: AsyncSession, run: AgentRun, task: AgentTask) -> bool:
        w = EventWriter(session)
        plan = (await session.execute(
            select(Plan).where(Plan.run_id == run.id).order_by(Plan.revision.desc()).limit(1)
        )).scalar_one_or_none()
        steps = list((await session.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id).order_by(PlanStep.idx.asc())
        )).scalars().all()) if plan else []
        tool_results = list((await session.execute(
            select(ToolCall).where(ToolCall.run_id == run.id)
            .order_by(ToolCall.created_at.desc(), ToolCall.id.desc()).limit(10)
        )).scalars().all())
        tool_dicts = [{
            "tool": f"{tc.server}.{tc.tool}",
            "status": str(tc.status.value) if hasattr(tc.status, "value") else str(tc.status),
            "summary": (tc.result_summary or "")[:300],
        } for tc in reversed(tool_results)]

        data = await self._chat_json(
            session, run,
            system=prompts.REVIEWER_SYSTEM,
            user=prompts.reviewer_user_message(task.title, _step_dicts(steps), tool_dicts),
        )
        verdict = str(data.get("verdict") or "fail")
        summary = str(data.get("summary") or "")[:2000]
        conv_id = await self._conversation_id(session, task)
        msg = Message(conversation_id=conv_id, run_id=run.id, role=AgentRole.REVIEWER,
                      content=f"复核结论：{verdict}。{summary}")
        session.add(msg)
        await session.flush()
        await w.log(run.id, "message.created", {"message": _message_dict(msg)})

        if verdict == "pass":
            await self._finalize(session, run, task, TaskStatus.COMPLETED, summary=summary)
            return True
        return await self._enter_replan_or_fail(session, run, task, summary or "复核未通过",
                                                reviewer_failed=True)

    async def _enter_replan_or_fail(
        self, session: AsyncSession, run: AgentRun, task: AgentTask,
        reason: str, *, reviewer_failed: bool = False,
    ) -> bool:
        """复核失败/审批拒绝的出口：仍有重规划额度 → 立即执行重规划阶段
        （Replanning 以新 revision 的 plan.updated 事件与 replan_count 表达，
        8 状态契约不变）；额度耗尽 → 终态 failed。"""
        if run.replan_count < get_settings().AGENT_MAX_REPLANS:
            await self._phase_replan(session, run, task)
            return True
        await self._finalize(session, run, task, TaskStatus.FAILED,
                             error=reason, reviewer_failed=reviewer_failed)
        return True

    # ------------------------------------------------------------------ replanning
    async def _phase_replan(self, session: AsyncSession, run: AgentRun, task: AgentTask) -> bool:
        w = EventWriter(session)
        prev = (await session.execute(
            select(Plan).where(Plan.run_id == run.id).order_by(Plan.revision.desc()).limit(1)
        )).scalar_one_or_none()
        prev_steps = list((await session.execute(
            select(PlanStep).where(PlanStep.plan_id == prev.id).order_by(PlanStep.idx.asc())
        )).scalars().all()) if prev else []
        last_review = (await session.execute(
            select(Message).where(Message.run_id == run.id,
                                  Message.role == AgentRole.REVIEWER)
            .order_by(Message.created_at.desc()).limit(1)
        )).scalar_one_or_none()

        data = await self._chat_json(
            session, run,
            system=prompts.REPLANNER_SYSTEM,
            user=prompts.replanner_user_message(
                task.title, task.description,
                last_review.content if last_review else "执行失败",
                _step_dicts(prev_steps)),
        )
        raw_steps = data.get("steps") or []
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("Replanner 未产出有效 steps")

        plan = Plan(run_id=run.id, revision=(prev.revision + 1) if prev else 1)
        session.add(plan)
        await session.flush()
        steps: list[PlanStep] = []
        for i, raw in enumerate(raw_steps, start=1):
            step = PlanStep(
                plan_id=plan.id, idx=i,
                title=str(raw.get("title") or f"步骤 {i}")[:200],
                detail=str(raw.get("detail"))[:2000] if raw.get("detail") else None,
                agent=AgentRole.EXECUTOR,
                status=PlanStepStatus.PENDING, attempt=run.replan_count + 1,
                tool_call_ids=[],
            )
            session.add(step)
            steps.append(step)
        await session.flush()
        run.replan_count += 1
        run.status = TaskStatus.EXECUTING
        task.status = TaskStatus.EXECUTING
        await w.log(run.id, "plan.updated", {"plan": _plan_dict(plan, steps)})
        await w.log(run.id, "run.status", {"status": "executing"})
        return True
    # ------------------------------------------------------------------ 终态
    async def _finalize(
        self, session: AsyncSession, run: AgentRun, task: AgentTask,
        status: TaskStatus, *, summary: str | None = None, error: str | None = None,
        reviewer_failed: bool = False,
    ) -> None:
        w = EventWriter(session)
        finished = _now()
        run.status = status
        run.finished_at = finished
        if run.started_at:
            run.duration_ms = int((finished - run.started_at).total_seconds() * 1000)
        # 聚合回写：tokens 从 model_usage 汇总；tool_calls 计数；test_pass_rate 从最近 run_tests 结果
        usage = (await session.execute(
            select(func.coalesce(func.sum(ModelUsage.prompt_tokens), 0),
                   func.coalesce(func.sum(ModelUsage.completion_tokens), 0))
            .where(ModelUsage.run_id == run.id)
        )).one()
        run.tokens_in, run.tokens_out = int(usage[0]), int(usage[1])
        run.tool_calls = (await session.execute(
            select(func.count(ToolCall.id)).where(ToolCall.run_id == run.id)
        )).scalar_one()
        last_test = (await session.execute(
            select(ToolCall).where(ToolCall.run_id == run.id, ToolCall.tool == "run_tests",
                                   ToolCall.status == ToolCallStatus.SUCCEEDED)
            .order_by(ToolCall.created_at.desc()).limit(1)
        )).scalar_one_or_none()
        if last_test is not None and last_test.result:
            passed = int((last_test.result or {}).get("passed", 0))
            failed = int((last_test.result or {}).get("failed", 0))
            if passed + failed > 0:
                run.test_pass_rate = round(passed / (passed + failed), 4)
        task.status = status
        task.duration_ms = run.duration_ms
        task.tokens_in = run.tokens_in
        task.tokens_out = run.tokens_out
        task.tool_calls = run.tool_calls
        task.test_pass_rate = run.test_pass_rate
        task.updated_at = finished

        status_str = status.value if hasattr(status, "value") else str(status)
        await w.log(run.id, "run.status", {"status": status_str})
        if status == TaskStatus.COMPLETED:
            await w.log(run.id, "run.completed", {"summary": summary or "任务已完成"})
        else:
            await w.log(run.id, "run.failed", {"error": error or summary or "任务失败"})


# ------------------------------------------------------------------ 单例
_orchestrator: AgentOrchestrator | None = None


def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        try:
            from app.db.redis import get_redis

            redis = get_redis()
        except RuntimeError:
            redis = None
        _orchestrator = AgentOrchestrator(redis=redis)
    return _orchestrator
