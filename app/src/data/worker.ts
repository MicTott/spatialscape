/// <reference lib="webworker" />
/**
 * Data worker: owns the zarr handles for every sample, fetches + decodes gene columns and
 * obs arrays, and builds KDBush spatial indexes. All big arrays are transferred, not copied.
 */
import { BigWig } from "@gmod/bbi";
import * as Comlink from "comlink";
import KDBush from "kdbush";
import * as zarr from "zarrita";
import { rasterize } from "../genome/raster";
import { decodeMoleculeTile, type MoleculeTile } from "./moleculeTiles";
import { decodeShapeTile, type ShapeTile } from "./shapeTiles";
import { coalesce, indexByKey, tileKey, type TileEntry, type TileIndexBase } from "./tileIndex";

type U8Array = zarr.Array<"uint8", zarr.FetchStore>;
type Handles = {
  base: string; // .../samples/<id>
  u8: U8Array;
  gmax: Float32Array;
  gmin: Float32Array; // 0 for non-negative features, -gmax for signed ones (older bundles: all 0)
  genes: string[];
  geneIndex: Map<string, number>;
  obs: zarr.Group<zarr.FetchStore>;
  cat: Map<string, Uint16Array>;
  num: Map<string, Float32Array>;
};

const samples = new Map<string, Handles>();
const inflight = new Map<string, Promise<unknown>>();
const bigwigs = new Map<string, BigWig>(); // genome-panel coverage tracks, by URL
type TileKind = string; // "shapes", "molecules", or a segmentation's "segmentations/<id>/shapes": the path under the sample
const tileIndexes = new Map<string, { index: TileIndexBase; byKey: Map<string, TileEntry> }>(); // `${kind}:${sampleId}`
let zstdCodec: Promise<{ decode(data: Uint8Array): Uint8Array | Promise<Uint8Array> }> | null = null;
function zstd() {
  zstdCodec ??= import("numcodecs/zstd").then((m) => m.default.fromConfig({ id: "zstd", level: 1 } as any));
  return zstdCodec;
}

/** A byte range of a packed file. A host that ignores Range answers 200 with the whole file: refuse that rather
 *  than download a whole section's shapes for one tile. */
