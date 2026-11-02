/** The per-cell row store read through zarrita: a few cells' rows equal the gene-major columns at those cells. */
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as zarr from "zarrita";
import { FileSystemStore } from "@zarrita/storage";
import { fetchRows, openRows, planRuns } from "../data/rows";

const bundle = resolve(__dirname, "../../../examples/synthetic");
const manifestPath = resolve(bundle, "manifest.json");
const hasRows = existsSync(manifestPath) && !!JSON.parse(readFileSync(manifestPath, "utf8")).samples.find((s: any) => s.id === "sampleA")?.rows;

describe("run planning", () => {
  it("merges neighbouring positions and small gaps, keeps far ones apart, drops duplicates", () => {
    const indptr = Uint32Array.from([0, 10, 20, 30, 40, 1000, 1010, 1020]);
    expect(planRuns(Uint32Array.from([2, 0, 1, 2]), indptr, 5)).toEqual([[0, 3]]);
    expect(planRuns(Uint32Array.from([0, 2]), indptr, 5)).toEqual([
      [0, 1],
      [2, 3],
    ]);
    expect(planRuns(Uint32Array.from([0, 2]), indptr, 50)).toEqual([[0, 3]]);
    expect(planRuns(Uint32Array.from([3, 5]), indptr, 50)).toEqual([
      [3, 4],
      [5, 6],
    ]);
  });
});

describe.skipIf(!hasRows)("rows.zarr", () => {
  it("returns each asked cell's nonzero genes and codes, matching the gene-major store", async () => {
    const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
    const s = manifest.samples.find((x: any) => x.id === "sampleA");
    const group = await zarr.open.v3(zarr.root(new FileSystemStore(resolve(bundle, "samples/sampleA/rows.zarr"))), { kind: "group" });
    const h = await openRows(group, s.rows.chunk);
    expect(h.indptr.length).toBe(s.nObs + 1);
    expect(h.indptr[s.nObs]).toBe(s.rows.nnz);
    const cells = [5, 0, 1999, 731, 5];
    const r = await fetchRows(h, cells);
    expect(r.indptr.length).toBe(cells.length + 1);
    const u8 = (await zarr.open.v3(zarr.root(new FileSystemStore(resolve(bundle, "samples/sampleA/expr.zarr"))).resolve("u8"), { kind: "array" })) as zarr.Array<"uint8">;
    for (let i = 0; i < cells.length; i++) {
      const got = new Map<number, number>();
      for (let k = r.indptr[i]; k < r.indptr[i + 1]; k++) got.set(r.gene[k], r.value[k]);
      for (let g = 0; g < s.nGenes; g++) {
        const col = await zarr.get(u8, [g, zarr.slice(cells[i], cells[i] + 1)]);
        const v = (col.data as Uint8Array)[0];
        expect(got.get(g) ?? 0).toBe(v);
      }
    }
    // the same cell asked twice comes back twice, identical
    expect(Array.from(r.gene.subarray(r.indptr[0], r.indptr[1]))).toEqual(Array.from(r.gene.subarray(r.indptr[4], r.indptr[5])));
  });
});
