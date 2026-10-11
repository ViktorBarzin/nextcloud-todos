import json

import httpx

from nextcloud_todos.triage import TriageVerdict, triage


async def test_triage_parses_json_verdict():
    payload = {
        "is_actionable": True,
        "kind": "code",
        "priority": "normal",
        "needs_approval": True,
        "one_line_summary": "Add a panel",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "chat/completions" in str(request.url)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        v = await triage(
            "Add a Grafana panel", "", client=client, url="http://x", model="haiku", token="tok"
        )
    assert isinstance(v, TriageVerdict)
    assert v.kind == "code"
    assert v.needs_approval is True


async def test_noise_is_not_actionable():
    payload = {
        "is_actionable": False,
        "kind": "noise",
        "priority": "low",
        "needs_approval": False,
        "one_line_summary": "buy milk",
    }
    transport = httpx.MockTransport(
        lambda r: httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        v = await triage("buy milk", "", client=client, url="http://x", model="haiku", token="tok")
    assert v.kind == "noise"
    assert v.is_actionable is False


def _reply(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


async def test_triage_asks_claude_agent_in_no_tools_mode():
    """To-do text is written by whoever can add to the list, so it goes to
    claude-agent-service's no-tools sandbox with the service bearer."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _reply(json.dumps({"is_actionable": False, "kind": "noise",
                                  "priority": "low", "needs_approval": False,
                                  "one_line_summary": "buy milk"}))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await triage("buy milk", "", client=client, url="http://agent", model="haiku",
                     token="tok")
    assert str(seen[0].url) == "http://agent/v1/chat/completions"
    assert seen[0].headers["Authorization"] == "Bearer tok"
    body = json.loads(seen[0].content)
    assert body["model"] == "haiku"
    assert body["no_tools"] is True
    assert "chat_template_kwargs" not in body


async def test_triage_reads_a_fenced_json_reply():
    """Claude often wraps its JSON in a markdown fence."""
    fenced = "```json\n" + json.dumps({"is_actionable": True, "kind": "research",
                                        "priority": "normal", "needs_approval": False,
                                        "one_line_summary": "x"}) + "\n```"
    transport = httpx.MockTransport(lambda r: _reply(fenced))
    async with httpx.AsyncClient(transport=transport) as client:
        v = await triage("look up X", "", client=client, url="http://x", model="haiku",
                         token="tok")
    assert v.kind == "research"
