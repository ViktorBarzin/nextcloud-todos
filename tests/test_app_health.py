import httpx
from sqlalchemy.ext.asyncio import create_async_engine

from nextcloud_todos.app import create_app
from nextcloud_todos.config import get_settings
from nextcloud_todos.db import metadata


async def test_healthz():
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        r = await c.get("/healthz")
    assert r.status_code == 200


async def test_api_requires_bearer(monkeypatch, tmp_path):
    db = tmp_path / "app.db"
    monkeypatch.setenv("WEBHOOK_BEARER_TOKEN", "tok")
    monkeypatch.setenv("DB_CONNECTION_STRING", f"sqlite+aiosqlite:///{db}")
    get_settings.cache_clear()
    engine = create_async_engine(f"sqlite+aiosqlite:///{db}")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    await engine.dispose()

    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as c:
        unauth = await c.get("/api/events?since=0")
        authed = await c.get("/api/events?since=0", headers={"Authorization": "Bearer tok"})
    assert unauth.status_code == 401  # middleware blocks missing token
    assert authed.status_code == 200  # valid token reaches the route
    assert authed.json() == []
    get_settings.cache_clear()
