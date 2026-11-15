"""Tool Harness：工具执行编排（B2）。

职责（docs/05 §7 / docs/06 §4）：
- 权限矩阵：settings 表 key='permissions' 的 JSONB 覆盖 > registry 内置默认值；
  auto（直接执行）/ require_approval（审批闸门）/ disabled（拒绝）。
- 幂等：Redis 键 toolidem:{run_id}:{server}.{tool}:{sha256(args)[:16]}，
  命中且 ToolCall 行存在 → 返回 replayed（行已删则继续新建）；终态后 SET ex=3600。
- 审批闸门：require_approval → 建 pending Approval、log approval.requested、
  返回 suspended；批准后经 resume_tool_call 续跑，拒绝后经 reject_tool_call 取消。
- 重试/超时：attempts = 1 + TOOL_MAX_RETRIES，每次 wait_for(handler, TOOL_TIMEOUT_SECONDS)；
  全部失败 → failed（超时语义为 result_summary='执行超时'）。
- 步数上限：同一 run 内 ToolCall 行数（不含本行）>= TOOL_MAX_STEPS → failed。
- 事件日志：AgentExecutionLog 事件溯源（seq 自增），支撑 SSE 断点续传。

事务约定：本服务不做 commit——请求级事务由 db_session 统一提交；
测试内直接 await session.commit()。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import (
    ApprovalResolvedBy,
    ApprovalStatus,
    RiskLevel,
    ToolCallStatus,
)
from app.core.exceptions import BizException
from app.core.response import ErrorCode
from app.core.security import WorkspaceGuard
from app.core.logging import get_logger
from app.models.execution import AgentExecutionLog, Approval, ToolCall
from app.models.task import AgentRun, AgentTask
from app.models.misc import Setting
from app.tools.base import ToolArgError, ToolContext, ToolResult, ToolSpec, validate_args
from app.tools.registry import ToolRegistry, build_default_registry

logger = get_logger(__name__)

_VALID_POLICIES = ("auto", "require_approval", "disabled")


def _tc_payload(tc: ToolCall) -> dict:
    """ToolCall → 前端 types/api.ts ToolCall 形状（camelCase，SSE 事件内嵌）。"""
    status = tc.status.value if hasattr(tc.status, "value") else str(tc.status)
    risk = tc.risk.value if hasattr(tc.risk, "value") else str(tc.risk)
    return {
        "id": tc.id,
        "runId": tc.run_id,
        "stepId": tc.plan_step_id,
        "server": tc.server,
        "tool": tc.tool,
        "args": tc.args or {},
        "resultSummary": tc.result_summary,
        "status": status,
        "risk": risk,
        "durationMs": tc.duration_ms,
        "createdAt": tc.created_at.isoformat() if tc.created_at else None,
    }


def _apv_payload(apv: Approval) -> dict:
    """Approval → 前端 types/api.ts Approval 形状。"""
    status = apv.status.value if hasattr(apv.status, "value") else str(apv.status)
    risk = apv.risk.value if hasattr(apv.risk, "value") else str(apv.risk)
    return {
        "id": apv.id,
        "runId": apv.run_id,
        "toolCallId": apv.tool_call_id,
        "tool": apv.tool,
        "summary": apv.summary,
        "risk": risk,
        "status": status,
        "createdAt": apv.created_at.isoformat() if apv.created_at else None,
        "resolvedAt": apv.resolved_at.isoformat() if apv.resolved_at else None,
        "resolvedBy": str(apv.resolved_by.value) if getattr(apv.resolved_by, "value", None) else (str(apv.resolved_by) if apv.resolved_by else None),
    }


async def _emit_diff_event(session_add_log, run_id: str, tc: ToolCall, result: ToolResult) -> None:
    """write_file 成功后合成真实 code.diff.created（difflib unified diff，B3 契约）。"""
    import difflib

    out = result.output or {}
    prev = out.get("previousContent") or ""
    new = out.get("content") or ""
    if prev == new:
        return
    diff_lines = list(difflib.unified_diff(
        prev.splitlines(), new.splitlines(),
        fromfile=f"a/{out.get('path')}", tofile=f"b/{out.get('path')}", lineterm="",
    ))
    patch = "\n".join(diff_lines[:2000])
    additions = sum(1 for l in diff_lines if l.startswith("+") and not l.startswith("+++"))
    deletions = sum(1 for l in diff_lines if l.startswith("-") and not l.startswith("---"))
    await session_add_log(run_id, "code.diff.created", {
        "diff": {
            "id": f"diff_{tc.id}",
            "runId": run_id,
            "files": [{"path": out.get("path", ""), "additions": additions,
                        "deletions": deletions, "patch": patch}],
            "createdAt": (tc.created_at.isoformat() if tc.created_at else None),
        },
        "toolCallId": tc.id,
    })


async def _emit_test_event(session_add_log, run_id: str, tc: ToolCall, result: ToolResult) -> None:
    """run_tests 成功后合成 test.finished（前端 TestResult 形状）。"""
    out = result.output or {}
    await session_add_log(run_id, "test.finished", {
        "result": {
            "id": f"test_{tc.id}",
            "runId": run_id,
            "passed": int(out.get("passed", 0)),
            "failed": int(out.get("failed", 0)),
            "skipped": int(out.get("skipped", 0)),
            "failures": [],
            "logTail": (out.get("logTail") or "")[-4000:],
            "createdAt": (tc.created_at.isoformat() if tc.created_at else None),
        },
        "toolCallId": tc.id,
    })


@dataclass
class ToolExecutionOutcome:
    """单次工具调用的执行结果（供 API 层/Agent 循环消费）。"""

    status: str  # succeeded | failed | suspended | rejected | cancelled | replayed
    tool_call_id: str
    approval_id: str | None = None
    result: dict = field(default_factory=dict)
    summary: str = ""


class HarnessService:
    """工具执行编排服务（单进程 MVP；跨进程幂等依赖 Redis）。"""

    def __init__(self, session: AsyncSession, redis: Any = None, registry: ToolRegistry | None = None) -> None:
        self.session = session
        self.redis = redis
        self._registry = registry

    # ------------------------------------------------------------------ registry
    @property
    def registry(self) -> ToolRegistry:
        """默认注册表惰性装配；workspace/git 工具模块缺失时退化为空表（如实告警）。"""
        if self._registry is None:
            try:
                self._registry = build_default_registry()
            except Exception as exc:  # noqa: BLE001 - 工具模块未落地时降级，不崩
                logger.warning("默认工具注册表装配失败，降级为空注册表: %s", exc)
                self._registry = ToolRegistry()
        return self._registry

    # ------------------------------------------------------------------ policy
    async def _permission_overrides(self) -> dict[str, str]:
        """读取 settings 表 key='permissions' 的覆盖矩阵；无行返回空 dict。"""
        row = (await self.session.execute(select(Setting).where(Setting.key == "permissions"))).scalar_one_or_none()
        if row is None or not isinstance(row.value, dict):
            return {}
        return {k: v for k, v in row.value.items() if isinstance(v, str)}

    async def _policy(self, server: str, name: str, spec: ToolSpec) -> str:
        """权限判定：settings 覆盖 > registry 默认矩阵（docs/05 §7）。"""
        override = await self._permission_overrides()
        policy = override.get(f"{server}.{name}")
        if policy in _VALID_POLICIES:
            return policy
        return self.registry.default_policy(spec)

    # ------------------------------------------------------------------ logs
    async def _next_seq(self, run_id: str) -> int:
        """下一事件序号：SELECT max(seq)+1。

        并发限制：单进程 MVP 下够用；多进程并发写同一 run 存在竞态，
        需 DB 序列或行锁升级（docstring 诚实声明）。
        """
        current = (await self.session.execute(select(func.max(AgentExecutionLog.seq)).where(AgentExecutionLog.run_id == run_id))).scalar()
        return (current or 0) + 1

    async def _add_log(self, run_id: str, event_type: str, payload: dict) -> AgentExecutionLog:
        """写一行事件溯源日志（seq 自增；不 commit，随请求事务提交）。"""
        row = AgentExecutionLog(run_id=run_id, seq=await self._next_seq(run_id), event_type=event_type, payload=payload)
        self.session.add(row)
        await self.session.flush()
        return row

    # ------------------------------------------------------------------ ctx
    def _build_ctx(self, run: AgentRun, task: AgentTask) -> ToolContext:
        """构造 ToolContext：工作区 = WORKSPACE_BASE/<task_id>/。

        Guard 以 WORKSPACE_BASE 为基目录，task_root(task.id) 创建并校验任务目录；
        路径类入参由各工具 handler 经 WorkspaceGuard.resolve 在工具层拒绝
        （Harness 只负责授权工作区的创建与注入）。
        """
        settings = get_settings()
        guard = WorkspaceGuard(Path(settings.WORKSPACE_BASE))
        task_root = guard.task_root(task.id)
        return ToolContext(
            run_id=run.id,
            task_id=task.id,
            workspace=task_root,
            timeout_seconds=settings.TOOL_TIMEOUT_SECONDS,
            output_limit_bytes=settings.TOOL_OUTPUT_LIMIT_BYTES,
        )

    # ------------------------------------------------------------------ idempotency
    @staticmethod
    def _idem_key(run: AgentRun, server: str, tool: str, args: dict) -> str:
        raw = json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"toolidem:{run.id}:{server}.{tool}:{digest}"

    async def _idem_lookup(self, run: AgentRun, server: str, tool: str, args: dict) -> ToolExecutionOutcome | None:
        """幂等命中：返回 replayed outcome；未命中/行已删/Redis 故障返回 None。"""
        if self.redis is None:
            return None
        try:
            cached_id = await self.redis.get(self._idem_key(run, server, tool, args))
        except Exception as exc:  # noqa: BLE001 - Redis 故障不阻断执行
            logger.warning("幂等键读取失败（降级为直接执行）: %s", exc)
            return None
        if not cached_id:
            return None
        row = await self.session.get(ToolCall, cached_id)
        if row is None:  # 行已删（如级联清理）→ 继续新建
            return None
        return ToolExecutionOutcome(
            status="replayed",
            tool_call_id=row.id,
            result={
                "toolCallStatus": str(row.status.value if hasattr(row.status, "value") else row.status),
                "resultSummary": row.result_summary or "",
                "result": row.result or {},
            },
            summary=row.result_summary or "",
        )

    async def _idem_store(self, run: AgentRun, server: str, tool: str, args: dict, tool_call_id: str) -> None:
        """终态后写幂等键（ex=3600）；Redis 故障仅告警，不影响结果。"""
        if self.redis is None:
            return
        try:
            await self.redis.set(self._idem_key(run, server, tool, args), tool_call_id, ex=3600)
        except Exception as exc:  # noqa: BLE001
            logger.warning("幂等键写入失败: %s", exc)

    # ------------------------------------------------------------------ execute
    async def execute_tool(
        self,
        run: AgentRun,
        task: AgentTask,
        server: str,
        tool: str,
        args: dict,
        plan_step_id: str | None = None,
    ) -> ToolExecutionOutcome:
        """执行一次工具调用：权限 → 幂等 → 审批闸门 → 实际执行。"""
        # a) 工具发现 + 权限判定
        try:
            spec = self.registry.get(server, tool)
        except KeyError:
            return await self._reject_unregistered(run, server, tool, args, plan_step_id)

        policy = await self._policy(server, tool, spec)

        if policy == "disabled":
            return await self._reject_disabled(run, server, tool, spec, args, plan_step_id)

        # b) Redis 幂等
        replay = await self._idem_lookup(run, server, tool, args)
        if replay is not None:
            return replay

        # c) 建 ToolCall(running) + tool.call.started
        tc = ToolCall(
            run_id=run.id,
            plan_step_id=plan_step_id,
            server=server,
            tool=tool,
            args=args,
            status=ToolCallStatus.RUNNING,
            risk=spec.risk,
        )
        self.session.add(tc)
        await self.session.flush()
        await self._add_log(run.id, "tool.call.started", {
            "toolCallId": tc.id,
            "tool": spec.full_name,
            "args": args,
            "toolCall": _tc_payload(tc),
        })

        # d) 审批闸门：不执行，挂起等待人工决策
        if policy == "require_approval":
            summary = f"{spec.description}：{json.dumps(args, ensure_ascii=False, default=str)[:200]}"
            apv = Approval(
                run_id=run.id,
                tool_call_id=tc.id,
                tool=spec.full_name,
                summary=summary,
                risk=spec.risk,
                status=ApprovalStatus.PENDING,
            )
            self.session.add(apv)
            await self.session.flush()
            await self._add_log(run.id, "approval.requested", {
                "toolCallId": tc.id,
                "approvalId": apv.id,
                "tool": spec.full_name,
                "risk": str(spec.risk.value if hasattr(spec.risk, "value") else spec.risk),
                "summary": summary,
                "status": "pending",
                "approval": _apv_payload(apv),
            })
            return ToolExecutionOutcome(
                status="suspended",
                tool_call_id=tc.id,
                approval_id=apv.id,
                result={"approvalId": apv.id},
                summary=summary,
            )

        # e) 直接执行（auto）
        ctx = self._build_ctx(run, task)
        outcome = await self._run(run, spec, ctx, args, tc)
        if outcome.status in ("succeeded", "failed"):
            await self._idem_store(run, server, tool, args, tc.id)
        return outcome

    async def _reject_unregistered(
        self, run: AgentRun, server: str, tool: str, args: dict, plan_step_id: str | None
    ) -> ToolExecutionOutcome:
        """工具未注册：如实记失败 ToolCall + 事件日志，返回 rejected。"""
        tc = ToolCall(
            run_id=run.id,
            plan_step_id=plan_step_id,
            server=server,
            tool=tool,
            args=args,
            status=ToolCallStatus.FAILED,
            risk=RiskLevel.SAFE,
            result_summary=f"权限拒绝：工具未注册 {server}.{tool}",
        )
        self.session.add(tc)
        await self.session.flush()
        await self._add_log(run.id, "tool.call.started", {"toolCallId": tc.id, "tool": f"{server}.{tool}", "args": args})
        await self._add_log(run.id, "tool.call.failed", {
            "toolCallId": tc.id,
            "tool": f"{server}.{tool}",
            "reason": "tool_not_registered",
            "error": f"工具未注册: {server}.{tool}",
        })
        return ToolExecutionOutcome(status="rejected", tool_call_id=tc.id, summary=tc.result_summary or "")

    async def _reject_disabled(
        self, run: AgentRun, server: str, tool: str, spec: ToolSpec, args: dict, plan_step_id: str | None
    ) -> ToolExecutionOutcome:
        """工具已禁用：不执行，直接记失败。"""
        tc = ToolCall(
            run_id=run.id,
            plan_step_id=plan_step_id,
            server=server,
            tool=tool,
            args=args,
            status=ToolCallStatus.FAILED,
            risk=spec.risk,
            result_summary="权限拒绝：工具已禁用",
        )
        self.session.add(tc)
        await self.session.flush()
        await self._add_log(run.id, "tool.call.started", {"toolCallId": tc.id, "tool": spec.full_name, "args": args})
        await self._add_log(run.id, "tool.call.failed", {
            "toolCallId": tc.id,
            "tool": spec.full_name,
            "reason": "tool_disabled",
        })
        return ToolExecutionOutcome(status="rejected", tool_call_id=tc.id, summary="权限拒绝：工具已禁用")

    # ------------------------------------------------------------------ run
    async def _run(
        self,
        run: AgentRun,
        spec: ToolSpec,
        ctx: ToolContext,
        args: dict,
        tc: ToolCall,
        extra_log: dict | None = None,
    ) -> ToolExecutionOutcome:
        """实际执行（含参数校验 / 步数上限 / 超时与重试），写终态与日志。"""
        extra = dict(extra_log or {})

        # 参数校验失败：不重试
        try:
            args = validate_args(spec, args)
        except ToolArgError as exc:
            return await self._fail_no_retry(tc, run, spec, f"参数校验失败：{exc}", reason="invalid_args", error=str(exc), extra=extra)

        # 步数上限：本 run 已有 ToolCall 行数（不含本行）>= TOOL_MAX_STEPS
        settings = get_settings()
        if settings.TOOL_MAX_STEPS >= 0:
            existing = (
                await self.session.execute(
                    select(func.count(ToolCall.id)).where(ToolCall.run_id == run.id, ToolCall.id != tc.id)
                )
            ).scalar_one()
            if existing >= settings.TOOL_MAX_STEPS:
                return await self._fail_no_retry(
                    tc, run, spec, "已达最大执行步数限制", reason="max_steps_exceeded", error=None, extra=extra
                )

        attempts = 1 + max(0, settings.TOOL_MAX_RETRIES)
        start = time.perf_counter()
        last_error: str | None = None
        executed_attempts = 0

        for attempt in range(1, attempts + 1):
            executed_attempts = attempt
            try:
                result: ToolResult = await asyncio.wait_for(spec.handler(ctx, args), timeout=ctx.timeout_seconds)
            except (asyncio.TimeoutError, TimeoutError):
                last_error = "执行超时"
            except Exception as exc:  # noqa: BLE001 - 工具层任意异常均计入重试
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if result.ok:
                    duration_ms = int((time.perf_counter() - start) * 1000)
                    tc.status = ToolCallStatus.SUCCEEDED
                    tc.result_summary = result.summary
                    tc.result = result.output
                    tc.duration_ms = duration_ms
                    await self._add_log(run.id, "tool.call.completed", {
                        "toolCallId": tc.id,
                        "tool": spec.full_name,
                        "summary": result.summary,
                        "attempts": attempt,
                        "durationMs": duration_ms,
                        "toolCall": _tc_payload(tc),
                        **extra,
                    })
                    # B3：语义事件（前端 runStore 消费 code.diff.created / test.finished）
                    full_name = f"{spec.server}.{spec.name}"
                    if full_name == "workspace.write_file":
                        await _emit_diff_event(self._add_log, run.id, tc, result)
                    elif full_name == "workspace.run_tests":
                        await _emit_test_event(self._add_log, run.id, tc, result)
                    return ToolExecutionOutcome(
                        status="succeeded",
                        tool_call_id=tc.id,
                        result=result.output,
                        summary=result.summary,
                    )
                last_error = result.error or f"工具返回失败: {result.summary}"
            # 失败重试间隔（非最后一轮才需要 sleep）
            if attempt < attempts:
                await asyncio.sleep(0.1 * attempt)

        duration_ms = int((time.perf_counter() - start) * 1000)
        tc.status = ToolCallStatus.FAILED
        tc.result_summary = last_error or "执行失败"
        tc.duration_ms = duration_ms
        await self._add_log(run.id, "tool.call.failed", {
            "toolCallId": tc.id,
            "tool": spec.full_name,
            "attempts": executed_attempts,
            "error": tc.result_summary,
            "durationMs": duration_ms,
            "toolCall": _tc_payload(tc),
            **extra,
        })
        return ToolExecutionOutcome(status="failed", tool_call_id=tc.id, summary=tc.result_summary or "")

    async def _fail_no_retry(
        self,
        tc: ToolCall,
        run: AgentRun,
        spec: ToolSpec,
        summary: str,
        *,
        reason: str,
        error: str | None,
        extra: dict,
    ) -> ToolExecutionOutcome:
        """免重试失败（参数校验/步数上限）：写终态 + 日志。"""
        tc.status = ToolCallStatus.FAILED
        tc.result_summary = summary
        await self._add_log(run.id, "tool.call.failed", {
            "toolCallId": tc.id,
            "tool": spec.full_name,
            "reason": reason,
            "error": error,
            **extra,
        })
        return ToolExecutionOutcome(status="failed", tool_call_id=tc.id, summary=summary)

    # ------------------------------------------------------------------ resume / reject
    async def _load_tool_call(self, tool_call_id: str) -> ToolCall:
        tc = await self.session.get(ToolCall, tool_call_id)
        if tc is None:
            raise BizException(ErrorCode.NOT_FOUND, "工具调用不存在", status_code=404)
        return tc

    async def _latest_approval(self, tool_call_id: str) -> Approval | None:
        row = (
            await self.session.execute(
                select(Approval)
                .where(Approval.tool_call_id == tool_call_id)
                .order_by(Approval.created_at.desc(), Approval.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

    async def _load_run_task(self, run_id: str) -> tuple[AgentRun, AgentTask]:
        run = await self.session.get(AgentRun, run_id)
        if run is None:
            raise BizException(ErrorCode.NOT_FOUND, "运行不存在", status_code=404)
        task = await self.session.get(AgentTask, run.task_id)
        if task is None:
            raise BizException(ErrorCode.NOT_FOUND, "任务不存在", status_code=404)
        return run, task

    async def resume_tool_call(self, tool_call_id: str) -> ToolExecutionOutcome:
        """审批通过后续跑挂起的工具调用（ctx 重建）。"""
        tc = await self._load_tool_call(tool_call_id)
        approval = await self._latest_approval(tool_call_id)
        if approval is None:
            raise BizException(ErrorCode.NOT_FOUND, "该工具调用无审批记录", status_code=404)
        if approval.status != ApprovalStatus.APPROVED:
            raise BizException(
                ErrorCode.CONFLICT,
                "审批未通过，无法继续执行",
                status_code=409,
                details={"currentStatus": str(approval.status.value if hasattr(approval.status, "value") else approval.status)},
            )
        if tc.status != ToolCallStatus.RUNNING:
            raise BizException(
                ErrorCode.CONFLICT,
                "工具调用不在挂起状态，无法继续执行",
                status_code=409,
                details={"currentStatus": str(tc.status.value if hasattr(tc.status, "value") else tc.status)},
            )
        run, task = await self._load_run_task(tc.run_id)
        spec = self.registry.get(tc.server, tc.tool)
        ctx = self._build_ctx(run, task)
        return await self._run(run, spec, ctx, tc.args, tc, extra_log={"approvalResolved": True})

    async def reject_tool_call(self, tool_call_id: str) -> ToolExecutionOutcome:
        """拒绝审批：Approval → rejected，ToolCall → cancelled（仅 pending 可决）。"""
        tc = await self._load_tool_call(tool_call_id)
        approval = await self._latest_approval(tool_call_id)
        if approval is None or approval.status != ApprovalStatus.PENDING:
            current = "无审批记录" if approval is None else str(
                approval.status.value if hasattr(approval.status, "value") else approval.status
            )
            raise BizException(ErrorCode.CONFLICT, "无待审批记录可拒绝", status_code=409, details={"currentStatus": current})
        approval.status = ApprovalStatus.REJECTED
        approval.resolved_by = ApprovalResolvedBy.USER
        approval.resolved_at = datetime.now(timezone.utc)
        tc.status = ToolCallStatus.CANCELLED
        await self._add_log(run_id=tc.run_id, event_type="approval.resolved", payload={
            "toolCallId": tc.id,
            "approvalId": approval.id,
            "decision": "rejected",
            "status": "rejected",
            "resolvedBy": "user",
            "approval": _apv_payload(approval),
        })
        await self._add_log(run_id=tc.run_id, event_type="tool.call.cancelled", payload={
            "toolCallId": tc.id,
            "tool": approval.tool,
            "toolCall": _tc_payload(tc),
        })
        return ToolExecutionOutcome(status="cancelled", tool_call_id=tc.id, approval_id=approval.id, summary="已拒绝")
