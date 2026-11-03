/**
 * Differential expression on single cells, computed in the browser from the per-cell row store: a two-sided
 * Wilcoxon rank-sum test per gene (tie-corrected normal approximation with continuity correction, as scipy's
 * asymptotic Mann-Whitney), the AUROC it implies, the log2 fold change of mean expression with a pseudocount of 1,
 * the fraction of cells expressing in each group, Benjamini-Hochberg over the genes tested, and how many sections
 * agree with the pooled direction.
 *
 * A gene is compared only among the cells of the sections that measured it: a section whose panel lacks the gene
 * contributes no cells to that gene's test, and a section that measured it and found no counts contributes zeros.
 * Means are taken on the expression scale the bundle records: values stored log-normalised (log1p) are
 * un-logged with expm1 first; raw values (intensities, `normalized: raw`) are averaged as they are.
 * Pure functions: the worker feeds them CSR blocks.
 */
import type { CellRows } from "./rows";

/** How a sample's values are stored: natural-log normalised (log1p; Seurat, scanpy, scran) or as they are. */
export type ValueScale = "log" | "raw";

/** The cells of one sample on one side of a contrast, as rows of the row store (bundle row indices). */
export interface DePart {
  sample: string;
  rows: Uint32Array;
  chunk: number; // the sample's row-store chunk (values per inner chunk)
  values: ValueScale;
}
export interface DeLevelRequest {
  id: string;
  a: DePart[];
  b: DePart[];
}
export interface DeRequest {
  token: number; // for cancelDe
  genes: string[]; // the features tested, in result order
  levels: DeLevelRequest[];
  cap: number; // cells per side; a larger side is subsampled by whole blocks of the row store
  minPct: number; // a gene is tested when at least this fraction of either side expresses it
}
export interface DeProgress {
  level: string;
  text: string;
}
export interface DeLevelResult {
  id: string;
  nA: number; // cells on each side, all sections
  nB: number;
  perSample: { sample: string; nA: number; nB: number }[]; // cells used after the cap
  nSections: number; // sections with at least MIN_CELLS cells on both sides: the denominator of `agree`
  measured: Uint8Array; // 1 where some section of the level carries the gene
  effect: Float32Array; // log2FC, NaN where not measured
  p: Float32Array; // NaN where not tested
  padj: Float32Array;
  pctIn: Float32Array;
  pctOut: Float32Array;
  auc: Float32Array;
  agree: Float32Array; // sections whose own log2FC has the pooled sign
  cellsIn: Float32Array; // cells of sections measuring the gene, per side: the denominators of pctIn / pctOut
  cellsOut: Float32Array;
}

export const MIN_CELLS = 3; // a side (or a section's side) with fewer cells is not tested
export const DEFAULT_CAP = 3000;
export const DEFAULT_MIN_PCT = 0.1;

/** A small seeded generator (mulberry32): the same drawing gives the same subsample every time. */
export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** At most `cap` cells across the parts, taken as whole blocks of the row store (cells sharing a chunk) in a
 *  seeded random order, the last block cut to the cap: as many whole chunks as the cap allows, so the download
 *  shrinks with the cap. `block[i]` is the chunk of `rows[i]`. Under the cap, everything is kept as it is. */
export function subsample(parts: { sample: string; rows: Uint32Array; block: Uint32Array }[], cap: number, seed = 42): { sample: string; rows: Uint32Array }[] {
  const total = parts.reduce((n, p) => n + p.rows.length, 0);
  if (total <= cap) return parts.map((p) => ({ sample: p.sample, rows: p.rows }));
  const buckets: { part: number; rows: number[] }[] = [];
  parts.forEach((p, k) => {
    const by = new Map<number, number[]>();
    for (let i = 0; i < p.rows.length; i++) {
      const b = p.block[i];
      let list = by.get(b);
      if (!list) by.set(b, (list = []));
      list.push(p.rows[i]);
    }
    for (const rows of by.values()) buckets.push({ part: k, rows });
  });
  const rand = rng(seed);
  for (let i = buckets.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [buckets[i], buckets[j]] = [buckets[j], buckets[i]];
  }
  const chosen: number[][] = parts.map(() => []);
  let left = cap;
  for (const b of buckets) {
    if (left <= 0) break;
    const take = Math.min(left, b.rows.length);
    for (let i = 0; i < take; i++) chosen[b.part].push(b.rows[i]);
    left -= take;
  }
  return parts.map((p, k) => ({ sample: p.sample, rows: Uint32Array.from(chosen[k]) })).filter((p) => p.rows.length);
}

