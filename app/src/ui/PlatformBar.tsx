import { store, useViewer } from "../store/store";
import { splitKeys, unassignedSamples } from "../views/panes";

const ORDER = ["visium", "visium_hd", "xenium", "merfish", "other"];
const LABEL: Record<string, string> = { visium: "Visium", visium_hd: "Visium HD", xenium: "Xenium", merfish: "MERFISH", other: "Other" };

/** Top bar: which spatial platforms are shown in the mosaic. */
export function PlatformBar() {
  const manifest = useViewer((s) => s.manifest);
  const platforms = useViewer((s) => s.platforms);
  const split = useViewer((s) => s.split);
  const genome = useViewer((s) => s.genome);
  const hasTracks = useViewer((s) => !!s.manifest?.samples.some((x) => x.tracks));
  const splitBy = useViewer((s) => s.splitBy);
  const matchScale = useViewer((s) => s.matchScale);
  if (!manifest) return null;
  const keys = splitKeys(manifest);
  const left = splitBy ? unassignedSamples(manifest, splitBy).length : 0;
  const present = ORDER.filter((p) => manifest.samples.some((s) => s.kind !== "embedding" && s.platform === p));
  const hasEmbedding = manifest.samples.some((s) => s.kind === "embedding");
  // Platform and linked-view controls remain available above the canvas.
  const active = new Set(platforms ?? present);
  const counts = Object.fromEntries(present.map((p) => [p, manifest.samples.filter((s) => s.kind !== "embedding" && s.platform === p).length]));
  const set = store.getState().set;
  if (present.length < 2 && keys.length === 0 && !hasEmbedding && !hasTracks) return null;
  return (
    <div className={`platformbar${splitBy && keys.length ? " below-heads" : ""}`}>
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
      {keys.length > 0 && (
        <span className="split-ctl">
          <span className="muted">split by</span>
          <select
            value={splitBy?.key ?? ""}
            onChange={(e) => set({ splitBy: e.target.value ? { key: e.target.value, groups: null, fractions: null } : null })}
            title="one pane per group, side by side, each with its own camera"
          >
            <option value="">none</option>
            {keys.map((k) => (
              <option key={k.id} value={k.id}>
                {k.name}
              </option>
            ))}
          </select>
          {splitBy && (
            <button className={matchScale ? "on" : ""} onClick={() => set({ matchScale: !matchScale })} title="keep every pane at the same microns per pixel: zoom one, the others follow in scale">
              match scale
            </button>
          )}
          {left > 0 && (
            <span className="muted" title={`${left} section${left === 1 ? " has" : "s have"} no ${splitBy!.key} value, or one that is not in a pane; not drawn while the canvas is split`}>
              {left} not shown
            </span>
          )}
        </span>
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
      {hasTracks && (
        <span className="split-ctl">
          <span className="muted">genome</span>
          <button className={!genome ? "on" : ""} onClick={() => set({ genome: false })}>
            off
          </button>
          <button className={genome ? "on" : ""} onClick={() => set({ genome: true })}>
            on
          </button>
        </span>
      )}
    </div>
  );
}
