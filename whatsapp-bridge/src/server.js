// Small HTTP API used only by the Amaan backend (not exposed outside Docker).
import http from "node:http";

const httpError = (status, message) => Object.assign(new Error(message), { status });

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
      if (body?.mode !== "unknown" && body?.mode !== "manual") throw httpError(400, "send {mode, include, exclude}");
      if (![body.include ?? [], body.exclude ?? []].every(Array.isArray)) throw httpError(400, "include/exclude must be lists");
      chats.setPolicy(body);
      return { selected: chats.watchedCount(), ...chats.policy() };
    },
  };

  return http.createServer(async (req, res) => {
    const handler = routes[`${req.method} ${req.url?.split("?")[0]}`];
    try {
      if (!handler) throw httpError(404, "not found");
      let body = null;
      if (req.method === "PUT" || req.method === "POST") {
        let raw = "";
        for await (const chunk of req) {
          raw += chunk;
          if (raw.length > 1_000_000) throw httpError(413, "too large");
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
