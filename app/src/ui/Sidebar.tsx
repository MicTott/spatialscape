import { useMemo, useState } from "react";
import type { FeatureList } from "../data/manifest";
import { store, useViewer, type FilterSpec } from "../store/store";
import { GeneSearch } from "./GeneSearch";
import { BlendPanel } from "./BlendPanel";
import { GeneByAnnotation } from "./GeneByAnnotation";
import { SelectionPanel } from "./SelectionPanel";
import { RegionsPanel } from "./RegionsPanel";
import { Legend } from "./Legend";
import { SampleStrip } from "./SampleStrip";
import { CompareSelect } from "../compare/CompareSelect";

export function Sidebar() {
  const manifest = useViewer((s) => s.manifest);
  const features = useViewer((s) => s.features);
  const genes = features?.genes ?? [];
  const collapsed = !useViewer((s) => s.sidebarOpen);

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
            {manifest.description && <p className="muted">{manifest.description}</p>}
          </header>
          <SelectionPanel controller={() => window.__sscape?.controller ?? null} />
          <RegionsPanel />
          <ColorPanel genes={genes} />
          <CompareSelect />
          <Legend />
          <GeneByAnnotation />
          <FilterPanel genes={genes} />
          <OutlinePanel />
          <DisplayPanel />
          <SampleStrip />
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

const GROUP_LIST_MAX = 200;

function ColorPanel({ genes }: { genes: string[] }) {
  const manifest = useViewer((s) => s.manifest)!;
  const features = useViewer((s) => s.features);
  const color = useViewer((s) => s.color);
  const colormap = useViewer((s) => s.colormap);
  const geneMin = useViewer((s) => s.geneMin);
  const vrange = useViewer((s) => s.vrange);
  const hideZeros = useViewer((s) => s.hideZeros);
  const scalePerSample = useViewer((s) => s.scalePerSample);
  const recent = useViewer((s) => s.recentGenes);
  const set = store.getState().set;
  const groups = features?.groups ?? [];
  // feature id -> its group, built once per feature list (a peak set can hold hundreds of thousands of entries)
  const groupIndex = useMemo(() => {
    const m = new Map<string, FeatureList["groups"][number]>();
    for (const g of groups) for (const f of g.features) m.set(f.id, g);
    return m;
  }, [groups]);
  const isGene = color?.kind === "gene";
  const isBlend = color?.kind === "blend";
  const activeGroup = isGene ? groupIndex.get(color.gene) : undefined;
  const fields = manifest.fields;
  const plainGene = isGene && !activeGroup ? color.gene : undefined;
  const [lastGene, setLastGene] = useState(manifest.defaultGene ?? genes[0] ?? "");
  const lastPlain = plainGene ?? lastGene;
  const [groupQuery, setGroupQuery] = useState("");
  // the list shows at most GROUP_LIST_MAX rows (plus the current feature): a 350k-peak group would otherwise put
  // 350k nodes in the page and slow every interaction
  const current = isGene ? color.gene : null;
  const shown = useMemo(() => {
    if (!activeGroup) return { rows: [] as { id: string; label: string }[], total: 0 };
    const q = groupQuery.trim().toLowerCase();
    const all = q ? activeGroup.features.filter((f) => f.label.toLowerCase().includes(q)) : activeGroup.features;
    const rows = all.slice(0, GROUP_LIST_MAX);
    if (current && !rows.some((f) => f.id === current)) {
      const cur = activeGroup.features.find((f) => f.id === current);
      if (cur) rows.unshift(cur);
    }
    return { rows, total: all.length };
  }, [activeGroup, groupQuery, current]);
  return (
    <section>
      <h2>Color by</h2>
      <div className="tabs">
        <button className={isGene && !activeGroup ? "on" : ""} onClick={() => store.getState().setColor({ kind: "gene", gene: lastPlain })}>
          Gene
        </button>
        {groups.map((g) => (
          <button key={g.id} className={activeGroup?.id === g.id ? "on" : ""} onClick={() => g.features[0] && store.getState().setColor({ kind: "gene", gene: g.features[0].id })} title={g.name}>
            {g.name.replace(/\s*\(.*\)$/, "")}
          </button>
        ))}
        <button className={isBlend ? "on" : ""} onClick={() => store.getState().setColor({ kind: "blend", a: isGene && !activeGroup ? [color.gene] : [], b: [], scheme: "yb" })} title="two gene sets, blended colors">
          Blend
        </button>
        <button className={color?.kind === "field" ? "on" : ""} onClick={() => fields[0] && store.getState().setColor({ kind: "field", field: color?.kind === "field" ? color.field : fields[0].id })}>
          Annotation
        </button>
      </div>
      {isBlend ? (
        <BlendPanel genes={genes} />
      ) : isGene && activeGroup ? (
        <div className="grouplist">
          <input placeholder={`search ${activeGroup.name.toLowerCase()}…`} value={groupQuery} onChange={(e) => setGroupQuery(e.target.value)} spellCheck={false} />
          <ul>
            {shown.rows.map((f) => (
              <li key={f.id} className={f.id === color.gene ? "on" : ""} onClick={() => store.getState().setColor({ kind: "gene", gene: f.id })}>
                {f.label}
              </li>
            ))}
          </ul>
          <div className="muted small genecount">
            {shown.total > GROUP_LIST_MAX
              ? `${GROUP_LIST_MAX} of ${shown.total.toLocaleString()} shown · type to narrow`
              : `${shown.total.toLocaleString()} of ${activeGroup.features.length.toLocaleString()}`}
          </div>
        </div>
      ) : isGene ? (
        <>
          <GeneSearch
            genes={genes}
            value={color.gene}
            onPick={(g) => {
              setLastGene(g);
              store.getState().setColor({ kind: "gene", gene: g });
            }}
          />
          <div className="muted small genecount">{genes.length.toLocaleString()} genes · type to search</div>
          {recent.filter((g) => g !== color.gene).length > 0 && (
            <div className="chips recent" title="recent genes">
              {recent
                .filter((g) => g !== color.gene)
                .map((g) => (
                  <button key={g} className="chip" onClick={() => store.getState().setColor({ kind: "gene", gene: g })}>
                    {g}
                  </button>
                ))}
            </div>
          )}
        </>
      ) : (
        <select value={color?.kind === "field" ? color.field : ""} onChange={(e) => store.getState().setColor({ kind: "field", field: e.target.value })}>
          {(() => {
            const n = manifest.samples.length;
            const avail = (fid: string) => manifest.samples.filter((smp) => smp.fields.includes(fid)).length;
            const all = fields.filter((f) => avail(f.id) === n);
            const some = fields.filter((f) => avail(f.id) < n);
            const opt = (f: (typeof fields)[number]) => (
              <option key={f.id} value={f.id}>
                {f.name}
                {avail(f.id) < n ? ` (${avail(f.id)}/${n} samples)` : ""}
              </option>
            );
            return (
              <>
                {all.length > 0 && <optgroup label="all samples">{all.map(opt)}</optgroup>}
                {some.length > 0 && <optgroup label="some samples">{some.map(opt)}</optgroup>}
              </>
            );
          })()}
        </select>
      )}
      {(isGene || isBlend || (color?.kind === "field" && manifest.fields.find((f) => f.id === color.field)?.type === "continuous")) && (
        <div className="controls">
          {!isBlend && (
            <label>
              colormap
              <select value={colormap} onChange={(e) => set({ colormap: e.target.value })}>
                {manifest.colormaps.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </select>
              {geneMin < 0 && <small className="muted">signed feature: drawn with a diverging map centred on zero</small>}
            </label>
          )}
          <RangeSlider value={vrange} onChange={(v) => set({ vrange: v })} label="range" />
          <label className="check">
            <input type="checkbox" checked={hideZeros} onChange={(e) => set({ hideZeros: e.target.checked })} /> hide zeros
          </label>
          {(isGene || isBlend) && (
            <label className="check" title="off: one shared scale across samples, so colors are comparable. on: each sample is stretched to its own maximum">
              <input type="checkbox" checked={scalePerSample} onChange={(e) => set({ scalePerSample: e.target.checked })} /> scale each sample to its own max
            </label>
          )}
        </div>
      )}
    </section>
  );
}

function RangeSlider({ value, onChange, label }: { value: [number, number]; onChange: (v: [number, number]) => void; label: string }) {
  return (
    <div className="range">
      <span className="range-label">
        {label} <small>{(value[0] * 100).toFixed(0)}–{(value[1] * 100).toFixed(0)}%</small>
      </span>
      <input type="range" min={0} max={1} step={0.005} value={value[0]} onChange={(e) => onChange([Math.min(+e.target.value, value[1] - 0.005), value[1]])} />
      <input type="range" min={0} max={1} step={0.005} value={value[1]} onChange={(e) => onChange([value[0], Math.max(+e.target.value, value[0] + 0.005)])} />
    </div>
  );
}

function FilterPanel({ genes }: { genes: string[] }) {
  const manifest = useViewer((s) => s.manifest)!;
  const filter = useViewer((s) => s.filter);
  const hist = useViewer((s) => s.filterHistogram);
  const visible = useViewer((s) => s.visibleCount);
  const colorGene = useViewer((s) => (s.color?.kind === "gene" ? s.color.gene : null));
  const total = manifest.samples.reduce((a, s) => a + s.nObs, 0);
  const contFields = manifest.fields.filter((f) => f.type === "continuous");
  const setF = (f: FilterSpec | null) => store.getState().setFilter(f);
  const kindValue = !filter ? "none" : filter.kind === "gene" ? "gene" : filter.kind === "category" ? `cat:${filter.field}` : `field:${filter.field}`;
  const catFields = manifest.fields.filter((f) => f.type === "categorical");
  return (
    <section>
      <h2 title="Filters hide cells; the coloring stays as it is">Filter by</h2>
      <select
        value={kindValue}
        onChange={(e) => {
          const v = e.target.value;
          if (v === "none") setF(null);
          else if (v === "gene") setF({ kind: "gene", gene: filter?.kind === "gene" ? filter.gene : colorGene ?? manifest.defaultGene ?? genes[0] ?? "", range: [0.05, 1] });
          else if (v.startsWith("cat:")) setF({ kind: "category", field: v.slice(4), codes: [] });
          else setF({ kind: "field", field: v.slice(6), range: [0, 1] });
        }}
      >
        <option value="none">no filter</option>
        <option value="gene">gene expression</option>
        {contFields.map((f) => (
          <option key={f.id} value={`field:${f.id}`}>
            {f.name}
          </option>
        ))}
        {catFields.map((f) => (
          <option key={f.id} value={`cat:${f.id}`}>
            {f.name} (categories)
          </option>
        ))}
      </select>
      {filter?.kind === "gene" && <GeneSearch genes={genes} value={filter.gene} onPick={(g) => setF({ ...filter, gene: g })} />}
      {filter?.kind === "category" && (
        <div className="grouplist">
          <ul>
            {manifest.vocabularies[(manifest.fields.find((f) => f.id === filter.field) as any)?.vocabulary]?.categories.map((c, i) => (
              <li
                key={c}
                className={filter.codes.includes(i) ? "on" : ""}
                onClick={() => setF({ ...filter, codes: filter.codes.includes(i) ? filter.codes.filter((x) => x !== i) : [...filter.codes, i].sort((a, b) => a - b) })}
              >
                {c}
              </li>
            ))}
          </ul>
          <div className="muted small">{filter.codes.length ? `${filter.codes.length} selected` : "pick categories to keep (nothing hidden until you do)"}</div>
        </div>
      )}
      {filter && filter.kind !== "category" && (
        <>
          {hist && <Histogram bins={hist} range={filter.range} />}
          <RangeSlider value={filter.range} onChange={(r) => setF({ ...filter, range: r })} label="keep" />
          {visible != null && (
            <div className="muted small">
              {visible.toLocaleString()} of {total.toLocaleString()} cells pass
            </div>
          )}
        </>
      )}
    </section>
  );
}

function Histogram({ bins, range }: { bins: number[]; range: [number, number] }) {
  const max = Math.max(1, ...bins.slice(1)); // ignore the zero bin, usually huge
  return (
    <div className="hist">
      {bins.map((b, i) => {
        const x = i / bins.length;
        const inRange = x >= range[0] - 1e-9 && x <= range[1];
        return <div key={i} className={inRange ? "bar on" : "bar"} style={{ height: `${Math.min(100, (100 * b) / max)}%` }} />;
      })}
    </div>
  );
}

function OutlinePanel() {
  const manifest = useViewer((s) => s.manifest)!;
  const outline = useViewer((s) => s.outline);
  const set = store.getState().set;
  const fields = manifest.fields.filter((f) => f.type === "categorical" && manifest.samples.some((s) => s.outlines?.includes(f.id)));
  if (!fields.length) return null;
  return (
    <section>
      <h2 title="Annotation boundaries drawn over any coloring">Outlines</h2>
      <select value={outline.field ?? ""} onChange={(e) => set({ outline: { ...outline, field: e.target.value || null } })}>
        <option value="">none</option>
        {fields.map((f) => (
          <option key={f.id} value={f.id}>
            {f.name}
          </option>
        ))}
      </select>
    </section>
  );
}

function DisplayPanel() {
  const manifest = useViewer((s) => s.manifest)!;
  const showImages = useViewer((s) => s.showImages);
  const showPolygons = useViewer((s) => s.showPolygons);
  const clusterLabels = useViewer((s) => s.clusterLabels);
  const imageOpacity = useViewer((s) => s.imageOpacity);
  const layoutMode = useViewer((s) => s.layoutMode);
  const set = store.getState().set;
  const hasImages = manifest.samples.some((s) => s.images.length);
  return (
    <section>
      <h2>Display</h2>
      <div className="tabs">
        <button className={layoutMode === "grid" ? "on" : ""} onClick={() => set({ layoutMode: "grid" })}>
          Grid
        </button>
        <button className={layoutMode === "strip" ? "on" : ""} onClick={() => set({ layoutMode: "strip" })}>
          Strip
        </button>
      </div>
      {manifest.samples.some((s) => s.polygons) && (
        <label className="check">
          <input type="checkbox" checked={showPolygons} onChange={(e) => set({ showPolygons: e.target.checked })} /> cell boundaries when zoomed in
        </label>
      )}
      {manifest.samples.some((s) => s.kind === "embedding") && (
        <label className="check">
          <input type="checkbox" checked={clusterLabels} onChange={(e) => set({ clusterLabels: e.target.checked })} /> label clusters in the embedding
        </label>
      )}
      {hasImages && (
        <>
          <label className="check">
            <input type="checkbox" checked={showImages} onChange={(e) => set({ showImages: e.target.checked })} /> show images
          </label>
          <label>
            image opacity <small>{(imageOpacity * 100).toFixed(0)}%</small>
            <input type="range" min={0} max={1} step={0.02} value={imageOpacity} disabled={!showImages} onChange={(e) => set({ imageOpacity: +e.target.value })} />
          </label>
        </>
      )}
    </section>
  );
}
