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
    "GET /chats": () => ({ chats: chats.list(), ...chats.policy() }),
    "POST /chats": (body) => ({ id: chats.addNumber(body?.number), selected: chats.watchedCount() }),
    "PUT /selection": (body) => {
      if (Array.isArray(body?.chat_ids)) chats.select(body.chat_ids); // older clients
      else if (body && (body.mode === "unknown" || body.mode === "manual")) {
        if (![body.include ?? [], body.exclude ?? []].every(Array.isArray)) throw Object.assign(new Error("include/exclude must be lists"), { status: 400 });
        chats.setPolicy(body);
      } else throw Object.assign(new Error("send {mode, include, exclude}"), { status: 400 });
      return { selected: chats.watchedCount(), ...chats.policy() };
    },
  };

  return http.createServer(async (req, res) => {
    const handler = routes[`${req.method} ${req.url?.split("?")[0]}`];
    try {
      if (!handler) throw Object.assign(new Error("not found"), { status: 404 });
      let body = null;
      if (req.method === "PUT" || req.method === "POST") {
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
