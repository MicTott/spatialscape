/** How many (shuffled-prefix) points to draw for a sample given its on-screen footprint. */
export const LOD_DENSITY = 0.6; // points per screen pixel of sample bbox area
export const LOD_MIN = 3000;

export function drawCount(nObs: number, worldBbox: [number, number, number, number], zoom: number, viewportPx: [number, number]): number {
  const scale = Math.pow(2, zoom); // px per world unit (OrthographicView)
  const w = (worldBbox[2] - worldBbox[0]) * scale;
  const h = (worldBbox[3] - worldBbox[1]) * scale;
  const area = Math.min(w * h, viewportPx[0] * viewportPx[1] * 1.5);
  const k = Math.ceil(area * LOD_DENSITY);
  return Math.min(nObs, Math.max(LOD_MIN, k));
}

/** True if the sample's world bbox intersects the view rectangle. */
export function intersects(a: [number, number, number, number], b: [number, number, number, number]): boolean {
  return a[0] <= b[2] && a[2] >= b[0] && a[1] <= b[3] && a[3] >= b[1];
}
