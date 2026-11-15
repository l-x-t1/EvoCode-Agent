"""B1 种子数据脚本（幂等；不删除、不重置任何已有数据）。

用法（backend 目录）：
    .venv\\Scripts\\python.exe scripts\\seed.py          # 已有数据则跳过
    .venv\\Scripts\\python.exe scripts\\seed.py --force  # 已有数据时仍追加演示数据（不删旧行）

内容：开发用户、3 个 Skill（含版本与 1 个待审候选）、6 个不同状态任务
（completed/executing/waiting_approval/failed(重规划)/queued）、完整 run/
plan/tool_calls/execution_logs（含 code.diff.created / test.finished）/messages/
model_usage（近 7 天分布，供 trends）。
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.enums import (  # noqa: E402
    AgentRole,
    CandidateKind,
    CandidateStatus,
    PlanStepStatus,
    RiskLevel,
    SkillCategory,
    SkillSource,
    SkillStatus,
    TaskStatus,
    ToolCallStatus,
)
from app.core.logging import setup_logging  # noqa: E402
from app.db.session import dispose_engine, get_session_factory, init_engine  # noqa: E402
from app.models.execution import AgentExecutionLog, Approval, ToolCall  # noqa: E402
from app.models.misc import ModelUsage  # noqa: E402
from app.models.skill import Skill, SkillCandidate, SkillVersion  # noqa: E402
from app.models.task import AgentRun, AgentTask, Plan, PlanStep  # noqa: E402
from app.models.user import User  # noqa: E402

UTC = timezone.utc
NOW = datetime.now(UTC)


def days_ago(d: int, h: int = 12) -> datetime:
    return (NOW - timedelta(days=d)).replace(hour=h, minute=0, second=0, microsecond=0)


async def main() -> int:
    settings = get_settings()
    setup_logging(settings)
    init_engine(settings)
    factory = get_session_factory()
    async with factory() as session:
        existing = (await session.execute(
            select(func.count()).select_from(AgentTask)
        )).scalar_one()
        if existing and "--force" not in sys.argv:
            print(f"已存在 {existing} 个任务，默认跳过（--force 追加）。不删除任何数据。")
            await dispose_engine()
            return 0

        # ── 开发用户（D5）─────────────────────────────
        user = (await session.execute(
            select(User).where(User.email == "dev@evocode.local")
        )).scalar_one_or_none()
        if user is None:
            user = User(email="dev@evocode.local", display_name="开发用户",
                        is_active=True, role="owner")
            session.add(user)
            await session.flush()
            print("已创建开发用户 dev@evocode.local")

        # ── Skills ───────────────────────────────────
        skills_data = [
            ("pytest-runner", "测试运行器", "testing", "1.1.0",
             "运行 pytest 并解析结果为结构化 TestResult。"),
            ("code-searcher", "代码检索", "debugging", "1.0.0",
             "在工作区内按关键词/正则检索代码位置。"),
            ("doc-writer", "文档整理", "docs", "0.9.0",
             "整理模块说明文档，保持术语一致。"),
        ]
        skill_ids: dict[str, str] = {}
        for slug, name, cat, ver, desc in skills_data:
            skill = (await session.execute(
                select(Skill).where(Skill.slug == slug)
            )).scalar_one_or_none()
            if skill is None:
                skill = Skill(name=name, slug=slug, description=desc,
                              category=cat, status=SkillStatus.ACTIVE,
                              current_version=ver, usage_count=3,
                              success_rate=0.85, evolutions=0)
                session.add(skill)
                await session.flush()
            skill_ids[slug] = skill.id
            has_ver = (await session.execute(
                select(func.count()).select_from(SkillVersion)
                .where(SkillVersion.skill_id == skill.id)
            )).scalar_one()
            if not has_ver:
                session.add(SkillVersion(
                    skill_id=skill.id, version=ver, changelog=f"{name} 初始版本",
                    content=desc, source_type=SkillSource.MANUAL,
                    eval_score=0.82, created_at=days_ago(9), updated_at=days_ago(9),
                ))
                await session.flush()

        cand = (await session.execute(
            select(SkillCandidate).where(SkillCandidate.status == CandidateStatus.PENDING)
        )).scalar_one_or_none()
        if cand is None:
            session.add(SkillCandidate(
                skill_id=skill_ids["pytest-runner"], kind=CandidateKind.REVISE,
                proposed_version="1.2.0",
                summary="增加对 pytest -k 过滤参数的支持，失败用例保留标准输出片段",
                proposed_content="pytest-runner v1.2.0: 支持 -k 过滤与失败片段保留。",
                evidence_task_ids=[], evaluation={"suite": "pytest-smoke", "before": 0.82,
                                                  "after": 0.91, "sampleSize": 12},
                status=CandidateStatus.PENDING, created_at=days_ago(1),
                updated_at=days_ago(1),
            ))
            await session.flush()

        # ── 任务 × 6（不同状态，覆盖 Dashboard/Workspace 场景）──
        plans_spec = {
            "completed": [
                ("分析仓库结构与依赖", "executor"),
                ("实现功能改动", "executor"),
                ("运行测试验证", "executor"),
                ("复核结果", "reviewer"),
            ],
            "executing": [
                ("阅读现有实现", "executor"),
                ("编写修复补丁", "executor"),
                ("运行回归测试", "executor"),
                ("复核变更", "reviewer"),
            ],
            "waiting_approval": [
                ("定位缺陷根因", "executor"),
                ("应用修复补丁（高危写入）", "executor"),
                ("验证修复", "executor"),
            ],
            "failed": [
                ("初次尝试修复", "executor"),
                ("运行测试", "executor"),
            ],
            "failed_replan": [
                ("修订方案：改用配置注入", "replanner"),
                ("实施修订补丁", "executor"),
            ],
        }
        statuses = ["completed", "executing", "waiting_approval", "failed", "queued", "completed"]
        created_days = [6, 1, 0, 3, 0, 4]
        titles = [
            "修复 settings 接口的时区序列化缺陷",
            "为 Dashboard 增加导出 CSV 能力",
            "重构 plan_steps 状态迁移守卫",
            "修复 SSE 心跳在代理层被缓冲的问题",
            "新增 Skill 候选评估报告模板",
            "优化 tool_calls 列表分页查询",
        ]
        task_ids: list[str] = []
        run_for_task: dict[str, str] = {}
        for i, (status, title) in enumerate(zip(statuses, titles, strict=True)):
            d = created_days[i]
            task = AgentTask(
                user_id=user.id, title=title,
                description=f"{title}：请分析相关代码并给出改动。",
                repo="evocode-backend", model="auto" if i % 2 else "glm-5.3",
                status=TaskStatus(status) if status != "failed_replan" else TaskStatus.FAILED,
                skill_ids=[skill_ids["pytest-runner"]] if i % 2 == 0 else [],
                duration_ms=120_000 if status == "completed" else 45_000,
                tokens_in=5200 + i * 300, tokens_out=3100 + i * 200,
                tool_calls=4 if status == "completed" else 2,
                test_pass_rate=0.95 if status == "completed" else None,
                created_at=days_ago(d, 9), updated_at=days_ago(max(d - 1, 0), 15),
            )
            session.add(task)
            await session.flush()
            task_ids.append(task.id)

            if status == "queued":
                continue
            run_status = TaskStatus(status) if status != "failed_replan" else TaskStatus.FAILED
            run = AgentRun(
                task_id=task.id, status=run_status, model="glm-5.3",
                started_at=days_ago(d, 10),
                finished_at=days_ago(max(d - 1, 0), 15) if status in ("completed", "failed") else None,
                replan_count=1 if status == "failed_replan" else 0,
                duration_ms=120_000 if status == "completed" else 45_000,
                tokens_in=5200 + i * 300, tokens_out=3100 + i * 200,
                tool_calls=4 if status == "completed" else 2,
                created_at=days_ago(d, 10), updated_at=days_ago(max(d - 1, 0), 15),
            )
            session.add(run)
            await session.flush()
            run_for_task[task.id] = run.id
            task.latest_run_id = run.id

            # 会话与消息
            from app.models.conversation import Conversation, Message
            conv = Conversation(task_id=task.id, user_id=user.id, title=title,
                                created_at=days_ago(d, 9), updated_at=days_ago(max(d - 1, 0), 15))
            session.add(conv)
            await session.flush()
            session.add(Message(
                conversation_id=conv.id, run_id=None, role=AgentRole.USER,
                content=f"{title}：请分析相关代码并给出改动。",
                created_at=days_ago(d, 9),
            ))
            session.add(Message(
                conversation_id=conv.id, run_id=run.id, role=AgentRole.PLANNER,
                content="已理解需求，计划分 3~4 步执行，先分析后改动再验证。",
                tokens=180, created_at=days_ago(d, 10),
            ))

            # Plan + steps
            key = "failed" if status == "failed" else (
                "failed_replan" if status == "failed_replan" else status)
            rev1_steps = plans_spec.get(key, [])
            plan = Plan(run_id=run.id, revision=1, created_at=days_ago(d, 10))
            session.add(plan)
            await session.flush()
            for idx, (t, agent) in enumerate(rev1_steps):
                if status == "executing":
                    st = PlanStepStatus.DONE if idx == 0 else (
                        PlanStepStatus.RUNNING if idx == 1 else PlanStepStatus.PENDING)
                elif status == "completed":
                    st = PlanStepStatus.DONE
                elif status == "waiting_approval":
                    st = PlanStepStatus.DONE if idx == 0 else (
                        PlanStepStatus.PENDING if idx == 2 else PlanStepStatus.RUNNING)
                elif status == "failed":
                    st = PlanStepStatus.DONE if idx == 0 else PlanStepStatus.FAILED
                else:
                    st = PlanStepStatus.PENDING
                session.add(PlanStep(
                    plan_id=plan.id, idx=idx, title=t, detail=None, agent=agent,
                    status=st, attempt=1, tool_call_ids=[],
                    created_at=days_ago(d, 10),
                ))
            await session.flush()

            if status == "failed_replan":
                plan2 = Plan(run_id=run.id, revision=2, created_at=days_ago(max(d - 1, 0), 13))
                session.add(plan2)
                await session.flush()
                for idx, (t, agent) in enumerate(plans_spec["failed_replan"]):
                    session.add(PlanStep(
                        plan_id=plan2.id, idx=idx, title=t, agent=agent,
                        status=PlanStepStatus.FAILED if idx == 1 else PlanStepStatus.DONE,
                        attempt=2, tool_call_ids=[], created_at=days_ago(max(d - 1, 0), 13),
                    ))
                run.replan_count = 1

        await session.flush()

        # ── tool_calls / approvals / execution_logs / model_usage ──
        seq_cursor: dict[str, int] = {}

        async def add_log(run_id: str, event_type: str, payload: dict, at: datetime) -> None:
            seq = seq_cursor.get(run_id, 0) + 1
            seq_cursor[run_id] = seq
            session.add(AgentExecutionLog(
                run_id=run_id, seq=seq, event_type=event_type, payload=payload, created_at=at,
            ))

        async def add_tool_call(run_id: str, server: str, tool: str,
                                risk: RiskLevel, status: ToolCallStatus, summary: str,
                                at: datetime, duration_ms: int = 800) -> ToolCall:
            tc = ToolCall(
                run_id=run_id, plan_step_id=None, server=server, tool=tool,
                args={}, result_summary=summary, status=status, risk=risk,
                duration_ms=duration_ms if status != ToolCallStatus.RUNNING else None,
                created_at=at, updated_at=at,
            )
            session.add(tc)
            await session.flush()
            return tc

        t_completed, t_exec, t_apv, t_failed = task_ids[0], task_ids[1], task_ids[2], task_ids[3]
        r_completed = run_for_task[t_completed]

        # completed：完整事件流（含 diff/test）
        await add_log(r_completed, "run.status", {"from": None, "to": "executing"}, days_ago(6, 10))
        await add_log(r_completed, "message.created",
                      {"role": "assistant", "content": "计划已生成"}, days_ago(6, 10))
        tc1 = await add_tool_call(r_completed, "workspace", "read_file", RiskLevel.SAFE,
                                  ToolCallStatus.SUCCEEDED, "读取 app/main.py（42 行）",
                                  days_ago(6, 10))
        await add_log(r_completed, "tool.call.completed",
                      {"toolCallId": tc1.id, "tool": "read_file", "ok": True}, days_ago(6, 10))
        await add_log(r_completed, "code.diff.created", {
            "files": [{
                "path": "app/core/config.py", "additions": 6, "deletions": 1,
                "patch": ("@@ -50,7 +50,8 @@\n-    DB_ECHO: bool = False\n"
                          "+    DB_ECHO: bool = False\n+    DB_POOL_RECYCLE: int = 1800"),
            }],
        }, days_ago(6, 11))
        await add_log(r_completed, "test.finished", {
            "passed": 17, "failed": 0, "skipped": 1, "failures": [],
            "logTail": "17 passed in 0.28s",
        }, days_ago(6, 12))
        await add_log(r_completed, "run.completed", {"status": "completed"}, days_ago(5, 15))

        # executing：运行中
        r_exec = run_for_task[t_exec]
        await add_log(r_exec, "run.status", {"from": None, "to": "executing"}, days_ago(1, 10))
        await add_tool_call(r_exec, "workspace", "search_code", RiskLevel.SAFE,
                            ToolCallStatus.SUCCEEDED, "定位 fetchSummary 调用（2 处）",
                            days_ago(1, 10))
        await add_tool_call(r_exec, "workspace", "write_file", RiskLevel.GATED,
                            ToolCallStatus.RUNNING, "写入导出工具函数（进行中）", days_ago(0, 11))

        # waiting_approval：待审批（pending 审批真实行）
        r_apv = run_for_task[t_apv]
        await add_log(r_apv, "run.status", {"from": "executing", "to": "waiting_approval"},
                      days_ago(0, 11))
        tc_apv = await add_tool_call(r_apv, "workspace", "write_file", RiskLevel.DANGEROUS,
                                     ToolCallStatus.RUNNING,
                                     "覆盖 plan_steps 状态迁移守卫实现", days_ago(0, 11))
        apv = (await session.execute(
            select(Approval).where(Approval.tool_call_id == tc_apv.id,
                                   Approval.status == "pending")
        )).scalar_one_or_none()
        if apv is None:
            session.add(Approval(
                run_id=r_apv, tool_call_id=tc_apv.id, tool="write_file",
                summary="write_file 将覆盖状态迁移守卫实现（危险级别操作）",
                risk=RiskLevel.DANGEROUS, status="pending",
                created_at=days_ago(0, 11), updated_at=days_ago(0, 11),
            ))
        await add_log(r_apv, "approval.requested",
                      {"tool": "write_file", "risk": "dangerous"}, days_ago(0, 11))

        # failed：失败（重规划语义由 failed_replan 任务的 run.replan_count=1 体现）
        r_failed = run_for_task[t_failed]
        await add_log(r_failed, "run.status", {"from": "executing", "to": "failed"}, days_ago(3, 12))
        await add_log(r_failed, "test.finished", {
            "passed": 14, "failed": 3, "skipped": 0,
            "failures": [
                {"name": "tests/test_health.py::test_readyz_semantics",
                 "message": "AssertionError: expected 503 got 200",
                 "snippet": "assert r.status_code == 503"},
            ],
            "logTail": "3 failed, 14 passed in 0.41s",
        }, days_ago(3, 12))
        await add_log(r_failed, "run.failed", {"reason": "测试未通过，进入重规划"}, days_ago(2, 13))

        # model_usage（近 7 天，两条模型，供 tokenTrend）
        for d in range(7):
            for mi, model in enumerate(("glm-5.3", "glm-5.3-flash")):
                session.add(ModelUsage(
                    run_id=None, task_id=None, model=model,
                    prompt_tokens=1500 + 220 * d + mi * 90,
                    completion_tokens=900 + 140 * d + mi * 60,
                    cost=0.12 + 0.02 * d, latency_ms=1200 + 80 * d,
                    created_at=days_ago(d, 8 + d % 4),
                ))

        await session.commit()
        print("种子数据写入完成：tasks=%d runs=%d skills=%d"
              % (len(task_ids), len(run_for_task), len(skill_ids)))
    await dispose_engine()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
