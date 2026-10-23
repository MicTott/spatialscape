/**
 * Molecules in the viewer: which tiles each pane needs, whether it may draw them, and the per-gene colours that
 * make molecules follow the colour on screen. Fetching, caching and settling live in TileManager.
 *
 * The gate is screen density, not zoom: molecules draw when the molecules that would be visible come to at most
 * MOLECULE_DENSITY per screen pixel of the pane (estimated from the index: a gene's share of the sample times the
 * molecules of the tiles in view) and at most MOLECULE_CAP across every pane; otherwise the status line says to zoom
 * in. Colour: the gene on screen draws in the colormap's top colour, a blend's two gene sets in the blend's colours,
 * and with an annotation (or nothing) on screen every molecule draws in grey, the view for judging a segmentation.
 */
import type { MoleculeIndex, MoleculeTile, MoleculeTileEntry } from "../data/moleculeTiles";
import { MoleculeLayer } from "../layers/MoleculeLayer";
import { BLEND_SCHEMES, COLORMAPS, effectiveColormap, hexToRGB } from "../layers/lut";
import type { ViewerState, ViewId } from "../store/store";
import type { LayoutResult } from "./layout";
import { intersects } from "./lod";
import { TILE_CAP, TileManager, type Cached } from "./tileManager";
import { overlayProps } from "./types";
import type { ViewerController } from "./ViewerController";

export const MOLECULE_DENSITY = 0.1; // visible molecules per CSS pixel of the pane
export const MOLECULE_CAP = 2_000_000; // molecules held for drawing across every pane
const GREY: [number, number, number] = [205, 208, 214];

interface MoleculeCached extends Cached<MoleculeTile> {
  data?: any;
}

/** Which genes draw, and in what colour, for the colour state on screen. */
export function geneColors(genes: string[], s: Pick<ViewerState, "color" | "colormap" | "geneMin">): { colors: Uint8Array; shares: (counts: number[]) => number } {
  const n = genes.length;
  const out = new Uint8Array(Math.max(1, n) * 4);
  const paint = (i: number, rgb: [number, number, number]) => {
    out[i * 4] = rgb[0];
    out[i * 4 + 1] = rgb[1];
    out[i * 4 + 2] = rgb[2];
    out[i * 4 + 3] = 255;
  };
  const color = s.color;
  if (color?.kind === "gene") {
    const i = genes.indexOf(color.gene);
    const cm = COLORMAPS[effectiveColormap(s.colormap, s.geneMin < 0)] ?? COLORMAPS.viridis;
    if (i >= 0) paint(i, cm(1).map((v) => Math.max(0, Math.min(255, Math.round(v * 255)))) as [number, number, number]); // colormaps return 0..1
    return { colors: out, shares: (counts) => (i >= 0 ? counts[i] : 0) / Math.max(1, counts.reduce((a, b) => a + b, 0)) };
  }
  if (color?.kind === "blend") {
    const scheme = BLEND_SCHEMES[color.scheme] ?? BLEND_SCHEMES.yb;
    const a = new Set(color.a);
    const b = new Set(color.b);
    const picked: number[] = [];
    genes.forEach((g, i) => {
      const inA = a.has(g);
      const inB = b.has(g);
      if (!inA && !inB) return;
      paint(i, hexToRGB(inA && inB ? scheme.both : inA ? scheme.a : scheme.b));
      picked.push(i);
    });
    return { colors: out, shares: (counts) => picked.reduce((acc, i) => acc + counts[i], 0) / Math.max(1, counts.reduce((x, y) => x + y, 0)) };
  }
  for (let i = 0; i < n; i++) paint(i, GREY);
  return { colors: out, shares: () => 1 };
}

export class MoleculeManager extends TileManager<MoleculeIndex, MoleculeTile> {
  private colorCache: { genes: string[]; key: string; value: ReturnType<typeof geneColors> } | null = null;

  constructor(c: ViewerController) {
    super(c, "molecules", 256 * 2 ** 20, "moleculeHint");
  }

  protected load(id: string, keys: string[]) {
    return this.c.cache.worker.moleculeTiles(id, keys);
  }

  private colorsFor(genes: string[], s: ViewerState) {
    const key = JSON.stringify([s.color, s.colormap, s.geneMin < 0]);
    if (!this.colorCache || this.colorCache.genes !== genes || this.colorCache.key !== key) this.colorCache = { genes, key, value: geneColors(genes, s) };
    return this.colorCache.value;
  }

  /** One pane: the molecule layers to draw and the samples whose dots should fade under them. */
  pane(view: ViewId, L: LayoutResult, s: ViewerState): { drawn: Set<string>; layers: any[] } {
    const c = this.c;
    const out = { drawn: new Set<string>(), layers: [] as any[] };
    if (!s.molecules) return out;
    const vb = c.viewBbox(view);
    const [vw, vh] = c.viewSize(view);
    const settled = this.settled(view, vb);
    type Want = { id: string; matrix: any; tiles: MoleculeTileEntry[]; index: MoleculeIndex; colors: ReturnType<typeof geneColors> };
    const wants: Want[] = [];
    let visible = 0;
    let held = 0;
    for (const [id, p] of L.placements) {
      const smp = c.samplesById.get(id)!;
      if (!smp.molecules || !intersects(p.worldBbox, vb) || !c.cache.samples.get(id)) continue;
      const ix = this.index(id);
      if (!ix) continue;
      const rect = this.sampleRect(p.modelMatrix, vb);
      const tiles = this.tilesFor(ix, p.modelMatrix, vb) as MoleculeTileEntry[];
      if (!tiles.length) continue;
      const colors = this.colorsFor(ix.index.genes, s);
      // what the pane would show: each tile's molecules by the share of the tile inside the view
      const inView = tiles.reduce((n, t) => n + t[4] * this.overlap(ix.index, t, rect), 0);
      held += tiles.reduce((n, t) => n + t[4], 0);
      visible += inView * colors.shares(ix.index.counts);
      wants.push({ id, matrix: p.modelMatrix, tiles, index: ix.index, colors });
    }
    if (!wants.length) return out;
    const ntiles = wants.reduce((n, w) => n + w.tiles.length, 0);
    if (visible > MOLECULE_DENSITY * vw * vh || held > MOLECULE_CAP || this.tilesThisBuild + ntiles > TILE_CAP) {
      this.nextHint = "zoom in for molecules";
      return out;
    }
    this.tilesThisBuild += ntiles;
    for (const w of wants) {
      const { ready } = this.resolve(w.id, w.tiles, settled);
      if (ready.length) out.drawn.add(w.id);
      for (const t of ready as MoleculeCached[]) {
        t.data ??= { length: t.tile.n, attributes: { getPosition: { value: t.tile.positions, size: 2 }, getGene: { value: t.tile.gene, size: 1 }, getFlags: { value: t.tile.flags, size: 1 } } };
        out.layers.push(
          new MoleculeLayer({
            ...overlayProps(view),
            id: `mol-${w.id}-${t.key}`,
            data: t.data,
            modelMatrix: w.matrix,
            geneColors: w.colors.colors,
            radiusUnits: "pixels",
            getRadius: 1.6,
            radiusMinPixels: 1,
            stroked: false,
            filled: true,
            antialiasing: true,
            opacity: 0.95,
          } as any),
        );
      }
    }
    return out;
  }
}
