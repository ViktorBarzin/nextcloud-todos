import httpx
from defusedxml import ElementTree as ET  # add `defusedxml` to deps


class CalendarResolver:
    def __init__(
        self, *, base_url: str = "", user: str = "", password: str = "", allowlist_names: list[str]
    ):
        self._base_url = base_url
        self._user = user
        self._password = password
        self._allow = {n.casefold() for n in allowlist_names}
        self._cache: dict[str, str] = {}  # uri -> display_name

    def is_allowlisted(self, calendar_uri: str) -> bool:
        name = self._cache.get(calendar_uri)
        return name is not None and name.casefold() in self._allow

    def allowlisted_uris(self) -> set[str]:
        return {uri for uri, name in self._cache.items() if name.casefold() in self._allow}

    def display_name(self, calendar_uri: str) -> str:
        return self._cache.get(calendar_uri, "")

    async def refresh(self, client: httpx.AsyncClient) -> None:
        """PROPFIND calendar-home to build {uri: display_name}. Called at startup."""
        url = f"{self._base_url}/remote.php/dav/calendars/{self._user}/"
        body = '<d:propfind xmlns:d="DAV:"><d:prop><d:displayname/></d:prop></d:propfind>'
        resp = await client.request(
            "PROPFIND",
            url,
            content=body,
            headers={"Depth": "1", "Content-Type": "application/xml"},
            auth=(self._user, self._password),
        )
        resp.raise_for_status()
        self._cache = self._parse_propfind(resp.text)

    @staticmethod
    def _parse_propfind(xml: str) -> dict[str, str]:
        ns = {"d": "DAV:"}
        root = ET.fromstring(xml)
        out: dict[str, str] = {}
        for resp in root.findall("d:response", ns):
            href = (resp.findtext("d:href", default="", namespaces=ns) or "").rstrip("/")
            uri = href.rsplit("/", 1)[-1]
            name = resp.findtext(".//d:displayname", default="", namespaces=ns) or ""
            if uri and name:
                out[uri] = name
        return out
