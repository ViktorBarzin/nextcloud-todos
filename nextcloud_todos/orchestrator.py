from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from nextcloud_todos.models import Event, Todo, TriageLog
from nextcloud_todos.parsing import ParsedTodo
from nextcloud_todos.triage import TriageVerdict

TriageFn = Callable[[str, str], Awaitable[TriageVerdict]]


async def process_todo(session: AsyncSession, parsed: ParsedTodo, calendar_uri: str,
                       etag: str, *, triage_fn: TriageFn) -> Todo:
    todo = (await session.execute(select(Todo).where(Todo.uid == parsed.uid))).scalar_one_or_none()
    if todo and todo.etag == etag:
        return todo  # dedup: unchanged delivery

    if todo is None:
        todo = Todo(uid=parsed.uid)
        session.add(todo)
    todo.calendar_uri = calendar_uri
    todo.etag = etag
    todo.summary = parsed.summary
    todo.description = parsed.description
    todo.due = parsed.due
    await session.flush()  # assign todo.id

    verdict = await triage_fn(parsed.summary, parsed.description)
    session.add(TriageLog(todo_id=todo.id, verdict=verdict.__dict__, model="qwen3-8b"))

    if not verdict.is_actionable or verdict.kind == "noise":
        todo.status = "dropped"
        await session.commit()
        return todo

    kind = "plan" if verdict.needs_approval else "answer"
    session.add(Event(todo_id=todo.id, kind=kind,
                      payload={"summary": verdict.one_line_summary, "todo_kind": verdict.kind}))
    todo.status = "awaiting_approval" if kind == "plan" else "answering"
    await session.commit()
    return todo
