/** The genome panel's canvas: a deck.gl OrthographicView whose x axis is the chromosome (bp) and whose y axis is
 *  pixels from the top of the panel. Scroll zooms around the cursor (x only), drag pans, double-click zooms in.
 *  Rows, top to bottom: axis, one coverage track per category on a shared scale, peaks, gene models.
 *  Coverage polygons are built once per fetched window and scaled through a model matrix, so panning and
 *  autoscaling never retriangulate; peaks and genes are rebuilt only when the zoom or the window changes. */
import { Deck, LinearInterpolator, OrthographicView } from "@deck.gl/core";
import { LineLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import { Matrix4 } from "@math.gl/core";
import { binFor, chevronPositions, covers, MAX_PX_PER_BP, MIN_SPAN_BP, niceStep, packLanes, tickLabel, ticks, windowFor, type Gene, type Locus, type Peak } from "./model";

export interface CoverageTrack {
  id: string;
  name: string;
  url: string;
  color: [number, number, number];
}
export interface Span {
  chrom: string;
  start: number;
  end: number;
}
export type Hit = { kind: "gene"; gene: Gene } | { kind: "peak"; peak: Peak } | { kind: "track"; track: CoverageTrack; value: number } | null;
export interface HoverInfo {
  x: number;
  y: number;
  bp: number;
  hit: Hit;
}
export interface GenomeViewOptions {
  sizes: Map<string, number>; // chromosome lengths, in display order
  trackBin: number; // bp per bin in the bigWigs
  peaks: Map<string, Peak[]>; // per chromosome, sorted by start
  fetchBins: (url: string, chrom: string, start: number, bin: number, n: number) => Promise<Float32Array>;
  loadGenes: (chrom: string) => Promise<Gene[]>;
  onLocus: (l: Locus) => void;
  onHover: (h: HoverInfo | null) => void;
  onClick: (hit: Hit) => void;
  onScale: (yMax: number) => void;
  onError?: (message: string | null) => void; // tracks that could not be read, for the panel header
  smoothBp?: number; // display smoothing: rolling mean over this many bp, the same for every track (0 = raw bins)
}

export const DEFAULT_SMOOTH_BP = 200;

const AXIS_H = 22;
const PEAKS_H = 16;
const LANE_H = 24;
const LANES = 3;
const LABEL_PX = 6.3; // px per character of a gene name, for lane packing
const FONT = "Inter, system-ui, sans-serif";
type RGBA = [number, number, number, number];
const MUTED: RGBA = [139, 148, 158, 255];
const BORDER: RGBA = [48, 54, 61, 255];
const TEXT: RGBA = [201, 209, 217, 255];
const GENE = [122, 162, 216] as const;
const PEAK = [217, 119, 6] as const;
const ACCENT = [64, 196, 255] as const;

interface Cached {
  chrom: string;
  bin: number;
  start: number;
  end: number;
  values: Float32Array; // as fetched
  display: Float32Array; // smoothed for drawing and hovering (see smoothBp)
  polygon: Float64Array; // step outline in (bp, -value); the layer's model matrix maps it into its row
  data: Cached[]; // the layer's `data` prop: one stable array, so deck never re-tesselates on a pan
}

/** Centred rolling mean over `k` bins (k forced odd), the edges averaging what is there. A single noisy bin of a
 *  small group shrinks by k while a promoter-wide peak keeps its height, which is what makes lanes comparable. */
export function smooth(values: Float32Array, k: number): Float32Array {
  const n = values.length;
  if (k <= 1 || n === 0) return values;
  if (k % 2 === 0) k += 1;
  const half = (k - 1) / 2;
  const cum = new Float64Array(n + 1);
  for (let i = 0; i < n; i++) cum[i + 1] = cum[i] + values[i];
  const out = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const a = Math.max(0, i - half);
    const b = Math.min(n, i + half + 1);
    out[i] = (cum[b] - cum[a]) / (b - a);
  }
  return out;
}

function polygonFor(values: Float32Array, start: number, bin: number): Float64Array {
  const n = values.length;
  const out = new Float64Array((2 * n + 3) * 2);
  let k = 0;
  out[k++] = start;
  out[k++] = 0;
  for (let i = 0; i < n; i++) {
    const v = -values[i];
    out[k++] = start + i * bin;
    out[k++] = v;
    out[k++] = start + (i + 1) * bin;
    out[k++] = v;
  }
  out[k++] = start + n * bin;
  out[k++] = 0;
  out[k++] = start;
  out[k++] = 0;
  return out;
}

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2);

