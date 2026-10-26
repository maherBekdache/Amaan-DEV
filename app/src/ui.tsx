// Result card and small building blocks. Links are only ever shown defanged
// (example[.]com) and never made tappable: the app never opens a checked link.
// It only opens other sites' rating pages (VirusTotal, …) when the user taps one.
import { ADVICE, lookupLinks, topReasons, type EvidenceLabel, type Item, type RiskLevel, type Severity } from "@amaan/core";
import { useState, type ReactNode } from "react";
import { ActivityIndicator, Linking, Pressable, StyleSheet, Text, View } from "react-native";
import { explainResult } from "./ai";
import type { Checked } from "./check";
import type { AIOpinion, Pairing } from "./server";

export const C = {
  ink: "#0f172a", muted: "#64748b", line: "#e2e8f0", bg: "#f8fafc", card: "#ffffff", brand: "#0f172a",
};

export const LOOK: Record<RiskLevel, { icon: string; bg: string; border: string; fg: string }> = {
  High: { icon: "⛔", bg: "#fef2f2", border: "#fca5a5", fg: "#7f1d1d" },
  Medium: { icon: "⚠️", bg: "#fffbeb", border: "#fcd34d", fg: "#78350f" },
  Low: { icon: "✅", bg: "#ecfdf5", border: "#6ee7b7", fg: "#064e3b" },
};
const DOT: Record<Severity, string> = { high: "#ef4444", medium: "#f59e0b", low: "#facc15", good: "#10b981", info: "#38bdf8" };
const LABEL: Record<EvidenceLabel, [string, string, string]> = {
  automated_indicator: ["Automated check", "#e2e8f0", "#334155"],
  community_report: ["Reported by others", "#e9d5ff", "#581c87"],
  verified: ["Verified", "#a7f3d0", "#064e3b"],
};
const KIND: Record<string, string> = { url: "Link", wifi: "Wi-Fi", tel: "Phone call", sms: "SMS", mailto: "Email", geo: "Location", text: "Text" };

export function Button({ title, onPress, kind = "primary", disabled }: { title: string; onPress: () => void; kind?: "primary" | "plain"; disabled?: boolean }) {
  return (
    <Pressable accessibilityRole="button" onPress={onPress} disabled={disabled}
      style={({ pressed }) => [s.btn, kind === "plain" && s.btnPlain, (pressed || disabled) && { opacity: 0.6 }]}>
      <Text style={[s.btnText, kind === "plain" && { color: C.ink }]}>{title}</Text>
    </Pressable>
  );
}

export const Card = ({ children }: { children: ReactNode }) => <View style={s.card}>{children}</View>;

export function Chip({ label }: { label: EvidenceLabel }) {
  const [text, bg, fg] = LABEL[label];
  return <Text style={[s.chip, { backgroundColor: bg, color: fg }]}>{text}</Text>;
}

export function ResultCard({ r, pairing }: { r: Checked; pairing: Pairing | null }) {
  const look = LOOK[r.riskLevel];
  const { title, advice } = ADVICE[r.riskLevel];
  const reasons = topReasons(r);
  return (
    <View style={{ gap: 12 }}>
      <View style={[s.verdict, { backgroundColor: look.bg, borderColor: look.border }]} accessibilityLiveRegion="polite">
        <Text style={[s.verdictTitle, { color: look.fg }]}>{look.icon} {title}</Text>
        <Text style={{ color: look.fg, fontSize: 15 }}>{advice}</Text>
      </View>

      {r.serverNote && <Text style={s.note}>ℹ️ {r.serverNote}</Text>}
      {r.warnings.map((w) => <Text key={w} style={s.note}>ℹ️ {w}</Text>)}

      <Card>
        <Text style={s.h2}>Why?</Text>
        {reasons.length === 0 && <Text style={s.muted}>No warning signs in this message.</Text>}
        {reasons.map((sig) => (
          <View key={sig.id + sig.title} style={s.reason}>
            <View style={[s.dot, { backgroundColor: DOT[sig.severity] }]} />
            <View style={{ flex: 1, gap: 2 }}>
              <Text style={s.reasonTitle}>{sig.title}</Text>
              {!!sig.detail && <Text style={s.muted}>{sig.detail}</Text>}
              <View style={{ flexDirection: "row" }}><Chip label={sig.label} /></View>
            </View>
          </View>
        ))}
      </Card>

      {pairing && <AISummary r={r} pairing={pairing} />}

      {r.items.length > 0 && (
        <Card>
          <Text style={s.h2}>What we found</Text>
          {r.items.map((it, i) => (
            <View key={i} style={s.item}>
              <Text style={s.itemKind}>{KIND[it.kind] ?? it.kind} · {LOOK[it.riskLevel].icon} {ADVICE[it.riskLevel].title}</Text>
              <Text style={s.mono} selectable>{it.display}</Text>
              {it.kind === "url" && <Text style={s.muted}>{it.checked ? "Checked online (sandbox + safety lists)" : "Not checked online"}</Text>}
              <Lookups item={it} />
            </View>
          ))}
        </Card>
      )}
    </View>
  );
}