async function fetchRange(url: string, start: number, length: number): Promise<Uint8Array> {
  const r = await fetch(url, { headers: { Range: `bytes=${start}-${start + length - 1}` } });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${url}`);
  if (r.status !== 206) {
    const len = Number(r.headers.get("Content-Length") ?? NaN);
    if (!(start === 0 && len === length)) {
      void r.body?.cancel();
      throw new Error(`the host ignored the byte range for ${url}; serve the bundle from a host that supports Range requests, or build it with --no-shard`);
    }
  }
  const b = new Uint8Array(await r.arrayBuffer());
  if (b.length !== length) throw new Error(`expected ${length} bytes from ${url}, got ${b.length}`);
  return b;
}

/** The decompressed frames of some tiles of a sample: [key, bytes, tile origin, index]. Adjacent tiles of a packed
 *  file come in one range request of at most 1 MB; the "files" layout fetches one file per tile. */
async function tileFrames(kind: TileKind, sampleId: string, keys: string[]): Promise<[string, Uint8Array, [number, number], TileIndexBase][]> {
  await api.tileIndex(kind, sampleId);
  const { index, byKey } = tileIndexes.get(`${kind}:${sampleId}`)!;
  const h = samples.get(sampleId)!;
  const entries = keys.map((k) => byKey.get(k)).filter((e): e is TileEntry => !!e);
  const codec = await zstd();
  const frames: [TileEntry, Uint8Array][] = [];
  if (index.layout === "packed") {
    const runs = coalesce(entries);
    const blobs = await Promise.all(runs.map((run) => fetchRange(`${h.base}/${kind}.bin`, run[0][2], run.reduce((n, e) => n + e[3], 0))));
    runs.forEach((run, i) => {
      let o = 0;
      for (const e of run) {
        frames.push([e, blobs[i].subarray(o, o + e[3])]);
        o += e[3];
      }
    });
  } else {
    const got = await Promise.all(
      entries.map((e) =>
        fetch(`${h.base}/${kind}/${tileKey(e[0], e[1])}.bin`).then(async (r) => {
          if (!r.ok) throw new Error(`${r.status} ${r.statusText} for ${r.url}`);
          return new Uint8Array(await r.arrayBuffer());
        }),
      ),
    );
    entries.forEach((e, i) => frames.push([e, got[i]]));
  }
  const out: [string, Uint8Array, [number, number], TileIndexBase][] = [];
  for (const [e, frame] of frames) {
    const raw = await codec.decode(frame);
    out.push([tileKey(e[0], e[1]), raw, [index.origin[0] + e[0] * index.tile, index.origin[1] + e[1] * index.tile], index]);
  }
  return out;
}

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
      let gmin = new Float32Array((gmaxChunk.data as Float32Array).length);
      try {
        const gminArr = await zarr.open.v3(exprRoot.resolve("gmin"), { kind: "array" });
        gmin = new Float32Array((await zarr.get(gminArr as zarr.Array<"float32", zarr.FetchStore>)).data as Float32Array);
      } catch (e) {
        // only a bundle built before signed features existed has no gmin array; anything else (a failed request, a
        // damaged array) must not pass as "every feature starts at 0"
        if (!(e instanceof zarr.NotFoundError)) throw e;
      }
      const h: Handles = {
        base,
        u8,
        gmax: new Float32Array(gmaxChunk.data as Float32Array),
        gmin,
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

  /** [min, max] a feature was quantized over: value = min + u8 / 255 * (max - min). */
  geneRange(sampleId: string, geneIdx: number): [number, number] {
    const h = samples.get(sampleId);
    return h ? [h.gmin[geneIdx] ?? 0, h.gmax[geneIdx] ?? 0] : [0, 0];
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
  /** Mean signal of a bigWig over `n` bins of `bin` bp from `start`, from the zoom level that is at least that fine
   *  (genome panel coverage). Unknown chromosomes and empty regions come back as zeros. */
  async bigwigBins(url: string, chrom: string, start: number, bin: number, n: number): Promise<Float32Array> {
    let bw = bigwigs.get(url);
    if (!bw) {
      bw = new BigWig({ url });
      bigwigs.set(url, bw);
    }
    const f = await bw.getFeaturesAsArrays(chrom, start, start + n * bin, { basesPerSpan: bin / 2 });
    const out = rasterize(f.starts, f.ends, f.scores, start, bin, n);
    return Comlink.transfer(out, [out.buffer]);
  },

  /** A sample's tile index (shapes.json or molecules.json). */
  async tileIndex(kind: TileKind, sampleId: string): Promise<TileIndexBase> {
    const hit = tileIndexes.get(`${kind}:${sampleId}`);
    if (hit) return hit.index;
    const h = samples.get(sampleId)!;
    return dedupe(`${kind}:${sampleId}`, async () => {
      const index = await fetchJSON<TileIndexBase>(`${h.base}/${kind}.json`);
      tileIndexes.set(`${kind}:${sampleId}`, { index, byKey: indexByKey(index.tiles) });
      return index;
    });
  },

  /** Decoded shape tiles by key ("ix_iy"): adjacent tiles of a packed file come in one range request of at most
   *  1 MB, are decompressed and triangulated here, and every array is transferred. */
  async shapeTiles(sampleId: string, keys: string[]): Promise<(ShapeTile & { key: string })[]> {
    const out: (ShapeTile & { key: string })[] = [];
    const transfer: ArrayBuffer[] = [];
    for (const [key, raw, origin, index] of await tileFrames("shapes", sampleId, keys)) {
      const t = decodeShapeTile(raw, origin, index.grid);
      out.push({ key, ...t });
      transfer.push(t.rows.buffer as ArrayBuffer, t.startIndices.buffer as ArrayBuffer, t.positions.buffer as ArrayBuffer, t.vertexRow.buffer as ArrayBuffer, t.indices.buffer as ArrayBuffer);
    }
    return Comlink.transfer(out, transfer);
  },

  /** Decoded tiles of another segmentation of the section (segmentations/<id>/shapes), the same format as shapes. */
  async segmentationTiles(segmentation: string, sampleId: string, keys: string[]): Promise<(ShapeTile & { key: string })[]> {
    const out: (ShapeTile & { key: string })[] = [];
    const transfer: ArrayBuffer[] = [];
    for (const [key, raw, origin, index] of await tileFrames(`segmentations/${segmentation}/shapes`, sampleId, keys)) {
      const t = decodeShapeTile(raw, origin, index.grid);
      out.push({ key, ...t });
      transfer.push(t.rows.buffer as ArrayBuffer, t.startIndices.buffer as ArrayBuffer, t.positions.buffer as ArrayBuffer, t.vertexRow.buffer as ArrayBuffer, t.indices.buffer as ArrayBuffer);
    }
    return Comlink.transfer(out, transfer);
  },

  /** Decoded molecule tiles by key, the same way. */
  async moleculeTiles(sampleId: string, keys: string[]): Promise<(MoleculeTile & { key: string })[]> {
    const out: (MoleculeTile & { key: string })[] = [];
    const transfer: ArrayBuffer[] = [];
    for (const [key, raw, origin, index] of await tileFrames("molecules", sampleId, keys)) {
      const t = decodeMoleculeTile(raw, origin, index.grid);
      out.push({ key, ...t });
      transfer.push(t.positions.buffer as ArrayBuffer, t.gene.buffer as ArrayBuffer, t.flags.buffer as ArrayBuffer, t.runs.buffer as ArrayBuffer, t.runStarts.buffer as ArrayBuffer);
    }
    return Comlink.transfer(out, transfer);
  },

  async getPolygons(sampleId: string, xy: Float32Array, scale: number): Promise<{ positions: Float32Array; startIndices: Uint32Array }> {
    const h = samples.get(sampleId)!;
    const ok = async (r: Response) => {
      if (!r.ok) throw new Error(`${r.status} for ${r.url}`);
      return r.arrayBuffer();
    };
    const [offBuf, dBuf] = await Promise.all([fetch(`${h.base}/polygons.offsets.u32`).then(ok), fetch(`${h.base}/polygons.i16`).then(ok)]);
    const offsets = new Uint32Array(offBuf);
    const deltas = new Int16Array(dBuf);
    const n = offsets.length - 1;
    const nv = deltas.length / 2;
    if (n !== xy.length / 2 || offsets[0] !== 0 || offsets[n] !== nv) throw new Error(`polygon files do not match the sample (${n} cells, ${offsets[n]} vs ${nv} vertices)`);
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
