import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";
import type { FeatureList, LayoutMode, Manifest } from "../data/manifest";
import type { Locus } from "../genome/model";

export type BlendScheme = "yb" | "cm" | "rg";
export type CellShapes = "auto" | "dots" | "filled" | "outlined";
export type ColorSpec = { kind: "gene"; gene: string } | { kind: "field"; field: string } | { kind: "blend"; a: string[]; b: string[]; scheme: BlendScheme };
/** A lasso kept as part of a region group, in the coordinates of the section it was drawn on. */
export interface RegionPolygon {
  id: string;
  seq: number; // draw order across groups: the last lasso wins where polygons overlap
  sample: string;
  view: ViewKind; // the kind of pane it was drawn in (panes come and go; the sample is what anchors it)
  local: [number, number][];
}
export interface RegionGroup {
  id: string;
  name: string;
  color: string;
  polygons: RegionPolygon[];
}
export interface Regions {
  groups: RegionGroup[];
  active: string | null; // the group new lassos go into
  seq: number;
}
export const REGION_COLORS = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac", "#1f77b4", "#d62728"];
export const EMPTY_REGIONS: Regions = { groups: [], active: null, seq: 0 };
export type FilterSpec =
  | { kind: "gene"; gene: string; range: [number, number] }
  | { kind: "field"; field: string; range: [number, number] }
  | { kind: "category"; field: string; codes: number[] };
export interface GroupRow {
  code: number;
  n: number;
  mean: number;
  frac: number;
  perSample: Record<string, { n: number; mean: number; frac: number }>;
  hist: number[]; // cells per expression bin over [vmin, vmax] (GroupStats.bins of them): the violin
  median: number;
  q1: number;
  q3: number;
}
export interface GroupStats {
  gene: string;
  field: string;
  rows: GroupRow[];
  maxMean: number;
  vmin: number; // the expression range the histograms span, shared by every category
  vmax: number;
  bins: number;
}
export interface SelectionSummary {
  version: number;
  total: number;
  perSample: { id: string; name: string; n: number }[];
  fields: Record<string, { code: number; n: number }[]>;
  gene: { name: string; mean: number; frac: number; meanAll: number; fracAll: number } | null;
}
export type Status = "idle" | "loading" | "ready" | "error";
export interface ViewState {
  target: [number, number, number];
  zoom: number;
  transitionDuration?: number;
  transitionInterpolator?: unknown;
}
export interface HoverInfo {
  sampleId: string;
  index: number;
  x: number;
  y: number;
  label?: string;
  value?: number | null;
  id?: string;
  rows?: { label: string; value: string; swatch?: string }[];
}

