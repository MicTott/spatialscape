/** Gene-set scores for two-channel blending: mean of per-gene normalized expression (uint8) per cell. */
import type { BinaryAttr, SampleData } from "../data/cache";
import type { ViewerController } from "./ViewerController";

export class Blend {
  private cache = new Map<string, { attr: BinaryAttr<Uint8Array>; loaded: string }>();

  constructor(private c: ViewerController) {}

  invalidate() {
    this.cache.clear();
  }

  /** Mean of the genes currently loaded for this sample, 0..255; null when none of the genes is measured. */
  score(sd: SampleData, genes: string[]): Uint8Array | null {
    return this.attr(sd, genes)?.value ?? null;
  }

  attr(sd: SampleData, genes: string[]): BinaryAttr<Uint8Array> | undefined {
    const present = genes.filter((g) => sd.geneIndex.has(g));
    if (!present.length) return undefined;
    const cols = present.map((g) => this.c.cache.getGeneSync(sd.id, g)?.value).filter((v): v is Uint8Array => !!v);
    if (!cols.length) return undefined;
    const key = `${sd.id}|${genes.join(",")}`;
    const loaded = cols.length + "/" + present.length;
    const hit = this.cache.get(key);
    if (hit && hit.loaded === loaded) return hit.attr;
    const n = sd.nObs;
    const out = new Uint8Array(n);
    if (cols.length === 1) out.set(cols[0]);
    else {
      const acc = new Float32Array(n);
      for (const col of cols) for (let i = 0; i < n; i++) acc[i] += col[i];
      const k = 1 / cols.length;
      for (let i = 0; i < n; i++) out[i] = Math.round(acc[i] * k);
    }
    const attr = { value: out, size: 1 };
    this.cache.set(key, { attr, loaded });
    return attr;
  }

  /** How many of the requested genes exist on a sample's panel (for the UI). */
  coverage(sd: SampleData, genes: string[]): number {
    return genes.filter((g) => sd.geneIndex.has(g)).length;
  }
}
