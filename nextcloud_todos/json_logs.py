"""Log lines as JSON in the OpenTelemetry field names (docs/adr/0001, infra ADR-0041).

One object per line on stdout, written by `viktorbarzin_telemetry`'s formatter:
`timestamp`, `severity_text`, `severity_number`, `body`, `logger.name`,
`service.name` (`nextcloud-todos`), `service.version` (`APP_VERSION`, the
commit's short sha baked in by the CI build) and `deployment.environment.name`.

`__main__` calls `setup` before uvicorn starts, and starts uvicorn without a
logging config of its own; `setup` still hands uvicorn's loggers to the root
logger, so the access and error lines are JSON however they were configured.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TextIO

import viktorbarzin_telemetry as telemetry

APP = "nextcloud-todos"

#: uvicorn's loggers, which it may configure with handlers of their own.
UVICORN_LOGGERS: tuple[str, ...] = ("uvicorn", "uvicorn.error", "uvicorn.access")


def release(env: Mapping[str, str]) -> str:
    """This image's release: the commit's short sha, which the CI build bakes in."""
    return env.get("APP_VERSION", "").strip() or "0.0.0"


def setup(env: Mapping[str, str], *, stream: TextIO | None = None) -> logging.Handler:
    """Make every log line JSON, on stdout or `stream`. Returns the handler."""
    environment = env.get(telemetry.ENVIRONMENT_VARIABLE, "").strip() or None
    handler = telemetry.setup_logging(
        service_name=APP,
        service_version=release(env),
        environment=environment,
        stream=stream,
    )
    for name in UVICORN_LOGGERS:
        named = logging.getLogger(name)
        for existing in list(named.handlers):
            named.removeHandler(existing)
        named.propagate = True
    return handler