export class GenomeView {
  deck: Deck<OrthographicView[]>;
  width = 1;
  height = 1;
  chrom: string;
  start: number;
  end: number;
  tracks: CoverageTrack[] = [];
  genes: Gene[] = [];
  peaks: Peak[] = [];
  highlight: Span | null = null;
  yMax = 1;
  smoothBp = DEFAULT_SMOOTH_BP;
  private cache = new Map<string, Cached>();
  private inflight = new Set<string>();
  private errors = new Map<string, string>(); // track id -> why it could not be read (no retries until the tracks change)
  private gen = 0;
  private fetchTimer: number | null = null;
  private frame: number | null = null;
  private lanes: Gene[][] = [];
  private annot: { pxPerBp: number; start: number; end: number; layers: unknown[]; long: { gene: Gene; y: number }[] } | null = null;
  private hoverHit: Hit = null;
  private destroyed = false;

  constructor(
    public container: HTMLDivElement,
    private opts: GenomeViewOptions,
  ) {
    const first = opts.sizes.keys().next().value as string;
    this.smoothBp = opts.smoothBp ?? DEFAULT_SMOOTH_BP;
    this.chrom = first;
    this.start = 0;
    this.end = opts.sizes.get(first)!;
    this.peaks = opts.peaks.get(first) ?? [];
    this.deck = new Deck({
      parent: container,
      views: [new OrthographicView({ id: "genome", flipY: true, controller: { zoomAxis: "X", dragRotate: false, keyboard: false, inertia: 300, doubleClickZoom: true } as any })],
      viewState: this.viewState() as any,
      onViewStateChange: ({ viewState }) => this.onViewState(viewState as any),
      layers: [],
      useDevicePixels: true,
      getCursor: ({ isDragging }) => (isDragging ? "grabbing" : this.hoverHit && this.hoverHit.kind !== "track" ? "pointer" : "default"),
      onHover: (info) => this.hover(info.x, info.y),
      onClick: (info) => this.opts.onClick(this.hitAt(info.x, info.y)),
      onResize: ({ width, height }) => this.resize(width, height),
    });
    container.addEventListener("pointerleave", this.leave);
    void this.loadChrom();
  }

  private leave = () => {
    this.hoverHit = null;
    this.opts.onHover(null);
  };

  destroy() {
    this.destroyed = true;
    this.gen++;
    if (this.frame != null) cancelAnimationFrame(this.frame);
    if (this.fetchTimer != null) clearTimeout(this.fetchTimer);
    this.container.removeEventListener("pointerleave", this.leave);
    this.deck.finalize();
  }

  locus(): Locus {
    return { chrom: this.chrom, start: this.start, end: this.end };
  }

  private len() {
    return this.opts.sizes.get(this.chrom)!;
  }
  private pxPerBp() {
    return this.width / (this.end - this.start);
  }
  private clampSpan(span: number) {
    const min = Math.min(this.len(), Math.max(MIN_SPAN_BP, this.width / MAX_PX_PER_BP));
    return Math.max(min, Math.min(this.len(), span));
  }
  private viewState() {
    const span = this.end - this.start;
    return { target: [this.start + span / 2, this.height / 2, 0], zoom: [Math.log2(this.width / span), 0] };
  }

  /** What the controller or a transition proposes, clamped: x only, inside the chromosome, between the zoom limits. */
  private onViewState(vs: { target: number[]; zoom: number | number[]; transitionDuration?: number; transitionInterpolator?: unknown; transitionEasing?: unknown }) {
    const len = this.len();
    const zx = Array.isArray(vs.zoom) ? vs.zoom[0] : vs.zoom;
    const span = this.clampSpan(this.width / 2 ** zx);
    const cx = span >= len ? len / 2 : Math.min(len - span / 2, Math.max(span / 2, vs.target[0]));
    this.start = cx - span / 2;
    this.end = cx + span / 2;
    // the controller's inertia arrives as an end state plus transition props: keep them, or a flick snaps instead of gliding
    const glide = vs.transitionDuration ? { transitionDuration: vs.transitionDuration, transitionInterpolator: vs.transitionInterpolator, transitionEasing: vs.transitionEasing } : {};
    this.deck.setProps({ viewState: { ...this.viewState(), ...glide } as any });
    this.changed();
  }

