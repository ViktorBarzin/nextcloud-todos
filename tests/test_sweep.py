from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import pytest_asyncio

from nextcloud_todos.calendars import CalendarResolver
from nextcloud_todos.caldav_client import sweep
from nextcloud_todos.config import get_settings
from nextcloud_todos.db import metadata
from nextcloud_todos.models import SyncState, Todo
from nextcloud_todos.triage import TriageVerdict

VTODO = (
    "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nUID:swept-1\n"
    "SUMMARY:Swept task\nEND:VTODO\nEND:VCALENDAR"
)


class FakeSyncer:
    """Records which calendars were synced and returns canned changes."""

    def __init__(self, changes):
        self._changes = changes  # {calendar_uri: (new_token, [(todo_uri, ics), ...])}
        self.synced = []

    async def changed_todos(self, calendar_uri, sync_token):
        self.synced.append(calendar_uri)
        return self._changes.get(calendar_uri, (sync_token, []))


@pytest_asyncio.fixture
async def maker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_sweep_only_syncs_allowlisted_calendars(maker):
    get_settings.cache_clear()
    resolver = CalendarResolver(allowlist_names=["Personal"])
    resolver._cache = {"personal": "Personal", "A63E": "To Buy"}
    syncer = FakeSyncer({})

    async def fake_triage(*a, **k):
        return TriageVerdict(True, "code", "normal", True, "s")

    await sweep(maker, resolver, syncer, triage_fn=fake_triage)
    assert syncer.synced == ["personal"]  # "A63E" (To Buy) is not allowlisted
    get_settings.cache_clear()


async def test_sweep_new_todo_creates_row_and_persists_token(maker):
    get_settings.cache_clear()
    resolver = CalendarResolver(allowlist_names=["Personal"])
    resolver._cache = {"personal": "Personal"}
    syncer = FakeSyncer({"personal": ("sync-token-2", [("swept-1.ics", VTODO)])})

    async def fake_triage(*a, **k):
        return TriageVerdict(True, "code", "normal", True, "s")

    await sweep(maker, resolver, syncer, triage_fn=fake_triage)

    async with maker() as s:
        todos = (await s.execute(select(Todo))).scalars().all()
        assert len(todos) == 1
        assert todos[0].uid == "swept-1"
        assert todos[0].calendar_uri == "personal"
        states = (await s.execute(select(SyncState))).scalars().all()
        assert len(states) == 1
        assert states[0].calendar_uri == "personal"
        assert states[0].sync_token == "sync-token-2"
    get_settings.cache_clear()
