/** The Comparisons group of the side panel: one radio row per comparison the dataset carries, each named as the
 *  yaml names it with what it is underneath (the annotation a marker table clusters, the condition a contrast
 *  compares, how many replicates); the group's switch opens and closes the panel under the maps. */
import { useViewer } from "../store/store";
import { activateComparison } from "./activate";
import type { ComparisonInfo, Manifest } from "../data/manifest";

export function comparisonSummary(info: ComparisonInfo): string {
  if (info.kind === "markers") return `${info.levels.length} ${info.facet?.field ? "categories" : "clusters"} · markers`;
  return [info.groups.join(" vs "), info.levels.length > 1 ? `${info.levels.length} levels` : null, info.nReplicates ? `${info.nReplicates} replicates` : null].filter(Boolean).join(" · ");
}

/** What the comparison is about, in the dataset's own words. */
export function comparisonLine(m: Manifest, info: ComparisonInfo): string {
  const fieldName = (id: string | null | undefined) => (id ? (m.fields.find((f) => f.id === id)?.name ?? id) : null);
  const facet = fieldName(info.facet?.field);
  if (info.kind === "markers") return `${info.levels.length} ${facet ? facet.toLowerCase() : "cluster"}${info.levels.length === 1 ? "" : "s"}, each against the rest`;
  const split = info.split ? (m.meta?.find((k) => k.id === info.split)?.name ?? info.split) : null;
  return [split ? (facet ? `${split} within each ${facet.toLowerCase()}` : split) : info.groups.join(" vs "), info.nReplicates ? `${info.nReplicates} replicates` : null, info.hasPseudobulk ? "pseudobulk" : null].filter(Boolean).join(" · ");
}

export function CompareGroup() {
  const manifest = useViewer((s) => s.manifest);
  const current = useViewer((s) => s.comparison);
  const comparisons = manifest?.comparisons ?? [];
  if (!manifest || !comparisons.length) return null;
  return (
    <ul className="cmp-list" role="radiogroup">
      {comparisons.map((c) => {
        const on = c.id === current;
        return (
          <li key={c.id} className={`cmp-row${on ? " on" : ""}`} role="radio" aria-checked={on} onClick={() => void activateComparison(on ? null : c.id)} title={on ? "close this comparison" : "open it under the maps"}>
            <span className="cmp-dot" />
            <div>
              <div className="cmp-name">{c.name}</div>
              <div className="cmp-sub">{comparisonLine(manifest, c)}</div>
            </div>
          </li>
        );
      })}
    </ul>
  );
}
