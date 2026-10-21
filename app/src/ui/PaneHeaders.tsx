import { store, useViewer } from "../store/store";
import { MAX_GROUP_PANES, metaName, PANE_HEADER, presentLevels } from "../views/panes";

/** The caption strip above each pane when the canvas is split by a meta key: the group, its section count, and,
 *  with more groups than panes, a select to choose which group the pane shows. The active pane is underlined. */
export function PaneHeaders() {
  const manifest = useViewer((s) => s.manifest);
  const panes = useViewer((s) => s.panes);
  const rects = useViewer((s) => s.viewRects);
  const splitBy = useViewer((s) => s.splitBy);
  const active = useViewer((s) => s.activeView);
  if (!manifest || !splitBy || !panes.some((p) => p.key)) return null;
  const levels = presentLevels(manifest, splitBy.key);
  const chosen = panes.filter((p) => p.key).map((p) => p.value!);
  const keyName = metaName(manifest, splitBy.key);
  const setGroupAt = (idx: number, value: string) => {
    const groups = [...chosen];
    groups[idx] = value;
    store.getState().set({ splitBy: { ...splitBy, groups } });
  };
  return (
    <>
      {panes.map((p) => {
        const r = rects[p.id];
        if (!r) return null;
        const idx = p.key ? chosen.indexOf(p.value!) : -1;
        return (
          <div
            key={p.id}
            className={`pane-head${p.id === active ? " active" : ""}`}
            style={{ left: r.x, top: r.y - PANE_HEADER, width: r.w, height: PANE_HEADER }}
            onPointerDown={() => store.getState().set({ activeView: p.id })}
            title={p.key ? `${keyName}: ${p.value}` : undefined}
          >
            {p.key && levels.length > MAX_GROUP_PANES ? (
              <select value={p.value!} onChange={(e) => setGroupAt(idx, e.target.value)} title="which group this pane shows">
                {levels.map((l) => (
                  <option key={l} value={l} disabled={chosen.includes(l) && l !== p.value}>
                    {l}
                  </option>
                ))}
              </select>
            ) : (
              <span className="cap">{p.label}</span>
            )}
            <span className="n">
              {p.count} section{p.count === 1 ? "" : "s"}
              {p.hidden ? ` · ${p.hidden} hidden` : ""}
            </span>
            {p.key && <span className="key muted">{keyName}</span>}
          </div>
        );
      })}
    </>
  );
}
