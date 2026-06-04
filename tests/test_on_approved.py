from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import pytest_asyncio

from nextcloud_todos.app import handle_approval
from nextcloud_todos.claude_agent import AgentResult
from nextcloud_todos.config import get_settings
from nextcloud_todos.db import metadata
from nextcloud_todos.models import Approval, Event, Run, Todo


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_approval_triggers_execute_run(maker):
    get_settings.cache_clear()
    async with maker() as s:
        todo = Todo(uid="exec-1", calendar_uri="personal", summary="add a panel")
        s.add(todo)
        await s.flush()
        ev = Event(todo_id=todo.id, kind="plan", payload={"plan": "edit X"})
        s.add(ev)
        await s.flush()
        ap = Approval(event_id=ev.id, decision="approve", sig="sig", steer_prompt="be careful")
        s.add(ap)
        await s.commit()
        approval_id = ap.id

    captured = {}

    async def fake_agent(**k):
        captured.update(k)
        return AgentResult("completed", "executed end to end", 7.5, "job-x")

    await handle_approval(approval_id, maker, fake_agent)

    async with maker() as s:
        runs = (await s.execute(select(Run))).scalars().all()
        assert len(runs) == 1
        assert runs[0].phase == "execute"
        assert runs[0].status == "completed"
        ap2 = await s.get(Approval, approval_id)
        assert ap2.consumed is True

    # steer prompt from the approval reached the agent
    assert "be careful" in captured["prompt"]
    assert captured["agent"] == get_settings().exec_agent
    get_settings.cache_clear()
