// Thin client for the nextcloud-todos service REST API. Used by the polling
// loop (to fetch event payloads for the Telegram card) and by the plugin tools
// (for in-chat reads). Centralises base URL + bearer token + JSON shape.
// Cloned from recruiter-responder/openclaw-plugin/rrClient.mjs.

export class NtClient {
  constructor(baseUrl, token) {
    this.baseUrl = baseUrl.replace(/\/$/, "");
    this.token = token;
  }

  async _req(method, path, body) {
    const res = await fetch(`${this.baseUrl}${path}`, {
      method,
      headers: {
        "Authorization": `Bearer ${this.token}`,
        "Content-Type": "application/json",
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${method} ${path} -> ${res.status}: ${text.slice(0, 300)}`);
    }
    return res.status === 204 ? null : res.json();
  }

  events(since) {
    return this._req("GET", `/api/events?since=${since}`);
  }

  consume(id) {
    return this._req("POST", `/api/events/${id}/consume`);
  }

  getTodo(id) {
    return this._req("GET", `/api/get/${id}`);
  }
}
