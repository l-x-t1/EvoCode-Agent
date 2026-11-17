"""临时诊断脚本：定位 SSE 流式 transport 挂点（跑完即删）。"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone

sys.path.insert(0, ".")

from asgi_lifespan import LifespanManager
from httpx import AsyncClient

from app.main import app as fastapi_app
from tests.test_sse_endpoint import StreamingASGITransport, SSE_HEADERS


class DebugTransport(StreamingASGITransport):
    async def handle_async_request(self, request):
        print("TRANSPORT: enter", flush=True)
        resp = await super().handle_async_request(request)
        print("TRANSPORT: exit", flush=True)
        return resp


async def main() -> None:
    from app.core.enums import TaskStatus
    from app.db.session import get_session_factory
    from app.models.execution import AgentExecutionLog
    from app.models.task import AgentRun, AgentTask
    from app.repositories.users import UsersRepository

    async with LifespanManager(fastapi_app):
        async with AsyncClient(
            transport=DebugTransport(fastapi_app), base_url="http://testserver"
        ) as client:
            factory = get_session_factory()
            async with factory() as session:
                user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
                now = datetime.now(timezone.utc)
                task = AgentTask(user_id=user.id, title="diag", description="",
                                 model="auto", status=TaskStatus.EXECUTING,
                                 created_at=now, updated_at=now)
                session.add(task)
                await session.flush()
                run = AgentRun(task_id=task.id, status=TaskStatus.EXECUTING, model="m",
                               started_at=now, created_at=now, updated_at=now)
                session.add(run)
                await session.flush()
                session.add(AgentExecutionLog(run_id=run.id, seq=1, event_type="run.status",
                                              payload={"to": "executing"}, created_at=now))
                await session.commit()
                run_id = run.id

            print("STEP1: entering stream", flush=True)
            cm = client.stream("GET", f"/api/v1/runs/{run_id}/events", headers=SSE_HEADERS)
            r = await asyncio.wait_for(cm.__aenter__(), timeout=10)
            print("STEP2: entered, status=", r.status_code, r.headers.get("content-type"), flush=True)
            try:
                parts: list[bytes] = []

                async def drain() -> None:
                    async for chunk in r.aiter_bytes():
                        parts.append(chunk)

                try:
                    await asyncio.wait_for(drain(), timeout=3)
                    print("STEP3: EOF", flush=True)
                except asyncio.TimeoutError:
                    print("STEP3: still alive after 3s (expected)", flush=True)
            finally:
                print("STEP4: exiting stream context", flush=True)
                await asyncio.wait_for(cm.__aexit__(None, None, None), timeout=10)
                print("STEP5: exited", flush=True)


if __name__ == "__main__":
    import faulthandler
    import os
    import threading

    fh = open("diag_stack.txt", "w")
    faulthandler.dump_traceback_later(40, file=fh, exit=True)  # 40s 后转储全线程栈并强退
    threading.Timer(50, lambda: os._exit(9)).start()
    try:
        asyncio.run(asyncio.wait_for(main(), timeout=35))
        print("DONE-OK", flush=True)
    except BaseException as exc:
        print(f"DONE-EXC: {type(exc).__name__}: {exc}", flush=True)
