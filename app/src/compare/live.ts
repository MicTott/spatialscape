/**
 * A differential expression test on the drawn regions, run in the viewer: the cells of each group are taken from
 * the per-cell row store, platform by platform (a Visium spot and a Xenium cell are never pooled), tested in the
 * worker (data/de.ts), and the result opens in the Compare panel as a comparison held in memory. Two groups are
 * tested against each other; otherwise each group against the rest of the drawn sections, or of every section.
 */
import * as Comlink from "comlink";
import { MIN_CELLS, type DeLevelRequest, type DeLevelResult, type DePart, type DeProgress, type ValueScale } from "../data/de";
import { platformLabel, type ComparisonInfo, type LevelInfo } from "../data/manifest";
import { store, type RegionGroup } from "../store/store";
import type { ViewerController } from "../views/ViewerController";
import { registerMatrix } from "./data";
import type { MatrixData } from "./model";
import { activateComparison } from "./activate";

export const LIVE_ID = "regions-test";
export type TestMode = "pair" | "rest";
export type RestScope = "drawn" | "all";
export interface TestOptions {
  mode: TestMode;
  scope: RestScope;
  cap: number;
}

/** What the planner needs to know about a loaded sample. */
export interface PlanSample {
  id: string;
  name: string;
  platform: string;
  embedding: boolean;
  codes: Uint16Array | null; // the regions field: group index per cell, groups.length for none
  chunk: number | null; // the row store's chunk, null without one
  values: ValueScale; // how the sample stores expression: log-normalised, or raw values kept as they are
}
export interface PlannedLevel {
  req: DeLevelRequest;
  name: string;
  group: string | null; // the region a "vs rest" level is about
  platform: string;
}
export interface TestPlan {
  levels: PlannedLevel[];
  groups: RegionGroup[]; // the groups with cells, in order
  skipped: string[]; // sections touched by a region but without a row store
}

/** The levels of a test: one per contrast and platform with at least MIN_CELLS cells on each side. */
export function planTest(groups: RegionGroup[], samples: PlanSample[], opts: TestOptions): TestPlan | { problem: string } {
  const n = groups.length;
  const used = groups.map((_, gi) => samples.some((s) => s.codes?.some((c) => c === gi)));
  const live = groups.filter((_, gi) => used[gi]);
  if (opts.mode === "pair" && live.length !== 2) return { problem: "two regions with cells are needed to test one against the other" };
  if (!live.length) return { problem: "draw a region first" };
  const cells = new Map<string, Map<number, number[]>>(); // sample -> code -> rows
  const skipped: string[] = [];
  const touched = new Set<string>();
  for (const s of samples) {
    if (s.embedding || !s.codes) continue;
    const by = new Map<number, number[]>();
    for (let i = 0; i < s.codes.length; i++) {
      const c = s.codes[i];
      let list = by.get(c);
      if (!list) by.set(c, (list = []));
      list.push(i);
    }
    const drawnOn = [...by.keys()].some((c) => c < n);
    if (drawnOn) touched.add(s.id);
    if (s.chunk == null) {
      if (drawnOn) skipped.push(s.name);
      continue;
    }
    cells.set(s.id, by);
  }
  const code = (g: RegionGroup) => groups.indexOf(g);
  const part = (s: PlanSample, pick: (c: number) => boolean): DePart | null => {
    const by = cells.get(s.id);
    if (!by) return null;
    const rows: number[] = [];
    for (const [c, list] of by) if (pick(c)) for (const i of list) rows.push(i);
    return rows.length ? { sample: s.id, rows: Uint32Array.from(rows), chunk: s.chunk!, values: s.values } : null;
  };
  const contrasts: { name: string; group: string | null; a: (s: PlanSample) => DePart | null; b: (s: PlanSample) => DePart | null }[] =
    opts.mode === "pair"
      ? [{ name: `${live[0].name} vs ${live[1].name}`, group: null, a: (s) => part(s, (c) => c === code(live[0])), b: (s) => part(s, (c) => c === code(live[1])) }]
      : live.map((g) => ({
          name: `${g.name} vs rest`,
          group: g.name,
          a: (s) => part(s, (c) => c === code(g)),
          b: (s) => (opts.scope === "all" || touched.has(s.id) ? part(s, (c) => c !== code(g)) : null),
        }));
  const platforms = [...new Set(samples.filter((s) => cells.has(s.id)).map((s) => s.platform))];
  const levels: PlannedLevel[] = [];
  contrasts.forEach((ct, ci) => {
    for (const platform of platforms) {
      const of = samples.filter((s) => s.platform === platform && cells.has(s.id));
      const a = of.map(ct.a).filter((p): p is DePart => !!p);
      const b = of.map(ct.b).filter((p): p is DePart => !!p);
      const count = (ps: DePart[]) => ps.reduce((k, p) => k + p.rows.length, 0);
      if (count(a) < MIN_CELLS || count(b) < MIN_CELLS) continue;
      if (new Set([...a, ...b].map((p) => p.values)).size > 1) {
        skipped.push(`${platformLabel(platform)} (its sections store expression on different scales)`);
        continue;
      }
      const manyPlatforms = platforms.length > 1;
      const name = contrasts.length > 1 ? (manyPlatforms ? `${ct.group} · ${platformLabel(platform)}` : ct.group!) : manyPlatforms ? platformLabel(platform) : ct.name;
      levels.push({ req: { id: `${ci}:${platform}`, a, b }, name, group: ct.group, platform });
    }
  });
  if (!levels.length) return { problem: skipped.length ? `no row store on ${skipped.join(", ")}: the test needs one (expression.rows)` : `each side needs at least ${MIN_CELLS} cells on one platform` };
  return { levels, groups: live, skipped };
}