  /** Show a locus: animated when staying on the chromosome, a jump otherwise. */
  setLocus(l: Locus, animate = true) {
    const len = this.opts.sizes.get(l.chrom);
    if (len == null || this.destroyed) return;
    if (l.chrom !== this.chrom) {
      this.chrom = l.chrom;
      this.gen++;
      this.cache.clear();
      this.inflight.clear();
      this.genes = [];
      this.lanes = [];
      this.annot = null;
      this.peaks = this.opts.peaks.get(l.chrom) ?? [];
      animate = false;
      void this.loadChrom();
    }
    const span = this.clampSpan(l.end - l.start);
    const cx = span >= len ? len / 2 : Math.min(len - span / 2, Math.max(span / 2, (l.start + l.end) / 2));
    if (animate && this.width > 1) {
      this.deck.setProps({
        viewState: {
          target: [cx, this.height / 2, 0],
          zoom: [Math.log2(this.width / span), 0],
          transitionDuration: 500,
          transitionEasing: ease,
          transitionInterpolator: new LinearInterpolator({ transitionProps: ["target", "zoom"] }),
        } as any,
      });
    } else {
      this.start = cx - span / 2;
      this.end = cx + span / 2;
      this.deck.setProps({ viewState: this.viewState() as any });
      this.changed();
    }
  }

  private resize(width: number, height: number) {
    this.width = width;
    this.height = height;
    this.annot = null;
    this.setLocus(this.locus(), false);
  }

  setTracks(tracks: CoverageTrack[]) {
    const ids = new Set(tracks.map((t) => t.id));
    for (const id of [...this.cache.keys()]) if (!ids.has(id)) this.cache.delete(id);
    if (this.errors.size) {
      this.errors.clear();
      this.opts.onError?.(null);
    }
    this.tracks = tracks;
    this.annot = null; // rows move when the track count changes
    this.changed();
  }

  /** Change the display smoothing (bp): every cached track is re-smoothed, nothing is fetched again. */
  setSmooth(bp: number) {
    if (bp === this.smoothBp) return;
    this.smoothBp = bp;
    for (const c of this.cache.values()) {
      c.display = smooth(c.values, Math.round(bp / c.bin));
      c.polygon = polygonFor(c.display, c.start, c.bin);
      c.data = [c];
    }
    this.changed();
  }

  setHighlight(h: Span | null) {
    this.highlight = h;
    this.annot = null; // the highlighted peak changes colour
    this.changed();
  }

  private async loadChrom() {
    const chrom = this.chrom;
    const gen = this.gen;
    try {
      const genes = await this.opts.loadGenes(chrom);
      if (this.destroyed || gen !== this.gen || chrom !== this.chrom) return;
      this.genes = genes;
      this.annot = null;
      this.changed();
    } catch {
      /* no gene models for this chromosome */
    }
  }

  private changed() {
    if (this.destroyed) return;
    if (this.frame == null)
      this.frame = requestAnimationFrame(() => {
        this.frame = null;
        this.render();
        this.opts.onLocus(this.locus());
      });
    if (this.fetchTimer != null) clearTimeout(this.fetchTimer);
    this.fetchTimer = window.setTimeout(() => this.ensureData(), 60);
  }

