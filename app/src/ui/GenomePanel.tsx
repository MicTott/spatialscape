/** Genome panel: igv.js under the maps, showing pseudobulk accessibility per category of the current annotation,
 *  the peaks, gene spans and links that `spatialscape build` wrote for an ATAC sample (manifest `sample.tracks`). */
import { useEffect, useRef, useState } from "react";
import { fieldById } from "../data/manifest";
import { store, useViewer } from "../store/store";

const PEAK = /^(?:peak: )?(chr\w+):(\d+)-(\d+)$/;
const HOSTED_GENOMES = new Set(["hg38", "hg19", "hg18", "mm10", "mm39", "rn6", "rn7", "danRer11", "dm6", "ce11", "sacCer3"]); // igv.js brings sequence and gene models for these
type Span = { chr: string; start: number; end: number };

/** igv.js renders into a shadow root with its own light stylesheet; this moves it onto the dark panel. */
const DARK = `
  .igv-container, .igv-column-container, .igv-navbar, .igv-viewport, .igv-axis-column, .igv-sample-name-column, .igv-scrollbar-column, .igv-track-drag-column, .igv-gear-menu-column { background: #11151b !important; color: #e6edf3 !important; }
  .igv-navbar { border-bottom: 1px solid #2a3140 !important; }
  .igv-logo { display: none !important; }
  .igv-current-genome, .igv-windowsize-panel-container, .igv-navbar-genomic-location { color: #9aa5b1 !important; }
  .igv-search-input, .igv-chromosome-select-widget-container select { background: #1a2029 !important; color: #e6edf3 !important; border: 1px solid #2a3140 !important; }
  .igv-navbar-icon-button, .igv-navbar-toggle-button-container { background: #1a2029 !important; border-color: #2a3140 !important; }
  .igv-track-label { background: rgba(26, 32, 41, 0.9) !important; color: #e6edf3 !important; border: 1px solid #2a3140 !important; font-size: 11px !important; }
  .igv-viewport, .igv-column { border-color: #2a3140 !important; }
  .igv-center-line, .igv-cursor-guide-vertical, .igv-cursor-guide-horizontal { border-color: #40c4ff !important; }
  .igv-zoom-in-notice-container { color: #9aa5b1 !important; }
  .igv-gear-menu-column > div, .igv-scrollbar-column > div, .igv-track-drag-column > div { background: transparent !important; }
  /* igv paints axis boxes and annotation tracks on white canvases; inverting them keeps the drawing and darkens the paper */
  .igv-axis-column canvas, .sscape-invert canvas { filter: invert(0.9) hue-rotate(180deg); }
`;

const LIGHT_TRACK = /^(peaks|genes|links)$|refseq|gene/i;

/** Annotation tracks (peaks, gene models, links) draw on white; tag their viewports so the dark filter applies.
 *  Found through the DOM, since each track's label sits inside its viewport. */
function tagLightViewports(shadow: ShadowRoot | null) {
  if (!shadow) return;
  for (const label of shadow.querySelectorAll(".igv-track-label")) {
    if (LIGHT_TRACK.test(label.textContent ?? "")) label.closest(".igv-viewport")?.classList.add("sscape-invert");
  }
}

