from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import pytest_asyncio

from nextcloud_todos.calendars import CalendarResolver
from nextcloud_todos.caldav_client import sweep
from nextcloud_todos.config import get_settings
from nextcloud_todos.db import metadata
from nextcloud_todos.models import Event, SyncState, Todo
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


async def test_sweep_first_run_baselines_without_processing(maker):
    # First sync (no stored token) = a full pull of pre-existing todos. They are
    # baselined (recorded, never acted on), and the token is persisted.
    get_settings.cache_clear()
    resolver = CalendarResolver(allowlist_names=["Personal"])
    resolver._cache = {"personal": "Personal"}
    syncer = FakeSyncer({"personal": ("sync-token-2", [("swept-1.ics", VTODO)])})

    async def fake_triage(*a, **k):
        raise AssertionError("baseline must not classify pre-existing todos")

    await sweep(maker, resolver, syncer, triage_fn=fake_triage)

    async with maker() as s:
        todos = (await s.execute(select(Todo))).scalars().all()
        assert len(todos) == 1 and todos[0].uid == "swept-1"
        assert todos[0].status == "baseline"
        assert (await s.execute(select(Event))).scalars().all() == []  # not processed
        state = (await s.execute(select(SyncState))).scalars().one()
        assert state.sync_token == "sync-token-2"
    get_settings.cache_clear()


async def test_sweep_processes_new_todo_on_later_sync(maker):
    # A todo appearing in a delta AFTER the baseline (token already set) is a
    # genuine new creation -> processed.
    get_settings.cache_clear()
    resolver = CalendarResolver(allowlist_names=["Personal"])
    resolver._cache = {"personal": "Personal"}
    async with maker() as s:  # simulate a prior baseline (token already stored)
        s.add(SyncState(calendar_uri="personal", display_name="Personal", sync_token="t1"))
        await s.commit()
    syncer = FakeSyncer({"personal": ("t2", [("swept-1.ics", VTODO)])})

    async def fake_triage(*a, **k):
        return TriageVerdict(True, "code", "normal", True, "s")

    await sweep(maker, resolver, syncer, triage_fn=fake_triage)

    async with maker() as s:
        todos = (await s.execute(select(Todo))).scalars().all()
        assert len(todos) == 1 and todos[0].uid == "swept-1"
        assert todos[0].status == "awaiting_approval"  # processed (a code todo)
        assert len((await s.execute(select(Event))).scalars().all()) == 1
    get_settings.cache_clear()
