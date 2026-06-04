FROM python:3.12-slim AS build
ENV POETRY_VERSION=1.8.4 PIP_NO_CACHE_DIR=1
RUN pip install "poetry==$POETRY_VERSION"
WORKDIR /app
COPY pyproject.toml poetry.lock* ./
RUN poetry config virtualenvs.in-project true && poetry install --only main --no-root
COPY nextcloud_todos ./nextcloud_todos
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY openclaw-plugin ./openclaw-plugin
RUN poetry install --only main

FROM python:3.12-slim
RUN useradd -u 10001 -m app
WORKDIR /app
COPY --from=build /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER 10001
ENTRYPOINT ["python", "-m", "nextcloud_todos"]
CMD ["serve"]
