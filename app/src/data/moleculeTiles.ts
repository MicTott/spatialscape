/**
 * Molecule tiles (written by python/src/spatialscape/molecules.py): the index and the decoder for one tile.
 * Pure functions, shared by the worker and the tests.
 */
import { unplane16, unplane32, type TileIndexBase } from "./tileIndex";

/** [ix, iy, byte offset, bytes, molecules] */
export type MoleculeTileEntry = [number, number, number, number, number];

export interface MoleculeIndex extends TileIndexBase {
  genes: string[]; // a molecule's gene id indexes this list
  counts: number[]; // molecules per gene, whole sample (the gate's estimate of what a view holds)
  count: number;
  flags: string[]; // bit names: ["assigned", "nucleus"]
  tiles: MoleculeTileEntry[];
}

export const FLAG_ASSIGNED = 1;
export const FLAG_NUCLEUS = 2;

/** A decoded tile, ready for the molecule layer: gene-major, Morton order within a gene. */
export interface MoleculeTile {
  n: number;
  positions: Float32Array; // x y, um in the sample frame
  gene: Uint16Array;
  flags: Uint8Array;
  runs: Uint16Array; // gene id of each run, ascending
  runStarts: Uint32Array; // runs + 1 entries: molecules [runStarts[k], runStarts[k+1]) belong to runs[k]
  bytes: number;
}

/** Decode one decompressed tile (see the layout in molecules.py). */
export function decodeMoleculeTile(buf: Uint8Array, origin: [number, number], grid: number): MoleculeTile {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const n = dv.getUint32(0, true);
  const nruns = dv.getUint32(4, true);
  let o = 8;
  const runs = new Uint16Array(nruns);
  for (let i = 0; i < nruns; i++) runs[i] = buf[o + i] | (buf[o + nruns + i] << 8);
  o += 2 * nruns;
  const counts = unplane32(buf, o, nruns);
  o += 4 * nruns;
  if (o + 5 * n > buf.length) throw new Error("molecule tile is shorter than its header says");
  const dx = unplane16(buf, o, n);
  o += 2 * n;
  const dy = unplane16(buf, o, n);
  o += 2 * n;
  const flags = buf.slice(o, o + n);
  const positions = new Float32Array(n * 2);
  const gene = new Uint16Array(n);
  const runStarts = new Uint32Array(nruns + 1);
  let qx = 0;
  let qy = 0;
  let m = 0;
  for (let r = 0; r < nruns; r++) {
    runStarts[r] = m;
    const g = runs[r];
    const c = counts[r];
    for (let k = 0; k < c; k++) {
      qx += dx[m];
      qy += dy[m];
      positions[m * 2] = origin[0] + qx * grid;
      positions[m * 2 + 1] = origin[1] + qy * grid;
      gene[m] = g;
      m++;
    }
  }
  runStarts[nruns] = m;
  if (m !== n) throw new Error(`molecule tile runs cover ${m} molecules, the header says ${n}`);
  const bytes = positions.byteLength + gene.byteLength + flags.byteLength + runs.byteLength + runStarts.byteLength;
  return { n, positions, gene, flags, runs, runStarts, bytes };
}
