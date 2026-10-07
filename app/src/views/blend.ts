/** Gene-set scores for two-channel blending: per cell, the mean log-normalized expression of the set's genes. */
import type { BinaryAttr, SampleData } from "../data/cache";
import type { ViewerController } from "./ViewerController";

/**
 * Mean of the genes per cell, in expression units, then mapped to 0..255 against `scaleMax`.
 * `cols` are uint8 columns quantized against `gmax[j]` (value = u8 / 255 * gmax).
 */
export function blendScore(cols: Uint8Array[], gmax: number[], n: number, scaleMax: number): Uint8Array {
  const out = new Uint8Array(n);
  if (!cols.length || scaleMax <= 0) return out;
  const acc = new Float32Array(n);
  cols.forEach((col, j) => {
    const k = gmax[j] / 255;
    for (let i = 0; i < n; i++) acc[i] += col[i] * k;
  });
  const f = 255 / (cols.length * scaleMax);
  for (let i = 0; i < n; i++) out[i] = Math.min(255, Math.round(acc[i] * f));
  return out;
}

export class Blend {
  private cache = new Map<string, { attr: BinaryAttr<Uint8Array>; key: string }>();

  constructor(private c: ViewerController) {}

  invalidate() {
    this.cache.clear();
  }

  score(sd: SampleData, genes: string[]): Uint8Array | null {
    return this.attr(sd, genes)?.value ?? null;
  }

  /** Largest per-gene max for these genes: across every loaded sample (shared scale) or within this sample. */
  scaleMax(sd: SampleData, genes: string[], perSample: boolean): number {
    let m = 0;
    for (const [k, v] of this.c.geneGmax) {
      const i = k.indexOf(":");
      if (!genes.includes(k.slice(i + 1))) continue;
      if (perSample && k.slice(0, i) !== sd.id) continue;
      if (v > m) m = v;
    }
    return m;
  }

  attr(sd: SampleData, genes: string[]): BinaryAttr<Uint8Array> | undefined {
    const present = genes.filter((g) => sd.geneIndex.has(g));
    if (!present.length) return undefined;
    const cols: Uint8Array[] = [];
    const gmax: number[] = [];
    let missingMax = false;
    for (const g of present) {
      const col = this.c.cache.getGeneSync(sd.id, g)?.value;
      if (!col) continue;
      const gm = this.c.geneGmax.get(`${sd.id}:${g}`);
      if (gm === undefined) missingMax = true;
      cols.push(col);
      gmax.push(gm ?? 1);
    }
    if (!cols.length) return undefined;
    const perSample = !!this.c.storeState().scalePerSample;
    const scaleMax = missingMax ? 0 : this.scaleMax(sd, present, perSample);
    const key = `${genes.join(",")}|${cols.length}/${present.length}|${perSample}|${scaleMax}|${missingMax}`;
    const cacheKey = `${sd.id}|${genes.join(",")}`;
    const hit = this.cache.get(cacheKey);
    if (hit && hit.key === key) return hit.attr;
    let out: Uint8Array;
    if (missingMax || scaleMax <= 0) {
      // maxima not known yet: provisional mean of the raw quantized columns, replaced once gmax arrives
      out = new Uint8Array(sd.nObs);
      const acc = new Float32Array(sd.nObs);
      for (const col of cols) for (let i = 0; i < sd.nObs; i++) acc[i] += col[i];
      const k = 1 / cols.length;
      for (let i = 0; i < sd.nObs; i++) out[i] = Math.round(acc[i] * k);
    } else out = blendScore(cols, gmax, sd.nObs, scaleMax);
    const attr = { value: out, size: 1 };
    this.cache.set(cacheKey, { attr, key });
    return attr;
  }

  /** How many of the requested genes exist on a sample's panel (for the UI). */
  coverage(sd: SampleData, genes: string[]): number {
    return genes.filter((g) => sd.geneIndex.has(g)).length;
  }
}
