/** Pointer and keyboard handling: hover (KDBush lookup + tooltip rows), click/double-click, lasso gestures, shortcuts. */
import { Matrix4 } from "@math.gl/core";
import type { SampleData } from "../data/cache";
import { store, type ViewId, type ViewerState } from "../store/store";
import { fmtValue, VIEWS } from "./types";
import type { ViewerController } from "./ViewerController";

export class Interaction {
  private abort = new AbortController();

  constructor(private c: ViewerController) {
    const { signal } = this.abort;
    const el = c.container;
    el.addEventListener("pointerdown", this.onPointerDown, { signal });
    el.addEventListener("pointerup", this.onPointerUp, { signal });
    el.addEventListener("pointermove", this.onPointerMove, { signal });
    el.addEventListener("pointerleave", () => store.getState().set({ hover: null }), { signal });
    el.addEventListener("click", this.onClick, { signal });
    el.addEventListener("dblclick", this.onDblClick, { signal });
    window.addEventListener("keydown", this.onKey, { signal });
  }

  destroy() {
    this.abort.abort();
  }

  /** Which view a container-relative pixel falls in. */
  viewAtPixel(x: number): ViewId | null {
    for (const v of VIEWS) {
      const r = this.c.rects[v];
      if (r && x >= r.x && x < r.x + r.w) return v;
    }
    return null;
  }

  worldFromEvent(e: MouseEvent): { view: ViewId; world: [number, number]; px: [number, number] } | null {
    const c = this.c;
    if (c.destroyed || !(c.deck as any).viewManager) return null;
    const rect = c.container.getBoundingClientRect();
    const px: [number, number] = [e.clientX - rect.left, e.clientY - rect.top];
    const view = this.viewAtPixel(px[0]);
    if (!view) return null;
    const vp = c.deck.getViewports().find((v) => v.id === view);
    if (!vp) return null;
    const [x, y] = vp.unproject([px[0] - vp.x, px[1] - vp.y]);
    return { view, world: [x, y], px };
  }

  sampleAt(view: ViewId, wx: number, wy: number, pad = 0): string | null {
    const L = this.c.layouts[view];
    if (!L) return null;
    for (const [id, p] of L.placements) {
      const b = p.worldBbox;
      if (wx >= b[0] - pad && wx <= b[2] + pad && wy >= b[1] - pad && wy <= b[3] + pad) return id;
    }
    return null;
  }

  private onPointerDown = (e: PointerEvent) => {
    if (store.getState().tool !== "lasso" || e.button !== 0) return;
    const hit = this.worldFromEvent(e);
    if (!hit) return;
    this.c.selection.begin(hit.view, hit.world);
    this.c.container.setPointerCapture?.(e.pointerId);
    e.preventDefault();
  };

  private onPointerUp = (e: PointerEvent) => {
    if (!this.c.selection.lassoActive) return;
    this.c.selection.finish();
    e.preventDefault();
  };

  private onPointerMove = (e: PointerEvent) => {
    const c = this.c;
    const hit = this.worldFromEvent(e);
    const s = store.getState();
    if (hit && c.selection.lassoActive) {
      c.selection.extend(hit.view, hit.world);
      return;
    }
    if (!hit) {
      if (s.hover) s.set({ hover: null });
      return;
    }
    if (s.activeView !== hit.view) s.set({ activeView: hit.view });
    const scale = Math.pow(2, c.viewStates[hit.view].zoom);
    const id = this.sampleAt(hit.view, hit.world[0], hit.world[1], 8 / scale);
    const sd = id ? c.cache.samples.get(id) : undefined;
    const smp = id ? c.samplesById.get(id) : undefined;
    if (!id || !sd || !smp || !sd.index) {
      if (s.hover) s.set({ hover: null });
      return;
    }
    const p = c.layouts[hit.view]!.placements.get(id)!;
    const inv = new Matrix4(p.modelMatrix).invert();
    const [lx, ly] = inv.transformAsPoint([hit.world[0], hit.world[1], 0]);
    const r = Math.max(smp.pointRadius * s.pointScale[hit.view], 6 / scale);
    const hits = sd.index.within(lx, ly, r);
    if (!hits.length) {
      if (s.hover) s.set({ hover: null });
      return;
    }
    let best = hits[0];
    let bd = Infinity;
    for (const h of hits) {
      const dx = sd.xy[h * 2] - lx;
      const dy = sd.xy[h * 2 + 1] - ly;
      const d = dx * dx + dy * dy;
      if (d < bd) {
        bd = d;
        best = h;
      }
    }
    s.set({ hover: { sampleId: id, index: best, x: hit.px[0], y: hit.px[1], ...this.describe(sd, best, s) } });
    void c.cache.getId(id, best, smp.idBlock).then((cid) => {
      const cur = store.getState().hover;
      if (cur && cur.sampleId === id && cur.index === best && cur.id !== cid) store.getState().set({ hover: { ...cur, id: cid } });
    });
  };

