from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.config import get_settings
from nextcloud_todos.hmac_links import verify
from nextcloud_todos.models import Approval, Event

router = APIRouter(prefix="/cb")


async def get_session() -> AsyncSession:
    raise NotImplementedError


async def _record(
    session: AsyncSession,
    event_id: int,
    decision: str,
    sig: str,
    steer: str | None = None,
) -> Approval:
    secret = get_settings().hmac_secret
    if not verify(secret, event_id, decision, sig):
        raise HTTPException(status_code=403, detail="bad signature")
    if await session.get(Event, event_id) is None:
        raise HTTPException(status_code=404, detail="no such event")
    ap = Approval(event_id=event_id, decision=decision, sig=sig, steer_prompt=steer)
    session.add(ap)
    await session.commit()
    return ap


@router.get("/approve/{event_id}", response_class=HTMLResponse)
async def approve(
    event_id: int, sig: str, request: Request, session: AsyncSession = Depends(get_session)
) -> str:
    ap = await _record(session, event_id, "approve", sig)
    if hasattr(request.app.state, "on_approved"):
        await request.app.state.on_approved(ap.id)
    return "<h3>Approved ✅ — execution queued.</h3>"


@router.get("/reject/{event_id}", response_class=HTMLResponse)
async def reject(
    event_id: int, sig: str, session: AsyncSession = Depends(get_session)
) -> str:
    await _record(session, event_id, "reject", sig)
    return "<h3>Rejected ❌</h3>"


@router.get("/refine/{event_id}", response_class=HTMLResponse)
async def refine_form(event_id: int, sig: str) -> str:
    if not verify(get_settings().hmac_secret, event_id, "refine", sig):
        raise HTTPException(status_code=403, detail="bad signature")
    return f"""<form method="post" action="/cb/refine/{event_id}?sig={sig}">
    <textarea name="steer" rows="6" cols="60" placeholder="Extra instructions..."></textarea><br>
    <button type="submit">Approve with notes ✅</button></form>"""


@router.post("/refine/{event_id}", response_class=HTMLResponse)
async def refine_submit(
    event_id: int,
    sig: str,
    request: Request,
    steer: str = Form(""),
    session: AsyncSession = Depends(get_session),
) -> str:
    ap = await _record(session, event_id, "refine", sig, steer=steer)
    if hasattr(request.app.state, "on_approved"):
        await request.app.state.on_approved(ap.id)
    return "<h3>Approved with notes ✅ — execution queued.</h3>"
