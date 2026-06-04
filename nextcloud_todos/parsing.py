from dataclasses import dataclass
from datetime import datetime

from icalendar import Calendar


@dataclass(frozen=True)
class ParsedTodo:
    uid: str
    summary: str
    description: str
    due: datetime | None
    status: str
    component: str = "vtodo"


def parse_vtodo(ics: str) -> ParsedTodo | None:
    cal = Calendar.from_ical(ics)
    for comp in cal.walk("VTODO"):
        due = comp.get("DUE")
        return ParsedTodo(
            uid=str(comp.get("UID", "")),
            summary=str(comp.get("SUMMARY", "")),
            description=str(comp.get("DESCRIPTION", "")),
            due=due.dt if due is not None else None,
            status=str(comp.get("STATUS", "")),
        )
    return None
