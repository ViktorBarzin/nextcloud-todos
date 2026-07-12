import httpx

from nextcloud_todos.claude_agent import submit_and_wait


async def test_submit_polls_until_complete():
    state = {"calls": 0}

    def handler(request):
        if request.url.path == "/execute":
            return httpx.Response(202, json={"job_id": "j1"})
        state["calls"] += 1
        if state["calls"] < 2:
            return httpx.Response(200, json={"status": "running"})
        return httpx.Response(200, json={"status": "completed", "result": "done", "cost_usd": 0.42})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await submit_and_wait(
            base_url="http://a",
            token="t",
            prompt="p",
            agent="nextcloud-todos-planner",
            max_budget_usd=5,
            timeout_seconds=30,
            client=client,
            poll_interval=0,
        )
    assert res.status == "completed"
    assert res.result_text == "done"
    assert res.cost_usd == 0.42


async def test_submit_parses_stream_json_output_schema():
    # The live claude-agent-service /jobs/{id} schema has no top-level "result"
    # or "cost_usd": the agent's answer is the final stream-json line inside
    # "output" (a list of strings), with the text under "result" and the cost
    # under "total_cost_usd". Verified against a real job (db9398678db5).
    final_line = (
        '{"type":"result","subtype":"success","is_error":false,'
        '"result":"1. Buy flowers\\n2. Write a note\\n3. Plan a market walk",'
        '"total_cost_usd":0.208,"usage":{"output_tokens":474}}'
    )

    def handler(request):
        if request.url.path == "/execute":
            return httpx.Response(202, json={"job_id": "j2"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "output": ['{"type":"system"}\n' + final_line + "\n"],
                "stderr": "",
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await submit_and_wait(
            base_url="http://a",
            token="t",
            prompt="p",
            agent="nextcloud-todos-planner",
            max_budget_usd=5,
            timeout_seconds=30,
            client=client,
            poll_interval=0,
        )
    assert res.status == "completed"
    assert res.result_text.startswith("1. Buy flowers")
    assert res.cost_usd == 0.208


async def test_submit_handles_output_with_no_result_line():
    def handler(request):
        if request.url.path == "/execute":
            return httpx.Response(202, json={"job_id": "j3"})
        return httpx.Response(200, json={"status": "failed", "output": ["gibberish\n"]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        res = await submit_and_wait(
            base_url="http://a",
            token="t",
            prompt="p",
            agent="nextcloud-todos-planner",
            max_budget_usd=5,
            timeout_seconds=30,
            client=client,
            poll_interval=0,
        )
    assert res.status == "failed"
    assert res.result_text == ""
    assert res.cost_usd is None
