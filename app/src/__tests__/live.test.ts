/** Planning a test on drawn regions: sides, platforms, the rest's scope, sections without a row store. */
import { describe, expect, it } from "vitest";
import { planTest, type PlanSample } from "../compare/live";
import type { RegionGroup } from "../store/store";

const g = (id: string, name: string): RegionGroup => ({ id, name, color: "#000000", polygons: [{ id: "p", seq: 1, sample: "x", view: "spatial", local: [] }] });
const groups = [g("a", "Inner"), g("b", "Outer"), g("c", "Empty")];
// codes: 0 = Inner, 1 = Outer, 3 = none
const sample = (id: string, platform: string, codes: number[], chunk: number | null = 1024): PlanSample => ({ id, name: id, platform, embedding: false, codes: Uint16Array.from(codes), chunk, values: "log" });
const vis1 = sample("vis1", "visium", [0, 0, 0, 0, 1, 1, 1, 3, 3, 3]);
const vis2 = sample("vis2", "visium", [3, 3, 3, 3, 3, 3]);
const hd = sample("hd", "visium_hd", [0, 0, 0, 1, 1, 1, 3]);

describe("planTest", () => {
  it("tests two regions against each other per platform, naming the levels by platform", () => {
    const plan = planTest(groups, [vis1, vis2, hd], { mode: "pair", scope: "drawn", cap: 3000 });
    if ("problem" in plan) throw new Error(plan.problem);
    expect(plan.groups.map((x) => x.name)).toEqual(["Inner", "Outer"]); // the empty group is not a side
    expect(plan.levels.map((l) => l.name)).toEqual(["Visium", "Visium HD"]);
    const [v] = plan.levels;
    expect(v.req.a.map((p) => [p.sample, Array.from(p.rows)])).toEqual([["vis1", [0, 1, 2, 3]]]);
    expect(v.req.b.map((p) => [p.sample, Array.from(p.rows)])).toEqual([["vis1", [4, 5, 6]]]);
  });
  it("tests each region against the rest of the drawn sections, or of every section", () => {
    const drawn = planTest(groups, [vis1, vis2, hd], { mode: "rest", scope: "drawn", cap: 3000 });
    if ("problem" in drawn) throw new Error(drawn.problem);
    expect(drawn.levels.map((l) => l.name)).toEqual(["Inner · Visium", "Inner · Visium HD", "Outer · Visium", "Outer · Visium HD"]);
    expect(drawn.levels[0].req.b.map((p) => p.sample)).toEqual(["vis1"]); // vis2 has no region: not part of the rest
    expect(Array.from(drawn.levels[0].req.b[0].rows)).toEqual([4, 5, 6, 7, 8, 9]);
    const all = planTest(groups, [vis1, vis2, hd], { mode: "rest", scope: "all", cap: 3000 });
    if ("problem" in all) throw new Error(all.problem);
    expect(all.levels[0].req.b.map((p) => p.sample)).toEqual(["vis1", "vis2"]);
  });
  it("leaves out sections without a row store and says so, and refuses what cannot be tested", () => {
    const noRows = sample("old", "visium", [0, 0, 0, 1, 1, 1], null);
    const plan = planTest(groups, [vis1, noRows], { mode: "pair", scope: "drawn", cap: 3000 });
    if ("problem" in plan) throw new Error(plan.problem);
    expect(plan.skipped).toEqual(["old"]);
    expect(plan.levels).toHaveLength(1);
    expect(planTest(groups, [noRows], { mode: "pair", scope: "drawn", cap: 3000 })).toEqual({ problem: "no row store on old: the test needs one (expression.rows)" });
    expect(planTest(groups.slice(0, 1), [vis1], { mode: "pair", scope: "drawn", cap: 3000 })).toHaveProperty("problem");
    const tiny = sample("tiny", "visium", [0, 0, 1, 1]);
    expect(planTest(groups, [tiny], { mode: "pair", scope: "drawn", cap: 3000 })).toHaveProperty("problem"); // fewer than 3 cells a side
  });
});

