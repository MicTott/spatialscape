import { store, useViewer } from "../store/store";

const ORDER = ["visium", "visium_hd", "xenium", "merfish", "other"];
const LABEL: Record<string, string> = { visium: "Visium", visium_hd: "Visium HD", xenium: "Xenium", merfish: "MERFISH", other: "Other" };

/** Top bar: which spatial platforms are shown in the mosaic. */
export function PlatformBar() {
  const manifest = useViewer((s) => s.manifest);
  const platforms = useViewer((s) => s.platforms);
  const split = useViewer((s) => s.split);
  const tool = useViewer((s) => s.tool);
  if (!manifest) return null;
  const present = ORDER.filter((p) => manifest.samples.some((s) => s.kind !== "embedding" && s.platform === p));
  const hasEmbedding = manifest.samples.some((s) => s.kind === "embedding");
  // always shown: it also hosts the lasso tool
  const active = new Set(platforms ?? present);
  const counts = Object.fromEntries(present.map((p) => [p, manifest.samples.filter((s) => s.kind !== "embedding" && s.platform === p).length]));
  const set = store.getState().set;
  return (
    <div className="platformbar">
      <button className={tool === "lasso" ? "on tool" : "tool"} onClick={() => set({ tool: tool === "lasso" ? "pan" : "lasso" })} title="lasso select cells (L)">
        ⌒ lasso
      </button>
      {present.length >= 2 && (
        <>
          <button className={platforms === null ? "on" : ""} onClick={() => set({ platforms: null })}>
            All
          </button>
          {present.map((p) => (
            <button
              key={p}
              className={active.has(p) ? "on" : ""}
              onClick={(e) => (e.shiftKey ? store.getState().togglePlatform(p, present) : set({ platforms: [p] }))}
              title="click: only this platform · shift-click: toggle"
            >
              {LABEL[p] ?? p} <span className="n">{counts[p]}</span>
            </button>
          ))}
        </>
      )}
      {hasEmbedding && (
        <span className="split-ctl">
          <span className="muted">snRNA-seq</span>
          <button className={!split.on ? "on" : ""} onClick={() => set({ split: { ...split, on: false } })}>
            off
          </button>
          <button className={split.on && split.side === "left" ? "on" : ""} onClick={() => set({ split: { ...split, on: true, side: "left" } })}>
            left
          </button>
          <button className={split.on && split.side === "right" ? "on" : ""} onClick={() => set({ split: { ...split, on: true, side: "right" } })}>
            right
          </button>
        </span>
      )}
    </div>
  );
}
