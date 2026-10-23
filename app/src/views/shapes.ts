/**
 * Cell shapes in the viewer: which shape tiles each pane needs, whether it may draw them, and the per-tile colour
 * bytes gathered from the per-cell arrays the dots already use (so a gene or annotation change recolours shapes
 * without any download). Fetching, caching and settling live in TileManager.
 *
 * Rules: shapes appear once a cell is at least SHAPE_GATE_PX across, when the tiles in view hold at most
 * SHAPE_CELL_BUDGET cells for the pane and at most TILE_CAP tiles across all panes; otherwise the dots stay and
 * the status line says to zoom in. A sample whose visible tiles are all loaded shows shapes instead of dots.
 */
import type { ShapeIndex, ShapeTile, ShapeTileEntry } from "../data/shapeTiles";
import { ShapeEdgeLayer, ShapeFillLayer } from "../layers/ShapeLayers";
import type { CellColorProps } from "../layers/colorModule";
import type { CellShapes, ViewerState, ViewId } from "../store/store";
import type { LayoutResult } from "./layout";
import { intersects } from "./lod";
import { TILE_CAP, TileManager, type Cached } from "./tileManager";
import { overlayProps, type SampleLayerInputs } from "./types";
import type { ViewerController } from "./ViewerController";

export const SHAPE_GATE_PX = 6;
export const SHAPE_CELL_BUDGET = 40_000;

type Attr = { value: ArrayBufferView; size: number };
interface ShapeCached extends Cached<ShapeTile> {
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

export class ShapeManager extends TileManager<ShapeIndex, ShapeTile> {
  constructor(c: ViewerController) {
    super(c, "shapes", 128 * 2 ** 20, "shapeHint");
  }

  protected load(id: string, keys: string[]) {
    return this.c.cache.worker.shapeTiles(id, keys);
  }

  protected reach(index: ShapeIndex) {
    return index.reach;
  }

  /**
   * One pane: the shape layers to draw and the samples whose dots they replace. `colorFor` gives a sample's colour
   * props and per-cell inputs (the same the dots use); `modeFor` its drawing mode.
   */
  pane(
    view: ViewId,
    L: LayoutResult,
    _s: ViewerState,
    modeFor: (id: string) => "dots" | "filled" | "edges",
    colorFor: (id: string) => CellColor | undefined,
  ): { complete: Set<string>; layers: any[] } {
    const c = this.c;
    const out = { complete: new Set<string>(), layers: [] as any[] };
    const vb = c.viewBbox(view);
    const zoomScale = Math.pow(2, c.viewStates[view].zoom);
    const settled = this.settled(view, vb);
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
      const tiles = this.tilesFor(ix, p.modelMatrix, vb) as ShapeTileEntry[];
      for (const t of tiles) cells += t[4];
      wants.push({ id, mode, matrix: p.modelMatrix, tiles });
    }
    const ntiles = wants.reduce((n, w) => n + w.tiles.length, 0);
    if (cells > SHAPE_CELL_BUDGET || this.tilesThisBuild + ntiles > TILE_CAP) {
      this.nextHint = "zoom in for cell shapes";
      return out;
    }
    this.tilesThisBuild += ntiles;
    for (const w of wants) {
      const { ready, complete } = this.resolve(w.id, w.tiles, settled);
      const color = colorFor(w.id);
      if (!color) continue;
      if (complete) out.complete.add(w.id);
      for (const t of ready) out.layers.push(...this.tileLayers(view, w.id, w.mode, w.matrix, t as ShapeCached, color));
    }
    return out;
  }

  private tileLayers(view: ViewId, id: string, mode: "filled" | "edges", matrix: any, t: ShapeCached, color: CellColor) {
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
