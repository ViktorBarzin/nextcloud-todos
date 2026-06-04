from nextcloud_todos.models import Todo


async def test_todo_roundtrip(session):
    session.add(Todo(uid="u1", calendar_uri="personal", etag="e1", summary="hi"))
    await session.commit()
    got = (await session.execute(Todo.__table__.select())).first()
    assert got.uid == "u1"
    assert got.status == "pending"
