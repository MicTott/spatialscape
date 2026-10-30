import { useState } from "react";
import { store, useViewer } from "../store/store";
import { shapeMode } from "../views/shapes";
import { OVERLAY_HEX } from "../views/overlay";
import { LayerRow } from "./Group";

/** How cells are drawn: their shapes once zoomed in, another segmentation over them, and cluster names in the embedding. */
export function CellRows() {
  const manifest = useViewer((s) => s.manifest)!;
  const showImages = useViewer((s) => s.showImages);
  const cellShapes = useViewer((s) => s.cellShapes);
  const clusterLabels = useViewer((s) => s.clusterLabels);
  const overlay = useViewer((s) => s.overlay);
  const focus = useViewer((s) => s.focus);
  const color = useViewer((s) => s.color);
  const panes = useViewer((s) => s.panes);
  const set = store.getState().set;
  const hasShapes = manifest.samples.some((s) => s.shapes || s.polygons);
  // the other segmentations of these sections, by id, with their names
  const segs = new Map<string, string>();
  for (const smp of manifest.samples) for (const sg of smp.segmentations ?? []) if (!segs.has(sg.id)) segs.set(sg.id, sg.name);
  const [lastOverlay, setLastOverlay] = useState<string | null>(null);
  const hasEmbedding = manifest.samples.some((s) => s.kind === "embedding");
  if (!hasShapes && !hasEmbedding && !segs.size) return null;
  const categorical = color?.kind === "field" && manifest.fields.some((f) => f.id === color.field && f.type === "categorical");
  const measuredInEmbedding = color?.kind === "field" && manifest.samples.some((s) => s.kind === "embedding" && s.fields.includes(color.field));
  const labelsHint = !panes.some((p) => p.kind === "embedding")
    ? "Open a single-cell view to display cluster labels."
    : !categorical ? "Choose a categorical annotation to display cluster labels."
    : !measuredInEmbedding ? "This annotation is not measured in the single-cell view."
    : "Cluster names appear on the single-cell view when there is room.";
  // the comparison table: the focused section, or every section with another segmentation summed
  const compared = manifest.samples.filter((s) => s.segmentations?.length && (!focus || s.id === focus));
  const row = (name: string, pick: (s: (typeof manifest.samples)[number]) => { cells: number; medianArea?: number | null } | undefined) => {
    const parts = compared.map(pick).filter((x): x is { cells: number; medianArea?: number | null } => !!x);
    if (!parts.length) return null;
    const cells = parts.reduce((n, x) => n + x.cells, 0);
    const areas = parts.map((x) => x.medianArea).filter((a): a is number => a != null);
    const area = areas.length ? areas.reduce((a, b) => a + b, 0) / areas.length : null;
    return (
      <tr key={name}>
        <td>{name}</td>
        <td>{cells.toLocaleString()}</td>
        <td>{area != null ? `${Math.round(area)} µm²` : "–"}</td>
      </tr>
    );
  };
  const shapeModes = new Set(manifest.samples.filter((s) => s.shapes || s.polygons).map((s) => shapeMode(cellShapes, showImages && s.images.length > 0)));
  const shownMode = shapeModes.size === 1 ? [...shapeModes][0] : null;
  return (
    <section className="cell-rows">
      <h2>Drawing</h2>
      {hasShapes && (
        <LayerRow name="Draw cells as" summary={shownMode ? `${shownMode} when zoomed in` : "by sample"} title="how cells are drawn once zoomed in far enough to see their shapes; the chosen mode again returns to automatic (filled, or outlined over an image)">
          <div className="tabs">
            {(["dots", "filled", "outlined"] as const).map((m) => (
              <button key={m} className={shownMode === m ? "on" : ""} onClick={() => set({ cellShapes: cellShapes === m ? "auto" : m })}>
                {m}
              </button>
            ))}
          </div>
        </LayerRow>
      )}
      {segs.size > 0 && (
        <LayerRow
          name="Compare with"
          on={overlay != null}
          onToggle={(v) => set({ overlay: v ? (lastOverlay ?? [...segs.keys()][0]) : null })}
          summary={overlay ? (segs.get(overlay) ?? overlay) : "a second segmentation"}
          title="another segmentation of the same sections, drawn as dashed edges over the cells once zoomed in"
        >
          <div className="overlay-pick">
            <span className="swatch" style={{ background: OVERLAY_HEX }} />
            <select
              value={overlay ?? ""}
              onChange={(e) => {
                setLastOverlay(e.target.value || null);
                set({ overlay: e.target.value || null });
              }}
            >
              {[...segs.entries()].map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </div>
          <table className="compare-table">
            <thead>
              <tr>
                <th>{compared.length === 1 ? compared[0].name : `${compared.length} sections`}</th>
                <th>cells</th>
                <th>median area</th>
              </tr>
            </thead>
            <tbody>
              {row("Cells", (s) => (s.shapes ? { cells: s.shapes.cells, medianArea: s.shapes.medianArea } : undefined))}
              {[...segs.entries()].map(([id, name]) => row(name, (s) => s.segmentations?.find((sg) => sg.id === id)))}
            </tbody>
          </table>
        </LayerRow>
      )}
      {hasEmbedding && (
        <>
          <LayerRow name="Embedding labels" on={clusterLabels} onToggle={(v) => set({ clusterLabels: v })} summary="cluster names" />
          {clusterLabels && <div className="muted small labels-hint">{labelsHint}</div>}
        </>
      )}
    </section>
  );
}
