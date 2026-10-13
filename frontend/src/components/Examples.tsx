import examples from "../examples.json";

// One-click, safe examples (links use example.com or real official sites).
// Images are served by our own app from /examples/, never from the internet.

export type Example =
  | { kind: "text"; label: string; text: string }
  | { kind: "image"; label: string; file: string };

const LIST: Example[] = [
  ...["arabic-prize", "arabizi-code", "english-suspended", "safe-chat"].map((id) => {
    const t = examples.text.find((x) => x.id === id)!;
    return { kind: "text" as const, label: t.label, text: t.text };
  }),
  ...["02-at-sign-trick.png", "01-official-omt.png", "03-open-wifi.png"].map((file) => {
    const q = examples.qr.find((x) => x.file === file)!;
    return { kind: "image" as const, label: q.label, file };
  }),
  { kind: "image", label: examples.qr_multi.label, file: examples.qr_multi.file },
];

export async function loadExampleImage(file: string): Promise<File> {
  const res = await fetch(`./examples/${file}`);
  const blob = await res.blob();
  return new File([blob], file, { type: blob.type || "image/png" });
}

export default function Examples({ disabled, onPick }: { disabled: boolean; onPick: (e: Example) => void }) {
  return (
    <div>
      <p className="mb-2 text-sm font-medium text-slate-600">Try an example:</p>
      <div className="flex flex-wrap gap-2">
        {LIST.map((e) => (
          <button
            key={e.label}
            disabled={disabled}
            onClick={() => onPick(e)}
            className="flex items-center gap-2 rounded-full border border-slate-300 bg-white py-1 pl-1 pr-3 text-sm hover:border-teal-500 hover:bg-teal-50 disabled:opacity-40"
          >
            {e.kind === "image" ? (
              <img src={`./examples/${e.file}`} alt="" className="h-7 w-7 rounded-full border border-slate-200 object-cover" />
            ) : (
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-slate-100 text-xs">💬</span>
            )}
            {e.label}
          </button>
        ))}
      </div>
    </div>
  );
}
