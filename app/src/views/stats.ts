/** Derived numbers shown in the sidebar: category counts, filter histogram, gene-by-annotation table. */
import type { BinaryAttr, SampleData } from "../data/cache";
import { fieldById } from "../data/manifest";
import { store, type FilterSpec } from "../store/store";
import type { ViewerController } from "./ViewerController";
import { filterRange } from "./types";

export class Stats {
  constructor(private c: ViewerController) {}

  filterAttr(sd: SampleData, f: FilterSpec): BinaryAttr<Uint8Array> | undefined {
    if (f.kind === "gene") return this.c.cache.getGeneSync(sd.id, f.gene);
    if (f.kind === "category") return this.c.cache.categoryMask(sd.id, f.field, f.codes);
    const key = [...sd.numU8.keys()].find((k) => k.startsWith(`${f.field}@`));
    const u8 = key ? sd.numU8.get(key) : undefined;
    return u8 ? { value: u8, size: 1 } : undefined;
  }

  updateCategoryCounts(field: string) {
    const c = this.c;
    const f = c.manifest && fieldById(c.manifest, field);
    if (!f || f.type !== "categorical") return;
    const n = c.manifest!.vocabularies[f.vocabulary].categories.length;
    const counts = new Array<number>(n).fill(0);
    const hidden = c.hiddenSampleSet(store.getState());
    for (const sd of c.cache.samples.values()) {
      if (hidden.has(sd.id)) continue;
      const codes = sd.cat.get(field);
      if (!codes) continue;
      for (let i = 0; i < codes.length; i++) if (codes[i] < n) counts[codes[i]]++;
    }
    store.getState().set({ categoryCounts: { ...store.getState().categoryCounts, [field]: counts } });
  }

  updateFilterHistogram() {
    const s = store.getState();
    if (!s.filter) return;
    const bins = new Array<number>(64).fill(0);
    let visible = 0;
    const range = filterRange(s.filter);
    for (const sd of this.c.cache.samples.values()) {
      const arr = this.filterAttr(sd, s.filter)?.value;
      if (!arr) continue;
      const lo = range[0] * 255;
      const hi = range[1] * 255;
      for (let i = 0; i < arr.length; i++) {
        bins[arr[i] >> 2]++;
        if (arr[i] >= lo && arr[i] <= hi) visible++;
      }
    }
    s.set({ filterHistogram: bins, visibleCount: visible });
  }

  /** Mean / fraction-expressing of the colored gene (or blend channel A) per category, over visible samples. */
  updateGroupStats() {
    const c = this.c;
    const s = store.getState();
    const genes = s.color?.kind === "gene" ? [s.color.gene] : s.color?.kind === "blend" ? s.color.a : [];
    if (!c.manifest || !genes.length || !s.groupField) {
      if (s.groupStats) s.set({ groupStats: null });
      return;
    }
    const f = fieldById(c.manifest, s.groupField);
    if (!f || f.type !== "categorical") return;
    const n = c.manifest.vocabularies[f.vocabulary].categories.length;
    const hidden = c.hiddenSampleSet(s);
    const sum = new Float64Array(n);
    const cnt = new Float64Array(n);
    const pos = new Float64Array(n);
    const per: Record<string, { sum: Float64Array; cnt: Float64Array; pos: Float64Array }> = {};
    for (const sd of c.cache.samples.values()) {
      if (hidden.has(sd.id)) continue;
      const cat = sd.cat.get(f.id);
      const score = s.color?.kind === "blend" ? c.blend.score(sd, genes) : null;
      const g = score ?? c.cache.getGeneSync(sd.id, genes[0])?.value;
      const gmax = score ? 1 : c.geneGmax.get(`${sd.id}:${genes[0]}`);
      if (!g || !cat || gmax === undefined) continue;
      const p = (per[sd.id] = { sum: new Float64Array(n), cnt: new Float64Array(n), pos: new Float64Array(n) });
      const k = gmax / 255;
      for (let i = 0; i < g.length; i++) {
        const cc = cat[i];
        if (cc >= n) continue;
        const v = g[i] * k;
        sum[cc] += v;
        cnt[cc]++;
        p.sum[cc] += v;
        p.cnt[cc]++;
        if (g[i] > 0) {
          pos[cc]++;
          p.pos[cc]++;
        }
      }
    }
    const rows = [];
    let maxMean = 0;
    for (let code = 0; code < n; code++) {
      if (!cnt[code]) continue;
      const mean = sum[code] / cnt[code];
      maxMean = Math.max(maxMean, mean);
      const perSample: Record<string, { n: number; mean: number; frac: number }> = {};
      for (const [sid, p] of Object.entries(per)) if (p.cnt[code]) perSample[sid] = { n: p.cnt[code], mean: p.sum[code] / p.cnt[code], frac: p.pos[code] / p.cnt[code] };
      rows.push({ code, n: cnt[code], mean, frac: pos[code] / cnt[code], perSample });
    }
    rows.sort((a, b) => b.mean - a.mean);
    s.set({ groupStats: { gene: s.color?.kind === "blend" ? "set A" : genes[0], field: f.id, rows, maxMean } });
  }
}
