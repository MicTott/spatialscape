import { useMemo, useState } from "react";
import { BLEND_SCHEMES } from "../layers/lut";
import { store, useViewer, type BlendScheme } from "../store/store";
import { GeneSearch } from "./GeneSearch";

/** Two gene sets (1..n genes each) blended into one color per cell. */
export function BlendPanel({ genes }: { genes: string[] }) {
  const color = useViewer((s) => s.color);
  const manifest = useViewer((s) => s.manifest)!;
  const blend = color?.kind === "blend" ? color : null;
  const [draftA, setDraftA] = useState("");
  const [draftB, setDraftB] = useState("");
  const known = useMemo(() => new Set(genes), [genes]);
  if (!blend) return null;
  const set = (patch: Partial<typeof blend>) => store.getState().setColor({ ...blend, ...patch });
  const parse = (txt: string) => [...new Set(txt.split(/[\s,;]+/).map((g) => g.trim()).filter(Boolean))];
  const scheme = BLEND_SCHEMES[blend.scheme];

  const editor = (label: string, key: "a" | "b", list: string[], draft: string, setDraft: (v: string) => void, swatch: string) => (
    <div className="geneset">
      <div className="geneset-head">
        <span className="swatch" style={{ background: swatch }} />
        <b>{label}</b>
        <span className="muted">
          {list.length} gene{list.length === 1 ? "" : "s"}
        </span>
        {list.length > 0 && (
          <span className="legend-actions">
            <button onClick={() => set({ [key]: [] } as any)}>clear</button>
          </span>
        )}
      </div>
      <div className="chips">
        {list.map((g) => (
          <span key={g} className={`chip ${known.has(g) ? "" : "unknown"}`} title={known.has(g) ? "" : "not in this dataset's gene list"}>
            {g}
            <button onClick={() => set({ [key]: list.filter((x) => x !== g) } as any)} aria-label={`remove ${g}`}>
              ×
            </button>
          </span>
        ))}
      </div>
      <GeneSearch genes={genes} value={null} placeholder="add a gene…" onPick={(g) => !list.includes(g) && set({ [key]: [...list, g] } as any)} />
      <textarea
        className="genelist"
        rows={2}
        placeholder="or paste a list (comma, space or newline separated) and press Enter"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            const add = parse(draft).filter((g) => !list.includes(g));
            if (add.length) set({ [key]: [...list, ...add] } as any);
            setDraft("");
          }
        }}
      />
    </div>
  );

  return (
    <div className="blend">
      {editor("Set A", "a", blend.a, draftA, setDraftA, scheme.a)}
      {editor("Set B", "b", blend.b, draftB, setDraftB, scheme.b)}
      <label>
        colors
        <select value={blend.scheme} onChange={(e) => set({ scheme: e.target.value as BlendScheme })}>
          {Object.entries(BLEND_SCHEMES).map(([k, v]) => (
            <option key={k} value={k}>
              {v.name}
            </option>
          ))}
        </select>
      </label>
      <p className="muted small">
        Each cell's score per set is the mean of its genes' normalized expression. Genes missing from a sample's panel are skipped; samples with none of a set's genes
        show that channel as empty. {manifest.samples.some((s) => s.platform === "xenium") ? "Xenium panels cover only some genes." : ""}
      </p>
    </div>
  );
}
