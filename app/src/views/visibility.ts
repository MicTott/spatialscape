/** One definition of "a cell you can see", shared by the layers, hover, lasso and the sidebar's numbers.
 *
 *  A cell is drawn unless its category is hidden in the legend (colouring by an annotation), the active filter
 *  leaves it out, or *hide zeros* is on and it does not express the gene on screen. A gene filter is set on one
 *  shared value range (the drawn samples' lowest minimum to highest maximum, like the colour scale), so the same
 *  expression value passes in every sample; a sample that does not measure the filter's gene or field shows no
 *  cells while the filter is on, and the filter panel says how many that is. */
import type { SampleData } from "../data/cache";
import type { ViewerState } from "../store/store";
import { filterRange } from "./types";
import type { ViewerController } from "./ViewerController";

export type FilterState =
  | { state: "none" }
  | { state: "loading" } // the sample measures the channel but its column has not arrived: nothing hidden yet
  | { state: "unmeasured" } // the sample has no such gene or field: every cell is out while the filter is on
  | { state: "ok"; values: Uint8Array; lo: number; hi: number; unit: (byte: number) => number }; // bytes in [lo, hi] pass; unit maps a byte to the slider's 0..255 scale

export interface CellMask {
  hidden?: Set<number>; // category codes hidden in the legend
  cat?: ArrayLike<number>; // the colour field's codes per cell
  filter: FilterState;
  zeros?: ArrayLike<number>; // the gene on screen, when hide zeros is on
  isZero?: (byte: number) => boolean; // which byte of `zeros` is zero (default 0; a signed feature's zero is mid-range)
}

/** The per-cell test for one sample, or null when nothing is hidden. */
export function cellTest(m: CellMask): ((i: number) => boolean) | null {
  if (m.filter.state === "unmeasured") return () => false;
  const cat = m.hidden?.size ? m.cat : undefined;
  const hidden = m.hidden;
  const f = m.filter.state === "ok" ? m.filter : null;
  const z = m.zeros;
  const isZero = m.isZero ?? ((b: number) => b === 0);
  if (!cat && !f && !z) return null;
  return (i) => !(cat && hidden!.has(cat[i])) && !(f && (f.values[i] < f.lo || f.values[i] > f.hi)) && !(z && isZero(z[i]));
}

export class Visibility {
  constructor(private c: ViewerController) {}

  /** The value range a gene filter is set in: the union of the drawn samples' own ranges, or null for per-sample
   *  scaling, non-gene filters and before any range is known. */
  sharedFilterRange(s: ViewerState): [number, number] | null {
    if (s.filter?.kind !== "gene" || s.scalePerSample) return null;
    const hidden = this.c.hiddenSampleSet(s);
    let lo = Infinity;
    let hi = -Infinity;
    for (const id of this.c.cache.samples.keys()) {
      if (hidden.has(id)) continue;
      const g = this.c.geneGmax.get(`${id}:${s.filter.gene}`);
      if (g === undefined) continue;
      hi = Math.max(hi, g);
      lo = Math.min(lo, this.c.geneGmin.get(`${id}:${s.filter.gene}`) ?? 0);
    }
    return hi > lo ? [lo, hi] : null;
  }

  /** What the filter does to one sample. */
  filterState(sd: SampleData, s: ViewerState, shared: [number, number] | null = this.sharedFilterRange(s)): FilterState {
    const f = s.filter;
    if (!f) return { state: "none" };
    const smp = this.c.samplesById.get(sd.id);
    if (f.kind === "gene" ? !sd.geneIndex.has(f.gene) : !smp?.fields.includes(f.field)) return { state: "unmeasured" };
    const values = this.c.stats.filterAttr(sd, f)?.value;
    if (!values) return { state: "loading" };
    const [a, b] = filterRange(f);
    if (f.kind === "gene" && shared) {
      // the slider's 0..1 spans the shared range; this sample's bytes span its own [gmin, gmax]
      const gmax = this.c.geneGmax.get(`${sd.id}:${f.gene}`);
      const gmin = this.c.geneGmin.get(`${sd.id}:${f.gene}`) ?? 0;
      if (gmax === undefined) return { state: "loading" };
      const span = gmax - gmin;
      const [L, H] = shared;
      const toByte = (t: number) => (span > 0 ? ((L + t * (H - L) - gmin) / span) * 255 : t * 255);
      const unit = (byte: number) => (span > 0 ? ((gmin + (byte / 255) * span - L) / (H - L)) * 255 : byte);
      return { state: "ok", values, lo: toByte(a), hi: toByte(b), unit };
    }
    return { state: "ok", values, lo: a * 255, hi: b * 255, unit: (byte) => byte };
  }

  /** Zero for a gene, as the shader sees it: byte 0 for a non-negative feature, the middle code for a signed one
   *  (its range is symmetric about zero); null until the sample's range is known. */
  zeroTest(sd: SampleData, gene: string): ((byte: number) => boolean) | null {
    const gmin = this.c.geneGmin.get(`${sd.id}:${gene}`);
    if (gmin === undefined) return null;
    return gmin < 0 ? (b) => Math.abs(b / 255 - 0.5) < 0.0025 : (b) => b === 0;
  }

  /** The test for what is drawn of a sample. `categories: false` leaves the legend's hidden categories out and
   *  `zeros: false` the hide-zeros switch, for numbers that are about the categories or the values themselves. */
  mask(sd: SampleData, s: ViewerState, { categories = true, zeros = true } = {}, shared?: [number, number] | null): ((i: number) => boolean) | null {
    const field = s.color?.kind === "field" ? s.color.field : null;
    const codes = categories && field ? s.hiddenCategories[field] : undefined;
    const hidden = codes?.length ? new Set(codes) : undefined;
    const gene = zeros && s.hideZeros && s.color?.kind === "gene" ? s.color.gene : null;
    const z = gene ? this.c.cache.getGeneSync(sd.id, gene)?.value : undefined;
    const isZero = gene ? (this.zeroTest(sd, gene) ?? undefined) : undefined;
    const fs = this.filterState(sd, s, shared === undefined ? this.sharedFilterRange(s) : shared);
    return cellTest({ hidden, cat: hidden && field ? sd.cat.get(field) : undefined, filter: fs, zeros: z, isZero });
  }
}