  /** Fetch bins for every track whose cache does not cover the view at the wanted resolution. */
  private ensureData() {
    this.fetchTimer = null;
    if (this.destroyed || this.width <= 1) return;
    const bin = binFor(1 / this.pxPerBp(), this.opts.trackBin);
    const win = windowFor(this.start, this.end, bin, this.len());
    const n = Math.ceil((win.end - win.start) / bin);
    if (n <= 0) return;
    for (const t of this.tracks) {
      const c = this.cache.get(t.id);
      if (this.errors.has(t.id) || (c && covers(c, this.chrom, this.start, this.end, bin))) continue;
      const key = `${t.id}|${this.chrom}|${bin}|${win.start}|${n}`;
      if (this.inflight.has(key)) continue;
      this.inflight.add(key);
      const gen = this.gen;
      const chrom = this.chrom;
      this.opts
        .fetchBins(t.url, chrom, win.start, bin, n)
        .then((values) => {
          if (this.destroyed || gen !== this.gen || chrom !== this.chrom || !this.tracks.some((x) => x.id === t.id)) return;
          const prev = this.cache.get(t.id);
          const wantBin = binFor(1 / this.pxPerBp(), this.opts.trackBin);
          if (prev && prev.chrom === chrom && prev.bin < bin && covers(prev, chrom, this.start, this.end, wantBin)) return; // finer data arrived first: keep it
          const display = smooth(values, Math.round(this.smoothBp / bin));
          const entry: Cached = { chrom, bin, start: win.start, end: win.start + n * bin, values, display, polygon: polygonFor(display, win.start, bin), data: [] };
          entry.data = [entry];
          this.cache.set(t.id, entry);
          this.changed();
        })
        .catch((e) => {
          if (this.destroyed || gen !== this.gen) return;
          this.errors.set(t.id, `${t.name}: ${(e as Error)?.message ?? e}`);
          this.opts.onError?.([...this.errors.values()].join(" · "));
        })
        .finally(() => this.inflight.delete(key));
    }
  }

  private rows() {
    const n = this.tracks.length;
    const genesH = LANES * LANE_H + 6;
    const avail = this.height - AXIS_H - 2 - PEAKS_H - genesH - 10;
    const trackH = n ? Math.max(14, Math.min(120, Math.floor(avail / n))) : 0;
    const covTop = AXIS_H + 2;
    const covBottom = covTop + n * trackH;
    return { trackH, covTop, covBottom, peaksTop: covBottom + 4, genesTop: covBottom + 4 + PEAKS_H + 6 };
  }

  private computeYMax(): number {
    let m = 0;
    for (const t of this.tracks) {
      const c = this.cache.get(t.id);
      if (!c || c.chrom !== this.chrom) continue;
      const a = Math.max(0, Math.floor((this.start - c.start) / c.bin));
      const b = Math.min(c.values.length, Math.ceil((this.end - c.start) / c.bin));
      for (let i = a; i < b; i++) if (c.display[i] > m) m = c.display[i];
    }
    return m > 0 ? m : 1;
  }