/** Complementary error function (Numerical Recipes erfcc, relative error under 1.2e-7 everywhere). */
export function erfc(x: number): number {
  const z = Math.abs(x);
  const t = 1 / (1 + 0.5 * z);
  const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 + t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 + t * (-0.82215223 + t * 0.17087277)))))))));
  return x >= 0 ? r : 2 - r;
}
/** P(Z > z) for a standard normal. */
export const normalSf = (z: number): number => 0.5 * erfc(z / Math.SQRT2);

/** Benjamini-Hochberg adjusted p-values; NaN entries are left out of the family and stay NaN. */
export function benjaminiHochberg(p: Float32Array): Float32Array {
  const idx: number[] = [];
  for (let i = 0; i < p.length; i++) if (!Number.isNaN(p[i])) idx.push(i);
  idx.sort((i, j) => p[i] - p[j]);
  const out = new Float32Array(p.length).fill(NaN);
  const m = idx.length;
  let running = 1;
  for (let k = m - 1; k >= 0; k--) {
    running = Math.min(running, (p[idx[k]] * m) / (k + 1));
    out[idx[k]] = running;
  }
  return out;
}

/** A Wilcoxon rank-sum test of two samples of which only the nonzero values are listed (`a`, `b`, sorted in place),
 *  the rest being `nA - a.length` and `nB - b.length` zeros: returns the one-sided rank statistic's AUROC and the
 *  two-sided p (tie-corrected, continuity-corrected normal approximation; 1 when every value ties). */
export function rankSum(a: Float32Array, b: Float32Array, nA: number, nB: number): { auc: number; p: number } {
  a.sort();
  b.sort();
  const cA = a.length;
  const cB = b.length;
  const nZero = nA - cA + (nB - cB);
  let tie = nZero > 1 ? nZero * nZero * nZero - nZero : 0;
  let rankA = (nA - cA) * ((nZero + 1) / 2);
  let i = 0;
  let j = 0;
  let r = nZero;
  while (i < cA || j < cB) {
    const v = j >= cB || (i < cA && a[i] <= b[j]) ? a[i] : b[j];
    let tA = 0;
    let tB = 0;
    while (i < cA && a[i] === v) {
      i++;
      tA++;
    }
    while (j < cB && b[j] === v) {
      j++;
      tB++;
    }
    const t = tA + tB;
    rankA += tA * (r + (t + 1) / 2);
    r += t;
    if (t > 1) tie += t * t * t - t;
  }
  const U = rankA - (nA * (nA + 1)) / 2;
  const N = nA + nB;
  const auc = U / (nA * nB);
  const variance = ((nA * nB) / 12) * (N + 1 - tie / (N * (N - 1)));
  if (!(variance > 0)) return { auc, p: 1 };
  let z = U - (nA * nB) / 2;
  z -= Math.sign(z) * 0.5;
  z /= Math.sqrt(variance);
  return { auc, p: Math.min(1, 2 * normalSf(Math.abs(z))) };
}

/** One side's cells of one sample, decoded: the rows' values in the level's gene space. */
export interface DeBlock {
  sample: string;
  side: 0 | 1; // 0 = a, 1 = b
  rows: CellRows;
  geneMap: Int32Array; // the sample's gene index -> index in the request's genes, -1 to skip
  scale: Float32Array; // per sample gene: gmax / 255 (a code times it is the value)
  zeroGenes: Int32Array; // request genes the sample measured and found zero everywhere (not in its stored panel)
}