let running: { token: number } | null = null;
let seq = 0;

/** Run the test on the drawn regions and open the result under the maps. */
export async function runRegionTest(c: ViewerController, opts: TestOptions): Promise<void> {
  const s = store.getState();
  const m = c.manifest;
  const features = s.features;
  if (!m || !features || !s.datasetUrl) return;
  if (running) c.cache.worker.cancelDe(running.token);
  const field = c.regions.field;
  // in manifest order, so the platforms (the columns) come out the same every run
  const samples: PlanSample[] = m.samples.flatMap((smp) => {
    const sd = c.cache.samples.get(smp.id);
    return sd ? [{ id: sd.id, name: smp.name, platform: smp.platform, embedding: smp.kind === "embedding", codes: sd.cat.get(field) ?? null, chunk: sd.rows?.chunk ?? null, values: smp.expr.normalized === "raw" ? "raw" : "log" }] : [];
  });
  const plan = planTest(s.regions.groups, samples, opts);
  if ("problem" in plan) {
    s.set({ testNote: plan.problem });
    return;
  }
  const token = ++seq;
  running = { token };
  const datasetUrl = s.datasetUrl;
  s.set({ test: { token, text: "starting" }, testNote: null });
  const progress = (p: DeProgress) => {
    const cur = store.getState();
    if (cur.test?.token !== token) return;
    const lv = plan.levels.find((l) => l.req.id === p.level);
    cur.set({ test: { token, text: `${lv?.name ?? p.level}: ${p.text}` } });
  };
  const transfer = plan.levels.flatMap((l) => [...l.req.a, ...l.req.b].map((p) => p.rows.buffer as ArrayBuffer));
  const genes = features.genes;
  try {
    const results = await c.cache.worker.de(Comlink.transfer({ token, genes, levels: plan.levels.map((l) => l.req), cap: opts.cap, minPct: 0.1 }, transfer), Comlink.proxy(progress));
    if (store.getState().test?.token !== token || c.manifest !== m) return; // cancelled, or another dataset
    const { info, matrix } = assemble(plan, results, genes, field, opts, m.id);
    registerMatrix(datasetUrl, info, matrix);
    c.regions.setLive(info);
    store.getState().set({ test: null, testNote: plan.skipped.length ? `left out, no row store: ${plan.skipped.join(", ")}` : null });
    void activateComparison(LIVE_ID);
  } catch (e) {
    if (store.getState().test?.token !== token) return;
    const msg = (e as Error).message;
    store.getState().set({ test: null, testNote: /cancelled/.test(msg) ? null : `the test failed: ${msg}` });
  } finally {
    if (running?.token === token) running = null;
  }
}