/** AI summary from the paired computer, on request (it can take up to a minute). */
function AISummary({ r, pairing }: { r: Checked; pairing: Pairing }) {
  const [op, setOp] = useState<AIOpinion | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      setOp(await explainResult(pairing, r, r.inputType ?? "text"));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <Text style={s.h2}>🤖 AI summary</Text>
      {!op && !busy && <Button title="Explain with AI" kind="plain" onPress={run} />}
      {busy && <View style={{ flexDirection: "row", gap: 8, alignItems: "center" }}><ActivityIndicator /><Text style={s.muted}>Asking the AI on your computer…</Text></View>}
      {error && <Text style={s.note}>⚠️ {error}</Text>}
      {op && !op.available && <Text style={s.muted}>{op.message}</Text>}
      {op?.available && (
        <View style={{ gap: 6 }}>
          <Text style={{ color: C.ink, fontSize: 15 }}>{op.summary}</Text>
          {op.red_flags.map((f) => <Text key={f} style={s.muted}>• {f}</Text>)}
          {!!op.advice && <Text style={{ color: C.ink, fontWeight: "600" }}>{op.advice}</Text>}
        </View>
      )}
      <Text style={[s.muted, { fontSize: 12 }]}>Sends Amaan's findings to your computer's AI, not your message. An AI can be wrong; the verdict above comes from the evidence.</Text>
    </Card>
  );
}

/** "Check it yourself": other sites' rating of this link, opened in the browser on tap. */
function Lookups({ item }: { item: Item }) {
  const [open, setOpen] = useState(false);
  if (item.kind !== "url" || !item.url || !item.hostAscii) return null;
  return (
    <View style={{ gap: 6, marginTop: 4 }}>
      <Pressable onPress={() => setOpen(!open)} accessibilityRole="button">
        <Text style={{ color: "#0f766e", fontWeight: "600" }}>{open ? "▾" : "▸"} Check it yourself on other sites</Text>
      </Pressable>
      {open && (
        <>
          <Text style={[s.muted, { fontSize: 12 }]}>Opens that site's rating in your browser. The site sees the link, not your message.</Text>
          {lookupLinks(item.url, item.hostAscii).map((l) => (
            <Pressable key={l.id} accessibilityRole="link" onPress={() => Linking.openURL(l.href)}
              style={({ pressed }) => [s.lookup, pressed && { opacity: 0.6 }]}>
              <Text style={{ color: "#115e59", fontWeight: "600" }}>{l.name} ↗</Text>
              <Text style={[s.muted, { fontSize: 12 }]}>{l.about}</Text>
            </Pressable>
          ))}
        </>
      )}
    </View>
  );
}

export const s = StyleSheet.create({
  btn: { backgroundColor: C.brand, paddingVertical: 14, paddingHorizontal: 16, borderRadius: 12, alignItems: "center", flexGrow: 1 },
  btnPlain: { backgroundColor: C.card, borderWidth: 1, borderColor: C.line },
  btnText: { color: "#fff", fontWeight: "600", fontSize: 16 },
  card: { backgroundColor: C.card, borderRadius: 14, borderWidth: 1, borderColor: C.line, padding: 14, gap: 10 },
  verdict: { borderWidth: 1, borderRadius: 14, padding: 16, gap: 6 },
  verdictTitle: { fontSize: 22, fontWeight: "700" },
  h2: { fontSize: 16, fontWeight: "700", color: C.ink },
  muted: { color: C.muted, fontSize: 14 },
  note: { color: C.ink, backgroundColor: "#f1f5f9", padding: 10, borderRadius: 10, fontSize: 14 },
  reason: { flexDirection: "row", gap: 10, alignItems: "flex-start" },
  reasonTitle: { fontWeight: "600", color: C.ink, fontSize: 15 },
  dot: { width: 10, height: 10, borderRadius: 5, marginTop: 6 },
  chip: { fontSize: 11, fontWeight: "600", paddingHorizontal: 6, paddingVertical: 2, borderRadius: 6, overflow: "hidden" },
  item: { gap: 2, borderTopWidth: 1, borderTopColor: C.line, paddingTop: 8 },
  itemKind: { fontSize: 13, fontWeight: "600", color: C.muted },
  lookup: { borderWidth: 1, borderColor: C.line, borderRadius: 10, paddingVertical: 8, paddingHorizontal: 10 },
  mono: { fontFamily: "monospace", color: C.ink, fontSize: 14 },
});
