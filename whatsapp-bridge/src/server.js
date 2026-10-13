// Small HTTP API used only by the Amaan backend (not exposed outside Docker).
import http from "node:http";

export function makeServer(wa, chats) {
  const routes = {
    "GET /status": () => wa.status(),
    "POST /link": async () => {
      await wa.connect();
      return wa.status();
    },
    "POST /logout": async () => {
      await wa.logout();
      return wa.status();
    },
    "GET /chats": () => ({ chats: chats.list() }),
    "PUT /selection": (body) => {
      if (!Array.isArray(body?.chat_ids)) throw Object.assign(new Error("chat_ids must be a list"), { status: 400 });
      chats.select(body.chat_ids);
      return { selected: chats.selection.size };
    },
  };

  return http.createServer(async (req, res) => {
    const handler = routes[`${req.method} ${req.url?.split("?")[0]}`];
    try {
      if (!handler) throw Object.assign(new Error("not found"), { status: 404 });
      let body = null;
      if (req.method === "PUT") {
        let raw = "";
        for await (const chunk of req) {
          raw += chunk;
          if (raw.length > 1_000_000) throw Object.assign(new Error("too large"), { status: 413 });
        }
        body = raw ? JSON.parse(raw) : null;
      }
      const out = await handler(body);
      res.writeHead(200, { "Content-Type": "application/json", "Cache-Control": "no-store" });
      res.end(JSON.stringify(out));
    } catch (e) {
      res.writeHead(e.status ?? 500, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ detail: e.status ? e.message : "bridge error" }));
    }
  });
}
