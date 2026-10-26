import { describe, expect, it } from "vitest";
import { arrange, countSignificant, fmtEffect, fmtP, groupValues, jitter, pairs, rows, ticks, type ComparisonData } from "../compare/model";

const data: ComparisonData = (() => {
  const genes = ["A", "B", "C", "D"];
  const results = { genes, effect: [1.5, -2, 0.2, 3], p: [0.001, 0.01, 0.5, null], padj: [0.004, 0.03, 0.9, null], mean: [5, 6, 1, 2], unmeasured: [3] };
  const replicates = [
    { id: "m1", group: "control", subject: "s1", samples: ["a"] },
    { id: "m2", group: "control", subject: "s2", samples: [] },
    { id: "m3", group: "stress", subject: "s1", samples: ["c"] },
    { id: "m4", group: "stress", subject: "s3", samples: ["d", "e"] },
  ];
  const pseudobulk = new Float32Array([1, 2, 3, 4, 1, 1, 1, 1, 0, 0, NaN, 0, 5, 5, 5, 5]);
  const level = { id: "all", name: "all", path: "levels/all", nGenes: 4, nSignificant: 2, nUnmatched: 1, nReplicates: 4, hasPseudobulk: true };
  const info = { id: "x", name: "x", path: "comparisons/x", groups: ["control", "stress"], levels: [level], nGenes: 4, nReplicates: 4, nUnmatched: 1, hasP: true, hasPadj: true, hasMean: true, hasPseudobulk: true, replicates: { all: replicates }, columns: {} };
  return { info, level, results, geneIndex: new Map(genes.map((g, i) => [g, i])), unmeasured: new Set([3]), replicates, pseudobulk };
})();

describe("compare model", () => {
  it("keeps a ranked list in its own order and hides direction and effect sorting", () => {
    const genes = ["Z", "Y", "X"];
    const list: ComparisonData = { ...data, results: { genes, effect: null, p: null, padj: null, mean: null, unmeasured: [] }, geneIndex: new Map(genes.map((g, i) => [g, i])), unmeasured: new Set(), replicates: [], pseudobulk: null };
    const all = rows(list);
    expect(all.map((r) => [r.gene, r.effect, r.pctIn])).toEqual([["Z", null, null], ["Y", null, null], ["X", null, null]]);
    expect(arrange(all, "padj", false, "all", "").map((r) => r.gene)).toEqual(["Z", "Y", "X"]); // nothing to sort by: the rank stays
    expect(arrange(all, "effect", true, "up", "").map((r) => r.gene)).toEqual([]); // a direction needs an effect
    expect(countSignificant(all)).toBe(0);
  });

  it("arranges rows by the asked key with missing values last, and filters by direction and text", () => {
    const all = rows(data);
    expect(all.map((r) => r.measured)).toEqual([true, true, true, false]);
    expect(arrange(all, "padj", false, "all", "").map((r) => r.gene)).toEqual(["A", "B", "C", "D"]);
    expect(arrange(all, "effect", true, "all", "").map((r) => r.gene)).toEqual(["D", "B", "A", "C"]); // by |effect|
    expect(arrange(all, "effect", true, "up", "").map((r) => r.gene)).toEqual(["D", "A", "C"]);
    expect(arrange(all, "padj", false, "down", "").map((r) => r.gene)).toEqual(["B"]);
    expect(arrange(all, "gene", false, "all", "c").map((r) => r.gene)).toEqual(["C"]);
    expect(countSignificant(all)).toBe(2);
  });

  it("formats numbers the way a table reads", () => {
    expect([fmtP(null), fmtP(0.5), fmtP(0.0123), fmtP(0.00032)]).toEqual(["—", "0.5", "0.012", "3.2e-4"]);
    expect([fmtEffect(1.234), fmtEffect(-12.3), fmtEffect(0)]).toEqual(["+1.23", "−12.3", "0.00"]);
    expect(ticks(0, 10)).toEqual([0, 2.5, 5, 7.5, 10]);
    expect(ticks(1.2, 1.2)).toEqual([1.2]);
  });

  it("arranges a gene's replicate values by group with quartiles, skipping missing values", () => {
    const g = groupValues(data, 0);
    expect(g.map((x) => [x.group, x.values.map((v) => v.value), x.median])).toEqual([
      ["control", [1, 2], 1.5],
      ["stress", [3, 4], 3.5],
    ]);
    const c = groupValues(data, 2);
    expect(c[1].values.map((v) => v.rep.id)).toEqual(["m4"]); // m3's value is NaN
    expect(c[0].q1).toBe(0);
    const p = pairs(g);
    expect(p).toEqual([{ subject: "s1", points: [{ group: "control", value: 1 }, { group: "stress", value: 3 }] }]);
  });

  it("jitters deterministically within [-1, 1]", () => {
    const a = jitter("m1");
    expect(a).toBe(jitter("m1"));
    expect(a).not.toBe(jitter("m2"));
    for (const id of ["m1", "m2", "donor Br2743", ""]) expect(Math.abs(jitter(id))).toBeLessThanOrEqual(1);
  });
});
