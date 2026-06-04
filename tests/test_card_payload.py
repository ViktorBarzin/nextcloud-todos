import httpx
import pytest_asyncio
from fastapi import FastAPI

from nextcloud_todos.api.events import get_session, router
from nextcloud_todos.config import get_settings
from nextcloud_todos.hmac_links import verify
from nextcloud_todos.models import Event, Todo


@pytest_asyncio.fixture
async def client_with_plan_event(session, monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "secret")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    session.add(Todo(uid="u", calendar_uri="personal", summary="Add a Grafana panel"))
    await session.flush()
    session.add(Event(todo_id=1, kind="plan", payload={"plan": "PLAN: edit X", "cost_usd": 3.0}))
    await session.commit()
    latest = (await session.get(Event, 1)).id
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        yield c, latest
    get_settings.cache_clear()


async def test_card_payload_has_signed_links(client_with_plan_event):
    c, latest_event_id = client_with_plan_event
    r = await c.get("/api/get/1")
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == "Add a Grafana panel"
    assert "plan" in body
    assert body["plan"] == "PLAN: edit X"
    assert verify("secret", latest_event_id, "approve", body["links"]["approve"].split("sig=")[1])
    assert verify("secret", latest_event_id, "reject", body["links"]["reject"].split("sig=")[1])
    assert verify("secret", latest_event_id, "refine", body["links"]["refine"].split("sig=")[1])


async def test_answer_only_todo_omits_plan(client_with_plan_event):
    c, _ = client_with_plan_event
    r = await c.get("/api/get/1")
    body = r.json()
    # the plan event carries cost_usd; surface it for the plan card
    assert body["cost_usd"] == 3.0


async def test_get_unknown_todo_404(client_with_plan_event):
    c, _ = client_with_plan_event
    r = await c.get("/api/get/999")
    assert r.status_code == 404
