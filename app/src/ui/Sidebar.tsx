import { useState } from "react";
import { store, useViewer } from "../store/store";
import { GeneByAnnotation } from "./GeneByAnnotation";
import { SelectionPanel } from "./SelectionPanel";
import { RegionsPanel } from "./RegionsPanel";
import { Legend } from "./Legend";
import { SampleStrip } from "./SampleStrip";
import { CompareGroup, comparisonSummary } from "../compare/CompareGroup";
import { activateComparison, reopenComparison } from "../compare/activate";
import { Group } from "./Group";
import { ColorPanel, FilterPanel } from "./ColorPanel";
import { CellRows } from "./CellRows";
import { MoleculeGenes } from "./MoleculeGenes";
import { ImageChannels, channelSummary } from "./ImageChannels";

export function Sidebar() {
  const manifest = useViewer((s) => s.manifest);
  const features = useViewer((s) => s.features);
  const genes = features?.genes ?? [];
  const collapsed = !useViewer((s) => s.sidebarOpen);
  const [activeTab, setActiveTab] = useState<"explore" | "layers" | "samples">("explore");

  if (!manifest) return null;
  return (
    <aside className={`sidebar ${collapsed ? "collapsed" : ""}`}>
      <button className="collapse" onClick={() => store.getState().set({ sidebarOpen: collapsed })} title="toggle panel">
        {collapsed ? "›" : "‹"}
      </button>
      {!collapsed && (
        <div className="sidebar-inner">
          <header>
            <div className="hdr-row">
              <h1>{manifest.name}</h1>
              <HeaderActions />
            </div>
            {manifest.description && <details className="dataset-description"><summary>About this dataset</summary><p className="muted">{manifest.description}</p></details>}
          </header>
          <div className="inspector-tabs" role="tablist" aria-label="Viewer controls" onKeyDown={(e) => {
            const tabs = ["explore", "layers", "samples"] as const;
            const current = tabs.indexOf(activeTab);
            const next = e.key === "ArrowRight" ? (current + 1) % tabs.length : e.key === "ArrowLeft" ? (current + tabs.length - 1) % tabs.length : e.key === "Home" ? 0 : e.key === "End" ? tabs.length - 1 : -1;
            if (next < 0) return;
            e.preventDefault();
            setActiveTab(tabs[next]);
            document.getElementById(`inspector-tab-${tabs[next]}`)?.focus();
          }}>
            {(["explore", "layers", "samples"] as const).map((tab) => (
              <button key={tab} role="tab" id={`inspector-tab-${tab}`} aria-controls={`inspector-panel-${tab}`} aria-selected={activeTab === tab} tabIndex={activeTab === tab ? 0 : -1} onClick={() => setActiveTab(tab)}>{tab[0].toUpperCase() + tab.slice(1)}</button>
            ))}
          </div>
          <Groups genes={genes} activeTab={activeTab} />
        </div>
      )}
    </aside>
  );
}

function HeaderActions() {
  const [copied, setCopied] = useState<"" | "copied" | "copied · local link" | "copy failed">("");
  const localOnly = (() => {
    const loop = (h: string) => h === "127.0.0.1" || h === "localhost" || h === "[::1]" || h === "::1";
    if (loop(window.location.hostname)) return true;
    const d = new URLSearchParams(window.location.search).get("d");
    try {
      return !!d && /^https?:/.test(d) && loop(new URL(d).hostname);
    } catch {
      return false;
    }
  })();
  const copy = () => {
    const done = (what: typeof copied) => {
      setCopied(what);
      window.setTimeout(() => setCopied(""), what === "copy failed" ? 2500 : 2000);
    };
    if (!navigator.clipboard?.writeText) return done("copy failed");
    navigator.clipboard.writeText(window.location.href).then(() => done(localOnly ? "copied · local link" : "copied"), () => done("copy failed"));
  };
  return (
    <span className="legend-actions hdr-actions">
      <button
        onClick={copy}
        title={localOnly ? "copy a link that reproduces this view. It points at this computer (127.0.0.1): publish the dataset to share it" : "copy a link that reproduces this view"}
      >
        {copied || "copy link"}
      </button>
      <button onClick={() => void window.__sscape?.controller?.exportPNG()} title="download the current view as PNG with legend and scale bar">
        PNG
      </button>
    </span>
  );
}

/** The panel's five groups, each a bar that opens its controls and shows a one-line summary when closed. Several can
 * be open at once; what is open is remembered per browser. Image and Transcripts carry their switch in the bar. */
