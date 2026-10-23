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
import { TileManager, type Cached } from "./tileManager";
import { overlayProps } from "./types";
import type { ViewerController } from "./ViewerController";

// Measured on an M1 Max: a frame costs about 9 us per 1,000 molecules (0.78 M in 8.6 ms, 1.7 M in 16 ms, 3.5 M in
// 30 ms), and a base M1 is about three times slower, so a million keeps every laptop near 60 fps.
export const MOLECULE_DENSITY = 1.0; // visible molecules per CSS pixel of the pane (a 1440 x 900 window: about 1 M)
export const MOLECULE_CAP = 1_500_000; // molecules held for drawing across every pane
export const MOLECULE_TILE_CAP = 512; // 128 um tiles of a dense section hold about 3-5k molecules each
const GREY: [number, number, number] = [205, 208, 214];
/** Colours of pinned genes, in pin order: six apart from each other, from grey and from the colormaps' top colours,
 *  then hues spaced by the golden angle, which stay as different from each other as a long list allows. */
export const PIN_COLORS = ["#ff4fd8", "#3fe0e0", "#ff6b4f", "#3fd14a", "#4c8dff", "#f0f0f0"];
export const pinColor = (i: number) => (i < PIN_COLORS.length ? PIN_COLORS[i] : hslHex((i * 137.508 + 40) % 360, 0.8, 0.62));
/** One colour per gene for the all-genes view: a rainbow by gene index. */
export const geneHue = (i: number): [number, number, number] => hslRGB((i * 137.508) % 360, 0.72, 0.6);

function hslRGB(h: number, s: number, l: number): [number, number, number] {
  const k = (n: number) => (n + h / 30) % 12;
  const a = s * Math.min(l, 1 - l);
  const f = (n: number) => l - a * Math.max(-1, Math.min(k(n) - 3, 9 - k(n), 1));
  return [Math.round(f(0) * 255), Math.round(f(8) * 255), Math.round(f(4) * 255)];
}
function hslHex(h: number, s: number, l: number): string {
  return "#" + hslRGB(h, s, l).map((v) => v.toString(16).padStart(2, "0")).join("");
}

/** The colour the gene on screen gets: the top of the colormap in use. */
export function onScreenColor(s: Pick<ViewerState, "colormap" | "geneMin">): [number, number, number] {
  const cm = COLORMAPS[effectiveColormap(s.colormap, s.geneMin < 0)] ?? COLORMAPS.viridis;
  return cm(1).map((v) => Math.max(0, Math.min(255, Math.round(v * 255)))) as [number, number, number]; // colormaps return 0..1
}

interface MoleculeCached extends Cached<MoleculeTile> {
  data?: any;
}

/** Which genes draw, and in what colour, for the colour state on screen: the gene on screen in the colormap's top
 *  colour (a blend's sets in its colours), every pinned gene in its pin colour, and under an annotation every other
 *  gene in grey. `shares` gives the fraction of a sample's molecules that would draw, for the density gate. */
export function geneColors(genes: string[], s: Pick<ViewerState, "color" | "colormap" | "geneMin" | "moleculeGenes"> & { moleculeColors?: "follow" | "all" }): { colors: Uint8Array; shares: (counts: number[]) => number } {
  const n = genes.length;
  const out = new Uint8Array(Math.max(1, n) * 4);
  const picked = new Set<number>();
  const paint = (i: number, rgb: [number, number, number]) => {
    out[i * 4] = rgb[0];
    out[i * 4 + 1] = rgb[1];
    out[i * 4 + 2] = rgb[2];
    out[i * 4 + 3] = 255;
    picked.add(i);
  };
  const color = s.color;
  let all = false;
  if (s.moleculeColors === "all") {
    all = true;
    for (let i = 0; i < n; i++) paint(i, geneHue(i));
  }
  if (color?.kind === "gene") {
    const i = genes.indexOf(color.gene);
    if (i >= 0) paint(i, onScreenColor(s));
  } else if (color?.kind === "blend") {
    const scheme = BLEND_SCHEMES[color.scheme] ?? BLEND_SCHEMES.yb;
    const a = new Set(color.a);
    const b = new Set(color.b);
    genes.forEach((g, i) => {
      const inA = a.has(g);
      const inB = b.has(g);
      if (inA || inB) paint(i, hexToRGB(inA && inB ? scheme.both : inA ? scheme.a : scheme.b));
    });
  } else if (!all) {
    all = true;
    for (let i = 0; i < n; i++) paint(i, GREY);
  }
  (s.moleculeGenes ?? []).forEach((g, k) => {
    const i = genes.indexOf(g);
    if (i >= 0) paint(i, hexToRGB(pinColor(k)));
  });
  if (all) return { colors: out, shares: () => 1 };
  const idx = [...picked];
  return { colors: out, shares: (counts) => idx.reduce((acc, i) => acc + counts[i], 0) / Math.max(1, counts.reduce((x, y) => x + y, 0)) };
}

export class MoleculeManager extends TileManager<MoleculeIndex, MoleculeTile> {
  private colorCache = new WeakMap<string[], { key: string; value: ReturnType<typeof geneColors> }>(); // per sample's gene list
  private heldThisBuild = 0; // molecules held for drawing across every pane of one build

  constructor(c: ViewerController) {
    super(c, "molecules", 256 * 2 ** 20, "moleculeHint", MOLECULE_TILE_CAP);
  }

  protected load(id: string, keys: string[]) {
    return this.c.cache.worker.moleculeTiles(id, keys);
  }

  private colorsFor(genes: string[], s: ViewerState) {
    const key = JSON.stringify([s.color, s.colormap, s.geneMin < 0, s.moleculeGenes, s.moleculeColors]);
    const hit = this.colorCache.get(genes);
    if (hit && hit.key === key) return hit.value; // the same array identity keeps every tile layer's texture
    const value = geneColors(genes, s);
    this.colorCache.set(genes, { key, value });
    return value;
  }

  beginBuild() {
    super.beginBuild();
    this.heldThisBuild = 0;
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
    if (visible > MOLECULE_DENSITY * vw * vh || this.heldThisBuild + held > MOLECULE_CAP || this.tilesThisBuild + ntiles > this.tileCap) {
      this.nextHint = "zoom in for molecules";
      return out;
    }
    this.tilesThisBuild += ntiles;
    this.heldThisBuild += held;
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
            getRadius: 1.6 * s.moleculeSize,
            radiusMinPixels: 0.75,
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
