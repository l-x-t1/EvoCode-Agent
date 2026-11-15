"""git.* 内部工具（B2 工具层，只读）：git_status / git_diff。

- 只允许只读子命令（core.security.CommandWhitelist 纵深防御）；
- 子进程一律 argv 数组启动（无 shell），经 core.sandbox.LocalProcessProvider；
- 非 git 仓库 → ToolResult(ok=False, error='工作区不是 git 仓库')，不抛异常。
"""

from __future__ import annotations

from app.core.enums import RiskLevel
from app.core.sandbox import LocalProcessProvider
from app.core.security import CommandWhitelist, WorkspaceGuard
from app.tools.base import ToolContext, ToolResult, ToolSpec, validate_args

_WHITELIST = CommandWhitelist()
_ERROR_TAIL_CHARS = 500


def _guard(ctx: ToolContext) -> WorkspaceGuard:
    """构造 Guard（副作用：确保工作区目录存在，供子进程 cwd 使用）。"""
    return WorkspaceGuard(ctx.workspace)


def _is_not_repo(run) -> bool:
    blob = ((run.stderr or "") + (run.stdout or "")).lower()
    return "not a git repository" in blob


def _error_tail(run) -> str:
    text = (run.stderr or "") or (run.stdout or "")
    return text[-_ERROR_TAIL_CHARS:]


# ---------------------------------------------------------------------------
# git.git_status
# ---------------------------------------------------------------------------

_STATUS_SPEC = ToolSpec(
    server="git",
    name="git_status",
    description="git status --porcelain：返回变更文件列表（code/path）与 clean 标志。",
    risk=RiskLevel.SAFE,
    parameters={},
    handler=None,  # 注册前填充
)


async def _git_status(ctx: ToolContext, args: dict) -> ToolResult:
    args = validate_args(_STATUS_SPEC, args)
    _guard(ctx)  # 确保工作区目录存在（git 子进程需要有效 cwd）
    argv = ["git", "status", "--porcelain"]
    _WHITELIST.assert_allowed(argv)

    run = await LocalProcessProvider().run(
        argv,
        cwd=ctx.workspace,
        timeout_seconds=ctx.timeout_seconds,
        output_limit_bytes=ctx.output_limit_bytes,
    )
    if not run.ok and _is_not_repo(run):
        return ToolResult(ok=False, summary="git status 失败", error="工作区不是 git 仓库")
    if not run.ok:
        return ToolResult(
            ok=False,
            summary="git status 失败",
            error=_error_tail(run),
            output={"exitCode": run.exit_code},
        )

    files = []
    for line in run.stdout.splitlines():
        line = line.rstrip("\r")
        if not line.strip():
            continue
        # porcelain 格式：XY + 空格 + 路径
        files.append({"code": line[:2], "path": line[3:]})
    clean = not files
    return ToolResult(
        ok=True,
        summary="工作区干净" if clean else f"{len(files)} 个变更文件",
        output={"files": files, "clean": clean, "exitCode": run.exit_code},
    )


# ---------------------------------------------------------------------------
# git.git_diff
# ---------------------------------------------------------------------------

_DIFF_SPEC = ToolSpec(
    server="git",
    name="git_diff",
    description="git diff（可选 path 限定文件，相对路径经 WorkspaceGuard 解析）。",
    risk=RiskLevel.SAFE,
    parameters={"path": "string"},
    handler=None,
)


async def _git_diff(ctx: ToolContext, args: dict) -> ToolResult:
    args = validate_args(_DIFF_SPEC, args)
    _guard(ctx)  # 确保工作区目录存在
    argv = ["git", "diff"]
    path = args.get("path")
    if path is not None:
        resolved = WorkspaceGuard(ctx.workspace).resolve(ctx.workspace, path)
        argv += ["--", str(resolved)]
    _WHITELIST.assert_allowed(argv)

    run = await LocalProcessProvider().run(
        argv,
        cwd=ctx.workspace,
        timeout_seconds=ctx.timeout_seconds,
        output_limit_bytes=ctx.output_limit_bytes,
    )
    if not run.ok and _is_not_repo(run):
        return ToolResult(ok=False, summary="git diff 失败", error="工作区不是 git 仓库")
    if not run.ok:
        return ToolResult(
            ok=False,
            summary="git diff 失败",
            error=_error_tail(run),
            output={"exitCode": run.exit_code},
        )

    return ToolResult(
        ok=True,
        summary="无改动" if not run.stdout.strip() else f"diff {len(run.stdout)} 字符",
        output={"diff": run.stdout, "truncated": run.truncated, "exitCode": run.exit_code},
    )


_STATUS_SPEC.handler = _git_status
_DIFF_SPEC.handler = _git_diff


def register_git_tools(registry) -> None:
    """注册 2 个 git 只读工具（registry: ToolRegistry）。"""
    registry.register(_STATUS_SPEC)
    registry.register(_DIFF_SPEC)
