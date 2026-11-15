"""四角色提示词（B3）。输出一律为 JSON（解析见 llm.client.extract_json_block）。"""

from __future__ import annotations

import json

from app.tools.registry import ToolRegistry

PLANNER_SYSTEM = """你是 EvoCode Agent 的 Planner。你的唯一职责：把用户的研发任务拆解为可执行计划。
输出要求：只输出一个 JSON 对象，不要输出任何其它文字。格式：
{"steps": [{"index": 1, "title": "步骤标题", "detail": "执行要点", "agent": "executor"}]}
约束：
- steps 数组按执行顺序排列，index 从 1 递增；
- 每个 step 应当是可独立验证的最小工作单元；
- agent 固定为 "executor"（复核由系统 Reviewer 角色完成，不要加入 review 步骤）；
- 最后一个步骤必须包含运行测试验证改动。"""

EXECUTOR_SYSTEM_TEMPLATE = """你是 EvoCode Agent 的 Executor，正在执行计划中的一个步骤。
可用工具（server.name / 描述 / 参数 / 风险）：
{tool_catalog}

决策要求：只输出一个 JSON 对象：
- 需要调用工具时：{"action": "tool", "server": "...", "tool": "...", "args": {{...}}, "reason": "一句话理由"}
- 步骤已完成时：{"action": "done", "summary": "一句话结果摘要"}
约束：
- 每次只调用一个工具；参数必须是工具 schema 允许的字段；
- 只能操作授权工作区内的文件（相对路径）；
- 运行过测试且拿到结果后，若步骤目标已达成就用 action=done；
- 上一次工具调用失败时，应调整参数重试或换用其它工具，不要原样重复同一调用超过 2 次。"""

REVIEWER_SYSTEM = """你是 EvoCode Agent 的 Reviewer。根据计划执行情况与工具/测试结果，判断任务是否达成。
输出要求：只输出一个 JSON 对象：
{"verdict": "pass" | "fail", "summary": "一句话结论", "reasons": ["..."]}
判定标准：
- 关键步骤全部完成且测试通过（或任务本身不涉及代码改动）→ pass；
- 存在未完成步骤、测试未通过、或结果与任务目标不符 → fail。"""

REPLANNER_SYSTEM = """你是 EvoCode Agent 的 Replanner。之前的执行失败了，请给出修订后的新计划。
输出要求：只输出一个 JSON 对象，格式与 Planner 相同：
{"steps": [{"index": 1, "title": "...", "detail": "...", "agent": "executor"}]}
约束：新计划必须明确针对失败原因调整策略；保留已成功部分的后续必要步骤；不要重复同样会失败的方案。"""


def tool_catalog(registry: ToolRegistry) -> str:
    lines = []
    for spec in registry.discover():
        params = ", ".join(
            f"{k}:{v}" + ("*" if k in spec.required else "") for k, v in spec.parameters.items()
        )
        lines.append(f"- {spec.full_name} [{spec.risk.value}] {spec.description} 参数: {params}")
    return "\n".join(lines)


def plan_user_message(task_title: str, description: str, history: list[dict]) -> str:
    parts = [f"任务标题：{task_title}", f"任务描述：\n{description}"]
    if history:
        parts.append("会话历史（最近消息）：")
        for m in history[-6:]:
            parts.append(f"- [{m.get('role')}] {str(m.get('content'))[:300]}")
    return "\n".join(parts)


def executor_user_message(
    step_title: str, step_detail: str | None, recent: list[dict], turn: int, max_turns: int
) -> str:
    parts = [f"当前步骤：{step_title}"]
    if step_detail:
        parts.append(f"步骤要求：{step_detail}")
    parts.append(f"本步骤第 {turn}/{max_turns} 轮决策。")
    if recent:
        parts.append("最近工具/执行记录：")
        for r in recent[-8:]:
            parts.append(f"- {json.dumps(r, ensure_ascii=False)[:300]}")
    return "\n".join(parts)


def reviewer_user_message(
    task_title: str, steps: list[dict], tool_results: list[dict]
) -> str:
    parts = [f"任务：{task_title}", "计划执行情况："]
    for s in steps:
        parts.append(f"- [{s.get('status')}] {s.get('title')}")
    if tool_results:
        parts.append("工具/测试结果：")
        for r in tool_results[-10:]:
            parts.append(f"- {json.dumps(r, ensure_ascii=False)[:300]}")
    return "\n".join(parts)


def replanner_user_message(
    task_title: str, description: str, failed_summary: str, previous_plan: list[dict]
) -> str:
    parts = [f"任务：{task_title}", f"描述：{description}", f"失败原因摘要：{failed_summary}"]
    if previous_plan:
        parts.append("上一个计划的步骤与状态：")
        for s in previous_plan:
            parts.append(f"- [{s.get('status')}] {s.get('title')}")
    parts.append("请输出修订后的新计划 JSON。")
    return "\n".join(parts)
