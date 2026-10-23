/**
 * Owns the imperative deck.gl instance and coordinates the modules:
 *   Loader       manifest / samples / channel arrays        (loader.ts)
 *   LayerBuilder store state -> deck.gl layers              (layers.ts)
 *   Interaction  pointer, keyboard, hover tooltip           (interaction.ts)
 *   Selection    lasso, highlight, summary, CSV export      (selection.ts)
 *   Stats        counts, histograms, gene-by-annotation     (stats.ts)
 *   Blend        two-set gene scores                        (blend.ts)
 * The canvas is a list of panes (panes.ts) sharing one GL context: the tissue sections in one pane, or one
 * pane per group when split by a sample meta key, plus the embeddings' pane. Each pane is an orthographic
 * view with its own camera and layout; colour, filters and every other setting are shared.
 * React never touches the canvas; this class subscribes to the store directly.
 */
import { Deck, OrthographicView, LinearInterpolator } from "@deck.gl/core";
import { DataCache } from "../data/cache";
import type { Manifest, Sample } from "../data/manifest";
import { store, type ViewId, type ViewKind, type ViewRect, type ViewerState, type ViewState } from "../store/store";
import { Blend } from "./blend";
import { Interaction } from "./interaction";
import { RegionsManager } from "./regions";
import { LayerBuilder } from "./layers";
import { computeLayout, fitBbox, type LayoutResult } from "./layout";
import { Loader } from "./loader";
import { computePanes, paneInfo, paneRects, STACK_BELOW, unassignedSamples, type Pane } from "./panes";
import { Selection } from "./selection";
import { Stats } from "./stats";
import { composePNG } from "./exportPng";
import { sameChannel } from "./types";

export class ViewerController {
  deck: Deck<OrthographicView[]>;
  cache = new DataCache();
  manifest: Manifest | null = null;
  samplesById = new Map<string, Sample>();
  regions: RegionsManager;
  panes: Pane[] = [];
  layouts: Record<ViewId, LayoutResult | null> = {};
  viewStates: Record<ViewId, ViewState> = {};
  rects: Record<ViewId, ViewRect> = {};
  geneGmax = new Map<string, number>(); // `${sampleId}:${gene}` -> per-gene max (dequantization)
  geneGmin = new Map<string, number>(); // `${sampleId}:${gene}` -> per-gene min: 0, or -max for signed features
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
  private userMoved = new Set<ViewId>(); // panes whose camera the user (or the URL) set: kept across resizes

  constructor(public container: HTMLDivElement) {
    this.deck = new Deck({
      parent: container,
      views: this.makeViews(),
      viewState: this.viewStates as any,
      // a programmatic transition reports its frames here too, flagged inTransition; user input is everything else
      onViewStateChange: ({ viewState, viewId, interactionState }) => this.onViewState(viewId as ViewId, viewState as ViewState, !!interactionState?.inTransition),
      layerFilter: ({ layer, viewport }) => (layer.props as any).viewId === viewport.id,
      layers: [],
      useDevicePixels: true,
      getCursor: ({ isDragging }) => (store.getState().tool === "lasso" ? "crosshair" : isDragging ? "grabbing" : "crosshair"),
      onAfterRender: () => this.afterRender(),
      onResize: () => this.onResize(),
    });
    this.interaction = new Interaction(this);
    this.regions = new RegionsManager(this);
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
    if (this.vsTimer) window.clearTimeout(this.vsTimer);
    this.cache.dispose();
    this.deck.finalize();
  }

