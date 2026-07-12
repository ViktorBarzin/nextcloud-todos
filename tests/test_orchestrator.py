from nextcloud_todos.models import Event, Todo, TriageLog
from nextcloud_todos.orchestrator import process_todo
from nextcloud_todos.parsing import ParsedTodo
from nextcloud_todos.triage import TriageVerdict


def _parsed(uid="u1", summary="do x", status=""):
    return ParsedTodo(uid=uid, summary=summary, description="", due=None, status=status)


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


async def test_changed_etag_still_skipped(session):
    # Process-once: a re-delivery for the same UID is ignored even if the etag
    # changed (an edit, status flip, or the agent's own note-append) — the agent
    # only acts on newly-created items, never re-triggers.
    async def fake_triage(*a, **k):
        return await _verdict("code")

    await process_todo(session, _parsed(uid="d1"), "personal", "etag-1", triage_fn=fake_triage)
    await process_todo(session, _parsed(uid="d1"), "personal", "etag-2", triage_fn=fake_triage)
    assert len((await session.execute(Event.__table__.select())).fetchall()) == 1


async def test_completed_todo_skipped(session):
    async def fake_triage(*a, **k):
        raise AssertionError("triage must not run for a completed todo")

    out = await process_todo(
        session, _parsed(uid="c1", status="COMPLETED"), "personal", "e", triage_fn=fake_triage
    )
    assert out is None
    assert (await session.execute(Todo.__table__.select())).fetchall() == []
    assert (await session.execute(Event.__table__.select())).fetchall() == []


async def test_cancelled_todo_skipped(session):
    async def fake_triage(*a, **k):
        raise AssertionError("triage must not run for a cancelled todo")

    out = await process_todo(
        session, _parsed(uid="x1", status="CANCELLED"), "personal", "e", triage_fn=fake_triage
    )
    assert out is None


async def test_ideation_skips_triage_stores_uri_and_emits_no_event(session):
    async def fake_triage(*a, **k):
        raise AssertionError("ideation lane must not classify")

    todo = await process_todo(
        session,
        _parsed(uid="i1", summary="12 Jul — misses thunderstorms"),
        "NF01",
        "e",
        triage_fn=fake_triage,
        ideation=True,
        todo_uri="i1.ics",
    )
    assert todo is not None and todo.status == "ideating"
    assert todo.todo_uri == "i1.ics"
    assert (await session.execute(Event.__table__.select())).fetchall() == []
    assert (await session.execute(TriageLog.__table__.select())).fetchall() == []


async def test_ideation_with_existing_ideas_marker_is_recorded_not_redone(session):
    async def fake_triage(*a, **k):
        raise AssertionError("ideation lane must not classify")

    parsed = ParsedTodo(
        uid="i2",
        summary="s",
        description="💡 Ideas (Claude, 2026-07-01):\n1) x",
        due=None,
        status="",
    )
    todo = await process_todo(
        session, parsed, "NF01", "e", triage_fn=fake_triage, ideation=True
    )
    assert todo is not None and todo.status == "ideated"


async def test_agent_lane_also_persists_todo_uri(session):
    async def fake_triage(*a, **k):
        return await _verdict("code")

    todo = await process_todo(
        session, _parsed(uid="u9"), "personal", "e", triage_fn=fake_triage, todo_uri="u9.ics"
    )
    assert todo is not None and todo.todo_uri == "u9.ics"