  private render() {
    if (this.destroyed || this.width <= 1) return;
    const pxPerBp = this.pxPerBp();
    const r = this.rows();
    const { start, end } = this;
    this.yMax = this.computeYMax();
    this.opts.onScale(this.yMax);
    const layers: unknown[] = [];
    const span = end - start;
    const x0 = start - span;
    const x1 = end + span;
    const hl = this.highlight && this.highlight.chrom === this.chrom ? this.highlight : null;
    if (hl) {
      layers.push(
        new SolidPolygonLayer({
          id: "highlight",
          data: [hl],
          getPolygon: (d: Span) => [
            [d.start, 0],
            [d.end, 0],
            [d.end, this.height],
            [d.start, this.height],
          ],
          getFillColor: [...ACCENT, 26] as RGBA,
        }),
      );
    }
    const step = niceStep(span, this.width);
    const major = ticks(start, end, step);
    const minor = ticks(start, end, step / 5).filter((t) => Math.abs(t / step - Math.round(t / step)) > 1e-6);
    layers.push(
      new LineLayer({
        id: "rules",
        data: [
          { s: [x0, AXIS_H - 0.5], t: [x1, AXIS_H - 0.5] },
          { s: [x0, r.covBottom + 2], t: [x1, r.covBottom + 2] },
          { s: [x0, r.genesTop - 3], t: [x1, r.genesTop - 3] },
        ],
        getSourcePosition: (d: any) => d.s,
        getTargetPosition: (d: any) => d.t,
        getColor: BORDER,
        getWidth: 1,
        widthUnits: "pixels",
      }),
      new LineLayer({
        id: "ticks",
        data: [...major.map((t) => ({ x: t, h: 7 })), ...minor.map((t) => ({ x: t, h: 3 }))],
        getSourcePosition: (d: any) => [d.x, AXIS_H - 1],
        getTargetPosition: (d: any) => [d.x, AXIS_H - 1 - d.h],
        getColor: MUTED,
        getWidth: 1,
        widthUnits: "pixels",
      }),
      new TextLayer({
        id: "tick-labels",
        data: major,
        getPosition: (t: number) => [t, 3],
        getText: (t: number) => tickLabel(t + 1, step), // 1-based, like the locus readout and the hover tip
        getColor: MUTED,
        getSize: 10,
        sizeUnits: "pixels",
        getTextAnchor: "middle",
        getAlignmentBaseline: "top",
        fontFamily: FONT,
        characterSet: "auto",
        updateTriggers: { getText: step },
      }),
    );
    this.tracks.forEach((t, i) => {
      const c = this.cache.get(t.id);
      if (!c || c.chrom !== this.chrom) return;
      const top = r.covTop + i * r.trackH;
      const h = r.trackH - 4;
      layers.push(
        new SolidPolygonLayer({
          id: `cov-${t.id}`,
          data: c.data,
          getPolygon: (d: Cached) => d.polygon as any,
          positionFormat: "XY",
          getFillColor: [...t.color, 235] as RGBA,
          modelMatrix: new Matrix4().translate([0, top + h, 0]).scale([1, h / this.yMax, 1]),
        }),
      );
    });
    if (this.tracks.length) {
      layers.push(
        new TextLayer({
          id: "track-labels",
          data: this.tracks.map((t, i) => ({ t, y: r.covTop + i * r.trackH + 2 })),
          getPosition: (d: any) => [start + 6 / pxPerBp, d.y],
          getText: (d: any) => d.t.name,
          getColor: (d: any) => [...d.t.color, 255] as RGBA,
          getSize: 11,
          sizeUnits: "pixels",
          getTextAnchor: "start",
          getAlignmentBaseline: "top",
          fontFamily: FONT,
          fontWeight: 600,
          characterSet: "auto",
          background: true,
          getBackgroundColor: [14, 17, 22, 170],
          backgroundPadding: [4, 1, 4, 1],
        }),
      );
    }
    const a = this.annot;
    if (!a || Math.abs(Math.log2(pxPerBp / a.pxPerBp)) > 0.07 || start < a.start || end > a.end) this.annot = this.buildAnnotations(pxPerBp, r);
    layers.push(...this.annot!.layers);
    const longNames = this.annot!.long
      .map(({ gene, y }) => ({ x: (Math.max(gene.start, start) + Math.min(gene.end, end)) / 2, y, name: gene.name, ok: gene.end > start && gene.start < end }))
      .filter((d) => d.ok);
    if (longNames.length) layers.push(this.nameLayer("gene-names-long", longNames));
    this.deck.setProps({ layers: layers as any });
  }

