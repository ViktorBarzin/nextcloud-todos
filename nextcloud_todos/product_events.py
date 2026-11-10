"""nextcloud-todos' Product events and error reports (docs/adr/0001, infra ADR-0041).

Events go through `viktorbarzin_telemetry` (Segment's SDK) to the Event
pipeline, and errors through Sentry to GlitchTip. `start` turns both on from the
environment:

- `TELEMETRY_WRITE_KEY`: nextcloud-todos' Write key. Unset or blank means no
  events, which is how dev, tests and a laptop run.
- `TELEMETRY_HOST`: the Event pipeline's base URL (the event-pipeline Service
  inside the cluster).
- `TELEMETRY_ENVIRONMENT`: only `production` sends anything.
- `TELEMETRY_PERSON_ID`: the Authentik hashed user id of the person whose
  Nextcloud lists are watched. Nobody signs in to this service, so every event
  is theirs. Unset means events carry no Person, only `OWNER_ANONYMOUS_ID`.
- `SENTRY_DSN`: GlitchTip's DSN for nextcloud-todos. Unset means no error reports.

Properties are kinds, outcomes, statuses, costs and durations. No property
carries a todo's summary or description, a plan, an answer, steering notes or a
calendar name, since all of them are the owner's own words.

Every helper here returns at once and never raises: an event is worth less than
the work it rides on.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime, timezone

import viktorbarzin_telemetry as telemetry

from nextcloud_todos.json_logs import APP, release

logger = logging.getLogger(__name__)

TODO_RECEIVED = "todo.received"
TODO_TRIAGED = "todo.triaged"
IDEATION_FINISHED = "ideation.finished"
CARD_DELIVERED = "card.delivered"
APPROVAL_RECORDED = "approval.recorded"
EXECUTION_FINISHED = "execution.finished"

#: Every event nextcloud-todos sends, for the ADR and the tests.
EVENTS: tuple[str, ...] = (
    TODO_RECEIVED,
    TODO_TRIAGED,
    IDEATION_FINISHED,
    CARD_DELIVERED,
    APPROVAL_RECORDED,
    EXECUTION_FINISHED,
)

#: The anonymousId of every event: there is one owner and no visitor.
OWNER_ANONYMOUS_ID = "nextcloud-todos-owner"

_person: str | None = None


def start(env: Mapping[str, str], *, client: telemetry.EventClient | None = None) -> bool:
    """Turn events and error reports on from `env`. True when events are sent.

    `client` replaces Segment's, for tests.
    """
    global _person
    write_key = env.get("TELEMETRY_WRITE_KEY", "").strip()
    environment = env.get(telemetry.ENVIRONMENT_VARIABLE, "").strip() or "dev"
    dsn = env.get("SENTRY_DSN", "").strip() or None
    if not write_key:
        stop()
        if dsn and environment == telemetry.PRODUCTION:
            telemetry.init_sentry(dsn, release=release(env), environment=environment)
        return False
    try:
        sender = telemetry.configure(
            app=APP,
            write_key=write_key,
            release=release(env),
            environment=environment,
            dsn=dsn,
            host=env.get(telemetry.HOST_VARIABLE, "").strip() or None,
            client=client,
        )
    except ValueError as exc:
        # Production with no pipeline URL: say so once and send nothing,
        # rather than keep the pod from starting.
        logger.warning("product events are off: %s", exc)
        stop()
        return False
    _person = env.get("TELEMETRY_PERSON_ID", "").strip() or None
    logger.info("product events %s", "on" if sender.enabled else "off (not production)")
    return sender.enabled


def stop() -> None:
    """Send nothing from here on. For tests, and a start that cannot send."""
    global _person
    _person = None
    telemetry.configure(app=APP, write_key="", release="0", environment="dev")


def flush() -> None:
    """Send what is queued. Called once, on shutdown."""
    try:
        telemetry.flush()
    except Exception:
        logger.warning("product events: the last flush failed", exc_info=True)


def _send(event: str, properties: telemetry.Properties) -> None:
    try:
        telemetry.track(event, properties, user_id=_person, anonymous_id=OWNER_ANONYMOUS_ID)
    except Exception:
        logger.warning("product events: %s was not sent", event, exc_info=True)


def seconds_between(start: datetime | None, end: datetime | None = None) -> int | None:
    """Whole seconds from `start` to `end` (now). A naive time is taken as UTC,
    which is how SQLite hands back the stored ones."""
    if start is None:
        return None
    stop_at = end or datetime.now(timezone.utc)
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if stop_at.tzinfo is None:
        stop_at = stop_at.replace(tzinfo=timezone.utc)
    return max(0, round((stop_at - start).total_seconds()))


def _with(
    properties: dict[str, telemetry.JsonValue], **optional: telemetry.JsonValue
) -> dict[str, telemetry.JsonValue]:
    """`properties` plus each of `optional` that is not None."""
    properties.update({key: value for key, value in optional.items() if value is not None})
    return properties


def todo_received(*, lane: str, source: str) -> None:
    """A new open todo was seen on a watched list, through the Nextcloud
    `webhook` or the `sweep`. `lane` is `triage` or `ideation`."""
    _send(TODO_RECEIVED, {"lane": lane, "source": source})


def todo_triaged(*, todo_kind: str, priority: str, outcome: str) -> None:
    """The classifier's verdict: `outcome` is `dropped`, `answer` or `plan`."""
    _send(TODO_TRIAGED, {"todo_kind": todo_kind, "priority": priority, "outcome": outcome})


def ideation_finished(*, status: str, cost_usd: float | None, duration_s: int | None) -> None:
    """An ideation run for a noticing ended."""
    _send(
        IDEATION_FINISHED,
        _with({"status": status}, cost_usd=cost_usd, duration_s=duration_s),
    )


def card_delivered(kind: str, *, wait_s: int | None) -> None:
    """The Telegram side took a `plan` or `answer` card, `wait_s` after it was made."""
    _send(CARD_DELIVERED, _with({"kind": kind}, wait_s=wait_s))


def approval_recorded(decision: str, *, steered: bool, wait_s: int | None) -> None:
    """The owner tapped `approve`, `reject` or `refine` on a card, `wait_s` after
    the card was made. `steered` when a refine carried notes."""
    _send(APPROVAL_RECORDED, _with({"decision": decision, "steered": steered}, wait_s=wait_s))


def execution_finished(
    *, status: str, steered: bool, cost_usd: float | None, duration_s: int | None
) -> None:
    """An approved todo's execute run ended."""
    _send(
        EXECUTION_FINISHED,
        _with({"status": status, "steered": steered}, cost_usd=cost_usd, duration_s=duration_s),
    )
