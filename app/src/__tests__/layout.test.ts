import { describe, expect, it } from "vitest";
import { computeLayout, fitBbox } from "../views/layout";
import { drawCount, intersects } from "../views/lod";
import type { Sample } from "../data/manifest";

const mk = (id: string, w: number, h: number): Sample => ({
  id,
  name: id,
  platform: "xenium",
  kind: "spatial",
  nObs: 1000,
  nGenes: 10,
  bbox: [0, 0, w, h],
  toDataset: [1, 0, 0, 0, 1, 0, 0, 0, 1],
  pointRadius: 5,
  expr: { kind: "u8", sharded: true, shardGenes: 512 },
  hasF16: false,
  fields: [],
  images: [],
  idBlock: 65536,
});

describe("computeLayout", () => {
  it("places samples in non-overlapping cells and preserves order", () => {
    const samples = [mk("a", 100, 50), mk("b", 80, 80), mk("c", 40, 40)];
    const L = computeLayout(samples, ["c", "a", "b"], "grid", 0.1, 1.5);
    expect([...L.placements.keys()]).toEqual(["c", "a", "b"]);
    const boxes = [...L.placements.values()].map((p) => p.worldBbox);
    for (let i = 0; i < boxes.length; i++)
      for (let j = i + 1; j < boxes.length; j++) expect(intersects(boxes[i], boxes[j])).toBe(false);
    // each sample's bbox transformed by its model matrix equals its world bbox
    for (const p of L.placements.values()) {
      const s = samples.find((x) => x.id === p.sampleId)!;
      const [x0, y0] = p.modelMatrix.transformAsPoint([s.bbox[0], s.bbox[1], 0]);
      expect(x0).toBeCloseTo(p.worldBbox[0], 6);
      expect(y0).toBeCloseTo(p.worldBbox[1], 6);
    }
  });
  it("strip mode is a single row; hidden samples are dropped", () => {
    const samples = [mk("a", 10, 10), mk("b", 10, 10), mk("c", 10, 10)];
    const L = computeLayout(samples, ["a", "b", "c"], "strip", 0.1, 1, new Set(["b"]));
    expect(L.nrows).toBe(1);
    expect(L.ncols).toBe(2);
    expect(L.placements.has("b")).toBe(false);
  });
  it("applies toDataset affines", () => {
    const s = mk("a", 100, 50);
    s.toDataset = [0, -1, 50, 1, 0, 0, 0, 0, 1]; // rotate 90
    const L = computeLayout([s], ["a"], "grid", 0, 1);
    const p = L.placements.get("a")!;
    expect(p.worldBbox[2] - p.worldBbox[0]).toBeCloseTo(50);
    expect(p.worldBbox[3] - p.worldBbox[1]).toBeCloseTo(100);
  });
});

describe("fitBbox / drawCount", () => {
  it("fits a bbox into the viewport", () => {
    const v = fitBbox([0, 0, 1000, 500], 800, 600, 0);
    expect(v.target).toEqual([500, 250, 0]);
    expect(Math.pow(2, v.zoom)).toBeCloseTo(0.8);
  });
  it("draws fewer points when the sample is small on screen", () => {
    const full = drawCount(1_000_000, [0, 0, 1000, 1000], 0, [1000, 1000]);
    const small = drawCount(1_000_000, [0, 0, 1000, 1000], -5, [1000, 1000]);
    expect(full).toBe(600_000);
    expect(small).toBeLessThan(full);
    expect(small).toBeGreaterThanOrEqual(3000);
  });
});

describe("image footprints", () => {
  it("grow the cell so H&E frames do not touch across the gutter", async () => {
    const { footprint } = await import("../views/layout");
    const s: any = { id: "a", bbox: [0, 0, 6500, 6500], toDataset: [1, 0, 0, 0, 1, 0], images: [{ pixelSize: 4.4, translate: [-1100, -1100], size: [2000, 2000] }] };
    expect(footprint(s)).toEqual([-1100, -1100, 7700, 7700]);
    const L = computeLayout([s, { ...s, id: "b" }], ["a", "b"], "strip", 0.2, 1);
    expect(L.cell[0]).toBeCloseTo(8800 * 1.2);
  });
});
