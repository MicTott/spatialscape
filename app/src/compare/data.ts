/** Loads a comparison's files once per dataset: comparison.json for the whole comparison, then each level's
 *  results.json and pseudobulk array as it is shown. */
import * as zarr from "zarrita";
import type { ComparisonInfo, LevelInfo } from "../data/manifest";
import { levelOf, type ComparisonData, type ComparisonDoc, type ResultsDoc } from "./model";

const docs = new Map<string, Promise<ComparisonDoc>>();
const levels = new Map<string, Promise<ComparisonData>>();

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} for ${url}`);
  return (await r.json()) as T;
}

function base(datasetUrl: string, info: ComparisonInfo): string {
  return `${datasetUrl.replace(/\/$/, "")}/${info.path.replace(/\/$/, "")}`;
}

export function loadComparisonDoc(datasetUrl: string, info: ComparisonInfo): Promise<ComparisonDoc> {
  const b = base(datasetUrl, info);
  let p = docs.get(b);
  if (!p) {
    p = json<ComparisonDoc>(`${b}/comparison.json`);
    docs.set(b, p);
    p.catch(() => docs.delete(b));
  }
  return p;
}

export function loadComparison(datasetUrl: string, info: ComparisonInfo, levelId?: string | null): Promise<ComparisonData> {
  const level: LevelInfo | null = levelOf(info, levelId);
  if (!level) return Promise.reject(new Error(`comparison ${info.id} has no levels`));
  const b = `${base(datasetUrl, info)}/${level.path}`;
  let p = levels.get(b);
  if (!p) {
    p = (async () => {
      const [doc, results] = await Promise.all([loadComparisonDoc(datasetUrl, info), json<ResultsDoc>(`${b}/results.json`)]);
      const replicates = doc.replicates?.[level.id] ?? [];
      let pseudobulk: Float32Array | null = null;
      if (level.hasPseudobulk && replicates.length) {
        // a few megabytes at most (genes x replicates of float32): read once, then every gene is a slice
        const arr = await zarr.open.v3(zarr.root(new zarr.FetchStore(`${b}/pseudobulk.zarr`)), { kind: "array" });
        const chunk = await zarr.get(arr as zarr.Array<"float32", zarr.FetchStore>);
        pseudobulk = new Float32Array(chunk.data as Float32Array);
      }
      const geneIndex = new Map<string, number>();
      results.genes.forEach((g, i) => geneIndex.set(g, i));
      return { info: { ...info, ...doc }, level, results, geneIndex, unmeasured: new Set(results.unmeasured ?? []), replicates, pseudobulk };
    })();
    levels.set(b, p);
    p.catch(() => levels.delete(b));
  }
  return p;
}

export function forgetComparisons() {
  docs.clear();
  levels.clear();
}
