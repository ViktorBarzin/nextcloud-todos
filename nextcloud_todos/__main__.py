import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "serve"
    if cmd == "migrate":
        from alembic import command
        from alembic.config import Config

        command.upgrade(Config("alembic.ini"), "head")
    elif cmd == "serve":
        import uvicorn

        uvicorn.run("nextcloud_todos.app:create_app", factory=True, host="0.0.0.0", port=8080)
    else:
        raise SystemExit(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
