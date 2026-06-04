import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.calendars import CalendarResolver
from nextcloud_todos.config import get_settings
from nextcloud_todos.orchestrator import process_todo
from nextcloud_todos.parsing import parse_vtodo

router = APIRouter()
logger = logging.getLogger("uvicorn.error")


def _as_dict(v: object) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


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

    container = _as_dict(await request.json())
    ev = _as_dict(container.get("event", container))
    obj = _as_dict(ev.get("objectData"))
    cal = _as_dict(ev.get("calendarData"))
    # In the webhook_listeners payload `user`/`time` are TOP-LEVEL siblings of
    # `event` (not nested under it); fall back to ev.user for robustness.
    user_obj = _as_dict(container.get("user") or ev.get("user"))
    user_uid = user_obj.get("uid")
    component = obj.get("component") or ""
    calendar_uri = cal.get("uri", "")

    logger.info(
        "nextcloud hook: user=%s component=%s cal_uri=%s allow=%s",
        user_uid, component, calendar_uri, sorted(resolver.allowlisted_uris())
    )

    if user_uid != get_settings().nextcloud_user:
        return {"skipped": "wrong-user"}
    if component.lower() != "vtodo":
        return {"skipped": "not-vtodo"}
    if not resolver.is_allowlisted(calendar_uri):
        return {"skipped": "not-allowlisted"}

    parsed = parse_vtodo(obj.get("calendardata", ""))
    if parsed is None:
        return {"skipped": "no-vtodo-in-ics"}

    triage_fn = request.app.state.triage_fn
    await process_todo(session, parsed, calendar_uri, obj.get("etag", ""), triage_fn=triage_fn)
    logger.info("hook: processed uid=%s cal=%s", parsed.uid, calendar_uri)
    return {"ok": True}
