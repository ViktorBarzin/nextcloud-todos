from nextcloud_todos.claude_agent import AgentResult
from nextcloud_todos.models import Event, Run, Todo
from nextcloud_todos.runner import run_plan, run_research


async def test_run_research_emits_answer_event_and_run_row(session):
    session.add(Todo(uid="r1", calendar_uri="personal", summary="compare heat pumps"))
    await session.flush()

    async def fake_agent(**k):
        assert k["agent"] == "nextcloud-todos-planner"
        assert k["max_budget_usd"] == 20.0  # research soft cap
        return AgentResult("completed", "Heat pump A vs B...", 1.2, "j1")

    await run_research(session, todo_id=1, agent_fn=fake_agent)
    runs = (await session.execute(Run.__table__.select())).fetchall()
    assert runs[0].phase == "research"
    assert runs[0].status == "completed"
    events = (await session.execute(Event.__table__.select())).fetchall()
    assert events[-1].kind == "answer"
    assert "Heat pump" in events[-1].payload["result"]


async def test_run_plan_emits_plan_event(session):
    session.add(Todo(uid="c1", calendar_uri="personal", summary="add panel"))
    await session.flush()

    async def fake_agent(**k):
        assert k["max_budget_usd"] == 5.0  # plan budget
        return AgentResult("completed", "PLAN: edit X. EST: $3", 0.3, "j2")

    await run_plan(session, todo_id=1, agent_fn=fake_agent)
    events = (await session.execute(Event.__table__.select())).fetchall()
    assert events[-1].kind == "plan"
    assert "PLAN:" in events[-1].payload["plan"]