export function GenomePanel() {
  const manifest = useViewer((s) => s.manifest);
  const datasetUrl = useViewer((s) => s.datasetUrl);
  const on = useViewer((s) => s.genome);
  const color = useViewer((s) => s.color);
  const hidden = useViewer((s) => s.hiddenCategories);
  const sidebarOpen = useViewer((s) => s.sidebarOpen);
  const ref = useRef<HTMLDivElement>(null);
  const igvRef = useRef<any>(null);
  const browserRef = useRef<any>(null);
  const genesRef = useRef<Map<string, Span>>(new Map());
  const loadedRef = useRef<Set<string>>(new Set());
  const [ready, setReady] = useState(0);
  const sample = manifest?.samples.find((s) => s.tracks);
  const tracks = sample?.tracks;
  const base = tracks && datasetUrl && sample ? `${datasetUrl.replace(/\/$/, "")}/samples/${sample.id}/` : null;
  const colorField = color?.kind === "field" ? color.field : null;
  const colorGene = color?.kind === "gene" ? color.gene : null;

  // the browser lives as long as the panel is shown for this dataset
  useEffect(() => {
    if (!on || !tracks || !base || !ref.current) return;
    let cancelled = false;
    const el = ref.current;
    (async () => {
      const igv = (await import("igv")).default;
      if (cancelled) return;
      igvRef.current = igv;
      const b = await igv.createBrowser(el, { genome: tracks.genome, showNavigation: true, showRuler: true, showIdeogram: false, showCenterGuide: false, tracks: [] });
      if (cancelled) {
        igv.removeBrowser(b);
        return;
      }
      browserRef.current = b;
      const shadow = el.shadowRoot;
      if (shadow) {
        const style = document.createElement("style");
        style.textContent = DARK;
        shadow.appendChild(style);
      }
      if (tracks.genes) {
        // hosted genomes already come with full gene models (exons, strand); our spans only serve the locus lookup then
        if (!HOSTED_GENOMES.has(tracks.genome)) await b.loadTrack({ type: "annotation", format: "bed", url: base + tracks.genes, name: "Genes", displayMode: "COLLAPSED", color: "#4d6a8a", height: 32, order: 1000 });
        void fetch(base + tracks.genes)
          .then((r) => r.text())
          .then((text) => {
            const m = new Map<string, Span>();
            for (const line of text.split("\n")) {
              const [chr, s, e, name] = line.split("\t");
              if (name && !m.has(name)) m.set(name, { chr, start: +s, end: +e });
            }
            genesRef.current = m;
            setReady((n) => n + 1); // re-run the locus effect now that genes are known
          });
      }
      if (tracks.peaks) await b.loadTrack({ type: "annotation", format: "bed", url: base + tracks.peaks, name: "Peaks", displayMode: "COLLAPSED", color: "#b45309", height: 22, order: 999 });
      if (tracks.links) await b.loadTrack({ type: "interact", format: "bedpe", url: base + tracks.links, name: "Links", height: 60, order: 1001 });
      tagLightViewports(shadow);
      setTimeout(() => tagLightViewports(el.shadowRoot), 500); // igv's own gene track appears after the genome loads
      // a click on a peak colors everything by that peak's accessibility
      b.on("trackclick", (track: any, data: any) => {
        if (track?.name !== "Peaks" || !Array.isArray(data)) return undefined;
        const hit = data.map((d: any) => String(d?.value ?? "")).find((v: string) => PEAK.test(v));
        if (!hit) return undefined;
        const feats = store.getState().features;
        const id = feats?.groups.flatMap((g) => g.features).find((f) => f.id === hit || f.id === `peak: ${hit}`)?.id;
        if (id) store.getState().setColor({ kind: "gene", gene: id });
        return false;
      });
      setReady((n) => n + 1);
    })();
    return () => {
      cancelled = true;
      if (browserRef.current && igvRef.current) igvRef.current.removeBrowser(browserRef.current);
      browserRef.current = null;
      loadedRef.current.clear();
      genesRef.current = new Map();
    };
  }, [on, tracks, base]);

  // one coverage track per visible category of the current annotation (or every cell when coloring by a feature)
  useEffect(() => {
    const b = browserRef.current;
    if (!b || !manifest || !tracks || !base) return;
    const f = colorField ? fieldById(manifest, colorField) : undefined;
    const set = f?.type === "categorical" ? tracks.by.find((t) => t.field === f.id) : undefined;
    const wanted: { name: string; url: string; color: string; order: number }[] = [];
    if (set && f?.type === "categorical") {
      const vocab = manifest.vocabularies[f.vocabulary];
      const hid = new Set(hidden[f.id] ?? []);
      vocab.categories.forEach((label, i) => {
        const p = set.categories[label];
        if (p && !hid.has(i)) wanted.push({ name: label, url: base + p, color: vocab.colors[i], order: i });
      });
    } else wanted.push({ name: "All cells", url: base + tracks.all, color: "#9aa5b1", order: 0 });
    const names = new Set(wanted.map((w) => w.name));
    for (const name of [...loadedRef.current]) {
      if (!names.has(name)) {
        b.removeTrackByName(name);
        loadedRef.current.delete(name);
      }
    }
    void (async () => {
      for (const w of wanted) {
        if (loadedRef.current.has(w.name)) continue;
        loadedRef.current.add(w.name);
        await b.loadTrack({ type: "wig", format: "bigWig", url: w.url, name: w.name, color: w.color, autoscaleGroup: "accessibility", height: 36, order: w.order });
      }
      tagLightViewports(ref.current?.shadowRoot ?? null);
    })();
  }, [ready, manifest, tracks, base, colorField, hidden]);

  // the locus follows the current feature: a peak, a gene, or a gene's activity score (the dataset's default gene until one is chosen)
  const target = colorGene ?? manifest?.defaultGene ?? null;
  useEffect(() => {
    const b = browserRef.current;
    if (!b || !target) return;
    const colorGene = target;
    const m = PEAK.exec(colorGene);
    if (m) {
      b.search(`${m[1]}:${Math.max(1, +m[2] - 10_000)}-${+m[3] + 10_000}`);
      return;
    }
    const span = genesRef.current.get(colorGene.replace(/^activity: /, ""));
    if (span) b.search(`${span.chr}:${Math.max(1, span.start - 50_000)}-${span.end + 50_000}`);
  }, [ready, target]);

  if (!on || !tracks) return null;
  return <div className={`genome${sidebarOpen ? " with-sidebar" : ""}`} ref={ref} />;
}
