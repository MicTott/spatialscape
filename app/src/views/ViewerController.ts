/**
 * Owns the imperative deck.gl instance and coordinates the modules:
 *   Loader       manifest / samples / channel arrays        (loader.ts)
 *   LayerBuilder store state -> deck.gl layers              (layers.ts)
 *   Interaction  pointer, keyboard, hover tooltip           (interaction.ts)
 *   Selection    lasso, highlight, summary, CSV export      (selection.ts)
 *   Stats        counts, histograms, gene-by-annotation     (stats.ts)
 *   Blend        two-set gene scores                        (blend.ts)
 * Two orthographic views share one GL context: "spatial" (tissue mosaic) and "embedding" (UMAPs).
 * React never touches the canvas; this class subscribes to the store directly.
 */
import { Deck, OrthographicView, LinearInterpolator } from "@deck.gl/core";
import { DataCache } from "../data/cache";
import type { Manifest, Sample } from "../data/manifest";
import { store, type ViewId, type ViewerState, type ViewState } from "../store/store";
import { Blend } from "./blend";
import { Interaction } from "./interaction";
import { LayerBuilder } from "./layers";
import { computeLayout, fitBbox, type LayoutResult } from "./layout";
import { Loader } from "./loader";
import { Selection } from "./selection";
import { Stats } from "./stats";
import { composePNG } from "./exportPng";
import { sameChannel, VIEWS, type ViewRect } from "./types";

export class ViewerController {
  deck: Deck<OrthographicView[]>;
  cache = new DataCache();
  manifest: Manifest | null = null;
  samplesById = new Map<string, Sample>();
  layouts: Record<ViewId, LayoutResult | null> = { spatial: null, embedding: null };
  viewStates: Record<ViewId, ViewState> = { spatial: { target: [0, 0, 0], zoom: 0 }, embedding: { target: [0, 0, 0], zoom: 0 } };
  rects: Partial<Record<ViewId, ViewRect>> = {};
  geneGmax = new Map<string, number>(); // `${sampleId}:${gene}` -> per-gene max (dequantization)
  generation = 0; // bumped whenever color/filter/group change so stale loads are ignored
  destroyed = false;

  readonly loader = new Loader(this);
  readonly layersBuilder = new LayerBuilder(this);
  readonly stats = new Stats(this);
  readonly selection = new Selection(this);
  readonly blend = new Blend(this);
  readonly interaction: Interaction;

  private raf: number | null = null;
  private unsub: () => void;
  private frameTimes: number[] = [];
  private lastProbe: { nonBackground: number; total: number } | null = null;
  private wantProbe = false;
  private wantCapture = false;
  private captureResolvers: (() => void)[] = [];
  private probeResolvers: ((p: { nonBackground: number; total: number }) => void)[] = [];

  constructor(public container: HTMLDivElement) {
    this.deck = new Deck({
      parent: container,
      views: this.makeViews(),
      viewState: this.viewStates as any,
      onViewStateChange: ({ viewState, viewId }) => this.onViewState(viewId as ViewId, viewState as ViewState),
      layerFilter: ({ layer, viewport }) => (layer.props as any).viewId === viewport.id,
      layers: [],
      useDevicePixels: true,
      getCursor: ({ isDragging }) => (store.getState().tool === "lasso" ? "crosshair" : isDragging ? "grabbing" : "crosshair"),
      onAfterRender: () => this.afterRender(),
      onResize: () => this.onResize(),
    });
    this.interaction = new Interaction(this);
    this.unsub = store.subscribe((s, prev) => this.onStore(s, prev));
  }

  destroy() {
    this.destroyed = true;
    this.interaction.destroy();
    this.unsub();
    if (this.raf != null) {
      cancelAnimationFrame(this.raf);
      clearTimeout(this.raf);
      this.raf = null;
    }
    this.deck.finalize();
  }

