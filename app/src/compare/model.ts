/**
 * Pure helpers for the Compare panel: the rows of a results table in the order and selection the header asks
 * for, the replicate values of one gene arranged by group, box statistics, pairing and formatting. Nothing here
 * computes a statistic the table did not already hold: values are drawn as imported.
 */
import type { ComparisonInfo, LevelInfo, Manifest } from "../data/manifest";
import { fieldById } from "../data/manifest";
import { REGION_COLORS } from "../store/store";

export interface ResultsDoc {
  genes: string[];
  effect: number[] | null; // null for a ranked list without statistics
  p: (number | null)[] | null;
  padj: (number | null)[] | null;
  mean: (number | null)[] | null;
  pct_in?: (number | null)[] | null;
  pct_out?: (number | null)[] | null;
  score?: (number | null)[] | null;
  unmeasured: number[];
}
export interface Replicate {
  id: string;
  group: string;
  subject: string;
  samples: string[];
}
export interface ComparisonDoc extends ComparisonInfo {
  replicates: Record<string, Replicate[]>; // per level id
  columns: Record<string, string>;
  sources?: Record<string, string>;
}
/** One level of a comparison, loaded: its table, and its replicate values when it has them. */
export interface ComparisonData {
  info: ComparisonDoc;
  level: LevelInfo;
  results: ResultsDoc;
  geneIndex: Map<string, number>; // gene -> row in the results
  unmeasured: Set<number>;
  replicates: Replicate[];
  pseudobulk: Float32Array | null; // row-major (nGenes, nReplicates), replicate order = replicates
}

/** genes x levels of one statistic each: the table that shows every cluster or level at once. */
export interface MatrixData {
  info: ComparisonInfo;
  genes: string[];
  levels: string[]; // level ids, column order
  stats: Record<string, Float32Array>; // row-major (genes, levels); NaN where a level's table has no row for the gene
  unmeasured: Set<number>;
  geneIndex: Map<string, number>;
}
export interface MatrixRow {
  i: number;
  gene: string;
  measured: boolean;
}
/** The statistic the matrix is read by: the effect when the tables have one, else the rank in each level. */
export const matrixStat = (m: MatrixData): "effect" | "rank" => (m.stats.effect ? "effect" : "rank");

export function matrixRows(m: MatrixData): MatrixRow[] {
  return m.genes.map((gene, i) => ({ i, gene, measured: !m.unmeasured.has(i) }));
}

/** Rows ordered by one level's statistic (a missing value sorts last), narrowed by a search. */
export function arrangeMatrix(m: MatrixData, rows: MatrixRow[], stat: string, level: number, descending: boolean, query: string): MatrixRow[] {
  const q = query.trim().toLowerCase();
  const out = q ? rows.filter((r) => r.gene.toLowerCase().includes(q)) : rows;
  const a = m.stats[stat];
  const k = m.levels.length;
  if (!a || level < 0 || level >= k) return out;
  const sign = descending ? -1 : 1;
  return [...out].sort((x, y) => {
    const vx = a[x.i * k + level];
    const vy = a[y.i * k + level];
    const nx = Number.isNaN(vx);
    const ny = Number.isNaN(vy);
    if (nx && ny) return x.i - y.i;
    if (nx) return 1;
    if (ny) return -1;
    if (vx === vy) return x.i - y.i;
    return vx < vy ? -sign : sign;
  });
}

/** What a cell holds besides the number shown: padj, % in / out, rank. */
export function cellDetail(m: MatrixData, i: number, j: number): string {
  const k = m.levels.length;
  const at = (name: string) => m.stats[name]?.[i * k + j];
  const parts: string[] = [];
  const eff = at("effect");
  if (eff != null && !Number.isNaN(eff)) parts.push(`effect ${fmtEffect(eff)}`);
  const padj = at("padj");
  if (padj != null && !Number.isNaN(padj)) parts.push(`padj ${fmtP(padj)}`);
  else {
    const p = at("p");
    if (p != null && !Number.isNaN(p)) parts.push(`p ${fmtP(p)}`);
  }
  const pin = at("pct_in");
  const pout = at("pct_out");
  if ((pin != null && !Number.isNaN(pin)) || (pout != null && !Number.isNaN(pout))) parts.push(`in ${fmtPct(pin ?? null)}% / out ${fmtPct(pout ?? null)}%`);
  const rank = at("rank");
  if (rank != null && !Number.isNaN(rank)) parts.push(`rank ${rank}`);
  return parts.join(" · ");
}

export type SortKey = "padj" | "effect" | "mean" | "pct" | "gene";
export type Direction = "all" | "up" | "down";

export interface Row {
  i: number; // index in the results: the table's rank
  gene: string;
  effect: number | null;
  p: number | null;
  padj: number | null;
  mean: number | null;
  pctIn: number | null;
  pctOut: number | null;
  measured: boolean;
}

export function rows(data: ComparisonData): Row[] {
  const r = data.results;
  return r.genes.map((gene, i) => ({
    i,
    gene,
    effect: r.effect ? r.effect[i] : null,
    p: r.p ? r.p[i] : null,
    padj: r.padj ? r.padj[i] : null,
    mean: r.mean ? r.mean[i] : null,
    pctIn: r.pct_in ? r.pct_in[i] : null,
    pctOut: r.pct_out ? r.pct_out[i] : null,
    measured: !data.unmeasured.has(i),
  }));
}

