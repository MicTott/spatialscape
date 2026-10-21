import { useViewer } from "../store/store";
import { activateComparison } from "./activate";

/** Sidebar section: which comparison's table and replicate values to show under the maps. */
export function CompareSelect() {
  const manifest = useViewer((s) => s.manifest);
  const current = useViewer((s) => s.comparison);
  const comparisons = manifest?.comparisons ?? [];
  if (!comparisons.length) return null;
  const info = comparisons.find((c) => c.id === current);
  return (
    <section>
      <h2 title="differential expression results fit upstream: a table under the maps, one dot per replicate, the gene on every section">Compare</h2>
      <select value={current ?? ""} onChange={(e) => void activateComparison(e.target.value || null)}>
        <option value="">none</option>
        {comparisons.map((c) => (
          <option key={c.id} value={c.id}>
            {c.name}
          </option>
        ))}
      </select>
      <div className="muted small genecount">
        {info
          ? `${info.groups.join(" vs ")} · ${info.nGenes.toLocaleString()} genes${info.nReplicates ? ` · ${info.nReplicates} replicates` : ""}${info.split ? ` · panes by ${info.split}` : ""}`
          : `${comparisons.length} comparison${comparisons.length === 1 ? "" : "s"} in this dataset`}
      </div>
    </section>
  );
}
