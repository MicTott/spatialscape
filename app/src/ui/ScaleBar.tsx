import { useViewer } from "../store/store";

const NICE = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000];

/** A round length (µm) that spans about 110 px at `px` pixels per µm, with its label. */
export function niceScale(px: number): { um: number; label: string } {
  const target = 110 / px;
  const um = NICE.reduce((best, n) => (Math.abs(Math.log(n / target)) < Math.abs(Math.log(best / target)) ? n : best), NICE[0]);
  return { um, label: um >= 1000 ? `${um / 1000} mm` : `${um} µm` };
}

/** Scale bar for the spatial view, bottom-left of that view's rectangle. */
export function ScaleBar() {
  const px = useViewer((s) => s.viewPx.spatial);
  const rect = useViewer((s) => s.viewRects.spatial);
  const manifest = useViewer((s) => s.manifest);
  if (!px || !rect || !manifest) return null;
  const { um, label } = niceScale(px);
  const width = um * px;
  return (
    <div className="scalebar" style={{ left: rect.x + 12, width }}>
      <span>{label}</span>
    </div>
  );
}
