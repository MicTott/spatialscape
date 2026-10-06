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
export interface Sample {
  id: string;
  name: string;
  platform: Platform;
  kind: SampleKind;
  group?: string;
  nObs: number;
  nGenes: number;
  bbox: [number, number, number, number];
  toDataset: number[];
  pointRadius: number;
  expr: { kind: "u8" | "csc"; sharded: boolean; shardGenes: number };
  hasF16: boolean;
  fields: string[];
  images: SampleImage[];
  outlines?: string[];
  polygons?: { path: string; cells: number; vertices: number; scale: number } | null;
  idBlock: number;
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
}

export function fieldById(m: Manifest, id: string): ObsField | undefined {
  return m.fields.find((f) => f.id === id);
}
