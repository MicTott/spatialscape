/** Regions: annotation drawn in the viewer. Each group is a set of lassos kept in the coordinates of the section
 *  they were drawn on, so they survive layout changes; membership is recomputed into a live categorical field
 *  ("regions", one category per group plus "unassigned") that the legend, hover rows, dot plot, filters and a
 *  Python session all read like any other annotation. Where lassos overlap, the last one drawn wins. */
import { PathLayer, SolidPolygonLayer, TextLayer } from "@deck.gl/layers";
import { Matrix4 } from "@math.gl/core";
import type { Manifest } from "../data/manifest";
import { postRegions } from "../data/sessionApi";
import { hexToRGB } from "../layers/lut";
import { store, type RegionGroup, type RegionPolygon, type Regions, type ViewerState, type ViewId } from "../store/store";
import { pointInPolygon } from "./geometry";
import type { LayoutResult } from "./layout";
import { overlayProps } from "./types";
import type { ViewerController } from "./ViewerController";

export const UNASSIGNED_COLOR = "#4b5563";

export class RegionsManager {
  /** The manifest as loaded; the one in the store gains the "regions" field while groups exist. */
  private base: Manifest | null = null;
  private version = 0;

  constructor(private c: ViewerController) {}

  /** The field id: "regions" unless the dataset already has one of that name. */
  get field(): string {
    return this.base?.fields.some((f) => f.id === "regions") ? "regions_drawn" : "regions";
  }

  /** A new dataset: forget the previous drawing. */
  reset(manifest: Manifest) {
    this.base = manifest;
    if (store.getState().regions.groups.length) store.getState().set({ regions: { groups: [], active: null, seq: 0 } });
  }

  /** A lasso drawn while a group is active: it belongs to the section most of its points fall on, in that
   *  section's own coordinates. Returns false when it touched no section. */
  addFromLasso(view: ViewId, world: [number, number][]): boolean {
    const s = store.getState();
    const L = this.c.layouts[view];
    if (!s.regions.active || !L) return false;
    const votes = new Map<string, number>();
    for (const [x, y] of world) {
      const id = this.c.interaction.sampleAt(view, x, y);
      if (id) votes.set(id, (votes.get(id) ?? 0) + 1);
    }
    let best: string | null = null;
    let n = 0;
    for (const [id, k] of votes) if (k > n) [best, n] = [id, k];
    if (!best) return false;
    const inv = new Matrix4(L.placements.get(best)!.modelMatrix).invert();
    const local = world.map((pt) => inv.transformAsPoint([pt[0], pt[1], 0]).slice(0, 2) as [number, number]);
    s.addRegionPolygon(s.regions.active, { sample: best, view, local });
    return true;
  }

  /** Store changed: refresh the field, the codes, the layers, and the session. */
  onChange(prev: Regions) {
    const cur = store.getState().regions;
    if (cur.groups !== prev.groups || cur.active !== prev.active) {
      this.syncManifest();
      if (cur.groups !== prev.groups) {
        this.recompute();
        void this.post();
      }
      this.c.requestLayers();
    }
  }

  private syncManifest() {
    const base = this.base;
    if (!base) return;
    const { groups } = store.getState().regions;
    const field = this.field;
    let m: Manifest = base;
    if (groups.length) {
      const vocab = { categories: [...groups.map((g) => g.name), "unassigned"], colors: [...groups.map((g) => g.color), UNASSIGNED_COLOR] };
      m = {
        ...base,
        fields: [...base.fields, { id: field, name: "Regions", type: "categorical", vocabulary: field, description: "drawn in the viewer" }],
        vocabularies: { ...base.vocabularies, [field]: vocab },
        samples: base.samples.map((x) => ({ ...x, fields: [...x.fields, field] })),
      };
    }
    this.c.manifest = m;
    this.c.samplesById = new Map(m.samples.map((x) => [x.id, x]));
    this.c.layersBuilder.clearField(field);
    const s = store.getState();
    const upd: Partial<ViewerState> = { manifest: m };
    if (!groups.length && s.color?.kind === "field" && s.color.field === field) {
      upd.color = base.defaultColor?.kind === "field" && base.defaultColor.field ? { kind: "field", field: base.defaultColor.field } : base.defaultGene ? { kind: "gene", gene: base.defaultGene } : null;
    }
    s.set(upd);
  }

