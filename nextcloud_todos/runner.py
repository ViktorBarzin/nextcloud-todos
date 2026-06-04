from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.claude_agent import AgentResult
from nextcloud_todos.config import get_settings
from nextcloud_todos.models import Event, Run, Todo

AgentFn = Callable[..., Awaitable[AgentResult]]


def _finish(run: Run, res: AgentResult) -> None:
    run.status = res.status
    run.result_text = res.result_text
    run.cost_usd = res.cost_usd
    run.job_id = res.job_id
    run.finished_at = datetime.now(timezone.utc)


async def run_research(session: AsyncSession, *, todo_id: int, agent_fn: AgentFn) -> None:
    s = get_settings()
    todo = await session.get(Todo, todo_id)
    assert todo is not None
    run = Run(
        todo_id=todo_id,
        phase="research",
        agent=s.planner_agent,
        budget_usd=s.research_soft_cap_usd,
    )
    session.add(run)
    await session.flush()
    res = await agent_fn(
        prompt=f"Research this task and answer concisely:\n{todo.summary}\n{todo.description}",
        agent=s.planner_agent,
        max_budget_usd=s.research_soft_cap_usd,
        timeout_seconds=600,
    )
    _finish(run, res)
    todo.status = "answered" if res.status == "completed" else "failed"
    session.add(
        Event(
            todo_id=todo_id,
            kind="answer",
            payload={"result": res.result_text, "cost_usd": res.cost_usd},
        )
    )
    await session.commit()


async def run_plan(session: AsyncSession, *, todo_id: int, agent_fn: AgentFn) -> None:
    s = get_settings()
    todo = await session.get(Todo, todo_id)
    assert todo is not None
    run = Run(todo_id=todo_id, phase="plan", agent=s.planner_agent, budget_usd=s.plan_budget_usd)
    session.add(run)
    await session.flush()
    res = await agent_fn(
        prompt=(
            "Inspect the relevant repo/cluster state and produce a concrete plan plus a "
            f"cost estimate. CHANGE NOTHING.\nTask: {todo.summary}\n{todo.description}"
        ),
        agent=s.planner_agent,
        max_budget_usd=s.plan_budget_usd,
        timeout_seconds=600,
    )
    _finish(run, res)
    todo.status = "awaiting_approval" if res.status == "completed" else "failed"
    session.add(
        Event(
            todo_id=todo_id,
            kind="plan",
            payload={"plan": res.result_text, "cost_usd": res.cost_usd},
        )
    )
    await session.commit()


async def run_execute(
    session: AsyncSession, *, todo_id: int, steer: str | None, agent_fn: AgentFn
) -> None:
    s = get_settings()
    todo = await session.get(Todo, todo_id)
    assert todo is not None
    run = Run(todo_id=todo_id, phase="execute", agent=s.exec_agent, budget_usd=s.exec_budget_usd)
    session.add(run)
    await session.flush()
    prompt = f"Execute this approved task end to end.\nTask: {todo.summary}\n{todo.description}"
    if steer:
        prompt += f"\nAdditional instructions from the user:\n{steer}"
    res = await agent_fn(
        prompt=prompt,
        agent=s.exec_agent,
        max_budget_usd=s.exec_budget_usd,
        timeout_seconds=3600,
    )
    _finish(run, res)
    todo.status = "done" if res.status == "completed" else "failed"
    session.add(
        Event(
            todo_id=todo_id,
            kind="answer",
            payload={"result": res.result_text, "executed": True},
        )
    )
    await session.commit()
