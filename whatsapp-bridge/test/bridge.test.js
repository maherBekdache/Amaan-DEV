import { test } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { extractContent, shouldCheck, unwrap } from "../src/extract.js";
import { Chats } from "../src/chats.js";
import { makeForwarder } from "../src/forward.js";
import { makeServer } from "../src/server.js";

const tmp = () => fs.mkdtempSync(path.join(os.tmpdir(), "amaan-bridge-"));
const msg = (remoteJid, message, extra = {}) => ({ key: { remoteJid, fromMe: false, ...extra }, message });

test("extracts text, captions, images and voice notes", () => {
  assert.deepEqual(extractContent({ conversation: "hi bit.ly/x" }), { kind: "text", text: "hi bit.ly/x" });
  assert.deepEqual(extractContent({ extendedTextMessage: { text: "link" } }), { kind: "text", text: "link" });
  assert.deepEqual(extractContent({ imageMessage: { caption: "scan me", fileLength: 1000 } }),
    { kind: "image", text: "scan me", imageBytes: 1000 });
  assert.deepEqual(extractContent({ audioMessage: {} }), { kind: "voice", text: "" });
  assert.equal(extractContent({ stickerMessage: {} }), null);
  assert.equal(extractContent({ reactionMessage: { text: "👍" } }), null);
});

test("unwraps disappearing and view-once messages", () => {
  const m = { ephemeralMessage: { message: { viewOnceMessageV2: { message: { conversation: "x" } } } } };
  assert.deepEqual(unwrap(m), { conversation: "x" });
});

test("only new incoming messages from selected chats are checked", () => {
  const sel = new Set(["111@s.whatsapp.net", "g1@g.us"]);
  assert.equal(shouldCheck(msg("111@s.whatsapp.net", {}), "notify", sel), true);
  assert.equal(shouldCheck(msg("g1@g.us", {}), "notify", sel), true);
  assert.equal(shouldCheck(msg("222@s.whatsapp.net", {}), "notify", sel), false); // not selected
  assert.equal(shouldCheck(msg("111@s.whatsapp.net", {}), "append", sel), false); // history, not new
  assert.equal(shouldCheck(msg("111@s.whatsapp.net", {}, { fromMe: true }), "notify", sel), false); // own message
  assert.equal(shouldCheck(msg("status@broadcast", {}), "notify", new Set(["status@broadcast"])), false);
  // WhatsApp's newer "LID" ids: match on the alternate id too
  assert.equal(shouldCheck(msg("999@lid", {}, { remoteJidAlt: "111@s.whatsapp.net" }), "notify", sel), true);
});

test("chat selection is saved and survives a restart", () => {
  const dir = tmp();
  const c = new Chats(dir);
  c.upsert("111@s.whatsapp.net", "Mom");
  c.upsert("g1@g.us", "Family", true);
  c.upsert("status@broadcast", "Status"); // ignored
  c.select(["g1@g.us", "status@broadcast"]);
  assert.deepEqual(c.list().map((x) => [x.name, x.selected]), [["Family", true], ["Mom", false]]);
  assert.deepEqual([...new Chats(dir).selection], ["g1@g.us"]);
  assert.equal(c.nameOf(["555@s.whatsapp.net"]), "+555");
});

test("forwarder sends text and image with the bridge token", async () => {
  let call;
  const forward = makeForwarder({ backendUrl: "http://be", token: "t0k", fetchImpl: async (url, init) => {
    call = { url, init };
    return { ok: true };
  } });
  await forward({ chatId: "1@s", chatName: "A", sender: "B", timestamp: 5, kind: "image", text: "cap" }, Buffer.from("img"));
  assert.equal(call.url, "http://be/whatsapp/ingest");
  assert.equal(call.init.headers["X-Bridge-Token"], "t0k");
  assert.equal(call.init.body.get("kind"), "image");
  assert.equal(call.init.body.get("text"), "cap");
  assert.ok(call.init.body.get("file"));
});

test("HTTP API: status, chats and selection", async () => {
  const chats = new Chats(tmp());
  chats.upsert("1@s.whatsapp.net", "Ali");
  const wa = { status: () => ({ state: "connected" }), connect: async () => {}, logout: async () => {} };
  const server = makeServer(wa, chats).listen(0);
  const base = `http://127.0.0.1:${server.address().port}`;
  try {
    assert.equal((await (await fetch(`${base}/status`)).json()).state, "connected");
    const put = await fetch(`${base}/selection`, { method: "PUT", body: JSON.stringify({ chat_ids: ["1@s.whatsapp.net"] }) });
    assert.equal((await put.json()).selected, 1);
    assert.equal((await (await fetch(`${base}/chats`)).json()).chats[0].selected, true);
    assert.equal((await fetch(`${base}/nope`)).status, 404);
    assert.equal((await fetch(`${base}/selection`, { method: "PUT", body: "{}" })).status, 400);
  } finally {
    server.close();
  }
});

test("chat list survives a restart and merges privacy ids with phone ids", () => {
  const dir = tmp();
  const c = new Chats(dir);
  c.upsert("999@lid", null); // first seen only by privacy id
  c.upsertContact({ id: "96170111222@s.whatsapp.net", name: "Taha", lid: "999@lid" });
  c.upsertWeak("96170111222@s.whatsapp.net", "T-bone"); // sender's own name never overrides the contact name
  c.select(["999@lid"]); // selecting either id selects the person
  c.flush();
  const again = new Chats(dir);
  assert.deepEqual(again.list().map((x) => [x.id, x.name, x.selected]), [["96170111222@s.whatsapp.net", "Taha", true]]);
  assert.equal(again.isSelected(["999@lid"]), true);
  assert.equal(again.nameOf(["999@lid"]), "Taha");
});

test("add a chat by phone number", () => {
  const c = new Chats(tmp());
  const id = c.addNumber("+961 70 123 456");
  assert.equal(id, "96170123456@s.whatsapp.net");
  assert.equal(c.list()[0].selected, true);
  assert.throws(() => c.addNumber("123"), /country code/);
});

test("unsaved privacy-id contacts are not shown as phone numbers", () => {
  const c = new Chats(tmp());
  c.upsert("123456789@lid", null);
  assert.equal(c.list()[0].name, "Unsaved contact");
});