export function cancelRegionTest(c: ViewerController) {
  const t = store.getState().test;
  if (!t) return;
  c.cache.worker.cancelDe(t.token);
  store.getState().set({ test: null });
}

/** The comparison entry and matrix the panel reads: genes measured in some level, one column per level. */
export function assemble(plan: TestPlan, results: DeLevelResult[], genes: string[], field: string, opts: TestOptions, datasetId: string): { info: ComparisonInfo; matrix: MatrixData } {
  const k = results.length;
  const keep: number[] = [];
  for (let g = 0; g < genes.length; g++) if (results.some((r) => r.measured[g])) keep.push(g);
  const names: Record<string, keyof DeLevelResult> = { effect: "effect", p: "p", padj: "padj", pct_in: "pctIn", pct_out: "pctOut", auc: "auc", agree: "agree" };
  const stats: Record<string, Float32Array> = {};
  for (const [stat, key] of Object.entries(names)) {
    const a = new Float32Array(keep.length * k).fill(NaN);
    results.forEach((r, j) => {
      const src = r[key] as Float32Array;
      keep.forEach((g, i) => (a[i * k + j] = src[g]));
    });
    stats[stat] = a;
  }
  if (!results.some((r) => r.nSections)) delete stats.agree; // no section holds both sides: nothing to agree
  const kept = keep.map((g) => genes[g]);
  const markers = opts.mode === "rest";
  const levels: LevelInfo[] = plan.levels.map((l, j) => {
    const r = results[j];
    let nSig = 0;
    for (let i = 0; i < r.padj.length; i++) if (r.padj[i] < 0.05) nSig++;
    return { id: l.req.id, name: l.name, path: l.req.id, nGenes: r.measured.reduce((n, v) => n + v, 0), nSignificant: nSig, nUnmatched: 0, nReplicates: r.nSections, hasPseudobulk: false, population: markers ? { field, value: l.group! } : null };
  });
  const fmt = (n: number) => n.toLocaleString();
  const cells = plan.levels.map((l, j) => {
    const r = results[j];
    const per = r.perSample.map((p) => `${p.sample} ${fmt(p.nA)}/${fmt(p.nB)}`).join(", ");
    return `${l.name}: ${fmt(r.nA)} vs ${fmt(r.nB)} cells (${per})`;
  });
  const rest = markers ? ` The rest is every other cell of ${opts.scope === "all" ? "every section" : "the sections drawn on"}.` : "";
  const raw = plan.levels.some((l) => [...l.req.a, ...l.req.b].some((p) => p.values === "raw"));
  const description = [
    `Wilcoxon rank-sum test on single cells, two-sided and tie-corrected; log2FC of the mean expression ${raw ? "of the stored values" : "after undoing the log (expm1)"} with a pseudocount of 1; % expressing per side; BH over genes expressed in at least 10% of either side; at most ${fmt(opts.cap)} cells a side, taken as whole blocks of the row store. A gene is compared among the cells of the sections that measured it: a section whose panel lacks it contributes no cells, one that measured it and found no counts contributes zeros. Sections agreeing: those with ${MIN_CELLS}+ cells on both sides whose own log2FC has the same sign.${rest}`,
    ...cells,
  ].join("\n");
  const name = markers ? (plan.groups.length === 1 ? `${plan.groups[0].name} vs rest` : "each region vs rest") : `${plan.groups[0].name} vs ${plan.groups[1].name}`;
  const info: ComparisonInfo = {
    id: LIVE_ID,
    kind: markers ? "markers" : "contrast",
    name,
    description,
    path: `live/${datasetId}`,
    groups: markers ? [] : plan.groups.map((g) => g.name),
    contrast: markers ? null : name,
    effect: "log2FC",
    facet: { column: field, field },
    levels,
    nGenes: kept.length,
    nReplicates: 0,
    nUnmatched: 0,
    hasEffect: true,
    hasP: true,
    hasPadj: true,
    hasMean: false,
    hasPct: true,
    hasPseudobulk: false,
    live: true,
  };
  const matrix: MatrixData = { info, genes: kept, levels: levels.map((l) => l.id), stats, unmeasured: new Set(), geneIndex: new Map(kept.map((g, i) => [g, i])), sections: results.map((r) => r.nSections) };
  return { info, matrix };
}
