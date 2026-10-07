/** Lasso selection: drawing state, point-in-polygon, highlight layers, summary and CSV export. */
import { PathLayer, ScatterplotLayer } from "@deck.gl/layers";
import { Matrix4 } from "@math.gl/core";
import { store, type ViewId, type ViewerState } from "../store/store";
import { pointInPolygon } from "./geometry";
import type { LayoutResult } from "./layout";
import { intersects } from "./lod";
import { overlayProps } from "./types";
import type { ViewerController } from "./ViewerController";

export interface SelectionState {
  view: ViewId;
  samples: Map<string, Uint32Array>;
  highlight: Map<string, Float32Array>;
  polygon: [number, number][];
}

export class Selection {
  current: SelectionState | null = null;
  lassoPts: { view: ViewId; world: [number, number][] } | null = null;
  lassoActive = false;
  private version = 0;

  constructor(private c: ViewerController) {}

  begin(view: ViewId, world: [number, number]) {
    this.lassoActive = true;
    this.lassoPts = { view, world: [world] };
  }

  extend(view: ViewId, world: [number, number]): boolean {
    if (!this.lassoActive || !this.lassoPts || this.lassoPts.view !== view) return false;
    const last = this.lassoPts.world[this.lassoPts.world.length - 1];
    const scale = Math.pow(2, this.c.viewStates[view].zoom);
    if (Math.hypot(world[0] - last[0], world[1] - last[1]) * scale > 3) {
      this.lassoPts.world.push(world);
      this.c.requestLayers();
    }
    return true;
  }

  finish() {
    if (!this.lassoActive || !this.lassoPts) return;
    this.lassoActive = false;
    const { view, world } = this.lassoPts;
    this.lassoPts = null;
    if (world.length >= 3) this.apply(view, world);
    else this.c.requestLayers();
  }

  cancelDrawing() {
    this.lassoActive = false;
    this.lassoPts = null;
  }

  apply(view: ViewId, polygon: [number, number][]) {
    const c = this.c;
    const L = c.layouts[view];
    if (!L) return;
    const xs = polygon.map((p) => p[0]);
    const ys = polygon.map((p) => p[1]);
    const pb: [number, number, number, number] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    const samples = new Map<string, Uint32Array>();
    const highlight = new Map<string, Float32Array>();
    for (const [id, p] of L.placements) {
      if (!intersects(p.worldBbox, pb)) continue;
      const sd = c.cache.samples.get(id);
      if (!sd?.index) continue;
      const inv = new Matrix4(p.modelMatrix).invert();
      const local = polygon.map((pt) => inv.transformAsPoint([pt[0], pt[1], 0]).slice(0, 2) as [number, number]);
      const lx = local.map((q) => q[0]);
      const ly = local.map((q) => q[1]);
      const cand = sd.index.range(Math.min(...lx), Math.min(...ly), Math.max(...lx), Math.max(...ly));
      const sel: number[] = [];
      for (const i of cand) if (pointInPolygon(sd.xy[i * 2], sd.xy[i * 2 + 1], local)) sel.push(i);
      if (!sel.length) continue;
      samples.set(id, Uint32Array.from(sel));
      const hl = new Float32Array(sel.length * 2);
      for (let k = 0; k < sel.length; k++) {
        hl[k * 2] = sd.xy[sel[k] * 2];
        hl[k * 2 + 1] = sd.xy[sel[k] * 2 + 1];
      }
      highlight.set(id, hl);
    }
    this.current = { view, samples, highlight, polygon };
    this.version++;
    store.getState().set({ tool: "pan" });
    this.updateSummary();
    c.requestLayers();
  }

  clear() {
    this.current = null;
    store.getState().set({ selectionSummary: null });
    this.c.requestLayers();
  }

