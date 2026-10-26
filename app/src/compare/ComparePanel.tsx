/** The Compare panel under the maps: the results table of the chosen comparison (and level) on the left (click a gene
 *  to colour the maps by it, ↑/↓ to step), on the right the replicate values of the current gene when the comparison
 *  has them (one dot per mouse or donor, a median line, a box on request, lines between paired subjects; click a dot
 *  to focus its section), else the table's numbers for that gene. A markers comparison lists the clusters as levels,
 *  each against the rest. The top edge drags to resize. */
import { useEffect, useMemo, useRef, useState } from "react";
import { COMPARE_BOX_KEY, COMPARE_HEIGHT_KEY, store, useViewer } from "../store/store";
import { activateComparison, populationFilterActive, toggleLevelFilter } from "./activate";
import { loadComparison } from "./data";
import { arrange, countSignificant, fmtEffect, fmtMean, fmtP, fmtPct, groupColors, groupValues, jitter, levelOf, pairs, rows, ticks, type ComparisonData, type Direction, type Row, type SortKey } from "./model";

const ROW_H = 22;
const clampHeight = (h: number) => Math.max(180, Math.min(Math.max(180, window.innerHeight - 220), Math.round(h)));

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
  const info = manifest?.comparisons?.find((c) => c.id === id) ?? null;
  const level = info ? levelOf(info, levelId) : null;
  const [data, setData] = useState<ComparisonData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sort, setSort] = useState<SortKey>("padj");
  const [desc, setDesc] = useState(false);
  const [dir, setDir] = useState<Direction>("all");
  const [query, setQuery] = useState("");

  useEffect(() => {
    setData(null);
    setError(null);
    if (!info || !level || !datasetUrl) return;
    let cancelled = false;
    loadComparison(datasetUrl, info, level.id)
      .then((d) => !cancelled && setData(d))
      .catch((e: Error) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [info, level, datasetUrl]);

  const all = useMemo(() => (data ? rows(data) : []), [data]);
  const shown = useMemo(() => arrange(all, sort, desc, dir, query), [all, sort, desc, dir, query]);
  const gene = color?.kind === "gene" ? color.gene : null;
  const geneRow = gene && data ? (data.geneIndex.get(gene) ?? null) : null;

  // ↑ / ↓ step through the table as sorted; the map follows
  useEffect(() => {
    if (!data) return;
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
  }, [data, shown, gene]);

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
  const hasEffect = info.hasEffect !== false;
  const hasP = info.hasPadj || info.hasP;
  const sig = countSignificant(all);
  const head = (key: SortKey, label: string, title: string) => (
    <button
      className={`c-sort${sort === key ? " on" : ""}`}
      title={title}
      onClick={() => {
        if (sort === key) setDesc((d) => !d);
        else {
          setSort(key);
          setDesc(key === "effect" || key === "mean" || key === "pct");
        }
      }}
    >
      {label}
      {sort === key ? (desc ? " ▾" : " ▴") : ""}
    </button>
  );
  const columns = `minmax(0, 1fr)${hasEffect ? " 88px" : ""}${hasP ? " 72px" : ""}${info.hasMean ? " 64px" : ""}${info.hasPct ? " 84px" : ""}`;
  const bottom = 26 + (genomeOn ? genomeHeight : 0);
  const hasPlot = data ? data.replicates.length > 0 && data.pseudobulk != null : info.hasPseudobulk;
  const against = markers ? "rest" : info.groups[0];
  const forGroup = markers ? level.name : info.groups[info.groups.length - 1];
  return (
    <div className={`compare${sidebarOpen ? " with-sidebar" : ""}`} style={{ height, bottom }}>
      <div className="c-handle" onPointerDown={onHandleDown} title="drag to resize" />
      <div className="c-head">
        <select value={info.id} onChange={(e) => void activateComparison(e.target.value || null)} title="which comparison to show">
          {(manifest.comparisons ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {info.levels.length > 1 && (
          <select className="c-level" value={level.id} onChange={(e) => void activateComparison(info.id, e.target.value)} title={markers ? "which cluster's markers" : `which ${info.facet?.field ?? "level"} the contrast was fit in`}>
            {info.levels.map((l) => (
              <option key={l.id} value={l.id}>
                {l.name}
              </option>
            ))}
          </select>
        )}
        <input className="c-search" placeholder="find a gene…" value={query} onChange={(e) => setQuery(e.target.value)} spellCheck={false} />
        {hasEffect && (
          <span className="tabs c-dir" title={markers ? "direction of the effect: the cluster against the rest" : "direction of the effect: the last group against the first"}>
            {(["all", "up", "down"] as Direction[]).map((d) => (
              <button key={d} className={dir === d ? "on" : ""} onClick={() => setDir(d)}>
                {d === "all" ? "all" : d === "up" ? `↑ ${forGroup}` : `↓ ${against}`}
              </button>
            ))}
          </span>
        )}
        <span className="muted c-count">
          {markers ? `${level.name} vs rest · ` : ""}
          {all.length.toLocaleString()} genes{hasP ? ` · ${sig.toLocaleString()} at ${info.hasPadj ? "padj" : "p"} < 0.05` : ""}
          {level.nUnmatched ? ` · ${level.nUnmatched.toLocaleString()} not in this dataset` : ""}
          {query || dir !== "all" ? ` · ${shown.length.toLocaleString()} listed` : ""}
        </span>
        {markers && level.population && (
          <button className={`c-sort${population ? " on" : ""}`} onClick={toggleLevelFilter} title={population ? "show every cell again" : `filter the map to the cells of ${level.name}`}>
            only {level.name}
          </button>
        )}
        {!markers && population && (
          <span className="chip pop" title={`the comparison was fit in these cells; the map is filtered to them (field ${population.field})`}>
            map filtered to {population.value}
            <button onClick={() => store.getState().setFilter(null)} title="clear the filter">
              ×
            </button>
          </span>
        )}
        <span className="right">
          {hasPlot && (
            <button className={`c-sort${box ? " on" : ""}`} onClick={toggleBox} title="draw the quartiles behind the dots">
              box
            </button>
          )}
          <button className="c-close" onClick={() => void activateComparison(null)} title="close the panel (the split and the filter stay); the Comparisons group reopens it">
            ×
          </button>
        </span>
      </div>
      <div className="c-body">
        <div className={`c-table${hasPlot ? "" : " wide"}`}>
          <div className="c-row c-thead" style={{ gridTemplateColumns: columns }}>
            {head("gene", hasEffect ? "gene" : "gene (rank)", "sort by name")}
            {hasEffect && head("effect", "effect", "sort by the size of the effect")}
            {hasP && head("padj", info.hasPadj ? "padj" : "p", "sort by adjusted p-value")}
            {info.hasMean && head("mean", "mean", "sort by mean expression")}
            {info.hasPct && head("pct", "% in / out", "share of cells expressing the gene inside the cluster and outside it")}
          </div>
          {error && <div className="muted small c-note">could not load the comparison: {error}</div>}
          {!data && !error && <div className="muted small c-note">loading…</div>}
          {data && <GeneTable rows={shown} gene={gene} columns={columns} hasEffect={hasEffect} hasP={hasP} hasMean={info.hasMean} hasPct={!!info.hasPct} />}
        </div>
        <div className="c-plot">
          {data && geneRow != null && hasPlot ? (
            <ReplicatePlot data={data} geneRow={geneRow} gene={gene!} box={box} />
          ) : data && geneRow != null ? (
            <GeneNote data={data} geneRow={geneRow} gene={gene!} markers={markers} />
          ) : data ? (
            <div className="muted c-note">pick a gene in the table, or colour the maps by one of its genes</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

/** A windowed list: only the rows in view are in the page. */
function GeneTable({ rows: list, gene, columns, hasEffect, hasP, hasMean, hasPct }: { rows: Row[]; gene: string | null; columns: string; hasEffect: boolean; hasP: boolean; hasMean: boolean; hasPct: boolean }) {
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
    // keep the current gene in view when it changes (stepping, a click on the map's legend, the URL)
    const el = ref.current;
    if (!el || !gene) return;
    const k = list.findIndex((r) => r.gene === gene);
    if (k < 0) return;
    const y = k * ROW_H;
    if (y < el.scrollTop || y + ROW_H > el.scrollTop + el.clientHeight) el.scrollTop = Math.max(0, y - el.clientHeight / 2);
  }, [gene, list]);
  const maxAbs = useMemo(() => list.reduce((m, r) => Math.max(m, Math.abs(r.effect ?? 0)), 0) || 1, [list]);
  const first = Math.max(0, Math.floor(top / ROW_H) - 8);
  const last = Math.min(list.length, Math.ceil((top + h) / ROW_H) + 8);
  return (
    <div className="c-scroll" ref={ref} onScroll={(e) => setTop((e.target as HTMLDivElement).scrollTop)}>
      <div style={{ height: list.length * ROW_H, position: "relative" }}>
        {list.slice(first, last).map((r, k) => {
          const i = first + k;
          const pct = Math.min(100, (100 * Math.abs(r.effect ?? 0)) / maxAbs);
          return (
            <div
              key={r.gene}
              className={`c-row${r.gene === gene ? " on" : ""}${r.measured ? "" : " off"}`}
              style={{ top: i * ROW_H, gridTemplateColumns: columns }}
              title={r.measured ? "colour the maps by this gene" : "no section measures this gene"}
              onClick={() => r.measured && store.getState().setColor({ kind: "gene", gene: r.gene })}
            >
              <span className="c-gene">
                {!hasEffect && <span className="c-rank">{r.i + 1}</span>}
                {r.gene}
              </span>
              {hasEffect && (
                <span className={`c-effect ${(r.effect ?? 0) >= 0 ? "up" : "down"}`}>
                  <i style={{ width: `${pct}%` }} />
                  {r.effect == null ? "—" : fmtEffect(r.effect)}
                </span>
              )}
              {hasP && <span className="c-p">{fmtP(r.padj ?? r.p)}</span>}
              {hasMean && <span className="c-mean">{fmtMean(r.mean)}</span>}
              {hasPct && (
                <span className="c-pct">
                  {fmtPct(r.pctIn)} / {fmtPct(r.pctOut)}
                </span>
              )}
            </div>
          );
        })}
      </div>
      {!list.length && <div className="muted small c-note">no gene matches</div>}
    </div>
  );
}

function geneStats(data: ComparisonData, geneRow: number): string[] {
  const r = data.results;
  return [
    r.effect ? `effect ${fmtEffect(r.effect[geneRow])}` : null,
    r.p ? `p ${fmtP(r.p[geneRow])}` : null,
    r.padj ? `padj ${fmtP(r.padj[geneRow])}` : null,
    r.mean ? `mean ${fmtMean(r.mean[geneRow])}` : null,
    r.pct_in || r.pct_out ? `in ${fmtPct(r.pct_in?.[geneRow] ?? null)}% · out ${fmtPct(r.pct_out?.[geneRow] ?? null)}%` : null,
    r.score ? `score ${fmtMean(r.score[geneRow])}` : null,
  ].filter(Boolean) as string[];
}

/** The right side when there are no replicate values: the table's numbers for the gene and the comparison's description. */
function GeneNote({ data, geneRow, gene, markers }: { data: ComparisonData; geneRow: number; gene: string; markers: boolean }) {
  const stats = geneStats(data, geneRow);
  const unmeasured = data.unmeasured.has(geneRow);
  return (
    <div className="c-plotwrap c-genenote">
      <div className="c-title">
        {gene}
        {markers ? <span className="muted"> · {data.level.name} vs rest</span> : null}
        {!stats.length ? <span className="muted"> · rank {geneRow + 1} of {data.results.genes.length}</span> : null}
        {unmeasured ? <span className="warn"> · not measured by any section</span> : null}
      </div>
      {stats.length > 0 && <div className="c-stats">{stats.join(" · ")}</div>}
      <div className="muted small">{markers ? `the gene is on every pane; Cells → gene by annotation shows it across the clusters, and "only ${data.level.name}" keeps the cluster alone` : "no replicate values in this comparison; add `pseudobulk:` for a dot per replicate"}</div>
      {data.info.description && <div className="muted c-desc">{data.info.description}</div>}
    </div>
  );
}

function ReplicatePlot({ data, geneRow, gene, box }: { data: ComparisonData; geneRow: number; gene: string; box: boolean }) {
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
  const stats = geneStats(data, geneRow);
  const [W, H] = size;
  const footer = 44;
  const pad = { l: 46, r: 12, t: 26, b: 28 };
  const ph = Math.max(60, H - footer - pad.t - pad.b);
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
  const unmeasured = data.unmeasured.has(geneRow);
  return (
    <div className="c-plotwrap" ref={ref}>
      <svg width={W} height={Math.max(100, H - footer)}>
        <text x={pad.l} y={14} className="c-title">
          {gene}
          {data.level.name !== "all" ? <tspan className="muted"> · {data.level.name}</tspan> : null}
          {data.info.units ? <tspan className="muted"> · {data.info.units}</tspan> : null}
          {unmeasured ? <tspan className="warn"> · not measured by any section</tspan> : null}
        </text>
        {ticks(lo, hi).map((t) => (
          <g key={t}>
            <line x1={pad.l} x2={pad.l + pw} y1={y(t)} y2={y(t)} className="c-grid" />
            <text x={pad.l - 6} y={y(t) + 3} className="c-tick">
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
            <text x={gx(k)} y={pad.t + ph + 16} className="c-group" style={{ fill: colors[k] }}>
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
      <div className="c-foot">
        <span className="c-stats">{stats.join(" · ")}</span>
        {data.info.description && <span className="muted c-desc">{data.info.description}</span>}
      </div>
    </div>
  );
}
