/** Choosing a comparison does three things at once: splits the canvas by its groups (unless another split is
 *  pinned), applies its population as the category filter (unless another filter is in the way), and colours the
 *  maps by the table's first gene when the current colour is not one of its genes. Choosing none only closes the panel. */
import { fieldById } from "../data/manifest";
import { store, type ViewerState } from "../store/store";
import { splitKeys } from "../views/panes";
import { loadComparison } from "./data";

export async function activateComparison(id: string | null): Promise<void> {
  const s = store.getState();
  const m = s.manifest;
  if (!m) return;
  if (!id) {
    s.set({ comparison: null });
    return;
  }
  const info = m.comparisons?.find((c) => c.id === id);
  if (!info) return;
  const patch: Partial<ViewerState> = { comparison: id };
  if (info.split && splitKeys(m).some((k) => k.id === info.split) && (!s.splitBy || s.splitBy.key === info.split)) {
    patch.splitBy = { key: info.split, groups: info.groups.slice(0, 3), fractions: s.splitBy?.key === info.split ? s.splitBy.fractions : null };
  }
  if (info.population) {
    const f = fieldById(m, info.population.field);
    if (f?.type === "categorical") {
      const code = m.vocabularies[f.vocabulary].categories.indexOf(info.population.value);
      if (code >= 0 && (!s.filter || s.filter.kind === "category")) patch.filter = { kind: "category", field: f.id, codes: [code] };
    }
  }
  s.set(patch);
  if (!s.datasetUrl) return;
  const data = await loadComparison(s.datasetUrl, info);
  const cur = store.getState();
  if (cur.comparison !== id) return; // changed again while loading
  const gene = cur.color?.kind === "gene" ? cur.color.gene : null;
  if (!gene || !data.geneIndex.has(gene)) {
    const first = data.results.genes.find((_, i) => !data.unmeasured.has(i));
    if (first) cur.setColor({ kind: "gene", gene: first });
  }
}

/** The population filter a comparison applied, if it is still the active filter. */
export function populationFilterActive(s: ViewerState): { field: string; value: string } | null {
  const info = s.manifest?.comparisons?.find((c) => c.id === s.comparison);
  if (!info?.population || !s.manifest || s.filter?.kind !== "category" || s.filter.field !== info.population.field) return null;
  const f = fieldById(s.manifest, info.population.field);
  if (!f || f.type !== "categorical") return null;
  const code = s.manifest.vocabularies[f.vocabulary].categories.indexOf(info.population.value);
  return s.filter.codes.length === 1 && s.filter.codes[0] === code ? info.population : null;
}
