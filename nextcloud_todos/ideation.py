"""Ideation lane: turn a captured "noticing" into deployable romantic ideas.

Todos on lists in ``IDEATION_ALLOWLIST`` (v1: the "Noticing File") skip the
classifier entirely. A noticing is raw attention — something Anca said,
lingered on, griped about, or mused — and the runner's job is the ideation
phase only: generate concrete ideas that trace back to it, append them onto
the todo, and surface them in Telegram. Capture and the final pick stay human.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.config import get_settings
from nextcloud_todos.models import Event, Run, Todo
from nextcloud_todos.runner import AgentFn, _finish

NoteFn = Callable[..., Awaitable[None]]

IDEATION_BRIEF = """\
You are the ideation assistant for Viktor's romance course (learn/romance in his monorepo).
A "noticing" was just captured about his partner Anca — something she said, lingered on,
griped about, mused about, or a key date. Generate EXACTLY 3 concrete, deployable ideas
that trace directly back to this noticing.

Context that must shape every idea:
- They live together in London; Anca is from Timișoara, Romania.
- Her observed high-signal channel: thoughtful gifts & surprises. The value is
  demonstrated knowing — the gesture should quote her words back to her. Never price.
- Typical budget £20–50; prefer ideas that cost little or nothing. Occasions have
  their own budget.
- Vary the type across the 3 ideas where sensible: small gift / surprise moment /
  date or experience / act of service / a short note referencing her exact words.
- Each idea: ONE line, imperative, concrete enough to execute this week, with
  where/what specifics. Search the web for current London specifics when useful.
- Never suggest revealing the capture system or sharing the list with Anca.

Output ONLY the 3 numbered idea lines. No preamble, no closing remarks."""


def _prompt(todo: Todo) -> str:
    return (
        f"{IDEATION_BRIEF}\n\n"
        f"Noticing (summary): {todo.summary}\n"
        f"Noticing (details): {todo.description or '—'}"
    )


async def run_ideation(
    session: AsyncSession, *, todo_id: int, agent_fn: AgentFn, note_fn: NoteFn
) -> None:
    s = get_settings()
    todo = await session.get(Todo, todo_id)
    assert todo is not None
    run = Run(
        todo_id=todo_id,
        phase="ideation",
        agent=s.planner_agent,
        budget_usd=s.ideation_budget_usd,
    )
    session.add(run)
    await session.flush()
    res = await agent_fn(
        prompt=_prompt(todo),
        agent=s.planner_agent,
        max_budget_usd=s.ideation_budget_usd,
        timeout_seconds=600,
    )
    _finish(run, res)

    payload: dict[str, object]
    if res.status == "completed" and res.result_text.strip():
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        note = f"💡 Ideas (Claude, {stamp}):\n{res.result_text.strip()}"
        await note_fn(
            calendar_uri=todo.calendar_uri,
            todo_uri=todo.todo_uri or f"{todo.uid}.ics",
            note=note,
        )
        todo.status = "ideated"
        payload = {"result": f"💡 Ideas for “{todo.summary}”:\n{res.result_text.strip()}"}
    else:
        todo.status = "failed"
        payload = {"result": f"Ideation failed for “{todo.summary}” (status: {res.status})."}

    payload["cost_usd"] = res.cost_usd
    session.add(Event(todo_id=todo_id, kind="answer", payload=payload))
    await session.commit()
