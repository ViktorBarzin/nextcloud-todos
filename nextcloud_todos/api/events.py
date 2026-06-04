from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.config import get_settings
from nextcloud_todos.hmac_links import sign
from nextcloud_todos.models import Event, Todo

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
    return [{"id": e.id, "todo_id": e.todo_id, "kind": e.kind, "payload": e.payload} for e in rows]


@router.post("/events/{event_id}/consume")
async def consume(event_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, bool]:
    e = await session.get(Event, event_id)
    if e and e.consumed_at is None:
        e.consumed_at = datetime.now(timezone.utc)
        await session.commit()
    return {"ok": True}


async def _latest_event(session: AsyncSession, todo_id: int, kind: str) -> Event | None:
    return (
        await session.execute(
            select(Event)
            .where(Event.todo_id == todo_id, Event.kind == kind)
            .order_by(Event.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _signed_links(event_id: int, secret: str, base_url: str) -> dict[str, str]:
    base = base_url.rstrip("/")
    return {
        action: f"{base}/cb/{action}/{event_id}?sig={sign(secret, event_id, action)}"
        for action in ("approve", "reject", "refine")
    }


@router.get("/get/{todo_id}")
async def get_card(todo_id: int, session: AsyncSession = Depends(get_session)) -> dict[str, Any]:
    """Assemble the Telegram-card payload for a todo.

    Returns the todo ``summary``, the latest ``plan``/``answer`` event payload
    fields, and (when a plan event exists) signed approve/reject/refine links
    keyed off the latest plan event id. The links are HMAC-signed with the same
    secret the ``/cb`` callbacks verify against.
    """
    todo = await session.get(Todo, todo_id)
    if todo is None:
        raise HTTPException(status_code=404, detail="no such todo")

    payload: dict[str, Any] = {"todo_id": todo.id, "summary": todo.summary}

    answer = await _latest_event(session, todo_id, "answer")
    if answer is not None:
        payload["result"] = answer.payload.get("result", "")

    plan = await _latest_event(session, todo_id, "plan")
    if plan is not None:
        payload["plan"] = plan.payload.get("plan", "")
        payload["cost_usd"] = plan.payload.get("cost_usd")
        s = get_settings()
        payload["links"] = _signed_links(plan.id, s.hmac_secret, s.callback_base_url)

    return payload
