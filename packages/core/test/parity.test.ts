// The phone must give the same answers as the backend. These cases mirror
// backend/tests/test_urls.py and the built-in examples (frontend/src/examples.json).
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import examples from "../../../frontend/src/examples.json";
import { analyzeQr, analyzeText, defang, extractUrls, markOffline, mergeServer, textCueSignals } from "../src";

const here = (p: string) => new URL(p, import.meta.url);
const hosts = (t: string) => extractUrls(t).urls.map((u) => u.hostAscii);

describe("shared data is identical to the backend's", () => {
  for (const f of ["brands.json", "cues.json", "lookups.json"]) {
    it(f, () => {
      expect(readFileSync(here(`../src/data/${f}`), "utf8")).toBe(readFileSync(here(`../../../backend/amaan/data/${f}`), "utf8"));
    });
  }
});

describe("link finding (same cases as test_urls.py)", () => {
  it("schemes, bare domains, shorteners, www", () => {
    expect(extractUrls("Check https://example.com/login?x=1 now").urls[0].url).toBe("https://example.com/login?x=1");
    expect(hosts("go to omt-lb.xyz or bit.ly/3abcD")).toEqual(["omt-lb.xyz", "bit.ly"]);
    expect(hosts("visit www.blombank.com.")).toEqual(["www.blombank.com"]);
    expect(extractUrls("touch.com.lb").urls[0].registrable).toBe("touch.com.lb");
  });
  it("Arabic and Arabizi around links", () => {
    expect(extractUrls("مرحبا، افتح الرابط https://omt-lb.xyz/claim، وبعدين ابعتلي الكود").urls[0].url).toBe("https://omt-lb.xyz/claim");
    expect(hosts("زوروا الموقعexample.comهلق")).toEqual(["example.com"]);
    expect(hosts("شفت whish-money.net؟")).toEqual(["whish-money.net"]);
    expect(hosts("kifak! 3andak jeyze, eftah hal link: bit.ly/xyz12 w 7ot el code yalla")).toEqual(["bit.ly"]);
  });
  it("punycode, homographs, defanged, hidden characters, full-width", () => {
    expect(extractUrls("xn--80ak6aa92e.com").urls[0].host).toBe("аррӏе.com");
    expect(extractUrls("pay here: pаypal.com").urls[0].hostAscii.startsWith("xn--")).toBe(true);
    const d = extractUrls("bad: hxxps://evil[.]com/x");
    expect(d.urls[0].url).toBe("https://evil.com/x");
    expect(d.flags.defanged).toBe(true);
    expect(hosts("open exa​mple.com")).toEqual(["example.com"]);
    expect(extractUrls("open exa​mple.com").flags.zeroWidthInLink).toBe(true);
    expect(hosts("ｅｘａｍｐｌｅ。com")).toEqual(["example.com"]);
  });
  it("things that are not links", () => {
    expect(hosts("the price is 3.5 million, v1.2.3 node.js file.txt e.g. i.e.")).toEqual([]);
    expect(hosts("mail john.doe@example.com")).toEqual([]);
    expect(hosts("version 10.0.0.1")).toEqual([]);
    expect(hosts("router 192.168.1.1/admin")).toEqual(["192.168.1.1"]);
    expect(hosts("invoice.zip")).toEqual(["invoice.zip"]);
  });
  it("defang", () => {
    expect(defang("https://evil.com/a.b")).toBe("hxxps://evil[.]com/a.b");
    expect(defang("bit.ly/x")).toBe("bit[.]ly/x");
  });
});

const ids = (r: ReturnType<typeof analyzeText>) => new Set([...r.signals, ...r.items.flatMap((i) => i.signals)].map((s) => s.id));