describe("assemble", () => {
  it("builds a comparison and matrix the panel reads, keeping genes some level measures, and exports CSV", async () => {
    const { assemble } = await import("../compare/live");
    const { matrixCSV, matrixStats } = await import("../compare/model");
    const plan = planTest(groups, [vis1, hd], { mode: "pair", scope: "drawn", cap: 3000 });
    if ("problem" in plan) throw new Error(plan.problem);
    const genes = ["A", "B", "C"];
    const level = (id: string, measured: number[], effect: number[], p: number[], nSections: number) => ({
      id, nA: 4, nB: 3, perSample: [{ sample: "s", nA: 4, nB: 3 }], nSections,
      measured: Uint8Array.from(measured), effect: Float32Array.from(effect), p: Float32Array.from(p), padj: Float32Array.from(p.map((v) => v * 2)),
      pctIn: Float32Array.from([1, 0.5, NaN]), pctOut: Float32Array.from([0, 0.5, NaN]), auc: Float32Array.from([1, 0.5, NaN]), agree: Float32Array.from([1, 0, NaN]),
      cellsIn: Float32Array.from([4, 4, 0]), cellsOut: Float32Array.from([3, 3, 0]),
    });
    const results = [level("0:visium", [1, 1, 0], [2, 0, NaN], [0.001, 1, NaN], 1), level("0:visium_hd", [1, 0, 0], [1.5, NaN, NaN], [0.01, NaN, NaN], 1)];
    const { info, matrix } = assemble(plan, results, genes, "regions", { mode: "pair", scope: "drawn", cap: 3000 }, "ds");
    expect(info.live).toBe(true);
    expect(info.kind).toBe("contrast");
    expect(info.name).toBe("Inner vs Outer");
    expect(info.groups).toEqual(["Inner", "Outer"]);
    expect(info.levels.map((l) => [l.name, l.nGenes, l.nSignificant, l.nReplicates])).toEqual([["Visium", 2, 1, 1], ["Visium HD", 1, 1, 1]]); // one gene under padj 0.05 each
    expect(matrix.genes).toEqual(["A", "B"]); // C is measured nowhere
    expect(Array.from(matrix.stats.effect)).toEqual([2, 1.5, 0, NaN]);
    expect(matrixStats(matrix)).toEqual(["effect", "padj", "pct_in", "auc", "agree"]);
    expect(matrix.sections).toEqual([1, 1]);
    const csv = matrixCSV(matrix, info.levels.map((l) => l.name), "log2FC").split("\n");
    expect(csv[0]).toBe("gene,Visium log2FC,Visium p,Visium padj,Visium pct_in,Visium pct_out,Visium auc,Visium agree,Visium HD log2FC,Visium HD p,Visium HD padj,Visium HD pct_in,Visium HD pct_out,Visium HD auc,Visium HD agree");
    expect(csv[2].startsWith("B,0,1,2,0.5,0.5,0.5,0,,,,")).toBe(true); // blanks where the HD level has no value
    // each region against the rest: a markers table whose levels carry their region as population
    const rest = planTest(groups, [vis1], { mode: "rest", scope: "drawn", cap: 3000 });
    if ("problem" in rest) throw new Error(rest.problem);
    const r2 = assemble(rest, [level("0:visium", [1, 1, 1], [1, 1, 1], [0.1, 0.1, 0.1], 0), level("1:visium", [1, 1, 1], [1, 1, 1], [0.1, 0.1, 0.1], 0)], genes, "regions", { mode: "rest", scope: "drawn", cap: 3000 }, "ds");
    expect(r2.info.kind).toBe("markers");
    expect(r2.info.levels.map((l) => l.population)).toEqual([{ field: "regions", value: "Inner" }, { field: "regions", value: "Outer" }]);
    expect(r2.matrix.stats.agree).toBeUndefined(); // no section holds both sides
  });
});
