from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.config import get_settings
from nextcloud_todos.models import Event, Todo, TriageLog
from nextcloud_todos.parsing import ParsedTodo
from nextcloud_todos.triage import TriageVerdict

TriageFn = Callable[[str, str], Awaitable[TriageVerdict]]

# VTODO STATUS values that mean the task is NOT open — never act on these.
CLOSED_STATUSES = {"COMPLETED", "CANCELLED"}

# Marker the ideation runner writes into a todo's DESCRIPTION. A new todo that
# already carries it (e.g. a copy of an old noticing) is never re-ideated.
IDEAS_MARKER = "💡 Ideas"


async def process_todo(
    session: AsyncSession,
    parsed: ParsedTodo,
    calendar_uri: str,
    etag: str,
    *,
    triage_fn: TriageFn,
    ideation: bool = False,
    todo_uri: str | None = None,
) -> Todo | None:
    # Act on a todo ONCE, at first sight only. Any later delivery for the same
    # UID (an edit, a status change, the agent's own note-append) is ignored —
    # the agent is purely reactive to newly-created items, never re-triggers.
    existing = (
        await session.execute(select(Todo).where(Todo.uid == parsed.uid))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    # Only act on OPEN tasks — skip completed/cancelled (don't even record them).
    if parsed.status.upper() in CLOSED_STATUSES:
        return None

    todo = Todo(
        uid=parsed.uid,
        calendar_uri=calendar_uri,
        todo_uri=todo_uri,
        etag=etag,
        summary=parsed.summary,
        description=parsed.description,
        due=parsed.due,
    )
    session.add(todo)
    await session.flush()  # assign todo.id

    if ideation:
        # Ideation lane: no classification, no Event yet. The caller dispatches
        # the ideation run for "ideating" todos; ones already carrying an ideas
        # block are recorded as done so they are never re-ideated.
        todo.status = "ideated" if IDEAS_MARKER in parsed.description else "ideating"
        await session.commit()
        return todo

    verdict = await triage_fn(parsed.summary, parsed.description)
    session.add(TriageLog(todo_id=todo.id, verdict=verdict.__dict__, model=get_settings().triage_model))

    if not verdict.is_actionable or verdict.kind == "noise":
        todo.status = "dropped"
        await session.commit()
        return todo

    kind = "plan" if verdict.needs_approval else "answer"
    session.add(
        Event(
            todo_id=todo.id,
            kind=kind,
            payload={"summary": verdict.one_line_summary, "todo_kind": verdict.kind},
        )
    )
    todo.status = "awaiting_approval" if kind == "plan" else "answering"
    await session.commit()
    return todo
