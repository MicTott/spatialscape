/**
 * Cell shape tiles (written by python/src/spatialscape/shapes.py): the index, which tiles a view needs, how to
 * group them into few byte-range requests, and how to decode one tile into what the shape layers draw.
 * Pure functions, shared by the worker and the tests.
 */
import { earcut } from "@math.gl/polygon";

/** [ix, iy, byte offset in shapes.bin, bytes, rings, vertices] */
export type ShapeTileEntry = [number, number, number, number, number, number];

export interface ShapeIndex {
  version: number;
  grid: number; // um per stored unit
  tile: number; // um
  origin: [number, number]; // um, sample frame
  nx: number;
  ny: number;
  reach: number; // um: the largest centroid-to-vertex distance, by which a view is widened
  layout: "packed" | "files";
  tiles: ShapeTileEntry[];
}

/** A decoded tile, ready for the shape layers: closed rings (the first vertex repeated at the end of each). */
export interface ShapeTile {
  rows: Uint32Array; // bundle row of each ring's cell, ascending
  startIndices: Uint32Array; // rings + 1 entries into the closed vertex list
  positions: Float32Array; // closed vertices, x y, um in the sample frame
  vertexRow: Uint32Array; // the cell row of every closed vertex, for gathering per-cell colour bytes
  indices: Uint32Array; // triangles over the closed vertex list (filled shapes)
  bytes: number; // memory held, for the cache budget
}

export const tileKey = (ix: number, iy: number) => `${ix}_${iy}`;

/** The tiles a rectangle of the sample frame needs, widened by the index's reach. */
export function tilesInRect(index: ShapeIndex, byKey: Map<string, ShapeTileEntry>, rect: [number, number, number, number]): ShapeTileEntry[] {
  const [x0, y0, x1, y1] = rect;
  const r = index.reach;
  const i0 = Math.max(0, Math.floor((x0 - r - index.origin[0]) / index.tile));
  const i1 = Math.min(index.nx - 1, Math.floor((x1 + r - index.origin[0]) / index.tile));
  const j0 = Math.max(0, Math.floor((y0 - r - index.origin[1]) / index.tile));
  const j1 = Math.min(index.ny - 1, Math.floor((y1 + r - index.origin[1]) / index.tile));
  const out: ShapeTileEntry[] = [];
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
export function coalesce(entries: ShapeTileEntry[], maxBytes = 1 << 20): ShapeTileEntry[][] {
  const sorted = [...entries].sort((a, b) => a[2] - b[2]);
  const runs: ShapeTileEntry[][] = [];
  let cur: ShapeTileEntry[] = [];
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

function unplane16(buf: Uint8Array, o: number, n: number): Int16Array {
  const out = new Int16Array(n);
  for (let i = 0; i < n; i++) out[i] = (buf[o + i] | (buf[o + n + i] << 8)) << 16 >> 16;
  return out;
}

/** Decode one decompressed tile (see the layout in shapes.py). */
export function decodeShapeTile(buf: Uint8Array, origin: [number, number], grid: number): ShapeTile {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const rings = dv.getUint32(0, true);
  const nv = dv.getUint32(4, true);
  if (rings === 0) {
    return { rows: new Uint32Array(0), startIndices: new Uint32Array(1), positions: new Float32Array(0), vertexRow: new Uint32Array(0), indices: new Uint32Array(0), bytes: 0 };
  }
  let o = 8;
  const rows = new Uint32Array(rings);
  let acc = 0;
  for (let i = 0; i < rings; i++) {
    acc += (buf[o + i] | (buf[o + rings + i] << 8) | (buf[o + 2 * rings + i] << 16) | (buf[o + 3 * rings + i] << 24)) >>> 0;
    rows[i] = acc;
  }
  o += 4 * rings;
  const counts = buf.subarray(o, o + rings);
  o += rings;
  const fx = unplane16(buf, o, rings);
  o += 2 * rings;
  const fy = unplane16(buf, o, rings);
  o += 2 * rings;
  const ns = nv - rings;
  const sx = unplane16(buf, o, ns);
  o += 2 * ns;
  const sy = unplane16(buf, o, ns);
  if (o + 2 * ns > buf.length) throw new Error("shape tile is shorter than its header says");

  const closed = nv + rings;
  const positions = new Float32Array(closed * 2);
  const vertexRow = new Uint32Array(closed);
  const startIndices = new Uint32Array(rings + 1);
  const tris: number[] = [];
  const ring = new Float64Array(2 * 256);
  let w = 0;
  let s = 0;
  for (let r = 0; r < rings; r++) {
    const c = counts[r];
    startIndices[r] = w;
    let qx = fx[r];
    let qy = fy[r];
    const base = w;
    for (let k = 0; k < c; k++) {
      if (k > 0) {
        qx += sx[s];
        qy += sy[s];
        s++;
      }
      const x = origin[0] + qx * grid;
      const y = origin[1] + qy * grid;
      positions[w * 2] = x;
      positions[w * 2 + 1] = y;
      ring[k * 2] = x;
      ring[k * 2 + 1] = y;
      vertexRow[w] = rows[r];
      w++;
    }
    positions[w * 2] = positions[base * 2];
    positions[w * 2 + 1] = positions[base * 2 + 1];
    vertexRow[w] = rows[r];
    w++;
    const t = earcut(ring.subarray(0, c * 2), undefined, 2);
    for (let k = 0; k < t.length; k++) tris.push(base + t[k]);
  }
  startIndices[rings] = w;
  const indices = Uint32Array.from(tris);
  const bytes = positions.byteLength + vertexRow.byteLength + startIndices.byteLength + indices.byteLength + rows.byteLength;
  return { rows, startIndices, positions, vertexRow, indices, bytes };
}
