/**
 * Square spatial tiles over a sample's frame, shared by cell shapes and molecules: the index the Python build
 * writes (shapes.json, molecules.json), which tiles a rectangle needs, and how to group them into few byte-range
 * requests. Pure functions, used by the worker, the managers and the tests.
 */

/** [ix, iy, byte offset in the packed file, bytes, ...per-kind counts] */
export type TileEntry = [number, number, number, number, ...number[]];

export interface TileIndexBase {
  version: number;
  grid: number; // um per stored unit
  tile: number; // um
  origin: [number, number]; // um, sample frame
  nx: number;
  ny: number;
  layout: "packed" | "files";
  tiles: TileEntry[];
}

export const tileKey = (ix: number, iy: number) => `${ix}_${iy}`;

export function indexByKey<E extends TileEntry>(tiles: E[]): Map<string, E> {
  return new Map(tiles.map((e) => [tileKey(e[0], e[1]), e]));
}

/** The tiles a rectangle of the sample frame needs, widened by `reach` on every side. */
export function tilesInRect<E extends TileEntry>(index: TileIndexBase & { tiles: E[] }, byKey: Map<string, E>, rect: [number, number, number, number], reach = 0): E[] {
  const [x0, y0, x1, y1] = rect;
  const i0 = Math.max(0, Math.floor((x0 - reach - index.origin[0]) / index.tile));
  const i1 = Math.min(index.nx - 1, Math.floor((x1 + reach - index.origin[0]) / index.tile));
  const j0 = Math.max(0, Math.floor((y0 - reach - index.origin[1]) / index.tile));
  const j1 = Math.min(index.ny - 1, Math.floor((y1 + reach - index.origin[1]) / index.tile));
  const out: E[] = [];
  if (i1 < i0 || j1 < j0) return out;
  if ((i1 - i0 + 1) * (j1 - j0 + 1) > byKey.size) {
    for (const e of index.tiles) if (e[0] >= i0 && e[0] <= i1 && e[1] >= j0 && e[1] <= j1) out.push(e);
    return out;
  }
  for (let j = j0; j <= j1; j++)
    for (let i = i0; i <= i1; i++) {
      const e = byKey.get(tileKey(i, j));
      if (e) out.push(e);
    }
  return out;
}

/** Group tiles of a packed file into runs of adjacent bytes, each at most `maxBytes` (one range request per run). */
export function coalesce<E extends TileEntry>(entries: E[], maxBytes = 1 << 20): E[][] {
  const sorted = [...entries].sort((a, b) => a[2] - b[2]);
  const runs: E[][] = [];
  let cur: E[] = [];
  let start = 0;
  for (const e of sorted) {
    const prev = cur[cur.length - 1];
    if (prev && prev[2] + prev[3] === e[2] && e[2] + e[3] - start <= maxBytes) cur.push(e);
    else {
      if (cur.length) runs.push(cur);
      cur = [e];
      start = e[2];
    }
  }
  if (cur.length) runs.push(cur);
  return runs;
}

/** Signed 16-bit values stored as two byte planes (low plane first), starting at byte `o`. */
export function unplane16(buf: Uint8Array, o: number, n: number): Int16Array {
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) out[i] = ((buf[o + i] | (buf[o + n + i] << 8)) << 16) >> 16;
  return out;
}

/** Unsigned 32-bit values stored as four byte planes. */
export function unplane32(buf: Uint8Array, o: number, n: number): Uint32Array {
  const out = new Uint32Array(n);
  for (let i = 0; i < n; i++) out[i] = (buf[o + i] | (buf[o + n + i] << 8) | (buf[o + 2 * n + i] << 16) | (buf[o + 3 * n + i] << 24)) >>> 0;
  return out;
}
