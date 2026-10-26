/** The Comparisons group of the side panel: one row per comparison the dataset carries (a case/control result,
 *  a marker table), the active one highlighted with its level select; the group's switch opens and closes the
 *  panel under the maps. */
import { useViewer } from "../store/store";
import { activateComparison } from "./activate";
import type { ComparisonInfo } from "../data/manifest";

export function comparisonSummary(info: ComparisonInfo): string {
  if (info.kind === "markers") return `${info.levels.length} ${info.facet?.field ? "categories" : "clusters"} · markers`;
  return [info.groups.join(" vs "), info.levels.length > 1 ? `${info.levels.length} levels` : null, info.nReplicates ? `${info.nReplicates} replicates` : null].filter(Boolean).join(" · ");
}

export function CompareGroup() {
  const manifest = useViewer((s) => s.manifest);
  const current = useViewer((s) => s.comparison);
  const level = useViewer((s) => s.comparisonLevel);
  const comparisons = manifest?.comparisons ?? [];
  if (!comparisons.length) return null;
  return (
    <ul className="cmp-list">
      {comparisons.map((c) => {
        const on = c.id === current;
        return (
          <li key={c.id} className={`cmp-row${on ? " on" : ""}`}>
            <button className="cmp-pick" onClick={() => void activateComparison(on ? null : c.id)} title={on ? "close this comparison" : c.kind === "markers" ? "open its clusters' markers under the maps" : "open its table and replicate values under the maps"}>
              <span className="cmp-name">{c.name}</span>
              <span className="muted small">{comparisonSummary(c)}</span>
            </button>
            {on && c.levels.length > 1 && (
              <select value={level ?? c.levels[0].id} onChange={(e) => void activateComparison(c.id, e.target.value)} title={c.kind === "markers" ? "which cluster" : "which level the contrast was fit in"}>
                {c.levels.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.name}
                  </option>
                ))}
              </select>
            )}
            {on && c.description && <div className="muted small cmp-desc">{c.description}</div>}
          </li>
        );
      })}
    </ul>
  );
}
