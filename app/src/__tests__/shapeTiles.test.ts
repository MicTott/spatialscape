import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { coalesce, decodeShapeTile, tileKey, tilesInRect, type ShapeIndex, type ShapeTileEntry } from "../data/shapeTiles";

const dir = fileURLToPath(new URL("./fixtures/shapes/", import.meta.url));
const index = JSON.parse(readFileSync(dir + "shapes.json", "utf8")) as ShapeIndex;
const blob = new Uint8Array(readFileSync(dir + "shapes.bin"));
const expected = JSON.parse(readFileSync(dir + "expected.json", "utf8")) as Record<string, number[][]>;
const byKey = new Map(index.tiles.map((e) => [tileKey(e[0], e[1]), e]));

async function zstdDecode(frame: Uint8Array): Promise<Uint8Array> {
  const Zstd = (await import("numcodecs/zstd")).default;
  return Zstd.fromConfig({ id: "zstd", level: 1 } as any).decode(frame);
}

describe("shape tiles written by the Python build", () => {
  it("decode to the same rings, closed, with each vertex tagged by its cell", async () => {
    const seen = new Set<number>();
    for (const e of index.tiles) {
      const raw = await zstdDecode(blob.subarray(e[2], e[2] + e[3]));
      const origin: [number, number] = [index.origin[0] + e[0] * index.tile, index.origin[1] + e[1] * index.tile];
      const t = decodeShapeTile(raw, origin, index.grid);
      expect(t.rows.length).toBe(e[4]);
      expect(t.startIndices[t.rows.length]).toBe(e[5] + e[4]); // one closing vertex per ring
      for (let r = 0; r < t.rows.length; r++) {
        const row = t.rows[r];
        seen.add(row);
        const want = expected[String(row)];
        const a = t.startIndices[r];
        const b = t.startIndices[r + 1];
        expect(b - a).toBe(want.length + 1);
        for (let k = 0; k < want.length; k++) {
          expect(t.positions[(a + k) * 2]).toBeCloseTo(want[k][0], 3);
          expect(t.positions[(a + k) * 2 + 1]).toBeCloseTo(want[k][1], 3);
        }
        expect([t.positions[(b - 1) * 2], t.positions[(b - 1) * 2 + 1]]).toEqual([t.positions[a * 2], t.positions[a * 2 + 1]]);
        for (let v = a; v < b; v++) expect(t.vertexRow[v]).toBe(row);
      }
      // triangles cover every ring and stay inside it: a 7-gon is 5 triangles
      expect(t.indices.length).toBe(e[4] * 5 * 3);
      for (const i of t.indices) expect(t.vertexRow[i]).toBeDefined();
    }
    expect(seen.size).toBe(Object.keys(expected).length);
  });

  it("picks the tiles a view needs, widened by the reach, and groups adjacent ones into few requests", () => {
    const tile = index.tile;
    const inner = tilesInRect(index, byKey, [tile + 10, tile + 10, tile + 20, tile + 20]);
    expect(inner.map((e) => tileKey(e[0], e[1]))).toEqual(["1_1"]);
    const edge = tilesInRect(index, byKey, [tile + 1, tile + 10, tile + 2, tile + 20]); // within reach of tile 0_1
    expect(edge.map((e) => tileKey(e[0], e[1])).sort()).toEqual(["0_1", "1_1"]);
    expect(tilesInRect(index, byKey, [-1e6, -1e6, 1e6, 1e6]).length).toBe(index.tiles.length);
    expect(tilesInRect(index, byKey, [1e6, 1e6, 2e6, 2e6])).toEqual([]);
    const runs = coalesce(index.tiles);
    expect(runs.length).toBe(1); // the whole fixture is one contiguous run under 1 MB
    const split = coalesce(index.tiles, 400);
    expect(split.flat().length).toBe(index.tiles.length);
    for (const run of split) expect(run[run.length - 1][2] + run[run.length - 1][3] - run[0][2]).toBeLessThanOrEqual(Math.max(400, run[0][3]));
    const gap: ShapeTileEntry[] = [index.tiles[0], index.tiles[2]]; // not adjacent in the file
    expect(coalesce(gap).length).toBe(2);
  });
});
