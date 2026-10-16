/** Regions: draw your own annotation. Add a group, lasso as many areas as you like in any section, switch groups
 *  (click, or keys 1-9), colour the cells by it, export the table or save the drawing. */
import { useRef, useState } from "react";
import { store, useViewer } from "../store/store";

export function RegionsPanel() {
  const regions = useViewer((s) => s.regions);
  const manifest = useViewer((s) => s.manifest);
  const tool = useViewer((s) => s.tool);
  const color = useViewer((s) => s.color);
  const counts = useViewer((s) => s.categoryCounts);
  const [editing, setEditing] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const file = useRef<HTMLInputElement>(null);
  if (!manifest) return null;
  const st = store.getState();
  const ctl = () => window.__sscape?.controller ?? null;
  const field = ctl()?.regions.field ?? "regions";
  const cnt = counts[field];
  const coloring = color?.kind === "field" && color.field === field;
  const load = (f: File) =>
    void f.text().then((t) => {
      setProblem(ctl()?.regions.importJSON(t) ?? null);
      if (file.current) file.current.value = "";
    });
  return (
    <section className="regions">
      <h2>
        Regions
        <span className="legend-actions">
          <button onClick={() => st.addRegionGroup()} title="a new group; every lasso then adds an area to it">
            + group
          </button>
          {regions.groups.length > 0 && (
            <>
              <button onClick={() => void ctl()?.regions.exportCSV()} title="sample, cell_id, region for every cell inside a region">
                export CSV
              </button>
              <button onClick={() => ctl()?.regions.exportJSON()} title="save the drawing (groups and polygons) to load again">
                save
              </button>
            </>
          )}
          <button onClick={() => file.current?.click()} title="load a drawing saved earlier">
            load
          </button>
          {regions.groups.length > 0 && <button onClick={() => st.setRegions([])}>clear</button>}
        </span>
      </h2>
      <input ref={file} type="file" accept=".json,application/json" hidden onChange={(e) => e.target.files?.[0] && load(e.target.files[0])} />
      {problem && <div className="muted small">{problem}</div>}
      {regions.groups.length === 0 ? (
        <p className="muted small">Your own annotation: add a group, lasso one or more areas in any section, then add the next group. Keys 1–9 switch groups, Backspace removes the last area.</p>
      ) : (
        <>
          <div className="region-list">
            {regions.groups.map((g, i) => (
              <div key={g.id} className={`region-row${g.id === regions.active ? " active" : ""}`} onClick={() => st.setActiveRegion(g.id === regions.active ? null : g.id)} title={g.id === regions.active ? "drawing into this group; click to stop" : "click to draw into this group"}>
                <input type="color" value={g.color} onChange={(e) => st.updateRegionGroup(g.id, { color: e.target.value })} onClick={(e) => e.stopPropagation()} title="colour" />
                {editing === g.id ? (
                  <input
                    className="region-edit"
                    autoFocus
                    defaultValue={g.name}
                    onClick={(e) => e.stopPropagation()}
                    onBlur={(e) => {
                      st.updateRegionGroup(g.id, { name: e.target.value.trim() || g.name });
                      setEditing(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                      if (e.key === "Escape") setEditing(null);
                    }}
                  />
                ) : (
                  <span
                    className="region-name"
                    onDoubleClick={(e) => {
                      e.stopPropagation();
                      setEditing(g.id);
                    }}
                    title="double-click to rename"
                  >
                    {i < 9 && <kbd>{i + 1}</kbd>} {g.name}
                  </span>
                )}
                <span className="legend-actions">
                  <button
                    disabled={!g.polygons.length}
                    onClick={(e) => {
                      e.stopPropagation();
                      st.undoRegionPolygon(g.id);
                    }}
                    title="remove the last area of this group"
                  >
                    undo
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      st.removeRegionGroup(g.id);
                    }}
                    title="remove the group"
                  >
                    ×
                  </button>
                </span>
                <span className="muted small region-n">
                  {g.polygons.length} area{g.polygons.length === 1 ? "" : "s"} · {(cnt?.[i] ?? 0).toLocaleString()} cells
                </span>
              </div>
            ))}
          </div>
          <div className="muted small">
            {regions.active ? (tool === "lasso" ? "Drag a lasso around an area; release; repeat. Esc stops drawing." : "Press L or the lasso button to draw into the highlighted group.") : "Click a group to draw into it."}
          </div>
          <div className="chips">
            <button className={`chip${coloring ? " on" : ""}`} onClick={() => st.setColor({ kind: "field", field })} title="colour every cell by the region it falls in; the legend then shows the counts">
              color cells by regions
            </button>
          </div>
        </>
      )}
    </section>
  );
}
