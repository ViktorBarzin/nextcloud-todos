from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.models import Event

router = APIRouter(prefix="/api")


async def get_session() -> AsyncSession:  # overridden in app.py via dependency_overrides
    raise NotImplementedError


@router.get("/events")
async def list_events(
    since: int = 0, limit: int = 50, session: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    rows = (
        (
            await session.execute(
                select(Event)
                .where(Event.id > since, Event.consumed_at.is_(None))
                .order_by(Event.id)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {"id": e.id, "todo_id": e.todo_id, "kind": e.kind, "payload": e.payload} for e in rows
    ]


@router.post("/events/{event_id}/consume")
async def consume(event_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    e = await session.get(Event, event_id)
    if e and e.consumed_at is None:
        e.consumed_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True}
