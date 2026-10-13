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
  const wa = new WhatsApp({
    authDir: dir,
    chats: new Chats(dir),
    forward: async () => {},
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
  return { wa, sockets, close, tick };
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
