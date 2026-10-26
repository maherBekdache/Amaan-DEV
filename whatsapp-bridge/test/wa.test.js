import { test } from "node:test";
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { Chats } from "../src/chats.js";
import { WhatsApp } from "../src/wa.js";

function setup() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "amaan-wa-"));
  const sockets = [];
  const sent = [];
  const wa = new WhatsApp({
    authDir: dir,
    chats: new Chats(dir),
    forward: async (meta, media) => { sent.push({ ...meta, media }); },
    loadAuth: async () => ({ state: {}, saveCreds: () => {} }),
    fetchVersion: async () => ({ version: [2, 3000, 1] }),
    makeSocket: () => {
      const ev = new EventEmitter();
      const sock = { ev, user: { id: "961@s.whatsapp.net", name: "Test" }, end() {}, logout: async () => {},
                     groupFetchAllParticipating: async () => ({}) };
      sockets.push(sock);
      return sock;
    },
  });
  const close = (code) => sockets.at(-1).ev.emit("connection.update", { connection: "close", lastDisconnect: { error: { output: { statusCode: code } } } });
  const tick = () => new Promise((r) => setTimeout(r, 10));
  return { wa, sockets, close, tick, sent };
}

test("calling connect twice at once opens only one connection", async () => {
  const { wa, sockets } = setup();
  await Promise.all([wa.connect(), wa.connect(), wa.connect()]);
  assert.equal(sockets.length, 1);
});

test("connection replaced by another session stops instead of looping", async () => {
  const { wa, sockets, close, tick } = setup();
  await wa.connect();
  close(440);
  await tick();
  assert.equal(wa.state, "idle");
  assert.match(wa.error, /Another WhatsApp Web session/);
  await new Promise((r) => setTimeout(r, 2200));
  assert.equal(sockets.length, 1); // no reconnect attempt
});

test("restart required (normal after scanning) reconnects right away", async () => {
  const { wa, sockets, close, tick } = setup();
  await wa.connect();
  close(515);
  await tick();
  assert.equal(sockets.length, 2);
  sockets[1].ev.emit("connection.update", { connection: "open" });
  await tick();
  assert.equal(wa.state, "connected");
  assert.equal(wa.error, null);
});

test("dropped connection retries and shows why", async () => {
  const { wa, sockets, close, tick } = setup();
  await wa.connect();
  close(428);
  await tick();
  assert.equal(wa.state, "connecting");
  assert.match(wa.error, /connection closed, code 428\)\. Retrying 1\/5/);
  await new Promise((r) => setTimeout(r, 2200));
  assert.equal(sockets.length, 2);
});

test("bad saved session is cleared so the user can link again", async () => {
  const { wa, close, tick } = setup();
  await wa.connect();
  close(500);
  await tick();
  assert.equal(wa.state, "idle");
  assert.match(wa.error, /damaged/);
});

test("start over (logout) works while stuck connecting", async () => {
  const { wa, sockets, close, tick } = setup();
  await wa.connect();
  close(428);
  await tick();
  await wa.logout();
  const before = sockets.length;
  assert.equal(wa.state, "idle");
  assert.equal(wa.sock, null);
  await new Promise((r) => setTimeout(r, 2200));
  assert.equal(wa.state, "idle"); // the scheduled retry was cancelled
  assert.equal(sockets.length, before);
});


test("an incoming call from an unknown number is reported, never answered", async () => {
  const reports = [];
  const { wa, sockets } = setup();
  wa.forward = async (meta) => reports.push(meta);
  await wa.connect();
  sockets[0].ev.emit("call", [{ from: "777@lid", callerPn: "447700900123@s.whatsapp.net", status: "offer", id: "c1", date: new Date() }]);
  sockets[0].ev.emit("call", [{ from: "777@lid", status: "ringing", id: "c1", date: new Date() }]); // same call, ignored
  await new Promise((r) => setTimeout(r, 10));
  assert.equal(reports.length, 1);
  assert.equal(reports[0].kind, "call");
  assert.equal(reports[0].chatId, "447700900123@s.whatsapp.net");
});

test("calls from unknown numbers: reported when ringing, and a short unanswered ring is reported again", async () => {
  const { wa, sockets, sent } = setup();
  await wa.connect();
  const call = (id, status, sec, extra = {}) => sockets[0].ev.emit("call", [{ id, from: "88123@s.whatsapp.net", status,
    date: new Date(1_000_000 + sec * 1000), isGroup: false, ...extra }]);
  call("c1", "offer", 0);
  call("c1", "timeout", 3);
  call("c2", "offer", 10, { isVideo: true });
  call("c2", "accept", 15);
  call("c2", "terminate", 60);
  assert.deepEqual(sent.map((m) => [m.kind, m.callId, m.ringSeconds]), [
    ["call", "c1", undefined], ["missed_call", "c1", 3], ["video_call", "c2", undefined]]);
  assert.equal(sent[0].chatId, "88123@s.whatsapp.net");
});

test("calls from saved contacts are not reported", async () => {
  const { wa, sockets, sent } = setup();
  await wa.connect();
  wa.chats.upsertContact({ id: "96170111222@s.whatsapp.net", name: "Mom" });
  sockets[0].ev.emit("call", [{ id: "c3", from: "96170111222@s.whatsapp.net", status: "offer", date: new Date(), isGroup: false }]);
  sockets[0].ev.emit("call", [{ id: "c3", from: "96170111222@s.whatsapp.net", status: "timeout", date: new Date(), isGroup: false }]);
  assert.equal(sent.length, 0);
});
