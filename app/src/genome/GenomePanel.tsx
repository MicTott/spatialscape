/** Genome panel under the maps: accessibility per category of the current annotation, the peaks and the gene
 *  models of the ATAC sample (manifest `sample.tracks`), drawn by GenomeView. The header holds the chromosome,
 *  one search box for genes or loci, the locus and the shared scale; the top edge drags to resize. */
import { useEffect, useRef, useState } from "react";
import type { FeatureList, TracksInfo } from "../data/manifest";
import { fieldById } from "../data/manifest";
import { GENOME_HEIGHT_KEY, store, useViewer } from "../store/store";
import { GeneSearch } from "../ui/GeneSearch";
import { GenomeView, type CoverageTrack, type HoverInfo } from "./GenomeView";
import { formatLocus, formatSpan, geneFromRow, padGene, padPeak, parseLocus, type Gene, type GeneRow, type Peak } from "./model";

const PEAK = /^(?:peak: )?((?:chr)?[0-9A-Za-z_.]+)[:-](\d+)-(\d+)$/; // chr1:100-200, 1:100-200 or chr1-100-200
const ALL: [number, number, number] = [154, 165, 177];
const hex = (h: string): [number, number, number] => [parseInt(h.slice(1, 3), 16), parseInt(h.slice(3, 5), 16), parseInt(h.slice(5, 7), 16)];

interface Assets {
  sizes: Map<string, number>;
  peaks: Map<string, Peak[]>;
  names: string[]; // every gene name, for the search box
  source: string | null; // where the gene models came from
  genes: (chrom: string) => Promise<Gene[]>;
  find: (name: string) => Promise<(Gene & { chrom: string }) | null>;
}

