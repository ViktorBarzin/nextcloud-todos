from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.calendars import CalendarResolver
from nextcloud_todos.config import get_settings
from nextcloud_todos.orchestrator import process_todo
from nextcloud_todos.parsing import parse_vtodo

router = APIRouter()


async def get_session() -> AsyncSession:
    raise NotImplementedError


def get_resolver() -> CalendarResolver:
    raise NotImplementedError


@router.post("/nextcloud/hook")
async def hook(
    request: Request,
    authorization: str = Header(default=""),
    session: AsyncSession = Depends(get_session),
    resolver: CalendarResolver = Depends(get_resolver),
) -> dict[str, Any]:
    expected = f"Bearer {get_settings().webhook_bearer_token}"
    if authorization != expected:
        raise HTTPException(status_code=401, detail="bad token")

    body = await request.json()
    ev = body.get("event", body)
    obj = ev.get("objectData", {})
    cal = ev.get("calendarData", {})

    if ev.get("user", {}).get("uid") != get_settings().nextcloud_user:
        return {"skipped": "wrong-user"}
    if (obj.get("component") or "").lower() != "vtodo":
        return {"skipped": "not-vtodo"}
    calendar_uri = cal.get("uri", "")
    if not resolver.is_allowlisted(calendar_uri):
        return {"skipped": "not-allowlisted"}

    parsed = parse_vtodo(obj.get("calendardata", ""))
    if parsed is None:
        return {"skipped": "no-vtodo-in-ics"}

    triage_fn = request.app.state.triage_fn
    await process_todo(session, parsed, calendar_uri, obj.get("etag", ""), triage_fn=triage_fn)
    return {"ok": True}
