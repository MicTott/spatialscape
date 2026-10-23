/**
 * Cell shape tiles (written by python/src/spatialscape/shapes.py): the index, which tiles a view needs, how to
 * group them into few byte-range requests, and how to decode one tile into what the shape layers draw.
 * Pure functions, shared by the worker and the tests.
 */
import { earcut } from "@math.gl/polygon";
import { tilesInRect as tilesInRectBase, unplane16, unplane32, type TileIndexBase } from "./tileIndex";

/** [ix, iy, byte offset in shapes.bin, bytes, rings, vertices] */
export type ShapeTileEntry = [number, number, number, number, number, number];

export interface ShapeIndex extends TileIndexBase {
  reach: number; // um: the largest centroid-to-vertex distance, by which a view is widened
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

export { coalesce, tileKey } from "./tileIndex";

/** The tiles a rectangle of the sample frame needs, widened by the index's reach. */
export function tilesInRect(index: ShapeIndex, byKey: Map<string, ShapeTileEntry>, rect: [number, number, number, number]): ShapeTileEntry[] {
  return tilesInRectBase(index, byKey, rect, index.reach);
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
  const rows = unplane32(buf, o, rings);
  for (let i = 1; i < rings; i++) rows[i] += rows[i - 1]; // steps -> rows
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
  const tris = new Uint32Array(Math.max(0, nv - 2 * rings) * 3); // a simple c-gon is c - 2 triangles
  let nt = 0;
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
    for (let k = 0; k < t.length && nt < tris.length; k++) tris[nt++] = base + t[k];
  }
  startIndices[rings] = w;
  const indices = nt === tris.length ? tris : tris.slice(0, nt);
  const bytes = positions.byteLength + vertexRow.byteLength + startIndices.byteLength + indices.byteLength + rows.byteLength;
  return { rows, startIndices, positions, vertexRow, indices, bytes };
}
