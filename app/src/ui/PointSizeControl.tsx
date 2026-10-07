import { store, useViewer, type ViewId } from "../store/store";

const MIN = 0.25;
const MAX = 4;

/** Slider for the point radius multiplier of one view, bottom-left of that view's rectangle. */
function PointSizeControl({ view }: { view: ViewId }) {
  const rect = useViewer((s) => s.viewRects[view]);
  const value = useViewer((s) => s.pointScale[view]);
  if (!rect) return null;
  const update = (v: number) => store.getState().set({ pointScale: { ...store.getState().pointScale, [view]: v } });
  return (
    <div className={`pointsize ${view}`} style={{ left: rect.x + 12 }} title="Point size (double-click the slider to reset)">
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