/** What a pane shows: tissue sections or embeddings. Point sizes and persisted regions are per kind. */
export type ViewKind = "spatial" | "embedding";
/** A pane id: "spatial" (the single tissue canvas), "embedding", or "g0".."g2" (one pane per group when split by a meta key). */
export type ViewId = string;
export interface ViewRect {
  x: number; // px from the left of the container
  y: number; // px from the top (below the pane header when panes have one)
  w: number;
  h: number;
}
export interface SplitState {
  on: boolean;
  side: "left" | "right"; // where the embedding view sits
  fraction: number; // width fraction of the embedding view
}
/** The tissue canvas split into one pane per level of a sample meta key (condition, sex, ...). */
export interface GroupSplit {
  key: string;
  groups: string[] | null; // the levels shown, in pane order; null = the first three levels
  fractions: number[] | null; // width shares of the group panes once a divider was dragged; null = equal
}
/** What the UI needs to know about a pane; the controller publishes it with the rectangles. */
export interface PaneInfo {
  id: ViewId;
  kind: ViewKind;
  key: string | null; // meta key when the pane is one group
  value: string | null; // the group's level
  label: string; // caption: the level, or the kind
  count: number; // sections laid out in the pane
  hidden: number; // sections of the group hidden by the platform bar or the sample list
}
export interface ViewerState {
  groupField: string | null;
  groupStats: GroupStats | null;
  tool: "pan" | "lasso";
  cellShapes: CellShapes; // how cells draw once zoomed in: auto (filled, or outlined over an image), dots, filled, outlined
  shapeHint: string | null; // "zoom in for cell shapes" when too many cells are in view to draw their shapes
  molecules: boolean; // individual molecules (transcripts) once zoomed in, when the bundle has them
  moleculeGenes: string[]; // pinned genes whose molecules draw in fixed colours next to the gene on screen
  moleculePinColors: Record<string, string>; // a pinned gene's chosen colour (hex), replacing its pin colour
  moleculeColors: "selected" | "all"; // the selected genes (the one on screen and the pins; others grey under an annotation), or every gene in its own colour
  moleculeSize: number; // point radius multiplier for molecules (1 = 1.6 px)
  moleculeHint: string | null; // "zoom in for molecules" when the view holds too many to draw
  overlay: string | null; // another segmentation of the section (by id) drawn as dashed edges over the cells
  clusterLabels: boolean; // category names at the centre of their cells, in the embedding view
  genome: boolean; // the genome panel under the maps, when a sample carries tracks
  genomeHeight: number; // px; dragged at the panel's top edge, remembered per browser
  locus: Locus | null; // what the genome panel shows (gl in the URL)
  regions: Regions; // annotation drawn in the viewer: groups of lassos, exposed as the "regions" field
  viewPx: Record<ViewId, number>; // px per µm per pane (scale bar)
  viewRects: Record<ViewId, ViewRect>;
  panes: PaneInfo[]; // the panes on screen, in order
  splitBy: GroupSplit | null; // tissue sections split into one pane per group
  matchScale: boolean; // group panes share one µm/px: zoom one, the others follow in scale
  paneCameras: ViewState[] | null; // cameras of the group panes, pane order (pv in the URL)
  comparison: string | null; // the comparison shown under the maps (cmp in the URL)
  comparisonLevel: string | null; // its level (a cluster, a cell type) when it has several (cmp=<id>:<level>)
  compareHeight: number; // px; dragged at the panel's top edge, remembered per browser
  compareBox: boolean; // quartile boxes behind the replicate dots, remembered per browser
  selectionSummary: SelectionSummary | null;
  datasetUrl: string | null;
  datasetRef: string | null; // what the user typed / the registry id; kept in the URL
  manifest: Manifest | null;
  features: FeatureList | null;
  platforms: string[] | null; // null = all platforms visible
  split: SplitState;
  activeView: ViewId;
  sidebarOpen: boolean;
  status: Status;
  error: string | null;
  sampleStatus: Record<string, "pending" | "loading" | "ready" | "error">;
  pending: number;
  color: ColorSpec | null;
  colormap: string;
  vrange: [number, number];
  hideZeros: boolean;
  filter: FilterSpec | null;
  hiddenCategories: Record<string, number[]>;
  hiddenSamples: string[];
  layoutMode: LayoutMode;
  focus: string | null;
  selected: string | null;
  viewState: ViewState | null;
  imageOpacity: number;
  showImages: boolean;
  showCells: boolean; // the cells (dots and shapes); off to see the image or the transcripts alone
  hiddenChannels: string[]; // fluorescence channels switched off, by name, so one switch covers every sample
  // point radius multipliers: "spatial" and "embedding" are the bases per pane kind; a group pane ("g0".."g2") may
  // override its own, so a dense section and a sparse one can be read side by side
  pointScale: Record<string, number>;
  hover: HoverInfo | null;
  categoryCounts: Record<string, number[]>;
  filterHistogram: number[] | null;
  visibleCount: number | null; // cells shown (drawn samples, after the filter, hidden categories and hidden zeros)
  filterEvaluated: number | null; // cells of drawn samples the filter was applied to
  filterUnmeasured: { cells: number; samples: number } | null; // cells of drawn samples without the filter's gene or field
  geneMax: number; // max gmax of current gene across loaded samples (legend labels)
  geneMin: number; // min gmin across loaded samples: 0, or negative for signed features (module scores, motif deviations)
  scalePerSample: boolean; // gene colors: each sample stretched to its own max instead of one shared scale
  recentGenes: string[]; // last genes picked in the search box (not in the URL)
  debug: boolean; // ?debug=1: show timings in the status bar
  help: boolean; // keyboard shortcut overlay
  timings: { lastGeneMs: number | null; lastGeneFrameMs: number | null; fps: number }; // gene switch: data ready, first frame drawn with it

