import type { AnalyzedItem, Evidence } from "../types";

// Trace view (LINK_SECURITY.md section 2): for each link, what every layer received and passed on,
// built only from the evidence already on screen. Links are shown defanged, as everywhere else.

interface Row {
  layer: string;
  where: string;
  got: string;
  gave: string[];
  touched: "no" | "sandbox";
}

const bytes = (v: unknown) => new Blob([JSON.stringify(v ?? null)]).size;

function rowsFor(item: AnalyzedItem, ev: Evidence): Row[] {
  const link = item.display;
  const own = item.signals.filter((s) => s.source === "amaan");
  const fromWorker = item.signals.filter((s) => s.source === "expander");
  const rows: Row[] = [
    {
      layer: "L3 Static rules",
      where: "Amaan server, no network",
      got: link,
      gave: own.length ? own.map((s) => `${s.id} (${s.severity})`) : ["no signals"],
      touched: "no",
    },
    {
      layer: "L4 Reputation",
      where: "Amaan server to listed services",
      got: "the link only",
      gave: (item.sources ?? []).length
        ? item.sources.map((s) => `${s.source}: ${s.status === "ok" ? s.verdict : s.status.replaceAll("_", " ")}`)
        : ["no sources answered"],
      touched: "no",
    },
  ];
  const x = item.expansion;
  if (x) {
    const gave =
      x.status === "ok"
        ? [
            `${x.hops.length} hop${x.hops.length === 1 ? "" : "s"}, stopped: ${x.stopped || "?"}`,
            ...(x.final_url ? [`final: ${x.final_url}`] : []),
            ...(x.asks_for.length ? [`page asks for: ${x.asks_for.join(", ")}`] : []),
            ...(x.human_check ? ["human check in front of the page"] : []),
            ...(x.download ? [`download hashed: ${x.download.sha256.slice(0, 12)}…, not kept`] : []),
            ...fromWorker.map((s) => `${s.id} (${s.severity})`),
            ...(x.stopped === "final page" ? ["page text: kept on the server for the AI summary only"] : []),
          ]
        : [x.message];
    rows.push({
      layer: "L5 Expansion worker",
      where: "sandbox container, egress proxy only",
      got: "the link only",
      gave: [...gave, `${bytes(x)} bytes sent to the server, ${(x.elapsed_ms / 1000).toFixed(1)} s`],
      touched: "sandbox",
    });
  }
  const uv = item.urlvet;
  if (uv) {
    rows.push({
      layer: "URL.vet",
      where: "its own containers, Chrome behind the egress proxy",
      got: "the link only",
      gave:
        uv.status === "ok"
          ? [
              `verdict: ${uv.verdict ?? "?"}, score ${uv.final_score ?? "?"}`,
              ...(uv.redirect_chain.length > 1 ? [`${uv.redirect_chain.length} addresses in the chain`] : []),
            ]
          : [uv.message || uv.status],
      touched: "sandbox",
    });
  }
  rows.push({
    layer: "L7 Verdict",
    where: "Amaan server",
    got: `${item.signals.length} signals for this link`,
    gave: [`${item.risk_level} risk for this link, ${ev.risk_level} overall`],
    touched: "no",
  });
  return rows;
}

export default function TraceView({ ev }: { ev: Evidence }) {
  const links = ev.items.filter((i) => i.kind === "url");
  if (!links.length) return null;
  return (
    <div className="space-y-3 rounded-xl border border-slate-200 bg-white p-3">
      <p className="text-xs text-slate-600">
        <b>L1 Intake:</b> {ev.input_type === "text" ? "text" : "an image"}. The web app sends it to Amaan on this
        computer only; the phone app sends only the links. <b>L2</b> found {links.length} link
        {links.length === 1 ? "" : "s"}
        {links.some((l) => l.signals.some((s) => s.id === "hidden_redirect")) ? ", including one hidden inside another link" : ""}. Only the sandbox rows
        contacted a link.
      </p>
      {links.map((item) => (
        <div key={item.id}>
          <p className="break-all font-mono text-xs font-semibold text-slate-700" dir="ltr">{item.display}</p>
          <table className="mt-1 w-full table-fixed text-left text-xs">
            <thead className="text-slate-500">
              <tr>
                <th className="w-1/5 py-1 pr-2">Layer</th>
                <th className="w-1/5 pr-2">Received</th>
                <th className="pr-2">Passed on</th>
                <th className="w-20">Opened the link?</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 align-top">
              {rowsFor(item, ev).map((r) => (
                <tr key={r.layer}>
                  <td className="py-1 pr-2">
                    <span className="font-medium">{r.layer}</span>
                    <span className="block text-slate-400">{r.where}</span>
                  </td>
                  <td className="break-all py-1 pr-2 font-mono" dir="ltr">{r.got}</td>
                  <td className="py-1 pr-2">
                    <ul className="break-all">{r.gave.map((g, i) => <li key={i}>{g}</li>)}</ul>
                  </td>
                  <td className="py-1">{r.touched === "sandbox" ? "yes, in the sandbox" : "no"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      <p className="text-xs text-slate-500">
        <b>L8 AI summary</b> (on request): gets these findings; it gets the message only if the model runs on this
        computer, and it cannot change the verdict.
      </p>
    </div>
  );
}
