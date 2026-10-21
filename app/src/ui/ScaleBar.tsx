import { useViewer } from "../store/store";

const NICE = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];

/** A round length (µm) that spans about 110 px at `px` pixels per µm, with its label. */
export function niceScale(px: number): { um: number; label: string } {
  const target = 110 / px;
  const um = NICE.reduce((best, n) => (Math.abs(Math.log(n / target)) < Math.abs(Math.log(best / target)) ? n : best), NICE[0]);
  return { um, label: um >= 1000 ? `${um / 1000} mm` : `${um} µm` };
}

/** One scale bar per tissue pane, bottom-left of that pane's rectangle. */
export function ScaleBars() {
  const panes = useViewer((s) => s.panes);
  const rects = useViewer((s) => s.viewRects);
  const viewPx = useViewer((s) => s.viewPx);
  const manifest = useViewer((s) => s.manifest);
  if (!manifest) return null;
  return (
    <>
      {panes
        .filter((p) => p.kind === "spatial")
        .map((p) => {
          const px = viewPx[p.id];
          const rect = rects[p.id];
          if (!px || !rect) return null;
          const { um, label } = niceScale(px);
          return (
            <div key={p.id} className="scalebar" style={{ left: rect.x + 12, top: rect.y + rect.h - 56, bottom: "auto", width: um * px }}>
              <span>{label}</span>
            </div>
          );
        })}
    </>
  );
}
