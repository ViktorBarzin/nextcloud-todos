import httpx
from icalendar import Calendar


def append_description_note(ics: str, note: str) -> str:
    cal = Calendar.from_ical(ics)
    for comp in cal.walk("VTODO"):
        existing = str(comp.get("DESCRIPTION", ""))
        comp["DESCRIPTION"] = (existing + "\n" if existing else "") + note
        break
    return cal.to_ical().decode()


async def append_note(
    *,
    base_url: str,
    user: str,
    password: str,
    calendar_uri: str,
    todo_uri: str,
    note: str,
    client: httpx.AsyncClient,
) -> None:
    """Read-modify-write the VTODO object, preserving ETag semantics."""
    obj_url = f"{base_url}/remote.php/dav/calendars/{user}/{calendar_uri}/{todo_uri}"
    get = await client.get(obj_url, auth=(user, password))
    get.raise_for_status()
    updated = append_description_note(get.text, note)
    put = await client.put(
        obj_url,
        content=updated,
        auth=(user, password),
        headers={"Content-Type": "text/calendar", "If-Match": get.headers.get("ETag", "*")},
    )
    put.raise_for_status()