  set: (p: Partial<ViewerState>) => void;
  togglePlatform: (platform: string, all: string[]) => void;
  setColor: (c: ColorSpec) => void;
  setFilter: (f: FilterSpec | null) => void;
  toggleCategory: (field: string, code: number) => void;
  setHiddenCategories: (field: string, codes: number[]) => void;
  setFocus: (id: string | null) => void;
  toggleSample: (id: string) => void;
  addRegionGroup: (name?: string) => string;
  setActiveRegion: (id: string | null) => void;
  updateRegionGroup: (id: string, patch: Partial<Pick<RegionGroup, "name" | "color">>) => void;
  removeRegionGroup: (id: string) => void;
  addRegionPolygon: (groupId: string, poly: Omit<RegionPolygon, "id" | "seq">) => void;
  undoRegionPolygon: (groupId: string) => void;
  setRegions: (groups: RegionGroup[]) => void;
}

export const GENOME_HEIGHT_KEY = "sscape.genomeHeight";
export const COMPARE_HEIGHT_KEY = "sscape.compareHeight";
export const COMPARE_BOX_KEY = "sscape.compareBox";
function storedGenomeHeight(): number {
  try {
    const v = Number(localStorage.getItem(GENOME_HEIGHT_KEY));
    return v >= 160 && v <= 2000 ? v : 300;
  } catch {
    return 300;
  }
}
function storedCompareHeight(): number {
  try {
    const v = Number(localStorage.getItem(COMPARE_HEIGHT_KEY));
    return v >= 180 && v <= 2000 ? v : 340;
  } catch {
    return 340;
  }
}
function storedCompareBox(): boolean {
  try {
    return localStorage.getItem(COMPARE_BOX_KEY) === "1";
  } catch {
    return false;
  }
}

export const DEFAULTS = {
  colormap: "viridis",
  vrange: [0, 1] as [number, number],
  hideZeros: false,
  layoutMode: "grid" as LayoutMode,
  imageOpacity: 1,
  showImages: true,
  pointScale: { spatial: 1, embedding: 1 } as Record<string, number>,
  matchScale: true,
};

