from icalendar import Calendar

import httpx

from nextcloud_todos.caldav_client import append_description_note, append_note


def test_append_note_preserves_summary_adds_line():
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:u1\r\n"
        "SUMMARY:Do the thing\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
    )
    out = append_description_note(ics, "agent: researched - see Telegram")
    assert "SUMMARY:Do the thing" in out
    assert "agent: researched - see Telegram" in out
    assert "STATUS:COMPLETED" not in out  # never completes


def test_append_note_roundtrips_note_with_comma():
    # RFC 5545 escapes commas on serialization; the note must survive a parse round-trip.
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nBEGIN:VTODO\r\nUID:u1\r\n"
        "DESCRIPTION:original\r\nSUMMARY:Do the thing\r\nEND:VTODO\r\nEND:VCALENDAR\r\n"
    )
    out = append_description_note(ics, "agent: done, see Telegram")
    todo = Calendar.from_ical(out).walk("VTODO")[0]
    assert str(todo.get("DESCRIPTION")) == "original\nagent: done, see Telegram"
    assert "STATUS:COMPLETED" not in out


async def test_append_note_retries_unconditionally_on_proxy_412():
    # The front proxy (openresty) rejects VALID If-Match preconditions with a
    # bare 412 that never reaches Sabre (verified live 2026-07-12). On 412 the
    # append must re-read the object and retry once without If-Match.
    puts = []
    state = {"gets": 0}

    def handler(request):
        if request.method == "GET":
            state["gets"] += 1
            return httpx.Response(
                200,
                text=(
                    "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VTODO\nUID:x\n"
                    "SUMMARY:s\nEND:VTODO\nEND:VCALENDAR"
                ),
                headers={"ETag": '"e1"'},
            )
        puts.append(request.headers.get("If-Match"))
        if request.headers.get("If-Match"):
            return httpx.Response(412, text="<html>openresty</html>")
        return httpx.Response(204)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        await append_note(
            base_url="http://n",
            user="admin",
            password="p",
            calendar_uri="noticing-file",
            todo_uri="x.ics",
            note="💡 Ideas (Claude, 2026-07-12):\n1) A",
            client=client,
        )

    assert puts == ['"e1"', None]  # conditional first, then one unconditional retry
    assert state["gets"] == 2  # re-read before the unconditional retry
