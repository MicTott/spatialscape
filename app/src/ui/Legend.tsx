import { fieldById } from "../data/manifest";
import { colormapCSS } from "../layers/lut";
import { store, useViewer } from "../store/store";

export function Legend() {
  const manifest = useViewer((s) => s.manifest);
  const color = useViewer((s) => s.color);
  const hidden = useViewer((s) => s.hiddenCategories);
  const counts = useViewer((s) => s.categoryCounts);
  const colormap = useViewer((s) => s.colormap);
  const vrange = useViewer((s) => s.vrange);
  const geneMax = useViewer((s) => s.geneMax);
  const features = useViewer((s) => s.features);
  if (!manifest || !color) return null;

  if (color.kind === "field") {
    const f = fieldById(manifest, color.field);
    if (!f) return null;
    if (f.type === "categorical") {
      const v = manifest.vocabularies[f.vocabulary];
      const hid = new Set(hidden[f.id] ?? []);
      const cnt = counts[f.id];
      const all = () => store.getState().setHiddenCategories(f.id, []);
      const none = () => store.getState().setHiddenCategories(f.id, v.categories.map((_, i) => i));
      return (
        <div className="legend">
          <div className="legend-head">
            <span>{f.name}</span>
            <span className="legend-actions">
              <button onClick={all}>all</button>
              <button onClick={none}>none</button>
            </span>
          </div>
          <ul className="cats">
            {v.categories.map((c, i) => (
              <li
                key={c}
                className={hid.has(i) ? "off" : ""}
                onClick={() => store.getState().toggleCategory(f.id, i)}
                onDoubleClick={(e) => {
                  e.preventDefault();
                  store.getState().setHiddenCategories(f.id, v.categories.map((_, j) => j).filter((j) => j !== i));
                }}
                title="click: toggle · double-click: solo"
              >
                <span className="swatch" style={{ background: v.colors[i] }} />
                <span className="cat-name">{c}</span>
                {cnt && <span className="cat-n">{cnt[i].toLocaleString()}</span>}
              </li>
            ))}
          </ul>
        </div>
      );
    }
    return (
      <div className="legend">
        <div className="legend-head">
          <span>{f.name}</span>
        </div>
        <div className="ramp" style={{ background: colormapCSS(colormap) }} />
        <div className="ramp-labels">
          <span>low</span>
          <span>high</span>
        </div>
      </div>
    );
  }
  const lo = vrange[0] * geneMax;
  const hi = vrange[1] * geneMax;
  const group = features?.groups.find((g) => g.features.some((f) => f.id === color.gene));
  const label = group?.features.find((f) => f.id === color.gene)?.label ?? color.gene;
  return (
    <div className="legend">
      <div className="legend-head">
        <span>{label}</span>
        <span className="muted">{group ? (group.units ?? group.name) : "log-normalized"}</span>
      </div>
      <div className="ramp" style={{ background: colormapCSS(colormap) }} />
      <div className="ramp-labels">
        <span>{lo.toFixed(2)}</span>
        <span>{hi.toFixed(2)}</span>
      </div>
    </div>
  );
}
