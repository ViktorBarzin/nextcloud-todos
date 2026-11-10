"""Product events and OTel JSON log lines (docs/adr/0001).

`FakeEvents` replaces Segment's client, so nothing here reaches the network.
"""

from __future__ import annotations

import io
import json
import logging

import httpx
import pytest
import viktorbarzin_telemetry as telemetry
from fastapi import FastAPI

from nextcloud_todos import json_logs, product_events
from nextcloud_todos.api import callbacks, events
from nextcloud_todos.app import handle_approval
from nextcloud_todos.claude_agent import AgentResult
from nextcloud_todos.config import get_settings
from nextcloud_todos.hmac_links import sign
from nextcloud_todos.ideation import run_ideation
from nextcloud_todos.models import Approval, Event, Todo
from nextcloud_todos.orchestrator import process_todo
from nextcloud_todos.parsing import ParsedTodo
from nextcloud_todos.triage import TriageVerdict
from tests.telemetry_fakes import PRODUCTION, FakeEvents

PERSON = PRODUCTION["TELEMETRY_PERSON_ID"]
SECRET_TEXT = "ring the dentist about the crown"


@pytest.fixture
def sent():
    fake = FakeEvents()
    assert product_events.start(PRODUCTION, client=fake) is True
    yield fake
    product_events.stop()


@pytest.fixture
def stream():
    buffer = io.StringIO()
    json_logs.setup({"TELEMETRY_ENVIRONMENT": "production", "APP_VERSION": "abc12345"}, stream=buffer)
    yield buffer
    json_logs.setup({})


def _parsed(uid: str = "u1") -> ParsedTodo:
    return ParsedTodo(uid=uid, summary=SECRET_TEXT, description=SECRET_TEXT, due=None, status="")


def _triage(kind: str, *, actionable: bool = True, approval: bool = False):
    async def fn(summary: str, description: str) -> TriageVerdict:
        return TriageVerdict(actionable, kind, "high", approval, SECRET_TEXT)

    return fn


def _no_text(fake: FakeEvents) -> None:
    assert "dentist" not in json.dumps([s.properties for s in fake.tracks])


# ------------------------------------------------------------------ switches


def test_every_event_name_meets_the_standard():
    assert len(set(product_events.EVENTS)) == len(product_events.EVENTS)
    for name in product_events.EVENTS:
        assert telemetry.event_name_problem(name) is None, name


def test_nothing_is_sent_without_a_write_key():
    env = {k: v for k, v in PRODUCTION.items() if k != "TELEMETRY_WRITE_KEY"}
    assert product_events.start(env, client=FakeEvents()) is False


def test_nothing_is_sent_outside_production():
    env = {**PRODUCTION, "TELEMETRY_ENVIRONMENT": "dev"}
    assert product_events.start(env, client=FakeEvents()) is False


def test_production_without_a_host_sends_nothing_and_still_starts():
    env = {k: v for k, v in PRODUCTION.items() if k != "TELEMETRY_HOST"}
    assert product_events.start(env) is False


def test_every_event_names_the_list_owner(sent):
    product_events.card_delivered("plan", wait_s=3)
    [event] = sent.tracks
    assert event.user_id == PERSON
    assert event.anonymous_id == product_events.OWNER_ANONYMOUS_ID


def test_without_a_person_id_events_carry_only_the_owner_anonymous_id():
    fake = FakeEvents()
    env = {k: v for k, v in PRODUCTION.items() if k != "TELEMETRY_PERSON_ID"}
    assert product_events.start(env, client=fake) is True
    product_events.card_delivered("plan", wait_s=3)
    product_events.stop()
    [event] = fake.tracks
    assert event.user_id is None
    assert event.anonymous_id == product_events.OWNER_ANONYMOUS_ID


# ------------------------------------------------------------------ events


async def test_a_new_todo_is_received_and_triaged(session, sent):
    await process_todo(
        session, _parsed(), "personal", "e", triage_fn=_triage("code", approval=True), source="sweep"
    )
    [received] = sent.named(product_events.TODO_RECEIVED)
    assert received.properties == {"lane": "triage", "source": "sweep"}
    [triaged] = sent.named(product_events.TODO_TRIAGED)
    assert triaged.properties == {"todo_kind": "code", "priority": "high", "outcome": "plan"}
    _no_text(sent)


async def test_noise_is_triaged_as_dropped(session, sent):
    await process_todo(
        session, _parsed(), "personal", "e", triage_fn=_triage("noise", actionable=False)
    )
    [triaged] = sent.named(product_events.TODO_TRIAGED)
    assert triaged.properties["outcome"] == "dropped"
    [received] = sent.named(product_events.TODO_RECEIVED)
    assert received.properties["source"] == "webhook"


async def test_a_todo_seen_before_sends_nothing(session, sent):
    await process_todo(session, _parsed(), "personal", "e", triage_fn=_triage("research"))
    await process_todo(session, _parsed(), "personal", "e2", triage_fn=_triage("research"))
    assert len(sent.named(product_events.TODO_RECEIVED)) == 1


