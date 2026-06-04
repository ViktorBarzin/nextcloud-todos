# nextcloud-todos

Agent that watches the Nextcloud **Personal** task list. New/changed todos are
classified by a local LLM (`qwen3-8b`); read-only work is auto-handled and
answered in Telegram, mutating work surfaces a plan for one-tap approval before
a full-powers `claude-agent-service` run executes it.

See `docs/superpowers/specs/2026-06-04-nextcloud-todos-design.md` (in the
monorepo) for the design.

## Dev

    poetry install
    poetry run pytest -v
    poetry run mypy nextcloud_todos
    poetry run ruff check nextcloud_todos
