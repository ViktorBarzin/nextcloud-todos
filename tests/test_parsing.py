from datetime import datetime, timezone
from pathlib import Path

from nextcloud_todos.parsing import parse_vtodo

FX = Path(__file__).parent / "fixtures"


def test_parse_simple():
    p = parse_vtodo((FX / "vtodo_simple.ics").read_text())
    assert p is not None
    assert p.uid == "abc-123"
    assert p.summary == "Compare heat pumps for the flat"
    assert p.due is None


def test_parse_with_due():
    p = parse_vtodo((FX / "vtodo_with_due.ics").read_text())
    assert p.uid == "due-1"
    assert p.description == "Fuse Energy ends 19 Nov"
    assert p.due == datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)
    assert p.status == "NEEDS-ACTION"


def test_vevent_is_ignored():
    assert parse_vtodo((FX / "vevent_not_todo.ics").read_text()) is None
