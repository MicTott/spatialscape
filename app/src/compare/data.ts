/** Loads a comparison's files once per dataset: comparison.json, results.json and the pseudobulk array. */
import * as zarr from "zarrita";
import type { ComparisonInfo } from "../data/manifest";
import type { ComparisonData, ComparisonDoc, ResultsDoc } from "./model";

const cache = new Map<string, Promise<ComparisonData>>();

async function json<T>(url: string): Promise<T> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} for ${url}`);
  return (await r.json()) as T;
}

export function loadComparison(datasetUrl: string, info: ComparisonInfo): Promise<ComparisonData> {
  const base = `${datasetUrl.replace(/\/$/, "")}/${info.path.replace(/\/$/, "")}`;
  let p = cache.get(base);
  if (!p) {
    p = (async () => {
      const [doc, results] = await Promise.all([json<ComparisonDoc>(`${base}/comparison.json`), json<ResultsDoc>(`${base}/results.json`)]);
      let pseudobulk: Float32Array | null = null;
      if (info.hasPseudobulk && doc.replicates.length) {
        // a few megabytes at most (genes x replicates of float32): read once, then every gene is a slice
        const arr = await zarr.open.v3(zarr.root(new zarr.FetchStore(`${base}/pseudobulk.zarr`)), { kind: "array" });
        const chunk = await zarr.get(arr as zarr.Array<"float32", zarr.FetchStore>);
        pseudobulk = new Float32Array(chunk.data as Float32Array);
      }
      const geneIndex = new Map<string, number>();
      results.genes.forEach((g, i) => geneIndex.set(g, i));
      return { info: { ...info, ...doc }, results, geneIndex, unmeasured: new Set(results.unmeasured ?? []), pseudobulk };
    })();
    cache.set(base, p);
    p.catch(() => cache.delete(base));
  }
  return p;
}

export function forgetComparisons() {
  cache.clear();
}
