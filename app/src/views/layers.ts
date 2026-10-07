/** Builds the deck.gl layer list from the store state and the caches. Nothing here mutates state. */
import { PathLayer, TextLayer } from "@deck.gl/layers";
import type { SampleData } from "../data/cache";
import { fieldById } from "../data/manifest";
import { ExpressionScatterLayer } from "../layers/ExpressionScatterLayer";
import { imageLayer, loadImage, type ImageHandle } from "../layers/imageLayers";
import { blendLUT, categoryPalette, colormapLUT, hexToRGB } from "../layers/lut";
import { store, type ViewId, type ViewerState } from "../store/store";
import type { LayoutResult } from "./layout";
import { drawCount, intersects } from "./lod";
import { filterRange, overlayProps, VIEWS, type SampleLayerInputs } from "./types";
import type { ViewerController } from "./ViewerController";

export class LayerBuilder {
  private imageHandles = new Map<string, ImageHandle | "loading" | "error">();
  private inputs = new Map<string, SampleLayerInputs>();
  private lutCache = new Map<string, Uint8Array>();
  private paletteCache = new Map<string, Uint8Array>();

  constructor(private c: ViewerController) {}

  private lut(name: string): Uint8Array {
    let l = this.lutCache.get(name);
    if (!l) {
      l = name.startsWith("blend:") ? blendLUT(name.slice(6)) : colormapLUT(name);
      this.lutCache.set(name, l);
    }
    return l;
  }

  private palette(field: string, hidden: number[]): Uint8Array {
    const m = this.c.manifest;
    const f = m && fieldById(m, field);
    const colors = f && f.type === "categorical" ? m!.vocabularies[f.vocabulary].colors : ["#888888"];
    const key = `${field}|${hidden.join(".")}|${colors.length}`;
    let p = this.paletteCache.get(key);
    if (!p) {
      p = categoryPalette(colors, hidden);
      this.paletteCache.set(key, p);
    }
    return p;
  }

  /** Per-sample binary attribute bundle; identity is stable while the underlying arrays are unchanged. */
  private inputsFor(sd: SampleData, s: ViewerState): SampleLayerInputs & { value2?: { value: Uint8Array; size: number } } {
    const c = this.c;
    let value: SampleLayerInputs["value"];
    let value2: { value: Uint8Array; size: number } | undefined;
    let cat: SampleLayerInputs["cat"];
    let filter: SampleLayerInputs["filter"];
    if (s.color?.kind === "gene") value = c.cache.getGeneSync(sd.id, s.color.gene);
    else if (s.color?.kind === "blend") {
      value = c.blend.attr(sd, s.color.a);
      value2 = c.blend.attr(sd, s.color.b);
    } else if (s.color) {
      const f = c.manifest && fieldById(c.manifest, s.color.field);
      if (f?.type === "categorical") cat = sd.catAttr.get(s.color.field);
      else if (f) {
        const key = [...sd.numU8.keys()].find((k) => k.startsWith(`${f.id}@`));
        const u8 = key ? sd.numU8.get(key) : undefined;
        if (u8) value = { value: u8, size: 1 };
      }
    }
    if (s.filter) filter = c.stats.filterAttr(sd, s.filter);
    const prev = this.inputs.get(sd.id) as (SampleLayerInputs & { value2?: { value: Uint8Array; size: number } }) | undefined;
    if (prev && prev.pos === sd.posAttr && prev.value?.value === value?.value && prev.value2?.value === value2?.value && prev.cat === cat && prev.filter?.value === filter?.value) return prev;
    const attributes: Record<string, { value: ArrayBufferView; size: number }> = { getPosition: sd.posAttr };
    if (value) attributes.getValue = value;
    if (value2) attributes.getValue2 = value2;
    if (cat) attributes.getCategory = cat;
    if (filter) attributes.getFilter = filter;
    const next = { pos: sd.posAttr, value, value2, cat, filter, data: { length: sd.nObs, attributes } } as SampleLayerInputs & { value2?: { value: Uint8Array; size: number } };
    this.inputs.set(sd.id, next);
    return next;
  }