  /** Everything worth showing for one cell: colored feature(s), filter feature, all categorical annotations. */
  describe(sd: SampleData, i: number, s: ViewerState): { rows: { label: string; value: string; swatch?: string }[] } {
    const c = this.c;
    const rows: { label: string; value: string; swatch?: string }[] = [];
    if (!c.manifest) return { rows };
    const smp = c.samplesById.get(sd.id)!;
    const geneRow = (gene: string, prefix = "") => {
      const label = this.featureLabel(gene);
      if (!sd.geneIndex.has(gene)) return rows.push({ label: prefix + label, value: "not measured" });
      const a = c.cache.getGeneSync(sd.id, gene);
      const gmax = c.geneGmax.get(`${sd.id}:${gene}`);
      if (!a || gmax === undefined) return rows.push({ label: prefix + label, value: "…" });
      return rows.push({ label: prefix + label, value: a.value[i] === 0 ? "0" : fmtValue((a.value[i] / 255) * gmax) });
    };
    if (s.color?.kind === "gene") geneRow(s.color.gene);
    if (s.color?.kind === "blend") {
      for (const [name, genes] of [["set A", s.color.a], ["set B", s.color.b]] as const) {
        const sc = c.blend.score(sd, genes);
        rows.push({ label: `${name} (${c.blend.coverage(sd, genes)}/${genes.length} genes)`, value: sc ? `${Math.round((100 * sc[i]) / 255)}%` : "not measured" });
      }
    }
    if (s.filter?.kind === "gene" && (s.color?.kind !== "gene" || s.filter.gene !== s.color.gene)) geneRow(s.filter.gene, "filter: ");
    for (const f of c.manifest.fields) {
      if (!smp.fields.includes(f.id)) continue;
      if (f.type === "categorical") {
        const codes = sd.cat.get(f.id);
        if (!codes) {
          void c.cache.getCategorical(sd.id, f.id).then(() => c.requestLayers());
          rows.push({ label: f.name, value: "…" });
          continue;
        }
        const v = c.manifest.vocabularies[f.vocabulary];
        const code = codes[i];
        rows.push({ label: f.name, value: v.categories[code] ?? "?", swatch: v.colors[code] });
      } else if (s.color?.kind === "field" && s.color.field === f.id) {
        const vals = sd.num.get(f.id);
        rows.push({ label: f.name, value: vals ? fmtValue(vals[i]) : "…" });
      }
    }
    return { rows };
  }

  featureLabel(gene: string): string {
    const groups = store.getState().features?.groups ?? [];
    for (const g of groups) {
      const f = g.features.find((x) => x.id === gene);
      if (f) return f.label;
    }
    return gene;
  }

  private onClick = (e: MouseEvent) => {
    const hit = this.worldFromEvent(e);
    if (!hit) return;
    store.getState().set({ selected: this.sampleAt(hit.view, hit.world[0], hit.world[1]), activeView: hit.view });
  };

  private onDblClick = (e: MouseEvent) => {
    const hit = this.worldFromEvent(e);
    if (!hit) return;
    const id = this.sampleAt(hit.view, hit.world[0], hit.world[1]);
    const s = store.getState();
    if (id && id !== s.focus) s.setFocus(id);
    else if (!id) s.setFocus(null);
  };

  private onKey = (e: KeyboardEvent) => {
    const t = e.target as HTMLElement | null;
    if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
    const c = this.c;
    const s = store.getState();
    if (e.key === "ArrowRight" || e.key === "PageDown") {
      c.stepFocus(1);
      e.preventDefault();
    } else if (e.key === "ArrowLeft" || e.key === "PageUp") {
      c.stepFocus(-1);
      e.preventDefault();
    } else if (e.key === "Escape") {
      if (c.selection.current) c.selection.clear();
      else if (s.tool === "lasso") s.set({ tool: "pan" });
      else s.setFocus(null);
    } else if (e.key === "l") {
      s.set({ tool: s.tool === "lasso" ? "pan" : "lasso" });
    } else if (e.key === "Enter" && s.selected) {
      s.setFocus(s.selected);
    } else if (e.key === "f") {
      if (s.focus) c.focusSample(s.focus, true);
      else for (const v of VIEWS) if (c.rects[v]) c.fitAll(v, true);
    }
  };
}
