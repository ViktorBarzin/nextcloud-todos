import httpx
import pytest_asyncio
from fastapi import FastAPI

from nextcloud_todos.api.callbacks import get_session, router
from nextcloud_todos.config import get_settings
from nextcloud_todos.hmac_links import sign, verify
from nextcloud_todos.models import Event, Todo


def test_sign_verify_roundtrip():
    s = sign("secret", 7, "approve")
    assert verify("secret", 7, "approve", s) is True
    assert verify("secret", 7, "reject", s) is False
    assert verify("secret", 8, "approve", s) is False


@pytest_asyncio.fixture
async def client(session, monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "secret")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_session] = lambda: session
    session.add(Todo(uid="u", calendar_uri="personal"))
    await session.flush()
    session.add(Event(todo_id=1, kind="plan", payload={}))
    await session.commit()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        yield c
    get_settings.cache_clear()


async def test_approve_records_approval(client):
    sig = sign("secret", 1, "approve")
    r = await client.get(f"/cb/approve/1?sig={sig}")
    assert r.status_code == 200


async def test_bad_sig_rejected(client):
    r = await client.get("/cb/approve/1?sig=deadbeef")
    assert r.status_code == 403