  build(): any[] {
    const c = this.c;
    const s = store.getState();
    if (!c.manifest) return [];
    const layers: any[] = [];
    const colorField = s.color?.kind === "field" ? fieldById(c.manifest, s.color.field) : undefined;
    const baseMode: 0 | 1 | 3 = s.color?.kind === "blend" ? 3 : colorField?.type === "categorical" ? 1 : 0;
    const lut = this.lut(s.color?.kind === "blend" ? `blend:${s.color.scheme}` : s.colormap);
    const catColors = baseMode === 1 && colorField ? this.palette(colorField.id, s.hiddenCategories[colorField.id] ?? []) : this.palette("__none", []);

    for (const view of VIEWS) {
      const L = c.layouts[view];
      if (!L || !c.rects[view]) continue;
      const vb = c.viewBbox(view);
      const [vw, vh] = c.viewSize(view);
      const zoom = c.viewStates[view].zoom;
      for (const [id, p] of L.placements) {
        const smp = c.samplesById.get(id)!;
        const sd = c.cache.samples.get(id);
        const visible = intersects(p.worldBbox, vb);
        if (s.showImages && smp.images.length && visible) layers.push(...this.imageLayers(s, view, id, p.modelMatrix));
        if (!sd) continue;
        const inp = this.inputsFor(sd, s);
        const hasData = baseMode === 1 ? !!inp.cat : baseMode === 3 ? !!(inp.value || inp.value2) : !!inp.value;
        const mode: 0 | 1 | 2 | 3 = hasData || !s.color ? baseMode : 2; // 2 = feature not measured on this sample
        const filterActive = !!s.filter && !!inp.filter;
        layers.push(
          new ExpressionScatterLayer({
            id: `pts-${id}`,
            viewId: view,
            data: inp.data as any,
            visible,
            modelMatrix: p.modelMatrix,
            radiusUnits: "common",
            getRadius: smp.pointRadius * s.pointScale[view],
            radiusMinPixels: 1,
            radiusMaxPixels: 40,
            stroked: false,
            filled: true,
            antialiasing: true,
            pickable: false,
            opacity: mode === 2 ? 0.6 : 1,
            parameters: { depthWriteEnabled: false, depthCompare: "always" },
            mode,
            vmin: s.vrange[0],
            vmax: s.vrange[1],
            hideZeros: s.hideZeros,
            filterOn: filterActive,
            filterMin: s.filter ? filterRange(s.filter)[0] : 0,
            filterMax: s.filter ? filterRange(s.filter)[1] : 1,
            lut,
            catColors,
            drawCount: drawCount(sd.nObs, p.worldBbox, zoom, [vw, vh]),
            getValue: 0,
            getValue2: 0,
            getCategory: 0,
            getFilter: 0,
          } as any),
        );
      }
      if (view === "spatial" && s.outline.field) layers.push(...this.outlineLayers(s, view, L));
      if (view === "spatial" && s.showPolygons) layers.push(...this.polygonLayers(view, L));
      layers.push(...c.selection.layers(s, view, L));
      layers.push(...this.frameLayers(s, view, L));
    }
    return layers;
  }

  private imageLayers(s: ViewerState, view: ViewId, id: string, modelMatrix: any) {
    const c = this.c;
    const smp = c.samplesById.get(id)!;
    const out: any[] = [];
    for (const img of smp.images) {
      const key = `${s.datasetUrl}/samples/${id}/${img.path}`;
      const h = this.imageHandles.get(key);
      if (!h) {
        this.imageHandles.set(key, "loading");
        loadImage(key)
          .then((handle) => {
            this.imageHandles.set(key, handle);
            c.requestLayers();
          })
          .catch((e) => {
            console.error("image load failed", key, e);
            this.imageHandles.set(key, "error");
          });
      } else if (h !== "loading" && h !== "error") {
        out.push(imageLayer(`img-${id}-${img.id}`, img, h, modelMatrix, s.imageOpacity * img.defaultOpacity, true, { viewId: view }));
      }
    }
    return out;
  }

  /** Cell boundary outlines, only when zoomed in enough that a cell spans several pixels. */
  private polygonLayers(view: ViewId, L: LayoutResult) {
    const c = this.c;
    const out: any[] = [];
    const scale = Math.pow(2, c.viewStates[view].zoom);
    const vb = c.viewBbox(view);
    for (const [id, p] of L.placements) {
      const smp = c.samplesById.get(id)!;
      if (!smp.polygons || !intersects(p.worldBbox, vb)) continue;
      if (scale * smp.pointRadius * 2 < 6) continue;
      if (!c.cache.samples.get(id)) continue;
      const poly = c.cache.getPolygons(id, smp.polygons.scale);
      if (!poly) {
        const pending = (c.cache as any).polygons.get(id);
        if (pending instanceof Promise) void pending.then(() => c.requestLayers());
        continue;
      }
      out.push(
        new PathLayer({
          ...overlayProps(view),
          id: `poly-${id}`,
          data: { length: poly.startIndices.length - 1, startIndices: poly.startIndices, attributes: { getPath: { value: poly.positions, size: 2 } } } as any,
          _pathType: "open",
          modelMatrix: p.modelMatrix,
          getColor: [255, 255, 255, 150],
          getWidth: 1,
          widthUnits: "pixels",
          widthMinPixels: 0.75,
        } as any),
      );
    }
    return out;
  }

