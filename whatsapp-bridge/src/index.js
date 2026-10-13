// Amaan WhatsApp bridge entry point. Optional; started only with the
// "whatsapp" profile (start-whatsapp.bat / amaan.ps1 up -WhatsApp).
import { Chats } from "./chats.js";
import { makeForwarder } from "./forward.js";
import { makeServer } from "./server.js";
import { WhatsApp } from "./wa.js";

const authDir = process.env.WA_AUTH_DIR ?? "./wa-session";
const port = Number(process.env.PORT ?? 8090);
const host = process.env.HOST ?? "127.0.0.1";
const backendUrl = process.env.AMAAN_BACKEND_URL ?? "http://127.0.0.1:8000";
const token = process.env.AMAAN_BRIDGE_TOKEN;
if (!token) console.warn("AMAAN_BRIDGE_TOKEN is not set: the backend will refuse forwarded messages.");

const chats = new Chats(authDir);
const wa = new WhatsApp({ authDir, chats, forward: makeForwarder({ backendUrl, token }) });
makeServer(wa, chats).listen(port, host, () => console.log(`WhatsApp bridge listening on ${host}:${port}`));

// Reconnect automatically if this computer was linked before.
if (wa.hasSession()) wa.connect();

// Save the chat list before Docker stops the container.
for (const sig of ["SIGTERM", "SIGINT"]) {
  process.on(sig, () => {
    try {
      chats.flush();
    } finally {
      process.exit(0);
    }
  });
}
