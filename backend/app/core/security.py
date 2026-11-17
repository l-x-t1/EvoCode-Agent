"""工作区访问控制（B2 安全层）。

⚠️ 隔离级别诚实声明（修订要求）：本模块提供的是**应用层访问控制**——
路径规范化、符号链接/路径逃逸检查、授权工作区校验、命令白名单。
**不是操作系统级沙箱**；操作系统级隔离由 core/sandbox.py 的
SandboxProvider 容器实现承担（接口已定义，实现待落地）。

防护面：
1. 拒绝绝对路径 / 盘符 / UNC 路径输入；
2. 规范化后必须落在授权工作区内（含 `..` 逃逸）；
3. 已存在的符号链接（文件或任意祖先目录）经 realpath 解析后仍必须在
   工作区内（防 symlink 逃逸）；
4. 子进程 argv 前缀白名单（纵深防御；工具层本就不暴露任意命令）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PureWindowsPath

from app.core.logging import get_logger

logger = get_logger(__name__)


class SecurityViolation(Exception):
    """安全违规：一律拒绝并记录，不泄露内部路径细节。"""


def _deep_realpath(p: Path) -> Path:
    return Path(os.path.realpath(str(p)))


class WorkspaceGuard:
    """每个任务一个授权工作区：WORKSPACE_BASE/<task_id>/。"""

    def __init__(self, base: str | Path) -> None:
        self.base = _deep_realpath(Path(base))
        self.base.mkdir(parents=True, exist_ok=True)

    def task_root(self, task_id: str) -> Path:
        root = self.base / task_id
        root.mkdir(parents=True, exist_ok=True)
        root_r = _deep_realpath(root)
        if root_r != root and not _is_within(root_r, self.base):
            raise SecurityViolation("工作区初始化失败")
        return root

    def resolve(self, task_root: Path, user_path: str) -> Path:
        """把工具入参解析为工作区内安全绝对路径；任何逃逸一律拒绝。"""
        if not isinstance(user_path, str) or user_path.strip() == "":
            raise SecurityViolation("非法路径参数")
        p = PureWindowsPath(user_path)
        if p.is_absolute() or user_path.startswith(("/", "\\\\")) or (len(user_path) > 1 and user_path[1] == ":"):
            raise SecurityViolation("拒绝绝对路径")
        if any(part in ("..",) for part in p.parts):
            raise SecurityViolation("拒绝路径穿越")
        candidate = (task_root / user_path).resolve()
        root_r = _deep_realpath(task_root)
        # 1) 规范化结果必须在任务工作区内（覆盖 .. 已被上面拦截，此为纵深）
        if not _is_within(candidate, root_r):
            raise SecurityViolation("路径越界")
        # 2) symlink 逃逸：真实路径（解析全部已存在符号链接）必须仍在区内
        real = _deep_realpath(candidate)
        if not _is_within(real, root_r):
            raise SecurityViolation("拒绝符号链接逃逸")
        return candidate


def _is_within(child: Path, parent: Path) -> bool:
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class CommandWhitelist:
    """argv 前缀白名单（纵深防御层）。"""

    def __init__(self) -> None:
        import re

        self.py = Path(sys.executable).name.lower()
        self._pytest = (self.py, "-m", "pytest")
        self._git_read = re.compile(r"^(status|diff|log|show)$")

    def assert_allowed(self, argv: list[str]) -> None:
        if not argv:
            raise SecurityViolation("空命令")
        head = Path(str(argv[0])).name.lower()
        if head == "git":
            if len(argv) < 2 or not self._git_read.match(str(argv[1])):
                raise SecurityViolation("仅允许 git 只读子命令")
            return
        if head == self.py:
            if len(argv) >= 3 and argv[1] == "-m" and str(argv[2]) == "pytest":
                return
        raise SecurityViolation("命令不在白名单")


def default_provider() -> "LocalProcessProvider":
    from app.core.sandbox import LocalProcessProvider

    return LocalProcessProvider()
