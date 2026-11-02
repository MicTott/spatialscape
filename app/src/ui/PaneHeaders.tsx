import { store, useViewer } from "../store/store";
import { MAX_GROUP_PANES, levelName, metaName, PANE_HEADER, presentLevels, SECTION_KEY } from "../views/panes";
import { pinSection, unpinSection } from "../views/pins";

/** The caption strip above each pane when the canvas is split by a meta key or a section is pinned. A group pane
 *  shows its group and section count and, with more groups than panes, a select to choose which group it shows.
 *  A pinned window shows a select of every section and an × to unpin; the grid beside it says "all sections".
 *  The active pane is underlined. */
export function PaneHeaders() {
  const manifest = useViewer((s) => s.manifest);
  const panes = useViewer((s) => s.panes);
  const rects = useViewer((s) => s.viewRects);
  const splitBy = useViewer((s) => s.splitBy);
  const pins = useViewer((s) => s.pins);
  const active = useViewer((s) => s.activeView);
  if (!manifest || !panes.some((p) => p.key)) return null;
  const pinned = panes.some((p) => p.key === SECTION_KEY);
  const sections = pinned ? manifest.samples.filter((s) => s.kind !== "embedding") : [];
  const key = pinned ? SECTION_KEY : splitBy?.key;
  if (!key) return null;
  const levels = pinned ? [] : presentLevels(manifest, key);
  const chosen = panes.filter((p) => p.key).map((p) => p.value!);
  const keyName = metaName(manifest, key);
  const setGroupAt = (idx: number, value: string) => {
    if (!splitBy) return;
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
        const side = p.id === "g0" ? "left" : "right";
        return (
          <div
            key={p.id}
            className={`pane-head${p.id === active ? " active" : ""}${p.key === SECTION_KEY ? " pinned" : ""}`}
            style={{ left: r.x, top: r.y - PANE_HEADER, width: r.w, height: PANE_HEADER }}
            onPointerDown={() => store.getState().set({ activeView: p.id })}
            title={p.key === SECTION_KEY ? `pinned ${side}` : p.key ? `${keyName}: ${p.value}` : undefined}
          >
            {p.key === SECTION_KEY ? (
              <>
                <span className="pin-glyph" aria-hidden="true">
                  ⌖
                </span>
                <select value={p.value!} onChange={(e) => pinSection(e.target.value, side)} title={`which section this window shows (pinned ${side})`}>
                  {sections.map((s) => (
                    <option key={s.id} value={s.id} disabled={pins.includes(s.id) && s.id !== p.value}>
                      {s.name}
                    </option>
                  ))}
                </select>
                <span className="n">pinned {side}</span>
                <button className="unpin" onClick={() => unpinSection(p.value!)} aria-label={`unpin ${p.label}`} title="unpin: this window goes back to the grid">
                  ×
                </button>
              </>
            ) : p.key && levels.length > MAX_GROUP_PANES ? (
              <select value={p.value!} onChange={(e) => setGroupAt(idx, e.target.value)} title="which group this pane shows">
                {levels.map((l) => (
                  <option key={l} value={l} disabled={chosen.includes(l) && l !== p.value}>
                    {levelName(manifest, key, l)}
                  </option>
                ))}
              </select>
            ) : (
              <span className="cap">{p.label}</span>
            )}
            {p.key !== SECTION_KEY && (
              <span className="n">
                {p.count} section{p.count === 1 ? "" : "s"}
                {p.hidden ? ` · ${p.hidden} hidden` : ""}
              </span>
            )}
            {p.key && p.key !== SECTION_KEY && <span className="key muted">{keyName}</span>}
          </div>
        );
      })}
    </>
  );
}
