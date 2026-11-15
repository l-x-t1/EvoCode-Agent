"""SSE 端点测试（B3）：GET /api/v1/runs/{id}/events 的 text/event-stream 形态。

要点：
- httpx 0.28 官方 ASGITransport 会先收集完整响应体再返回，长连 SSE 流会卡死；
  这里实现真正流式的进程内 transport（逐块推送、断开时发 http.disconnect）。
- fixture 风格与 test_runs_api.py 一致：真实 PG 写入 run + agent_execution_logs。
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

import pytest
import pytest_asyncio
from asgi_lifespan import LifespanManager
from httpx import AsyncBaseTransport, AsyncByteStream, AsyncClient, Request, Response

from app.core.config import get_settings
from app.core.enums import TaskStatus
from app.db.session import get_session_factory
from app.main import app as fastapi_app
from app.models.execution import AgentExecutionLog
from app.models.task import AgentRun, AgentTask
from app.repositories.users import UsersRepository

SSE_HEADERS = {"Accept": "text/event-stream"}
_EOF = object()  # 响应体结束哨兵


class StreamingASGITransport(AsyncBaseTransport):
    """流式版 ASGI transport：响应体块一经产生即推给客户端。

    官方 httpx.ASGITransport(0.28) 在 handle_async_request 里 `await app(...)`
    收齐全部 body 才返回 Response，长连 SSE 会卡在 client.stream() 进入处；
    本实现用 asyncio.Queue 边产边推，并在连接关闭时向 app 发 http.disconnect。
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def handle_async_request(self, request: Request) -> Response:
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": request.method,
            "headers": [(k.lower(), v) for (k, v) in request.headers.raw],
            "scheme": request.url.scheme,
            "path": request.url.path,
            "raw_path": request.url.raw_path.split(b"?")[0],
            "query_string": request.url.query,
            "server": (request.url.host, request.url.port),
            "client": ("testclient", 50000),
            "root_path": "",
        }

        request_complete = False
        response_started = asyncio.Event()
        status_holder: list[int] = [500]
        headers_holder: list[list[tuple[bytes, bytes]]] = [[]]
        chunks: asyncio.Queue[Any] = asyncio.Queue()
        disconnected = asyncio.Event()

        async def receive() -> dict[str, Any]:
            nonlocal request_complete
            if request_complete:
                await disconnected.wait()
                return {"type": "http.disconnect"}
            try:
                body = await request.stream.__aiter__().__anext__()
            except StopAsyncIteration:
                request_complete = True
                return {"type": "http.request", "body": b"", "more_body": False}
            return {"type": "http.request", "body": body, "more_body": True}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder[0] = message["status"]
                headers_holder[0] = message.get("headers", [])
                response_started.set()
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if body and request.method != "HEAD":
                    await chunks.put(body)
                if not message.get("more_body", False):
                    await chunks.put(_EOF)

        async def run_app() -> None:
            try:
                await self.app(scope, receive, send)
            finally:
                await chunks.put(_EOF)

        app_task = asyncio.create_task(run_app())
        started_waiter = asyncio.ensure_future(response_started.wait())
        done, _pending = await asyncio.wait(
            {started_waiter, app_task}, return_when=asyncio.FIRST_COMPLETED
        )
        started_waiter.cancel()
        if app_task in done and not response_started.is_set():
            # app 在响应头之前出错（正常应被全局异常处理器转为 JSON），按官方语义原样抛出
            await app_task

        class _LiveStream(AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                while True:
                    chunk = await chunks.get()
                    if chunk is _EOF:
                        return
                    yield chunk

            async def aclose(self) -> None:
                # 客户端关闭连接 → 通知 app http.disconnect 并取消 app 任务
                disconnected.set()
                if not app_task.done():
                    app_task.cancel()
                if app_task.done():
                    try:
                        app_task.result()
                    except BaseException:  # noqa: S110 - 吞掉取结果异常，避免 unretrieved 警告
                        pass

        return Response(status_holder[0], headers=headers_holder[0], stream=_LiveStream())


@pytest_asyncio.fixture
async def sse_client() -> AsyncIterator[AsyncClient]:
    async with LifespanManager(fastapi_app):
        async with AsyncClient(
            transport=StreamingASGITransport(fastapi_app), base_url="http://testserver"
        ) as client:
            yield client


_EVENT_FIXTURES = [
    ("run.status", {"to": "executing"}),
    ("code.diff.created", {"files": [
        {"path": "app/main.py", "additions": 3, "deletions": 1, "patch": "@@ -1 +1,3 @@\n+x"},
    ]}),
    ("test.finished", {"passed": 2, "failed": 0, "skipped": 0,
                       "failures": [], "logTail": "2 passed"}),
]


async def _mk_run(
    deps_available: bool,
    *,
    status: TaskStatus = TaskStatus.EXECUTING,
    n_events: int = 3,
) -> str:
    """造 run + n_events 条事件日志（真实 PG），风格仿 test_runs_api.py。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        now = datetime.now(timezone.utc)
        task = AgentTask(user_id=user.id, title="SSE 测试任务", description="",
                         model="auto", status=TaskStatus.EXECUTING,
                         created_at=now, updated_at=now)
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=status, model="glm-5.3",
                       started_at=now, created_at=now, updated_at=now)
        session.add(run)
        await session.flush()
        for seq, (etype, payload) in enumerate(_EVENT_FIXTURES[:n_events], start=1):
            session.add(AgentExecutionLog(run_id=run.id, seq=seq, event_type=etype,
                                          payload=payload, created_at=now))
        await session.commit()
        return run.id


def _parse_frames(raw: str) -> list[dict[str, Any]]:
    """解析 SSE 文本：数据帧含 event/id/data；心跳注释帧记入 comment。"""
    frames: list[dict[str, Any]] = []
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.split("\n") if ln != ""]
        if not lines:
            continue
        frame: dict[str, Any] = {"event": None, "id": None, "data": None, "comment": None}
        for line in lines:
            if line.startswith(":"):
                frame["comment"] = line[1:].strip()
            elif line.startswith("event:"):
                frame["event"] = line[len("event:"):].strip()
            elif line.startswith("id:"):
                frame["id"] = int(line[len("id:"):].strip())
            elif line.startswith("data:"):
                frame["data"] = json.loads(line[len("data:"):].strip())
        frames.append(frame)
    return frames


async def _read_to_eof(response: Any, timeout: float = 10.0) -> tuple[str, bool]:
    """读到 EOF（或超时）。返回 (文本, 是否在超时内自然 EOF)。"""
    parts: list[bytes] = []

    async def _drain() -> None:
        async for chunk in response.aiter_bytes():
            parts.append(chunk)

    finished = True
    try:
        await asyncio.wait_for(_drain(), timeout=timeout)
    except asyncio.TimeoutError:
        finished = False
    return b"".join(parts).decode("utf-8"), finished


async def test_events_json_form_regression(sse_client: AsyncClient, deps_available: bool):
    """a) 无 text/event-stream 的 Accept（含默认 */*）→ JSON 形态与 B1 完全一致。"""
    run_id = await _mk_run(deps_available)
    r1 = await sse_client.get(f"/api/v1/runs/{run_id}/events")  # httpx 默认 Accept: */*
    assert r1.status_code == 200
    assert r1.headers["content-type"].startswith("application/json")
    body = r1.json()
    assert set(body.keys()) == {"items"}
    assert [e["seq"] for e in body["items"]] == [1, 2, 3]
    item = body["items"][0]
    assert set(item.keys()) == {"seq", "eventType", "payload", "createdAt"}
    assert item["payload"] == {"to": "executing"}
    assert item["eventType"] == "run.status"
    r2 = await sse_client.get(f"/api/v1/runs/{run_id}/events", headers={"Accept": "*/*"})
    assert r2.status_code == 200
    assert r2.headers["content-type"].startswith("application/json")
    assert [e["seq"] for e in r2.json()["items"]] == [1, 2, 3]