describe("built-in examples give the same result as the backend (URL.vet off)", () => {
  for (const ex of examples.text) {
    it(`text: ${ex.id}`, () => {
      const r = markOffline(analyzeText(ex.text));
      for (const id of ex.expect_signals) expect(ids(r)).toContain(id);
      expect(r.riskLevel).toBe(ex.expect_risk);
    });
  }
  for (const ex of examples.qr) {
    it(`qr: ${ex.file}`, () => {
      const r = analyzeQr([ex.payload]);
      for (const id of ex.expect_signals) expect(ids(r)).toContain(id);
      expect(r.riskLevel).toBe(ex.expect_risk);
    });
  }
  it("qr: three codes", () => {
    expect(analyzeQr(examples.qr_multi.payloads).riskLevel).toBe(examples.qr_multi.expect_risk);
  });
});

describe("message cues", () => {
  it("Arabizi spelling variants and the scam-script combo", () => {
    for (const m of ["lek b3atle el code tb3k", "ba3atli l code", "eb3atle el kod", "a3tini el code yalli wasalak"]) {
      expect(textCueSignals(m).map((s) => s.id)).toContain("cue_asks_for_code");
    }
    expect(textCueSignals("lek b3atle el code tb3k google.com")[0].id).toBe("cue_scam_script");
    const ar = textCueSignals("لقد ربحت معنا جاءزة مليون دولار امريكي اضغط على الينك لتأخذها www.winprize1m.com").map((s) => s.id);
    expect(ar).toEqual(expect.arrayContaining(["cue_prize", "cue_big_amount", "cue_click_link", "cue_scam_script"]));
  });
  it("normal chats stay quiet", () => {
    for (const m of ["mabrouk el baby! 🎉", "kifak? shoufak bokra", "The code review is tomorrow", "I paid 20$ for lunch"]) {
      expect(textCueSignals(m).some((s) => s.severity === "medium" || s.severity === "high")).toBe(false);
    }
  });
});

describe("hybrid merge", () => {
  it("server result replaces the device's view of the link; message cues stay", () => {
    const local = analyzeText("ab3atli el code: omt-gift.example.com");
    const merged = mergeServer(local, { complete: true, warnings: [], items: [{
      display: "omt-gift[.]example[.]com", host_ascii: "omt-gift.example.com", risk_level: "High",
      signals: [{ id: "source_virustotal", title: "VirusTotal flags it as dangerous", detail: "", severity: "high", label: "automated_indicator", source: "VirusTotal" }],
    }] });
    expect(merged.items[0].checked).toBe(true);
    expect(merged.riskLevel).toBe("High");
    expect(merged.signals.map((s) => s.id)).toContain("cue_asks_for_code");
  });
});

describe("look-it-up links (same as backend/tests/test_lookups.py)", () => {
  it("are encoded exactly like the backend's", async () => {
    const { lookupLinks } = await import("../src");
    const links = Object.fromEntries(lookupLinks("https://omt-gift.com/claim?code=1&x=y", "omt-gift.com").map((l) => [l.id, l.href]));
    expect(links.virustotal).toBe("https://www.virustotal.com/gui/search/https%253A%252F%252Fomt-gift.com%252Fclaim%253Fcode%253D1%2526x%253Dy");
    expect(links.safebrowsing).toBe("https://transparencyreport.google.com/safe-browsing/search?url=https%3A%2F%2Fomt-gift.com%2Fclaim%3Fcode%3D1%26x%3Dy");
    expect(links.urlvoid).toBe("https://www.urlvoid.com/scan/omt-gift.com/");
    expect(lookupLinks("omt-gift.com/claim", "omt-gift.com")[0].href).toMatch(/\/http%253A%252F%252Fomt-gift.com%252Fclaim$/);
    const evil = Object.fromEntries(lookupLinks("http://a.com", "evil.com/../x?y=1#").map((l) => [l.id, l.href]));
    expect(evil.urlvoid).toBe("https://www.urlvoid.com/scan/evil.com%2F..%2Fx%3Fy%3D1%23/");
  });
});
