import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Protocol

import httpx
from icalendar import Calendar
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nextcloud_todos.models import SyncState
from nextcloud_todos.orchestrator import process_todo
from nextcloud_todos.parsing import parse_vtodo
from nextcloud_todos.triage import TriageVerdict

log = logging.getLogger(__name__)

TriageFn = Callable[[str, str], Awaitable[TriageVerdict]]


class InvalidSyncToken(Exception):
    """Raised by a syncer when the server rejected the stored sync-token.

    Signals ``sweep`` to drop the token and perform a full resync (covers the
    Nextcloud 418-on-delete case).
    """


class CalDavSyncer(Protocol):
    """Injectable CalDAV access for the reconciliation sweep.

    Implementations return the new sync-token plus the (todo_uri, ics) pairs
    that were created/changed since ``sync_token``. A ``None`` sync_token means
    "full sync from scratch".
    """

    async def changed_todos(
        self, calendar_uri: str, sync_token: str | None
    ) -> tuple[str | None, list[tuple[str, str]]]: ...


class ResolverLike(Protocol):
    def allowlisted_uris(self) -> set[str]: ...
    def display_name(self, calendar_uri: str) -> str: ...


def append_description_note(ics: str, note: str) -> str:
    cal = Calendar.from_ical(ics)
    for comp in cal.walk("VTODO"):
        existing = str(comp.get("DESCRIPTION", ""))
        comp["DESCRIPTION"] = (existing + "\n" if existing else "") + note
        break
    return cal.to_ical().decode()


async def append_note(
    *,
    base_url: str,
    user: str,
    password: str,
    calendar_uri: str,
    todo_uri: str,
    note: str,
    client: httpx.AsyncClient,
) -> None:
    """Read-modify-write the VTODO object, preserving ETag semantics."""
    obj_url = f"{base_url}/remote.php/dav/calendars/{user}/{calendar_uri}/{todo_uri}"
    get = await client.get(obj_url, auth=(user, password))
    get.raise_for_status()
    updated = append_description_note(get.text, note)
    put = await client.put(
        obj_url,
        content=updated,
        auth=(user, password),
        headers={"Content-Type": "text/calendar", "If-Match": get.headers.get("ETag", "*")},
    )
    put.raise_for_status()


async def _sync_calendar(
    session: AsyncSession,
    syncer: CalDavSyncer,
    calendar_uri: str,
    display_name: str,
    *,
    triage_fn: TriageFn,
) -> None:
    state = (
        await session.execute(select(SyncState).where(SyncState.calendar_uri == calendar_uri))
    ).scalar_one_or_none()
    if state is None:
        state = SyncState(calendar_uri=calendar_uri, display_name=display_name)
        session.add(state)
    new_token, changes = await syncer.changed_todos(calendar_uri, state.sync_token)
    state.sync_token = new_token
    state.display_name = display_name
    for _todo_uri, ics in changes:
        parsed = parse_vtodo(ics)
        if parsed is not None:
            await process_todo(session, parsed, calendar_uri, "", triage_fn=triage_fn)
    await session.commit()


async def sweep(
    maker: async_sessionmaker[AsyncSession],
    resolver: ResolverLike,
    syncer: CalDavSyncer,
    *,
    triage_fn: TriageFn,
) -> None:
    """Reconcile each allowlisted calendar via an incremental sync-token pull.

    Scoped strictly to ``resolver.allowlisted_uris()``. Persists ``SyncState``
    per calendar and feeds new/changed VTODOs through ``process_todo``. A failed
    incremental sync (invalid token / Nextcloud 418-on-delete) is retried once
    with a full resync (sync_token reset to ``None``).
    """
    for calendar_uri in sorted(resolver.allowlisted_uris()):
        display_name = resolver.display_name(calendar_uri)
        try:
            async with maker() as session:
                await _sync_calendar(
                    session, syncer, calendar_uri, display_name, triage_fn=triage_fn
                )
        except InvalidSyncToken:
            log.warning("invalid sync token for %s; doing a full resync", calendar_uri)
            async with maker() as session:
                state = (
                    await session.execute(
                        select(SyncState).where(SyncState.calendar_uri == calendar_uri)
                    )
                ).scalar_one_or_none()
                if state is not None:
                    state.sync_token = None
                    await session.commit()
                await _sync_calendar(
                    session, syncer, calendar_uri, display_name, triage_fn=triage_fn
                )


class LiveCalDavSyncer:
    """Production CalDAV syncer over the blocking ``caldav`` client.

    ``caldav`` is synchronous, so each call runs in a worker thread. The
    DAVClient -> principal -> calendar -> objects_by_sync_token path is stable
    across caldav 1.x/3.x. An invalid token (Nextcloud 418-on-delete) surfaces
    as ``InvalidSyncToken`` so ``sweep`` can recover with a full resync.
    """

    def __init__(self, *, base_url: str, user: str, password: str) -> None:
        self._url = f"{base_url}/remote.php/dav/calendars/{user}/"
        self._user = user
        self._password = password

    async def changed_todos(
        self, calendar_uri: str, sync_token: str | None
    ) -> tuple[str | None, list[tuple[str, str]]]:
        return await asyncio.to_thread(self._changed_todos_blocking, calendar_uri, sync_token)

    def _changed_todos_blocking(
        self, calendar_uri: str, sync_token: str | None
    ) -> tuple[str | None, list[tuple[str, str]]]:
        from caldav import DAVClient
        from caldav.lib.error import DAVError

        client = DAVClient(url=self._url, username=self._user, password=self._password)
        calendar = client.principal().calendar(cal_id=calendar_uri)
        try:
            coll = calendar.objects_by_sync_token(sync_token=sync_token, load_objects=True)
        except DAVError as exc:
            raise InvalidSyncToken(str(exc)) from exc
        changes: list[tuple[str, str]] = []
        for obj in coll:
            data = getattr(obj, "data", None)
            if not data or "VTODO" not in data:
                continue
            todo_uri = str(obj.url).rstrip("/").rsplit("/", 1)[-1]
            changes.append((todo_uri, data))
        return str(coll.sync_token) if coll.sync_token else None, changes
