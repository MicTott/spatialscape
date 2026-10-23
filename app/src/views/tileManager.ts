/**
 * Spatial tiles in the viewer, shared by cell shapes and molecules: the index per sample, fetching only once the
 * camera has settled, a byte-budgeted cache, in-flight bookkeeping that survives dataset switches, and a status
 * hint. A subclass decides which tiles a pane needs and whether it may draw them, and builds the layers.
 */
import { Matrix4 } from "@math.gl/core";
import { tilesInRect, tileKey, indexByKey, type TileEntry, type TileIndexBase } from "../data/tileIndex";
import { store, type ViewId } from "../store/store";
import type { ViewerController } from "./ViewerController";

export const SETTLE_MS = 150; // the camera must be still this long before tiles are requested
export const TILE_CAP = 64; // tiles of one kind drawn at once across every pane

export interface Cached<T> {
  key: string;
  tile: T;
  used: number;
  bytes: number;
}

type Loaded<I> = { index: I; byKey: Map<string, TileEntry> };

export abstract class TileManager<I extends TileIndexBase, T extends { bytes: number }> {
  private indexes = new Map<string, Loaded<I> | "loading" | "error">();
  protected cache = new Map<string, Cached<T>>(); // `${sample}|${key}`
  private pending = new Set<string>();
  private bytes = 0;
  private rects = new Map<string, string>();
  private lastMove = 0;
  private timer: number | null = null;
  private wanted = new Set<string>();
  private hint: string | null = null;
  protected nextHint: string | null = null;
  protected tilesThisBuild = 0;
  private gen = 0; // bumped by reset(): a fetch started for the previous dataset must not land in this one
  private inflight = 0; // fetches counted in store.pending, to give back on reset (a disposed worker never settles)

  constructor(
    protected c: ViewerController,
    private kind: "shapes" | "molecules",
    private cacheBytes: number,
    private hintKey: "shapeHint" | "moleculeHint",
  ) {}

  /** Loads one sample's tiles by key from the worker. */
  protected abstract load(id: string, keys: string[]): Promise<(T & { key: string })[]>;
  /** How far outside a view rectangle a tile may still contribute (shapes: the longest ring radius). */
  protected reach(_index: I): number {
    return 0;
  }

  reset() {
    this.gen++;
    this.indexes.clear();
    this.cache.clear();
    this.pending.clear();
    this.bytes = 0;
    this.rects.clear();
    if (this.inflight) store.getState().set({ pending: Math.max(0, store.getState().pending - this.inflight) });
    this.inflight = 0;
    if (this.timer != null) window.clearTimeout(this.timer);
    this.timer = null;
  }

  beginBuild() {
    this.tilesThisBuild = 0;
    this.wanted = new Set();
    this.nextHint = null;
  }

  /** After every pane: evict beyond the budget, and publish the status hint when it changed. */
  endBuild() {
    if (this.bytes > this.cacheBytes) {
      const old = [...this.cache.entries()].filter(([k]) => !this.wanted.has(k)).sort((a, b) => a[1].used - b[1].used);
      for (const [k, v] of old) {
        if (this.bytes <= this.cacheBytes * 0.8) break;
        this.cache.delete(k);
        this.bytes -= v.bytes;
      }
    }
    if (this.nextHint !== this.hint) {
      this.hint = this.nextHint;
      store.getState().set({ [this.hintKey]: this.hint } as any);
    }
  }

  /** The sample's index, or undefined while it loads (a rebuild is requested when it arrives) or after it failed. */
  protected index(id: string): Loaded<I> | undefined {
    const v = this.indexes.get(id);
    if (v && v !== "loading" && v !== "error") return v;
    if (!v) {
      this.indexes.set(id, "loading");
      const gen = this.gen;
      this.c.cache.worker
        .tileIndex(this.kind, id)
        .then((index) => {
          if (gen !== this.gen) return;
          this.indexes.set(id, { index: index as I, byKey: indexByKey(index.tiles) });
          this.c.requestLayers();
        })
        .catch((e) => {
          if (gen !== this.gen) return;
          console.warn(`${this.kind} of ${id} unavailable:`, e);
          this.indexes.set(id, "error");
        });
    }
    return undefined;
  }

