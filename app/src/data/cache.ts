/**
 * Main-thread caches. Big typed arrays never go in the Zustand store; they live here, keyed by
 * sample id, and layers reference them through stable descriptor objects so deck.gl can tell
 * when a buffer is unchanged (identity check in Attribute.setExternalBuffer).
 */
import KDBush from "kdbush";
import * as Comlink from "comlink";
import type { DataWorkerAPI } from "./worker";
import type { OutlineData } from "./manifest";
import { ByteLRU } from "./lru";

export interface BinaryAttr<T extends ArrayBufferView> {
  value: T;
  size: number;
}

export interface SampleData {
  id: string;
  nObs: number;
  genes: string[];
  geneIndex: Map<string, number>;
  xy: Float32Array;
  posAttr: BinaryAttr<Float32Array>; // stable identity: positions never re-upload
  index: KDBush | null;
  cat: Map<string, Uint16Array>;
  catAttr: Map<string, BinaryAttr<Uint16Array>>;
  num: Map<string, Float32Array>;
  numU8: Map<string, Uint8Array>; // continuous obs quantized to [min,max] -> 0..255
  numRange: Map<string, [number, number]>;
  ids: Map<number, string[]>;
}

export const GENE_BUDGET_BYTES = 192 * 1024 * 1024;

export class DataCache {
  samples = new Map<string, SampleData>();
  genes = new ByteLRU<Uint8Array>(GENE_BUDGET_BYTES);
  private geneAttrs = new Map<string, BinaryAttr<Uint8Array>>();
  worker: Comlink.Remote<DataWorkerAPI>;

  constructor() {
    const w = new Worker(new URL("./worker.ts", import.meta.url), { type: "module" });
    this.worker = Comlink.wrap<DataWorkerAPI>(w);
  }

  async openSample(datasetUrl: string, id: string, nObs: number): Promise<SampleData> {
    const existing = this.samples.get(id);
    if (existing) return existing;
    const { genes } = await this.worker.openSample(datasetUrl, id);
    const { xy, index } = await this.worker.getXYAndIndex(id);
    const sd: SampleData = {
      id,
      nObs,
      genes,
      geneIndex: new Map(genes.map((g, i) => [g, i])),
      xy,
      posAttr: { value: xy, size: 2 },
      index: KDBush.from(index),
      cat: new Map(),
      catAttr: new Map(),
      num: new Map(),
      numU8: new Map(),
      numRange: new Map(),
      ids: new Map(),
    };
    this.samples.set(id, sd);
    return sd;
  }

  geneKey(sampleId: string, gene: string): string {
    return `${sampleId}\u0000${gene}`;
  }

  getGeneSync(sampleId: string, gene: string): BinaryAttr<Uint8Array> | undefined {
    const key = this.geneKey(sampleId, gene);
    const v = this.genes.get(key);
    if (!v) {
      this.geneAttrs.delete(key);
      return undefined;
    }
    let a = this.geneAttrs.get(key);
    if (!a || a.value !== v) {
      a = { value: v, size: 1 };
      this.geneAttrs.set(key, a);
    }
    return a;
  }

  async getGene(sampleId: string, gene: string): Promise<BinaryAttr<Uint8Array> | null> {
    const hit = this.getGeneSync(sampleId, gene);
    if (hit) return hit;
    const sd = this.samples.get(sampleId);
    if (!sd) return null;
    const gi = sd.geneIndex.get(gene);
    if (gi === undefined) return null; // gene not on this sample's panel
    const arr = await this.worker.getGene(sampleId, gi);
    this.genes.set(this.geneKey(sampleId, gene), arr);
    return this.getGeneSync(sampleId, gene)!;
  }

  gmax(sampleId: string, gene: string): Promise<number> {
    const sd = this.samples.get(sampleId);
    const gi = sd?.geneIndex.get(gene);
    if (!sd || gi === undefined) return Promise.resolve(0);
    return this.worker.gmax(sampleId, gi);
  }

  async getCategorical(sampleId: string, field: string): Promise<BinaryAttr<Uint16Array> | null> {
    const sd = this.samples.get(sampleId);
    if (!sd) return null;
    let a = sd.catAttr.get(field);
    if (a) return a;
    const codes = await this.worker.getCategorical(sampleId, field);
    sd.cat.set(field, codes);
    a = { value: codes, size: 1 };
    sd.catAttr.set(field, a);
    return a;
  }

