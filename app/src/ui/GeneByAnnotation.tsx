import { useState } from "react";
import { fieldById } from "../data/manifest";
import { store, useViewer } from "../store/store";

/** Mean expression and fraction expressing of the current gene per category; rows toggle a category filter. */
export function GeneByAnnotation() {
  const manifest = useViewer((s) => s.manifest);
  const color = useViewer((s) => s.color);
  const groupField = useViewer((s) => s.groupField);
  const stats = useViewer((s) => s.groupStats);
  const filter = useViewer((s) => s.filter);
  const [perSample, setPerSample] = useState(false);
  if (!manifest || !color || color.kind === "field") return null;
  const catFields = manifest.fields.filter((f) => f.type === "categorical");
  if (!catFields.length) return null;
  const set = store.getState().set;
  const fieldId = groupField && catFields.some((f) => f.id === groupField) ? groupField : null;
  const f = fieldId ? fieldById(manifest, fieldId) : undefined;
  const v = f && f.type === "categorical" ? manifest.vocabularies[f.vocabulary] : null;
  const active = filter?.kind === "category" && filter.field === fieldId ? new Set(filter.codes) : new Set<number>();
  const toggle = (code: number) => {
    if (!fieldId) return;
    const next = new Set(active);
    if (next.has(code)) next.delete(code);
    else next.add(code);
    store.getState().setFilter(next.size ? { kind: "category", field: fieldId, codes: [...next].sort((a, b) => a - b) } : null);
  };
  const sampleIds = stats ? [...new Set(stats.rows.flatMap((r) => Object.keys(r.perSample)))] : [];
  return (
    <section>
      <h2>
        Expression by annotation
        {fieldId && (
          <span className="legend-actions">
            <button className={perSample ? "on" : ""} onClick={() => setPerSample((p) => !p)} title="split by sample">
              per sample
            </button>
          </span>
        )}
      </h2>
      <select value={fieldId ?? ""} onChange={(e) => set({ groupField: e.target.value || null })}>
        <option value="">choose annotation…</option>
        {catFields.map((cf) => (
          <option key={cf.id} value={cf.id}>
            {cf.name}
          </option>
        ))}
      </select>
      {fieldId && !stats && <div className="muted small">computing…</div>}
      {stats && v && !perSample && (
        <div className="dotplot">
          <div className="dp-head">
            <span />
            <span>mean</span>
            <span title="fraction of cells with any expression">% expr</span>
          </div>
          {stats.rows.map((r) => (
            <div className={`dp-row ${active.has(r.code) ? "on" : ""}`} key={r.code} onClick={() => toggle(r.code)} title="click to filter the map to this category">
              <span className="swatch" style={{ background: v.colors[r.code] }} />
              <span className="dp-name">{v.categories[r.code]}</span>
              <span className="dp-bar">
                <span style={{ width: `${stats.maxMean ? (100 * r.mean) / stats.maxMean : 0}%` }} />
                <em>{r.mean.toFixed(2)}</em>
              </span>
              <span className="dp-dot" title={`${r.n.toLocaleString()} cells`}>
                <i style={{ width: 4 + 10 * r.frac, height: 4 + 10 * r.frac }} />
                {(100 * r.frac).toFixed(0)}
              </span>
            </div>
          ))}
          {active.size > 0 && (
            <div className="muted small">
              filtering map to {active.size} categor{active.size > 1 ? "ies" : "y"} ·{" "}
              <a href="#" onClick={(e) => { e.preventDefault(); store.getState().setFilter(null); }}>
                clear
              </a>
            </div>
          )}
        </div>
      )}
      {stats && v && perSample && (
        <div className="heat">
          <table>
            <thead>
              <tr>
                <th />
                {sampleIds.map((sid) => (
                  <th key={sid} title={manifest.samples.find((x) => x.id === sid)?.name}>
                    {(manifest.samples.find((x) => x.id === sid)?.name ?? sid).replace(/\s*\(.*\)$/, "")}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {stats.rows.map((r) => (
                <tr key={r.code}>
                  <td>
                    <span className="swatch" style={{ background: v.colors[r.code] }} /> {v.categories[r.code]}
                  </td>
                  {sampleIds.map((sid) => {
                    const c = r.perSample[sid];
                    const t = c && stats.maxMean ? c.mean / stats.maxMean : 0;
                    return (
                      <td key={sid} style={{ background: c ? `rgba(64,196,255,${0.08 + 0.85 * t})` : "transparent" }} title={c ? `${c.mean.toFixed(2)} · ${(100 * c.frac).toFixed(0)}% of ${c.n.toLocaleString()}` : "no cells"}>
                        {c ? c.mean.toFixed(1) : ""}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
