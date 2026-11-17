"""workspace.* 内部工具（B2 工具层）：read_file / list_dir / search_code /
write_file / run_tests。

硬性约定：
- 所有路径入参一律经 core.security.WorkspaceGuard.resolve 解析
  （拒绝绝对路径 / 盘符 / UNC / ``..`` 逃逸），工具层不做自己的路径拼接；
- 子进程一律 argv 数组启动（无 shell），经 core.sandbox.LocalProcessProvider
  执行，附加 CommandWhitelist 前缀白名单（纵深防御）；
- 参数一律先过 base.validate_args（未知键 / 缺必填 / 类型错 → ToolArgError）。
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from app.core.enums import RiskLevel
from app.core.sandbox import LocalProcessProvider
from app.core.security import CommandWhitelist, WorkspaceGuard
from app.tools.base import (
    ToolArgError,
    ToolContext,
    ToolResult,
    ToolSpec,
    validate_args,
)

# search_code 跳过的目录名（大小写不敏感）
_SKIP_DIRS = {".git", "node_modules", "__pycache__"}
# search_code 跳过 >1MB 的文件
_MAX_SEARCH_FILE_BYTES = 1_000_000
# search_code 命中文本截断长度
_MAX_HIT_TEXT_CHARS = 200
# list_dir 递归上限
_MAX_LIST_ENTRIES = 2000
# 命令白名单（模块级复用）
_WHITELIST = CommandWhitelist()


def _guard(ctx: ToolContext) -> WorkspaceGuard:
    """每个任务工作区一个 Guard（构造时确保 base 目录存在）。"""
    return WorkspaceGuard(ctx.workspace)


def _rel_name(p: Path, root: Path) -> str:
    """工作区内相对路径（统一 POSIX 分隔符，便于跨端展示）。"""
    return Path(os.path.relpath(p, root)).as_posix()


# ---------------------------------------------------------------------------
# workspace.read_file
# ---------------------------------------------------------------------------

_READ_SPEC = ToolSpec(
    server="workspace",
    name="read_file",
    description="读取工作区内文本文件；offset/limit 控制行窗口，"
    "内容按 ctx.output_limit_bytes 截断并标记 truncated。",
    risk=RiskLevel.SAFE,
    parameters={"path": "string", "offset": "int", "limit": "int"},
    required=("path",),
    handler=None,  # 注册前填充
)


async def _read_file(ctx: ToolContext, args: dict) -> ToolResult:
    args = validate_args(_READ_SPEC, args)
    path = args["path"]
    offset = args.get("offset", 0)
    limit = args.get("limit", 400)
    if offset < 0:
        raise ToolArgError("offset 不能为负")
    if limit <= 0:
        raise ToolArgError("limit 必须为正整数")

    resolved = _guard(ctx).resolve(ctx.workspace, path)
    if not resolved.is_file():
        return ToolResult(ok=False, summary=f"文件不存在: {path}", error="文件不存在")

    raw = resolved.read_bytes()
    truncated = len(raw) > ctx.output_limit_bytes
    raw = raw[: ctx.output_limit_bytes]
    text = raw.decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    window = all_lines[offset : offset + limit]
    content = "\n".join(window)
    return ToolResult(
        ok=True,
        summary=f"读取 {path}：返回 {len(window)} 行 / 共 {len(all_lines)} 行",
        output={
            "path": path,
            "content": content,
            "totalLines": len(all_lines),
            "returnedLines": len(window),
            "offset": offset,
            "bytes": len(raw),
            "truncated": truncated,
        },
    )


# ---------------------------------------------------------------------------
# workspace.list_dir
# ---------------------------------------------------------------------------

_LIST_SPEC = ToolSpec(
    server="workspace",
    name="list_dir",
    description="列出工作区目录；recursive 时递归枚举，最多 2000 项。",
    risk=RiskLevel.SAFE,
    parameters={"path": "string", "recursive": "boolean"},
    handler=None,
)


async def _list_dir(ctx: ToolContext, args: dict) -> ToolResult:
    args = validate_args(_LIST_SPEC, args)
    path = args.get("path", ".")
    recursive = args.get("recursive", False)

    root = _guard(ctx).resolve(ctx.workspace, path)
    if not root.exists():
        return ToolResult(ok=False, summary=f"目录不存在: {path}", error="目录不存在")
    if not root.is_dir():
        return ToolResult(ok=False, summary=f"不是目录: {path}", error="不是目录")

    entries: list[dict] = []
    truncated = False

    def _add(p: Path) -> bool:
        """追加一条 entry；超过上限返回 False 表示截断。"""
        if len(entries) >= _MAX_LIST_ENTRIES:
            return False
        if p.is_dir():
            entries.append({"name": _rel_name(p, root), "type": "dir", "size": 0})
        else:
            entries.append(
                {"name": _rel_name(p, root), "type": "file", "size": p.stat().st_size}
            )
        return True

    if recursive:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in dirnames + sorted(filenames):
                if not _add(Path(dirpath) / name):
                    truncated = True
                    break
            if truncated:
                break
    else:
        for child in sorted(root.iterdir()):
            if not _add(child):
                truncated = True
                break

    return ToolResult(
        ok=True,
        summary=f"列出 {path}：{len(entries)} 项" + ("（已截断）" if truncated else ""),
        output={"entries": entries, "truncated": truncated},
    )


# ---------------------------------------------------------------------------
# workspace.search_code
# ---------------------------------------------------------------------------

_SEARCH_SPEC = ToolSpec(
    server="workspace",
    name="search_code",
    description="在工作区内按行搜索代码；跳过 .git/node_modules/__pycache__、"
    ">1MB 与二进制文件（首 8KB 含 \\0）；命中返回 {path,line,text(≤200 字符)}。",
    risk=RiskLevel.SAFE,
    parameters={
        "pattern": "string",
        "path": "string",
        "is_regex": "boolean",
        "max_results": "int",
    },
    required=("pattern",),
    handler=None,
)


async def _search_code(ctx: ToolContext, args: dict) -> ToolResult:
    args = validate_args(_SEARCH_SPEC, args)
    pattern = args["pattern"]
    path = args.get("path", ".")
    is_regex = args.get("is_regex", False)
    max_results = args.get("max_results", 50)
    if max_results <= 0:
        raise ToolArgError("max_results 必须为正整数")

    regex = None
    if is_regex:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            raise ToolArgError(f"非法正则: {exc}") from None

    root = _guard(ctx).resolve(ctx.workspace, path)
    if not root.exists():
        return ToolResult(ok=False, summary=f"路径不存在: {path}", error="路径不存在")

    files: list[Path] = []
    if root.is_file():
        files.append(root)
    else:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = sorted(d for d in dirnames if d.lower() not in _SKIP_DIRS)
            files.extend(Path(dirpath) / fn for fn in sorted(filenames))

    matches: list[dict] = []
    truncated = False
    for f in files:
        try:
            if f.stat().st_size > _MAX_SEARCH_FILE_BYTES:
                continue
            with open(f, "rb") as fh:
                head = fh.read(8192)
                if b"\0" in head:  # 二进制文件
                    continue
                body = fh.read()
        except OSError:
            continue
        text = (head + body).decode("utf-8", errors="replace")
        rel = _rel_name(f, root)
        for lineno, line in enumerate(text.splitlines(), 1):
            hit = regex.search(line) if regex is not None else (pattern in line)
            if not hit:
                continue
            if len(matches) >= max_results:
                truncated = True
                break
            matches.append({"path": rel, "line": lineno, "text": line[:_MAX_HIT_TEXT_CHARS]})
        if truncated:
            break

    return ToolResult(
        ok=True,
        summary=f"搜索 '{pattern}'：{len(matches)} 处命中" + ("（已截断）" if truncated else ""),
        output={"matches": matches, "count": len(matches), "truncated": truncated},
    )


# ---------------------------------------------------------------------------
# workspace.write_file
# ---------------------------------------------------------------------------

_WRITE_SPEC = ToolSpec(
    server="workspace",
    name="write_file",
    description="以 UTF-8 写入工作区文件；父目录缺失且未开 create_dirs 时拒绝。",
    risk=RiskLevel.DANGEROUS,
    parameters={"path": "string", "content": "string", "create_dirs": "boolean"},
    required=("path", "content"),
    handler=None,
)


async def _write_file(ctx: ToolContext, args: dict) -> ToolResult:
    args = validate_args(_WRITE_SPEC, args)
    path = args["path"]
    content = args["content"]
    create_dirs = args.get("create_dirs", False)

    resolved = _guard(ctx).resolve(ctx.workspace, path)
    parent = resolved.parent
    if not parent.exists():
        if not create_dirs:
            return ToolResult(ok=False, summary=f"父目录不存在: {path}", error="目录不存在")
        parent.mkdir(parents=True, exist_ok=True)

    data = content.encode("utf-8")
    # 捕获写入前内容（供 Harness 生成真实 code.diff.created 事件；上限 100KB）
    previous_content: str | None = None
    if resolved.exists():
        try:
            previous_content = resolved.read_text("utf-8", errors="replace")[:100_000]
        except OSError:
            previous_content = None
    resolved.write_bytes(data)
    return ToolResult(
        ok=True,
        summary=f"写入 {path}（{len(data)} 字节）",
        output={
            "path": path,
            "bytes": len(data),
            "previousContent": previous_content,
            "content": content[:100_000],
        },
    )


# ---------------------------------------------------------------------------
# workspace.run_tests
# ---------------------------------------------------------------------------

_TESTS_SPEC = ToolSpec(
    server="workspace",
    name="run_tests",
    description="在工作区运行 pytest（argv 数组，无 shell）；paths 为相对路径列表，"
    "k 为 pytest -k 过滤表达式；返回 exitCode/passed/failed/skipped/logTail。",
    risk=RiskLevel.GATED,
    parameters={"paths": "array", "k": "string"},
    handler=None,
)

_PYTEST_BASE_ARGV = [
    sys.executable,
    "-m",
    "pytest",
    "-q",
    "--no-header",
    "-p",
    "no:cacheprovider",
]
_LOG_TAIL_CHARS = 4000


def _count(stdout: str, pattern: str) -> int:
    m = re.search(pattern, stdout)
    return int(m.group(1)) if m else 0


async def _run_tests(ctx: ToolContext, args: dict) -> ToolResult:
    args = validate_args(_TESTS_SPEC, args)
    paths = args.get("paths", [])
    k = args.get("k")

    guard = _guard(ctx)
    argv = list(_PYTEST_BASE_ARGV)
    for p in paths:
        resolved = guard.resolve(ctx.workspace, p)  # 相对路径 + 拒绝逃逸
        argv.append(str(resolved))
    if k is not None:
        argv += ["-k", str(k)]
    _WHITELIST.assert_allowed(argv)

    run = await LocalProcessProvider().run(
        argv,
        cwd=ctx.workspace,
        timeout_seconds=ctx.timeout_seconds,
        output_limit_bytes=ctx.output_limit_bytes,
    )

    passed = _count(run.stdout, r"(\d+) passed")
    failed = _count(run.stdout, r"(\d+) failed")
    skipped = _count(run.stdout, r"(\d+) skipped")

    if run.timed_out:
        summary = "执行超时"
    else:
        parts = []
        if passed:
            parts.append(f"{passed} passed")
        if failed:
            parts.append(f"{failed} failed")
        if skipped:
            parts.append(f"{skipped} skipped")
        summary = ", ".join(parts) if parts else f"pytest 退出码 {run.exit_code}"

    return ToolResult(
        ok=run.ok,
        summary=summary,
        output={
            "exitCode": run.exit_code,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "logTail": run.stdout[-_LOG_TAIL_CHARS:],
            "timedOut": run.timed_out,
            "truncated": run.truncated,
        },
    )


_READ_SPEC.handler = _read_file
_LIST_SPEC.handler = _list_dir
_SEARCH_SPEC.handler = _search_code
_WRITE_SPEC.handler = _write_file
_TESTS_SPEC.handler = _run_tests


def register_workspace_tools(registry) -> None:
    """注册 5 个 workspace 工具（registry: ToolRegistry，避免环导不写类型注解）。"""
    for spec in (_READ_SPEC, _LIST_SPEC, _SEARCH_SPEC, _WRITE_SPEC, _TESTS_SPEC):
        registry.register(spec)