  async getContinuousU8(sampleId: string, field: string, range?: [number, number]): Promise<BinaryAttr<Uint8Array> | null> {
    const sd = this.samples.get(sampleId);
    if (!sd) return null;
    let vals = sd.num.get(field);
    if (!vals) {
      vals = await this.worker.getContinuous(sampleId, field);
      sd.num.set(field, vals);
    }
    let r = range ?? sd.numRange.get(field);
    if (!r) {
      // robust range: 1st..99th percentile over a subsample
      const n = vals.length;
      const step = Math.max(1, Math.floor(n / 50000));
      const s: number[] = [];
      for (let i = 0; i < n; i += step) if (Number.isFinite(vals[i])) s.push(vals[i]);
      s.sort((a, b) => a - b);
      r = s.length ? [s[Math.floor(s.length * 0.01)], s[Math.floor(s.length * 0.99)]] : [0, 1];
      if (r[1] <= r[0]) r = [r[0], r[0] + 1];
      sd.numRange.set(field, r);
    }
    const key = `${field}@${r[0]},${r[1]}`;
    let u8 = sd.numU8.get(key);
    if (!u8) {
      u8 = new Uint8Array(vals.length);
      const sc = 255 / (r[1] - r[0]);
      for (let i = 0; i < vals.length; i++) {
        const v = (vals[i] - r[0]) * sc;
        u8[i] = v <= 0 || !Number.isFinite(v) ? 0 : v >= 255 ? 255 : Math.round(v);
      }
      sd.numU8.set(key, u8);
    }
    return { value: u8, size: 1 };
  }

  private polygons = new Map<string, { positions: Float32Array; startIndices: Uint32Array } | Promise<unknown>>();

  /** Decoded boundary polygons for a sample (cached); returns undefined while loading. */
  getPolygons(sampleId: string, scale: number): { positions: Float32Array; startIndices: Uint32Array } | undefined {
    const sd = this.samples.get(sampleId);
    if (!sd) return undefined;
    const v = this.polygons.get(sampleId);
    if (v && !(v instanceof Promise)) return v;
    if (!v) {
      const xyCopy = sd.xy.slice();
      const p = this.worker.getPolygons(sampleId, Comlink.transfer(xyCopy, [xyCopy.buffer]), scale).then((res) => {
        this.polygons.set(sampleId, res);
        return res;
      });
      this.polygons.set(sampleId, p);
    }
    return undefined;
  }

  private outlines = new Map<string, OutlineData | Promise<OutlineData>>();

  /** Outline polylines for a sample/field; resolved value is cached, pending fetch returned as a promise. */
  getOutlines(datasetUrl: string, sampleId: string, field: string): OutlineData | Promise<OutlineData> {
    const key = `${sampleId}/${field}`;
    let v = this.outlines.get(key);
    if (!v) {
      v = fetch(`${datasetUrl.replace(/\/$/, "")}/samples/${sampleId}/outlines/${field}.json`)
        .then((r) => {
          if (!r.ok) throw new Error(`outlines ${r.status}`);
          return r.json() as Promise<OutlineData>;
        })
        .then((d) => {
          this.outlines.set(key, d);
          return d;
        });
      this.outlines.set(key, v);
    }
    return v;
  }

  /** 0/1 mask for membership of categorical codes (cached per code set). Requires the categorical array. */
  categoryMask(sampleId: string, field: string, codes: number[]): BinaryAttr<Uint8Array> | undefined {
    const sd = this.samples.get(sampleId);
    const cat = sd?.cat.get(field);
    if (!sd || !cat) return undefined;
    const key = `cat:${field}:${codes.join(".")}`;
    let m = sd.numU8.get(key);
    if (!m) {
      const set = new Set(codes);
      m = new Uint8Array(cat.length);
      for (let i = 0; i < cat.length; i++) m[i] = set.has(cat[i]) ? 255 : 0;
      sd.numU8.set(key, m);
    }
    return { value: m, size: 1 };
  }

  async getId(sampleId: string, index: number, idBlock: number): Promise<string | undefined> {
    const sd = this.samples.get(sampleId);
    if (!sd) return undefined;
    const b = Math.floor(index / idBlock);
    let blk = sd.ids.get(b);
    if (!blk) {
      blk = await this.worker.getIds(sampleId, b);
      sd.ids.set(b, blk);
    }
    return blk[index - b * idBlock];
  }
}
