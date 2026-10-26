// Amaan phone app: paste a message or link, scan a QR code, pick a screenshot, or check WhatsApp.
// Messages, codes and images are analyzed on the phone. Only links are sent to the
// paired computer, which checks them in URL.vet's sandbox and against safety lists.
import { CameraView, scanFromURLAsync, useCameraPermissions, type BarcodeScanningResult } from "expo-camera";
import * as Clipboard from "expo-clipboard";
import * as ImagePicker from "expo-image-picker";
import { StatusBar } from "expo-status-bar";
import { useEffect, useRef, useState } from "react";
import { ActivityIndicator, KeyboardAvoidingView, Platform, Pressable, ScrollView, Text, TextInput, View } from "react-native";
import { SafeAreaProvider, SafeAreaView } from "react-native-safe-area-context";
import { runCheck, type Checked } from "./src/check";
import "./src/qrDecoder";
import { forgetPairing, health, hostOf, isLocalNetwork, loadPairing, parsePairing, savePairing, type Pairing } from "./src/server";
import { Button, C, Card, ResultCard, s } from "./src/ui";
import WhatsAppTab from "./src/WhatsAppTab";

type Scan = null | "check" | "pair";
type Tab = "check" | "whatsapp";

export default function App() {
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <Main />
    </SafeAreaProvider>
  );
}

function Main() {
  const [text, setText] = useState("");
  const [result, setResult] = useState<Checked | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [scan, setScan] = useState<Scan>(null);
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [showConnect, setShowConnect] = useState(false);
  const [pairCode, setPairCode] = useState(""); // kept here: the scanner replaces the screen
  const [tab, setTab] = useState<Tab>("check");

  useEffect(() => {
    loadPairing().then(setPairing);
  }, []);

  async function check(input: { text?: string; qr?: string[] }) {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      setResult(await runCheck(input, pairing));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function onCodes(codes: string[]) {
    setScan(null);
    // Everything in a QR code is untrusted: it is only analyzed, never opened.
    if (codes.some((c) => parsePairing(c))) {
      setError("That's an Amaan pairing code. To connect this phone, use “Connect to computer” at the top.");
      return;
    }
    check({ qr: codes });
  }

  async function pickScreenshot() {
    setError(null);
    const pick = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ["images"], quality: 1 });
    if (pick.canceled || !pick.assets?.[0]) return;
    try {
      const codes = (await scanFromURLAsync(pick.assets[0].uri, ["qr"])).map((c) => c.data).filter(Boolean);
      if (!codes.length) setError("No QR code found in this picture. Try a sharper screenshot.");
      else onCodes(codes);
    } catch {
      setError("Couldn't read this picture. Try another screenshot.");
    }
  }

  async function paste() {
    const t = await Clipboard.getStringAsync();
    if (t) setText(t);
  }

  if (scan) return <Scanner mode={scan} onCodes={scan === "pair" ? (c) => { setScan(null); setShowConnect(true); setPairCode(c[0]); } : onCodes} onCancel={() => setScan(null)} />;

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: C.bg }}>
      <KeyboardAvoidingView behavior={Platform.OS === "ios" ? "padding" : undefined} style={{ flex: 1 }}>
        <ScrollView contentContainerStyle={{ padding: 16, gap: 14, maxWidth: 640, width: "100%", alignSelf: "center" }} keyboardShouldPersistTaps="handled">
          <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
            <Text style={{ fontSize: 26, fontWeight: "800", color: C.ink }}>🛡️ Amaan</Text>
            <Pressable onPress={() => setShowConnect((v) => !v)} accessibilityRole="button">
              <Text style={{ color: pairing ? "#047857" : C.muted, fontWeight: "600" }}>
                {pairing ? `● ${hostOf(pairing.server)}` : "○ Connect to computer"}
              </Text>
            </Pressable>
          </View>

          {showConnect && <Connect pairing={pairing} code={pairCode} setCode={setPairCode} onChange={(p) => { setPairing(p); if (p) setShowConnect(false); }} onScan={() => setScan("pair")} />}

          <View style={{ flexDirection: "row", gap: 8 }} accessibilityRole="tablist">
            {([["check", "🔍 Check"], ["whatsapp", "💬 WhatsApp"]] as const).map(([id, label]) => (
              <Pressable key={id} onPress={() => setTab(id)} accessibilityRole="tab" accessibilityState={{ selected: tab === id }}
                style={{ flex: 1, paddingVertical: 10, borderRadius: 10, alignItems: "center", backgroundColor: tab === id ? C.ink : C.card, borderWidth: 1, borderColor: C.line }}>
                <Text style={{ fontWeight: "600", color: tab === id ? "#fff" : C.ink }}>{label}</Text>
              </Pressable>
            ))}
          </View>

          {tab === "whatsapp" ? <WhatsAppTab pairing={pairing} /> : <>
          <Card>
            <Text style={s.h2}>Is this a scam?</Text>
            <TextInput value={text} onChangeText={setText} multiline placeholder="Paste a message or a link…"
              autoCorrect={false} autoCapitalize="none" maxLength={20000}
              style={{ minHeight: 110, borderWidth: 1, borderColor: C.line, borderRadius: 10, padding: 10, fontSize: 16, color: C.ink, textAlignVertical: "top" }} />
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Button title="Paste" kind="plain" onPress={paste} />
              <Button title={busy ? "Checking…" : "Check"} disabled={busy || !text.trim()} onPress={() => check({ text })} />
            </View>
            <View style={{ flexDirection: "row", gap: 10 }}>
              <Button title="📷 Scan QR" kind="plain" disabled={busy} onPress={() => setScan("check")} />
              <Button title="🖼️ Screenshot" kind="plain" disabled={busy} onPress={pickScreenshot} />
            </View>
          </Card>

          {busy && (
            <View style={{ flexDirection: "row", gap: 10, alignItems: "center" }}>
              <ActivityIndicator />
              <Text style={s.muted}>{pairing ? "Checking… links are opened only in the computer's sandbox (up to a minute)." : "Checking…"}</Text>
            </View>
          )}
          {error && <Text style={s.note}>⚠️ {error}</Text>}
          {result && <ResultCard r={result} pairing={pairing} />}
          </>}

          <Text style={[s.muted, { fontSize: 12, textAlign: "center" }]}>
            Messages and pictures stay on this phone. Only links are sent to your computer for checking. Nothing is saved.
          </Text>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

