"""eval 域 API 测试（B8）：overview 形状 / models 分组 / skills delta / compression / runs 空表。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.enums import ContextTrigger, TaskStatus
from app.db.session import get_session_factory
from app.models.context import ContextSnapshot
from app.models.misc import ModelUsage
from app.models.skill import Skill, SkillEvaluation
from app.models.task import AgentRun, AgentTask
from app.repositories.users import UsersRepository

pytest_asyncio.fixture(autouse=True)


@pytest_asyncio.fixture(autouse=True)
async def db_stack():
    from app.db.redis import close_redis, init_redis
    from app.db.session import dispose_engine, init_engine

    settings = get_settings()
    init_engine(settings)
    init_redis(settings)
    yield
    await close_redis()
    await dispose_engine()


def _now():
    return datetime.now(timezone.utc)


OVERVIEW_KEYS = {"range", "successRate", "avgDurationMs", "avgCostPerTask", "compressionRate",
                 "trend"}


async def test_overview_shape(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/eval/overview?range=7d")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == OVERVIEW_KEYS
    assert body["range"] == "7d"
    assert 0 <= body["successRate"] <= 1
    assert 0 <= body["compressionRate"] <= 1
    assert len(body["trend"]) == 7
    for p in body["trend"]:
        assert set(p.keys()) == {"date", "overall", "byType"}
        assert set(p["byType"].keys()) == {"created", "failed"}
    r30 = await app_client.get("/api/v1/eval/overview?range=30d")
    assert len(r30.json()["trend"]) == 30
    bad = await app_client.get("/api/v1/eval/overview?range=14d")
    assert bad.status_code == 422
    assert bad.json()["error"]["code"] == "validation_error"


async def test_models_grouping(app_client: AsyncClient, deps_available: bool):
    """两个 model 各一条 run + 真实 model_usage cost 行 → 分组值精确断言。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    suffix = uuid.uuid4().hex[:8]
    model_a, model_b = f"glm-a-{suffix}", f"glm-b-{suffix}"
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title="eval models 种子", description="",
                         model="auto", created_at=_now(), updated_at=_now())
        session.add(task)
        await session.flush()
        run_a = AgentRun(task_id=task.id, status=TaskStatus.COMPLETED, model=model_a,
                         duration_ms=1000, created_at=_now(), updated_at=_now())
        run_b = AgentRun(task_id=task.id, status=TaskStatus.FAILED, model=model_b,
                         duration_ms=3000, created_at=_now(), updated_at=_now())
        session.add_all([run_a, run_b])
        await session.flush()
        session.add(ModelUsage(run_id=run_a.id, task_id=task.id, model=model_a,
                               prompt_tokens=10, completion_tokens=5,
                               cost=Decimal("1.500000"), created_at=_now(), updated_at=_now()))
        session.add(ModelUsage(run_id=run_a.id, task_id=task.id, model=model_a,
                               prompt_tokens=10, completion_tokens=5,
                               cost=Decimal("0.500000"), created_at=_now(), updated_at=_now()))
        session.add(ModelUsage(run_id=run_b.id, task_id=task.id, model=model_b,
                               prompt_tokens=10, completion_tokens=5,
                               cost=Decimal("3.000000"), created_at=_now(), updated_at=_now()))
        await session.commit()

    r = await app_client.get("/api/v1/eval/models?range=7d")
    assert r.status_code == 200
    items = {i["model"]: i for i in r.json()}
    a, b = items[model_a], items[model_b]
    assert set(a.keys()) == {"model", "successRate", "avgDurationMs", "avgCost", "sampleSize"}
    assert a["sampleSize"] == 1
    assert a["successRate"] == 1.0
    assert a["avgDurationMs"] == 1000
    assert a["avgCost"] == pytest.approx(2.0)
    assert b["sampleSize"] == 1
    assert b["successRate"] == 0.0
    assert b["avgDurationMs"] == 3000
    assert b["avgCost"] == pytest.approx(3.0)


async def test_skills_delta(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    factory = get_session_factory()
    async with factory() as session:
        slug = f"eval-skill-{uuid.uuid4().hex[:8]}"
        skill = Skill(name=slug, slug=slug, description="eval delta 种子", category="testing",
                      status="active", created_at=_now(), updated_at=_now())
        session.add(skill)
        await session.flush()
        session.add(SkillEvaluation(skill_id=skill.id, suite="pytest-smoke",
                                    before_score=Decimal("0.4000"), after_score=Decimal("0.8000"),
                                    sample_size=8, created_at=_now(), updated_at=_now()))
        session.add(SkillEvaluation(skill_id=skill.id, suite="pytest-smoke",
                                    before_score=Decimal("0.5000"), after_score=Decimal("0.7000"),
                                    sample_size=4, created_at=_now(), updated_at=_now()))
        await session.commit()
        sid = skill.id

    r = await app_client.get("/api/v1/eval/skills?range=30d")
    assert r.status_code == 200
    mine = [i for i in r.json() if i["skillId"] == sid]
    assert len(mine) == 2
    assert all(set(i.keys()) == {"skillId", "name", "before", "after", "delta", "sampleSize"}
               for i in mine)
    assert mine[0]["name"] == slug
    deltas = sorted(i["delta"] for i in mine)
    assert deltas == [pytest.approx(0.2), pytest.approx(0.4)]
    assert all(i["sampleSize"] in (8, 4) for i in mine)


async def test_compression_non_initial_only(app_client: AsyncClient, deps_available: bool):
    """initial 快照不出现在 compression 列表；非 initial 行字段如实。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title="compression 种子", description="",
                         model="auto", created_at=_now(), updated_at=_now())
        session.add(task)
        await session.flush()
        run = AgentRun(task_id=task.id, status=TaskStatus.EXECUTING, model="glm-5.3",
                       created_at=_now(), updated_at=_now())
        session.add(run)
        await session.flush()
        session.add(ContextSnapshot(run_id=run.id, version=1, is_current=False,
                                    trigger=ContextTrigger.INITIAL, created_at=_now(),
                                    updated_at=_now()))
        session.add(ContextSnapshot(run_id=run.id, version=2, is_current=True,
                                    trigger=ContextTrigger.THRESHOLD,
                                    before_tokens=24000, after_tokens=8000,
                                    compressed_at=_now(), created_at=_now(), updated_at=_now()))
        await session.commit()
        run_id = run.id

    r = await app_client.get("/api/v1/eval/compression?range=7d")
    assert r.status_code == 200
    assert set(r.json().keys()) == {"items"}
    mine = [i for i in r.json()["items"] if i["runId"] == run_id]
    assert len(mine) == 1
    item = mine[0]
    assert set(item.keys()) == {"runId", "version", "trigger", "beforeTokens", "afterTokens",
                                "compressedAt"}
    assert item["version"] == 2
    assert item["trigger"] == "threshold"
    assert item["beforeTokens"] == 24000
    assert item["afterTokens"] == 8000
    assert item["compressedAt"] is not None


async def test_runs_empty_table_honest(app_client: AsyncClient, deps_available: bool):
    """eval_runs 当前为空表 → items=[]、total=0，如实返回。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    r = await app_client.get("/api/v1/eval/runs?page=1")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "size"}
    assert body["items"] == []
    assert body["total"] == 0
    assert body["page"] == 1
