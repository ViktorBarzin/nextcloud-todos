from nextcloud_todos.claude_agent import AgentResult
from nextcloud_todos.ideation import run_ideation
from nextcloud_todos.models import Event, Run, Todo


async def test_run_ideation_appends_note_and_emits_answer(session):
    session.add(
        Todo(
            uid="n1",
            calendar_uri="NF01",
            todo_uri="n1.ics",
            summary="12 Jul — 'I miss real thunderstorms' — balcony",
            status="ideating",
        )
    )
    await session.flush()
    notes = []

    async def fake_agent(**k):
        assert k["agent"] == "nextcloud-todos-planner"
        assert k["max_budget_usd"] == 3.0  # ideation budget
        assert "thunderstorms" in k["prompt"]
        return AgentResult("completed", "1) A\n2) B\n3) C", 0.4, "j9")

    async def fake_note(*, calendar_uri, todo_uri, note):
        assert calendar_uri == "NF01" and todo_uri == "n1.ics"
        notes.append(note)

    await run_ideation(session, todo_id=1, agent_fn=fake_agent, note_fn=fake_note)

    assert len(notes) == 1
    assert notes[0].startswith("💡 Ideas") and "1) A" in notes[0]
    runs = (await session.execute(Run.__table__.select())).fetchall()
    assert runs[0].phase == "ideation" and runs[0].status == "completed"
    todo = await session.get(Todo, 1)
    assert todo is not None and todo.status == "ideated"
    events = (await session.execute(Event.__table__.select())).fetchall()
    assert events[-1].kind == "answer" and "1) A" in events[-1].payload["result"]


async def test_run_ideation_failure_skips_note_and_reports(session):
    session.add(Todo(uid="n2", calendar_uri="NF01", summary="s", status="ideating"))
    await session.flush()

    async def fake_agent(**k):
        return AgentResult("failed", "", None, "j10")

    async def fake_note(**k):
        raise AssertionError("must not write a note on failure")

    await run_ideation(session, todo_id=1, agent_fn=fake_agent, note_fn=fake_note)
    todo = await session.get(Todo, 1)
    assert todo is not None and todo.status == "failed"
    events = (await session.execute(Event.__table__.select())).fetchall()
    assert events[-1].kind == "answer" and "failed" in events[-1].payload["result"].lower()


async def test_run_ideation_missing_todo_uri_falls_back_to_uid_ics(session):
    session.add(Todo(uid="n3", calendar_uri="NF01", summary="s", status="ideating"))
    await session.flush()
    seen = {}

    async def fake_agent(**k):
        return AgentResult("completed", "1) A", 0.1, "j11")

    async def fake_note(*, calendar_uri, todo_uri, note):
        seen["uri"] = todo_uri

    await run_ideation(session, todo_id=1, agent_fn=fake_agent, note_fn=fake_note)
    assert seen["uri"] == "n3.ics"
