/**
 * Cell shapes in the viewer: which shape tiles each pane needs, whether it may draw them, fetching them only once
 * the camera has settled, a byte-budgeted cache, and the per-tile colour bytes gathered from the per-cell arrays
 * the dots already use (so a gene or annotation change recolours shapes without any download).
 *
 * Rules: shapes appear once a cell is at least SHAPE_GATE_PX across, when the tiles in view hold at most
 * SHAPE_CELL_BUDGET cells for the pane and at most SHAPE_TILE_CAP tiles across all panes; otherwise the dots stay
 * and the status line says to zoom in. A sample whose visible tiles are all loaded shows shapes instead of dots.
 */
import { Matrix4 } from "@math.gl/core";
import { tilesInRect, tileKey, type ShapeIndex, type ShapeTile, type ShapeTileEntry } from "../data/shapeTiles";
import { ShapeEdgeLayer, ShapeFillLayer } from "../layers/ShapeLayers";
import type { CellColorProps } from "../layers/colorModule";
import { store, type CellShapes, type ViewerState, type ViewId } from "../store/store";
import type { LayoutResult } from "./layout";
import { intersects } from "./lod";
import { overlayProps, type SampleLayerInputs } from "./types";
import type { ViewerController } from "./ViewerController";

export const SHAPE_GATE_PX = 6;
export const SHAPE_CELL_BUDGET = 40_000;
export const SHAPE_TILE_CAP = 64;
const SETTLE_MS = 150;
const CACHE_BYTES = 128 * 2 ** 20;

type Attr = { value: ArrayBufferView; size: number };
interface Cached {
  key: string;
  tile: ShapeTile;
  used: number;
  bytes: number;
  from?: unknown; // the per-cell inputs the gathered bytes came from
  fill?: any;
  edge?: any;
}
export interface CellColor {
  props: CellColorProps;
  inputs: SampleLayerInputs & { value2?: { value: Uint8Array; size: number } };
}

/** The drawing mode a sample gets: "auto" fills cells unless an image is drawn under them. */
export function shapeMode(setting: CellShapes, imageShown: boolean): "dots" | "filled" | "edges" {
  if (setting !== "auto") return setting;
  return imageShown ? "edges" : "filled";
}

/** Per-vertex colour inputs, packed as the shape layers read them: value, value2, filter (and a spare byte) in one
 *  4-byte attribute, the category code in another. */
function gatherCells(inp: CellColor["inputs"], rows: Uint32Array): Record<string, Attr> {
  const n = rows.length;
  const out: Record<string, Attr> = {};
  const v = inp.value?.value;
  const v2 = inp.value2?.value;
  const f = inp.filter?.value;
  if (v || v2 || f) {
    const b = new Uint8Array(n * 4);
    for (let i = 0; i < n; i++) {
      const r = rows[i];
      if (v) b[i * 4] = v[r];
      if (v2) b[i * 4 + 1] = v2[r];
      if (f) b[i * 4 + 2] = f[r];
    }
    out.getCellBytes = { value: b, size: 4 };
  }
  const cat = inp.cat?.value;
  if (cat) {
    const c = new Uint16Array(n);
    for (let i = 0; i < n; i++) c[i] = cat[rows[i]];
    out.getCellCategory = { value: c, size: 1 };
  }
  return out;
}

export class ShapeManager {
  private indexes = new Map<string, { index: ShapeIndex; byKey: Map<string, ShapeTileEntry> } | "loading" | "error">();
  private cache = new Map<string, Cached>(); // `${sample}|${key}`
  private pending = new Set<string>();
  private bytes = 0;
  private rects = new Map<string, string>();
  private lastMove = 0;
  private timer: number | null = null;
  private tilesThisBuild = 0;
  private wanted = new Set<string>();
  private hint: string | null = null;
  private nextHint: string | null = null;

  constructor(private c: ViewerController) {}

  reset() {
    this.indexes.clear();
    this.cache.clear();
    this.pending.clear();
    this.bytes = 0;
    this.rects.clear();
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
    if (this.bytes > CACHE_BYTES) {
      const old = [...this.cache.entries()].filter(([k]) => !this.wanted.has(k)).sort((a, b) => a[1].used - b[1].used);
      for (const [k, v] of old) {
        if (this.bytes <= CACHE_BYTES * 0.8) break;
        this.cache.delete(k);
        this.bytes -= v.bytes;
      }
    }
    if (this.nextHint !== this.hint) {
      this.hint = this.nextHint;
      store.getState().set({ shapeHint: this.hint });
    }
  }

  private index(id: string) {
    const v = this.indexes.get(id);
    if (v && v !== "loading" && v !== "error") return v;
    if (!v) {
      this.indexes.set(id, "loading");
      this.c.cache.worker
        .shapeIndex(id)
        .then((index) => {
          this.indexes.set(id, { index, byKey: new Map(index.tiles.map((e) => [tileKey(e[0], e[1]), e])) });
          this.c.requestLayers();
        })
        .catch((e) => {
          console.warn(`cell shapes of ${id} unavailable:`, e);
          this.indexes.set(id, "error");
        });
    }
    return undefined;
  }

