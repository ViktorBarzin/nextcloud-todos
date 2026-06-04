import asyncio
import contextlib
import hmac
import logging
from collections.abc import AsyncIterator, Awaitable, Callable

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nextcloud_todos import caldav_client
from nextcloud_todos.api import callbacks, events, webhook
from nextcloud_todos.calendars import CalendarResolver
from nextcloud_todos.claude_agent import AgentResult, submit_and_wait
from nextcloud_todos.config import get_settings
from nextcloud_todos.models import Approval, Event
from nextcloud_todos.runner import AgentFn, run_execute
from nextcloud_todos.triage import TriageVerdict, triage

log = logging.getLogger(__name__)

SessionMaker = async_sessionmaker[AsyncSession]
TriageFn = Callable[[str, str], Awaitable[TriageVerdict]]
SWEEP_INTERVAL_SECONDS = 300


async def handle_approval(approval_id: int, maker: SessionMaker, agent_fn: AgentFn) -> None:
    """Approval -> Event -> Todo, run the execute pass, mark the approval consumed.

    Runs in a fresh session so it is independent of the request-scoped session
    that recorded the approval.
    """
    async with maker() as session:
        approval = await session.get(Approval, approval_id)
        if approval is None or approval.consumed:
            return
        event = await session.get(Event, approval.event_id)
        if event is None:
            return
        await run_execute(
            session, todo_id=event.todo_id, steer=approval.steer_prompt, agent_fn=agent_fn
        )
        approval.consumed = True
        await session.commit()


async def _sweep_loop(
    maker: SessionMaker,
    resolver: CalendarResolver,
    syncer: caldav_client.CalDavSyncer,
    triage_fn: TriageFn,
) -> None:
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        with contextlib.suppress(Exception):
            await caldav_client.sweep(maker, resolver, syncer, triage_fn=triage_fn)


def _bearer_error(authorization: str | None) -> str | None:
    """Return an error string if the bearer header is invalid, else ``None``.

    Returns (rather than raises) because an ``HTTPException`` raised inside a
    Starlette ``BaseHTTPMiddleware`` is not caught by FastAPI's handler — the
    middleware must emit the response itself.
    """
    expected = get_settings().webhook_bearer_token
    if not expected:
        return "service unauthenticated"
    if not authorization or not authorization.startswith("Bearer "):
        return "missing bearer token"
    token = authorization.removeprefix("Bearer ")
    if not hmac.compare_digest(token, expected):
        return "invalid token"
    return None


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="nextcloud-todos")

    # Durable resources are created here (not in lifespan) so dependency
    # overrides and app.state are wired even when the ASGI lifespan protocol
    # is not run — e.g. httpx.ASGITransport in tests. The lifespan still does
    # the best-effort calendar refresh and owns the sweep task + teardown.
    engine = create_async_engine(s.db_connection_string)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    client = httpx.AsyncClient(timeout=300.0)
    resolver = CalendarResolver(
        base_url=s.nextcloud_base_url,
        user=s.nextcloud_user,
        password=s.caldav_app_password,
        allowlist_names=s.list_allowlist,
    )

    async def _session() -> AsyncIterator[AsyncSession]:
        async with maker() as sess:
            yield sess

    app.dependency_overrides[webhook.get_session] = _session
    app.dependency_overrides[events.get_session] = _session
    app.dependency_overrides[callbacks.get_session] = _session
    app.dependency_overrides[webhook.get_resolver] = lambda: resolver

    async def triage_fn(summary: str, description: str) -> TriageVerdict:
        return await triage(
            summary,
            description,
            client=client,
            llama_url=s.llama_swap_url,
            model=s.llama_swap_model,
        )

    app.state.triage_fn = triage_fn

    async def exec_agent_fn(**kwargs: object) -> AgentResult:
        return await submit_and_wait(
            base_url=s.claude_agent_url,
            token=s.claude_agent_token,
            client=client,
            **kwargs,  # type: ignore[arg-type]
        )

    async def on_approved(approval_id: int) -> None:
        await handle_approval(approval_id, maker, exec_agent_fn)

    app.state.on_approved = on_approved

    syncer = caldav_client.LiveCalDavSyncer(
        base_url=s.nextcloud_base_url, user=s.nextcloud_user, password=s.caldav_app_password
    )

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        with contextlib.suppress(Exception):
            await resolver.refresh(client)
        sweep_task = asyncio.create_task(_sweep_loop(maker, resolver, syncer, triage_fn))
        try:
            yield
        finally:
            sweep_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sweep_task
            await client.aclose()
            await engine.dispose()

    app.router.lifespan_context = lifespan

    @app.middleware("http")
    async def auth_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith("/api/"):
            err = _bearer_error(request.headers.get("authorization"))
            if err is not None:
                return JSONResponse({"detail": err}, status_code=401)
        return await call_next(request)

    app.include_router(webhook.router)
    app.include_router(events.router)
    app.include_router(callbacks.router)

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    return app
