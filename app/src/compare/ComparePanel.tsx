/** The Compare panel under the maps. Left: a matrix of genes by levels (every cluster of a marker table, every
 *  cell type a contrast was fit in, or the one column of a plain two-group result), each cell the log2 fold change
 *  as a chip tinted by sign and size, the level's legend colour in its column head; click a head to focus that
 *  level and sort by it, click a row to colour the maps by the gene, ↑/↓ to step. Right, for the gene on screen:
 *  its expression per category as violins (drawn from the same per-cell values the maps use) when the levels are
 *  an annotation's categories, or one dot per replicate with a median line and a box on request when the
 *  comparison carries pseudobulk values; the table's numbers for the gene in the focused level sit under the plot.
 *  The top edge drags to resize. Nothing statistical is computed here: the matrix is what the tables held. */
import { useEffect, useMemo, useRef, useState } from "react";
import { fieldById } from "../data/manifest";
import { COMPARE_BOX_KEY, COMPARE_HEIGHT_KEY, store, useViewer, type GroupRow, type GroupStats } from "../store/store";
import type { LevelInfo } from "../data/manifest";
import { activateComparison, populationFilterActive, toggleLevelFilter } from "./activate";
import { loadComparison, loadMatrix } from "./data";
import { arrangeMatrix, fmtEffect, fmtMean, fmtP, fmtPct, groupColors, groupValues, jitter, levelOf, matrixRows, matrixStat, pairs, ticks, type ComparisonData, type MatrixData, type MatrixRow } from "./model";

const ROW_H = 27;
const HEAD_H = 34;
const GENE_W = 132;
const COL_W = 96;
const clampHeight = (h: number) => Math.max(200, Math.min(Math.max(200, window.innerHeight - 220), Math.round(h)));

