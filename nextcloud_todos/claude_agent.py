import asyncio
from dataclasses import dataclass

import httpx

_TERMINAL = {"completed", "failed", "timeout", "error"}


@dataclass
class AgentResult:
    status: str
    result_text: str
    cost_usd: float | None
    job_id: str


async def submit_and_wait(
    *,
    base_url: str,
    token: str,
    prompt: str,
    agent: str,
    max_budget_usd: float,
    timeout_seconds: int,
    client: httpx.AsyncClient,
    poll_interval: float = 2.0,
) -> AgentResult:
    headers = {"Authorization": f"Bearer {token}"}
    sub = await client.post(
        f"{base_url}/execute",
        headers=headers,
        json={
            "prompt": prompt,
            "agent": agent,
            "max_budget_usd": max_budget_usd,
            "timeout_seconds": timeout_seconds,
        },
    )
    sub.raise_for_status()
    job_id = sub.json()["job_id"]

    deadline = asyncio.get_event_loop().time() + timeout_seconds + 30
    while True:
        r = await client.get(f"{base_url}/jobs/{job_id}", headers=headers)
        r.raise_for_status()
        data = r.json()
        if data.get("status") in _TERMINAL:
            return AgentResult(
                status=data["status"],
                result_text=data.get("result", ""),
                cost_usd=data.get("cost_usd"),
                job_id=job_id,
            )
        if asyncio.get_event_loop().time() > deadline:
            return AgentResult(status="timeout", result_text="", cost_usd=None, job_id=job_id)
        await asyncio.sleep(poll_interval)
