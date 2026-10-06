import { fieldById } from "../data/manifest";
import { useViewer } from "../store/store";
import type { ViewerController } from "../views/ViewerController";

export function SelectionPanel({ controller }: { controller: () => ViewerController | null }) {
  const manifest = useViewer((s) => s.manifest);
  const sum = useViewer((s) => s.selectionSummary);
  const tool = useViewer((s) => s.tool);
  if (!manifest) return null;
  if (!sum) {
    return tool === "lasso" ? (
      <section className="selection">
        <h2>Selection</h2>
        <p className="muted small">Drag to draw a lasso around cells. Esc cancels.</p>
      </section>
    ) : null;
  }
  const fields = Object.entries(sum.fields);
  return (
    <section className="selection">
      <h2>
        Selection <span className="muted">{sum.total.toLocaleString()} cells</span>
        <span className="legend-actions">
          <button onClick={() => void controller()?.exportSelectionCSV()} title="download sample,cell_id as CSV">
            export CSV
          </button>
          <button onClick={() => controller()?.clearSelection()}>clear</button>
        </span>
      </h2>
      {sum.perSample.length > 1 && (
        <div className="muted small">{sum.perSample.map((p) => `${p.name}: ${p.n.toLocaleString()}`).join(" · ")}</div>
      )}
      {sum.gene && (
        <table className="kv">
          <tbody>
            <tr>
              <td>{sum.gene.name} mean</td>
              <td>
                <b>{sum.gene.mean.toFixed(2)}</b> <span className="muted">vs {sum.gene.meanAll.toFixed(2)} overall</span>
              </td>
            </tr>
            <tr>
              <td>expressing</td>
              <td>
                <b>{(100 * sum.gene.frac).toFixed(0)}%</b> <span className="muted">vs {(100 * sum.gene.fracAll).toFixed(0)}%</span>
              </td>
            </tr>
          </tbody>
        </table>
      )}
      {fields.map(([fid, rows]) => {
        const f = fieldById(manifest, fid);
        if (!f || f.type !== "categorical") return null;
        const v = manifest.vocabularies[f.vocabulary];
        const tot = rows.reduce((a, r) => a + r.n, 0);
        return (
          <div className="comp" key={fid}>
            <div className="comp-head">{f.name}</div>
            {rows.slice(0, 8).map((r) => (
              <div className="comp-row" key={r.code}>
                <span className="swatch" style={{ background: v.colors[r.code] }} />
                <span className="comp-name">{v.categories[r.code]}</span>
                <span className="comp-bar">
                  <span style={{ width: `${(100 * r.n) / tot}%`, background: v.colors[r.code] }} />
                </span>
                <span className="comp-n">{((100 * r.n) / tot).toFixed(0)}%</span>
              </div>
            ))}
            {rows.length > 8 && <div className="muted small">+{rows.length - 8} more</div>}
          </div>
        );
      })}
    </section>
  );
}
