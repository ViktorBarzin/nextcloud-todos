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
