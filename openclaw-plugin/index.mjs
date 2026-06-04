/**
 * OpenClaw nextcloud-todos API plugin.
 *
 * Chat surface + announcement loop for the nextcloud-todos service. Polls the
 * service's events work-queue; per event it fetches the assembled card payload
 * (GET /api/get/{todo_id}), renders an answer card or a plan card (with tappable
 * Approve / Reject / Refine HMAC links), delivers it to Telegram, then consumes
 * the event and advances the cursor.
 *
 * kind:"tools" plugins do NOT receive api.bot, so Telegram delivery uses the Bot
 * API directly via the bot token env var.
 *
 * Cloned from recruiter-responder/openclaw-plugin/index.mjs.
 */

import { NtClient } from "./ntClient.mjs";
import { composeAnswerCard, composePlanCard } from "./card.mjs";

const PLUGIN_ID = "nextcloud-todos-api";
const POLL_MS = 60 * 1000;

// Module-level active-todo pointer — written by the polling loop, read by
// todos_get / todos_answer_for when the user omits a todo id.
let _activeTodoId = null;

// Module-level Telegram chat override — written by todos_set_chat, read by the
// poll loop's delivery. Falls back to the VIKTOR_CHAT_ID env var.
let _chatOverride = null;

const nextcloudTodosPlugin = {
  id: PLUGIN_ID,
  name: "Nextcloud Todos",
  description:
    "Chat with the nextcloud-todos service — list pending todo events, fetch a todo card, "
    + "render its answer/plan, and set the Telegram delivery chat.",
  kind: "tools",
  configSchema: { type: "object", additionalProperties: false, properties: {} },
  register(api) {
    const baseUrl = process.env.NEXTCLOUD_TODOS_URL
      || "http://nextcloud-todos.nextcloud-todos.svc.cluster.local:8080";
    const token = process.env.NEXTCLOUD_TODOS_TOKEN || "";
    const nt = new NtClient(baseUrl, token);

    let _cursor = 0;

    function chatId() {
      return _chatOverride || process.env.VIKTOR_CHAT_ID;
    }

    function asText(obj) {
      return {
        content: [
          { type: "text", text: typeof obj === "string" ? obj : JSON.stringify(obj, null, 2) },
        ],
      };
    }

    async function tgSend(text) {
      // OpenClaw exposes the bot token as OPENLOBSTER_CHANNELS_TELEGRAM_TOKEN;
      // TELEGRAM_BOT_TOKEN is kept as a fallback for local dev.
      const botToken = process.env.OPENLOBSTER_CHANNELS_TELEGRAM_TOKEN
        || process.env.TELEGRAM_BOT_TOKEN;
      if (!botToken) throw new Error("no OPENLOBSTER_CHANNELS_TELEGRAM_TOKEN / TELEGRAM_BOT_TOKEN");
      const target = chatId();
      if (!target) throw new Error("no VIKTOR_CHAT_ID / chat override; cannot deliver card");
      const r = await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          chat_id: target, text, parse_mode: "HTML", disable_web_page_preview: true,
        }),
      });
      if (!r.ok) {
        const t = await r.text().catch(() => "");
        throw new Error(`telegram sendMessage ${r.status}: ${t.slice(0, 200)}`);
      }
    }

    async function announceEvent(e) {
      const card = await nt.getTodo(e.todo_id);
      const text = e.kind === "plan" ? composePlanCard(card) : composeAnswerCard(card);
      await tgSend(text);
      _activeTodoId = e.todo_id;
      await nt.consume(e.id);
    }

    async function pollTick() {
      try {
        const events = await nt.events(_cursor);
        for (const e of events) {
          try {
            await announceEvent(e);
            _cursor = Math.max(_cursor, e.id);
          } catch (err) {
            api.log?.error?.("announceEvent failed; will retry next tick", {
              eventId: e.id, err: String(err),
            });
            break;  // stop advancing the cursor on the first failure
          }
        }
      } catch (err) {
        api.log?.warn?.("events poll failed", String(err));
      }
    }

    // Initial drain on boot, then every minute.
    pollTick().catch((e) => api.log?.error?.("initial pollTick", String(e)));
    setInterval(() => pollTick().catch((e) => api.log?.error?.("pollTick", String(e))), POLL_MS);

    // ---------- TOOLS ----------

    api.registerTool({
      name: "todos_list",
      label: "Todos List",
      description: "List pending todo events on the work-queue (not yet delivered/consumed). "
        + "Each line shows the event id, kind (plan|answer), and todo id.",
      parameters: {
        type: "object",
        properties: {
          since: { type: "integer", description: "Only events with id > since (default 0)" },
        },
      },
      async execute(_id, params) {
        const since = params.since ?? 0;
        const events = await nt.events(since);
        if (!events.length) return asText("No pending todo events.");
        const lines = events.map(
          (e) => `#${e.id} [${e.kind}] todo ${e.todo_id}`
            + (e.payload?.summary ? ` — ${e.payload.summary}` : ""),
        );
        return asText(`${events.length} pending events:\n\n${lines.join("\n")}`);
      },
    });

    api.registerTool({
      name: "todos_get",
      label: "Todos Get",
      description: "Fetch the full card payload for a Personal-list todo by id: summary, the "
        + "latest plan/answer text, and the signed approve/reject/refine links.",
      parameters: {
        type: "object",
        properties: {
          id: {
            type: "integer",
            description: "Todo id. Defaults to the active todo pointer if omitted.",
          },
        },
      },
      async execute(_id, params) {
        const tid = params.id ?? _activeTodoId;
        if (!tid) return asText("no todo specified and no active pointer");
        return asText(await nt.getTodo(tid));
      },
    });

    api.registerTool({
      name: "todos_answer_for",
      label: "Todos Answer For",
      description: "Render the human-readable Telegram card for a todo: the answer card for a "
        + "research/answer todo, or the plan card (with Approve/Reject/Refine links) for a "
        + "mutating todo awaiting approval.",
      parameters: {
        type: "object",
        properties: {
          id: {
            type: "integer",
            description: "Todo id. Defaults to the active todo pointer if omitted.",
          },
        },
      },
      async execute(_id, params) {
        const tid = params.id ?? _activeTodoId;
        if (!tid) return asText("no todo specified and no active pointer");
        const card = await nt.getTodo(tid);
        const text = card.plan != null ? composePlanCard(card) : composeAnswerCard(card);
        return asText(text);
      },
    });

    api.registerTool({
      name: "todos_set_chat",
      label: "Todos Set Chat",
      description: "Set the Telegram chat id the announcement loop delivers todo cards to. "
        + "Overrides the VIKTOR_CHAT_ID env default for this session.",
      parameters: {
        type: "object",
        properties: {
          chat_id: { type: "string", description: "Telegram chat id to deliver cards to" },
        },
        required: ["chat_id"],
      },
      async execute(_id, params) {
        _chatOverride = String(params.chat_id);
        return asText(`Todo cards will now be delivered to chat ${_chatOverride}.`);
      },
    });
  },
};

export default nextcloudTodosPlugin;
