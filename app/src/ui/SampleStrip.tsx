import { useState } from "react";
import type { Sample } from "../data/manifest";
import { store, useViewer } from "../store/store";
import { anyPinned, bothPinned, computePanes, SECTION_KEY, unassignedSamples } from "../views/panes";

/** Jump list of samples, collapsed by default: click selects, double-click (or the arrow) focuses. */
export function SampleStrip() {
  const manifest = useViewer((s) => s.manifest)!;
  const focus = useViewer((s) => s.focus);
  const selected = useViewer((s) => s.selected);
  const status = useViewer((s) => s.sampleStatus);
  const splitBy = useViewer((s) => s.splitBy);
  const split = useViewer((s) => s.split);
  const pins = useViewer((s) => s.pins);
  // the list follows the canvas: by group under a split, by window once both are pinned (one pin keeps the grid)
  const grouped = (!!splitBy && !anyPinned(pins)) || bothPinned(pins);
  const [open, setOpen] = useState(false);
  const order = [...manifest.layout.order];
  for (const s of manifest.samples) if (!order.includes(s.id)) order.push(s.id);
  const byId = new Map(manifest.samples.map((s) => [s.id, s]));
  const spatial = order.filter((id) => byId.get(id)?.kind !== "embedding");
  const embedding = order.filter((id) => byId.get(id)?.kind === "embedding");
  const row = (id: string) => <SampleRow key={id} id={id} s={byId.get(id)!} focus={focus} selected={selected} status={status[id]} />;
  const focusName = focus ? byId.get(focus)?.name : null;
  const layoutMode = useViewer((s) => s.layoutMode);
  const set = store.getState().set;
  return (
    <section>
      <h2>
        Samples <span className="muted">{manifest.samples.length}</span>
        <span className="legend-actions">
          <button className={layoutMode === "grid" ? "on" : ""} onClick={() => set({ layoutMode: "grid" })} title="sections in a grid">
            grid
          </button>
          <button className={layoutMode === "strip" ? "on" : ""} onClick={() => set({ layoutMode: "strip" })} title="sections in one row">
            strip
          </button>
          {focus && <button onClick={() => store.getState().setFocus(null)}>show all</button>}
          <button onClick={() => setOpen((o) => !o)}>{open ? "hide list" : "list"}</button>
        </span>
      </h2>
      {!open && <div className="muted small">{focusName ? `focused on ${focusName}` : "double-click a section on the map to focus it · ←/→ to step"}</div>}
      {open && !grouped && (
        <ul className="samples">
          {spatial.map(row)}
          {embedding.length > 0 && <li className="subhead">snRNA-seq / embeddings</li>}
          {embedding.map(row)}
        </ul>
      )}
      {open && grouped && (
        <ul className="samples">
          {computePanes(manifest, splitBy, split, pins)
            .filter((p) => p.group)
            .map((p) => (
              <li key={p.id} className="group">
                <div className="subhead">{p.group!.key === SECTION_KEY ? `pinned ${p.id === "g0" ? "left" : "right"}` : p.group!.value}</div>
                <ul className="samples">{order.filter((id) => p.samples.some((s) => s.id === id)).map(row)}</ul>
              </li>
            ))}
          {unassignedSamples(manifest, splitBy, pins).length > 0 && (
            <li className="group">
              <div className="subhead">{bothPinned(pins) ? "not pinned" : `no ${splitBy!.key}`} · not drawn</div>
              <ul className="samples">{order.filter((id) => unassignedSamples(manifest, splitBy, pins).some((s) => s.id === id)).map(row)}</ul>
            </li>
          )}
          {embedding.length > 0 && <li className="subhead">snRNA-seq / embeddings</li>}
          {embedding.map(row)}
        </ul>
      )}
    </section>
  );
}

function SampleRow({ id, s, focus, selected, status }: { id: string; s: Sample; focus: string | null; selected: string | null; status?: string }) {
  const st = store.getState();
  const rotation = useViewer((v) => v.rotations[id] ?? 0);
  const hidden = st.hiddenSamples.includes(id) || (!!st.platforms && s.kind !== "embedding" && !st.platforms.includes(s.platform));
  const cls = [id === focus ? "focus" : "", id === selected ? "sel" : "", status ?? "", hidden ? "hidden" : ""].join(" ");
  return (
    <li className={cls} title={hidden ? "hidden by the platform bar or the sample list" : undefined}>
      <button className="sample-btn" onClick={() => st.set({ selected: id })} onDoubleClick={() => !hidden && st.setFocus(id)} title={hidden ? "hidden" : "double-click to focus"}>
        <span className="s-name">{s.name}</span>
        <span className="s-meta">
          {s.platform} · {s.nObs.toLocaleString()}
          {rotation ? ` · turned ${rotation}°` : ""}
        </span>
      </button>
      {s.kind !== "embedding" && (
        <button className="focus-btn" disabled={hidden} onClick={() => st.rotateSample(id)} title={rotation ? `turned ${rotation}° clockwise · click for another 90°` : "turn 90° clockwise"}>
          ↻
        </button>
      )}
      <button className="focus-btn" disabled={hidden} onClick={() => st.setFocus(id === focus ? null : id)} title={id === focus ? "back to all" : "focus"}>
        {id === focus ? "⤢" : "⤡"}
      </button>
    </li>
  );
}
