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
    ev = body.get("event", body) if isinstance(body, dict) else {}
    obj = ev.get("objectData", {}) if isinstance(ev, dict) else {}
    cal = ev.get("calendarData", {}) if isinstance(ev, dict) else {}
    user_uid = (ev.get("user") or {}).get("uid") if isinstance(ev, dict) else None
    component = obj.get("component") if isinstance(obj, dict) else None
    calendar_uri = cal.get("uri", "") if isinstance(cal, dict) else ""

    logger.info(
        "nextcloud hook: body_keys=%s ev_keys=%s obj_keys=%s cal_keys=%s "
        "user=%s component=%s cal_uri=%s resolver_allow=%s",
        list(body.keys()) if isinstance(body, dict) else type(body).__name__,
        list(ev.keys()) if isinstance(ev, dict) else None,
        list(obj.keys()) if isinstance(obj, dict) else None,
        list(cal.keys()) if isinstance(cal, dict) else None,
        user_uid,
        component,
        calendar_uri,
        sorted(resolver.allowlisted_uris()),
    )

    if user_uid != get_settings().nextcloud_user:
        logger.info("hook skip: wrong-user (%s)", user_uid)
        return {"skipped": "wrong-user"}
    if (component or "").lower() != "vtodo":
        logger.info("hook skip: not-vtodo (%s)", component)
        return {"skipped": "not-vtodo"}
    if not resolver.is_allowlisted(calendar_uri):
        logger.info("hook skip: not-allowlisted (%s)", calendar_uri)
        return {"skipped": "not-allowlisted"}

    parsed = parse_vtodo(obj.get("calendardata", ""))
    if parsed is None:
        logger.info("hook skip: no-vtodo-in-ics")
        return {"skipped": "no-vtodo-in-ics"}

    triage_fn = request.app.state.triage_fn
    await process_todo(session, parsed, calendar_uri, obj.get("etag", ""), triage_fn=triage_fn)
    logger.info("hook: processed uid=%s cal=%s", parsed.uid, calendar_uri)
    return {"ok": True}