async def test_a_noticing_goes_to_the_ideation_lane_untriaged(session, sent):
    await process_todo(
        session, _parsed(), "noticing", "e", triage_fn=_triage("research"), ideation=True
    )
    [received] = sent.named(product_events.TODO_RECEIVED)
    assert received.properties["lane"] == "ideation"
    assert sent.named(product_events.TODO_TRIAGED) == []


async def test_ideation_finishing_reports_status_and_cost(session, sent):
    session.add(Todo(uid="n1", calendar_uri="NF01", summary=SECRET_TEXT, status="ideating"))
    await session.flush()

    async def agent(**kwargs: object) -> AgentResult:
        return AgentResult("completed", "1) A\n2) B\n3) C", 0.4, "j9")

    async def note(*, calendar_uri: str, todo_uri: str, note: str) -> None:
        return None

    await run_ideation(session, todo_id=1, agent_fn=agent, note_fn=note)
    [finished] = sent.named(product_events.IDEATION_FINISHED)
    assert finished.properties["status"] == "completed"
    assert finished.properties["cost_usd"] == 0.4
    assert isinstance(finished.properties["duration_s"], int)
    _no_text(sent)


@pytest.fixture
async def callback_client(session, monkeypatch):
    monkeypatch.setenv("HMAC_SECRET", "secret")
    get_settings.cache_clear()
    app = FastAPI()
    app.include_router(callbacks.router)
    app.include_router(events.router)
    app.dependency_overrides[callbacks.get_session] = lambda: session
    app.dependency_overrides[events.get_session] = lambda: session
    session.add(Todo(uid="u", calendar_uri="personal"))
    await session.flush()
    session.add(Event(todo_id=1, kind="plan", payload={}))
    await session.commit()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        yield client
    get_settings.cache_clear()


@pytest.mark.parametrize("decision", ["approve", "reject"])
async def test_a_decision_on_a_plan_is_recorded(callback_client, sent, decision):
    r = await callback_client.get(f"/cb/{decision}/1?sig={sign('secret', 1, decision)}")
    assert r.status_code == 200
    [recorded] = sent.named(product_events.APPROVAL_RECORDED)
    assert recorded.properties["decision"] == decision
    assert recorded.properties["steered"] is False
    assert isinstance(recorded.properties["wait_s"], int)


async def test_a_refined_approval_says_it_was_steered_without_the_notes(callback_client, sent):
    r = await callback_client.post(
        f"/cb/refine/1?sig={sign('secret', 1, 'refine')}", data={"steer": SECRET_TEXT}
    )
    assert r.status_code == 200
    [recorded] = sent.named(product_events.APPROVAL_RECORDED)
    assert recorded.properties["decision"] == "refine"
    assert recorded.properties["steered"] is True
    _no_text(sent)


async def test_a_bad_signature_records_nothing(callback_client, sent):
    r = await callback_client.get("/cb/approve/1?sig=forged")
    assert r.status_code == 403
    assert sent.named(product_events.APPROVAL_RECORDED) == []


async def test_a_card_delivered_once(callback_client, sent):
    await callback_client.post("/api/events/1/consume")
    await callback_client.post("/api/events/1/consume")
    [delivered] = sent.named(product_events.CARD_DELIVERED)
    assert delivered.properties["kind"] == "plan"
    assert isinstance(delivered.properties["wait_s"], int)


async def test_an_approved_execution_finishing_reports_status_and_cost(session, sent):
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session.add(Todo(uid="x", calendar_uri="personal", summary=SECRET_TEXT))
    await session.flush()
    session.add(Event(todo_id=1, kind="plan", payload={}))
    await session.flush()
    session.add(Approval(event_id=1, decision="refine", sig="s", steer_prompt=SECRET_TEXT))
    await session.commit()
    maker = async_sessionmaker(session.bind, expire_on_commit=False)

    async def agent(**kwargs: object) -> AgentResult:
        return AgentResult("failed", "", None, "job-x")

    await handle_approval(1, maker, agent)
    [finished] = sent.named(product_events.EXECUTION_FINISHED)
    assert finished.properties["status"] == "failed"
    assert finished.properties["steered"] is True
    assert "cost_usd" not in finished.properties
    assert isinstance(finished.properties["duration_s"], int)
    _no_text(sent)


# ------------------------------------------------------------------ logs


def test_a_line_carries_the_open_telemetry_fields(stream):
    logging.getLogger("nextcloud_todos.test").warning("slow sweep", extra={"calendars": 2})
    [line] = [json.loads(x) for x in stream.getvalue().splitlines() if x]
    assert line["severity_text"] == "WARN"
    assert line["body"] == "slow sweep"
    assert line["service.name"] == "nextcloud-todos"
    assert line["service.version"] == "abc12345"
    assert line["deployment.environment.name"] == "production"
    assert line["calendars"] == 2


def test_uvicorn_lines_go_through_the_same_handler(stream):
    for name in json_logs.UVICORN_LOGGERS:
        named = logging.getLogger(name)
        assert named.handlers == []
        assert named.propagate is True
