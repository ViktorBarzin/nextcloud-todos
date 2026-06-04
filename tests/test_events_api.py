import httpx
import pytest_asyncio
from fastapi import FastAPI

from nextcloud_todos.api.events import get_session, router
from nextcloud_todos.models import Event, Todo


@pytest_asyncio.fixture
async def client(session):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    session.add(Todo(uid="u", calendar_uri="personal"))
    await session.flush()
    session.add_all(
        [
            Event(todo_id=1, kind="plan", payload={}),
            Event(todo_id=1, kind="answer", payload={}),
        ]
    )
    await session.commit()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_events_since_cursor(client):
    r = await client.get("/api/events?since=0")
    assert r.status_code == 200
    ids = [e["id"] for e in r.json()]
    assert ids == [1, 2]
    r2 = await client.get("/api/events?since=1")
    assert [e["id"] for e in r2.json()] == [2]


async def test_consume_marks_event(client):
    await client.post("/api/events/1/consume")
    r = await client.get("/api/events?since=0")
    assert [e["id"] for e in r.json()] == [2]  # 1 now consumed
