/** The Comparisons group of the side panel: one row per comparison the dataset carries, named by the variable
 *  it is about (the annotation a marker table clusters, the condition a contrast compares), the active one
 *  highlighted with its description; the group's switch opens and closes the panel under the maps. */
import { useViewer } from "../store/store";
import { activateComparison } from "./activate";
import type { ComparisonInfo, Manifest } from "../data/manifest";

export function comparisonSummary(info: ComparisonInfo): string {
  if (info.kind === "markers") return `${info.levels.length} ${info.facet?.field ? "categories" : "clusters"} · markers`;
  return [info.groups.join(" vs "), info.levels.length > 1 ? `${info.levels.length} levels` : null, info.nReplicates ? `${info.nReplicates} replicates` : null].filter(Boolean).join(" · ");
}

/** What the comparison is about: the facet field's name for markers, the split key's name for a contrast. */
export function comparisonVariable(m: Manifest, info: ComparisonInfo): string | null {
  if (info.kind === "markers") return info.facet?.field ? (m.fields.find((f) => f.id === info.facet!.field)?.name ?? info.facet.field) : null;
  const split = info.split ? (m.meta?.find((k) => k.id === info.split)?.name ?? info.split) : null;
  const facet = info.facet?.field ? (m.fields.find((f) => f.id === info.facet!.field)?.name ?? info.facet.field) : null;
  return split ? (facet ? `${split} per ${facet}` : split) : null;
}

export function CompareGroup() {
  const manifest = useViewer((s) => s.manifest);
  const current = useViewer((s) => s.comparison);
  const comparisons = manifest?.comparisons ?? [];
  if (!manifest || !comparisons.length) return null;
  return (
    <ul className="cmp-list">
      {comparisons.map((c) => {
        const on = c.id === current;
        const variable = comparisonVariable(manifest, c);
        return (
          <li key={c.id} className={`cmp-row${on ? " on" : ""}`}>
            <button className="cmp-pick" onClick={() => void activateComparison(on ? null : c.id)} title={on ? "close this comparison" : c.kind === "markers" ? "open its clusters' markers under the maps" : "open its table and replicate values under the maps"}>
              <span className="cmp-name">{variable ? `${variable} · ${c.kind === "markers" ? "markers" : c.groups.join(" vs ")}` : c.name}</span>
              <span className="muted small">{variable ? c.name : comparisonSummary(c)}</span>
            </button>
            {on && c.description && <div className="muted small cmp-desc">{c.description}</div>}
          </li>
        );
      })}
    </ul>
  );
}