  /** Forget everything that belonged to the previous dataset: arrays, worker handles, scales, derived caches. */
  resetForDataset() {
    this.cache.dispose();
    this.cache = new DataCache();
    this.geneGmax.clear();
    this.geneGmin.clear();
    this.layersBuilder.reset();
    this.blend.invalidate();
    if (this.selection.current) this.selection.clear();
    this.layouts = {};
    this.userMoved.clear();
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

  // ---------------------------------------------------------------- panes
  paneOf(view: ViewId): Pane | undefined {
    return this.panes.find((p) => p.id === view);
  }
  kindOf(view: ViewId): ViewKind {
    return this.paneOf(view)?.kind ?? (view === "embedding" ? "embedding" : "spatial");
  }
  /** The pane a sample is drawn in, or null when the current split leaves it out. */
  viewOf(sampleId: string): ViewId | null {
    for (const p of this.panes) if (p.samples.some((s) => s.id === sampleId)) return p.id;
    return null;
  }
  groupPanes(): Pane[] {
    return this.panes.filter((p) => p.group);
  }
  private stacked(): boolean {
    return this.groupPanes().length >= 2 && this.container.clientWidth < STACK_BELOW;
  }

  /** Panes and their pixel rectangles from the manifest and the split state; published for the UI. */
  computeRects(): Record<ViewId, ViewRect> {
    const [w, h] = this.viewportSize();
    const s = store.getState();
    if (!this.manifest) {
      this.panes = [];
      return {};
    }
    this.panes = computePanes(this.manifest, s.splitBy, s.split);
    return paneRects(this.panes, w, h, s.splitBy, s.split, this.stacked());
  }

  private makeViews(): OrthographicView[] {
    this.rects = this.computeRects();
    for (const p of this.panes) this.viewStates[p.id] ??= { target: [0, 0, 0], zoom: 0 };
    for (const id of Object.keys(this.layouts)) if (!this.rects[id]) delete this.layouts[id];
    this.publishPanes();
    return this.panes
      .filter((p) => this.rects[p.id])
      .map(
        (p) =>
          new OrthographicView({
            id: p.id,
            flipY: true,
            x: this.rects[p.id].x,
            y: this.rects[p.id].y,
            width: this.rects[p.id].w,
            height: this.rects[p.id].h,
            controller: store.getState().tool === "lasso" ? false : { dragRotate: false, doubleClickZoom: false, inertia: 250, keyboard: false },
          }),
      );
  }

  private publishPanes() {
    const s = store.getState();
    const info = this.manifest ? paneInfo(this.panes, this.manifest, this.hiddenBase(s)) : [];
    const active = this.panes.some((p) => p.id === s.activeView) ? s.activeView : (this.panes.find((p) => p.kind === "spatial") ?? this.panes[0])?.id;
    s.set({ viewRects: this.rects, panes: info, ...(active && active !== s.activeView ? { activeView: active } : {}) });
  }

  /** Recompute panes and rectangles and push them to deck. */
  applyViews() {
    this.deck.setProps({ views: this.makeViews(), viewState: this.viewStates as any });
  }

  viewSize(v: ViewId): [number, number] {
    const r = this.rects[v];
    return [Math.max(1, r?.w ?? 1), Math.max(1, r?.h ?? 1)];
  }

  viewportSize(): [number, number] {
    return [Math.max(1, this.container.clientWidth), Math.max(1, this.container.clientHeight)];
  }

  /** Samples hidden by the sample list or the platform bar. */
  hiddenBase(s: ViewerState): Set<string> {
    const hidden = new Set(s.hiddenSamples);
    if (s.platforms && this.manifest) {
      const allowed = new Set(s.platforms);
      for (const smp of this.manifest.samples) if (smp.kind !== "embedding" && !allowed.has(smp.platform)) hidden.add(smp.id);
    }
    return hidden;
  }

  /** Samples not drawn: hidden by the user, or left out by the current split (no value of the key). */
  hiddenSampleSet(s: ViewerState): Set<string> {
    const hidden = this.hiddenBase(s);
    if (this.manifest && s.splitBy) for (const smp of unassignedSamples(this.manifest, s.splitBy)) hidden.add(smp.id);
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
    if (s.splitBy !== prev.splitBy || s.split !== prev.split) {
      const regrouped = s.splitBy?.key !== prev.splitBy?.key || s.splitBy?.groups !== prev.splitBy?.groups;
      if (regrouped) this.userMoved.clear(); // new panes start fitted; a dragged divider keeps the cameras
      this.applyViews();
      this.relayoutAll(true);
      if (s.splitBy !== prev.splitBy) {
        if (s.color?.kind === "field") this.stats.updateCategoryCounts(s.color.field);
        this.stats.updateGroupStats();
        this.stats.updateFilterHistogram();
      }
      this.requestLayers();
    }
    if (s.matchScale !== prev.matchScale && s.matchScale) this.applyMatchScale(this.paneOf(s.activeView)?.group ? s.activeView : undefined);
    if (s.tool !== prev.tool) {
      this.applyViews();
      if (s.tool === "pan") this.selection.cancelDrawing();
      this.requestLayers();
    }
    if (s.groupField !== prev.groupField) {
      this.generation++;
      void this.loader.loadChannels();
    }
    if (s.regions !== prev.regions) this.regions.onChange(prev.regions);
    if (s.sampleStatus !== prev.sampleStatus && s.regions.groups.length) {
      for (const [id, st] of Object.entries(s.sampleStatus)) if (st === "ready" && prev.sampleStatus[id] !== "ready") this.regions.recompute(id);
    }
    if (s.layoutMode !== prev.layoutMode || s.hiddenSamples !== prev.hiddenSamples || s.platforms !== prev.platforms) {
      this.publishPanes();
      this.relayoutAll(true);
      if (s.color?.kind === "field") this.stats.updateCategoryCounts(s.color.field);
      this.stats.updateGroupStats();
      this.stats.updateFilterHistogram();
      this.requestLayers();
    }
    if (s.focus !== prev.focus) {
      if (s.focus) this.focusSample(s.focus, true);
      else this.fitAll((prev.focus && this.viewOf(prev.focus)) || s.activeView, true);
    }
    if (
      s.colormap !== prev.colormap ||
      s.vrange !== prev.vrange ||
      s.hideZeros !== prev.hideZeros ||
      s.hiddenCategories !== prev.hiddenCategories ||
      s.imageOpacity !== prev.imageOpacity ||
      s.showImages !== prev.showImages ||
      s.hiddenChannels !== prev.hiddenChannels ||
      s.pointScale !== prev.pointScale ||
      s.scalePerSample !== prev.scalePerSample ||
      s.selected !== prev.selected ||
      s.sampleStatus !== prev.sampleStatus ||
      s.outline !== prev.outline ||
      s.cellShapes !== prev.cellShapes ||
      s.molecules !== prev.molecules ||
      s.moleculeGenes !== prev.moleculeGenes
    ) {
      this.requestLayers();
    }
  }

  // ---------------------------------------------------------------- layout / camera
  relayoutAll(animate: boolean) {
    for (const p of this.panes) if (this.rects[p.id]) this.relayout(p.id, animate);
    // group panes share one grid shape, so the same section index sits in the same place in every pane
    const gp = this.groupPanes().filter((p) => this.layouts[p.id]);
    if (gp.length >= 2 && !this.manifest?.layout.columns && store.getState().layoutMode === "grid") {
      const largest = gp.reduce((a, b) => (this.layouts[b.id]!.placements.size > this.layouts[a.id]!.placements.size ? b : a));
      const cols = this.layouts[largest.id]!.ncols;
      for (const p of gp) if (p.id !== largest.id && this.layouts[p.id]!.ncols !== cols) this.relayout(p.id, animate, cols);
    }
    const s = store.getState();
    if (s.focus && !this.viewOf(s.focus)) s.set({ focus: null }); // the split left the focused section out
    if (s.matchScale) this.applyMatchScale();
  }

  relayout(view: ViewId, animate: boolean, columns?: number) {
    const pane = this.paneOf(view);
    if (!this.manifest || !pane || !this.rects[view]) return;
    const s = store.getState();
    const [w, h] = this.viewSize(view);
    this.layouts[view] = computeLayout(pane.samples, this.manifest.layout.order, s.layoutMode, this.manifest.layout.gutterFraction, w / h, this.hiddenBase(s), columns ?? this.manifest.layout.columns);
    this.selection.onRelayout(view);
    const focusHere = s.focus && this.viewOf(s.focus) === view;
    if (focusHere && this.layouts[view]!.placements.has(s.focus!)) this.focusSample(s.focus!, animate);
    else if (focusHere) s.set({ focus: null });
    else if (!this.userMoved.has(view)) this.fitAll(view, animate, false);
    this.requestLayers();
  }

  /** Fit a pane to its sections. `propagate` carries the new zoom to the other group panes (match scale); callers
   *  that fit every pane in turn pass false and apply the shared scale once afterwards. */
  fitAll(view: ViewId, animate: boolean, propagate = true) {
    const L = this.layouts[view];
    if (!L || !this.rects[view]) return;
    const [w, h] = this.viewSize(view);
    this.setViewState(view, { ...fitBbox(L.worldBbox, w, h, 0.04), ...(animate ? transition() : {}) }, propagate);
  }

  fitAllPanes(animate: boolean) {
    this.userMoved.clear();
    for (const p of this.panes) this.fitAll(p.id, animate, false);
    if (store.getState().matchScale) this.applyMatchScale();
  }

  focusSample(id: string, animate: boolean) {
    const view = this.viewOf(id);
    if (!view) return;
    const p = this.layouts[view]?.placements.get(id);
    if (!p || !this.rects[view]) return;
    this.userMoved.add(view);
    this.setViewState(view, { ...fitBbox(p.worldBbox, w(this, view), h(this, view), 0.06), ...(animate ? transition() : {}) }, true);
    if (store.getState().activeView !== view) store.getState().set({ activeView: view });
  }

  /** Step through the sections of the active pane (the one the pointer last touched, or the focused one's). */
  stepFocus(delta: number) {
    const s = store.getState();
    const view = (s.focus && this.viewOf(s.focus)) || (this.paneOf(s.activeView) ? s.activeView : this.panes.find((p) => p.kind === "spatial")?.id);
    if (!view) return;
    const ids = [...(this.layouts[view]?.placements.keys() ?? [])];
    if (!ids.length) return;
    const i = s.focus ? ids.indexOf(s.focus) : -1;
    s.setFocus(ids[(i + delta + ids.length) % ids.length]);
  }

  setViewState(view: ViewId, vs: ViewState, propagate = false) {
    this.viewStates = { ...this.viewStates, [view]: vs };
    if (propagate && this.paneOf(view)?.group && store.getState().matchScale) {
      this.applyMatchScale(view); // pushes the state to deck as well
      return;
    }
    this.deck.setProps({ viewState: this.viewStates as any });
    this.publishScale(view, vs.zoom);
    this.requestLayers();
    this.publishCameras();
  }

  /** Group panes share one scale. With a `lead` pane (the one the user zoomed) the others take its zoom; without
   *  one (panes just fitted) the most zoomed-out pane leads, so no group is cut off. */
  applyMatchScale(lead?: ViewId) {
    const gp = this.groupPanes().filter((p) => this.layouts[p.id] && this.viewStates[p.id]);
    if (gp.length < 2) return;
    const leadState = lead ? this.viewStates[lead] : gp.map((p) => this.viewStates[p.id]).reduce((a, b) => (b.zoom < a.zoom ? b : a));
    const zoom = leadState.zoom;
    // the followers animate with the lead when it animates (a focus), else jump with it (a wheel zoom)
    const anim = leadState.transitionDuration ? { transitionDuration: leadState.transitionDuration, transitionInterpolator: leadState.transitionInterpolator } : {};
    for (const p of gp) {
      const o = this.viewStates[p.id];
      if (p.id !== lead && o && Math.abs(o.zoom - zoom) > 1e-6) this.viewStates = { ...this.viewStates, [p.id]: { target: o.target, zoom, ...anim } };
      this.publishScale(p.id, zoom);
    }
    this.deck.setProps({ viewState: this.viewStates as any });
    this.requestLayers();
    this.publishCameras();
  }

  private vsTimer: number | null = null;
  /** Deck reports both user interaction and the end of a programmatic transition here; only the former is a
   *  "move" that pins the camera and, with match scale on, carries its zoom to the other group panes. */
  private onViewState(view: ViewId, vs: ViewState, inTransition = false) {
    this.viewStates = { ...this.viewStates, [view]: vs };
    const pane = this.paneOf(view);
    if (!inTransition) this.userMoved.add(view);
    if (!inTransition && pane?.group && store.getState().matchScale) {
      for (const p of this.groupPanes()) {
        if (p.id === view || !this.layouts[p.id]) continue;
        const o = this.viewStates[p.id];
        if (o && Math.abs(o.zoom - vs.zoom) > 1e-6) {
          this.viewStates = { ...this.viewStates, [p.id]: { target: o.target, zoom: vs.zoom } }; // same scale, its own centre
          this.publishScale(p.id, vs.zoom);
        }
      }
    }
    this.deck.setProps({ viewState: this.viewStates as any });
    this.publishScale(view, vs.zoom);
    this.requestLayers();
    this.publishCameras();
  }

  /** The cameras the URL carries: the single tissue pane's as `v`, the group panes' as `pv`; written after a pause. */
  private publishCameras() {
    if (this.vsTimer) window.clearTimeout(this.vsTimer);
    this.vsTimer = window.setTimeout(() => {
      this.vsTimer = null;
      const s = store.getState();
      const patch: Partial<ViewerState> = {};
      const single = this.viewStates.spatial;
      if (this.paneOf("spatial") && single) patch.viewState = { target: single.target, zoom: single.zoom };
      const gp = this.groupPanes();
      if (gp.length) patch.paneCameras = gp.map((p) => ({ target: this.viewStates[p.id].target, zoom: this.viewStates[p.id].zoom }));
      else if (s.paneCameras) patch.paneCameras = null;
      s.set(patch);
    }, 150);
  }

  /** Cameras from the URL, applied once the panes exist: `v` to the tissue pane, `pv` to the group panes in order. */
  applyStoredCameras(s: ViewerState) {
    if (s.viewState && this.paneOf("spatial")) {
      this.userMoved.add("spatial");
      this.setViewState("spatial", s.viewState);
    }
    // the URL's pane cameras stand as they are, even with match scale on: that is what the link showed
    const gp = this.groupPanes();
    if (s.paneCameras && gp.length) {
      gp.forEach((p, i) => {
        const cam = s.paneCameras![i];
        if (cam) {
          this.userMoved.add(p.id);
          this.setViewState(p.id, { target: cam.target, zoom: cam.zoom });
        }
      });
    }
  }

  /** px per world unit (µm) per pane, for the scale bar; only published when it changes noticeably. */
  private publishScale(view: ViewId, zoom: number) {
    const px = Math.pow(2, zoom);
    const cur = store.getState().viewPx[view];
    if (!cur || Math.abs(px / cur - 1) > 0.005) store.getState().set({ viewPx: { ...store.getState().viewPx, [view]: px } });
  }

  private onResize() {
    if (!this.manifest) return;
    const wasStacked = this.groupPanes().length >= 2 && Object.values(this.rects).every((r) => r.x === 0);
    this.applyViews();
    const s = store.getState();
    const stackedChanged = wasStacked !== this.stacked();
    if (stackedChanged || this.panes.some((p) => this.rects[p.id] && !this.layouts[p.id])) {
      this.relayoutAll(false);
    } else {
      for (const p of this.panes) {
        if (!this.rects[p.id]) continue;
        if (s.focus && this.viewOf(s.focus) === p.id) this.focusSample(s.focus, false);
        else if (!this.userMoved.has(p.id)) this.fitAll(p.id, false, false);
      }
      if (s.matchScale && !this.groupPanes().some((p) => this.userMoved.has(p.id))) this.applyMatchScale();
    }
    this.requestLayers();
  }

  /** World-space rectangle currently visible in a pane. */
  viewBbox(view: ViewId): [number, number, number, number] {
    const [vw, vh] = this.viewSize(view);
    const vs = this.viewStates[view] ?? { target: [0, 0, 0], zoom: 0 };
    const scale = Math.pow(2, vs.zoom);
    const [cx, cy] = vs.target;
    return [cx - vw / 2 / scale, cy - vh / 2 / scale, cx + vw / 2 / scale, cy + vh / 2 / scale];
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
        composePNG(this.deck.getCanvas() as HTMLCanvasElement, this.container, this.panes, this.rects);
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

const w = (c: ViewerController, v: ViewId) => c.viewSize(v)[0];
const h = (c: ViewerController, v: ViewId) => c.viewSize(v)[1];

function transition() {
  return { transitionDuration: 400, transitionInterpolator: new LinearInterpolator({ transitionProps: ["target", "zoom"] }) };
}
