/**
 * The per-cell row store (`samples/<id>/rows.zarr`): the quantized matrix again as sparse rows along a Morton curve,
 * read for the cells a test needs. Pure planning here (which runs of the store to fetch), the arrays come from any
 * zarrita store: the worker's FetchStore in the app, a FileSystemStore in tests.
 */
import * as zarr from "zarrita";

export interface RowsHandle {
  indptr: Uint32Array; // stored values before each row of the store (nObs + 1)
  pos: Uint32Array; // store position of each bundle row
  gene: zarr.Array<"uint16" | "uint32", any>;
  value: zarr.Array<"uint8", any>;
  chunk: number; // values per inner chunk
}

/** Rows of a few cells as one CSR block: `indptr` over the cells in the order asked, gene indices and codes. */
export interface CellRows {
  indptr: Uint32Array;
  gene: Uint32Array;
  value: Uint8Array;
}

/** Contiguous store runs [start, end) covering the given store positions, neighbouring runs merged when the gap
 *  between them holds fewer stored values than `gap` (fetching a little extra beats another request). */
export function planRuns(positions: Uint32Array, indptr: Uint32Array, gap: number): [number, number][] {
  const sorted = Uint32Array.from(positions).sort();
  const runs: [number, number][] = [];
  for (const p of sorted) {
    const last = runs[runs.length - 1];
    if (last && p < last[1]) continue; // duplicate
    if (last && indptr[p] - indptr[last[1]] < gap) last[1] = p + 1;
    else runs.push([p, p + 1]);
  }
  return runs;
}

export async function openRows(group: zarr.Group<any>, chunk: number): Promise<RowsHandle> {
  const [indptrArr, posArr, gene, value] = await Promise.all([
    zarr.open.v3(group.resolve("indptr"), { kind: "array" }),
    zarr.open.v3(group.resolve("pos"), { kind: "array" }),
    zarr.open.v3(group.resolve("gene"), { kind: "array" }),
    zarr.open.v3(group.resolve("value"), { kind: "array" }),
  ]);
  const [indptr, pos] = await Promise.all([zarr.get(indptrArr as zarr.Array<"uint32", any>), zarr.get(posArr as zarr.Array<"uint32", any>)]);
  return { indptr: new Uint32Array(indptr.data as Uint32Array), pos: new Uint32Array(pos.data as Uint32Array), gene: gene as RowsHandle["gene"], value: value as RowsHandle["value"], chunk };
}

/** The stored values of the given bundle rows, in the order asked. */
export async function fetchRows(h: RowsHandle, rows: ArrayLike<number>): Promise<CellRows> {
  const n = rows.length;
  const positions = new Uint32Array(n);
  for (let i = 0; i < n; i++) positions[i] = h.pos[rows[i]];
  const runs = planRuns(positions, h.indptr, h.chunk >> 1);
  // fetch each run's value span once; runs are disjoint and sorted
  const spans = await Promise.all(
    runs.map(async ([a, b]) => {
      const lo = h.indptr[a];
      const hi = h.indptr[b];
      if (hi === lo) return { lo, gene: new Uint32Array(0), value: new Uint8Array(0) };
      const [g, v] = await Promise.all([zarr.get(h.gene, [zarr.slice(lo, hi)]), zarr.get(h.value, [zarr.slice(lo, hi)])]);
      return { lo, gene: Uint32Array.from(g.data as ArrayLike<number>), value: new Uint8Array(v.data as Uint8Array) };
    }),
  );
  const spanOf = (p: number) => {
    let lo = 0;
    let hi = runs.length - 1;
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (runs[mid][0] <= p) lo = mid;
      else hi = mid - 1;
    }
    return spans[lo];
  };
  const indptr = new Uint32Array(n + 1);
  for (let i = 0; i < n; i++) indptr[i + 1] = indptr[i] + (h.indptr[positions[i] + 1] - h.indptr[positions[i]]);
  const gene = new Uint32Array(indptr[n]);
  const value = new Uint8Array(indptr[n]);
  for (let i = 0; i < n; i++) {
    const p = positions[i];
    const s = spanOf(p);
    const a = h.indptr[p] - s.lo;
    const len = indptr[i + 1] - indptr[i];
    gene.set(s.gene.subarray(a, a + len), indptr[i]);
    value.set(s.value.subarray(a, a + len), indptr[i]);
  }
  return { indptr, gene, value };
}
