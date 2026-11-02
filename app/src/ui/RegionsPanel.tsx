/** Regions: draw your own annotation. Add a group, lasso as many areas as you like in any section, switch groups
 *  (click, or keys 1-9), colour the cells by it, export the table or save the drawing. */
import { useRef, useState } from "react";
import { cancelRegionTest, runRegionTest, type RestScope, type TestMode } from "../compare/live";
import { DEFAULT_CAP } from "../data/de";
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
          <RegionTest drawn={regions.groups.filter((g) => g.polygons.length).length} />
        </>
      )}
    </section>
  );
}

/** Differential expression on the drawn regions: what to compare, how many cells, run. The result opens under
 *  the maps as a comparison. Needs the bundle's per-cell row store. */
function RegionTest({ drawn }: { drawn: number }) {
  const manifest = useViewer((s) => s.manifest)!;
  const test = useViewer((s) => s.test);
  const note = useViewer((s) => s.testNote);
  const [mode, setMode] = useState<TestMode | null>(null);
  const [scope, setScope] = useState<RestScope>("drawn");
  const [cap, setCap] = useState(DEFAULT_CAP);
  const ctl = () => window.__sscape?.controller ?? null;
  if (!drawn) return null;
  const hasRows = manifest.samples.some((s) => s.rows);
  if (!hasRows)
    return (
      <div className="de">
        <div className="de-head">Differential expression</div>
        <div className="muted small">
          This bundle has no per-cell row store, which the test reads. Build it with <code>expression.rows: true</code>.
        </div>
      </div>
    );
  const pair = drawn === 2;
  const m: TestMode = mode ?? (pair ? "pair" : "rest");
  return (
    <div className="de">
      <div className="de-head">Differential expression</div>
      <div className="de-row">
        <select value={m} onChange={(e) => setMode(e.target.value as TestMode)} disabled={!!test} title="what is tested against what; the two sides are tested per platform">
          {pair && <option value="pair">one region against the other</option>}
          <option value="rest">{drawn === 1 ? "the region against the rest" : "each region against the rest"}</option>
        </select>
        {m === "rest" && (
          <select value={scope} onChange={(e) => setScope(e.target.value as RestScope)} disabled={!!test} title="which cells count as the rest">
            <option value="drawn">rest: other cells of the sections drawn on</option>
            <option value="all">rest: other cells of every section</option>
          </select>
        )}
        <select value={cap} onChange={(e) => setCap(+e.target.value)} disabled={!!test} title="a larger side is cut to this many cells, taken as whole blocks of the row store">
          <option value={3000}>up to 3,000 cells a side</option>
          <option value={10000}>up to 10,000 cells a side</option>
        </select>
      </div>
      <div className="de-row">
        {test ? (
          <>
            <span className="muted small de-progress">{test.text}…</span>
            <button onClick={() => ctl() && cancelRegionTest(ctl()!)}>cancel</button>
          </>
        ) : (
          <button className="primary" onClick={() => ctl() && void runRegionTest(ctl()!, { mode: m, scope, cap })} title="Wilcoxon rank-sum per gene on single cells; the result opens under the maps">
            run the test
          </button>
        )}
      </div>
      {note && <div className="muted small">{note}</div>}
    </div>
  );
}
