from nextcloud_todos.calendars import CalendarResolver


async def test_resolves_display_name_to_uri():
    r = CalendarResolver(allowlist_names=["Personal"])
    # simulate the parsed PROPFIND result: {uri: display_name}
    r._cache = {"personal": "Personal", "A63E": "To Buy", "50E5": "Work Todo"}
    assert r.is_allowlisted("personal") is True
    assert r.is_allowlisted("A63E") is False
    assert r.allowlisted_uris() == {"personal"}


async def test_match_is_case_insensitive():
    r = CalendarResolver(allowlist_names=["personal"])
    r._cache = {"personal": "Personal"}
    assert r.is_allowlisted("personal") is True


def test_parse_propfind_extracts_uri_and_name():
    xml = """<?xml version="1.0"?>
<d:multistatus xmlns:d="DAV:" xmlns:cal="urn:ietf:params:xml:ns:caldav">
  <d:response>
    <d:href>/remote.php/dav/calendars/admin/</d:href>
    <d:propstat>
      <d:prop><d:displayname/></d:prop>
      <d:status>HTTP/1.1 404 Not Found</d:status>
    </d:propstat>
  </d:response>
  <d:response>
    <d:href>/remote.php/dav/calendars/admin/personal/</d:href>
    <d:propstat>
      <d:prop><d:displayname>Personal</d:displayname></d:prop>
      <d:status>HTTP/1.1 200 OK</d:status>
    </d:propstat>
  </d:response>
</d:multistatus>"""
    assert CalendarResolver._parse_propfind(xml) == {"personal": "Personal"}
