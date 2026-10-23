/**
 * Another segmentation of a section (Xenium nuclei, a re-segmentation), drawn as dashed edges in one accent colour
 * over the cells, the image and the molecules, so two segmentations can be judged against each other. Its rings are
 * numbered, not tied to cells, so they carry no colour of their own. Same tiles, gate and fetching as cell shapes.
 */
import { PathLayer } from "@deck.gl/layers";
import { PathStyleExtension } from "@deck.gl/extensions";
import type { ShapeIndex, ShapeTile, ShapeTileEntry } from "../data/shapeTiles";
import type { ViewId } from "../store/store";
import type { LayoutResult } from "./layout";
import { intersects } from "./lod";
import { SHAPE_CELL_BUDGET, SHAPE_GATE_PX } from "./shapes";
import { TileManager, type Cached } from "./tileManager";
import { overlayProps } from "./types";
import type { ViewerController } from "./ViewerController";

export const OVERLAY_COLOR: [number, number, number] = [255, 176, 46]; // amber: apart from the pin colours and the colormaps
export const OVERLAY_HEX = "#ffb02e";
const DASH = new PathStyleExtension({ dash: true });

interface OverlayCached extends Cached<ShapeTile> {
  data?: any;
}

export class OverlayManager extends TileManager<ShapeIndex, ShapeTile> {
  constructor(
    c: ViewerController,
    readonly segmentation: string,
  ) {
    super(c, `segmentations/${segmentation}/shapes`, 64 * 2 ** 20, null);
  }

  protected load(id: string, keys: string[]) {
    return this.c.cache.worker.segmentationTiles(this.segmentation, id, keys);
  }

  protected reach(index: ShapeIndex) {
    return index.reach;
  }

  /** One pane: dashed edges of this segmentation for every sample that carries it. */
  pane(view: ViewId, L: LayoutResult): any[] {
    const c = this.c;
    const layers: any[] = [];
    const vb = c.viewBbox(view);
    const zoomScale = Math.pow(2, c.viewStates[view].zoom);
    const settled = this.settled(view, vb);
    const wants: { id: string; matrix: any; tiles: ShapeTileEntry[] }[] = [];
    let cells = 0;
    for (const [id, p] of L.placements) {
      const smp = c.samplesById.get(id)!;
      if (!smp.segmentations?.some((sg) => sg.id === this.segmentation) || !intersects(p.worldBbox, vb)) continue;
      if (zoomScale * smp.pointRadius * 2 < SHAPE_GATE_PX) continue;
      if (!c.cache.samples.get(id)) continue;
      const ix = this.index(id);
      if (!ix) continue;
      const tiles = this.tilesFor(ix, p.modelMatrix, vb) as ShapeTileEntry[];
      for (const t of tiles) cells += t[4];
      wants.push({ id, matrix: p.modelMatrix, tiles });
    }
    const ntiles = wants.reduce((n, w) => n + w.tiles.length, 0);
    if (cells > SHAPE_CELL_BUDGET || this.tilesThisBuild + ntiles > this.tileCap) return layers;
    this.tilesThisBuild += ntiles;
    for (const w of wants) {
      const { ready } = this.resolve(w.id, w.tiles, settled);
      for (const t of ready as OverlayCached[]) {
        t.data ??= { length: t.tile.rows.length, startIndices: t.tile.startIndices, attributes: { getPath: { value: t.tile.positions, size: 2 } } };
        layers.push(
          new PathLayer({
            ...overlayProps(view),
            id: `overlay-${this.segmentation}-${w.id}-${t.key}`,
            data: t.data,
            _pathType: "open",
            modelMatrix: w.matrix,
            getColor: [...OVERLAY_COLOR, 235],
            getWidth: 1.5,
            widthUnits: "pixels",
            widthMinPixels: 1,
            getDashArray: [5, 3],
            dashJustified: false,
            extensions: [DASH],
          } as any),
        );
      }
    }
    return layers;
  }
}
