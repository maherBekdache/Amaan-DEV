import { useEffect, useState } from "react";
import QRCode from "qrcode";

interface Pairing { enabled: boolean; server?: string; token?: string; pair_uri?: string; message?: string }

/** Shows the QR code the Amaan phone app scans to use this computer's link checker. */
export default function PhonePanel() {
  const [p, setP] = useState<Pairing | null>(null);
  const [qr, setQr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/phone/pairing", { credentials: "omit" })
      .then((r) => r.json())
      .then(async (data: Pairing) => {
        setP(data);
        if (data.enabled && data.pair_uri) setQr(await QRCode.toDataURL(data.pair_uri, { margin: 1, width: 260 }));
      })
      .catch(() => setP({ enabled: false, message: "Amaan's backend is not running." }));
  }, []);

  return (
    <section className="space-y-4 rounded-2xl border border-slate-200 bg-white p-5">
      <h2 className="text-lg font-semibold">Amaan on your phone</h2>
      <p className="text-sm text-slate-600">
        The phone app checks messages and QR codes <b>on the phone</b>. Only links are sent here, to this computer's
        sandbox and security sources.
      </p>
      <ol className="ml-5 list-decimal space-y-1 text-sm">
        <li>Install <b>Expo Go</b> from the App Store / Play Store and open the Amaan app (see README: "Phone app").</li>
        <li>Phone and this computer on the <b>same Wi-Fi</b>.</li>
        <li>In the app: <b>Connect to computer</b> → scan this code.</li>
      </ol>
      {!p ? null : p.enabled && qr ? (
        <div className="flex flex-wrap items-center gap-5">
          <img src={qr} alt="Pairing QR code" className="h-56 w-56 rounded-lg border" />
          <div className="text-sm text-slate-600">
            <p>Server: <span className="font-mono">{p.server}</span></p>
            <p className="mt-2 text-xs text-slate-400">The code contains a secret. Don't share a photo of it.</p>
          </div>
        </div>
      ) : (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">{p.message}</p>
      )}
    </section>
  );
}
