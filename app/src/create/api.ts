/** The Create page's backend (python: create.py), reached through the `create` path the server's datasets.json names.
 *  Paths are the server's own: the page browses them, nothing is uploaded. */
import { loadRegistry } from "../ui/registry";

export interface CreatePing {
  create: true;
  host: string;
  project: string;
  bundles: string;
  home: string;
  guard: string | null; // set when building here is a bad idea (a cluster login node)
  version: string;
}
export interface BrowseEntry {
  name: string;
  path: string;
  kind: "folder" | "object" | "store" | "table" | "file";
  hint: string;
  size: number | null;
}
export interface Browse {
  path: string;
  parent: string | null;
  entries: BrowseEntry[];
  roots: { name: string; path: string }[];
}
export interface ColumnRow {
  id: string;
  column: string;
  kind: "categorical" | "continuous";
  note: string;
  on: boolean;
  scale: number | null;
}
export interface EntryInfo {
  source: string;
  source_note: string;
  r_object: boolean;
  embedding: boolean;
  platform: string;
  platform_note: string;
  n_obs: number | null;
  samples: string[];
  sample_col: string | null;
  assay: string | null;
  assays: string[];
  layer: string;
  layers: string[];
  embedding_key: string | null;
  embeddings: string[];
  table: string | null;
  region: string | null;
  regions: string[];
  store_note: string;
  sections: [string, string[]] | null;
  layer_files: Record<string, string>;
  fragments: Record<string, string>;
  columns: ColumnRow[];
  meta: { column: string; note: string; on: boolean }[];
  skipped: string[];
}
export interface ComparisonInfo {
  source: string;
  id: string;
  name: string;
  kind: string;
  n_rows: number;
  columns: Record<string, string>;
  facet: string | null;
  groups: string[] | null;
}
export interface Rendered {
  id: string;
  name: string;
  yaml: string;
  yaml_path: string;
  bundle: string;
}
export interface Inspection extends Rendered {
  token: string;
  log: string[];
  entries: EntryInfo[];
  comparisons: ComparisonInfo[];
}
export interface EntryChoice {
  platform?: string;
  assay?: string;
  layer?: string;
  embedding?: string;
  region?: string;
  columns?: { column: string; id: string; on: boolean }[];
  meta?: string[];
}
export interface Choices {
  id?: string;
  name?: string;
  names?: Record<string, string>; // field id -> display name
  entries: Record<string, EntryChoice>;
}
export interface Job {
  id: string;
  status: "running" | "done" | "error";
  lines: string[];
  next: number;
  error: string | null;
  yaml: string;
  bundle: string;
  dataset_id: string;
  seconds: number;
}

let base: Promise<string | null> | null = null;
/** The API's URL when this server has a Create page, else null (a static site, or plain `serve`). */
export function createApi(): Promise<string | null> {
  base ??= loadRegistry()
    .then((reg) => {
      const p = (reg as ({ create?: string } & object) | null)?.create;
      return p ? new URL(p, document.baseURI).toString().replace(/\/$/, "") : null;
    })
    .catch(() => null);
  return base;
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const api = await createApi();
  if (!api) throw new Error("this server has no Create page; start one with `spatialscape create`");
  const r = await fetch(`${api}/${path}`, init);
  const doc = (await r.json().catch(() => ({}))) as T & { error?: string };
  if (!r.ok) throw new Error(doc.error || `${r.status} ${r.statusText}`);
  return doc;
}
const post = <T,>(path: string, body: unknown) => call<T>(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export const ping = () => call<CreatePing>("ping");
export const browse = (path?: string | null) => call<Browse>(`browse${path ? `?path=${encodeURIComponent(path)}` : ""}`);
export const inspect = (paths: string[], opts: { platform?: string | null; table?: string | null }) => post<Inspection>("inspect", { paths, platform: opts.platform || null, table: opts.table || null });
export const render = (token: string, choices: Choices) => post<Rendered>("render", { token, choices });
export const build = (token: string, choices: Choices) => post<{ job: string; yaml: string; bundle: string; dataset_id: string }>("build", { token, choices });
export const job = (id: string, from: number) => call<Job>(`jobs/${id}?from=${from}`);

export function fmtSize(n: number | null): string {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}
