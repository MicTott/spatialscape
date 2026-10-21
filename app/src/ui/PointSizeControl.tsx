import { store, useViewer, type ViewKind } from "../store/store";

const MIN = 0.25;
const MAX = 4;

/** Slider for the point radius multiplier of one pane kind, bottom-left of the first pane of that kind. */
function PointSizeControl({ view }: { view: ViewKind }) {
  const paneId = useViewer((s) => s.panes.find((p) => p.kind === view)?.id);
  const rect = useViewer((s) => (paneId ? s.viewRects[paneId] : undefined));
  const value = useViewer((s) => s.pointScale[view]);
  if (!rect) return null;
  const update = (v: number) => store.getState().set({ pointScale: { ...store.getState().pointScale, [view]: v } });
  return (
    <div className={`pointsize ${view}`} style={{ left: rect.x + 12, top: rect.y + rect.h - 42, bottom: "auto" }} title="Point size (double-click the slider to reset)">
      <span className="cap">Point size</span>
      <span className="dot" aria-hidden />
      <input
        type="range"
        min={MIN}
        max={MAX}
        step={0.05}
        value={value}
        aria-label={`${view} point size`}
        onChange={(e) => update(+e.target.value)}
        onDoubleClick={() => update(1)}
      />
      <span className="dot big" aria-hidden />
      <small>×{value.toFixed(2)}</small>
    </div>
  );
}

export function PointSizeControls() {
  const hasManifest = useViewer((s) => !!s.manifest);
  if (!hasManifest) return null;
  return (
    <>
      <PointSizeControl view="spatial" />
      <PointSizeControl view="embedding" />
    </>
  );
}
