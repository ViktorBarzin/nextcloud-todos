import asyncio
import json
from dataclasses import dataclass

import httpx

_TERMINAL = {"completed", "failed", "timeout", "error"}


@dataclass
class AgentResult:
    status: str
    result_text: str
    cost_usd: float | None
    job_id: str


def _extract_result(data: dict) -> tuple[str, float | None]:
    """Pull the agent's answer + cost out of a terminal /jobs/{id} payload.

    The live claude-agent-service schema has no top-level "result"/"cost_usd":
    the answer is the final stream-json line inside "output" (a list of
    strings), text under "result", cost under "total_cost_usd". A top-level
    "result" (older schema / other deployments) is honoured first.
    """
    if data.get("result"):
        return str(data["result"]), data.get("cost_usd")
    chunks = data.get("output") or []
    if isinstance(chunks, str):
        chunks = [chunks]
    lines = "".join(chunks).splitlines()
    for line in reversed(lines):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("type") == "result":
            return str(obj.get("result") or ""), obj.get("total_cost_usd")
    return "", None


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
            result_text, cost_usd = _extract_result(data)
            return AgentResult(
                status=data["status"],
                result_text=result_text,
                cost_usd=cost_usd,
                job_id=job_id,
            )
        if asyncio.get_event_loop().time() > deadline:
            return AgentResult(status="timeout", result_text="", cost_usd=None, job_id=job_id)
        await asyncio.sleep(poll_interval)
