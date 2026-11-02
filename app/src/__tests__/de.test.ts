/** Differential expression on single cells: the rank-sum test against scipy's asymptotic Mann-Whitney (tie and
 *  continuity corrected, two-sided), BH, the block subsample, and a level test over CSR blocks. */
import { describe, expect, it } from "vitest";
import { benjaminiHochberg, rankSum, subsample, testLevel, type DeBlock } from "../data/de";
import type { CellRows } from "../data/rows";

const nonzero = (xs: number[]) => Float32Array.from(xs.filter((x) => x !== 0));

describe("rank-sum", () => {
  it("matches scipy with ties among the zeros and among the values", () => {
    const a = [0, 0, 0, 1.2, 1.2, 2.5, 3.1, 0.7, 0, 4.0];
    const b = [0, 0, 0, 0, 0, 0.7, 1.2, 0, 0, 0, 0.3, 0];
    const r = rankSum(nonzero(a), nonzero(b), a.length, b.length);
    expect(r.auc).toBeCloseTo(87.5 / 120, 6); // U = 87.5
    expect(r.p).toBeCloseTo(0.04539833295321023, 6);
  });
  it("matches scipy without ties among the values", () => {
    const a = [0, 0, 1.5, 2.5, 3.5];
    const b = [0, 0, 0, 0.5, 1.0, 2.0];
    const r = rankSum(nonzero(a), nonzero(b), a.length, b.length);
    expect(r.auc).toBeCloseTo(20 / 30, 6);
    expect(r.p).toBeCloseTo(0.38886121403562657, 6);
  });
  it("is 1 when every cell ties, and tiny when the groups separate", () => {
    expect(rankSum(new Float32Array(0), new Float32Array(0), 10, 10).p).toBe(1);
    const a = Float32Array.from({ length: 500 }, (_, i) => 1 + i / 500);
    const r = rankSum(a, new Float32Array(0), 500, 500);
    expect(r.auc).toBe(1);
    expect(r.p).toBeLessThan(1e-100);
    expect(r.p).toBeGreaterThan(0);
  });
});

describe("Benjamini-Hochberg", () => {
  it("matches scipy and leaves untested genes out of the family", () => {
    const q = benjaminiHochberg(Float32Array.from([0.01, NaN, 0.04, 0.03, 0.5, 0.2]));
    expect(Number.isNaN(q[1])).toBe(true);
    expect(Array.from(q).filter((v) => !Number.isNaN(v)).map((v) => +v.toFixed(6))).toEqual([0.05, 0.066667, 0.066667, 0.5, 0.25]);
  });
});

describe("block subsample", () => {
  it("keeps everything under the cap, else whole blocks in a seeded order up to the cap", () => {
    const rows = Uint32Array.from({ length: 100 }, (_, i) => i);
    const block = Uint32Array.from({ length: 100 }, (_, i) => Math.floor(i / 10)); // ten blocks of ten
    const small = subsample([{ sample: "s", rows, block }], 200);
    expect(small[0].rows).toBe(rows);
    const cut = subsample([{ sample: "s", rows, block }], 35);
    expect(cut[0].rows.length).toBe(35);
    const blocks = new Set(Array.from(cut[0].rows).map((r) => Math.floor(r / 10)));
    expect(blocks.size).toBe(4); // three whole blocks and five cells of a fourth
    expect(Array.from(subsample([{ sample: "s", rows, block }], 35)[0].rows)).toEqual(Array.from(cut[0].rows)); // seeded
    const two = subsample(
      [
        { sample: "x", rows, block },
        { sample: "y", rows, block },
      ],
      50,
    );
    expect(two.reduce((n, p) => n + p.rows.length, 0)).toBe(50);
  });
});

/** CSR rows from a dense matrix of codes. */
function csr(dense: number[][]): CellRows {
  const indptr = new Uint32Array(dense.length + 1);
  const gene: number[] = [];
  const value: number[] = [];
  dense.forEach((row, i) => {
    row.forEach((v, g) => {
      if (v) {
        gene.push(g);
        value.push(v);
      }
    });
    indptr[i + 1] = gene.length;
  });
  return { indptr, gene: Uint32Array.from(gene), value: Uint8Array.from(value) };
}

describe("level test", () => {
  it("tests the genes expressed enough, reports fold change, fractions and section agreement", () => {
    // two sections; gene 0 up in a, gene 1 flat, gene 2 below the min fraction; the sample's gene 3 is not a tested feature
    const scale = Float32Array.from([1 / 255, 1 / 255, 1 / 255, 1 / 255]);
    const geneMap = Int32Array.from([0, 1, 2, -1]);
    const aRows = (seed: number) => Array.from({ length: 6 }, (_, i) => [200 + ((i * 7 + seed) % 50), 100, i === 0 && seed === 1 ? 50 : 0, 9]);
    const bRows = () => Array.from({ length: 6 }, () => [0, 100, 0, 9]);
    const blocks: DeBlock[] = [
      { sample: "s1", side: 0, rows: csr(aRows(1)), geneMap, scale },
      { sample: "s1", side: 1, rows: csr(bRows()), geneMap, scale },
      { sample: "s2", side: 0, rows: csr(aRows(3)), geneMap, scale },
      { sample: "s2", side: 1, rows: csr(bRows()), geneMap, scale },
    ];
    const r = testLevel("L", blocks, 4, 0.1);
    expect([r.nA, r.nB, r.nSections]).toEqual([12, 12, 2]);
    expect(Array.from(r.measured)).toEqual([1, 1, 1, 0]);
    expect(r.pctIn[0]).toBe(1);
    expect(r.pctOut[0]).toBe(0);
    expect(r.effect[0]).toBeGreaterThan(0.5);
    expect(r.auc[0]).toBe(1);
    expect(r.p[0]).toBeLessThan(0.001);
    expect(r.agree[0]).toBe(2);
    expect(r.effect[1]).toBe(0); // the same value everywhere
    expect(r.p[1]).toBe(1);
    expect(Number.isNaN(r.p[2])).toBe(true); // 1 of 12 cells: under the min fraction, so not tested
    expect(r.pctIn[2]).toBeCloseTo(1 / 12, 6);
    expect(Number.isNaN(r.effect[3])).toBe(true);
    expect(r.padj[0]).toBeLessThan(0.01);
    expect(r.perSample.map((x) => [x.sample, x.nA, x.nB])).toEqual([
      ["s1", 6, 6],
      ["s2", 6, 6],
    ]);
  });
});
