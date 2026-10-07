import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";
import type { FeatureList, LayoutMode, Manifest } from "../data/manifest";

export type BlendScheme = "yb" | "cm" | "rg";
export type ColorSpec = { kind: "gene"; gene: string } | { kind: "field"; field: string } | { kind: "blend"; a: string[]; b: string[]; scheme: BlendScheme };
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
}
export interface GroupStats {
  gene: string;
  field: string;
  rows: GroupRow[];
  maxMean: number;
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

export type ViewId = "spatial" | "embedding";
export interface SplitState {
  on: boolean;
  side: "left" | "right"; // where the embedding view sits
  fraction: number; // width fraction of the embedding view
}
export interface OutlineState {
  field: string | null;
  style: "field" | "light" | "dark";
  width: number; // pixels
}
export interface ViewerState {
  outline: OutlineState;
  groupField: string | null;
  groupStats: GroupStats | null;
  tool: "pan" | "lasso";
  showPolygons: boolean;
  viewPx: Partial<Record<ViewId, number>>; // px per µm per view (scale bar)
  viewRects: Partial<Record<ViewId, { x: number; w: number }>>;
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
  pointScale: Record<ViewId, number>; // point radius multiplier per view (spatial sections vs embeddings)
  hover: HoverInfo | null;
  categoryCounts: Record<string, number[]>;
  filterHistogram: number[] | null;
  visibleCount: number | null;
  geneMax: number; // max gmax of current gene across loaded samples (legend labels)
  scalePerSample: boolean; // gene colors: each sample stretched to its own max instead of one shared scale
  recentGenes: string[]; // last genes picked in the search box (not in the URL)
  debug: boolean; // ?debug=1: show timings in the status bar
  help: boolean; // keyboard shortcut overlay
  timings: { lastGeneMs: number | null; fps: number };

  set: (p: Partial<ViewerState>) => void;
  togglePlatform: (platform: string, all: string[]) => void;
  setColor: (c: ColorSpec) => void;
  setFilter: (f: FilterSpec | null) => void;
  toggleCategory: (field: string, code: number) => void;
  setHiddenCategories: (field: string, codes: number[]) => void;
  setFocus: (id: string | null) => void;
  toggleSample: (id: string) => void;
}

export const DEFAULTS = {
  colormap: "viridis",
  vrange: [0, 1] as [number, number],
  hideZeros: false,
  layoutMode: "grid" as LayoutMode,
  imageOpacity: 1,
  showImages: true,
  pointScale: { spatial: 1, embedding: 1 } as Record<ViewId, number>,
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
  outline: { field: null, style: "light", width: 1.5 },
  groupField: null,
  groupStats: null,
  tool: "pan",
  showPolygons: true,
  viewPx: {},
  viewRects: {},
  selectionSummary: null,
  focus: null,
  selected: null,
  viewState: null,
  imageOpacity: DEFAULTS.imageOpacity,
  showImages: DEFAULTS.showImages,
  pointScale: DEFAULTS.pointScale,
  hover: null,
  categoryCounts: {},
  filterHistogram: null,
  visibleCount: null,
  geneMax: 0,
  scalePerSample: false,
  recentGenes: [],
  debug: false,
  help: false,
  timings: { lastGeneMs: null, fps: 0 },

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
