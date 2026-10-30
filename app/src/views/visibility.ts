/** One definition of "a cell you can see", shared by the layers, hover, lasso and the sidebar's numbers.
 *
 *  A cell is drawn unless its category is hidden in the legend (colouring by an annotation), the active filter
 *  leaves it out, or *hide zeros* is on and it does not express the gene on screen. A gene filter is set on one
 *  shared scale (the largest per-sample maximum among the drawn samples, like the colour scale), so the same
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
  | { state: "ok"; values: Uint8Array; lo: number; hi: number; scale: number }; // bytes in [lo, hi] pass; scale = bytes per unit of the slider

export interface CellMask {
  hidden?: Set<number>; // category codes hidden in the legend
  cat?: ArrayLike<number>; // the colour field's codes per cell
  filter: FilterState;
  zeros?: ArrayLike<number>; // the gene on screen, when hide zeros is on: byte 0 is hidden
}

/** The per-cell test for one sample, or null when nothing is hidden. */
export function cellTest(m: CellMask): ((i: number) => boolean) | null {
  if (m.filter.state === "unmeasured") return () => false;
  const cat = m.hidden?.size ? m.cat : undefined;
  const hidden = m.hidden;
  const f = m.filter.state === "ok" ? m.filter : null;
  const z = m.zeros;
  if (!cat && !f && !z) return null;
  return (i) => !(cat && hidden!.has(cat[i])) && !(f && (f.values[i] < f.lo || f.values[i] > f.hi)) && !(z && z[i] === 0);
}

export class Visibility {
  constructor(private c: ViewerController) {}

  /** The largest per-sample maximum of the filter gene among drawn samples: the unit a gene filter is set in
   *  (0 when the filter is not a gene filter, or per-sample scaling was asked for). */
  sharedFilterMax(s: ViewerState): number {
    if (s.filter?.kind !== "gene" || s.scalePerSample) return 0;
    const hidden = this.c.hiddenSampleSet(s);
    let m = 0;
    for (const id of this.c.cache.samples.keys()) if (!hidden.has(id)) m = Math.max(m, this.c.geneGmax.get(`${id}:${s.filter.gene}`) ?? 0);
    return m;
  }

  /** What the filter does to one sample. */
  filterState(sd: SampleData, s: ViewerState, shared = this.sharedFilterMax(s)): FilterState {
    const f = s.filter;
    if (!f) return { state: "none" };
    const smp = this.c.samplesById.get(sd.id);
    if (f.kind === "gene" ? !sd.geneIndex.has(f.gene) : !smp?.fields.includes(f.field)) return { state: "unmeasured" };
    const values = this.c.stats.filterAttr(sd, f)?.value;
    if (!values) return { state: "loading" };
    let k = 255; // bytes per unit of the slider's 0..1 range
    if (f.kind === "gene" && shared > 0) {
      const g = this.c.geneGmax.get(`${sd.id}:${f.gene}`);
      if (g === undefined) return { state: "loading" };
      if (g > 0) k = (255 * shared) / g;
    }
    const [a, b] = filterRange(f);
    return { state: "ok", values, lo: a * k, hi: b * k, scale: k };
  }

  /** The test for what is drawn of a sample. `categories: false` leaves the legend's hidden categories out and
   *  `zeros: false` the hide-zeros switch, for numbers that are about the categories or the values themselves. */
  mask(sd: SampleData, s: ViewerState, { categories = true, zeros = true } = {}, shared?: number): ((i: number) => boolean) | null {
    const field = s.color?.kind === "field" ? s.color.field : null;
    const codes = categories && field ? s.hiddenCategories[field] : undefined;
    const hidden = codes?.length ? new Set(codes) : undefined;
    const z = zeros && s.hideZeros && s.color?.kind === "gene" ? this.c.cache.getGeneSync(sd.id, s.color.gene)?.value : undefined;
    return cellTest({ hidden, cat: hidden && field ? sd.cat.get(field) : undefined, filter: this.filterState(sd, s, shared), zeros: z });
  }
}
