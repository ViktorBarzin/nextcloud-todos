from nextcloud_todos.models import Event, TriageLog
from nextcloud_todos.orchestrator import process_todo
from nextcloud_todos.parsing import ParsedTodo
from nextcloud_todos.triage import TriageVerdict


def _parsed(uid="u1", summary="do x"):
    return ParsedTodo(uid=uid, summary=summary, description="", due=None, status="")


async def _verdict(kind, actionable=True, approval=None):
    needs = (kind in {"code", "infra", "mcp"}) if approval is None else approval
    return TriageVerdict(actionable, kind, "normal", needs, "s")


async def test_mutating_emits_plan_event(session):
    async def fake_triage(*a, **k):
        return await _verdict("code")

    todo = await process_todo(session, _parsed(), "personal", "etag1", triage_fn=fake_triage)
    events = (await session.execute(Event.__table__.select())).fetchall()
    assert len(events) == 1
    assert events[0].kind == "plan"
    assert todo.status == "awaiting_approval"


async def test_research_emits_answer_event(session):
    async def fake_triage(*a, **k):
        return await _verdict("research", approval=False)

    await process_todo(session, _parsed(uid="r1"), "personal", "e", triage_fn=fake_triage)
    events = (await session.execute(Event.__table__.select())).fetchall()
    assert events[0].kind == "answer"


async def test_noise_emits_no_event(session):
    async def fake_triage(*a, **k):
        return await _verdict("noise", actionable=False, approval=False)

    await process_todo(session, _parsed(uid="n1"), "personal", "e", triage_fn=fake_triage)
    assert (await session.execute(Event.__table__.select())).fetchall() == []
    assert (await session.execute(TriageLog.__table__.select())).fetchall()  # logged


async def test_same_etag_is_skipped(session):
    async def fake_triage(*a, **k):
        return await _verdict("code")

    await process_todo(session, _parsed(uid="d1"), "personal", "SAME", triage_fn=fake_triage)
    await process_todo(session, _parsed(uid="d1"), "personal", "SAME", triage_fn=fake_triage)
    # only one classification / one event despite two deliveries
    assert len((await session.execute(Event.__table__.select())).fetchall()) == 1
