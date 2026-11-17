"""B2 工具层单测：直接构造 ToolContext 调 handler（不经 HTTP）。

覆盖：
a) write→read 往返（含中文）        b) read_file 行 offset/limit
c) read 超大文件截断               d) list_dir 递归/非递归
e) search_code 命中与截断          f) 非法正则 → ToolArgError
g) write_file 父目录缺失 → ok=False h) 路径逃逸 → SecurityViolation
i) run_tests 通过样例              j) run_tests 失败样例
k) run_tests paths 逃逸            l) 参数校验 → ToolArgError
m) git 工具：非仓库 ok=False / git init 后 ok=True
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.security import SecurityViolation
from app.tools.base import ToolArgError, ToolContext, ToolResult
from app.tools.git_tools import register_git_tools
from app.tools.registry import ToolRegistry
from app.tools.workspace_tools import register_workspace_tools


def make_ctx(ws: Path, output_limit_bytes: int = 1_000_000) -> ToolContext:
    return ToolContext(
        run_id="run_test",
        task_id="task_test",
        workspace=ws,
        timeout_seconds=30,
        output_limit_bytes=output_limit_bytes,
    )


async def call(registry: ToolRegistry, full_name: str, ctx: ToolContext, **args) -> ToolResult:
    """直接调用已注册 handler（参数校验由 handler 内部的 validate_args 执行）。"""
    server, name = full_name.split(".", 1)
    spec = registry.get(server, name)
    return await spec.handler(ctx, args)


@pytest.fixture
def registry() -> ToolRegistry:
    r = ToolRegistry()
    register_workspace_tools(r)
    register_git_tools(r)
    return r


@pytest.fixture
def ctx(tmp_path) -> ToolContext:
    return make_ctx(tmp_path / "ws")


# ---------------------------------------------------------------------------
# a) write→read 往返（含中文）
# ---------------------------------------------------------------------------


async def test_write_read_roundtrip_chinese(registry: ToolRegistry, ctx: ToolContext):
    content = "# EvoCode\n中文内容 ✓ emoji 🚀 第二行"
    r = await call(
        registry, "workspace.write_file", ctx,
        path="docs/笔记.md", content=content, create_dirs=True,
    )
    assert isinstance(r, ToolResult)
    assert r.ok is True
    assert r.error is None
    assert r.output["bytes"] == len(content.encode("utf-8"))

    r2 = await call(registry, "workspace.read_file", ctx, path="docs/笔记.md")
    assert r2.ok is True
    assert r2.output["content"] == content
    assert r2.output["truncated"] is False
    assert r2.output["totalLines"] == 2
    assert r2.output["returnedLines"] == 2


# ---------------------------------------------------------------------------
# b) read_file 行 offset/limit
# ---------------------------------------------------------------------------


async def test_read_file_offset_and_limit(registry: ToolRegistry, ctx: ToolContext):
    body = "\n".join(f"line{i}" for i in range(100))
    assert (await call(registry, "workspace.write_file", ctx, path="lines.txt", content=body)).ok

    r = await call(registry, "workspace.read_file", ctx, path="lines.txt", offset=10, limit=5)
    assert r.ok is True
    assert r.output["content"] == "\n".join(f"line{i}" for i in range(10, 15))
    assert r.output["totalLines"] == 100
    assert r.output["returnedLines"] == 5

    # 窗口越过文件末尾：只返回剩余行
    r2 = await call(registry, "workspace.read_file", ctx, path="lines.txt", offset=98, limit=10)
    assert r2.ok is True
    assert r2.output["returnedLines"] == 2
    assert r2.output["content"] == "line98\nline99"


# ---------------------------------------------------------------------------
# c) read 超大文件截断（output_limit_bytes=512）
# ---------------------------------------------------------------------------


async def test_read_file_truncated_by_output_limit(registry: ToolRegistry, ctx: ToolContext):
    big = "x" * 2048
    assert (await call(registry, "workspace.write_file", ctx, path="big.txt", content=big)).ok

    ctx_small = make_ctx(ctx.workspace, output_limit_bytes=512)
    r = await call(registry, "workspace.read_file", ctx_small, path="big.txt")
    assert r.ok is True
    assert r.output["truncated"] is True
    assert len(r.output["content"].encode("utf-8")) == 512


# ---------------------------------------------------------------------------
# d) list_dir 递归 / 非递归
# ---------------------------------------------------------------------------


async def test_list_dir_recursive_and_flat(registry: ToolRegistry, ctx: ToolContext):
    assert (await call(registry, "workspace.write_file", ctx, path="a.txt", content="hello")).ok
    assert (
        await call(
            registry, "workspace.write_file", ctx,
            path="sub/b.txt", content="abc" * 10, create_dirs=True,
        )
    ).ok

    r = await call(registry, "workspace.list_dir", ctx, path=".")
    assert r.ok is True
    entries = {e["name"]: e for e in r.output["entries"]}
    assert set(entries) == {"a.txt", "sub"}
    assert entries["a.txt"]["type"] == "file"
    assert entries["a.txt"]["size"] == 5
    assert entries["sub"]["type"] == "dir"

    r2 = await call(registry, "workspace.list_dir", ctx, path=".", recursive=True)
    assert r2.ok is True
    entries2 = {e["name"]: e for e in r2.output["entries"]}
    assert set(entries2) == {"a.txt", "sub", "sub/b.txt"}
    assert entries2["sub/b.txt"]["type"] == "file"
    assert entries2["sub/b.txt"]["size"] == 30


async def test_list_dir_missing_dir(registry: ToolRegistry, ctx: ToolContext):
    r = await call(registry, "workspace.list_dir", ctx, path="no/such/dir")
    assert r.ok is False
    assert r.error == "目录不存在"


# ---------------------------------------------------------------------------
# e) search_code 命中与 max_results 截断
# ---------------------------------------------------------------------------


async def test_search_code_hits_and_max_results(registry: ToolRegistry, ctx: ToolContext):
    needle_body = "\n".join(f"needle line {i}" for i in range(5))
    assert (
        await call(
            registry, "workspace.write_file", ctx,
            path="code/needle.txt", content=needle_body, create_dirs=True,
        )
    ).ok
    assert (
        await call(
            registry, "workspace.write_file", ctx,
            path="code/other.txt", content="nothing here",
        )
    ).ok

    r = await call(registry, "workspace.search_code", ctx, pattern="needle")
    assert r.ok is True
    assert r.output["count"] == 5
    assert r.output["truncated"] is False
    assert {m["path"] for m in r.output["matches"]} == {"code/needle.txt"}
    assert sorted(m["line"] for m in r.output["matches"]) == [1, 2, 3, 4, 5]
    assert all(len(m["text"]) <= 200 for m in r.output["matches"])

    # 正则命中（内容为 "needle line N"）
    r2 = await call(
        registry, "workspace.search_code", ctx, pattern=r"needle line \d", is_regex=True
    )
    assert r2.ok is True
    assert r2.output["count"] == 5

    # max_results 截断
    r3 = await call(registry, "workspace.search_code", ctx, pattern="needle", max_results=3)
    assert r3.ok is True
    assert r3.output["count"] == 3
    assert r3.output["truncated"] is True


# ---------------------------------------------------------------------------
# f) 非法正则 → ToolArgError
# ---------------------------------------------------------------------------


async def test_search_code_invalid_regex(registry: ToolRegistry, ctx: ToolContext):
    with pytest.raises(ToolArgError):
        await call(registry, "workspace.search_code", ctx, pattern="[unclosed", is_regex=True)


# ---------------------------------------------------------------------------
# g) write_file 父目录缺失 → ok=False
# ---------------------------------------------------------------------------


async def test_write_file_missing_parent(registry: ToolRegistry, ctx: ToolContext):
    r = await call(registry, "workspace.write_file", ctx, path="no/such/f.txt", content="x")
    assert r.ok is False
    assert r.error == "目录不存在"
    assert not (ctx.workspace / "no").exists()

    # 开 create_dirs 后成功
    r2 = await call(
        registry, "workspace.write_file", ctx,
        path="deep/dir/f.txt", content="ok", create_dirs=True,
    )
    assert r2.ok is True
    assert (ctx.workspace / "deep" / "dir" / "f.txt").read_text(encoding="utf-8") == "ok"


# ---------------------------------------------------------------------------
# h) 路径逃逸 → SecurityViolation
# ---------------------------------------------------------------------------


async def test_path_escape_rejected(registry: ToolRegistry, ctx: ToolContext):
    with pytest.raises(SecurityViolation):
        await call(registry, "workspace.read_file", ctx, path="..\\secret.txt")
    with pytest.raises(SecurityViolation):
        await call(registry, "workspace.read_file", ctx, path="C:\\Windows\\system.ini")
    with pytest.raises(SecurityViolation):
        await call(registry, "workspace.read_file", ctx, path="/etc/evil")
    with pytest.raises(SecurityViolation):
        await call(registry, "workspace.write_file", ctx, path="..\\evil.txt", content="x")


# ---------------------------------------------------------------------------
# i/j) run_tests 通过样例 / 失败样例（真实 pytest 子进程）
# ---------------------------------------------------------------------------


async def test_run_tests_passes(registry: ToolRegistry, ctx: ToolContext):
    assert (
        await call(
            registry, "workspace.write_file", ctx,
            path="test_ok.py", content="def test_ok():\n    assert 1 + 1 == 2\n",
        )
    ).ok

    r = await call(registry, "workspace.run_tests", ctx, paths=["test_ok.py"])
    assert r.ok is True
    assert r.output["exitCode"] == 0
    assert r.output["passed"] >= 1
    assert r.output["failed"] == 0
    assert r.output["timedOut"] is False
    assert "passed" in r.summary


async def test_run_tests_failures(registry: ToolRegistry, ctx: ToolContext):
    assert (
        await call(
            registry, "workspace.write_file", ctx,
            path="test_bad.py", content="def test_bad():\n    assert False, 'boom'\n",
        )
    ).ok

    r = await call(registry, "workspace.run_tests", ctx, paths=["test_bad.py"])
    assert r.ok is False
    assert r.output["exitCode"] != 0
    assert r.output["failed"] >= 1
    assert r.output["passed"] == 0
    assert "failed" in r.summary
    assert "boom" in r.output["logTail"]


# ---------------------------------------------------------------------------
# k) run_tests 的 paths 参数逃逸 → SecurityViolation
# ---------------------------------------------------------------------------


async def test_run_tests_path_escape_rejected(registry: ToolRegistry, ctx: ToolContext):
    with pytest.raises(SecurityViolation):
        await call(registry, "workspace.run_tests", ctx, paths=["..\\evil"])
    with pytest.raises(SecurityViolation):
        await call(registry, "workspace.run_tests", ctx, paths=["C:\\tmp\\evil_test.py"])


# ---------------------------------------------------------------------------
# l) 参数校验：缺必填 / 未知参数 / 类型错 → ToolArgError
# ---------------------------------------------------------------------------


async def test_arg_validation_errors(registry: ToolRegistry, ctx: ToolContext):
    with pytest.raises(ToolArgError):  # 缺必填 path
        await call(registry, "workspace.read_file", ctx)
    with pytest.raises(ToolArgError):  # 未知参数
        await call(registry, "workspace.read_file", ctx, path="a.txt", foo=1)
    with pytest.raises(ToolArgError):  # 类型错（string 给 int 位置）
        await call(registry, "workspace.read_file", ctx, path="a.txt", offset="2")
    with pytest.raises(ToolArgError):  # 缺必填 content
        await call(registry, "workspace.write_file", ctx, path="a.txt")
    with pytest.raises(ToolArgError):  # array 元素类型错
        await call(registry, "workspace.run_tests", ctx, paths=["a.py"], k=123)


# ---------------------------------------------------------------------------
# m) git 工具：非仓库 ok=False；git init 后 ok=True
# ---------------------------------------------------------------------------


def _require_git() -> None:
    if shutil.which("git") is None:
        pytest.skip("git 不可用")


async def test_git_tools_in_non_repo(tmp_path):
    _require_git()
    registry = ToolRegistry()
    register_git_tools(registry)
    ctx = make_ctx(tmp_path / "plain")

    r = await call(registry, "git.git_status", ctx)
    assert r.ok is False
    assert r.error == "工作区不是 git 仓库"

    r2 = await call(registry, "git.git_diff", ctx)
    assert r2.ok is False
    assert r2.error == "工作区不是 git 仓库"


async def test_git_tools_in_real_repo(tmp_path, registry: ToolRegistry):
    _require_git()
    ws = tmp_path / "repo"
    ws.mkdir()
    subprocess.run(["git", "init"], cwd=ws, capture_output=True, check=True)

    ctx = make_ctx(ws)

    assert (
        await call(registry, "workspace.write_file", ctx, path="sample.txt", content="data")
    ).ok

    r = await call(registry, "git.git_status", ctx)
    assert r.ok is True
    assert r.output["clean"] is False
    assert any(f["path"] == "sample.txt" and f["code"] == "??" for f in r.output["files"])

    r2 = await call(registry, "git.git_diff", ctx)
    assert r2.ok is True  # 未跟踪文件不出现在 diff，退出码 0

    # path 限定且命中跟踪文件时 diff 正常执行
    r3 = await call(registry, "git.git_diff", ctx, path="sample.txt")
    assert r3.ok is True
    assert r3.output["diff"] == ""