  /** Composition and gene stats of the current selection (recomputed as arrays arrive). */
  updateSummary() {
    const c = this.c;
    const sel = this.current;
    const s = store.getState();
    if (!sel || !c.manifest) return;
    const perSample: { id: string; name: string; n: number }[] = [];
    const fields: Record<string, { code: number; n: number }[]> = {};
    let total = 0;
    const fieldCounts: Record<string, Float64Array> = {};
    let gSum = 0;
    let gN = 0;
    let gPos = 0;
    let aSum = 0;
    let aN = 0;
    let aPos = 0;
    const gene = s.color?.kind === "gene" ? s.color.gene : null;
    for (const [id, idx] of sel.samples) {
      const sd = c.cache.samples.get(id)!;
      const smp = c.samplesById.get(id)!;
      perSample.push({ id, name: smp.name, n: idx.length });
      total += idx.length;
      for (const f of c.manifest.fields) {
        if (f.type !== "categorical" || !smp.fields.includes(f.id)) continue;
        const codes = sd.cat.get(f.id);
        if (!codes) {
          void c.cache.getCategorical(id, f.id).then(() => this.updateSummary());
          continue;
        }
        const n = c.manifest.vocabularies[f.vocabulary].categories.length;
        const acc = (fieldCounts[f.id] ??= new Float64Array(n));
        for (const i of idx) if (codes[i] < n) acc[codes[i]]++;
      }
      if (gene) {
        const g = c.cache.getGeneSync(id, gene)?.value;
        const gmax = c.geneGmax.get(`${id}:${gene}`);
        if (g && gmax !== undefined) {
          const k = gmax / 255;
          for (const i of idx) {
            gSum += g[i] * k;
            gN++;
            if (g[i] > 0) gPos++;
          }
          for (let i = 0; i < g.length; i++) {
            aSum += g[i] * k;
            aN++;
            if (g[i] > 0) aPos++;
          }
        }
      }
    }
    for (const [fid, acc] of Object.entries(fieldCounts)) {
      fields[fid] = [...acc].map((n, code) => ({ code, n })).filter((r) => r.n > 0).sort((a, b) => b.n - a.n);
    }
    s.set({
      selectionSummary: {
        version: this.version,
        total,
        perSample,
        fields,
        gene: gene && gN ? { name: c.interaction.featureLabel(gene), mean: gSum / gN, frac: gPos / gN, meanAll: aN ? aSum / aN : 0, fracAll: aN ? aPos / aN : 0 } : null,
      },
    });
  }

  /** Download the selected cell ids as CSV (sample, cell_id). */
  async exportCSV() {
    const c = this.c;
    const sel = this.current;
    if (!sel) return;
    const lines = ["sample,cell_id"];
    for (const [id, idx] of sel.samples) {
      const smp = c.samplesById.get(id)!;
      for (const i of idx) lines.push(`${id},${(await c.cache.getId(id, i, smp.idBlock)) ?? i}`);
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${c.manifest?.id ?? "selection"}-selection.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  layers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const c = this.c;
    const out: any[] = [];
    const common = overlayProps(view);
    if (this.lassoPts && this.lassoPts.view === view && this.lassoPts.world.length > 1) {
      out.push(
        new PathLayer({
          ...common,
          id: `lasso-draw-${view}`,
          data: [{ path: [...this.lassoPts.world, this.lassoPts.world[0]] }],
          getPath: (d: any) => d.path,
          getColor: [64, 196, 255, 230],
          getWidth: 1.5,
          widthUnits: "pixels",
          getDashArray: [4, 3],
          dashJustified: true,
        } as any),
      );
    }
    if (this.current && this.current.view === view) {
      for (const [id, hl] of this.current.highlight) {
        const p = L.placements.get(id);
        const smp = c.samplesById.get(id);
        if (!p || !smp) continue;
        out.push(
          new ScatterplotLayer({
            ...common,
            id: `sel-${id}`,
            data: { length: hl.length / 2, attributes: { getPosition: { value: hl, size: 2 } } } as any,
            modelMatrix: p.modelMatrix,
            radiusUnits: "common",
            getRadius: smp.pointRadius * s.pointScale * 1.35,
            radiusMinPixels: 2.5,
            radiusMaxPixels: 50,
            filled: false,
            stroked: true,
            getLineColor: [255, 255, 255, 230],
            lineWidthMinPixels: 1,
            lineWidthMaxPixels: 2,
          } as any),
        );
      }
      out.push(
        new PathLayer({
          ...common,
          id: `sel-poly-${view}`,
          data: [{ path: [...this.current.polygon, this.current.polygon[0]] }],
          getPath: (d: any) => d.path,
          getColor: [255, 255, 255, 170],
          getWidth: 1,
          widthUnits: "pixels",
          getDashArray: [4, 3],
          dashJustified: true,
        } as any),
      );
    }
    return out;
  }
}
