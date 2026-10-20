// WhatsApp on the phone:
//  1. Check an exported chat: analyzed on the phone, only links go to the computer.
//  2. Live alerts: the computer's WhatsApp watcher (start-whatsapp.bat) flags messages
//     and calls from unknown numbers; the paired phone shows them.
import { ADVICE, topReasons, type Result, type RiskLevel, type Signal } from "@amaan/core";
import { useEffect, useState } from "react";
import { ActivityIndicator, Text, View } from "react-native";
import { whatsappLive, type Pairing, type WaAlert, type WaLive } from "./server";
import { Button, C, Card, Chip, LOOK, s } from "./ui";
import { analyzeChat, defangText, pickChat, type ChatFinding, type ChatReport } from "./whatsapp";

const POLL_MS = 15_000;

export default function WhatsAppTab({ pairing }: { pairing: Pairing | null }) {
  return (
    <View style={{ gap: 14 }}>
      <ChatCheck pairing={pairing} />
      <LiveAlerts pairing={pairing} />
    </View>
  );
}

function ChatCheck({ pairing }: { pairing: Pairing | null }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<ChatReport | null>(null);

  async function run() {
    setError(null);
    setReport(null);
    try {
      const ex = await pickChat();
      if (!ex) return;
      setBusy("Reading the chat…");
      setReport(await analyzeChat(ex, pairing, setBusy));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <>
      <Card>
        <Text style={s.h2}>Check a WhatsApp chat</Text>
        <Text style={s.muted}>
          In WhatsApp open the chat → tap the name → <Text style={{ fontWeight: "700" }}>Export chat</Text> → save it to
          Files. Choose “Attach media” to also scan photos for QR codes. Then pick the file here.
        </Text>
        <Button title={busy ? "Checking…" : "📄 Pick exported chat"} disabled={!!busy} onPress={run} />
        {busy && (
          <View style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
            <ActivityIndicator />
            <Text style={s.muted}>{busy}</Text>
          </View>
        )}
        {error && <Text style={s.note}>⚠️ {error}</Text>}
      </Card>
      {report && <Report r={report} />}
    </>
  );
}

function Report({ r }: { r: ChatReport }) {
  const look = LOOK[r.riskLevel];
  const flagged = r.findings.length;
  return (
    <View style={{ gap: 12 }}>
      <View style={[s.verdict, { backgroundColor: look.bg, borderColor: look.border }]}>
        <Text style={[s.verdictTitle, { color: look.fg }]}>
          {look.icon} {flagged ? `${flagged} suspicious message${flagged > 1 ? "s" : ""}` : "No warning signs found"}
        </Text>
        <Text style={{ color: look.fg }}>
          {r.title}: {r.messagesTotal} messages, {r.linksFound} links ({r.linksChecked} checked online)
          {r.imagesChecked ? `, ${r.imagesChecked} photo${r.imagesChecked > 1 ? "s" : ""} scanned` : ""}.
        </Text>
      </View>
      {r.notes.map((n) => <Text key={n} style={s.note}>ℹ️ {n}</Text>)}
      {r.findings.map((f) => <FindingCard key={f.key} f={f} />)}
    </View>
  );
}

function Reasons({ reasons }: { reasons: Signal[] }) {
  return (
    <>
      {reasons.map((sig) => (
        <View key={sig.id + sig.title} style={{ flexDirection: "row", gap: 6, alignItems: "center", flexWrap: "wrap" }}>
          <Text style={{ color: C.ink, fontSize: 14 }}>• {sig.title}</Text>
          <Chip label={sig.label} />
        </View>
      ))}
    </>
  );
}

function Head({ level, who, when }: { level: RiskLevel; who: string; when: string }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", gap: 8 }}>
      <Text style={{ fontWeight: "700", color: LOOK[level].fg, flexShrink: 1 }}>{LOOK[level].icon} {ADVICE[level].title} · {who}</Text>
      <Text style={s.muted}>{when}</Text>
    </View>
  );
}

function FindingCard({ f }: { f: ChatFinding }) {
  return (
    <Card>
      <Head level={f.result.riskLevel} who={f.sender || "Photo"} when={[f.date, f.time].filter(Boolean).join(" ")} />
      <Text style={s.mono} selectable>{defangText(f.text)}</Text>
      <Reasons reasons={topReasons(f.result, 3)} />
    </Card>
  );
}

function LiveAlerts({ pairing }: { pairing: Pairing | null }) {
  const [live, setLive] = useState<WaLive | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!pairing) return;
    let stop = false;
    const load = () => whatsappLive(pairing)
      .then((l) => { if (!stop) { setLive(l); setError(null); } })
      .catch((e) => { if (!stop) setError(e instanceof Error ? e.message : String(e)); });
    load();
    const t = setInterval(load, POLL_MS); // only while this screen is open
    return () => { stop = true; clearInterval(t); };
  }, [pairing]);

  return (
    <Card>
      <Text style={s.h2}>Live alerts from your computer</Text>
      {!pairing ? (
        <Text style={s.muted}>Connect to your computer (top right) to see messages and calls its WhatsApp watcher flagged.</Text>
      ) : error ? (
        <Text style={s.note}>⚠️ {error}</Text>
      ) : !live ? (
        <ActivityIndicator />
      ) : (
        <>
          <Text style={s.muted}>{statusText(live.status)}</Text>
          {live.alerts.length === 0 && live.status.state === "connected" && <Text style={s.muted}>Nothing suspicious so far.</Text>}
          {live.alerts.map((a) => <AlertRow key={a.id} a={a} />)}
        </>
      )}
    </Card>
  );
}

function statusText(st: WaLive["status"]): string {
  if (!st.enabled) return "WhatsApp watching is off. On the computer, start Amaan with start-whatsapp.bat (or start-everything.bat).";
  if (st.state !== "connected") return "WhatsApp isn't linked yet. On the computer: Amaan → WhatsApp tab → Link WhatsApp.";
  const who = st.mode === "unknown" ? "unknown numbers and callers" : `${st.selected ?? 0} chosen chats`;
  return `Watching ${who} · ${st.checked_total ?? 0} messages checked. Updates every 15 s while this screen is open.`;
}

function AlertRow({ a }: { a: WaAlert }) {
  const ev = a.evidence;
  const asResult = { signals: ev.signals, items: ev.items.map((i) => ({ signals: i.signals })) } as unknown as Result;
  const isCall = a.kind === "call" || a.kind === "video_call";
  return (
    <View style={s.item}>
      <Head level={ev.risk_level} who={a.chat_name || a.sender || "Unknown"}
        when={new Date(a.received_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} />
      <Text style={s.mono} selectable>{isCall ? (a.kind === "video_call" ? "📹 Video call" : "📞 Call") : defangText(a.text)}</Text>
      <Reasons reasons={topReasons(asResult, 3)} />
    </View>
  );
}