async function text(url: string): Promise<string> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status} for ${url}`);
  return r.text();
}

/** The sample's static track assets: chromosome sizes, peaks, the gene index (models load per chromosome). */
async function loadAssets(base: string, tracks: TracksInfo): Promise<Assets> {
  const sizes = new Map<string, number>();
  for (const line of (await text(base + (tracks.chromSizes ?? "tracks/chrom.sizes"))).split("\n")) {
    const [c, n] = line.split(/\s+/);
    if (c && +n > 0) sizes.set(c, +n);
  }
  if (!sizes.size) throw new Error("chrom.sizes lists no chromosomes");
  const peaks = new Map<string, Peak[]>();
  if (tracks.peaks) {
    for (const line of (await text(base + tracks.peaks)).split("\n")) {
      const [c, s, e, name] = line.split("\t");
      if (!c || !e) continue;
      let arr = peaks.get(c);
      if (!arr) peaks.set(c, (arr = []));
      arr.push({ start: +s, end: +e, name: name || `${c}:${+s + 1}-${e}` });
    }
    for (const arr of peaks.values()) arr.sort((a, b) => a.start - b.start);
  }
  const byChrom = new Map<string, Promise<Gene[]>>();
  const genes = (chrom: string) => {
    let p = byChrom.get(chrom);
    if (!p) {
      p = tracks.genes
        ? fetch(`${base}${tracks.genes}/${chrom}.json`)
            .then((r) => (r.ok ? (r.json() as Promise<GeneRow[]>) : []))
            .then((rows) => rows.map(geneFromRow))
        : Promise.resolve([]);
      byChrom.set(chrom, p);
    }
    return p;
  };
  const chromOf = new Map<string, string>();
  let source: string | null = null;
  if (tracks.genes) {
    const idx = JSON.parse(await text(`${base}${tracks.genes}/index.json`)) as { source?: string; chroms: Record<string, string[]> };
    source = idx.source ?? null;
    for (const [c, ns] of Object.entries(idx.chroms)) for (const n of ns) if (!chromOf.has(n)) chromOf.set(n, c);
  }
  const find = async (name: string) => {
    const c = chromOf.get(name) ?? chromOf.get(name.toUpperCase());
    if (!c) return null;
    const g = (await genes(c)).find((g) => g.name === name) ?? (await genes(c)).find((g) => g.name.toUpperCase() === name.toUpperCase());
    return g ? { ...g, chrom: c } : null;
  };
  return { sizes, peaks, names: [...chromOf.keys()], source, genes, find };
}

/** The feature to color by for a peak clicked in the panel, if the sample carries it. */
function peakFeature(features: FeatureList | null, name: string): string | null {
  if (!features) return null;
  const bare = name.replace(/^peak: /, "");
  for (const g of features.groups) for (const f of g.features) if (f.id === bare || f.id === `peak: ${bare}`) return f.id;
  return null;
}
/** The feature to color by for a gene clicked in the panel: its expression, else its activity score. */
function geneFeature(features: FeatureList | null, name: string): string | null {
  if (!features) return null;
  if (features.genes.includes(name)) return name;
  for (const g of features.groups) for (const f of g.features) if (f.id === `activity: ${name}`) return f.id;
  return null;
}

function tipText(h: HoverInfo, chrom: string | undefined, features: FeatureList | null): string {
  const pos = `${chrom ?? ""}:${Math.round(h.bp + 1).toLocaleString("en-US")}`;
  if (!h.hit) return pos;
  if (h.hit.kind === "track") return `${pos} · ${h.hit.track.name} ${h.hit.value.toPrecision(2)}`;
  if (h.hit.kind === "peak") return `${h.hit.peak.name.replace(/^peak: /, "")}${peakFeature(features, h.hit.peak.name) ? " · click to color by this peak" : ""}`;
  const g = h.hit.gene;
  return `${g.name}${g.strand > 0 ? " →" : g.strand < 0 ? " ←" : ""} · ${formatSpan(g.end - g.start)}${geneFeature(features, g.name) ? " · click to color by it" : ""}`;
}

const clampHeight = (h: number) => Math.max(160, Math.min(Math.max(160, window.innerHeight - 200), Math.round(h)));

export function GenomePanel() {
  const manifest = useViewer((s) => s.manifest);
  const datasetUrl = useViewer((s) => s.datasetUrl);
  const on = useViewer((s) => s.genome);
  const color = useViewer((s) => s.color);
  const hidden = useViewer((s) => s.hiddenCategories);
  const sidebarOpen = useViewer((s) => s.sidebarOpen);
  const locus = useViewer((s) => s.locus);
  const features = useViewer((s) => s.features);
  const sample = manifest?.samples.find((s) => s.tracks);
  const tracks = sample?.tracks ?? null;
  const base = tracks && datasetUrl && sample ? `${datasetUrl.replace(/\/$/, "")}/samples/${sample.id}/` : null;
  const bodyRef = useRef<HTMLDivElement>(null);
  const skipFollow = useRef(false);
  const lastField = useRef<string | null>(null); // the annotation whose categories the tracks follow
  const [assets, setAssets] = useState<Assets | null>(null);
  const [view, setView] = useState<GenomeView | null>(null);
  const [hover, setHover] = useState<HoverInfo | null>(null);
  const [yMax, setYMax] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [trackError, setTrackError] = useState<string | null>(null);
  const followDefault = useRef(true); // the dataset's default gene is a starting point, not something to return to
  const colorField = color?.kind === "field" ? color.field : null;
  const colorGene = color?.kind === "gene" ? color.gene : null;
  const defaultGene = manifest?.defaultGene ?? null;

  useEffect(() => {
    setAssets(null);
    setError(null);
    if (!tracks || !base) return;
    let cancelled = false;
    loadAssets(base, tracks).then(
      (a) => !cancelled && setAssets(a),
      (e) => !cancelled && setError(String(e)),
    );
    return () => {
      cancelled = true;
    };
  }, [tracks, base]);

  // the canvas lives while the panel is shown for this sample; it opens where the URL (or the last visit) left it
  useEffect(() => {
    if (!on || !assets || !tracks || !bodyRef.current) return;
    const v = new GenomeView(bodyRef.current, {
      sizes: assets.sizes,
      trackBin: tracks.bin,
      peaks: assets.peaks,
      fetchBins: (url, chrom, start, bin, n) => {
        const w = window.__sscape?.controller.cache.worker;
        return w ? w.bigwigBins(url, chrom, start, bin, n) : Promise.reject(new Error("no data worker"));
      },
      loadGenes: assets.genes,
      onLocus: (l) => {
        const cur = store.getState().locus;
        if (!cur || cur.chrom !== l.chrom || Math.abs(cur.start - l.start) > 0.5 || Math.abs(cur.end - l.end) > 0.5) store.getState().set({ locus: l });
      },
      onHover: setHover,
      onError: setTrackError,
      onScale: (m) => setYMax((prev) => (Math.abs(prev - m) > 0.005 * (m || 1) ? m : prev)),
      onClick: (hit) => {
        const st = store.getState();
        const id = hit?.kind === "peak" ? peakFeature(st.features, hit.peak.name) : hit?.kind === "gene" ? geneFeature(st.features, hit.gene.name) : null;
        if (id) st.setColor({ kind: "gene", gene: id });
      },
    });
    const l = store.getState().locus;
    followDefault.current = !l;
    if (l && assets.sizes.has(l.chrom)) {
      v.setLocus(l, false);
      skipFollow.current = true;
    }
    setView(v);
    if (window.__sscape) window.__sscape.genome = v;
    return () => {
      v.destroy();
      setView(null);
      if (window.__sscape?.genome === v) window.__sscape.genome = null;
    };
  }, [on, assets, tracks]);

  // one coverage track per visible category of the annotation last colored by (the first `by` field until then);
  // coloring by a gene keeps them, so a locus can be read per cell type; every cell only when no field has tracks
  useEffect(() => {
    if (!view || !manifest || !tracks || !base) return;
    const cf = colorField ? fieldById(manifest, colorField) : undefined;
    if (cf?.type === "categorical" && tracks.by.some((t) => t.field === cf.id)) lastField.current = cf.id;
    const fid = lastField.current ?? tracks.by[0]?.field ?? null;
    const f = fid ? fieldById(manifest, fid) : undefined;
    const set = f?.type === "categorical" ? tracks.by.find((t) => t.field === f.id) : undefined;
    const wanted: CoverageTrack[] = [];
    if (set && f?.type === "categorical") {
      const vocab = manifest.vocabularies[f.vocabulary];
      const hid = new Set(hidden[f.id] ?? []);
      vocab.categories.forEach((label, i) => {
        const p = set.categories[label];
        if (p && !hid.has(i)) wanted.push({ id: `${f.id}:${label}`, name: label, url: base + p, color: hex(vocab.colors[i]) });
      });
    } else wanted.push({ id: "all", name: "All cells", url: base + tracks.all, color: ALL });
    view.setTracks(wanted);
  }, [view, manifest, tracks, base, colorField, hidden]);

  // the locus follows what is colored by: a gene, a gene's activity score, or a peak; the band marks it.
  // The default gene is followed once, on a fresh open; switching from a gene to an annotation moves nothing.
  useEffect(() => {
    if (!view || !assets) return;
    const move = !skipFollow.current;
    skipFollow.current = false;
    const target = colorGene ?? (followDefault.current ? defaultGene : null);
    followDefault.current = false;
    if (!target) return;
    let cancelled = false;
    void (async () => {
      const m = PEAK.exec(target);
      if (m) {
        const chrom = assets.sizes.has(m[1]) ? m[1] : assets.sizes.has(`chr${m[1]}`) ? `chr${m[1]}` : null;
        const len = chrom ? assets.sizes.get(chrom) : undefined;
        if (!chrom || len == null || cancelled) return;
        view.setHighlight({ chrom, start: +m[2], end: +m[3] });
        if (move) view.setLocus({ chrom, ...padPeak(+m[2], +m[3], len) });
        return;
      }
      const g = await assets.find(target.replace(/^activity: /, ""));
      if (cancelled) return;
      view.setHighlight(g ? { chrom: g.chrom, start: g.start, end: g.end } : null);
      if (g && move) view.setLocus({ chrom: g.chrom, ...padGene(g.start, g.end, assets.sizes.get(g.chrom)!) });
    })();
    return () => {
      cancelled = true;
    };
  }, [view, assets, colorGene, defaultGene]);

  const goToGene = async (name: string) => {
    if (!view || !assets) return;
    const g = await assets.find(name);
    if (!g) return;
    view.setHighlight({ chrom: g.chrom, start: g.start, end: g.end });
    view.setLocus({ chrom: g.chrom, ...padGene(g.start, g.end, assets.sizes.get(g.chrom)!) });
  };
  const submitLocus = (t: string) => {
    if (!view || !assets) return false;
    const l = parseLocus(t, assets.sizes);
    if (!l) return false;
    view.setLocus(l);
    return true;
  };
  const onHandleDown = (e: React.PointerEvent) => {
    const y0 = e.clientY;
    const h0 = store.getState().genomeHeight;
    const move = (ev: PointerEvent) => store.getState().set({ genomeHeight: clampHeight(h0 + (y0 - ev.clientY)) });
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      try {
        localStorage.setItem(GENOME_HEIGHT_KEY, String(store.getState().genomeHeight));
      } catch {
        /* private mode */
      }
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    e.preventDefault();
  };

  if (!on || !tracks) return null;
  return (
    <div className={`genome${sidebarOpen ? " with-sidebar" : ""}`}>
      <div className="g-handle" onPointerDown={onHandleDown} title="drag to resize" />
      <div className="g-head">
        <select value={locus?.chrom ?? ""} disabled={!assets} onChange={(e) => view?.setLocus({ chrom: e.target.value, start: 0, end: assets?.sizes.get(e.target.value) ?? 0 }, false)}>
          {[...(assets?.sizes.keys() ?? [])].map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <GeneSearch genes={assets?.names ?? []} value={null} placeholder="gene or chr:start-end" onPick={(g) => void goToGene(g)} onSubmit={submitLocus} />
        {locus && (
          <span className="locus">
            {formatLocus(locus)} <span className="muted">· {formatSpan(locus.end - locus.start)}</span>
          </span>
        )}
        <span className="right">
          {yMax > 0 && <span title="insertions per million, one scale for every track">0 – {yMax.toPrecision(2)} / M</span>}
          {assets?.source && <span className="muted"> · genes: {assets.source}</span>}
          {(error || trackError) && <span className="warn"> {error ?? trackError}</span>}
        </span>
      </div>
      <div className="g-body" ref={bodyRef}>
        {hover && (
          <>
            <div className="g-guide" style={{ left: hover.x }} />
            <div className="g-tip" style={{ left: hover.x, top: Math.max(2, hover.y - 26) }}>
              {tipText(hover, locus?.chrom, features)}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