  /** One PathLayer per sample with the chosen categorical field's boundaries. */
  private outlineLayers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const c = this.c;
    const field = s.outline.field!;
    const f = c.manifest && fieldById(c.manifest, field);
    if (!f || f.type !== "categorical" || !s.datasetUrl) return [];
    const colors = c.manifest!.vocabularies[f.vocabulary].colors.map((col) => hexToRGB(col));
    const out: any[] = [];
    for (const [id, p] of L.placements) {
      const smp = c.samplesById.get(id)!;
      if (!smp.outlines?.includes(field)) continue;
      const data = c.cache.getOutlines(s.datasetUrl, id, field);
      if (data instanceof Promise) {
        store.getState().set({ pending: store.getState().pending + 1 });
        data
          .catch((e) => console.warn("outline load failed", id, field, e))
          .finally(() => {
            store.getState().set({ pending: Math.max(0, store.getState().pending - 1) });
            c.requestLayers();
          });
        continue;
      }
      const style = s.outline.style;
      out.push(
        new PathLayer({
          ...overlayProps(view),
          id: `outline-${id}`,
          data: data.paths,
          getPath: (d: any) => d.p,
          getColor: (d: any) => (style === "field" ? [...colors[d.c], 235] : style === "light" ? [255, 255, 255, 210] : [15, 17, 22, 230]),
          getWidth: s.outline.width,
          widthUnits: "pixels",
          widthMinPixels: 0.5,
          jointRounded: true,
          capRounded: true,
          modelMatrix: p.modelMatrix,
          updateTriggers: { getColor: [style] },
        } as any),
      );
    }
    return out;
  }

  /** Sample outlines (selected / focused / failed) and name labels, one layer each per view. */
  private frameLayers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const c = this.c;
    const frames: { path: [number, number][]; color: [number, number, number, number]; width: number; dashed: boolean }[] = [];
    const labels: { pos: [number, number]; text: string; color: [number, number, number, number] }[] = [];
    for (const [id, p] of L.placements) {
      const smp = c.samplesById.get(id)!;
      const [x0, y0, x1, y1] = p.worldBbox;
      const st = s.sampleStatus[id];
      const rect: [number, number][] = [
        [x0, y0],
        [x1, y0],
        [x1, y1],
        [x0, y1],
        [x0, y0],
      ];
      if (st === "error") frames.push({ path: rect, color: [255, 90, 90, 220], width: 2, dashed: true });
      else if (id === s.focus) frames.push({ path: rect, color: [64, 196, 255, 200], width: 2, dashed: false });
      else if (id === s.selected) frames.push({ path: rect, color: [230, 237, 243, 140], width: 1.5, dashed: false });
      labels.push({
        pos: [x0, y0],
        text: st === "error" ? `${smp.name} (failed to load)` : st === "loading" || st === "pending" ? `${smp.name} …` : smp.name,
        color: st === "error" ? [255, 120, 120, 255] : [230, 237, 243, 230],
      });
    }
    const common = overlayProps(view);
    return [
      new PathLayer({
        ...common,
        id: `frames-${view}`,
        data: frames,
        getPath: (d: any) => d.path,
        getColor: (d: any) => d.color,
        getWidth: (d: any) => d.width,
        widthUnits: "pixels",
        getDashArray: (d: any) => (d.dashed ? [6, 4] : [0, 0]),
        dashJustified: true,
      } as any),
      new TextLayer({
        ...common,
        id: `labels-${view}`,
        data: labels,
        getPosition: (d: any) => d.pos,
        getText: (d: any) => d.text,
        getColor: (d: any) => d.color,
        getSize: 13,
        sizeUnits: "pixels",
        getTextAnchor: "start",
        getAlignmentBaseline: "bottom",
        getPixelOffset: [2, -4],
        fontFamily: "Inter, system-ui, sans-serif",
        fontWeight: 600,
        background: true,
        getBackgroundColor: [14, 17, 22, 170],
        backgroundPadding: [4, 2, 4, 2],
      } as any),
    ];
  }
}
