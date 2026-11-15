"""Tool Registry：注册、发现、获取；内置默认权限矩阵。

权限矩阵（docs/05 §7：auto / require_approval / disabled）默认值：
- 只读工具（read_file/list_dir/search_code/git_status/git_diff）→ auto
- run_tests（执行工作区代码）→ auto（risk=gated，可在 settings.permissions 覆盖）
- write_file（写入工作区文件）→ require_approval（risk=dangerous，审批闸门）
覆盖方式：settings 表 key='permissions'，值为
{ "workspace.write_file": "require_approval", ... }（Harness 读取）。
"""

from __future__ import annotations

from app.core.enums import RiskLevel
from app.tools.base import ToolSpec

DEFAULT_POLICIES: dict[str, str] = {
    "workspace.read_file": "auto",
    "workspace.list_dir": "auto",
    "workspace.search_code": "auto",
    "workspace.write_file": "require_approval",
    "workspace.run_tests": "auto",
    "git.git_status": "auto",
    "git.git_diff": "auto",
}


class ToolRegistry:
    def __init__(self) -> None:
        self._specs: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.full_name in self._specs:
            raise ValueError(f"工具重复注册: {spec.full_name}")
        if spec.handler is None:
            raise ValueError(f"工具缺少 handler: {spec.full_name}")
        self._specs[spec.full_name] = spec

    def get(self, server: str, name: str) -> ToolSpec:
        spec = self._specs.get(f"{server}.{name}")
        if spec is None:
            raise KeyError(f"工具未注册: {server}.{name}")
        return spec

    def discover(self, server: str | None = None) -> list[ToolSpec]:
        """工具发现：返回全量或按 server 过滤（docs/06 §3.8 语义的内部版）。"""
        specs = sorted(self._specs.values(), key=lambda s: s.full_name)
        if server is None:
            return specs
        return [s for s in specs if s.server == server]

    def default_policy(self, spec: ToolSpec) -> str:
        return DEFAULT_POLICIES.get(spec.full_name, "require_approval")


def build_default_registry() -> ToolRegistry:
    """装配默认工具集（workspace + git）。"""
    from app.tools.git_tools import register_git_tools
    from app.tools.workspace_tools import register_workspace_tools

    registry = ToolRegistry()
    register_workspace_tools(registry)
    register_git_tools(registry)
    return registry