export function ComparePanel() {
  const manifest = useViewer((s) => s.manifest);
  const datasetUrl = useViewer((s) => s.datasetUrl);
  const id = useViewer((s) => s.comparison);
  const levelId = useViewer((s) => s.comparisonLevel);
  const color = useViewer((s) => s.color);
  const sidebarOpen = useViewer((s) => s.sidebarOpen);
  const height = useViewer((s) => s.compareHeight);
  const box = useViewer((s) => s.compareBox);
  const genomeOn = useViewer((s) => s.genome && !!s.manifest?.samples.some((x) => x.tracks));
  const genomeHeight = useViewer((s) => s.genomeHeight);
  const population = useViewer(populationFilterActive);
  const groupStats = useViewer((s) => s.groupStats);
  const info = manifest?.comparisons?.find((c) => c.id === id) ?? null;
  const level = info ? levelOf(info, levelId) : null;
  const [matrix, setMatrix] = useState<MatrixData | null>(null);
  const [levelData, setLevelData] = useState<ComparisonData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [desc, setDesc] = useState(true);
  const [query, setQuery] = useState("");

  useEffect(() => {
    setMatrix(null);
    setError(null);
    if (!info || !datasetUrl) return;
    let cancelled = false;
    loadMatrix(datasetUrl, info)
      .then((m) => !cancelled && setMatrix(m))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [info, datasetUrl]);
  useEffect(() => {
    setLevelData(null);
    if (!info || !level || !datasetUrl || !level.hasPseudobulk) return;
    let cancelled = false;
    loadComparison(datasetUrl, info, level.id)
      .then((d) => !cancelled && setLevelData(d))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [info, level, datasetUrl]);
  // the violins and the dot plot read the facet field: make it the grouping field while the comparison is open
  // (a comparison opened from the URL never went through activateComparison)
  const facetFieldId = info?.facet?.field ?? null;
  useEffect(() => {
    if (facetFieldId && store.getState().groupField !== facetFieldId) store.getState().set({ groupField: facetFieldId });
  }, [facetFieldId]);

  const stat = matrix ? matrixStat(matrix) : "effect";
  const col = matrix && level ? matrix.levels.indexOf(level.id) : -1;
  const all = useMemo(() => (matrix ? matrixRows(matrix) : []), [matrix]);
  const descending = stat === "effect" ? desc : !desc;
  const shown = useMemo(() => (matrix ? arrangeMatrix(matrix, all, stat, col, descending, query) : []), [matrix, all, stat, col, descending, query]);
  const gene = color?.kind === "gene" ? color.gene : null;
  const geneRow = gene && matrix ? (matrix.geneIndex.get(gene) ?? null) : null;

  // a comparison always shows a gene: when the colour is not one of its genes, the top of the focused level
  useEffect(() => {
    if (!matrix || col < 0) return;
    const cur = store.getState().color;
    if (cur?.kind === "gene" && matrix.geneIndex.has(cur.gene)) return;
    const first = arrangeMatrix(matrix, matrixRows(matrix), matrixStat(matrix), col, matrixStat(matrix) === "effect", "").find((r) => r.measured);
    if (first) store.getState().setColor({ kind: "gene", gene: first.gene });
  }, [matrix, col]);

  // ↑ / ↓ step through the table as sorted; the map follows
  useEffect(() => {
    if (!matrix) return;
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
      if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
      const measured = shown.filter((r) => r.measured);
      if (!measured.length) return;
      const k = measured.findIndex((r) => r.gene === gene);
      const next = measured[(k < 0 ? 0 : k + (e.key === "ArrowDown" ? 1 : -1) + measured.length) % measured.length];
      store.getState().setColor({ kind: "gene", gene: next.gene });
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [matrix, shown, gene]);

  const onHandleDown = (e: React.PointerEvent) => {
    const y0 = e.clientY;
    const h0 = store.getState().compareHeight;
    const move = (ev: PointerEvent) => store.getState().set({ compareHeight: clampHeight(h0 + (y0 - ev.clientY)) });
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      try {
        localStorage.setItem(COMPARE_HEIGHT_KEY, String(store.getState().compareHeight));
      } catch {
        /* private mode */
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    e.preventDefault();
  };
  const toggleBox = () => {
    const v = !store.getState().compareBox;
    store.getState().set({ compareBox: v });
    try {
      localStorage.setItem(COMPARE_BOX_KEY, v ? "1" : "0");
    } catch {
      /* private mode */
    }
  };

  if (!manifest || !info || !level) return null;
  const markers = info.kind === "markers";
  const facetField = info.facet?.field ? fieldById(manifest, info.facet.field) : undefined;
  const vocab = facetField?.type === "categorical" ? manifest.vocabularies[facetField.vocabulary] : null;
  // a level's category: the one it was linked to (through the field's aliases: AI -> IA), else its own name
  const catOf = (l: LevelInfo) => l.population?.value ?? l.name;
  const swatch = (name: string): string | undefined => {
    const k = vocab ? vocab.categories.indexOf(name) : -1;
    return k >= 0 ? vocab!.colors[k] : undefined;
  };
  const hasDots = !!(levelData && levelData.replicates.length && levelData.pseudobulk);
  const hasViolins = !!(vocab && groupStats && groupStats.field === facetField!.id && gene && groupStats.gene === gene);
  const bottom = 26 + (genomeOn ? genomeHeight : 0);
  const focusHeader = (lv: string) => {
    if (lv === level.id) setDesc((d) => !d);
    else void activateComparison(info.id, lv);
  };
  const subtitle = [
    markers ? `each ${facetField ? facetField.name.toLowerCase() : "cluster"} against the rest` : info.groups.join(" vs ") + (info.levels.length > 1 && facetField ? ` within each ${facetField.name.toLowerCase()}` : ""),
    !markers && info.nReplicates ? `${info.nReplicates} replicates` : null,
    matrix ? `${matrix.genes.length.toLocaleString()} genes` : null,
    info.nUnmatched ? `${info.nUnmatched.toLocaleString()} not in this dataset` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const single = info.levels.length === 1;
  const focusLabel = single ? (markers ? level.name : info.groups.join(" vs ")) : level.name;
  const focusColor = swatch(catOf(level));
  const levelRow = levelData && gene ? (levelData.geneIndex.get(gene) ?? null) : null;
  const foot = footerText({ matrix, geneRow, col, levelData, levelRow, markers, levelName: focusLabel, levelGenes: level.nGenes });
  return (
    <div className={`compare${sidebarOpen ? " with-sidebar" : ""}`} style={{ height, bottom }}>
      <div className="c-handle" onPointerDown={onHandleDown} title="drag to resize" />
      <div className="c-grip" />
      <div className="c-head">
        <span className="c-title">{info.name}</span>
        <span className="c-sub">{subtitle}</span>
        <label className="c-searchwrap" title="find a gene in the table">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input className="c-search" placeholder="Find a gene" value={query} onChange={(e) => setQuery(e.target.value)} spellCheck={false} />
        </label>
        {info.description && (
          <button className="c-ib" title={info.description} aria-label="how this was computed">
            i
          </button>
        )}
        <button className="c-ib" onClick={() => void activateComparison(null)} title="close the panel (the split and the filter stay); the Comparisons group reopens it" aria-label="close">
          ×
        </button>
      </div>
      <div className="c-body">
        <div className="c-matrix">
          {error && <div className="muted small c-note">could not load the comparison: {error}</div>}
          {!matrix && !error && <div className="muted small c-note">loading…</div>}
          {matrix && <MatrixTable matrix={matrix} rows={shown} stat={stat} gene={gene} focus={level.id} desc={descending} onFocus={focusHeader} labels={info.levels.map((l) => l.name)} colors={info.levels.map((l) => swatch(catOf(l)))} single={single ? focusLabel : null} />}
        </div>
        <div className="c-dist">
          <div className="d-head">
            <span className="d-gene">{gene ?? "—"}</span>
            {focusColor ? (
              <span className="d-tag" style={{ color: focusColor, background: `color-mix(in srgb, ${focusColor} 18%, transparent)` }}>
                <i />
                {focusLabel}
              </span>
            ) : (
              <span className="d-tag plain">{focusLabel}</span>
            )}
            {markers && <span className="muted small">vs rest</span>}
            <span className="d-right">
              {markers && level.population && (
                <label className="d-toggle" title={population ? "show every cell again" : `filter the map to the cells of ${level.name}`}>
                  <input type="checkbox" checked={!!population} onChange={toggleLevelFilter} />
                  only {level.name} on the map
                </label>
              )}
              {!markers && population && (
                <span className="chip pop" title={`the comparison was fit in these cells; the map is filtered to them (field ${population.field})`}>
                  map filtered to {population.value}
                  <button onClick={() => store.getState().setFilter(null)} title="clear the filter">
                    ×
                  </button>
                </span>
              )}
              {hasDots && (
                <button className={`c-ib text${box ? " on" : ""}`} onClick={toggleBox} title="draw the quartiles behind the dots">
                  box
                </button>
              )}
            </span>
          </div>
          <div className="d-plot">
            {hasDots && levelData && levelRow != null ? (
              <ReplicatePlot data={levelData} geneRow={levelRow} box={box} />
            ) : hasViolins && vocab ? (
              <Violins stats={groupStats!} vocab={vocab} focus={catOf(level)} order={info.levels.map((l) => catOf(l))} gene={gene!} />
            ) : (
              <div className="muted small c-note">{!matrix ? "" : !gene ? "pick a gene in the table" : vocab ? "computing the distributions…" : "no replicate values in this comparison; add `pseudobulk:` for a dot per replicate"}</div>
            )}
          </div>
          <div className="d-foot" title={foot.title}>
            {foot.parts.map((p, k) => (
              <span key={k}>
                {k > 0 ? " · " : ""}
                {k === 0 ? <b>{p}</b> : p}
              </span>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

/** The footer under the plot: the table's numbers for the gene in the focused level. */
function footerText(a: { matrix: MatrixData | null; geneRow: number | null; col: number; levelData: ComparisonData | null; levelRow: number | null; markers: boolean; levelName: string; levelGenes: number }): { parts: string[]; title: string } {
  const { matrix, geneRow, col, levelData, levelRow, markers, levelName, levelGenes } = a;
  if (!matrix || geneRow == null) return { parts: [], title: "" };
  const k = matrix.levels.length;
  const at = (name: string): number | null => {
    const v = matrix.stats[name]?.[geneRow * k + col];
    return v == null || Number.isNaN(v) ? null : v;
  };
  const parts: string[] = [];
  const eff = at("effect");
  if (eff != null) parts.push(`log2FC ${fmtEffect(eff)}`);
  const padj = at("padj");
  const p = at("p");
  if (padj != null) parts.push(`padj ${fmtP(padj)}`);
  else if (p != null) parts.push(`p ${fmtP(p)}`);
  const pin = at("pct_in");
  const pout = at("pct_out");
  if (pin != null || pout != null) parts.push(markers ? `${fmtPct(pin)}% of ${levelName} cells express it, ${fmtPct(pout)}% of the rest` : `expressed in ${fmtPct(pin)}% / ${fmtPct(pout)}%`);
  if (levelData && levelRow != null && levelData.results.mean) {
    const m = levelData.results.mean[levelRow];
    if (m != null) parts.push(`mean ${fmtMean(m)}`);
  }
  const rank = at("rank");
  if (!parts.length && rank != null) parts.push(`rank ${rank} of ${levelGenes} in ${levelName}`);
  if (col < 0) return { parts: [], title: "" };
  return { parts, title: `${matrix.genes[geneRow]} in ${levelName}` };
}

/** genes x levels, windowed by rows, scrolling both ways; the gene column stays put, the focused column is lit. */
function MatrixTable({ matrix, rows: list, stat, gene, focus, desc, onFocus, labels, colors, single }: { matrix: MatrixData; rows: MatrixRow[]; stat: "effect" | "rank"; gene: string | null; focus: string; desc: boolean; onFocus: (level: string) => void; labels: string[]; colors: (string | undefined)[]; single: string | null }) {
  const ref = useRef<HTMLDivElement>(null);
  const [top, setTop] = useState(0);
  const [h, setH] = useState(300);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setH(el.clientHeight));
    ro.observe(el);
    setH(el.clientHeight);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const el = ref.current;
    if (!el || !gene) return;
    const k = list.findIndex((r) => r.gene === gene);
    if (k < 0) return;
    const y = HEAD_H + k * ROW_H;
    if (y < el.scrollTop + HEAD_H || y + ROW_H > el.scrollTop + el.clientHeight) el.scrollTop = Math.max(0, y - el.clientHeight / 2);
  }, [gene, list]);
  const k = matrix.levels.length;
  const a = matrix.stats[stat];
  const maxAbs = useMemo(() => {
    let m = 0;
    for (let i = 0; i < a.length; i++) if (!Number.isNaN(a[i])) m = Math.max(m, Math.abs(a[i]));
    return m || 1;
  }, [a]);
  const nRank = useMemo(() => (stat === "rank" ? Math.max(1, ...Array.from(a).filter((v) => !Number.isNaN(v))) : 1), [a, stat]);
  const width = GENE_W + COL_W * k;
  const columns = `${GENE_W}px repeat(${k}, ${COL_W}px)`;
  const first = Math.max(0, Math.floor(top / ROW_H) - 8);
  const last = Math.min(list.length, Math.ceil((top + h) / ROW_H) + 8);
  const focusCol = matrix.levels.indexOf(focus);
  const tint = (v: number): string | undefined => {
    if (Number.isNaN(v)) return undefined;
    if (stat === "rank") return `color-mix(in srgb, var(--accent) ${Math.round(8 + 32 * (1 - (v - 1) / nRank))}%, transparent)`;
    const pct = Math.round(10 + 40 * Math.min(1, Math.abs(v) / maxAbs));
    return `color-mix(in srgb, var(${v >= 0 ? "--c-up" : "--c-down"}) ${pct}%, transparent)`;
  };
  const detail = (i: number, j: number): string => {
    const at = (name: string) => matrix.stats[name]?.[i * k + j];
    const bits: string[] = [];
    const eff = at("effect");
    if (eff != null && !Number.isNaN(eff)) bits.push(`log2FC ${fmtEffect(eff)}`);
    const padj = at("padj");
    if (padj != null && !Number.isNaN(padj)) bits.push(`padj ${fmtP(padj)}`);
    const pin = at("pct_in");
    const pout = at("pct_out");
    if (pin != null && !Number.isNaN(pin)) bits.push(`in ${fmtPct(pin)}% · out ${fmtPct(pout ?? null)}%`);
    const rank = at("rank");
    if (rank != null && !Number.isNaN(rank)) bits.push(`rank ${rank}`);
    return bits.length ? `${matrix.genes[i]} in ${labels[j]}: ${bits.join(" · ")}` : `${matrix.genes[i]}: not in ${labels[j]}'s table`;
  };
  return (
    <div className="m-scroll" ref={ref} onScroll={(e) => setTop((e.target as HTMLDivElement).scrollTop)}>
      {focusCol >= 0 && k > 1 && <div className="m-colbg" style={{ left: GENE_W + focusCol * COL_W, height: Math.max(HEAD_H + list.length * ROW_H, h) }} />}
      <div className="m-head" style={{ gridTemplateColumns: columns, width }}>
        <span className="m-gene">{stat === "effect" ? "Gene · log2FC" : "Gene · rank"}</span>
        {matrix.levels.map((lv, j) => (
          <button key={lv} className={lv === focus ? "on" : ""} onClick={() => onFocus(lv)} title={single ? `${single}: click to flip the order` : `${labels[j]}: click to sort by it and focus it`}>
            {colors[j] && <i style={{ background: colors[j] }} />}
            {single ?? labels[j]}
            {lv === focus ? (desc ? " ▾" : " ▴") : ""}
          </button>
        ))}
      </div>
      <div style={{ height: list.length * ROW_H, position: "relative", width }}>
        {list.slice(first, last).map((r, n) => {
          const i = first + n;
          return (
            <div
              key={r.gene}
              className={`m-row${r.gene === gene ? " on" : ""}${r.measured ? "" : " off"}`}
              style={{ top: i * ROW_H, gridTemplateColumns: columns, width }}
              title={r.measured ? "colour the maps by this gene" : "no section measures this gene"}
              onClick={() => r.measured && store.getState().setColor({ kind: "gene", gene: r.gene })}
            >
              <span className="m-gene">{r.gene}</span>
              {matrix.levels.map((lv, j) => {
                const v = a[r.i * k + j];
                const blank = Number.isNaN(v);
                return (
                  <span key={lv} className={`m-cell${blank ? " e" : ""}`} style={{ background: tint(v) }} title={detail(r.i, j)}>
                    {blank ? "" : stat === "rank" ? v : fmtEffect(v)}
                  </span>
                );
              })}
            </div>
          );
        })}
      </div>
      {!list.length && <div className="muted small c-note">no gene matches</div>}
    </div>
  );
}

/** The gene's expression per category as violins, from the histograms the dot plot already computes: the
 *  comparison's levels in its order, then every other category pooled into one "other" violin, so a 48-category
 *  annotation does not crowd the plot; the focused level in full colour, the rest dimmed; a tick at each median.
 *  Labels turn when the slots narrow and go when they are too narrow to read. */
function Violins({ stats, vocab, focus, order, gene }: { stats: GroupStats; vocab: { categories: string[]; colors: string[] }; focus: string; order: string[]; gene: string }) {
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<[number, number]>([320, 200]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize([el.clientWidth, el.clientHeight]));
    ro.observe(el);
    setSize([el.clientWidth, el.clientHeight]);
    return () => ro.disconnect();
  }, []);
  const rows = useMemo(() => {
    const byName = new Map(stats.rows.map((r) => [vocab.categories[r.code], r]));
    const seen = new Set<string>();
    const out: { name: string; color: string; row: GroupRow }[] = [];
    for (const name of order) {
      const r = byName.get(name);
      if (r && !seen.has(name)) {
        out.push({ name, color: vocab.colors[r.code], row: r });
        seen.add(name);
      }
    }
    const others = stats.rows.filter((r) => !seen.has(vocab.categories[r.code]));
    if (others.length) out.push({ name: others.length === 1 ? vocab.categories[others[0].code] : "other", color: others.length === 1 ? vocab.colors[others[0].code] : "#8b949e", row: pool(others, stats) });
    return out;
  }, [stats, vocab, order]);
  const [W, H] = size;
  const pad = { l: 44, r: 10, t: 18, b: 30 };
  const ph = Math.max(50, H - pad.t - pad.b);
  const pw = Math.max(80, W - pad.l - pad.r);
  const slot = Math.min(72, pw / Math.max(1, rows.length));
  const half = slot * 0.42;
  const { vmin, vmax, bins } = stats;
  const y = (v: number) => pad.t + ph - ((v - vmin) / (vmax - vmin)) * ph;
  const bw = (vmax - vmin) / bins;
  const x0 = pad.l + (pw - slot * rows.length) / 2;
  const turned = slot < 44; // labels turn 40 degrees
  const bare = slot < 18; // only the focused label
  const focusMissing = !rows.some((r) => r.name === focus); // no cell of the focused level has the gene on screen
  const path = (hist: number[], cx: number) => {
    const peak = Math.max(1, ...hist);
    const left: string[] = [];
    const right: string[] = [];
    for (let b = 0; b < bins; b++) {
      const w = (hist[b] / peak) * half;
      const yb = y(vmin + (b + 0.5) * bw);
      left.push(`${cx - w},${yb}`);
      right.unshift(`${cx + w},${yb}`);
    }
    return `M${left.join(" L")} L${right.join(" L")} Z`;
  };
  return (
    <div className="d-plotwrap" ref={ref}>
      <svg width={W} height={H}>
        <text x={pad.l} y={12} className="c-axis">
          log-normalized
        </text>
        {ticks(vmin, vmax).map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={pad.l + pw} y1={y(t)} y2={y(t)} className="c-grid" />
            <text x={pad.l - 8} y={y(t) + 3} className="c-tick">
              {fmtMean(t)}
            </text>
          </g>
        ))}
        {rows.map(({ name, color, row: r }, k) => {
          const cx = x0 + slot * (k + 0.5);
          const on = name === focus;
          const label = name.length > 11 && slot < 72 && !turned ? name.slice(0, 10) + "…" : name;
          const ly = pad.t + ph + (turned ? 10 : 16);
          return (
            <g key={name}>
              <title>{`${name} · ${r.n.toLocaleString()} cells · median ${fmtMean(r.median)} · ${(100 * r.frac).toFixed(0)}% expressing`}</title>
              <path d={path(r.hist, cx)} className={`violin${on ? "" : " dim"}`} style={{ fill: color }} />
              <line x1={cx - half * 0.55} x2={cx + half * 0.55} y1={y(r.median)} y2={y(r.median)} className="v-median" opacity={on ? 1 : 0.6} />
              {(on || !bare) && (
                <text x={cx} y={ly} className={`c-group${on ? " on" : ""}${turned ? " turned" : ""}`} style={{ fill: on ? color : undefined }} transform={turned ? `rotate(-40 ${cx} ${ly})` : undefined}>
                  {label}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      {focusMissing && <div className="d-missing">no {focus} cell on screen measures {gene}: the sections that carry {focus} do not include it</div>}
    </div>
  );
}

/** Several categories as one: histograms summed, quartiles read off the sum, mean and fraction weighted by cells. */
function pool(rows: GroupRow[], stats: GroupStats): GroupRow {
  const hist = new Array<number>(stats.bins).fill(0);
  let n = 0;
  let sum = 0;
  let pos = 0;
  for (const r of rows) {
    r.hist.forEach((v, b) => (hist[b] += v));
    n += r.n;
    sum += r.mean * r.n;
    pos += r.frac * r.n;
  }
  const width = (stats.vmax - stats.vmin) / stats.bins;
  const quantile = (q: number) => {
    let acc = 0;
    for (let b = 0; b < hist.length; b++) {
      acc += hist[b];
      if (acc >= q * n) return stats.vmin + (b + 0.5) * width;
    }
    return stats.vmax;
  };
  return { code: -1, n, mean: n ? sum / n : 0, frac: n ? pos / n : 0, perSample: {}, hist, median: quantile(0.5), q1: quantile(0.25), q3: quantile(0.75) };
}

/** One dot per replicate for the gene, by group; a median line, a box on request, lines between paired subjects. */
function ReplicatePlot({ data, geneRow, box }: { data: ComparisonData; geneRow: number; box: boolean }) {
  const manifest = useViewer((s) => s.manifest)!;
  const ref = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState<[number, number]>([320, 200]);
  const [hover, setHover] = useState<{ x: number; y: number; text: string } | null>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setSize([el.clientWidth, el.clientHeight]));
    ro.observe(el);
    setSize([el.clientWidth, el.clientHeight]);
    return () => ro.disconnect();
  }, []);
  const groups = useMemo(() => groupValues(data, geneRow), [data, geneRow]);
  const colors = useMemo(() => groupColors(manifest, data.info), [manifest, data.info]);
  const paired = useMemo(() => pairs(groups), [groups]);
  const [W, H] = size;
  const pad = { l: 46, r: 12, t: 18, b: 30 };
  const ph = Math.max(50, H - pad.t - pad.b);
  const pw = Math.max(80, W - pad.l - pad.r);
  const values = groups.flatMap((g) => g.values.map((v) => v.value));
  const any = values.length > 0;
  let lo = any ? Math.min(...values) : 0;
  let hi = any ? Math.max(...values) : 1;
  if (hi === lo) {
    lo -= 0.5;
    hi += 0.5;
  }
  const span = hi - lo;
  lo -= span * 0.08;
  hi += span * 0.08;
  const y = (v: number) => pad.t + ph - ((v - lo) / (hi - lo)) * ph;
  const slot = pw / Math.max(1, groups.length);
  const gx = (k: number) => pad.l + slot * (k + 0.5);
  const half = Math.min(22, slot * 0.22);
  return (
    <div className="d-plotwrap" ref={ref}>
      <svg width={W} height={H}>
        <text x={pad.l} y={12} className="c-axis">
          {data.info.units ?? "replicate value"}
        </text>
        {ticks(lo, hi).map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={pad.l + pw} y1={y(t)} y2={y(t)} className="c-grid" />
            <text x={pad.l - 8} y={y(t) + 3} className="c-tick">
              {fmtMean(t)}
            </text>
          </g>
        ))}
        {paired.map((p) => (
          <polyline key={p.subject} className="c-pair" points={p.points.map((pt) => `${gx(groups.findIndex((g) => g.group === pt.group)) + jitter(p.subject) * half * 0.5},${y(pt.value)}`).join(" ")} />
        ))}
        {groups.map((g, k) => (
          <g key={g.group}>
            {box && g.q1 != null && g.q3 != null && g.min != null && g.max != null && (
              <g className="c-box" style={{ color: colors[k] }}>
                <line x1={gx(k)} x2={gx(k)} y1={y(g.min)} y2={y(g.max)} />
                <rect x={gx(k) - half} width={half * 2} y={y(g.q3)} height={Math.max(1, y(g.q1) - y(g.q3))} />
              </g>
            )}
            {g.median != null && <line className="c-median" style={{ color: colors[k] }} x1={gx(k) - half - 4} x2={gx(k) + half + 4} y1={y(g.median)} y2={y(g.median)} />}
            {g.values.map(({ rep, value }) => {
              const cx = gx(k) + jitter(rep.subject) * half * 0.5;
              const cy = y(value);
              const where = rep.samples.length ? ` · ${rep.samples.length === 1 ? rep.samples[0] : `${rep.samples.length} sections`} (click to focus)` : " · no section";
              return (
                <g
                  key={rep.id}
                  className={`c-dot${rep.samples.length ? " link" : ""}`}
                  onPointerEnter={() => setHover({ x: cx, y: cy, text: `${rep.id} · ${fmtMean(value)}${where}` })}
                  onPointerLeave={() => setHover(null)}
                  onClick={() => rep.samples.length && store.getState().setFocus(rep.samples[0])}
                >
                  <circle cx={cx} cy={cy} r={10} className="c-hit" />
                  <circle cx={cx} cy={cy} r={5} style={{ fill: colors[k] }} />
                </g>
              );
            })}
            <text x={gx(k)} y={pad.t + ph + 16} className="c-group on" style={{ fill: colors[k] }}>
              {g.group}
              <tspan className="muted"> {g.values.length}</tspan>
            </text>
          </g>
        ))}
      </svg>
      {hover && (
        <div className="c-tip" style={{ left: hover.x, top: hover.y - 10 }}>
          {hover.text}
        </div>
      )}
    </div>
  );
}