/** The test of one level from its decoded blocks. `values` is the scale every block's sample stores. */
export function testLevel(id: string, blocks: DeBlock[], nGenes: number, minPct: number, values: ValueScale = "log"): DeLevelResult {
  const sections = [...new Set(blocks.map((b) => b.sample))];
  const secOf = new Map(sections.map((s, k) => [s, k]));
  const nSec = sections.length;
  const nCells = new Float64Array(nSec * 2); // per section and side
  const measuredSec = new Uint8Array(nGenes * nSec); // 1 where the section's panel has the gene (stored or all zero)
  const sumF = new Float64Array(nGenes * nSec * 2); // per gene, section, side: sum of the un-logged (or raw) values
  const cnt = new Uint32Array(nGenes * 2); // nonzero cells per gene and side
  let nA = 0;
  let nB = 0;
  const unlog = values === "log" ? Math.expm1 : (v: number) => v;
  for (const bl of blocks) {
    const n = bl.rows.indptr.length - 1;
    const sec = secOf.get(bl.sample)!;
    nCells[sec * 2 + bl.side] += n;
    if (bl.side === 0) nA += n;
    else nB += n;
    for (let g = 0; g < bl.geneMap.length; g++) if (bl.geneMap[g] >= 0) measuredSec[bl.geneMap[g] * nSec + sec] = 1;
    for (let k = 0; k < bl.zeroGenes.length; k++) measuredSec[bl.zeroGenes[k] * nSec + sec] = 1;
    const gene = bl.rows.gene;
    for (let k = 0; k < gene.length; k++) {
      const gi = bl.geneMap[gene[k]];
      if (gi >= 0) cnt[gi * 2 + bl.side]++;
    }
  }
  // per gene and side, the cells of the sections that measured it: the test's n and the fraction's denominator
  const measured = new Uint8Array(nGenes);
  const cellsIn = new Float32Array(nGenes);
  const cellsOut = new Float32Array(nGenes);
  for (let g = 0; g < nGenes; g++) {
    for (let s = 0; s < nSec; s++) {
      if (!measuredSec[g * nSec + s]) continue;
      measured[g] = 1;
      cellsIn[g] += nCells[s * 2];
      cellsOut[g] += nCells[s * 2 + 1];
    }
  }
  // lay the nonzero values out per gene: a's then b's
  const off = new Uint32Array(nGenes * 2 + 1);
  for (let g = 0; g < nGenes; g++) {
    off[g * 2 + 1] = off[g * 2] + cnt[g * 2];
    off[g * 2 + 2] = off[g * 2 + 1] + cnt[g * 2 + 1];
  }
  const vals = new Float32Array(off[nGenes * 2]);
  const cursor = Uint32Array.from(off.subarray(0, nGenes * 2));
  for (const bl of blocks) {
    const sec = secOf.get(bl.sample)!;
    const { indptr, gene, value } = bl.rows;
    const n = indptr.length - 1;
    for (let i = 0; i < n; i++) {
      for (let k = indptr[i]; k < indptr[i + 1]; k++) {
        const gi = bl.geneMap[gene[k]];
        if (gi < 0) continue;
        const v = value[k] * bl.scale[gene[k]];
        vals[cursor[gi * 2 + bl.side]++] = v;
        sumF[(gi * nSec + sec) * 2 + bl.side] += unlog(v);
      }
    }
  }
  const effect = new Float32Array(nGenes).fill(NaN);
  const p = new Float32Array(nGenes).fill(NaN);
  const pctIn = new Float32Array(nGenes).fill(NaN);
  const pctOut = new Float32Array(nGenes).fill(NaN);
  const auc = new Float32Array(nGenes).fill(NaN);
  const agree = new Float32Array(nGenes).fill(NaN);
  const secBoth: number[] = [];
  for (let s = 0; s < nSec; s++) if (nCells[s * 2] >= MIN_CELLS && nCells[s * 2 + 1] >= MIN_CELLS) secBoth.push(s);
  const lfc = (sa: number, na: number, sb: number, nb: number) => Math.log2((sa / na + 1) / (sb / nb + 1));
  for (let g = 0; g < nGenes; g++) {
    if (!measured[g]) continue;
    const cA = cnt[g * 2];
    const cB = cnt[g * 2 + 1];
    const na = cellsIn[g];
    const nb = cellsOut[g];
    pctIn[g] = na ? cA / na : NaN;
    pctOut[g] = nb ? cB / nb : NaN;
    if (!na || !nb) continue; // one side has no section measuring the gene: no comparison
    let sA = 0;
    let sB = 0;
    for (let s = 0; s < nSec; s++) {
      sA += sumF[(g * nSec + s) * 2];
      sB += sumF[(g * nSec + s) * 2 + 1];
    }
    const e = lfc(sA, na, sB, nb);
    effect[g] = e;
    const own = secBoth.filter((s) => measuredSec[g * nSec + s]);
    if (own.length) {
      let k = 0;
      for (const s of own) {
        const es = lfc(sumF[(g * nSec + s) * 2], nCells[s * 2], sumF[(g * nSec + s) * 2 + 1], nCells[s * 2 + 1]);
        if (es !== 0 && Math.sign(es) === Math.sign(e)) k++;
      }
      agree[g] = k;
    }
    if (na < MIN_CELLS || nb < MIN_CELLS || Math.max(pctIn[g], pctOut[g]) < minPct) continue;
    const r = rankSum(vals.subarray(off[g * 2], off[g * 2 + 1]), vals.subarray(off[g * 2 + 1], off[g * 2 + 2]), na, nb);
    auc[g] = r.auc;
    p[g] = r.p;
  }
  const perSample = sections.map((sample, s) => ({ sample, nA: nCells[s * 2], nB: nCells[s * 2 + 1] }));
  return { id, nA, nB, perSample, nSections: secBoth.length, measured, effect, p, padj: benjaminiHochberg(p), pctIn, pctOut, auc, agree, cellsIn, cellsOut };
}