  /** Codes for every loaded sample: group index per cell, `groups.length` for cells in no region. */
  recompute(onlySample?: string) {
    const c = this.c;
    const { groups } = store.getState().regions;
    const field = this.field;
    const byGroup = new Map(groups.map((g, i) => [g.id, i]));
    const polys: (RegionPolygon & { gi: number })[] = groups.flatMap((g) => g.polygons.map((p) => ({ ...p, gi: byGroup.get(g.id)! }))).sort((a, b) => a.seq - b.seq);
    for (const sd of c.cache.samples.values()) {
      if (onlySample && sd.id !== onlySample) continue;
      if (!groups.length) {
        sd.cat.delete(field);
        sd.catAttr.delete(field);
        continue;
      }
      const codes = new Uint16Array(sd.nObs).fill(groups.length);
      for (const p of polys) {
        if (p.sample !== sd.id || !sd.index) continue;
        const xs = p.local.map((q) => q[0]);
        const ys = p.local.map((q) => q[1]);
        for (const i of sd.index.range(Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys))) {
          if (pointInPolygon(sd.xy[i * 2], sd.xy[i * 2 + 1], p.local)) codes[i] = p.gi;
        }
      }
      sd.cat.set(field, codes);
      sd.catAttr.set(field, { value: codes, size: 1 });
    }
    c.layersBuilder.clearField(field);
    if (groups.length) c.stats.updateCategoryCounts(field);
    if (c.selection.current) c.selection.updateSummary();
    c.requestLayers();
  }

  /** The drawn polygons over their sections, filled and outlined in the group's colour; the active group brighter. */
  layers(s: ViewerState, view: ViewId, L: LayoutResult) {
    const { groups, active } = s.regions;
    if (!groups.length) return [];
    const common = overlayProps(view);
    const out: unknown[] = [];
    type Row = { polygon: [number, number][]; color: [number, number, number]; active: boolean; name: string; centroid: [number, number] };
    for (const [id, p] of L.placements) {
      const rows: Row[] = [];
      for (const g of groups) {
        const rgb = hexToRGB(g.color);
        for (const poly of g.polygons) {
          if (poly.sample !== id || poly.view !== view) continue;
          const cx = poly.local.reduce((a, q) => a + q[0], 0) / poly.local.length;
          const cy = poly.local.reduce((a, q) => a + q[1], 0) / poly.local.length;
          rows.push({ polygon: poly.local, color: [rgb[0], rgb[1], rgb[2]], active: g.id === active, name: g.name, centroid: [cx, cy] });
        }
      }
      if (!rows.length) continue;
      out.push(
        new SolidPolygonLayer({
          ...common,
          id: `region-fill-${view}-${id}`,
          data: rows,
          modelMatrix: p.modelMatrix,
          getPolygon: (d: Row) => d.polygon,
          getFillColor: (d: Row) => [...d.color, d.active ? 95 : 60] as [number, number, number, number],
          updateTriggers: { getFillColor: active },
        } as any),
        new PathLayer({
          ...common,
          id: `region-line-${view}-${id}`,
          data: rows,
          modelMatrix: p.modelMatrix,
          getPath: (d: Row) => [...d.polygon, d.polygon[0]],
          getColor: (d: Row) => [...d.color, d.active ? 255 : 200] as [number, number, number, number],
          getWidth: (d: Row) => (d.active ? 2.5 : 1.5),
          widthUnits: "pixels",
          updateTriggers: { getColor: active, getWidth: active },
        } as any),
        new TextLayer({
          ...common,
          id: `region-label-${view}-${id}`,
          data: rows,
          modelMatrix: p.modelMatrix,
          getPosition: (d: Row) => d.centroid,
          getText: (d: Row) => d.name,
          getColor: [240, 244, 248, 235],
          getSize: 11,
          sizeUnits: "pixels",
          getTextAnchor: "middle",
          getAlignmentBaseline: "center",
          fontFamily: "Inter, system-ui, sans-serif",
          fontWeight: 600,
          characterSet: "auto",
          background: true,
          getBackgroundColor: (d: Row) => [...d.color, 180] as [number, number, number, number],
          backgroundPadding: [4, 2, 4, 2],
          updateTriggers: { getBackgroundColor: groups.map((g) => g.color).join() },
        } as any),
      );
    }
    return out;
  }

  /** sample,cell_id,region for every cell inside a region. */
  async exportCSV() {
    const c = this.c;
    const { groups } = store.getState().regions;
    const field = this.field;
    const lines = ["sample,cell_id,region"];
    for (const sd of c.cache.samples.values()) {
      const codes = sd.cat.get(field);
      const smp = c.samplesById.get(sd.id);
      if (!codes || !smp) continue;
      for (let i = 0; i < codes.length; i++) {
        if (codes[i] >= groups.length) continue;
        const name = groups[codes[i]].name.replace(/"/g, '""');
        lines.push(`${sd.id},${(await c.cache.getId(sd.id, i, smp.idBlock)) ?? i},"${name}"`);
      }
    }
    download(`${c.manifest?.id ?? "dataset"}-regions.csv`, lines.join("\n"), "text/csv");
  }

  /** The drawing itself (groups and polygons), to load again later. */
  exportJSON() {
    const { groups } = store.getState().regions;
    const doc = { spatialscape_regions: 1, dataset: this.c.manifest?.id ?? null, groups: groups.map((g) => ({ name: g.name, color: g.color, polygons: g.polygons.map((p) => ({ sample: p.sample, view: p.view, local: p.local })) })) };
    download(`${this.c.manifest?.id ?? "dataset"}-regions.json`, JSON.stringify(doc), "application/json");
  }

  importJSON(text: string): string | null {
    let doc: any;
    try {
      doc = JSON.parse(text);
    } catch {
      return "not a JSON file";
    }
    if (!doc || !Array.isArray(doc.groups)) return "not a regions file (expected { groups: [...] })";
    let seq = 0;
    const groups: RegionGroup[] = doc.groups.map((g: any, i: number) => ({
      id: `r${Date.now().toString(36)}${i}`,
      name: String(g.name ?? `Region ${i + 1}`),
      color: typeof g.color === "string" ? g.color : "#4e79a7",
      polygons: (g.polygons ?? []).map((p: any) => ({ id: `p${++seq}`, seq, sample: String(p.sample), view: p.view === "embedding" ? "embedding" : "spatial", local: p.local })),
    }));
    store.getState().setRegions(groups);
    return null;
  }

  private async post() {
    const c = this.c;
    const { groups } = store.getState().regions;
    const field = this.field;
    const codes = new Map<string, Uint16Array>();
    for (const sd of c.cache.samples.values()) {
      const u = sd.cat.get(field);
      if (u) codes.set(sd.id, u);
    }
    await postRegions(store.getState().datasetUrl, ++this.version, groups.map((g) => ({ name: g.name, color: g.color })), codes);
  }
}

function download(name: string, text: string, type: string) {
  const blob = new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}