interface ConnectProps {
  pairing: Pairing | null;
  code: string;
  setCode: (c: string) => void;
  onChange: (p: Pairing | null) => void;
  onScan: () => void;
}

function Connect({ pairing, code, setCode, onChange, onScan }: ConnectProps) {
  const [msg, setMsg] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const candidate = parsePairing(code);

  async function connect(p: Pairing) {
    setTesting(true);
    setMsg(null);
    try {
      const h = await health(p);
      await savePairing(p);
      setCode("");
      onChange(p);
      if (!h.link_sandbox) setMsg("Connected, but the computer's link sandbox (URL.vet) is off. Links will be checked by lists only.");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : String(e));
    } finally {
      setTesting(false);
    }
  }

  if (pairing) {
    return (
      <Card>
        <Text style={s.h2}>Connected to {hostOf(pairing.server)}</Text>
        <Text style={s.muted}>Links you check are sent to this computer, opened in its sandbox, and checked against safety lists.</Text>
        {msg && <Text style={s.note}>{msg}</Text>}
        <View style={{ flexDirection: "row", gap: 10 }}>
          <Button title={testing ? "Testing…" : "Test connection"} kind="plain" disabled={testing} onPress={() => connect(pairing)} />
          <Button title="Disconnect" kind="plain" onPress={async () => { await forgetPairing(); onChange(null); }} />
        </View>
      </Card>
    );
  }

  return (
    <Card>
      <Text style={s.h2}>Connect to your computer</Text>
      <Text style={s.muted}>On the computer, run start-everything.bat, open Amaan and go to the “Phone app” tab. Scan the code shown there.</Text>
      <Button title="📷 Scan pairing code" onPress={onScan} />
      <TextInput value={code} onChangeText={setCode} placeholder="…or paste the pairing link (amaan://pair?…)" autoCapitalize="none" autoCorrect={false}
        style={{ borderWidth: 1, borderColor: C.line, borderRadius: 10, padding: 10, fontSize: 14, color: C.ink }} />
      {!!code && !candidate && <Text style={s.note}>That isn't an Amaan pairing code.</Text>}
      {candidate && (
        <View style={{ gap: 8 }}>
          <Text style={{ color: C.ink }}>Connect to <Text style={{ fontWeight: "700" }}>{hostOf(candidate.server)}</Text>?</Text>
          {!isLocalNetwork(candidate.server) && (
            <Text style={s.note}>⚠️ This is not on your home network. Only connect if it is your team's Amaan server: the links you check will be sent there.</Text>
          )}
          <Button title={testing ? "Connecting…" : "Connect"} disabled={testing} onPress={() => connect(candidate)} />
        </View>
      )}
      {msg && <Text style={s.note}>{msg}</Text>}
    </Card>
  );
}

function Scanner({ mode, onCodes, onCancel }: { mode: "check" | "pair"; onCodes: (codes: string[]) => void; onCancel: () => void }) {
  const [perm, requestPerm] = useCameraPermissions();
  const done = useRef(false);

  function onScanned(r: BarcodeScanningResult) {
    if (done.current || !r.data) return;
    if (mode === "pair" && !parsePairing(r.data)) return; // keep looking for the pairing code
    done.current = true;
    onCodes([r.data]);
  }

  if (!perm) return <View style={{ flex: 1, backgroundColor: "#000" }} />;
  if (!perm.granted) {
    return (
      <SafeAreaView style={{ flex: 1, padding: 24, gap: 14, justifyContent: "center", backgroundColor: C.bg }}>
        <Text style={s.h2}>Camera needed</Text>
        <Text style={s.muted}>Amaan uses the camera only to read QR codes. Nothing is recorded or uploaded.</Text>
        <Button title="Allow camera" onPress={requestPerm} />
        <Button title="Cancel" kind="plain" onPress={onCancel} />
      </SafeAreaView>
    );
  }
  return (
    <View style={{ flex: 1, backgroundColor: "#000" }}>
      <CameraView style={{ flex: 1 }} facing="back" barcodeScannerSettings={{ barcodeTypes: ["qr"] }} onBarcodeScanned={onScanned} />
      <SafeAreaView style={{ position: "absolute", left: 0, right: 0, bottom: 0, padding: 16, gap: 10 }}>
        <Text style={{ color: "#fff", textAlign: "center", fontSize: 15 }}>
          {mode === "pair" ? "Point at the code in Amaan's “Phone app” tab" : "Point at the QR code. It won't be opened."}
        </Text>
        <Button title="Cancel" kind="plain" onPress={onCancel} />
      </SafeAreaView>
    </View>
  );
}
