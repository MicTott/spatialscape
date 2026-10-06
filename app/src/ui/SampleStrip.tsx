import type { Sample } from "../data/manifest";
import { store, useViewer } from "../store/store";

export function SampleStrip() {
  const manifest = useViewer((s) => s.manifest)!;
  const focus = useViewer((s) => s.focus);
  const selected = useViewer((s) => s.selected);
  const hidden = useViewer((s) => s.hiddenSamples);
  const status = useViewer((s) => s.sampleStatus);
  const order = [...manifest.layout.order];
  for (const s of manifest.samples) if (!order.includes(s.id)) order.push(s.id);
  const byId = new Map(manifest.samples.map((s) => [s.id, s]));
  const spatial = order.filter((id) => byId.get(id)?.kind !== "embedding");
  const embedding = order.filter((id) => byId.get(id)?.kind === "embedding");
  const hid = new Set(hidden);
  const row = (id: string) => (
    <SampleRow key={id} id={id} s={byId.get(id)!} focus={focus} selected={selected} hidden={hid.has(id)} status={status[id]} />
  );
  return (
    <section>
      <h2>
        Samples <span className="muted">{manifest.samples.length}</span>
        <span className="legend-actions">
          <button onClick={() => store.getState().set({ hiddenSamples: [] })}>all</button>
          {focus && <button onClick={() => store.getState().setFocus(null)}>show all</button>}
        </span>
      </h2>
      <ul className="samples">
        {spatial.map(row)}
        {embedding.length > 0 && <li className="subhead">snRNA-seq / embeddings</li>}
        {embedding.map(row)}
      </ul>
    </section>
  );
}

function SampleRow({ id, s, focus, selected, hidden, status }: { id: string; s: Sample; focus: string | null; selected: string | null; hidden: boolean; status?: string }) {
  const cls = [id === focus ? "focus" : "", id === selected ? "sel" : "", hidden ? "off" : "", status ?? ""].join(" ");
  return (
    <li className={cls}>
      <input type="checkbox" checked={!hidden} onChange={() => store.getState().toggleSample(id)} title="show / hide in layout" />
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