  // ---------------------------------------------------------------- public API used by the UI and tests
  storeState() {
    return store.getState();
  }
  /** Renders one frame and downloads it as a PNG with a legend and scale bar drawn on top. */
  exportPNG(): Promise<void> {
    return new Promise((resolve) => {
      this.captureResolvers.push(resolve);
      this.wantCapture = true;
      this.buildLayers();
      this.deck.redraw("capture");
      setTimeout(() => {
        const i = this.captureResolvers.indexOf(resolve);
        if (i >= 0) {
          this.captureResolvers.splice(i, 1);
          resolve();
        }
      }, 4000);
    });
  }
  load(url: string) {
    return this.loader.load(url);
  }
  applyLasso(view: ViewId, polygon: [number, number][]) {
    this.selection.apply(view, polygon);
  }
  clearSelection() {
    this.selection.clear();
  }
  exportSelectionCSV() {
    return this.selection.exportCSV();
  }
  describe(sd: Parameters<Interaction["describe"]>[0], i: number, s: ViewerState) {
    return this.interaction.describe(sd, i, s);
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
    store.getState().set({ viewRects: this.rects });
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

  /** Recompute view rectangles and push them to deck. */
  applyViews() {
    this.deck.setProps({ views: this.makeViews() });
  }

  viewSize(v: ViewId): [number, number] {
    const [, h] = this.viewportSize();
    return [Math.max(1, this.rects[v]?.w ?? 1), h];
  }

  viewportSize(): [number, number] {
    return [Math.max(1, this.container.clientWidth), Math.max(1, this.container.clientHeight)];
  }

  viewOf(sampleId: string): ViewId {
    return this.samplesById.get(sampleId)?.kind === "embedding" ? "embedding" : "spatial";
  }

  /** Samples hidden by the sample list or the platform bar. */
  hiddenSampleSet(s: ViewerState): Set<string> {
    const hidden = new Set(s.hiddenSamples);
    if (s.platforms && this.manifest) {
      const allowed = new Set(s.platforms);
      for (const smp of this.manifest.samples) if (smp.kind !== "embedding" && !allowed.has(smp.platform)) hidden.add(smp.id);
    }
    return hidden;
  }

  // ---------------------------------------------------------------- store reactions
  private onStore(s: ViewerState, prev: ViewerState) {
    if (s.color !== prev.color || s.filter !== prev.filter) {
      this.generation++;
      if (s.color !== prev.color && s.color && s.color.kind !== "field") this.loader.markGeneSwitch();
      void this.loader.loadChannels();
      if (s.filter !== prev.filter && s.filter && prev.filter && sameChannel(s.filter, prev.filter)) this.stats.updateFilterHistogram();
    }
    if (s.split !== prev.split) {
      this.applyViews();
      for (const v of VIEWS) if (this.rects[v]) this.relayout(v, true);
      this.requestLayers();
    }
    if (s.tool !== prev.tool) {
      this.applyViews();
      if (s.tool === "pan") this.selection.cancelDrawing();
      this.requestLayers();
    }
    if (s.groupField !== prev.groupField) {
      this.generation++;
      void this.loader.loadChannels();
    }
    if (s.layoutMode !== prev.layoutMode || s.hiddenSamples !== prev.hiddenSamples || s.platforms !== prev.platforms) {
      for (const v of VIEWS) if (this.rects[v]) this.relayout(v, true);
      if (s.color?.kind === "field") this.stats.updateCategoryCounts(s.color.field);
      this.stats.updateGroupStats();
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
      s.scalePerSample !== prev.scalePerSample ||
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
    this.layouts[view] = computeLayout(samples, this.manifest.layout.order, s.layoutMode, this.manifest.layout.gutterFraction, w / h, this.hiddenSampleSet(s));
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

  setViewState(view: ViewId, vs: ViewState) {
    this.viewStates = { ...this.viewStates, [view]: vs };
    this.deck.setProps({ viewState: this.viewStates as any });
    this.publishScale(view, vs.zoom);
    this.requestLayers();
  }

  private vsTimer: number | null = null;
  private onViewState(view: ViewId, vs: ViewState) {
    this.viewStates = { ...this.viewStates, [view]: vs };
    this.deck.setProps({ viewState: this.viewStates as any });
    this.publishScale(view, vs.zoom);
    this.requestLayers();
    if (view !== "spatial") return;
    if (this.vsTimer) window.clearTimeout(this.vsTimer);
    this.vsTimer = window.setTimeout(() => {
      store.getState().set({ viewState: { target: vs.target, zoom: vs.zoom } });
    }, 150);
  }

  /** px per world unit (µm) per view, for the scale bar; only published when it changes noticeably. */
  private publishScale(view: ViewId, zoom: number) {
    const px = Math.pow(2, zoom);
    const cur = store.getState().viewPx[view];
    if (!cur || Math.abs(px / cur - 1) > 0.005) store.getState().set({ viewPx: { ...store.getState().viewPx, [view]: px } });
  }

  private onResize() {
    if (!this.manifest) return;
    this.applyViews();
    const s = store.getState();
    for (const v of VIEWS) {
      if (!this.rects[v]) continue;
      if (s.focus && this.viewOf(s.focus) === v) this.focusSample(s.focus, false);
      else if (v === "embedding" || !s.viewState) this.fitAll(v, false);
    }
    this.requestLayers();
  }

  /** World-space rectangle currently visible in a view. */
  viewBbox(view: ViewId): [number, number, number, number] {
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

  buildLayers() {
    if (this.destroyed || !this.manifest) return;
    try {
      this.deck.setProps({ layers: this.layersBuilder.build() });
    } catch (e) {
      console.error("buildLayers failed", e);
    }
  }

  // ---------------------------------------------------------------- diagnostics
  private afterRender() {
    const now = performance.now();
    this.frameTimes.push(now);
    while (this.frameTimes.length && now - this.frameTimes[0] > 1000) this.frameTimes.shift();
    if (this.frameTimes.length % 10 === 0) {
      const fps = this.frameTimes.length;
      const t = store.getState().timings;
      if (Math.abs(t.fps - fps) >= 2) store.getState().set({ timings: { ...t, fps } });
    }
    if (this.wantCapture) {
      this.wantCapture = false;
      const rs = this.captureResolvers;
      this.captureResolvers = [];
      try {
        composePNG(this.deck.getCanvas() as HTMLCanvasElement, this.container, this.rects);
      } catch (e) {
        console.error("PNG export failed", e);
      }
      rs.forEach((r) => r());
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
