/// <reference lib="webworker" />
/**
 * Data worker: owns the zarr handles for every sample, fetches + decodes gene columns and
 * obs arrays, and builds KDBush spatial indexes. All big arrays are transferred, not copied.
 */
import * as Comlink from "comlink";
import KDBush from "kdbush";
import * as zarr from "zarrita";

type U8Array = zarr.Array<"uint8", zarr.FetchStore>;
type Handles = {
  base: string; // .../samples/<id>
  u8: U8Array;
  gmax: Float32Array;
  genes: string[];
  geneIndex: Map<string, number>;
  obs: zarr.Group<zarr.FetchStore>;
  cat: Map<string, Uint16Array>;
  num: Map<string, Float32Array>;
};

const samples = new Map<string, Handles>();
const inflight = new Map<string, Promise<unknown>>();

function dedupe<T>(key: string, fn: () => Promise<T>): Promise<T> {
  const cur = inflight.get(key) as Promise<T> | undefined;
  if (cur) return cur;
  const p = fn().finally(() => inflight.delete(key));
  inflight.set(key, p);
  return p;
}

async function fetchJSON<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${url}`);
  return (await r.json()) as T;
}

const api = {
  async openSample(datasetUrl: string, sampleId: string): Promise<{ nGenes: number; genes: string[] }> {
    return dedupe(`open:${sampleId}`, async () => {
      const existing = samples.get(sampleId);
      if (existing) return { nGenes: existing.genes.length, genes: existing.genes };
      const base = `${datasetUrl.replace(/\/$/, "")}/samples/${sampleId}`;
      const exprStore = new zarr.FetchStore(`${base}/expr.zarr`);
      const exprRoot = zarr.root(exprStore);
      const [u8, gmaxArr, genes, obs] = await Promise.all([
        zarr.open.v3(exprRoot.resolve("u8"), { kind: "array" }) as Promise<U8Array>,
        zarr.open.v3(exprRoot.resolve("gmax"), { kind: "array" }),
        fetchJSON<string[]>(`${base}/genes.json`),
        zarr.open.v3(zarr.root(new zarr.FetchStore(`${base}/obs.zarr`)), { kind: "group" }),
      ]);
      const gmaxChunk = await zarr.get(gmaxArr as zarr.Array<"float32", zarr.FetchStore>);
      const h: Handles = {
        base,
        u8,
        gmax: new Float32Array(gmaxChunk.data as Float32Array),
        genes,
        geneIndex: new Map(genes.map((g, i) => [g, i])),
        obs: obs as zarr.Group<zarr.FetchStore>,
        cat: new Map(),
        num: new Map(),
      };
      samples.set(sampleId, h);
      return { nGenes: genes.length, genes };
    });
  },

  /** Positions plus a KDBush index over them. Both buffers are transferred (the worker keeps nothing). */
  async getXYAndIndex(sampleId: string): Promise<{ xy: Float32Array; index: ArrayBuffer }> {
    const h = samples.get(sampleId)!;
    const arr = await zarr.open.v3(h.obs.resolve("xy"), { kind: "array" });
    const chunk = await zarr.get(arr as zarr.Array<"float32", zarr.FetchStore>);
    const xy = new Float32Array(chunk.data as Float32Array);
    const n = xy.length / 2;
    const idx = new KDBush(n, 64, Float32Array);
    for (let i = 0; i < n; i++) idx.add(xy[i * 2], xy[i * 2 + 1]);
    idx.finish();
    const index = idx.data as ArrayBuffer;
    return Comlink.transfer({ xy, index }, [xy.buffer, index]);
  },

  geneIndex(sampleId: string, gene: string): number {
    return samples.get(sampleId)?.geneIndex.get(gene) ?? -1;
  },

  gmax(sampleId: string, geneIdx: number): number {
    return samples.get(sampleId)?.gmax[geneIdx] ?? 0;
  },

  /** uint8 column for one gene; one HTTP range request on sharded stores. */
  async getGene(sampleId: string, geneIdx: number): Promise<Uint8Array> {
    const h = samples.get(sampleId);
    if (!h) throw new Error(`sample ${sampleId} not open`);
    const chunk = await zarr.get(h.u8, [geneIdx, null]);
    const data = chunk.data as Uint8Array;
    const out = data.byteOffset === 0 && data.byteLength === data.buffer.byteLength ? data : new Uint8Array(data);
    return Comlink.transfer(out, [out.buffer]);
  },

  async getCategorical(sampleId: string, field: string): Promise<Uint16Array> {
    const h = samples.get(sampleId)!;
    const arr = await zarr.open.v3(h.obs.resolve(`cat/${field}`), { kind: "array" });
    const chunk = await zarr.get(arr as zarr.Array<"uint16", zarr.FetchStore>);
    const out = new Uint16Array(chunk.data as Uint16Array);
    return Comlink.transfer(out, [out.buffer]);
  },

  async getContinuous(sampleId: string, field: string): Promise<Float32Array> {
    const h = samples.get(sampleId)!;
    const arr = await zarr.open.v3(h.obs.resolve(`num/${field}`), { kind: "array" });
    const chunk = await zarr.get(arr as zarr.Array<"float32", zarr.FetchStore>);
    const out = new Float32Array(chunk.data as Float32Array);
    return Comlink.transfer(out, [out.buffer]);
  },

  async getIds(sampleId: string, block: number): Promise<string[]> {
    const h = samples.get(sampleId)!;
    return dedupe(`ids:${sampleId}:${block}`, () => fetchJSON<string[]>(`${h.base}/ids/${block}.json`));
  },

  /** Cell boundary polygons: decode int16 centroid deltas into absolute µm positions + start indices. */
  async getPolygons(sampleId: string, xy: Float32Array, scale: number): Promise<{ positions: Float32Array; startIndices: Uint32Array }> {
    const h = samples.get(sampleId)!;
    const [offBuf, dBuf] = await Promise.all([
      fetch(`${h.base}/polygons.offsets.u32`).then((r) => r.arrayBuffer()),
      fetch(`${h.base}/polygons.i16`).then((r) => r.arrayBuffer()),
    ]);
    const offsets = new Uint32Array(offBuf);
    const deltas = new Int16Array(dBuf);
    const n = offsets.length - 1;
    const nv = deltas.length / 2;
    // closed loops: repeat the first vertex so PathLayer draws the last edge
    const positions = new Float32Array((nv + n) * 2);
    const startIndices = new Uint32Array(n + 1);
    let w = 0;
    for (let i = 0; i < n; i++) {
      startIndices[i] = w;
      const a = offsets[i];
      const b = offsets[i + 1];
      if (b <= a) continue;
      const cx = xy[i * 2];
      const cy = xy[i * 2 + 1];
      for (let v = a; v < b; v++) {
        positions[w * 2] = cx + deltas[v * 2] * scale;
        positions[w * 2 + 1] = cy + deltas[v * 2 + 1] * scale;
        w++;
      }
      positions[w * 2] = cx + deltas[a * 2] * scale;
      positions[w * 2 + 1] = cy + deltas[a * 2 + 1] * scale;
      w++;
    }
    startIndices[n] = w;
    const out = { positions: positions.subarray(0, w * 2).slice(), startIndices };
    return Comlink.transfer(out, [out.positions.buffer, out.startIndices.buffer]);
  },

  /** 64-bin histogram of a uint8 column (for filter UI). */
  histogram(values: Uint8Array | Float32Array, bins = 64, min = 0, max = 1): number[] {
    const out = new Array<number>(bins).fill(0);
    const scale = values instanceof Uint8Array ? 1 / 255 : 1;
    for (let i = 0; i < values.length; i++) {
      const v = values[i] * scale;
      if (!Number.isFinite(v)) continue;
      let b = Math.floor(((v - min) / (max - min)) * bins);
      if (b < 0) b = 0;
      if (b >= bins) b = bins - 1;
      out[b]++;
    }
    return out;
  },
};

export type DataWorkerAPI = typeof api;
Comlink.expose(api);
