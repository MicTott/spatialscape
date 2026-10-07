import { useState } from "react";
import type { Sample } from "../data/manifest";
import { store, useViewer } from "../store/store";

/** Jump list of samples, collapsed by default: click selects, double-click (or the arrow) focuses. */
export function SampleStrip() {
  const manifest = useViewer((s) => s.manifest)!;
  const focus = useViewer((s) => s.focus);
  const selected = useViewer((s) => s.selected);
  const status = useViewer((s) => s.sampleStatus);
  const [open, setOpen] = useState(false);
  const order = [...manifest.layout.order];
  for (const s of manifest.samples) if (!order.includes(s.id)) order.push(s.id);
  const byId = new Map(manifest.samples.map((s) => [s.id, s]));
  const spatial = order.filter((id) => byId.get(id)?.kind !== "embedding");
  const embedding = order.filter((id) => byId.get(id)?.kind === "embedding");
  const row = (id: string) => <SampleRow key={id} id={id} s={byId.get(id)!} focus={focus} selected={selected} status={status[id]} />;
  const focusName = focus ? byId.get(focus)?.name : null;
  return (
    <section>
      <h2>
        Samples <span className="muted">{manifest.samples.length}</span>
        <span className="legend-actions">
          {focus && <button onClick={() => store.getState().setFocus(null)}>show all</button>}
          <button onClick={() => setOpen((o) => !o)}>{open ? "hide list" : "list"}</button>
        </span>
      </h2>
      {!open && <div className="muted small">{focusName ? `focused on ${focusName}` : "double-click a section on the map to focus it · ←/→ to step"}</div>}
      {open && (
        <ul className="samples">
          {spatial.map(row)}
          {embedding.length > 0 && <li className="subhead">snRNA-seq / embeddings</li>}
          {embedding.map(row)}
        </ul>
      )}
    </section>
  );
}

function SampleRow({ id, s, focus, selected, status }: { id: string; s: Sample; focus: string | null; selected: string | null; status?: string }) {
  const cls = [id === focus ? "focus" : "", id === selected ? "sel" : "", status ?? ""].join(" ");
  return (
    <li className={cls}>
      <button className="sample-btn" onClick={() => store.getState().set({ selected: id })} onDoubleClick={() => store.getState().setFocus(id)} title="double-click to focus">
        <span className="s-name">{s.name}</span>
        <span className="s-meta">
          {s.platform} · {s.nObs.toLocaleString()}
        </span>
      </button>
      <button className="focus-btn" onClick={() => store.getState().setFocus(id === focus ? null : id)} title={id === focus ? "back to all" : "focus"}>
        {id === focus ? "⤢" : "⤡"}
      </button>
    </li>
  );
}
