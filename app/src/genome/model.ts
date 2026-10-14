/** Pure helpers for the genome panel: loci, axis ticks, bins and fetch windows, gene lanes. Coordinates are bp,
 *  0-based and half-open like BED; loci are printed 1-based inclusive like every browser does. */
export interface Locus {
  chrom: string;
  start: number;
  end: number;
}
export interface Gene {
  name: string;
  strand: number; // 1, -1, or 0 when unknown
  start: number;
  end: number;
  exonStarts: number[];
  exonEnds: number[];
}
export interface Peak {
  start: number;
  end: number;
  name: string;
}
/** A row of tracks/genes/<chrom>.json: [name, strand, start, end, exon starts, exon ends]. */
export type GeneRow = [string, number, number, number, number[], number[]];
export const geneFromRow = (r: GeneRow): Gene => ({ name: r[0], strand: r[1], start: r[2], end: r[3], exonStarts: r[4], exonEnds: r[5] });

export const MAX_PX_PER_BP = 16;
export const MIN_SPAN_BP = 40;

const int = (n: number) => Math.round(n).toLocaleString("en-US");

export function formatLocus(l: Locus): string {
  return `${l.chrom}:${int(l.start + 1)}-${int(l.end)}`;
}

export function formatSpan(bp: number): string {
  if (bp >= 1e6) return `${(bp / 1e6).toFixed(bp >= 1e7 ? 0 : 1)} Mb`;
  if (bp >= 1e3) return `${(bp / 1e3).toFixed(bp >= 1e4 ? 0 : 1)} kb`;
  return `${Math.round(bp)} bp`;
}

/** "chr11:60,405,808-60,512,181", "11:60405808-60512181", "chr11" (the whole chromosome), "chr11:60455843" (±5 kb). */
export function parseLocus(text: string, sizes: Map<string, number>): Locus | null {
  const t = text.trim().replace(/,/g, "").replace(/\s+/g, "");
  const m = /^([A-Za-z0-9_.]+?)(?::(\d+)(?:-(\d+))?)?$/.exec(t);
  if (!m) return null;
  let chrom = m[1];
  if (!sizes.has(chrom)) {
    if (sizes.has(`chr${chrom}`)) chrom = `chr${chrom}`;
    else return null;
  }
  const len = sizes.get(chrom)!;
  if (m[2] == null) return { chrom, start: 0, end: len };
  let start = +m[2] - 1;
  let end = m[3] != null ? +m[3] : -1;
  if (end < 0) {
    start -= 5000;
    end = +m[2] + 5000;
  }
  start = Math.max(0, start);
  end = Math.min(len, end);
  return end > start ? { chrom, start, end } : null;
}

/** Tick spacing: 1, 2, 2.5 or 5 × a power of ten, at least `minPx` apart. */
export function niceStep(span: number, widthPx: number, minPx = 90): number {
  const raw = (span / Math.max(1, widthPx)) * minPx;
  const p = 10 ** Math.floor(Math.log10(raw));
  for (const f of [1, 2, 2.5, 5, 10]) if (f * p >= raw) return f * p;
  return 10 * p;
}

export function ticks(start: number, end: number, step: number): number[] {
  const out: number[] = [];
  for (let t = Math.ceil(start / step) * step; t <= end; t += step) out.push(t);
  return out;
}

function decimals(x: number): number {
  let d = 0;
  while (d < 6 && Math.abs(x * 10 ** d - Math.round(x * 10 ** d)) > 1e-9) d++;
  return d;
}

/** Tick labels in the unit of the step: "60.4 Mb", "60,410 kb", "60,412.5 kb", "1,250". */
export function tickLabel(bp: number, step: number): string {
  if (step >= 1e6) return `${(bp / 1e6).toFixed(decimals(step / 1e6))} Mb`;
  if (step >= 1e3) {
    const d = decimals(step / 1e3);
    return `${(bp / 1e3).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })} kb`;
  }
  return int(bp);
}

/** Bin width to request: the track's own bin, doubled until a bin is at least one pixel wide. */
export function binFor(bpPerPx: number, trackBin: number): number {
  let b = trackBin;
  while (b < bpPerPx) b *= 2;
  return b;
}

/** The window to fetch for a view: the visible range plus one span on each side, aligned to the bin. */
export function windowFor(start: number, end: number, bin: number, chromLen: number): { start: number; end: number } {
  const span = end - start;
  const s = Math.max(0, Math.floor((start - span) / bin) * bin);
  const e = Math.min(chromLen, Math.ceil((end + span) / bin) * bin);
  return { start: s, end: e };
}

/** Whether cached bins can draw the visible range: same chromosome, covering it, and no coarser than twice the wanted bin. */
export function covers(c: { chrom: string; bin: number; start: number; end: number }, chrom: string, start: number, end: number, bin: number): boolean {
  return c.chrom === chrom && c.start <= start && c.end >= end && c.bin <= 2 * bin;
}

/** Greedy packing of genes into at most `maxLanes` rows; extents in px include the centred label when `labelPx` is given.
 *  Genes that fit nowhere are dropped (dense regions at low zoom). */
export function packLanes<T extends { start: number; end: number; name: string }>(items: T[], pxPerBp: number, maxLanes: number, labelPx: ((name: string) => number) | null, gapPx = 8): T[][] {
  const lanes: T[][] = [];
  const ends: number[] = [];
  for (const g of [...items].sort((a, b) => a.start - b.start || a.end - b.end)) {
    let x0 = g.start * pxPerBp;
    let x1 = g.end * pxPerBp;
    if (labelPx) {
      const half = labelPx(g.name) / 2;
      const mid = (x0 + x1) / 2;
      x0 = Math.min(x0, mid - half);
      x1 = Math.max(x1, mid + half);
    }
    let placed = false;
    for (let i = 0; i < lanes.length; i++) {
      if (ends[i] + gapPx <= x0) {
        lanes[i].push(g);
        ends[i] = x1;
        placed = true;
        break;
      }
    }
    if (!placed && lanes.length < maxLanes) {
      lanes.push([g]);
      ends.push(x1);
    }
  }
  return lanes;
}

/** Positions (bp) for strand chevrons along the introns of a gene (or its body when there are no introns),
 *  about every `everyPx` pixels within the visible part. */
export function chevronPositions(g: Gene, pxPerBp: number, viewStart: number, viewEnd: number, everyPx = 60): number[] {
  const out: number[] = [];
  const segs: [number, number][] = [];
  if (g.exonStarts.length > 1) for (let i = 1; i < g.exonStarts.length; i++) segs.push([g.exonEnds[i - 1], g.exonStarts[i]]);
  else segs.push([g.start, g.end]);
  for (const [s0, e0] of segs) {
    const s = Math.max(s0, viewStart);
    const e = Math.min(e0, viewEnd);
    const px = (e - s) * pxPerBp;
    if (px < everyPx * 0.6) continue;
    const n = Math.max(1, Math.floor(px / everyPx));
    for (let k = 0; k < n; k++) out.push(s + ((k + 0.5) / n) * (e - s));
  }
  return out;
}

/** A gene with room around it: 1.5 lengths each side, at least 5 kb. */
export function padGene(start: number, end: number, chromLen: number): { start: number; end: number } {
  const pad = Math.max(5000, (end - start) * 1.5);
  return { start: Math.max(0, start - pad), end: Math.min(chromLen, end + pad) };
}

/** A peak with 10 kb each side. */
export function padPeak(start: number, end: number, chromLen: number): { start: number; end: number } {
  return { start: Math.max(0, start - 10_000), end: Math.min(chromLen, end + 10_000) };
}