  /** Peaks and gene models for one span each side of the view, at the current zoom. */
  private buildAnnotations(pxPerBp: number, r: ReturnType<GenomeView["rows"]>) {
    const span = this.end - this.start;
    const start = Math.max(0, this.start - span);
    const end = Math.min(this.len(), this.end + span);
    const minBp = 1.5 / pxPerBp;
    const widen = (s: number, e: number): [number, number] => (e - s >= minBp ? [s, e] : [(s + e) / 2 - minBp / 2, (s + e) / 2 + minBp / 2]);
    const hl = this.highlight && this.highlight.chrom === this.chrom ? this.highlight : null;
    const layers: unknown[] = [];
    const py = r.peaksTop + PEAKS_H / 2;
    const peaks = this.peaks.filter((p) => p.end > start && p.start < end);
    layers.push(
      new LineLayer({
        id: "peaks",
        data: peaks,
        getSourcePosition: (p: Peak) => [widen(p.start, p.end)[0], py],
        getTargetPosition: (p: Peak) => [widen(p.start, p.end)[1], py],
        getColor: (p: Peak) => (hl && p.start === hl.start && p.end === hl.end ? ([...ACCENT, 255] as RGBA) : ([...PEAK, 230] as RGBA)),
        getWidth: 9,
        widthUnits: "pixels",
      }),
    );
    const visible = this.genes.filter((g) => g.end > start && g.start < end);
    const dense = visible.length > 250;
    this.lanes = packLanes(visible, pxPerBp, LANES, dense ? null : (name) => name.length * LABEL_PX + 10);
    const bodies: { s: number[]; t: number[] }[] = [];
    const exons: { s: number[]; t: number[] }[] = [];
    const chevrons: { s: number[]; t: number[] }[] = [];
    const names: { x: number; y: number; name: string }[] = [];
    const long: { gene: Gene; y: number }[] = [];
    const dx = 3.5 / pxPerBp; // chevron arms: 3.5 px each way
    this.lanes.forEach((lane, li) => {
      const yc = r.genesTop + li * LANE_H + 8;
      for (const g of lane) {
        bodies.push({ s: [g.start, yc], t: [g.end, yc] });
        for (let i = 0; i < g.exonStarts.length; i++) {
          const [s, e] = widen(g.exonStarts[i], g.exonEnds[i]);
          exons.push({ s: [s, yc], t: [e, yc] });
        }
        if (dense) continue;
        if (g.strand) {
          const back = g.strand > 0 ? -dx : dx;
          for (const x of chevronPositions(g, pxPerBp, start, end)) chevrons.push({ s: [x + back, yc - 3.5], t: [x, yc] }, { s: [x + back, yc + 3.5], t: [x, yc] });
        }
        // a gene longer than most of the view keeps its label on screen (placed per frame); the rest sit at their centre
        if (g.end - g.start > 0.8 * span) long.push({ gene: g, y: yc + 9 });
        else names.push({ x: (g.start + g.end) / 2, y: yc + 9, name: g.name });
      }
    });
    layers.push(
      new LineLayer({ id: "gene-bodies", data: bodies, getSourcePosition: (d: any) => d.s, getTargetPosition: (d: any) => d.t, getColor: [...GENE, 170] as RGBA, getWidth: 1.5, widthUnits: "pixels" }),
      new LineLayer({ id: "exons", data: exons, getSourcePosition: (d: any) => d.s, getTargetPosition: (d: any) => d.t, getColor: [...GENE, 255] as RGBA, getWidth: 10, widthUnits: "pixels" }),
      new LineLayer({ id: "chevrons", data: chevrons, getSourcePosition: (d: any) => d.s, getTargetPosition: (d: any) => d.t, getColor: [...GENE, 230] as RGBA, getWidth: 1.5, widthUnits: "pixels" }),
      this.nameLayer("gene-names", names),
    );
    return { pxPerBp, start, end, layers, long };
  }

  private nameLayer(id: string, names: { x: number; y: number; name: string }[]) {
    return new TextLayer({
      id,
      data: names,
      getPosition: (d: any) => [d.x, d.y],
      getText: (d: any) => d.name,
      getColor: TEXT,
      getSize: 10.5,
      sizeUnits: "pixels",
      getTextAnchor: "middle",
      getAlignmentBaseline: "top",
      fontFamily: FONT,
      characterSet: "auto",
    });
  }

  private hover(x: number, y: number) {
    const hit = this.hitAt(x, y);
    this.hoverHit = hit;
    this.opts.onHover({ x, y, bp: this.start + x / this.pxPerBp(), hit });
  }

  /** What sits under a canvas pixel: a coverage track (with its value there), a peak, or a gene. */
  hitAt(x: number, y: number): Hit {
    const pxPerBp = this.pxPerBp();
    const bp = this.start + x / pxPerBp;
    const r = this.rows();
    const tol = 2 / pxPerBp;
    if (y >= r.covTop && y < r.covBottom && this.tracks.length) {
      const i = Math.min(this.tracks.length - 1, Math.floor((y - r.covTop) / r.trackH));
      const t = this.tracks[i];
      const c = this.cache.get(t.id);
      let value = 0;
      if (c && c.chrom === this.chrom) {
        const k = Math.floor((bp - c.start) / c.bin);
        if (k >= 0 && k < c.display.length) value = c.display[k];
      }
      return { kind: "track", track: t, value };
    }
    if (y >= r.peaksTop && y < r.peaksTop + PEAKS_H) {
      const p = this.peaks.find((p) => p.end + tol > bp && p.start - tol < bp);
      return p ? { kind: "peak", peak: p } : null;
    }
    if (y >= r.genesTop) {
      const lane = this.lanes[Math.floor((y - r.genesTop) / LANE_H)];
      const g = lane?.find((g) => g.end + tol > bp && g.start - tol < bp);
      return g ? { kind: "gene", gene: g } : null;
    }
    return null;
  }
}
