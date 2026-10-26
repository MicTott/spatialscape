/** Choosing a comparison (and a level of it) does three things at once: splits the canvas by its groups (unless
 *  another split is pinned), applies the level's population as the category filter (a contrast fit in one cell
 *  type; for markers only when the filter is already following the levels), and colours the maps by the table's
 *  first gene when the current colour is not one of its genes. Choosing none only closes the panel. */
import { fieldById, type Manifest } from "../data/manifest";
import { store, type FilterSpec, type ViewerState } from "../store/store";
import { splitKeys } from "../views/panes";
import { loadComparison } from "./data";
import { levelOf, levelPopulation } from "./model";

function categoryFilter(m: Manifest, pop: { field: string; value: string }): FilterSpec | null {
  const f = fieldById(m, pop.field);
  if (f?.type !== "categorical") return null;
  const code = m.vocabularies[f.vocabulary].categories.indexOf(pop.value);
  return code >= 0 ? { kind: "category", field: f.id, codes: [code] } : null;
}

function isFilterFor(m: Manifest, filter: FilterSpec | null, pop: { field: string; value: string } | null): boolean {
  if (!pop || filter?.kind !== "category" || filter.field !== pop.field) return false;
  const want = categoryFilter(m, pop);
  return !!want && want.kind === "category" && filter.codes.length === 1 && filter.codes[0] === want.codes[0];
}

let last: string | null = null; // the comparison closed most recently, so the group's switch can reopen it

export async function activateComparison(id: string | null, levelId?: string | null): Promise<void> {
  const s = store.getState();
  const m = s.manifest;
  if (!m) return;
  if (!id) {
    last = s.comparison ?? last;
    s.set({ comparison: null, comparisonLevel: null });
    return;
  }
  const info = m.comparisons?.find((c) => c.id === id);
  if (!info) return;
  last = id;
  const level = levelOf(info, levelId ?? (s.comparison === id ? s.comparisonLevel : null));
  const markers = info.kind === "markers";
  const patch: Partial<ViewerState> = { comparison: id, comparisonLevel: level?.id ?? null };
  if (!markers && info.split && splitKeys(m).some((k) => k.id === info.split) && (!s.splitBy || s.splitBy.key === info.split)) {
    patch.splitBy = { key: info.split, groups: info.groups.slice(0, 3), fractions: s.splitBy?.key === info.split ? s.splitBy.fractions : null };
  }
  const pop = levelPopulation(info, level);
  const previous = activePopulation(s);
  if (pop) {
    const f = categoryFilter(m, pop);
    // a contrast fit in a population filters the map to it; markers keep the whole map unless the filter was
    // already following the levels (the "only this cluster" toggle), in which case it moves to the new level
    const follow = markers ? isFilterFor(m, s.filter, previous) : !s.filter || s.filter.kind === "category";
    if (f && follow) patch.filter = f;
  } else if (markers && isFilterFor(m, s.filter, previous)) patch.filter = null;
  s.set(patch);
  if (!s.datasetUrl || !level) return;
  const data = await loadComparison(s.datasetUrl, info, level.id);
  const cur = store.getState();
  if (cur.comparison !== id || cur.comparisonLevel !== level.id) return; // changed again while loading
  const gene = cur.color?.kind === "gene" ? cur.color.gene : null;
  if (!gene || !data.geneIndex.has(gene)) {
    const first = data.results.genes.find((_, i) => !data.unmeasured.has(i));
    if (first) cur.setColor({ kind: "gene", gene: first });
  }
}

/** The group's switch: reopen the comparison closed last, else the dataset's first. */
export function reopenComparison(): void {
  const m = store.getState().manifest;
  const id = (m?.comparisons?.some((c) => c.id === last) ? last : null) ?? m?.comparisons?.[0]?.id ?? null;
  if (id) void activateComparison(id);
}

/** The population the active comparison level stands for, if any. */
export function activePopulation(s: ViewerState): { field: string; value: string } | null {
  const info = s.manifest?.comparisons?.find((c) => c.id === s.comparison);
  if (!info) return null;
  return levelPopulation(info, levelOf(info, s.comparisonLevel));
}

/** The population filter a comparison applied, if it is still the active filter. */
export function populationFilterActive(s: ViewerState): { field: string; value: string } | null {
  const pop = activePopulation(s);
  return s.manifest && pop && isFilterFor(s.manifest, s.filter, pop) ? pop : null;
}

/** Markers: filter the map to the level's cells, or back to every cell. */
export function toggleLevelFilter(): void {
  const s = store.getState();
  const pop = activePopulation(s);
  if (!s.manifest || !pop) return;
  s.setFilter(isFilterFor(s.manifest, s.filter, pop) ? null : categoryFilter(s.manifest, pop));
}