function Groups({ genes, activeTab }: { genes: string[]; activeTab: "explore" | "layers" | "samples" }) {
  const manifest = useViewer((s) => s.manifest)!;
  const showImages = useViewer((s) => s.showImages);
  const showCells = useViewer((s) => s.showCells);
  const imageOpacity = useViewer((s) => s.imageOpacity);
  const hiddenChannels = useViewer((s) => s.hiddenChannels);
  const molecules = useViewer((s) => s.molecules);
  const pins = useViewer((s) => s.moleculeGenes);
  const moleculeColors = useViewer((s) => s.moleculeColors);
  const color = useViewer((s) => s.color);
  const selection = useViewer((s) => s.selectionSummary);
  const regions = useViewer((s) => s.regions);
  const layoutMode = useViewer((s) => s.layoutMode);
  const splitBy = useViewer((s) => s.splitBy);
  const focus = useViewer((s) => s.focus);
  const comparison = useViewer((s) => s.comparison);
  const comparisonLevel = useViewer((s) => s.comparisonLevel);
  const set = store.getState().set;
  const hasImages = manifest.samples.some((s) => s.images.length);
  const comparisons = manifest.comparisons ?? [];
  const activeComparison = comparisons.find((c) => c.id === comparison);
  const comparisonText = activeComparison
    ? [activeComparison.name, activeComparison.levels.length > 1 ? (activeComparison.levels.find((l) => l.id === comparisonLevel) ?? activeComparison.levels[0]).name : null].filter(Boolean).join(" · ")
    : comparisons.length === 1
      ? comparisonSummary(comparisons[0])
      : `${comparisons.length} available`;
  const hasMolecules = manifest.samples.some((s) => s.molecules);
  const channelRows = channelSummary(manifest);
  const fieldName = (id: string) => manifest.fields.find((f) => f.id === id)?.name ?? id;
  const colorSummary = !color ? "no colour" : color.kind === "gene" ? color.gene : color.kind === "blend" ? "blend" : fieldName(color.field);
  const sections = manifest.samples.filter((s) => s.kind !== "embedding").length;
  const sampleSummary = [`${sections} section${sections === 1 ? "" : "s"}`, splitBy ? `split by ${splitBy.key}` : layoutMode, focus ? `focused on ${manifest.samples.find((s) => s.id === focus)?.name ?? focus}` : null].filter(Boolean).join(" · ");
  const nRegions = regions.groups.reduce((n, g) => n + g.polygons.length, 0);
  const selectionSummary = selection?.total ? `${selection.total.toLocaleString()} cells selected` : nRegions ? `${nRegions} region${nRegions === 1 ? "" : "s"} drawn` : "lasso, regions";
  const transcriptSummary = !molecules ? "off" : [moleculeColors === "all" ? "all genes" : color?.kind === "gene" ? color.gene : color?.kind === "blend" ? "blend" : "other genes grey", pins.length ? `${pins.length} pinned` : null].filter(Boolean).join(" · ");
  const imageSummary = !showImages ? "off" : channelRows ? `${channelRows - hiddenChannels.length} of ${channelRows} channels` : `${Math.round(imageOpacity * 100)}%`;
  return (
    <>
      <div role="tabpanel" id="inspector-panel-layers" aria-labelledby="inspector-tab-layers" hidden={activeTab !== "layers"}>
      {hasImages && (
        <Group id="image" title="Image" summary={imageSummary} on={showImages} onToggle={(v) => set({ showImages: v })}>
          <label>
            opacity <small>{(imageOpacity * 100).toFixed(0)}%</small>
            <input type="range" min={0} max={1} step={0.02} value={imageOpacity} onChange={(e) => set({ imageOpacity: +e.target.value })} />
          </label>
          <ImageChannels />
        </Group>
      )}
      {hasMolecules && (
        <Group id="transcripts" title="Transcripts" summary={transcriptSummary} on={molecules} onToggle={(v) => set({ molecules: v })}>
          <MoleculeGenes genes={genes} />
        </Group>
      )}
      </div>
      <div role="tabpanel" id="inspector-panel-explore" aria-labelledby="inspector-tab-explore" hidden={activeTab !== "explore"}>
      <Group id="cells" title="Cells" summary={showCells ? colorSummary : "off"} on={showCells} onToggle={(v) => set({ showCells: v })} defaultOpen>
        <ColorPanel genes={genes} />
        <Legend />
        <GeneByAnnotation />
        <FilterPanel genes={genes} />
        <CellRows />
      </Group>
      {comparisons.length > 0 && (
        <Group id="comparisons" title="Comparisons" summary={comparisonText} on={!!activeComparison} onToggle={(v) => (v ? reopenComparison() : void activateComparison(null))}>
          <CompareGroup />
        </Group>
      )}
      <Group id="selections" title="Selections" summary={selectionSummary}>
        <SelectionPanel controller={() => window.__sscape?.controller ?? null} />
        <RegionsPanel />
      </Group>
      </div>
      <div role="tabpanel" id="inspector-panel-samples" aria-labelledby="inspector-tab-samples" hidden={activeTab !== "samples"}>
      <Group id="samples" title="Samples" summary={sampleSummary}>
        <SampleStrip />
      </Group>
      </div>
    </>
  );
}
