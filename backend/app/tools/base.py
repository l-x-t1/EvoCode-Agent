"""Tool 层契约：ToolSpec / ToolResult / ToolContext / 参数校验。

- 所有工具入参必须通过 schema 校验（必填键 + 类型），拒绝未知键
- 工具实现只经 core.security.WorkspaceGuard 访问文件，只经
  core.sandbox.SandboxProvider 启动子进程（无 shell）
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.core.enums import RiskLevel


class ToolArgError(Exception):
    """参数校验失败（工具层）。"""


@dataclass
class ToolContext:
    """单次工具执行的运行时上下文（由 Harness 构造）。"""

    run_id: str
    task_id: str
    workspace: Path            # 已解析的任务工作区绝对路径
    timeout_seconds: int
    output_limit_bytes: int


@dataclass
class ToolResult:
    ok: bool
    summary: str
    output: dict = field(default_factory=dict)
    error: str | None = None


Handler = Callable[[ToolContext, dict[str, Any]], Awaitable[ToolResult]]


@dataclass
class ToolSpec:
    server: str                # 'workspace' | 'git'
    name: str                  # 工具名（同 server 内唯一）
    description: str
    risk: RiskLevel
    parameters: dict[str, str]                       # 参数名 -> 类型标注
    required: tuple[str, ...] = ()
    handler: Handler | None = None

    @property
    def full_name(self) -> str:
        return f"{self.server}.{self.name}"


_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "int": (int,),
    "float": (int, float),
    "boolean": (bool,),
    "array": (list,),
    "object": (dict,),
}


def validate_args(spec: ToolSpec, args: dict[str, Any]) -> dict[str, Any]:
    """schema 校验：未知键拒绝；必填缺失拒绝；类型不符拒绝。返回清洗后的入参。"""
    if not isinstance(args, dict):
        raise ToolArgError("参数必须是对象")
    unknown = set(args) - set(spec.parameters)
    if unknown:
        raise ToolArgError(f"未知参数: {sorted(unknown)}")
    missing = [k for k in spec.required if k not in args]
    if missing:
        raise ToolArgError(f"缺少必填参数: {missing}")
    for key, value in args.items():
        types = _TYPE_CHECKS.get(spec.parameters[key])
        if types is None:
            continue
        if isinstance(value, bool) and bool not in types:
            raise ToolArgError(f"参数 {key} 类型应为 {spec.parameters[key]}")
        if not isinstance(value, types):
            raise ToolArgError(f"参数 {key} 类型应为 {spec.parameters[key]}")
    return args