  /** A pane's view rectangle in a placed sample's own frame. */
  protected sampleRect(modelMatrix: unknown, vb: [number, number, number, number]): [number, number, number, number] {
    const inv = new Matrix4(modelMatrix as Matrix4).invert();
    const corners = [
      [vb[0], vb[1]],
      [vb[2], vb[1]],
      [vb[0], vb[3]],
      [vb[2], vb[3]],
    ].map(([x, y]) => inv.transformAsPoint([x, y, 0]));
    const xs = corners.map((q) => q[0]);
    const ys = corners.map((q) => q[1]);
    return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
  }

  /** The tiles a pane's view rectangle needs from a placed sample. */
  protected tilesFor(ix: Loaded<I>, modelMatrix: unknown, vb: [number, number, number, number]): TileEntry[] {
    return tilesInRect(ix.index, ix.byKey, this.sampleRect(modelMatrix, vb), this.reach(ix.index));
  }

  /** The share of a tile's area inside a rectangle of the sample frame. */
  protected overlap(index: I, e: TileEntry, rect: [number, number, number, number]): number {
    const x0 = index.origin[0] + e[0] * index.tile;
    const y0 = index.origin[1] + e[1] * index.tile;
    const w = Math.min(x0 + index.tile, rect[2]) - Math.max(x0, rect[0]);
    const h = Math.min(y0 + index.tile, rect[3]) - Math.max(y0, rect[1]);
    return w <= 0 || h <= 0 ? 0 : (w * h) / (index.tile * index.tile);
  }

  /** Record the pane's view; true when the camera has been still for SETTLE_MS. */
  protected settled(view: ViewId, vb: [number, number, number, number]): boolean {
    const rectKey = vb.map((v) => v.toFixed(1)).join(",");
    if (this.rects.get(view) !== rectKey) {
      this.rects.set(view, rectKey);
      this.lastMove = performance.now();
    }
    return performance.now() - this.lastMove >= SETTLE_MS;
  }

  /**
   * The cached tiles among `tiles` (marked as wanted this build); the missing ones are fetched when the camera has
   * settled, or a rebuild is scheduled for when it has. `complete` is true when every tile is cached.
   */
  protected resolve(id: string, tiles: TileEntry[], settled: boolean): { ready: Cached<T>[]; complete: boolean } {
    const now = performance.now();
    const missing: string[] = [];
    const ready: Cached<T>[] = [];
    for (const t of tiles) {
      const key = tileKey(t[0], t[1]);
      const ck = `${id}|${key}`;
      this.wanted.add(ck);
      const hit = this.cache.get(ck);
      if (hit) {
        hit.used = now;
        ready.push(hit);
      } else if (!this.pending.has(ck)) missing.push(key);
    }
    if (missing.length) {
      if (settled) this.fetch(id, missing);
      else if (this.timer == null) {
        this.timer = window.setTimeout(() => {
          this.timer = null;
          this.c.requestLayers();
        }, SETTLE_MS);
      }
    }
    return { ready, complete: ready.length === tiles.length };
  }

  private fetch(id: string, keys: string[]) {
    const gen = this.gen;
    for (const k of keys) this.pending.add(`${id}|${k}`);
    this.inflight++;
    store.getState().set({ pending: store.getState().pending + 1 });
    this.load(id, keys)
      .then((tiles) => {
        if (gen !== this.gen) return; // another dataset by now
        const now = performance.now();
        for (const t of tiles) {
          const bytes = t.bytes * 2; // the derived attribute arrays and GPU copies roughly double it
          this.cache.set(`${id}|${t.key}`, { key: t.key, tile: t, used: now, bytes });
          this.bytes += bytes;
        }
      })
      .catch((e) => {
        if (gen !== this.gen) return;
        // the sample goes without for good: retrying would loop on a host that cannot serve the tiles
        console.warn(`${this.kind} of ${id} unavailable:`, e);
        this.indexes.set(id, "error");
      })
      .finally(() => {
        if (gen !== this.gen) return; // reset() already gave the pending count back
        for (const k of keys) this.pending.delete(`${id}|${k}`);
        this.inflight--;
        store.getState().set({ pending: Math.max(0, store.getState().pending - 1) });
        this.c.requestLayers();
      });
  }
}
