import json
from dataclasses import dataclass

import httpx

KINDS = {"research", "code", "infra", "mcp", "noise"}
MUTATING_KINDS = {"code", "infra", "mcp"}

SYSTEM_PROMPT = """You classify a single personal TODO item. Output ONLY a JSON object:
{
 "is_actionable": bool,   // false for pure reminders/shopping/noise
 "kind": "research|code|infra|mcp|noise",
 "priority": "low|normal|high",
 "needs_approval": bool,  // true if acting requires changing code/infra/devices
 "one_line_summary": str
}
Rules:
- "research": answerable by looking things up (no side effects) -> needs_approval=false
- "code": requires editing a software project -> needs_approval=true
- "infra": requires changing servers/k8s/terraform -> needs_approval=true
- "mcp": requires changing home-automation / external systems -> needs_approval=true
- "noise": groceries, simple reminders, personal notes -> is_actionable=false
No prose, no markdown, JSON only."""


@dataclass(frozen=True)
class TriageVerdict:
    is_actionable: bool
    kind: str
    priority: str
    needs_approval: bool
    one_line_summary: str

    @property
    def is_mutating(self) -> bool:
        return self.kind in MUTATING_KINDS


async def triage(summary: str, description: str, *, client: httpx.AsyncClient,
                 llama_url: str, model: str) -> TriageVerdict:
    user = f"SUMMARY: {summary}\nDESCRIPTION: {description}".strip()
    resp = await client.post(
        f"{llama_url}/v1/chat/completions",
        json={
            "model": model,
            "temperature": 0.0,
            "max_tokens": 512,
            "response_format": {"type": "json_object"},
            "chat_template_kwargs": {"enable_thinking": False},
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
        },
        timeout=300.0,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    data = json.loads(content)
    kind = data.get("kind", "noise")
    if kind not in KINDS:
        kind = "noise"
    return TriageVerdict(
        is_actionable=bool(data.get("is_actionable", False)),
        kind=kind,
        priority=str(data.get("priority", "normal")),
        needs_approval=bool(data.get("needs_approval", kind in MUTATING_KINDS)),
        one_line_summary=str(data.get("one_line_summary", summary))[:500],
    )
