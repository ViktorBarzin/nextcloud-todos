from icalendar import Calendar

from nextcloud_todos.caldav_client import append_description_note


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
