import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "migrate":
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
    elif cmd == "serve":
        import os

        import uvicorn

        from nextcloud_todos import json_logs, product_events

        # JSON lines in the OpenTelemetry field names, and Product events and
        # error reports when the environment turns them on (docs/adr/0001).
        # uvicorn gets no logging config, so its lines go through the same handler.
        json_logs.setup(os.environ)
        product_events.start(os.environ)
        uvicorn.run(
            "nextcloud_todos.app:create_app",
            factory=True,
            host="0.0.0.0",
            port=8080,
            log_config=None,
        )
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
