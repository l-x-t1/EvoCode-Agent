"""Context Manager（B4）：上下文窗口组装 / token 统计 / 阈值压缩 / 恢复重建。

修订要求逐项落地：
- 保存与恢复：任务目标及约束（system 段）、已完成/未完成步骤与工具结果、
  重要代码位置（working 段）、多轮对话历史（history 段）、token 统计
  （segments + used_tokens）、压缩前后 Snapshot 版本链（context_snapshots
  1:N 版本化 + is_current 部分唯一索引，决策 #6）。
- 压缩：used_tokens 超过阈值（settings 表 key='system' 覆盖 > 默认值）时，
  生成新版本快照：历史段由摘要（compressed 段）替代，before/after tokens
  与 compressed_at 记录在案，摘要由 LLM 生成（失败时确定性抽取式兜底，
  不虚构内容）。
- 恢复重建：assemble() 完全从 DB 状态派生（任务/计划/工具调用/消息/快照），
  服务重启后无需额外状态即可重建。
- 零迁移、零前端契约变更（segments 键与前端 ContextSegmentKey 逐字一致）。

token 计量：LLM 调用用 GLM 回传 usage（精确，已入 model_usage）；本模块为
窗口估算，采用确定性启发式（CJK≈1 token/字符，ASCII≈1 token/4 字符），
口径在 docstring 如实声明为近似值。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import ContextTrigger, MemoryLayer
from app.core.logging import get_logger
from app.models.context import ContextSnapshot, MemoryItem
from app.models.conversation import Conversation, Message
from app.models.execution import ToolCall
from app.models.misc import Setting
from app.models.task import AgentRun, AgentTask, Plan, PlanStep

logger = get_logger(__name__)

DEFAULT_WINDOW_TOKENS = 32_000
DEFAULT_COMPRESSION_THRESHOLD = 24_000
HISTORY_RECENT_MESSAGES = 10      # 压缩后仍保留的最近消息数
SUMMARY_MAX_CHARS = 4000

SEGMENT_KEYS = ("system", "skill", "memory", "history", "working", "compressed")


def estimate_tokens(text: str) -> int:
    """确定性估算：CJK 字符 1 token/字，其它 1 token/4 字符（近似口径）。"""
    if not text:
        return 0
    cjk = sum(1 for ch in text if ord(ch) > 0x2E80)
    other = len(text) - cjk
    return max(1, cjk + (other + 3) // 4)


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


@dataclass
class ContextWindow:
    """一次窗口组装的完整产物（供编排器提示词与快照持久化）。"""

    run_id: str
    task_id: str
    segments: list[dict] = field(default_factory=list)   # [{key, tokens}]
    used_tokens: int = 0
    window_tokens: int = DEFAULT_WINDOW_TOKENS
    # 各段的实际内容（仅存在于内存，供提示词；快照只存 segments/token 数）
    system_text: str = ""
    skill_text: str = ""
    memory_text: str = ""
    history_text: str = ""
    working_text: str = ""
    compressed_text: str = ""

    def block(self, limit: int = 4000) -> str:
        """面向提示词的上下文块（按修订要求包含目标/步骤/工具结果/代码位置）。"""
        parts = []
        if self.compressed_text:
            parts.append(f"[已压缩历史摘要]\n{self.compressed_text}")
        if self.system_text:
            parts.append(f"[任务目标与约束]\n{self.system_text}")
        if self.skill_text:
            parts.append(f"[引用 Skill]\n{self.skill_text}")
        if self.working_text:
            parts.append(f"[执行状态（已完成/未完成步骤、工具结果、代码位置）]\n{self.working_text}")
        if self.history_text:
            parts.append(f"[最近对话]\n{self.history_text}")
        text = "\n\n".join(parts)
        return _truncate(text, limit)


class ContextManager:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ 配置
    async def _budget(self) -> tuple[int, int]:
        """(windowTokens, compressionThreshold)：settings 表 key='system' 覆盖 > 默认。"""
        row = (await self.session.execute(
            select(Setting).where(Setting.key == "system")
        )).scalar_one_or_none()
        window, threshold = DEFAULT_WINDOW_TOKENS, DEFAULT_COMPRESSION_THRESHOLD
        if row is not None and isinstance(row.value, dict):
            window = int(row.value.get("contextWindowTokens", window))
            threshold = int(row.value.get("compressionThreshold", threshold))
        return window, threshold

    # ------------------------------------------------------------------ 快照
    async def current_snapshot(self, run_id: str) -> ContextSnapshot | None:
        return (await self.session.execute(
            select(ContextSnapshot)
            .where(ContextSnapshot.run_id == run_id, ContextSnapshot.is_current.is_(True))
            .limit(1)
        )).scalar_one_or_none()

    async def snapshot_chain(self, run_id: str) -> list[ContextSnapshot]:
        rows = list((await self.session.execute(
            select(ContextSnapshot)
            .where(ContextSnapshot.run_id == run_id)
            .order_by(ContextSnapshot.version.asc())
        )).scalars().all())
        for r in rows:
            self.session.expunge(r)
        return rows

    async def _next_version(self, run_id: str) -> int:
        current = (await self.session.execute(
            select(func.max(ContextSnapshot.version)).where(ContextSnapshot.run_id == run_id)
        )).scalar()
        return (current or 0) + 1

    async def _save_snapshot(
        self, run: AgentRun, window: ContextWindow, *,
        trigger: ContextTrigger, summary: str | None = None,
        before_tokens: int | None = None,
    ) -> ContextSnapshot:
        """写入新版本快照；旧当前版本翻为历史（is_current=False）。"""
        previous = await self.current_snapshot(run.id)
        if previous is not None:
            previous.is_current = False
        snap = ContextSnapshot(
            run_id=run.id,
            version=await self._next_version(run.id),
            is_current=True,
            window_tokens=window.window_tokens,
            used_tokens=window.used_tokens,
            segments=list(window.segments),
            trigger=trigger,
            before_tokens=before_tokens,
            after_tokens=window.used_tokens if trigger != ContextTrigger.INITIAL else None,
            summary=summary,
            compressed_at=_now() if trigger != ContextTrigger.INITIAL else None,
        )
        self.session.add(snap)
        await self.session.flush()
        return snap

    # ------------------------------------------------------------------ 组装
    async def assemble(self, run: AgentRun, task: AgentTask) -> ContextWindow:
        """从 DB 状态完整组装窗口（恢复重建的唯一入口）。"""
        window = ContextWindow(run_id=run.id, task_id=task.id)
        window.window_tokens, threshold = await self._budget()

        # ── system：任务目标及约束 ──
        window.system_text = _truncate(
            f"任务：{task.title}\n描述/约束：{task.description or '（无）'}\n"
            f"仓库：{task.repo or '默认工作区'}\n模型偏好：{task.model}",
            2000,
        )

        # ── skill：引用的 Skill ──
        from app.models.skill import Skill

        skill_lines = []
        for sid in (task.skill_ids or [])[:10]:
            skill = await self.session.get(Skill, sid)
            if skill is not None:
                skill_lines.append(f"- {skill.name}({skill.current_version})：{skill.description[:120]}")
        window.skill_text = "\n".join(skill_lines)

        # ── memory：core/episodic 层记忆（MVP：按 score 取前 5）──
        mems = list((await self.session.execute(
            select(MemoryItem)
            .where(MemoryItem.layer.in_([MemoryLayer.CORE, MemoryLayer.EPISODIC]))
            .order_by(MemoryItem.score.desc(), MemoryItem.created_at.desc())
            .limit(5)
        )).scalars().all())
        window.memory_text = "\n".join(f"- {m.content[:160]}" for m in mems)

        # ── working：已完成/未完成步骤 + 工具结果 + 重要代码位置 ──
        plan = (await self.session.execute(
            select(Plan).where(Plan.run_id == run.id).order_by(Plan.revision.desc()).limit(1)
        )).scalar_one_or_none()
        steps = list((await self.session.execute(
            select(PlanStep).where(PlanStep.plan_id == plan.id).order_by(PlanStep.idx.asc())
        )).scalars().all()) if plan else []
        working: list[str] = []
        if steps:
            done = [f"✓ {s.title}" for s in steps
                    if str(getattr(s.status, "value", s.status)) in ("done",)]
            failed = [f"✗ {s.title}" for s in steps
                      if str(getattr(s.status, "value", s.status)) == "failed"]
            pending = [f"□ {s.title}" for s in steps
                       if str(getattr(s.status, "value", s.status)) in ("pending", "running")]
            if done:
                working.append("已完成步骤：" + "；".join(done))
            if failed:
                working.append("失败步骤：" + "；".join(failed))
            if pending:
                working.append("未完成步骤：" + "；".join(pending))
        tool_calls = list((await self.session.execute(
            select(ToolCall).where(ToolCall.run_id == run.id)
            .order_by(ToolCall.created_at.desc(), ToolCall.id.desc()).limit(10)
        )).scalars().all())
        code_locations: list[str] = []
        if tool_calls:
            working.append("最近工具结果：")
            for tc in reversed(tool_calls):
                status = str(getattr(tc.status, "value", tc.status))
                working.append(f"- {tc.server}.{tc.tool}[{status}] {tc.result_summary or ''}"[:200])
                if tc.tool == "write_file" and tc.result:
                    code_locations.append(str((tc.result or {}).get("path") or ""))
        if code_locations:
            working.append("重要代码位置：" + "；".join(dict.fromkeys(code_locations)))
        window.working_text = _truncate("\n".join(working), 4000)

        # ── compressed：当前快照携带的压缩摘要 ──
        snapshot = await self.current_snapshot(run.id)
        if snapshot is not None and snapshot.summary:
            window.compressed_text = snapshot.summary

        # ── history：最近对话（有压缩摘要时仅取摘要之后的消息）──
        conv = (await self.session.execute(
            select(Conversation).where(Conversation.task_id == task.id).limit(1)
        )).scalar_one_or_none()
        if conv is not None:
            stmt = select(Message).where(Message.conversation_id == conv.id)
            if snapshot is not None and snapshot.compressed_at is not None:
                stmt = stmt.where(Message.created_at > snapshot.compressed_at)
            msgs = list((await self.session.execute(
                stmt.order_by(Message.created_at.desc(), Message.id.desc())
                .limit(HISTORY_RECENT_MESSAGES)
            )).scalars().all())
            msgs.reverse()
            if msgs:
                window.history_text = _truncate("\n".join(
                    f"[{getattr(m.role, 'value', m.role)}] {m.content[:200]}" for m in msgs
                ), 4000)

        # ── 汇总 segments 与 token 统计 ──
        window.segments = [
            {"key": key, "tokens": estimate_tokens(getattr(window, f"{key}_text") or "")}
            for key in SEGMENT_KEYS
        ]
        window.used_tokens = sum(s["tokens"] for s in window.segments)
        return window

    # ------------------------------------------------------------------ 压缩
    async def maybe_compress(
        self, run: AgentRun, task: AgentTask, llm=None,
    ) -> tuple[ContextSnapshot | None, ContextWindow]:
        """阈值检查 + 压缩。返回 (新快照或 None, 组装后的窗口)。"""
        window = await self.assemble(run, task)
        _, threshold = await self._budget()
        if window.used_tokens < threshold:
            return None, window

        history_tokens = next((s["tokens"] for s in window.segments if s["key"] == "history"), 0)
        before = window.used_tokens

        summary = await self._summarize(run, task, window, llm)

        # 压缩后窗口：history 段清空并入 compressed 段
        compressed_window = ContextWindow(
            run_id=run.id, task_id=task.id, window_tokens=window.window_tokens,
            system_text=window.system_text, skill_text=window.skill_text,
            memory_text=window.memory_text, working_text=window.working_text,
            compressed_text=summary, history_text="",
        )
        compressed_window.segments = [
            {"key": s["key"], "tokens": 0 if s["key"] == "history"
             else estimate_tokens(getattr(compressed_window, f"{s['key']}_text") or "")}
            for s in window.segments
        ]
        compressed_window.used_tokens = sum(s["tokens"] for s in compressed_window.segments)

        snap = await self._save_snapshot(
            run, compressed_window, trigger=ContextTrigger.THRESHOLD,
            summary=summary, before_tokens=before,
        )
        logger.info("上下文压缩 run=%s before=%d after=%d（历史段 %d tokens）",
                    run.id, before, compressed_window.used_tokens, history_tokens)
        return snap, compressed_window

    async def _summarize(self, run: AgentRun, task: AgentTask, window: ContextWindow, llm) -> str:
        """压缩摘要：优先 LLM 生成；不可用/失败时确定性抽取式兜底（不虚构）。"""
        if llm is not None and getattr(llm, "configured", True):
            try:
                from app.llm.client import LLMMessage

                resp = await llm.chat(
                    [LLMMessage(role="system", content=(
                        "你是 EvoCode Agent 的上下文压缩器。把执行历史压缩为要点摘要，"
                        "保留：任务目标、已完成/未完成工作、关键工具结果与代码位置、"
                        "重要决策。只输出摘要正文，不超过 800 字。")),
                     LLMMessage(role="user", content=(
                         f"任务：{task.title}\n{window.working_text}\n\n最近对话：\n{window.history_text}"))],
                    model=run.model,
                )
                return _truncate(resp.content.strip(), SUMMARY_MAX_CHARS)
            except Exception as exc:  # noqa: BLE001 - 压缩失败走确定性兜底
                logger.warning("LLM 压缩摘要失败，使用抽取式兜底: %s", exc)
        # 抽取式兜底：目标 + 步骤/工具/代码位置要点 + 最近对话首行
        return _truncate(
            "（自动摘要）" + (window.working_text or window.system_text or ""),
            SUMMARY_MAX_CHARS,
        )

    # ------------------------------------------------------------------ 会话视图
    async def session_view(self, run: AgentRun, task: AgentTask) -> dict:
        """前端 ContextSession 形状（id 即 runId，深链 /context/:runId）。"""
        snapshot = await self.current_snapshot(run.id)
        chain = await self.snapshot_chain(run.id)
        window = await self.assemble(run, task)
        window_tokens, _ = await self._budget()
        events = [
            {
                "id": s.id,
                "reason": _truncate(s.summary or "", 200) if s.summary else
                          (f"快照 v{s.version}（{getattr(s.trigger, 'value', s.trigger)}）"),
                "trigger": str(getattr(s.trigger, "value", s.trigger)),
                "beforeTokens": s.before_tokens,
                "afterTokens": s.after_tokens,
                "summaryId": s.id if s.summary else None,
                "createdAt": (s.compressed_at or s.created_at).isoformat()
                if (s.compressed_at or s.created_at) else None,
            }
            for s in chain
        ]
        segments = snapshot.segments if snapshot is not None else window.segments
        updated = snapshot.updated_at if snapshot is not None else run.updated_at
        return {
            "id": run.id,
            "runId": run.id,
            "windowTokens": window_tokens,
            "usedTokens": snapshot.used_tokens if snapshot is not None else window.used_tokens,
            "segments": list(segments or []),
            "compressionEvents": events,
            "updatedAt": updated.isoformat() if updated else None,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)
