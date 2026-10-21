import { store, useViewer, type PaneInfo } from "../store/store";
import { pointScaleFor } from "../views/panes";

const MIN = 0.25;
const MAX = 4;

/** Slider for the point radius multiplier of one pane, bottom-left of its rectangle. The single tissue canvas and the
 *  embedding set the base value of their kind; a group pane sets its own, and a double-click returns it to the base. */
function PointSizeControl({ pane }: { pane: PaneInfo }) {
  const rect = useViewer((s) => s.viewRects[pane.id]);
  const scales = useViewer((s) => s.pointScale);
  if (!rect) return null;
  const own = pane.key != null; // a group pane: its value overrides the shared spatial one
  const value = pointScaleFor(scales, pane.id, pane.kind);
  const update = (v: number) => store.getState().set({ pointScale: { ...store.getState().pointScale, [own ? pane.id : pane.kind]: v } });
  const reset = () => {
    const next = { ...store.getState().pointScale };
    if (own) delete next[pane.id];
    else next[pane.kind] = 1;
    store.getState().set({ pointScale: next });
  };
  return (
    <div className={`pointsize ${pane.kind}`} style={{ left: rect.x + 12, top: rect.y + rect.h - 42, bottom: "auto" }} title={own ? "Point size in this pane (double-click the slider to follow the others again)" : "Point size (double-click the slider to reset)"}>
      <span className="cap">Point size</span>
      <span className="dot" aria-hidden />
      <input type="range" min={MIN} max={MAX} step={0.05} value={value} aria-label={`${pane.label} point size`} onChange={(e) => update(+e.target.value)} onDoubleClick={reset} />
      <span className="dot big" aria-hidden />
      <small>×{value.toFixed(2)}</small>
    </div>
  );
}

export function PointSizeControls() {
  const panes = useViewer((s) => s.panes);
  if (!panes.length) return null;
  return (
    <>
      {panes.map((p) => (
        <PointSizeControl key={p.id} pane={p} />
      ))}
    </>
  );
}