async def test_events_sse_content_type(sse_client: AsyncClient, deps_available: bool):
    """b) Accept: text/event-stream → content-type 为 text/event-stream。"""
    run_id = await _mk_run(deps_available)
    async with sse_client.stream(
        "GET", f"/api/v1/runs/{run_id}/events", headers=SSE_HEADERS
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
    # 退出 stream 上下文即主动断开：流被取消、连接关闭（断开处理不挂起）


async def test_sse_full_history_and_envelope(sse_client: AsyncClient, deps_available: bool):
    """c) 首连 Last-Event-ID=0 → 全部历史帧、seq 升序、信封五键齐全。"""
    run_id = await _mk_run(deps_available, status=TaskStatus.COMPLETED, n_events=3)
    t0 = time.monotonic()
    async with sse_client.stream(
        "GET", f"/api/v1/runs/{run_id}/events",
        headers={**SSE_HEADERS, "Last-Event-ID": "0"},
    ) as r:
        assert r.status_code == 200
        raw, eof = await _read_to_eof(r, timeout=10.0)
    assert eof, "终态 run 的流应在有限时间内自然结束"
    assert time.monotonic() - t0 < 15.0

    data_frames = [f for f in _parse_frames(raw) if f["data"] is not None]
    seqs = [f["id"] for f in data_frames]
    assert seqs == [1, 2, 3]
    assert seqs == sorted(seqs)
    expected = {seq: (etype, payload) for seq, (etype, payload) in enumerate(_EVENT_FIXTURES, start=1)}
    for f in data_frames:
        assert set(f["data"].keys()) == {"v", "seq", "ts", "runId", "payload"}
        assert f["data"]["v"] == 1
        assert f["data"]["runId"] == run_id
        assert f["data"]["seq"] == f["id"]
        datetime.fromisoformat(f["data"]["ts"])  # ts 为合法 ISO8601
        etype, payload = expected[f["id"]]
        assert f["event"] == etype
        assert f["data"]["payload"] == payload


async def test_sse_last_event_id_resume(sse_client: AsyncClient, deps_available: bool):
    """d) Last-Event-ID=1 → 只收到 seq>1；非法头回退 after 参数。"""
    run_id = await _mk_run(deps_available, status=TaskStatus.COMPLETED, n_events=3)
    async with sse_client.stream(
        "GET", f"/api/v1/runs/{run_id}/events",
        headers={**SSE_HEADERS, "Last-Event-ID": "1"},
    ) as r:
        raw, eof = await _read_to_eof(r, timeout=10.0)
    assert eof
    seqs = [f["id"] for f in _parse_frames(raw) if f["data"] is not None]
    assert seqs == [2, 3]

    # 非法 Last-Event-ID → 回退 query after
    async with sse_client.stream(
        "GET", f"/api/v1/runs/{run_id}/events?after=1",
        headers={**SSE_HEADERS, "Last-Event-ID": "not-a-number"},
    ) as r:
        raw2, eof2 = await _read_to_eof(r, timeout=10.0)
    assert eof2
    seqs2 = [f["id"] for f in _parse_frames(raw2) if f["data"] is not None]
    assert seqs2 == [2, 3]


async def test_sse_terminal_run_closes(sse_client: AsyncClient, deps_available: bool):
    """e) run 终态 → 流在有限时间内自然结束（EOF，且耗时 <15s）。"""
    run_id = await _mk_run(deps_available, status=TaskStatus.FAILED, n_events=2)
    t0 = time.monotonic()
    async with sse_client.stream(
        "GET", f"/api/v1/runs/{run_id}/events", headers=SSE_HEADERS
    ) as r:
        assert r.status_code == 200
        raw, eof = await _read_to_eof(r, timeout=14.0)
    elapsed = time.monotonic() - t0
    assert eof, f"终态 run 且无新事件 → 流应自然关闭（实际 {elapsed:.1f}s 仍打开）"
    assert elapsed < 15.0
    seqs = [f["id"] for f in _parse_frames(raw) if f["data"] is not None]
    assert seqs == [1, 2]  # 未带 Last-Event-ID → 缺省从 0 起全部补发


async def test_sse_run_not_found(sse_client: AsyncClient, deps_available: bool):
    """f) run 不存在 → 404 错误体（SSE Accept 下同样是 404 JSON 错误结构）。"""
    missing = "run_sse_missing00000000000000"
    async with sse_client.stream(
        "GET", f"/api/v1/runs/{missing}/events", headers=SSE_HEADERS
    ) as r:
        assert r.status_code == 404
        await r.aread()
        body = r.json()
    assert body["error"]["code"] == "not_found"
    # JSON 形态（无 SSE Accept）同样 404 —— 回归保护
    r2 = await sse_client.get(f"/api/v1/runs/{missing}/events")
    assert r2.status_code == 404
    assert r2.json()["error"]["code"] == "not_found"


async def test_sse_heartbeat_and_keepalive(
    sse_client: AsyncClient, deps_available: bool, monkeypatch: pytest.MonkeyPatch
):
    """g+h) 心跳 ': ping'；非终态 run 无新事件 → 流保持存活不 EOF。"""
    settings = get_settings()
    orig_hb = settings.SSE_HEARTBEAT_SECONDS
    orig_poll = settings.SSE_POLL_SECONDS
    settings.SSE_HEARTBEAT_SECONDS = 1
    settings.SSE_POLL_SECONDS = 0.2
    try:
        run_id = await _mk_run(deps_available, status=TaskStatus.EXECUTING, n_events=1)
        t0 = time.monotonic()
        async with sse_client.stream(
            "GET", f"/api/v1/runs/{run_id}/events", headers=SSE_HEADERS
        ) as r:
            assert r.status_code == 200
            raw, eof = await _read_to_eof(r, timeout=3.0)
        elapsed = time.monotonic() - t0
        assert eof is False, "非终态 run 且无新事件 → 流应保持存活（3s 内不应 EOF）"
        assert elapsed >= 1.0, "连接至少存活 1s 未 EOF"
        assert ": ping" in raw, "静默超过心跳间隔应收到 ': ping' 注释帧"
        assert "event: run.status" in raw, "心跳等待期间历史帧照常送达"
    finally:
        settings.SSE_HEARTBEAT_SECONDS = orig_hb
        settings.SSE_POLL_SECONDS = orig_poll
