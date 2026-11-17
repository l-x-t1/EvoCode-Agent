"""子进程执行 Provider（B2 隔离层）。

⚠️ 隔离级别诚实声明（修订要求）：
- 本模块当前唯一的 LocalProcessProvider 在宿主机上直接启动子进程，
  叠加 core/security.py 的应用层访问控制（工作区白名单 + 命令白名单 +
  输出上限 + 超时终止），**不构成操作系统级沙箱**。
- SandboxProvider 接口即为容器隔离预留：后续提供容器实现（如 Windows 容器/
  远程沙箱服务）时替换注入即可，调用方签名不变。在容器实现落地前，
  系统提示与 UI 不得宣称「沙箱隔离已完成」。

职责：受控地启动 argv 子进程——超时终止（含进程树）、输出字节上限、
退出码与耗时采集。不提供 shell（无字符串拼接命令，无注入面）。
"""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class RunResult:
    argv: list[str]
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    duration_ms: int = 0
    timed_out: bool = False
    truncated: bool = False
    killed: bool = False
    extra: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return (not self.timed_out) and (not self.killed) and self.exit_code == 0


async def _kill_tree(pid: int) -> None:
    """Windows 进程树终止；POSIX 退化为进程组终止。"""
    import subprocess
    import sys

    try:
        if sys.platform == "win32":
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
            )
        else:
            import os
            import signal

            os.killpg(pid, signal.SIGKILL)
    except Exception as exc:  # noqa: BLE001 - 终止失败仅记录，不掩盖主流程
        logger.warning("进程树终止失败 pid=%s: %s", pid, exc)


class SandboxProvider(ABC):
    """容器隔离执行接口（容器实现落地前仅本地子进程实现）。"""

    @abstractmethod
    async def run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> RunResult: ...


class LocalProcessProvider(SandboxProvider):
    """本地子进程实现（MVP）。隔离级别见模块 docstring 的诚实声明。"""

    def __init__(self) -> None:
        self._last = None  # 最近 RunResult（调试/测试断言用）

    async def run(
        self,
        argv: list[str],
        *,
        cwd: Path,
        timeout_seconds: int,
        output_limit_bytes: int,
    ) -> RunResult:
        start = time.perf_counter()
        result = RunResult(argv=[str(a) for a in argv])
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err, truncated = await asyncio.wait_for(
                self._collect(proc, output_limit_bytes), timeout=timeout_seconds
            )
            result.stdout, result.stderr, result.truncated = out, err, truncated
            result.exit_code = proc.returncode
        except asyncio.TimeoutError:
            result.timed_out = True
            await _kill_tree(proc.pid)
            try:
                out, err = await asyncio.wait_for(proc.communicate(), timeout=5)
                result.stdout = (out or b"").decode("utf-8", "replace")[:output_limit_bytes]
                result.stderr = (err or b"").decode("utf-8", "replace")[:output_limit_bytes]
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001 - 启动失败等
            result.killed = True
            result.stderr = f"spawn failed: {exc}"
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        result.duration_ms = int((time.perf_counter() - start) * 1000)
        self._last = result
        return result

    async def _collect(self, proc, limit: int):
        """限长读取：超限即终止进程并返回已读内容（防止管道阻塞）。"""

        async def _read_stream(stream) -> tuple[str, bool]:
            chunks: list[bytes] = []
            total = 0
            truncated = False
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                if total >= limit:
                    chunks.append(chunk[: max(0, limit - (total - len(chunk)))])
                    truncated = True
                    break
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", "replace"), truncated

        out_task = asyncio.create_task(_read_stream(proc.stdout))
        err_task = asyncio.create_task(_read_stream(proc.stderr))
        out, err = await asyncio.gather(out_task, err_task)
        await proc.wait()
        truncated = out[1] or err[1]
        if truncated:
            await _kill_tree(proc.pid)
        return out[0], err[0], truncated
