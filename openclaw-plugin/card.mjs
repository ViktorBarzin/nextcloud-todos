// Deterministic Telegram-card builder. No LLM. Inputs: the card payload from
// the service's GET /api/get/{todo_id} (summary + latest plan/answer + signed
// approve/reject/refine links). Output: an HTML-formatted string for
// sendMessage with parse_mode: HTML.
// Cloned from recruiter-responder/openclaw-plugin/card.mjs.

export function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

export function composeAnswerCard({ summary, result }) {
  return `🔎 <b>${esc(summary)}</b>\n\n${esc(result).slice(0, 3500)}`;
}

export function composePlanCard({ summary, plan, cost_usd, links }) {
  const cost = cost_usd != null ? ` (est. $${esc(cost_usd)})` : "";
  return [
    `🛠 <b>${esc(summary)}</b>${cost}`,
    "",
    esc(plan).slice(0, 3200),
    "",
    `<a href="${esc(links.approve)}">✅ Approve</a>  ·  ` +
    `<a href="${esc(links.reject)}">❌ Reject</a>  ·  ` +
    `<a href="${esc(links.refine)}">✏️ Refine</a>`,
  ].join("\n");
}
