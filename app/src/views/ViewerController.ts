/**
 * Owns the imperative deck.gl instance. Two orthographic views share one GL context:
 *   "spatial"   — the mosaic of tissue sections
 *   "embedding" — snRNA-seq (or any) embeddings, shown in a resizable split when present
 * Subscribes to the store, loads data through DataCache, builds layers, handles hover / focus / keys.
 * React never touches the canvas.
 */
import { Deck, OrthographicView, LinearInterpolator } from "@deck.gl/core";
import { PathLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { Matrix4 } from "@math.gl/core";
import { DataCache, type BinaryAttr, type SampleData } from "../data/cache";
import { assertManifest, fieldById, type Manifest, type Sample } from "../data/manifest";
import { ExpressionScatterLayer } from "../layers/ExpressionScatterLayer";
import { imageLayer, loadImage, type ImageHandle } from "../layers/imageLayers";
import { categoryPalette, colormapLUT, hexToRGB } from "../layers/lut";
import { store, type ColorSpec, type FilterSpec, type ViewId, type ViewerState, type ViewState } from "../store/store";
import { computeLayout, fitBbox, type LayoutResult } from "./layout";
import { pointInPolygon } from "./geometry";
import { drawCount, intersects } from "./lod";

const VIEWS: ViewId[] = ["spatial", "embedding"];

interface SampleLayerInputs {
  pos: BinaryAttr<Float32Array>;
  value?: BinaryAttr<Uint8Array>;
  cat?: BinaryAttr<Uint16Array>;
  filter?: BinaryAttr<Uint8Array>;
  data: { length: number; attributes: Record<string, BinaryAttr<ArrayBufferView>> };
}
interface ViewRect {
  x: number; // px from the left of the container
  w: number;
}

export class ViewerController {
  deck: Deck<OrthographicView[]>;
  cache = new DataCache();
  layouts: Record<ViewId, LayoutResult | null> = { spatial: null, embedding: null };
  private manifest: Manifest | null = null;
  private samplesById = new Map<string, Sample>();
  private viewStates: Record<ViewId, ViewState> = { spatial: { target: [0, 0, 0], zoom: 0 }, embedding: { target: [0, 0, 0], zoom: 0 } };
  private rects: Partial<Record<ViewId, ViewRect>> = {};
  private imageHandles = new Map<string, ImageHandle | "loading" | "error">();
  private layerInputs = new Map<string, SampleLayerInputs>();
  private lutCache = new Map<string, Uint8Array>();
  private paletteCache = new Map<string, Uint8Array>();
  private raf: number | null = null;
  private generation = 0;
  private frameTimes: number[] = [];
  private lastProbe: { nonBackground: number; total: number } | null = null;
  private wantProbe = false;
  private geneSwitchStart = 0;
  private unsub: () => void;
  private abort = new AbortController();
  private destroyed = false;

  constructor(public container: HTMLDivElement) {
    this.deck = new Deck({
      parent: container,
      views: this.makeViews(),
      viewState: this.viewStates as any,
      onViewStateChange: ({ viewState, viewId }) => this.onViewState(viewId as ViewId, viewState as ViewState),
      layerFilter: ({ layer, viewport }) => (layer.props as any).viewId === viewport.id,
      layers: [],
      useDevicePixels: true,
      getCursor: ({ isDragging }) => (isDragging ? "grabbing" : "crosshair"),
      onAfterRender: () => this.afterRender(),
      onResize: () => this.onResize(),
    });
    const { signal } = this.abort;
    container.addEventListener("pointerdown", this.onPointerDown, { signal });
    container.addEventListener("pointerup", this.onPointerUp, { signal });
    container.addEventListener("pointermove", this.onPointerMove, { signal });
    container.addEventListener("pointerleave", () => store.getState().set({ hover: null }), { signal });
    container.addEventListener("click", this.onClick, { signal });
    container.addEventListener("dblclick", this.onDblClick, { signal });
    window.addEventListener("keydown", this.onKey, { signal });
    this.unsub = store.subscribe((s, prev) => this.onStore(s, prev));
  }

  destroy() {
    this.destroyed = true;
    this.abort.abort();
    this.unsub();
    if (this.raf != null) {
      cancelAnimationFrame(this.raf);
      clearTimeout(this.raf);
      this.raf = null;
    }
    this.deck.finalize();
  }

  // ---------------------------------------------------------------- views
  private hasEmbedding(): boolean {
    return !!this.manifest?.samples.some((s) => s.kind === "embedding");
  }
  private hasSpatial(): boolean {
    return !!this.manifest?.samples.some((s) => s.kind !== "embedding");
  }

  /** Pixel rectangles of the active views, computed from the split state. */
  computeRects(): Partial<Record<ViewId, ViewRect>> {
    const [w] = this.viewportSize();
    const s = store.getState();
    const emb = this.hasEmbedding() && s.split.on;
    const spa = this.hasSpatial();
    if (emb && spa) {
      const ew = Math.round(w * s.split.fraction);
      return s.split.side === "left"
        ? { embedding: { x: 0, w: ew }, spatial: { x: ew, w: w - ew } }
        : { spatial: { x: 0, w: w - ew }, embedding: { x: w - ew, w: ew } };
    }
    if (emb) return { embedding: { x: 0, w } };
    return { spatial: { x: 0, w } };
  }

  private makeViews(): OrthographicView[] {
    this.rects = this.computeRects();
    return VIEWS.filter((v) => this.rects[v]).map(
      (v) =>
        new OrthographicView({
          id: v,
          flipY: true,
          x: this.rects[v]!.x,
          y: 0,
          width: this.rects[v]!.w,
          height: "100%",
          controller: store.getState().tool === "lasso" ? false : { dragRotate: false, doubleClickZoom: false, inertia: 250, keyboard: false },
        }),
    );
  }

  private viewSize(v: ViewId): [number, number] {
    const [, h] = this.viewportSize();
    return [Math.max(1, this.rects[v]?.w ?? 1), h];
  }

  private viewportSize(): [number, number] {
    return [Math.max(1, this.container.clientWidth), Math.max(1, this.container.clientHeight)];
  }

  private updateViews(animate: boolean) {
    this.deck.setProps({ views: this.makeViews() });
    for (const v of VIEWS) if (this.rects[v]) this.relayout(v, animate);
    this.requestLayers();
  }

  viewOf(sampleId: string): ViewId {
    return this.samplesById.get(sampleId)?.kind === "embedding" ? "embedding" : "spatial";
  }

  // ---------------------------------------------------------------- loading
  async load(url: string) {
    const s = store.getState();
    s.set({ status: "loading", error: null, datasetUrl: url, manifest: null, features: null, sampleStatus: {} });
    let manifest: Manifest;
    try {
      const r = await fetch(`${url.replace(/\/$/, "")}/manifest.json`);
      if (!r.ok) throw new Error(`HTTP ${r.status} fetching manifest.json`);
      manifest = await r.json();
      assertManifest(manifest);
    } catch (e) {
      s.set({ status: "error", error: `Could not load dataset at ${url}: ${(e as Error).message}. If the data is on another host, it must send CORS headers and support HTTP Range requests.` });
      return;
    }
    this.manifest = manifest;
    this.samplesById = new Map(manifest.samples.map((x) => [x.id, x]));
    void fetch(`${url.replace(/\/$/, "")}/features.json`)
      .then((r) => (r.ok ? r.json() : fetch(`${url.replace(/\/$/, "")}/genes.json`).then((g) => g.json()).then((genes) => ({ genes, groups: [] }))))
      .then((features) => store.getState().set({ features }))
      .catch(() => store.getState().set({ features: { genes: [], groups: [] } }));
    const cur = store.getState();
    const color: ColorSpec =
      cur.color ??
      (manifest.defaultColor.kind === "gene" && manifest.defaultColor.gene
        ? { kind: "gene", gene: manifest.defaultColor.gene }
        : manifest.defaultColor.field
          ? { kind: "field", field: manifest.defaultColor.field }
          : { kind: "gene", gene: manifest.defaultGene ?? "" });
    const sampleStatus: ViewerState["sampleStatus"] = {};
    for (const smp of manifest.samples) sampleStatus[smp.id] = "pending";
    cur.set({ manifest, color, sampleStatus });
    this.deck.setProps({ views: this.makeViews() });
    for (const v of VIEWS) if (this.rects[v]) this.relayout(v, false);
    if (cur.viewState) this.setViewState("spatial", cur.viewState);
    if (cur.focus && this.layouts[this.viewOf(cur.focus)]?.placements.has(cur.focus)) this.focusSample(cur.focus, false);

    const order = [...manifest.layout.order];
    for (const smp of manifest.samples) if (!order.includes(smp.id)) order.push(smp.id);
    if (cur.focus) order.sort((a) => (a === cur.focus ? -1 : 0));
    await Promise.all(
      order.map(async (id) => {
        const smp = this.samplesById.get(id)!;
        store.getState().set({ sampleStatus: { ...store.getState().sampleStatus, [id]: "loading" } });
        try {
          await this.cache.openSample(url, id, smp.nObs);
          store.getState().set({ sampleStatus: { ...store.getState().sampleStatus, [id]: "ready" } });
          void this.loadChannels(id);
        } catch (e) {
          console.error(e);
          store.getState().set({ sampleStatus: { ...store.getState().sampleStatus, [id]: "error" } });
        }
        this.requestLayers();
      }),
    );
    store.getState().set({ status: "ready" });
    this.requestLayers();
  }

  /** Make sure the arrays needed by the current color/filter are present for one sample (or all). */
  private async loadChannels(sampleId?: string) {
    const s = store.getState();
    const ids = sampleId ? [sampleId] : [...this.cache.samples.keys()];
    const gen = this.generation;
    const jobs: Promise<unknown>[] = [];
    const need = (p: Promise<unknown>) => {
      s.set({ pending: store.getState().pending + 1 });
      jobs.push(
        p
          .catch((e) => console.error(e))
          .finally(() => {
            store.getState().set({ pending: Math.max(0, store.getState().pending - 1) });
            if (gen === this.generation) this.requestLayers();
          }),
      );
    };
    for (const id of ids) {
      const sd = this.cache.samples.get(id);
      if (!sd) continue;
      const wanted: (ColorSpec | FilterSpec | null)[] = [s.color, s.filter];
      if (s.groupField && s.color?.kind === "gene") wanted.push({ kind: "field", field: s.groupField });
      for (const spec of wanted) {
        if (!spec) continue;
        if (spec.kind === "category") {
          if (this.samplesById.get(id)?.fields.includes(spec.field) && !sd.catAttr.has(spec.field)) need(this.cache.getCategorical(id, spec.field));
          continue;
        }
        if (spec.kind === "gene") {
          if (!this.cache.getGeneSync(id, spec.gene) && sd.geneIndex.has(spec.gene)) need(this.cache.getGene(id, spec.gene));
        } else {
          const f = this.manifest && fieldById(this.manifest, spec.field);
          if (!f || !this.samplesById.get(id)?.fields.includes(spec.field)) continue;
          if (f.type === "categorical") {
            if (!sd.catAttr.has(spec.field)) need(this.cache.getCategorical(id, spec.field).then(() => this.updateCategoryCounts(spec.field)));
          } else if (!sd.num.has(spec.field)) need(this.cache.getContinuousU8(id, spec.field, f.range));
        }
      }
    }
    await Promise.all(jobs);
    if (gen === this.generation) this.afterChannelsLoaded();
  }

  private afterChannelsLoaded() {
    const s = store.getState();
    if (s.color?.kind === "gene") {
      const gene = s.color.gene;
      const ids = [...this.cache.samples.keys()];
      Promise.all(ids.map((id) => this.cache.gmax(id, gene))).then((v) => {
        ids.forEach((id, i) => this.geneGmax.set(`${id}:${gene}`, v[i]));
        store.getState().set({ geneMax: Math.max(0, ...v) });
        this.updateGroupStats();
        this.updateSelectionSummary();
      });
      if (this.geneSwitchStart) {
        store.getState().set({ timings: { ...store.getState().timings, lastGeneMs: performance.now() - this.geneSwitchStart } });
        this.geneSwitchStart = 0;
      }
    }
    if (s.filter) this.updateFilterHistogram();
    this.updateGroupStats();
    this.updateSelectionSummary();
    this.requestLayers();
  }

  private geneGmax = new Map<string, number>();

  /** Mean / fraction-expressing of the current gene per category of the group field, over visible samples. */
  updateGroupStats() {
    const s = store.getState();
    if (!this.manifest || s.color?.kind !== "gene" || !s.groupField) {
      if (s.groupStats) s.set({ groupStats: null });
      return;
    }
    const gene = s.color.gene;
    const f = fieldById(this.manifest, s.groupField);
    if (!f || f.type !== "categorical") return;
    const n = this.manifest.vocabularies[f.vocabulary].categories.length;
    const hidden = this.hiddenSampleSet(s);
    const sum = new Float64Array(n);
    const cnt = new Float64Array(n);
    const pos = new Float64Array(n);
    const per: Record<string, { sum: Float64Array; cnt: Float64Array; pos: Float64Array }> = {};
    for (const sd of this.cache.samples.values()) {
      if (hidden.has(sd.id)) continue;
      const g = this.cache.getGeneSync(sd.id, gene)?.value;
      const cat = sd.cat.get(f.id);
      const gmax = this.geneGmax.get(`${sd.id}:${gene}`);
      if (!g || !cat || gmax === undefined) continue;
      const p = (per[sd.id] = { sum: new Float64Array(n), cnt: new Float64Array(n), pos: new Float64Array(n) });
      const k = gmax / 255;
      for (let i = 0; i < g.length; i++) {
        const c = cat[i];
        if (c >= n) continue;
        const v = g[i] * k;
        sum[c] += v;
        cnt[c]++;
        p.sum[c] += v;
        p.cnt[c]++;
        if (g[i] > 0) {
          pos[c]++;
          p.pos[c]++;
        }
      }
    }
    const rows = [];
    let maxMean = 0;
    for (let c = 0; c < n; c++) {
      if (!cnt[c]) continue;
      const mean = sum[c] / cnt[c];
      maxMean = Math.max(maxMean, mean);
      const perSample: Record<string, { n: number; mean: number; frac: number }> = {};
      for (const [sid, p] of Object.entries(per)) if (p.cnt[c]) perSample[sid] = { n: p.cnt[c], mean: p.sum[c] / p.cnt[c], frac: p.pos[c] / p.cnt[c] };
      rows.push({ code: c, n: cnt[c], mean, frac: pos[c] / cnt[c], perSample });
    }
    rows.sort((a, b) => b.mean - a.mean);
    s.set({ groupStats: { gene, field: f.id, rows, maxMean } });
  }

  private hiddenSampleSet(s: ViewerState): Set<string> {
    const hidden = new Set(s.hiddenSamples);
    if (s.platforms && this.manifest) {
      const allowed = new Set(s.platforms);
      for (const smp of this.manifest.samples) if (smp.kind !== "embedding" && !allowed.has(smp.platform)) hidden.add(smp.id);
    }
    return hidden;
  }

  private updateCategoryCounts(field: string) {
    const f = this.manifest && fieldById(this.manifest, field);
    if (!f || f.type !== "categorical") return;
    const n = this.manifest!.vocabularies[f.vocabulary].categories.length;
    const counts = new Array<number>(n).fill(0);
    const hidden = this.hiddenSampleSet(store.getState());
    for (const sd of this.cache.samples.values()) {
      if (hidden.has(sd.id)) continue;
      const codes = sd.cat.get(field);
      if (!codes) continue;
      for (let i = 0; i < codes.length; i++) if (codes[i] < n) counts[codes[i]]++;
    }
    store.getState().set({ categoryCounts: { ...store.getState().categoryCounts, [field]: counts } });
  }

  private updateFilterHistogram() {
    const s = store.getState();
    if (!s.filter) return;
    const bins = new Array<number>(64).fill(0);
    let visible = 0;
    const range = filterRange(s.filter);
    for (const sd of this.cache.samples.values()) {
      const arr = this.filterAttr(sd, s.filter)?.value;
      if (!arr) continue;
      const lo = range[0] * 255;
      const hi = range[1] * 255;
      for (let i = 0; i < arr.length; i++) {
        bins[arr[i] >> 2]++;
        if (arr[i] >= lo && arr[i] <= hi) visible++;
      }
    }
    s.set({ filterHistogram: bins, visibleCount: visible });
  }

  private filterAttr(sd: SampleData, f: FilterSpec): BinaryAttr<Uint8Array> | undefined {
    if (f.kind === "gene") return this.cache.getGeneSync(sd.id, f.gene);
    if (f.kind === "category") return this.cache.categoryMask(sd.id, f.field, f.codes);
    const key = [...sd.numU8.keys()].find((k) => k.startsWith(`${f.field}@`));
    const u8 = key ? sd.numU8.get(key) : undefined;
    return u8 ? { value: u8, size: 1 } : undefined;
  }

  // ---------------------------------------------------------------- store reactions
  private onStore(s: ViewerState, prev: ViewerState) {
    if (s.color !== prev.color || s.filter !== prev.filter) {
      this.generation++;
      if (s.color !== prev.color && s.color?.kind === "gene") this.geneSwitchStart = performance.now();
      void this.loadChannels();
      if (s.filter !== prev.filter && s.filter && prev.filter && sameChannel(s.filter, prev.filter)) this.updateFilterHistogram();
    }
    if (s.split !== prev.split) this.updateViews(true);
    if (s.tool !== prev.tool) {
      this.deck.setProps({ views: this.makeViews() });
      if (s.tool === "pan") this.lassoPts = null;
      this.requestLayers();
    }
    if (s.groupField !== prev.groupField) {
      this.generation++;
      void this.loadChannels();
    }
    if (s.layoutMode !== prev.layoutMode || s.hiddenSamples !== prev.hiddenSamples || s.platforms !== prev.platforms) {
      for (const v of VIEWS) if (this.rects[v]) this.relayout(v, true);
      if (s.color?.kind === "field") this.updateCategoryCounts(s.color.field);
      this.updateGroupStats();
      this.requestLayers();
    }
    if (s.focus !== prev.focus) {
      if (s.focus) this.focusSample(s.focus, true);
      else this.fitAll(prev.focus ? this.viewOf(prev.focus) : "spatial", true);
    }
    if (
      s.colormap !== prev.colormap ||
      s.vrange !== prev.vrange ||
      s.hideZeros !== prev.hideZeros ||
      s.hiddenCategories !== prev.hiddenCategories ||
      s.imageOpacity !== prev.imageOpacity ||
      s.showImages !== prev.showImages ||
      s.pointScale !== prev.pointScale ||
      s.selected !== prev.selected ||
      s.sampleStatus !== prev.sampleStatus ||
      s.outline !== prev.outline ||
      s.showPolygons !== prev.showPolygons
    ) {
      this.requestLayers();
    }
  }

  // ---------------------------------------------------------------- layout / camera
  relayout(view: ViewId, animate: boolean) {
    if (!this.manifest || !this.rects[view]) return;
    const s = store.getState();
    const [w, h] = this.viewSize(view);
    const samples = this.manifest.samples.filter((x) => (x.kind === "embedding") === (view === "embedding"));
    const hidden = this.hiddenSampleSet(s);
    this.layouts[view] = computeLayout(samples, this.manifest.layout.order, s.layoutMode, this.manifest.layout.gutterFraction, w / h, hidden);
    const focusHere = s.focus && this.viewOf(s.focus) === view;
    if (focusHere && this.layouts[view]!.placements.has(s.focus!)) this.focusSample(s.focus!, animate);
    else if (focusHere) s.set({ focus: null });
    else this.fitAll(view, animate);
    this.requestLayers();
  }

  fitAll(view: ViewId, animate: boolean) {
    const L = this.layouts[view];
    if (!L || !this.rects[view]) return;
    const [w, h] = this.viewSize(view);
    this.setViewState(view, { ...fitBbox(L.worldBbox, w, h, 0.04), ...(animate ? transition() : {}) });
  }

  focusSample(id: string, animate: boolean) {
    const view = this.viewOf(id);
    const p = this.layouts[view]?.placements.get(id);
    if (!p || !this.rects[view]) return;
    const [w, h] = this.viewSize(view);
    this.setViewState(view, { ...fitBbox(p.worldBbox, w, h, 0.06), ...(animate ? transition() : {}) });
  }

  stepFocus(delta: number) {
    const s = store.getState();
    const view = s.focus ? this.viewOf(s.focus) : s.activeView;
    const ids = [...(this.layouts[view]?.placements.keys() ?? [])];
    if (!ids.length) return;
    const i = s.focus ? ids.indexOf(s.focus) : -1;
    s.setFocus(ids[(i + delta + ids.length) % ids.length]);
  }

  private setViewState(view: ViewId, vs: ViewState) {
    this.viewStates = { ...this.viewStates, [view]: vs };
    this.deck.setProps({ viewState: this.viewStates as any });
    this.requestLayers();
  }

  private vsTimer: number | null = null;
  private onViewState(view: ViewId, vs: ViewState) {
    this.viewStates = { ...this.viewStates, [view]: vs };
    this.deck.setProps({ viewState: this.viewStates as any });
    this.requestLayers();
    if (view !== "spatial") return;
    if (this.vsTimer) window.clearTimeout(this.vsTimer);
    this.vsTimer = window.setTimeout(() => {
      store.getState().set({ viewState: { target: vs.target, zoom: vs.zoom } });
    }, 150);
  }

  private onResize() {
    if (!this.manifest) return;
    this.deck.setProps({ views: this.makeViews() });
    const s = store.getState();
    for (const v of VIEWS) {
      if (!this.rects[v]) continue;
      if (s.focus && this.viewOf(s.focus) === v) this.focusSample(s.focus, false);
      else if (v === "embedding" || !s.viewState) this.fitAll(v, false);
    }
    this.requestLayers();
  }

  /** World-space rectangle currently visible in a view. */
  private viewBbox(view: ViewId): [number, number, number, number] {
    const [w, h] = this.viewSize(view);
    const vs = this.viewStates[view];
    const scale = Math.pow(2, vs.zoom);
    const [cx, cy] = vs.target;
    return [cx - w / 2 / scale, cy - h / 2 / scale, cx + w / 2 / scale, cy + h / 2 / scale];
  }

  // ---------------------------------------------------------------- layers
  requestLayers() {
    if (this.raf != null) return;
    // rAF stalls in hidden tabs/panes; fall back to a timer so data keeps flowing
    const schedule =
      typeof document !== "undefined" && document.visibilityState === "hidden"
        ? (cb: () => void) => window.setTimeout(cb, 16)
        : (cb: () => void) => requestAnimationFrame(cb);
    this.raf = schedule(() => {
      this.raf = null;
      this.buildLayers();
    }) as unknown as number;
  }

  private lut(name: string): Uint8Array {
    let l = this.lutCache.get(name);
    if (!l) {
      l = colormapLUT(name);
      this.lutCache.set(name, l);
    }
    return l;
  }

  private palette(field: string, hidden: number[]): Uint8Array {
    const f = this.manifest && fieldById(this.manifest, field);
    const colors = f && f.type === "categorical" ? this.manifest!.vocabularies[f.vocabulary].colors : ["#888888"];
    const key = `${field}|${hidden.join(".")}|${colors.length}`;
    let p = this.paletteCache.get(key);
    if (!p) {
      p = categoryPalette(colors, hidden);
      this.paletteCache.set(key, p);
    }
    return p;
  }

  private inputsFor(sd: SampleData, s: ViewerState): SampleLayerInputs {
    let value: BinaryAttr<Uint8Array> | undefined;
    let cat: BinaryAttr<Uint16Array> | undefined;
    let filter: BinaryAttr<Uint8Array> | undefined;
    if (s.color?.kind === "gene") value = this.cache.getGeneSync(sd.id, s.color.gene);
    else if (s.color) {
      const f = this.manifest && fieldById(this.manifest, s.color.field);
      if (f?.type === "categorical") cat = sd.catAttr.get(s.color.field);
      else if (f) {
        const key = [...sd.numU8.keys()].find((k) => k.startsWith(`${f.id}@`));
        const u8 = key ? sd.numU8.get(key) : undefined;
        if (u8) value = { value: u8, size: 1 };
      }
    }
    if (s.filter) filter = this.filterAttr(sd, s.filter);
    const prev = this.layerInputs.get(sd.id);
    if (prev && prev.pos === sd.posAttr && prev.value?.value === value?.value && prev.cat === cat && prev.filter?.value === filter?.value) return prev;
    const attributes: Record<string, BinaryAttr<ArrayBufferView>> = { getPosition: sd.posAttr };
    if (value) attributes.getValue = value;
    if (cat) attributes.getCategory = cat;
    if (filter) attributes.getFilter = filter;
    const next: SampleLayerInputs = { pos: sd.posAttr, value, cat, filter, data: { length: sd.nObs, attributes } };
    this.layerInputs.set(sd.id, next);
    return next;
  }

  buildLayers() {
    if (this.destroyed || !this.manifest) return;
    try {
      this._buildLayers();
    } catch (e) {
      console.error("buildLayers failed", e);
    }
  }

  private _buildLayers() {
    if (!this.manifest) return;
    const s = store.getState();
    const layers: any[] = [];
    const colorField = s.color?.kind === "field" ? fieldById(this.manifest, s.color.field) : undefined;
    const baseMode: 0 | 1 = colorField?.type === "categorical" ? 1 : 0;
    const lut = this.lut(s.colormap);
    const catColors = baseMode === 1 && colorField ? this.palette(colorField.id, s.hiddenCategories[colorField.id] ?? []) : this.palette("__none", []);

    for (const view of VIEWS) {
      const L = this.layouts[view];
      if (!L || !this.rects[view]) continue;
      const vb = this.viewBbox(view);
      const [vw, vh] = this.viewSize(view);
      const zoom = this.viewStates[view].zoom;
      for (const [id, p] of L.placements) {
        const smp = this.samplesById.get(id)!;
        const sd = this.cache.samples.get(id);
        const visible = intersects(p.worldBbox, vb);
        if (s.showImages && smp.images.length && visible) {
          for (const img of smp.images) {
            const key = `${s.datasetUrl}/samples/${id}/${img.path}`;
            const h = this.imageHandles.get(key);
            if (!h) {
              this.imageHandles.set(key, "loading");
              loadImage(key)
                .then((handle) => {
                  this.imageHandles.set(key, handle);
                  this.requestLayers();
                })
                .catch((e) => {
                  console.error("image load failed", key, e);
                  this.imageHandles.set(key, "error");
                });
            } else if (h !== "loading" && h !== "error") {
              layers.push(imageLayer(`img-${id}-${img.id}`, img, h, p.modelMatrix, s.imageOpacity * img.defaultOpacity, true, { viewId: view }));
            }
          }
        }
        if (!sd) continue;
        const inp = this.inputsFor(sd, s);
        const hasData = baseMode === 1 ? !!inp.cat : !!inp.value;
        const mode: 0 | 1 | 2 = hasData || !s.color ? baseMode : 2; // 2 = feature not measured on this sample
        const filterActive = !!s.filter && !!inp.filter;
        layers.push(
          new ExpressionScatterLayer({
            id: `pts-${id}`,
            viewId: view,
            data: inp.data as any,
            visible,
            modelMatrix: p.modelMatrix,
            radiusUnits: "common",
            getRadius: smp.pointRadius * s.pointScale,
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
            getCategory: 0,
            getFilter: 0,
          } as any),
        );
      }
      if (view === "spatial" && s.outline.field) layers.push(...this.outlineLayers(s, view, L));
      if (view === "spatial" && s.showPolygons) layers.push(...this.polygonLayers(s, view, L));
      layers.push(...this.selectionLayers(s, view, L));
      layers.push(...this.frameLayers(s, view, L));
    }
    this.deck.setProps({ layers });
  }

  /** Cell boundary outlines, only when zoomed in enough that a cell spans several pixels. */
  private polygonLayers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const out: any[] = [];
    const scale = Math.pow(2, this.viewStates[view].zoom); // px per µm
    const vb = this.viewBbox(view);
    for (const [id, p] of L.placements) {
      const smp = this.samplesById.get(id)!;
      if (!smp.polygons || !intersects(p.worldBbox, vb)) continue;
      if (scale * smp.pointRadius * 2 < 6) continue; // a cell is < 6 px wide: outlines would be noise
      const sd = this.cache.samples.get(id);
      if (!sd) continue;
      const poly = this.cache.getPolygons(id, smp.polygons.scale);
      if (!poly) {
        // first request: show it when it lands
        const pending = (this.cache as any).polygons.get(id);
        if (pending instanceof Promise) void pending.then(() => this.requestLayers());
        continue;
      }
      out.push(
        new PathLayer({
          id: `poly-${id}`,
          viewId: view,
          data: { length: poly.startIndices.length - 1, startIndices: poly.startIndices, attributes: { getPath: { value: poly.positions, size: 2 } } } as any,
          _pathType: "open",
          modelMatrix: p.modelMatrix,
          getColor: [255, 255, 255, 150],
          getWidth: 1,
          widthUnits: "pixels",
          widthMinPixels: 0.75,
          pickable: false,
          parameters: { depthWriteEnabled: false, depthCompare: "always" },
        } as any),
      );
    }
    return out;
  }

  /** One PathLayer per sample with the chosen categorical field's boundaries. */
  private outlineLayers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const field = s.outline.field!;
    const f = this.manifest && fieldById(this.manifest, field);
    if (!f || f.type !== "categorical" || !s.datasetUrl) return [];
    const colors = this.manifest!.vocabularies[f.vocabulary].colors.map((c) => hexToRGB(c));
    const out: any[] = [];
    for (const [id, p] of L.placements) {
      const smp = this.samplesById.get(id)!;
      if (!smp.outlines?.includes(field)) continue;
      const data = this.cache.getOutlines(s.datasetUrl, id, field);
      if (data instanceof Promise) {
        store.getState().set({ pending: store.getState().pending + 1 });
        data
          .catch((e) => console.warn("outline load failed", id, field, e))
          .finally(() => {
            store.getState().set({ pending: Math.max(0, store.getState().pending - 1) });
            this.requestLayers();
          });
        continue;
      }
      const style = s.outline.style;
      out.push(
        new PathLayer({
          id: `outline-${id}`,
          viewId: view,
          data: data.paths,
          getPath: (d: any) => d.p,
          getColor: (d: any) => (style === "field" ? [...colors[d.c], 235] : style === "light" ? [255, 255, 255, 210] : [15, 17, 22, 230]),
          getWidth: s.outline.width,
          widthUnits: "pixels",
          widthMinPixels: 0.5,
          jointRounded: true,
          capRounded: true,
          modelMatrix: p.modelMatrix,
          pickable: false,
          parameters: { depthWriteEnabled: false, depthCompare: "always" },
          updateTriggers: { getColor: [style] },
        } as any),
      );
    }
    return out;
  }

  /** Sample outlines (selected / focused / failed) and name labels, one layer each per view. */
  private frameLayers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const frames: { path: [number, number][]; color: [number, number, number, number]; width: number; dashed: boolean }[] = [];
    const labels: { pos: [number, number]; text: string; color: [number, number, number, number] }[] = [];
    for (const [id, p] of L.placements) {
      const smp = this.samplesById.get(id)!;
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
    const common = { pickable: false, viewId: view, parameters: { depthWriteEnabled: false, depthCompare: "always" } };
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

  // ---------------------------------------------------------------- interaction
  /** Which view a container-relative pixel falls in. */
  private viewAtPixel(x: number): ViewId | null {
    for (const v of VIEWS) {
      const r = this.rects[v];
      if (r && x >= r.x && x < r.x + r.w) return v;
    }
    return null;
  }

  private worldFromEvent(e: MouseEvent): { view: ViewId; world: [number, number]; px: [number, number] } | null {
    if (this.destroyed || !(this.deck as any).viewManager) return null;
    const rect = this.container.getBoundingClientRect();
    const px: [number, number] = [e.clientX - rect.left, e.clientY - rect.top];
    const view = this.viewAtPixel(px[0]);
    if (!view) return null;
    const vp = this.deck.getViewports().find((v) => v.id === view);
    if (!vp) return null;
    const [x, y] = vp.unproject([px[0] - vp.x, px[1] - vp.y]);
    return { view, world: [x, y], px };
  }

  private sampleAt(view: ViewId, wx: number, wy: number, pad = 0): string | null {
    const L = this.layouts[view];
    if (!L) return null;
    for (const [id, p] of L.placements) {
      const b = p.worldBbox;
      if (wx >= b[0] - pad && wx <= b[2] + pad && wy >= b[1] - pad && wy <= b[3] + pad) return id;
    }
    return null;
  }

  private onPointerMove = (e: PointerEvent) => {
    const hit = this.worldFromEvent(e);
    const s = store.getState();
    if (this.lassoActive && this.lassoPts && hit && hit.view === this.lassoPts.view) {
      const last = this.lassoPts.world[this.lassoPts.world.length - 1];
      const scale = Math.pow(2, this.viewStates[hit.view].zoom);
      if (Math.hypot(hit.world[0] - last[0], hit.world[1] - last[1]) * scale > 3) {
        this.lassoPts.world.push(hit.world);
        this.requestLayers();
      }
      return;
    }
    if (!hit) {
      if (s.hover) s.set({ hover: null });
      return;
    }
    if (s.activeView !== hit.view) s.set({ activeView: hit.view });
    const scale = Math.pow(2, this.viewStates[hit.view].zoom);
    const id = this.sampleAt(hit.view, hit.world[0], hit.world[1], 8 / scale);
    const sd = id ? this.cache.samples.get(id) : undefined;
    const smp = id ? this.samplesById.get(id) : undefined;
    if (!id || !sd || !smp || !sd.index) {
      if (s.hover) s.set({ hover: null });
      return;
    }
    const p = this.layouts[hit.view]!.placements.get(id)!;
    const inv = new Matrix4(p.modelMatrix).invert();
    const [lx, ly] = inv.transformAsPoint([hit.world[0], hit.world[1], 0]);
    const r = Math.max(smp.pointRadius * s.pointScale, 6 / scale);
    const hits = sd.index.within(lx, ly, r);
    if (!hits.length) {
      if (s.hover) s.set({ hover: null });
      return;
    }
    let best = hits[0];
    let bd = Infinity;
    for (const h of hits) {
      const dx = sd.xy[h * 2] - lx;
      const dy = sd.xy[h * 2 + 1] - ly;
      const d = dx * dx + dy * dy;
      if (d < bd) {
        bd = d;
        best = h;
      }
    }
    const hover = { sampleId: id, index: best, x: hit.px[0], y: hit.px[1], ...this.describe(sd, best, s) };
    s.set({ hover });
    void this.cache.getId(id, best, smp.idBlock).then((cid) => {
      const cur = store.getState().hover;
      if (cur && cur.sampleId === id && cur.index === best && cur.id !== cid) store.getState().set({ hover: { ...cur, id: cid } });
    });
  };

  /** Everything worth showing for one cell: all categorical annotations, the colored feature, the filter feature. */
  private describe(sd: SampleData, i: number, s: ViewerState): { rows: { label: string; value: string; swatch?: string }[] } {
    const rows: { label: string; value: string; swatch?: string }[] = [];
    if (!this.manifest) return { rows };
    const smp = this.samplesById.get(sd.id)!;
    const fmt = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
    const geneRow = (gene: string, prefix = "") => {
      const label = this.featureLabel(gene);
      if (!sd.geneIndex.has(gene)) return rows.push({ label: prefix + label, value: "not measured" });
      const a = this.cache.getGeneSync(sd.id, gene);
      const gmax = this.geneGmax.get(`${sd.id}:${gene}`);
      if (!a || gmax === undefined) return rows.push({ label: prefix + label, value: "…" });
      const v = (a.value[i] / 255) * gmax;
      return rows.push({ label: prefix + label, value: a.value[i] === 0 ? "0" : fmt(v) });
    };
    if (s.color?.kind === "gene") geneRow(s.color.gene);
    if (s.filter?.kind === "gene" && (s.color?.kind !== "gene" || s.filter.gene !== s.color.gene)) geneRow(s.filter.gene, "filter: ");
    for (const f of this.manifest.fields) {
      if (!smp.fields.includes(f.id)) continue;
      if (f.type === "categorical") {
        const codes = sd.cat.get(f.id);
        if (!codes) {
          void this.cache.getCategorical(sd.id, f.id).then(() => this.requestLayers());
          rows.push({ label: f.name, value: "…" });
          continue;
        }
        const v = this.manifest.vocabularies[f.vocabulary];
        const c = codes[i];
        rows.push({ label: f.name, value: v.categories[c] ?? "?", swatch: v.colors[c] });
      } else if (s.color?.kind === "field" && s.color.field === f.id) {
        const vals = sd.num.get(f.id);
        rows.push({ label: f.name, value: vals ? fmt(vals[i]) : "…" });
      }
    }
    return { rows };
  }

  private featureLabel(gene: string): string {
    const groups = store.getState().features?.groups ?? [];
    for (const g of groups) {
      const f = g.features.find((x) => x.id === gene);
      if (f) return f.label;
    }
    return gene;
  }

  // ---------------------------------------------------------------- lasso selection
  private lassoPts: { view: ViewId; world: [number, number][] } | null = null;
  private lassoActive = false;
  selection: { view: ViewId; samples: Map<string, Uint32Array>; highlight: Map<string, Float32Array>; polygon: [number, number][] } | null = null;
  private selectionVersion = 0;

  private onPointerDown = (e: PointerEvent) => {
    if (store.getState().tool !== "lasso" || e.button !== 0) return;
    const hit = this.worldFromEvent(e);
    if (!hit) return;
    this.lassoActive = true;
    this.lassoPts = { view: hit.view, world: [hit.world] };
    this.container.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  };

  private onPointerUp = (e: PointerEvent) => {
    if (!this.lassoActive || !this.lassoPts) return;
    this.lassoActive = false;
    const { view, world } = this.lassoPts;
    this.lassoPts = null;
    if (world.length >= 3) this.applyLasso(view, world);
    else this.requestLayers();
    e.preventDefault();
  };

  applyLasso(view: ViewId, polygon: [number, number][]) {
    const L = this.layouts[view];
    if (!L) return;
    const xs = polygon.map((p) => p[0]);
    const ys = polygon.map((p) => p[1]);
    const pb: [number, number, number, number] = [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    const samples = new Map<string, Uint32Array>();
    const highlight = new Map<string, Float32Array>();
    for (const [id, p] of L.placements) {
      if (!intersects(p.worldBbox, pb)) continue;
      const sd = this.cache.samples.get(id);
      if (!sd?.index) continue;
      const inv = new Matrix4(p.modelMatrix).invert();
      const local = polygon.map((pt) => inv.transformAsPoint([pt[0], pt[1], 0]).slice(0, 2) as [number, number]);
      const lx = local.map((q) => q[0]);
      const ly = local.map((q) => q[1]);
      const cand = sd.index.range(Math.min(...lx), Math.min(...ly), Math.max(...lx), Math.max(...ly));
      const sel: number[] = [];
      for (const i of cand) if (pointInPolygon(sd.xy[i * 2], sd.xy[i * 2 + 1], local)) sel.push(i);
      if (!sel.length) continue;
      const idx = Uint32Array.from(sel);
      samples.set(id, idx);
      const hl = new Float32Array(sel.length * 2);
      for (let k = 0; k < sel.length; k++) {
        hl[k * 2] = sd.xy[sel[k] * 2];
        hl[k * 2 + 1] = sd.xy[sel[k] * 2 + 1];
      }
      highlight.set(id, hl);
    }
    this.selection = { view, samples, highlight, polygon };
    this.selectionVersion++;
    store.getState().set({ tool: "pan" });
    this.updateSelectionSummary();
    this.requestLayers();
  }

  clearSelection() {
    this.selection = null;
    store.getState().set({ selectionSummary: null });
    this.requestLayers();
  }

  /** Composition and gene stats of the current selection (recomputed as arrays arrive). */
  updateSelectionSummary() {
    const sel = this.selection;
    const s = store.getState();
    if (!sel || !this.manifest) return;
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
      const sd = this.cache.samples.get(id)!;
      const smp = this.samplesById.get(id)!;
      perSample.push({ id, name: smp.name, n: idx.length });
      total += idx.length;
      for (const f of this.manifest.fields) {
        if (f.type !== "categorical" || !smp.fields.includes(f.id)) continue;
        const codes = sd.cat.get(f.id);
        if (!codes) {
          void this.cache.getCategorical(id, f.id).then(() => this.updateSelectionSummary());
          continue;
        }
        const n = this.manifest.vocabularies[f.vocabulary].categories.length;
        const acc = (fieldCounts[f.id] ??= new Float64Array(n));
        for (const i of idx) if (codes[i] < n) acc[codes[i]]++;
      }
      if (gene) {
        const g = this.cache.getGeneSync(id, gene)?.value;
        const gmax = this.geneGmax.get(`${id}:${gene}`);
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
        version: this.selectionVersion,
        total,
        perSample,
        fields,
        gene: gene && gN ? { name: this.featureLabel(gene), mean: gSum / gN, frac: gPos / gN, meanAll: aN ? aSum / aN : 0, fracAll: aN ? aPos / aN : 0 } : null,
      },
    });
  }

  /** Download the selected cell ids as CSV (sample, cell_id). */
  async exportSelectionCSV() {
    const sel = this.selection;
    if (!sel) return;
    const lines = ["sample,cell_id"];
    for (const [id, idx] of sel.samples) {
      const smp = this.samplesById.get(id)!;
      for (const i of idx) lines.push(`${id},${(await this.cache.getId(id, i, smp.idBlock)) ?? i}`);
    }
    const blob = new Blob([lines.join("\n")], { type: "text/csv" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${this.manifest?.id ?? "selection"}-selection.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }

  private selectionLayers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const out: any[] = [];
    const common = { pickable: false, viewId: view, parameters: { depthWriteEnabled: false, depthCompare: "always" } };
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
    if (this.selection && this.selection.view === view) {
      for (const [id, hl] of this.selection.highlight) {
        const p = L.placements.get(id);
        const smp = this.samplesById.get(id);
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
          data: [{ path: [...this.selection.polygon, this.selection.polygon[0]] }],
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

  private gmaxCache = new Map<string, number>();
  private gmaxSync(sampleId: string, gi: number): number {
    const key = `${sampleId}:${gi}`;
    const v = this.gmaxCache.get(key);
    if (v !== undefined) return v;
    void this.cache.worker.gmax(sampleId, gi).then((g) => this.gmaxCache.set(key, g));
    return 0;
  }

  private onClick = (e: MouseEvent) => {
    const hit = this.worldFromEvent(e);
    if (!hit) return;
    store.getState().set({ selected: this.sampleAt(hit.view, hit.world[0], hit.world[1]), activeView: hit.view });
  };

  private onDblClick = (e: MouseEvent) => {
    const hit = this.worldFromEvent(e);
    if (!hit) return;
    const id = this.sampleAt(hit.view, hit.world[0], hit.world[1]);
    const s = store.getState();
    if (id && id !== s.focus) s.setFocus(id);
    else if (!id) s.setFocus(null);
  };

  private onKey = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    const s = store.getState();
    if (e.key === "ArrowRight" || e.key === "PageDown") {
      this.stepFocus(1);
      e.preventDefault();
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      this.stepFocus(-1);
      e.preventDefault();
    } else if (e.key === "Escape") {
      if (this.selection) this.clearSelection();
      else if (s.tool === "lasso") s.set({ tool: "pan" });
      else s.setFocus(null);
    } else if (e.key === "l") {
      s.set({ tool: s.tool === "lasso" ? "pan" : "lasso" });
    } else if (e.key === "Enter" && s.selected) {
      s.setFocus(s.selected);
    } else if (e.key === "f") {
      if (s.focus) this.focusSample(s.focus, true);
      else for (const v of VIEWS) if (this.rects[v]) this.fitAll(v, true);
    }
  };

  // ---------------------------------------------------------------- diagnostics
  private probeResolvers: ((p: { nonBackground: number; total: number }) => void)[] = [];

  private afterRender() {
    const now = performance.now();
    this.frameTimes.push(now);
    while (this.frameTimes.length && now - this.frameTimes[0] > 1000) this.frameTimes.shift();
    if (this.frameTimes.length % 10 === 0) {
      const fps = this.frameTimes.length;
      const t = store.getState().timings;
      if (Math.abs(t.fps - fps) >= 2) store.getState().set({ timings: { ...t, fps } });
    }
    if (this.wantProbe) {
      this.wantProbe = false;
      try {
        const gl = (this.deck as any).device?.gl as WebGL2RenderingContext | undefined;
        if (gl) {
          const w = gl.drawingBufferWidth;
          const h = gl.drawingBufferHeight;
          const row = new Uint8Array(w * 4);
          let nb = 0;
          let total = 0;
          for (let y = 0; y < h; y += 8) {
            gl.readPixels(0, y, w, 1, gl.RGBA, gl.UNSIGNED_BYTE, row);
            for (let i = 0; i < row.length; i += 4) {
              total++;
              if (row[i + 3] > 0 && (row[i] > 20 || row[i + 1] > 20 || row[i + 2] > 20)) nb++;
            }
          }
          this.lastProbe = { nonBackground: nb, total };
          const rs = this.probeResolvers;
          this.probeResolvers = [];
          rs.forEach((r) => r(this.lastProbe!));
        }
      } catch (e) {
        console.warn("pixel probe failed", e);
      }
    }
  }

  /** Resolves once no loads are pending and the layers reflect the current state. */
  whenIdle(): Promise<void> {
    return new Promise((resolve) => {
      const check = () => {
        if (store.getState().pending === 0 && store.getState().status !== "loading") {
          unsub();
          setTimeout(() => {
            this.buildLayers();
            this.deck.redraw("whenIdle");
            resolve();
          }, 0);
          return true;
        }
        return false;
      };
      const unsub = store.subscribe(() => void check());
      check();
    });
  }

  /** Reads back the framebuffer inside the next rendered frame (works without preserveDrawingBuffer). */
  pixelProbe(): Promise<{ nonBackground: number; total: number }> {
    return new Promise((resolve) => {
      this.probeResolvers.push(resolve);
      this.wantProbe = true;
      this.buildLayers();
      this.deck.redraw("probe");
      setTimeout(() => {
        const i = this.probeResolvers.indexOf(resolve);
        if (i >= 0) {
          this.probeResolvers.splice(i, 1);
          resolve(this.lastProbe ?? { nonBackground: 0, total: 0 });
        }
      }, 3000);
    });
  }
}

function transition() {
  return { transitionDuration: 400, transitionInterpolator: new LinearInterpolator({ transitionProps: ["target", "zoom"] }) };
}
function sameChannel(a: FilterSpec, b: FilterSpec) {
  return a.kind === b.kind && (a.kind === "gene" ? a.gene === (b as any).gene : a.field === (b as any).field);
}
function filterRange(f: FilterSpec): [number, number] {
  return f.kind === "category" ? [0.5, 1] : f.range;
}