export const store = createStore<ViewerState>((set, get) => ({
  datasetUrl: null,
  datasetRef: null,
  manifest: null,
  status: "idle",
  error: null,
  sampleStatus: {},
  pending: 0,
  color: null,
  colormap: DEFAULTS.colormap,
  vrange: DEFAULTS.vrange,
  hideZeros: DEFAULTS.hideZeros,
  filter: null,
  hiddenCategories: {},
  hiddenSamples: [],
  layoutMode: DEFAULTS.layoutMode,
  features: null,
  platforms: null,
  split: { on: true, side: "left", fraction: 0.38 },
  activeView: "spatial",
  sidebarOpen: true,
  groupField: null,
  groupStats: null,
  tool: "pan",
  cellShapes: "auto",
  shapeHint: null,
  molecules: false,
  moleculeGenes: [],
  moleculePinColors: {},
  moleculeColors: "selected",
  moleculeSize: 1,
  moleculeHint: null,
  overlay: null,
  clusterLabels: true,
  genome: true,
  genomeHeight: storedGenomeHeight(),
  locus: null,
  regions: EMPTY_REGIONS,
  viewPx: {},
  viewRects: {},
  panes: [],
  splitBy: null,
  matchScale: DEFAULTS.matchScale,
  paneCameras: null,
  comparison: null,
  comparisonLevel: null,
  compareHeight: storedCompareHeight(),
  compareBox: storedCompareBox(),
  selectionSummary: null,
  focus: null,
  selected: null,
  viewState: null,
  imageOpacity: DEFAULTS.imageOpacity,
  showImages: DEFAULTS.showImages,
  showCells: true,
  hiddenChannels: [],
  pointScale: DEFAULTS.pointScale,
  hover: null,
  categoryCounts: {},
  filterHistogram: null,
  visibleCount: null,
  filterEvaluated: null,
  filterUnmeasured: null,
  geneMax: 0,
  geneMin: 0,
  scalePerSample: true,
  recentGenes: [],
  debug: false,
  help: false,
  timings: { lastGeneMs: null, lastGeneFrameMs: null, fps: 0 },

  set: (p) => set(p),
  togglePlatform: (platform, all) => {
    const cur = new Set(get().platforms ?? all);
    if (cur.has(platform)) cur.delete(platform);
    else cur.add(platform);
    const next = all.filter((p) => cur.has(p));
    set({ platforms: next.length === all.length ? null : next });
  },
  setColor: (color) => {
    const recent = get().recentGenes;
    const gene = color.kind === "gene" ? color.gene : null;
    set({ color, recentGenes: gene && recent[0] !== gene ? [gene, ...recent.filter((g) => g !== gene)].slice(0, 6) : recent });
  },
  setFilter: (filter) => set({ filter }),
  toggleCategory: (field, code) => {
    const cur = new Set(get().hiddenCategories[field] ?? []);
    if (cur.has(code)) cur.delete(code);
    else cur.add(code);
    set({ hiddenCategories: { ...get().hiddenCategories, [field]: [...cur].sort((a, b) => a - b) } });
  },
  setHiddenCategories: (field, codes) => set({ hiddenCategories: { ...get().hiddenCategories, [field]: codes } }),
  setFocus: (focus) => set({ focus, selected: focus ?? get().selected }),
  addRegionGroup: (name) => {
    const r = get().regions;
    const id = `r${Date.now().toString(36)}${r.groups.length}`;
    const taken = new Set(r.groups.map((g) => g.name));
    let n = r.groups.length + 1;
    while (taken.has(`Region ${n}`)) n++; // names are categories and keys: never reuse one that is still there
    const group: RegionGroup = { id, name: name ?? `Region ${n}`, color: REGION_COLORS[r.groups.length % REGION_COLORS.length], polygons: [] };
    set({ regions: { ...r, groups: [...r.groups, group], active: id }, tool: "lasso" });
    return id;
  },
  setActiveRegion: (active) => set({ regions: { ...get().regions, active }, tool: active ? "lasso" : get().tool }),
  updateRegionGroup: (id, patch) => set({ regions: { ...get().regions, groups: get().regions.groups.map((g) => (g.id === id ? { ...g, ...patch } : g)) } }),
  removeRegionGroup: (id) => {
    const r = get().regions;
    set({ regions: { ...r, groups: r.groups.filter((g) => g.id !== id), active: r.active === id ? null : r.active } });
  },
  addRegionPolygon: (groupId, poly) => {
    const r = get().regions;
    const seq = r.seq + 1;
    set({ regions: { ...r, seq, groups: r.groups.map((g) => (g.id === groupId ? { ...g, polygons: [...g.polygons, { ...poly, id: `p${seq}`, seq }] } : g)) } });
  },
  undoRegionPolygon: (groupId) => {
    const r = get().regions;
    set({ regions: { ...r, groups: r.groups.map((g) => (g.id === groupId ? { ...g, polygons: g.polygons.slice(0, -1) } : g)) } });
  },
  setRegions: (groups) => set({ regions: { groups, active: null, seq: groups.reduce((m, g) => Math.max(m, ...g.polygons.map((p) => p.seq)), 0) } }),
  toggleSample: (id) => {
    const cur = new Set(get().hiddenSamples);
    if (cur.has(id)) cur.delete(id);
    else cur.add(id);
    set({ hiddenSamples: [...cur] });
  },
}));

export type ViewerStore = typeof store;
export function useViewer<T>(selector: (s: ViewerState) => T): T {
  return useStore(store, selector);
}
