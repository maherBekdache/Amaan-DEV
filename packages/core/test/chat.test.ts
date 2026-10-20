// Same cases as backend/tests/test_whatsapp.py (parser + import report).
import { strToU8, zipSync } from "fflate";
import { describe, expect, it } from "vitest";
import { ExportRejected, loadExport, parseChat, planChat } from "../src";

const ANDROID = `12/10/2026, 14:05 - Messages and calls are end-to-end encrypted. No one outside of this chat can read them.
12/10/2026, 14:05 - Ali: kifak?
12/10/2026, 14:06 - Unknown: Mabrouk! rbe7t jeyze men OMT
ekbos hon omt-gift.example.com/claim w ab3atli el code
12/10/2026, 14:07 - Ali: IMG-20261012-WA0001.jpg (file attached)
`;
const IOS = "‎[12/10/26, 2:05:33 PM] Rana: check https://www.aub.edu.lb\n[12/10/26, 2:06:01 PM] Rana: <attached: 00000002-PHOTO.jpg>\n";

describe("WhatsApp export parser", () => {
  it("Android: multi-line messages, system lines dropped", () => {
    const msgs = parseChat(ANDROID);
    expect(msgs.map((m) => m.sender)).toEqual(["Ali", "Unknown", "Ali"]);
    expect(msgs[1].text).toContain("omt-gift.example.com");
    expect(msgs[2].attachments).toEqual(["IMG-20261012-WA0001.jpg"]);
  });
  it("iPhone with invisible marks", () => {
    const msgs = parseChat(IOS);
    expect(msgs.map((m) => [m.sender, m.time])).toEqual([["Rana", "2:05:33 PM"], ["Rana", "2:06:01 PM"]]);
    expect(msgs[1].attachments).toEqual(["00000002-PHOTO.jpg"]);
  });
  it("rejects files that are not chats", () => {
    expect(() => loadExport("notes.txt", strToU8("just some notes\nwithout dates"))).toThrow(ExportRejected);
  });
  it("zip: title, chat text and referenced photos", () => {
    const zip = zipSync({ "WhatsApp Chat with Rana.txt": strToU8(IOS), "00000002-PHOTO.jpg": new Uint8Array([1, 2, 3]), "other.png": new Uint8Array([4]) });
    const ex = loadExport("WhatsApp Chat with Rana.zip", zip);
    expect(ex.title).toBe("Rana");
    expect([...ex.images.keys()][0]).toBe("00000002-PHOTO.jpg");
  });
  it("zip bomb refused before unpacking", () => {
    const zip = zipSync({ "_chat.txt": strToU8(IOS), "big.bin": new Uint8Array(81 * 1024 * 1024) });
    expect(() => loadExport("chat.zip", zip)).toThrow(/too large/);
  });
});

describe("chat plan", () => {
  it("flags the scam message and picks its link", () => {
    const plan = planChat(parseChat(ANDROID));
    const scam = plan.candidates.find((c) => c.message.sender === "Unknown")!;
    expect(scam.result.riskLevel).toBe("High");
    expect(plan.links).toEqual(["omt-gift.example.com/claim"]);
  });
  it("link budget: most suspicious first", () => {
    const lines = Array.from({ length: 5 }, (_, i) => `12/10/2026, 14:0${i} - A: see site${i}.com`).join("\n");
    const plan = planChat(parseChat(lines + "\n12/10/2026, 14:09 - B: login at paypal-verify.xyz/login"), 2);
    expect(plan.linksFound).toBe(6);
    expect(plan.links[0]).toBe("paypal-verify.xyz/login");
    expect(plan.links).toHaveLength(2);
  });
});