/** The table's rows after the search box, the direction filter and the sort. Missing values sort last. */
export function arrange(all: Row[], sort: SortKey, descending: boolean, dir: Direction, query: string): Row[] {
  const q = query.trim().toLowerCase();
  let out = all;
  if (q) out = out.filter((r) => r.gene.toLowerCase().includes(q));
  if (dir === "up") out = out.filter((r) => r.effect != null && r.effect > 0);
  else if (dir === "down") out = out.filter((r) => r.effect != null && r.effect < 0);
  const key = (r: Row): number | string | null => (sort === "gene" ? r.gene : sort === "effect" ? (r.effect == null ? null : Math.abs(r.effect)) : sort === "mean" ? r.mean : sort === "pct" ? r.pctIn : (r.padj ?? r.p));
  const sign = descending ? -1 : 1;
  return [...out].sort((a, b) => {
    const ka = key(a);
    const kb = key(b);
    if (ka == null && kb == null) return a.i - b.i;
    if (ka == null) return 1;
    if (kb == null) return -1;
    if (ka < kb) return -sign; // ascending puts the smaller key first
    if (ka > kb) return sign;
    return a.i - b.i;
  });
}

export function countSignificant(all: Row[], alpha = 0.05): number {
  return all.reduce((n, r) => n + ((r.padj ?? r.p ?? 1) < alpha ? 1 : 0), 0);
}

export function fmtP(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v === 0) return "0";
  if (v < 1e-3) return v.toExponential(1).replace("e-", "e-").replace(".0e", "e");
  return v.toFixed(3).replace(/0+$/, "").replace(/\.$/, "");
}

export function fmtEffect(v: number): string {
  const a = Math.abs(v);
  const s = a >= 100 ? a.toFixed(0) : a >= 10 ? a.toFixed(1) : a.toFixed(2);
  return (v < 0 ? "−" : v > 0 ? "+" : "") + s;
}

export function fmtMean(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2);
}

/** A deterministic horizontal jitter in [-1, 1] from a replicate id, so dots never move between genes. */
export function jitter(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 2001) / 1000 - 1;
}

export interface GroupValues {
  group: string;
  values: { rep: Replicate; value: number }[];
  median: number | null;
  q1: number | null;
  q3: number | null;
  min: number | null;
  max: number | null;
}

function quantile(sorted: number[], q: number): number {
  if (!sorted.length) return NaN;
  const pos = (sorted.length - 1) * q;
  const lo = Math.floor(pos);
  const hi = Math.ceil(pos);
  return sorted[lo] + (sorted[hi] - sorted[lo]) * (pos - lo);
}

/** The gene's replicate values per group, in the comparison's group order; replicates with no value are left out. */
export function groupValues(data: ComparisonData, geneRow: number): GroupValues[] {
  const { info, pseudobulk, replicates } = data;
  const n = replicates.length;
  return info.groups.map((group) => {
    const values: { rep: Replicate; value: number }[] = [];
    if (pseudobulk) {
      replicates.forEach((rep, j) => {
        const v = pseudobulk[geneRow * n + j];
        if (rep.group === group && Number.isFinite(v)) values.push({ rep, value: v });
      });
    }
    const sorted = values.map((x) => x.value).sort((a, b) => a - b);
    const has = sorted.length > 0;
    return { group, values, median: has ? quantile(sorted, 0.5) : null, q1: has ? quantile(sorted, 0.25) : null, q3: has ? quantile(sorted, 0.75) : null, min: has ? sorted[0] : null, max: has ? sorted[sorted.length - 1] : null };
  });
}

/** Subjects that appear in more than one group: their dots are joined by a line (a paired design). */
export function pairs(groups: GroupValues[]): { subject: string; points: { group: string; value: number }[] }[] {
  const by = new Map<string, { group: string; value: number }[]>();
  for (const g of groups) for (const { rep, value } of g.values) by.set(rep.subject, [...(by.get(rep.subject) ?? []), { group: g.group, value }]);
  return [...by.entries()].filter(([, pts]) => pts.length > 1).map(([subject, points]) => ({ subject, points }));
}

/** Round axis ticks: at most `n` of them spanning [lo, hi]. */
export function ticks(lo: number, hi: number, n = 4): number[] {
  if (!(hi > lo)) return [lo];
  const raw = (hi - lo) / n;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => (hi - lo) / s <= n) ?? raw;
  const out: number[] = [];
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(10));
  return out;
}

/** One colour per group: the split key's annotation colours when it is also a categorical field with these
 *  categories, else a fixed palette in group order. */
export function groupColors(m: Manifest, info: ComparisonInfo): string[] {
  const f = info.split ? fieldById(m, info.split) : undefined;
  if (f && f.type === "categorical") {
    const v = m.vocabularies[f.vocabulary];
    if (info.groups.every((g) => v.categories.includes(g))) return info.groups.map((g) => v.colors[v.categories.indexOf(g)]);
  }
  return info.groups.map((_, i) => REGION_COLORS[i % REGION_COLORS.length]);
}

export function fmtPct(v: number | null): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const pct = v <= 1 ? v * 100 : v; // Seurat writes fractions, presto percentages
  return pct >= 10 ? pct.toFixed(0) : pct.toFixed(1);
}

/** The level a comparison shows: the one asked for, else its first. */
export function levelOf(info: ComparisonInfo, id: string | null | undefined): LevelInfo | null {
  return info.levels.find((l) => l.id === id) ?? info.levels[0] ?? null;
}

/** The population a level stands for: its own (a facet level that is a category), else the comparison's. */
export function levelPopulation(info: ComparisonInfo, level: LevelInfo | null): { field: string; value: string } | null {
  return level?.population ?? info.population ?? null;
}
