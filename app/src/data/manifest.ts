/** Mirrors python/src/sscape/manifest.py. Keep in sync. */
export type Platform = "visium" | "visium_hd" | "xenium" | "merfish" | "snrnaseq" | "other";
export type SampleKind = "spatial" | "embedding";
export type LayoutMode = "grid" | "strip";

export interface Vocabulary {
  categories: string[];
  colors: string[];
  aliases?: Record<string, string>;
}
export interface CategoricalField {
  id: string;
  name: string;
  type: "categorical";
  vocabulary: string;
  description?: string;
}
export interface ContinuousField {
  id: string;
  name: string;
  type: "continuous";
  range?: [number, number];
  colormap?: string;
  description?: string;
}
export type ObsField = CategoricalField | ContinuousField;

export interface ColorSpecManifest {
  kind: "gene" | "field";
  gene?: string;
  field?: string;
}
export interface Layout {
  mode: LayoutMode;
  gutterFraction: number;
  order: string[];
  columns?: number | null; // grid: a fixed number of columns
}
export interface ImageChannel {
  name: string;
  color: string;
  window: [number, number];
}
export interface SampleImage {
  id: string;
  name: string;
  path: string;
  kind: "rgb" | "multichannel";
  pixelSize: number;
  translate: [number, number];
  size: [number, number];
  channels?: ImageChannel[] | null;
  defaultOpacity: number;
}
export interface MetaKey {
  id: string;
  name: string;
  levels: string[]; // declared order first, then values in sample order
}
/** A differential expression result stored under comparisons/<id>/ (results.json, pseudobulk.zarr, comparison.json). */
export interface LevelInfo {
  id: string; // folder under the comparison
  name: string; // the level's label ("all" for a comparison without a facet)
  path: string; // levels/<id>
  nGenes: number;
  nSignificant: number;
  nUnmatched: number;
  nReplicates: number;
  hasPseudobulk: boolean;
  population?: { field: string; value: string } | null; // the level as a category of the facet field
}
export interface ComparisonInfo {
  id: string;
  kind?: "contrast" | "markers"; // markers: every level against the rest, no replicates, no split
  name: string;
  description?: string | null;
  path: string;
  groups: string[]; // pane and plotting order; the contrast is the last against the first (empty for markers)
  units?: string | null;
  population?: { field: string; value: string } | null;
  split?: string | null; // sample meta key whose levels are the groups
  link?: string | null;
  facet?: { column: string; field?: string | null } | null;
  levels: LevelInfo[];
  nGenes: number;
  nReplicates: number;
  nUnmatched: number;
  hasEffect?: boolean; // false for a ranked list without statistics
  hasP: boolean;
  hasPadj: boolean;
  hasMean: boolean;
  hasPct?: boolean;
  hasScore?: boolean;
  hasPseudobulk: boolean;
}
export interface Sample {
  id: string;
  name: string;
  platform: Platform;
  kind: SampleKind;
  group?: string;
  meta?: Record<string, string>; // sample-level metadata (condition, subject, ...); keys declared in Manifest.meta
  nObs: number;
  nGenes: number;
  bbox: [number, number, number, number];
  toDataset: number[];
  pointRadius: number;
  expr: { kind: "u8" | "csc"; sharded: boolean; shardGenes: number; normalized?: "lognorm" | "log1p_cp10k" | null };
  hasF16: boolean;
  fields: string[];
  images: SampleImage[];
  outlines?: string[];
  polygons?: { path: string; cells: number; vertices: number; scale: number } | null; // bundles built before shape tiles
  shapes?: { path: string; cells: number; vertices: number; tile: number; tiles: number; bytes: number; medianArea?: number | null } | null;
  segmentations?: { id: string; name: string; path: string; cells: number; vertices: number; tile: number; tiles: number; bytes: number; medianArea?: number | null }[];
  molecules?: { path: string; count: number; genes: number; tile: number; tiles: number; bytes: number } | null;
  idBlock: number;
  suggestedGene?: string | null; // most variable gene; the dataset default when none is configured
  tracks?: TracksInfo | null; // genome tracks (ATAC samples)
}
export interface TrackSet {
  field: string;
  categories: Record<string, string>; // category label -> bigWig path relative to the sample folder
}
export interface TracksInfo {
  genome: string;
  bin: number;
  all?: string | null; // every cell: built from fragments, or given with exported bigWigs
  units?: string; // what the tracks measure (default insertions per million)
  by: TrackSet[];
  peaks?: string | null;
  genes?: string | null;
  links?: string | null;
  chromSizes?: string;
}
export interface FeatureGroup {
  id: string;
  name: string;
  units?: string | null;
  count: number;
}
export interface FeatureList {
  genes: string[];
  groups: { id: string; name: string; units?: string | null; features: { id: string; label: string }[] }[];
}
export interface OutlinePath {
  c: number;
  p: [number, number][];
}
export interface OutlineData {
  bin: number;
  paths: OutlinePath[];
}
export interface Manifest {
  formatVersion: 1;
  id: string;
  name: string;
  description?: string;
  defaultGene?: string;
  defaultColor: ColorSpecManifest;
  layout: Layout;
  colormaps: string[];
  vocabularies: Record<string, Vocabulary>;
  fields: ObsField[];
  featureGroups?: FeatureGroup[];
  samples: Sample[];
  thumbnailSample?: string; // sample drawn on the dataset thumbnail
  meta?: MetaKey[]; // the sample metadata keys the viewer can split the canvas by
  comparisons?: ComparisonInfo[];
}

export function assertManifest(m: unknown): asserts m is Manifest {
  const x = m as Partial<Manifest>;
  if (!x || typeof x !== "object") throw new Error("manifest is not an object");
  if (x.formatVersion !== 1) throw new Error(`unsupported formatVersion ${String(x.formatVersion)}`);
  if (!Array.isArray(x.samples) || x.samples.length === 0) throw new Error("manifest has no samples");
  if (!x.layout || !Array.isArray(x.layout.order)) throw new Error("manifest.layout.order missing");
  for (const s of x.samples) {
    if (!s.id || !Number.isFinite(s.nObs) || !Array.isArray(s.bbox)) throw new Error(`bad sample entry ${JSON.stringify(s).slice(0, 80)}`);
  }
  for (const f of x.fields ?? []) {
    if (f.type !== "categorical") continue;
    const v = x.vocabularies?.[f.vocabulary];
    if (!v || !Array.isArray(v.categories) || !Array.isArray(v.colors) || v.categories.length !== v.colors.length) throw new Error(`field ${f.id}: vocabulary ${f.vocabulary} missing or malformed`);
  }
}

export function fieldById(m: Manifest, id: string): ObsField | undefined {
  return m.fields.find((f) => f.id === id);
}
