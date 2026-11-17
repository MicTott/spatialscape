/** How many (shuffled-prefix) points to draw for a sample given its on-screen footprint.
 *
 *  Zoomed out, a sample draws `LOD_DENSITY` points per screen pixel of its bounding box: more could not be told apart.
 *  Zooming in grows the box and with it the count, until every point is drawn. The count stops at `LOD_CEILING` per
 *  sample (or at what a very large pane could show, when that is more), so a sample of up to two million points is
 *  complete once you are close, on any window, and a larger one stays a sample. */
export const LOD_DENSITY = 0.6; // points per screen pixel of sample bbox area
export const LOD_MIN = 3000;
export const LOD_CEILING = 2_000_000; // the most points one sample draws

export function drawCount(nObs: number, worldBbox: [number, number, number, number], zoom: number, viewportPx: [number, number]): number {
  const scale = Math.pow(2, zoom); // px per world unit (OrthographicView)
  const w = (worldBbox[2] - worldBbox[0]) * scale;
  const h = (worldBbox[3] - worldBbox[1]) * scale;
  const k = Math.ceil(w * h * LOD_DENSITY);
  const ceiling = Math.max(LOD_CEILING, Math.ceil(viewportPx[0] * viewportPx[1] * 1.5 * LOD_DENSITY));
  return Math.min(nObs, Math.max(LOD_MIN, Math.min(k, ceiling)));
}

/** True if the sample's world bbox intersects the view rectangle. */
export function intersects(a: [number, number, number, number], b: [number, number, number, number]): boolean {
  return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
}