  private fetch(id: string, keys: string[]) {
    for (const k of keys) this.pending.add(`${id}|${k}`);
    store.getState().set({ pending: store.getState().pending + 1 });
    this.c.cache.worker
      .shapeTiles(id, keys)
      .then((tiles) => {
        const now = performance.now();
        for (const t of tiles) {
          const bytes = t.bytes * 2; // the gathered colour bytes and GPU copies roughly double it
          this.cache.set(`${id}|${t.key}`, { key: t.key, tile: t, used: now, bytes });
          this.bytes += bytes;
        }
      })
      .catch((e) => console.warn(`cell shape tiles of ${id} failed:`, e))
      .finally(() => {
        for (const k of keys) this.pending.delete(`${id}|${k}`);
        store.getState().set({ pending: Math.max(0, store.getState().pending - 1) });
        this.c.requestLayers();
      });
  }

  /**
   * One pane: the shape layers to draw and the samples whose dots they replace. `colorFor` gives a sample's colour
   * props and per-cell inputs (the same the dots use); `modeFor` its drawing mode.
   */
  pane(
    view: ViewId,
    L: LayoutResult,
    s: ViewerState,
    modeFor: (id: string) => "dots" | "filled" | "edges",
    colorFor: (id: string) => CellColor | undefined,
  ): { complete: Set<string>; layers: any[] } {
    const c = this.c;
    const out = { complete: new Set<string>(), layers: [] as any[] };
    const vb = c.viewBbox(view);
    const zoomScale = Math.pow(2, c.viewStates[view].zoom);
    const rectKey = vb.map((v) => v.toFixed(1)).join(",");
    if (this.rects.get(view) !== rectKey) {
      this.rects.set(view, rectKey);
      this.lastMove = performance.now();
    }
    type Want = { id: string; mode: "filled" | "edges"; matrix: any; tiles: ShapeTileEntry[] };
    const wants: Want[] = [];
    let cells = 0;
    for (const [id, p] of L.placements) {
      const smp = c.samplesById.get(id)!;
      if (!smp.shapes || !intersects(p.worldBbox, vb)) continue;
      const mode = modeFor(id);
      if (mode === "dots") continue;
      if (zoomScale * smp.pointRadius * 2 < SHAPE_GATE_PX) continue;
      if (!c.cache.samples.get(id)) continue;
      const ix = this.index(id);
      if (!ix) continue;
      const inv = new Matrix4(p.modelMatrix).invert();
      const corners = [
        [vb[0], vb[1]],
        [vb[2], vb[1]],
        [vb[0], vb[3]],
        [vb[2], vb[3]],
      ].map(([x, y]) => inv.transformAsPoint([x, y, 0]));
      const xs = corners.map((q) => q[0]);
      const ys = corners.map((q) => q[1]);
      const tiles = tilesInRect(ix.index, ix.byKey, [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)]);
      for (const t of tiles) cells += t[4];
      wants.push({ id, mode, matrix: p.modelMatrix, tiles });
    }
    const ntiles = wants.reduce((n, w) => n + w.tiles.length, 0);
    if (cells > SHAPE_CELL_BUDGET || this.tilesThisBuild + ntiles > SHAPE_TILE_CAP) {
      this.nextHint = "zoom in for cell shapes";
      return out;
    }
    this.tilesThisBuild += ntiles;
    const now = performance.now();
    const settled = now - this.lastMove >= SETTLE_MS;
    for (const w of wants) {
      const missing: string[] = [];
      const ready: Cached[] = [];
      for (const t of w.tiles) {
        const key = tileKey(t[0], t[1]);
        const ck = `${w.id}|${key}`;
        this.wanted.add(ck);
        const hit = this.cache.get(ck);
        if (hit) {
          hit.used = now;
          ready.push(hit);
        } else if (!this.pending.has(ck)) missing.push(key);
      }
      if (missing.length) {
        if (settled) this.fetch(w.id, missing);
        else if (this.timer == null) {
          this.timer = window.setTimeout(() => {
            this.timer = null;
            c.requestLayers();
          }, SETTLE_MS);
        }
      }
      const color = colorFor(w.id);
      if (!color) continue;
      if (ready.length === w.tiles.length) out.complete.add(w.id);
      for (const t of ready) out.layers.push(...this.tileLayers(view, w.id, w.mode, w.matrix, t, color));
    }
    return out;
  }

  private tileLayers(view: ViewId, id: string, mode: "filled" | "edges", matrix: any, t: Cached, color: CellColor) {
    const tile = t.tile;
    if (t.from !== color.inputs) {
      const attrs = gatherCells(color.inputs, tile.vertexRow);
      const n = tile.rows.length;
      t.edge = { length: n, startIndices: tile.startIndices, attributes: { getPath: { value: tile.positions, size: 2 }, ...attrs } };
      t.fill = { length: n, startIndices: tile.startIndices, attributes: { getPolygon: { value: tile.positions, size: 2 }, indices: tile.indices, ...attrs } };
      t.from = color.inputs;
    }
    const common = { ...overlayProps(view), modelMatrix: matrix, ...color.props };
    const tid = `${id}-${t.key}`;
    const layers: any[] = [];
    if (mode === "filled") {
      layers.push(
        new ShapeFillLayer({ ...common, id: `shape-fill-${tid}`, data: t.fill, _normalize: false, positionFormat: "XY", opacity: 0.85 } as any),
        new ShapeEdgeLayer({ ...common, id: `shape-edge-${tid}`, data: t.edge, _pathType: "open", shade: 0.55, getWidth: 1, widthUnits: "pixels", widthMinPixels: 0.75 } as any),
      );
    } else {
      layers.push(new ShapeEdgeLayer({ ...common, id: `shape-edge-${tid}`, data: t.edge, _pathType: "open", shade: 1, getWidth: 1.5, widthUnits: "pixels", widthMinPixels: 1 } as any));
    }
    return layers;
  }
}
