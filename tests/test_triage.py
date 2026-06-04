import json

import httpx

from nextcloud_todos.triage import TriageVerdict, triage


async def test_triage_parses_json_verdict():
    payload = {
        "is_actionable": True, "kind": "code", "priority": "normal",
        "needs_approval": True, "one_line_summary": "Add a panel",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert "chat/completions" in str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        v = await triage("Add a Grafana panel", "", client=client,
                         llama_url="http://x", model="qwen3-8b")
    assert isinstance(v, TriageVerdict)
    assert v.kind == "code"
    assert v.needs_approval is True


async def test_noise_is_not_actionable():
    payload = {"is_actionable": False, "kind": "noise", "priority": "low",
               "needs_approval": False, "one_line_summary": "buy milk"}
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}))
    async with httpx.AsyncClient(transport=transport) as client:
        v = await triage("buy milk", "", client=client, llama_url="http://x", model="qwen3-8b")
    assert v.kind == "noise"
    assert v.is_actionable is False
