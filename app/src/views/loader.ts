/** Dataset loading: manifest, per-sample open, and the arrays the current color / filter / group need. */
import { assertManifest, fieldById, type Manifest } from "../data/manifest";
import { store, type ColorSpec, type FilterSpec, type ViewerState } from "../store/store";
import type { ViewerController } from "./ViewerController";
import { VIEWS } from "./types";

export class Loader {
  private geneSwitchStart = 0;

  constructor(private c: ViewerController) {}

  markGeneSwitch() {
    this.geneSwitchStart = performance.now();
  }

  async load(url: string) {
    const c = this.c;
    const s = store.getState();
    s.set({ status: "loading", error: null, datasetUrl: url, manifest: null, features: null, sampleStatus: {} });
    let manifest: Manifest;
    try {
      const r = await fetch(`${url.replace(/\/$/, "")}/manifest.json`);
      if (!r.ok) throw new Error(`HTTP ${r.status} fetching manifest.json`);
      manifest = await r.json();
      assertManifest(manifest);
    } catch (e) {
      s.set({ status: "error", error: `Could not load dataset at ${url}: ${(e as Error).message}. If the data is on another host, it must send CORS headers and support HTTP Range requests.` });
      return;
    }
    c.manifest = manifest;
    c.samplesById = new Map(manifest.samples.map((x) => [x.id, x]));
    void fetch(`${url.replace(/\/$/, "")}/features.json`)
      .then((r) => (r.ok ? r.json() : fetch(`${url.replace(/\/$/, "")}/genes.json`).then((g) => g.json()).then((genes) => ({ genes, groups: [] }))))
      .then((features) => store.getState().set({ features }))
      .catch(() => store.getState().set({ features: { genes: [], groups: [] } }));
    const cur = store.getState();
    const color: ColorSpec =
      cur.color ??
      (manifest.defaultColor.kind === "gene" && manifest.defaultColor.gene
        ? { kind: "gene", gene: manifest.defaultColor.gene }
        : manifest.defaultColor.field
          ? { kind: "field", field: manifest.defaultColor.field }
          : { kind: "gene", gene: manifest.defaultGene ?? "" });
    const sampleStatus: ViewerState["sampleStatus"] = {};
    for (const smp of manifest.samples) sampleStatus[smp.id] = "pending";
    cur.set({ manifest, color, sampleStatus });
    c.applyViews();
    for (const v of VIEWS) if (c.rects[v]) c.relayout(v, false);
    if (cur.viewState) c.setViewState("spatial", cur.viewState);
    if (cur.focus && c.layouts[c.viewOf(cur.focus)]?.placements.has(cur.focus)) c.focusSample(cur.focus, false);

    const order = [...manifest.layout.order];
    for (const smp of manifest.samples) if (!order.includes(smp.id)) order.push(smp.id);
    if (cur.focus) order.sort((a) => (a === cur.focus ? -1 : 0));
    await Promise.all(
      order.map(async (id) => {
        const smp = c.samplesById.get(id)!;
        store.getState().set({ sampleStatus: { ...store.getState().sampleStatus, [id]: "loading" } });
        try {
          await c.cache.openSample(url, id, smp.nObs);
          store.getState().set({ sampleStatus: { ...store.getState().sampleStatus, [id]: "ready" } });
          void this.loadChannels(id);
        } catch (e) {
          console.error(e);
          store.getState().set({ sampleStatus: { ...store.getState().sampleStatus, [id]: "error" } });
        }
        c.requestLayers();
      }),
    );
    store.getState().set({ status: "ready" });
    c.requestLayers();
  }

  /** Make sure the arrays needed by the current color / filter / group field are present for one sample (or all). */
  async loadChannels(sampleId?: string) {
    const c = this.c;
    const s = store.getState();
    const ids = sampleId ? [sampleId] : [...c.cache.samples.keys()];
    const gen = c.generation;
    const jobs: Promise<unknown>[] = [];
    const need = (p: Promise<unknown>) => {
      s.set({ pending: store.getState().pending + 1 });
      jobs.push(
        p
          .catch((e) => console.error(e))
          .finally(() => {
            store.getState().set({ pending: Math.max(0, store.getState().pending - 1) });
            if (gen === c.generation) c.requestLayers();
          }),
      );
    };
    for (const id of ids) {
      const sd = c.cache.samples.get(id);
      if (!sd) continue;
      const smp = c.samplesById.get(id);
      const wanted: (ColorSpec | FilterSpec | null)[] = [s.color, s.filter];
      if (s.groupField && s.color && s.color.kind !== "field") wanted.push({ kind: "field", field: s.groupField });
      for (const spec of wanted) {
        if (!spec) continue;
        if (spec.kind === "blend") {
          for (const g of [...spec.a, ...spec.b]) if (!c.cache.getGeneSync(id, g) && sd.geneIndex.has(g)) need(c.cache.getGene(id, g));
          continue;
        }
        if (spec.kind === "category") {
          if (smp?.fields.includes(spec.field) && !sd.catAttr.has(spec.field)) need(c.cache.getCategorical(id, spec.field));
          continue;
        }
        if (spec.kind === "gene") {
          if (!c.cache.getGeneSync(id, spec.gene) && sd.geneIndex.has(spec.gene)) need(c.cache.getGene(id, spec.gene));
        } else {
          const f = c.manifest && fieldById(c.manifest, spec.field);
          if (!f || !smp?.fields.includes(spec.field)) continue;
          if (f.type === "categorical") {
            if (!sd.catAttr.has(spec.field)) need(c.cache.getCategorical(id, spec.field).then(() => c.stats.updateCategoryCounts(spec.field)));
          } else if (!sd.num.has(spec.field)) need(c.cache.getContinuousU8(id, spec.field, f.range));
        }
      }
    }
    await Promise.all(jobs);
    if (gen === c.generation) this.afterChannelsLoaded();
  }

  private afterChannelsLoaded() {
    const c = this.c;
    const s = store.getState();
    const genes = s.color?.kind === "gene" ? [s.color.gene] : s.color?.kind === "blend" ? [...s.color.a, ...s.color.b] : [];
    if (genes.length) {
      const ids = [...c.cache.samples.keys()];
      Promise.all(genes.flatMap((g) => ids.map((id) => c.cache.gmax(id, g).then((v) => [id, g, v] as const)))).then((rows) => {
        for (const [id, g, v] of rows) c.geneGmax.set(`${id}:${g}`, v);
        if (s.color?.kind === "gene") store.getState().set({ geneMax: Math.max(0, ...rows.map((r) => r[2])) });
        c.blend.invalidate();
        c.stats.updateGroupStats();
        c.selection.updateSummary();
        c.requestLayers();
      });
      if (this.geneSwitchStart) {
        store.getState().set({ timings: { ...store.getState().timings, lastGeneMs: performance.now() - this.geneSwitchStart } });
        this.geneSwitchStart = 0;
      }
    }
    if (s.filter) c.stats.updateFilterHistogram();
    c.stats.updateGroupStats();
    c.selection.updateSummary();
    c.requestLayers();
  }
}
