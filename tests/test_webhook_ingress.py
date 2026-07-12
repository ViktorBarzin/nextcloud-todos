import json
from pathlib import Path

import httpx
import pytest_asyncio
from fastapi import FastAPI

from nextcloud_todos.api.webhook import get_resolver, get_session, router
from nextcloud_todos.calendars import CalendarResolver
from nextcloud_todos.config import get_settings
from nextcloud_todos.models import Todo

FX = Path(__file__).parent / "fixtures"


@pytest_asyncio.fixture
async def client(session, monkeypatch):
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "tok")
    get_settings.cache_clear()
    resolver = CalendarResolver(allowlist_names=["Personal"])
    resolver._cache = {"personal": "Personal", "A63E": "To Buy"}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_resolver] = lambda: resolver

    async def fake_triage(*a, **k):
        from nextcloud_todos.triage import TriageVerdict

        return TriageVerdict(True, "code", "normal", True, "s")

    app.state.triage_fn = fake_triage
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, session
    get_settings.cache_clear()


async def test_personal_vtodo_is_processed(client):
    c, session = client
    body = json.loads((FX / "webhook_created.json").read_text())
    r = await c.post("/nextcloud/hook", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    todos = (await session.execute(Todo.__table__.select())).fetchall()
    assert len(todos) == 1 and todos[0].uid == "abc-123"


async def test_missing_bearer_rejected(client):
    c, _ = client
    r = await c.post("/nextcloud/hook", json={}, headers={})
    assert r.status_code == 401


async def test_non_allowlisted_list_dropped(client):
    c, session = client
    body = json.loads((FX / "webhook_created.json").read_text())
    body["event"]["calendarData"]["uri"] = "A63E"  # "To Buy"
    r = await c.post("/nextcloud/hook", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200 and r.json()["skipped"] == "not-allowlisted"
    assert (await session.execute(Todo.__table__.select())).fetchall() == []


async def test_updated_event_skipped(client):
    # Only newly-created todos trigger; an Updated event must be ignored.
    c, session = client
    body = json.loads((FX / "webhook_created.json").read_text())
    body["event"]["class"] = "OCP\\Calendar\\Events\\CalendarObjectUpdatedEvent"
    r = await c.post("/nextcloud/hook", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200 and r.json()["skipped"] == "not-created"
    assert (await session.execute(Todo.__table__.select())).fetchall() == []


@pytest_asyncio.fixture
async def ideation_client(session, monkeypatch):
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "tok")
    get_settings.cache_clear()
    resolver = CalendarResolver(
        allowlist_names=["Personal"], ideation_names=["Noticing File"]
    )
    resolver._cache = {"personal": "Personal", "NF01": "Noticing File"}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_resolver] = lambda: resolver

    async def fail_triage(*a, **k):
        raise AssertionError("ideation lane must not classify")

    app.state.triage_fn = fail_triage
    ideated: list[int] = []
    app.state.ideate_fn = ideated.append
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, session, ideated
    get_settings.cache_clear()


async def test_ideation_list_vtodo_dispatches_ideation(ideation_client):
    c, session, ideated = ideation_client
    body = json.loads((FX / "webhook_created.json").read_text())
    body["event"]["calendarData"]["uri"] = "NF01"
    r = await c.post("/nextcloud/hook", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200 and r.json() == {"ok": True}
    todos = (await session.execute(Todo.__table__.select())).fetchall()
    assert len(todos) == 1
    assert todos[0].status == "ideating"
    assert todos[0].todo_uri == "todo-1.ics"
    assert ideated == [todos[0].id]


async def test_agent_lane_persists_todo_uri_from_payload(client):
    c, session = client
    body = json.loads((FX / "webhook_created.json").read_text())
    r = await c.post("/nextcloud/hook", json=body, headers={"Authorization": "Bearer tok"})
    assert r.status_code == 200
    todos = (await session.execute(Todo.__table__.select())).fetchall()
    assert todos[0].todo_uri == "todo-1.ics"
