"""Skill 域 API 测试（B5）：CRUD/版本/差异/回滚/候选审核闸门/事件/评估/用量。"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import get_settings
from app.core.enums import AgentRole, TaskStatus
from app.db.session import get_session_factory
from app.models.skill import Skill, SkillCandidate, SkillVersion
from app.models.task import AgentTask
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


async def _mk_skill(slug: str, versions: list[tuple[str, str]]) -> str:
    """skill + 按序版本（内容递增可 diff）。"""
    factory = get_session_factory()
    async with factory() as session:
        skill = Skill(name=slug, slug=slug, description=f"{slug} 描述",
                      category="testing", status="active",
                      current_version=versions[-1][0] if versions else "0.1.0")
        session.add(skill)
        await session.flush()
        for ver, content in versions:
            session.add(SkillVersion(skill_id=skill.id, version=ver,
                                     changelog=f"{ver} 发布", content=content,
                                     source_type="manual", created_at=_now(),
                                     updated_at=_now()))
        await session.commit()
        return skill.id


async def _mk_candidate(skill_id: str | None, status: str = "pending",
                        proposed: str = "1.1.0") -> str:
    factory = get_session_factory()
    async with factory() as session:
        c = SkillCandidate(skill_id=skill_id, kind="revise", proposed_version=proposed,
                           summary="候选摘要：增强 -k 过滤", proposed_content="v1.1.0 新内容",
                           evidence_task_ids=[], evaluation={"suite": "smoke", "before": 0.8,
                                                            "after": 0.9, "sampleSize": 8},
                           status=status, created_at=_now(), updated_at=_now())
        session.add(c)
        await session.commit()
        return c.id


async def _mk_task_using_skill(skill_id: str) -> str:
    factory = get_session_factory()
    async with factory() as session:
        user = await UsersRepository(session).get_or_create_dev_user("dev@evocode.local")
        task = AgentTask(user_id=user.id, title="使用该技能的任务", description="",
                         model="auto", status=TaskStatus.COMPLETED,
                         skill_ids=[skill_id], created_at=_now(), updated_at=_now())
        session.add(task)
        await session.commit()
        return task.id


# ── 查询 ─────────────────────────────────────────────

async def test_list_and_get_skill_contract(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-list", [("1.0.0", "内容")])
    r = await app_client.get("/api/v1/skills")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "size"}
    mine = next(s for s in body["items"] if s["id"] == sid)
    assert set(mine.keys()) == {"id", "name", "slug", "description", "category", "status",
                                "currentVersion", "metrics", "createdAt", "updatedAt"}
    assert set(mine["metrics"].keys()) == {"usageCount", "successRate", "evolutions",
                                           "avgTokenDelta"}
    r2 = await app_client.get(f"/api/v1/skills/{sid}")
    assert r2.status_code == 200 and r2.json()["slug"] == "b5-list"
    r3 = await app_client.get("/api/v1/skills?q=b5-list&category=testing&status=active")
    assert any(s["id"] == sid for s in r3.json()["items"])
    r4 = await app_client.get("/api/v1/skills/skill_notexist000000000000000")
    assert r4.status_code == 404 and r4.json()["error"]["code"] == "not_found"


async def test_versions_and_diff(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-diff", [("1.0.0", "第一行\n第二行"),
                                      ("1.1.0", "第一行\n第二行改")])
    r = await app_client.get(f"/api/v1/skills/{sid}/versions")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert {v["version"] for v in items} == {"1.0.0", "1.1.0"}
    assert all(set(v.keys()) == {"id", "skillId", "version", "changelog", "content",
                                "source", "evalScore", "createdAt"} for v in items)
    d = await app_client.get(f"/api/v1/skills/{sid}/versions/1.0.0/diff/1.1.0")
    assert d.status_code == 200
    diff = d.json()
    assert diff["fromVersion"] == "1.0.0" and diff["toVersion"] == "1.1.0"
    assert diff["files"][0]["additions"] == 1 and diff["files"][0]["deletions"] == 1
    assert "第二行改" in diff["files"][0]["patch"]
    d2 = await app_client.get(f"/api/v1/skills/{sid}/versions/9.9.9/diff/1.1.0")
    assert d2.status_code == 404


async def test_rollback_creates_new_version_and_event(app_client: AsyncClient, deps_available: bool):
    """回滚 = 新版本发布目标内容；版本历史完整；rolled_back 事件可派生。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-rollback", [("1.0.0", "原始内容"), ("1.1.0", "被改坏的内容")])
    r = await app_client.post(f"/api/v1/skills/{sid}/rollback",
                              json={"targetVersion": "1.0.0", "reason": "1.1.0 质量回归"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currentVersion"] == "1.1.1"  # 当前版本 patch+1
    vs = (await app_client.get(f"/api/v1/skills/{sid}/versions")).json()["items"]
    assert len(vs) == 3
    rollback_row = next(v for v in vs if v["version"] == "1.1.1")
    assert rollback_row["content"] == "原始内容"      # 内容回到目标版本
    ev = (await app_client.get(f"/api/v1/skills/{sid}/versions")).json()
    events = (await app_client.get("/api/v1/skills/events?skillId=" + sid)).json()["items"]
    assert any(e["type"] == "rolled_back" for e in events)
    assert ev is not None


# ── 候选与审核闸门 ────────────────────────────────────

async def test_candidate_review_gate(app_client: AsyncClient, deps_available: bool):
    """审核闸门核心：approved → 发布正式版本 + evolutions+1；重复审核 409。"""
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-gate", [("1.0.0", "初始内容")])
    before = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert before["currentVersion"] == "1.0.0" and before["metrics"]["evolutions"] == 0
    cid = await _mk_candidate(sid, status="pending", proposed="1.1.0")

    # pending 候选存在期间：正式版本纹丝不动（未审核候选不覆盖正式版）
    mid = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert mid["currentVersion"] == "1.0.0"

    r = await app_client.post(f"/api/v1/skills/candidates/{cid}/review",
                              json={"decision": "approved", "comment": "评测达标"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    after = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert after["currentVersion"] == "1.1.0"           # 审核通过才发布
    assert after["metrics"]["evolutions"] == 1
    vs = (await app_client.get(f"/api/v1/skills/{sid}/versions")).json()["items"]
    assert any(v["version"] == "1.1.0" and v["source"]["type"] == "evolution" for v in vs)
    # 重复审核 → 409 终态守卫
    r2 = await app_client.post(f"/api/v1/skills/candidates/{cid}/review",
                               json={"decision": "rejected"})
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "conflict"


async def test_candidate_rejected_publishes_nothing(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-reject", [("1.0.0", "内容")])
    cid = await _mk_candidate(sid, status="pending", proposed="2.0.0")
    r = await app_client.post(f"/api/v1/skills/candidates/{cid}/review",
                              json={"decision": "rejected", "comment": "评测未达标"})
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"
    after = (await app_client.get(f"/api/v1/skills/{sid}")).json()
    assert after["currentVersion"] == "1.0.0"            # 拒绝不产生版本
    vs = (await app_client.get(f"/api/v1/skills/{sid}/versions")).json()["items"]
    assert all(v["version"] != "2.0.0" for v in vs)


async def test_review_invalid_decision_and_404(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-invalid", [("1.0.0", "x")])
    cid = await _mk_candidate(sid, status="pending")
    r = await app_client.post(f"/api/v1/skills/candidates/{cid}/review",
                              json={"decision": "maybe"})
    assert r.status_code == 422
    r2 = await app_client.post("/api/v1/skills/candidates/cand_notexist0000000000000/review",
                               json={"decision": "approved"})
    assert r2.status_code == 404


async def test_candidates_list_by_status(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-candlist", [("1.0.0", "x")])
    cid = await _mk_candidate(sid, status="pending")
    r = await app_client.get("/api/v1/skills/candidates?status=pending")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"items", "total", "page", "size"}
    mine = next((c for c in body["items"] if c["id"] == cid), None)
    assert mine is not None
    assert set(mine.keys()) == {"id", "skillId", "kind", "proposedVersion", "summary",
                                "proposedContent", "evidenceTaskIds", "evaluation",
                                "status", "createdAt"}
    assert mine["evaluation"]["suite"] == "smoke"


# ── 评估 / 用量 / 事件 ────────────────────────────────

async def test_evaluations_and_usages(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-eval", [("1.0.0", "x")])
    task_id = await _mk_task_using_skill(sid)
    factory = get_session_factory()
    async with factory() as session:
        from app.models.skill import SkillEvaluation

        skill = await session.get(Skill, sid)
        session.add(SkillEvaluation(skill_id=sid, version_id=None, suite="pytest-smoke",
                                    before_score=0.8, after_score=0.9, sample_size=10,
                                    created_at=_now()))
        skill.usage_count += 1
        skill.success_rate = 0.9
        await session.commit()
    r = await app_client.get(f"/api/v1/skills/{sid}/evaluations")
    assert r.status_code == 200
    ev = r.json()["items"][0]
    assert ev["suite"] == "pytest-smoke" and ev["after"] == 0.9 and ev["sampleSize"] == 10
    u = await app_client.get(f"/api/v1/skills/{sid}/usages")
    assert u.status_code == 200
    items = u.json()["items"]
    assert any(t["taskId"] == task_id for t in items)
    assert items[0]["status"] == "completed"


async def test_events_list(app_client: AsyncClient, deps_available: bool):
    if not deps_available:
        pytest.skip("PG/Redis 未启动")
    sid = await _mk_skill("b5-events", [("1.0.0", "x")])
    await _mk_candidate(sid, status="pending", proposed="1.1.0")
    r = await app_client.get("/api/v1/skills/events")
    assert r.status_code == 200
    items = r.json()["items"]
    types = {e["type"] for e in items}
    assert {"created", "proposed"} <= types
    r2 = await app_client.get("/api/v1/skills/events?skillId=" + sid)
    assert all(e["skillId"] == sid for e in r2.json()["items"])
