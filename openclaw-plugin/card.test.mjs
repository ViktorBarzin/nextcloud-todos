import { test } from "node:test";
import assert from "node:assert";
import { composePlanCard, composeAnswerCard, esc } from "./card.mjs";

test("esc escapes html", () => {
  assert.equal(esc("<b>&"), "&lt;b&gt;&amp;");
});

test("plan card has approve/reject/refine links", () => {
  const html = composePlanCard({
    summary: "Add panel", plan: "PLAN: edit X", cost_usd: 3,
    links: { approve: "https://h/cb/approve/1?sig=a",
             reject: "https://h/cb/reject/1?sig=b",
             refine: "https://h/cb/refine/1?sig=c" },
  });
  assert.match(html, /Approve/);
  assert.match(html, /cb\/approve\/1/);
  assert.match(html, /cb\/refine\/1/);
});

test("answer card includes result", () => {
  assert.match(composeAnswerCard({ summary: "x", result: "Heat pump A wins" }), /Heat pump A wins/);
});
