/** Derived numbers shown in the sidebar: category counts, filter histogram, gene-by-annotation table. */
import type { BinaryAttr, SampleData } from "../data/cache";
import { fieldById } from "../data/manifest";
import { store, type FilterSpec, type ViewerState } from "../store/store";
import type { ViewerController } from "./ViewerController";
import { filterRange } from "./types";
import { cellTest } from "./visibility";

function hiddenSetOf(s: ViewerState): Set<number> | undefined {
  const codes = s.color?.kind === "field" ? s.hiddenCategories[s.color.field] : undefined;
  return codes?.length ? new Set(codes) : undefined;
}

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
    const s = store.getState();
    const hidden = c.hiddenSampleSet(s);
    const shared = c.visibility.sharedFilterMax(s);
    for (const sd of c.cache.samples.values()) {
      if (hidden.has(sd.id)) continue;
      const codes = sd.cat.get(field);
      if (!codes) continue;
      // the population: cells of drawn samples that pass the filter (a hidden category still shows its count)
      const keep = c.visibility.mask(sd, s, { categories: false, zeros: false }, shared);
      for (let i = 0; i < codes.length; i++) if (codes[i] < n && (!keep || keep(i))) counts[codes[i]]++;
    }
    store.getState().set({ categoryCounts: { ...store.getState().categoryCounts, [field]: counts } });
  }

  updateFilterHistogram() {
    const s = store.getState();
    if (!s.filter) return;
    const bins = new Array<number>(64).fill(0);
    let visible = 0;
    let evaluated = 0;
    const unmeasured = { cells: 0, samples: 0 };
    const c = this.c;
    const hiddenSamples = c.hiddenSampleSet(s);
    const shared = c.visibility.sharedFilterMax(s);
    for (const sd of c.cache.samples.values()) {
      if (hiddenSamples.has(sd.id)) continue;
      const fs = c.visibility.filterState(sd, s, shared);
      if (fs.state === "unmeasured") {
        unmeasured.cells += sd.nObs;
        unmeasured.samples++;
        continue;
      }
      if (fs.state !== "ok") continue;
      // the histogram is in the units the slider is set in; the legend's hidden categories and hidden zeros decide the rest
      const hidden = hiddenSetOf(s);
      const other = cellTest({
        hidden,
        cat: hidden && s.color?.kind === "field" ? sd.cat.get(s.color.field) : undefined,
        filter: { state: "none" },
        zeros: s.hideZeros && s.color?.kind === "gene" ? c.cache.getGeneSync(sd.id, s.color.gene)?.value : undefined,
      });
      const arr = fs.values;
      const toUnit = 255 / fs.scale;
      evaluated += arr.length;
      for (let i = 0; i < arr.length; i++) {
        bins[Math.min(63, (arr[i] * toUnit) >> 2)]++;
        if (arr[i] >= fs.lo && arr[i] <= fs.hi && (!other || other(i))) visible++;
      }
    }
    s.set({ filterHistogram: bins, visibleCount: visible, filterEvaluated: evaluated, filterUnmeasured: unmeasured.cells ? unmeasured : null });
  }

  /** Mean, fraction expressing and the distribution (a histogram over the shared value range, with quartiles)
   *  of the colored gene (or blend channel A) per category, over visible samples. */
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
    const BINS = 24;
    // the samples that carry the gene and the field, and the value range they share (gmax differs per sample)
    const parts: { id: string; g: ArrayLike<number>; cat: ArrayLike<number>; gmin: number; gmax: number }[] = [];
    let vmin = Infinity;
    let vmax = -Infinity;
    for (const sd of c.cache.samples.values()) {
      if (hidden.has(sd.id)) continue;
      const cat = sd.cat.get(f.id);
      const score = s.color?.kind === "blend" ? c.blend.score(sd, genes) : null;
      const g = score ?? c.cache.getGeneSync(sd.id, genes[0])?.value;
      const gmax = score ? 1 : c.geneGmax.get(`${sd.id}:${genes[0]}`);
      const gmin = score ? 0 : (c.geneGmin.get(`${sd.id}:${genes[0]}`) ?? 0);
      if (!g || !cat || gmax === undefined) continue;
      parts.push({ id: sd.id, g, cat, gmin, gmax });
      vmin = Math.min(vmin, gmin);
      vmax = Math.max(vmax, gmax);
    }
    if (!(vmax > vmin)) vmax = vmin + 1;
    const sum = new Float64Array(n);
    const cnt = new Float64Array(n);
    const pos = new Float64Array(n);
    const hist = new Float64Array(n * BINS);
    const per: Record<string, { sum: Float64Array; cnt: Float64Array; pos: Float64Array }> = {};
    const bk = BINS / (vmax - vmin);
    const shared = c.visibility.sharedFilterMax(s);
    const signed = parts.some((p) => p.gmin < 0); // a score that takes negative values has no "expressing" fraction
    for (const { id, g, cat, gmin, gmax } of parts) {
      const p = (per[id] = { sum: new Float64Array(n), cnt: new Float64Array(n), pos: new Float64Array(n) });
      const k = (gmax - gmin) / 255;
      const keep = c.visibility.mask(c.cache.samples.get(id)!, s, { categories: false, zeros: false }, shared);
      for (let i = 0; i < g.length; i++) {
        const cc = cat[i];
        if (cc >= n || (keep && !keep(i))) continue;
        const v = gmin + g[i] * k;
        sum[cc] += v;
        cnt[cc]++;
        p.sum[cc] += v;
        p.cnt[cc]++;
        if (!signed && g[i] > 0) {
          // byte 0 is exactly zero for a non-negative feature (a positive value never quantizes to 0)
          pos[cc]++;
          p.pos[cc]++;
        }
        let b = Math.floor((v - vmin) * bk);
        if (b >= BINS) b = BINS - 1;
        else if (b < 0) b = 0;
        hist[cc * BINS + b]++;
      }
    }
    const rows = [];
    let maxMean = 0;
    const width = (vmax - vmin) / BINS;
    for (let code = 0; code < n; code++) {
      if (!cnt[code]) continue;
      const mean = sum[code] / cnt[code];
      maxMean = Math.max(maxMean, mean);
      const perSample: Record<string, { n: number; mean: number; frac: number }> = {};
      for (const [sid, p] of Object.entries(per)) if (p.cnt[code]) perSample[sid] = { n: p.cnt[code], mean: p.sum[code] / p.cnt[code], frac: signed ? NaN : p.pos[code] / p.cnt[code] };
      const h = Array.from(hist.subarray(code * BINS, (code + 1) * BINS));
      const quantile = (q: number) => {
        // the bin the q-th cell falls in, read at its centre: as fine as the 8-bit values allow
        const target = q * cnt[code];
        let acc = 0;
        for (let b = 0; b < BINS; b++) {
          acc += h[b];
          if (acc >= target) return vmin + (b + 0.5) * width;
        }
        return vmax;
      };
      rows.push({ code, n: cnt[code], mean, frac: signed ? NaN : pos[code] / cnt[code], perSample, hist: h, median: quantile(0.5), q1: quantile(0.25), q3: quantile(0.75) });
    }
    rows.sort((a, b) => b.mean - a.mean);
    s.set({ groupStats: { gene: s.color?.kind === "blend" ? "set A" : genes[0], field: f.id, rows, maxMean, vmin, vmax, bins: BINS } });
  }
}
