import os

import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from nextcloud_todos.db import metadata

# Telemetry stays off unless a test turns it on with a recorder (docs/adr/0001).
for _name in (
    "TELEMETRY_WRITE_KEY",
    "TELEMETRY_HOST",
    "TELEMETRY_ENVIRONMENT",
    "TELEMETRY_PERSON_ID",
    "SENTRY_DSN",
):
    os.environ.pop(_name, None)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()
