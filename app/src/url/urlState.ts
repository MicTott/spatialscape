/** URLSearchParams <-> store. Source of truth is the store; the URL mirrors it (replaceState). */
import { DEFAULTS, store, type ColorSpec, type FilterSpec, type ViewerState } from "../store/store";

const num = (s: string | null, d: number) => (s == null || s === "" || Number.isNaN(+s) ? d : +s);

function parseColor(s: string | null): ColorSpec | null {
  if (!s) return null;
  if (s.startsWith("g:")) return { kind: "gene", gene: s.slice(2) };
  if (s.startsWith("f:")) return { kind: "field", field: s.slice(2) };
  return null;
}
function parseFilter(s: string | null): FilterSpec | null {
  if (!s) return null;
  const c = /^c:([^:]+):(.*)$/.exec(s);
  if (c) return { kind: "category", field: c[1], codes: c[2].split(".").map(Number).filter((n) => Number.isFinite(n)) };
  const m = /^(g|f):([^:]+):([^,]*),(.*)$/.exec(s);
  if (!m) return null;
  const range: [number, number] = [num(m[3], 0), num(m[4], 1)];
  return m[1] === "g" ? { kind: "gene", gene: m[2], range } : { kind: "field", field: m[2], range };
}
function parseHidden(s: string | null): Record<string, number[]> {
  const out: Record<string, number[]> = {};
  if (!s) return out;
  for (const part of s.split(";")) {
    const [f, codes] = part.split(":");
    if (f && codes) out[f] = codes.split(".").map(Number).filter((n) => Number.isFinite(n));
  }
  return out;
}

export function readUrl(): Partial<ViewerState> {
  const q = new URLSearchParams(window.location.search);
  const out: Partial<ViewerState> = {};
  const d = q.get("d");
  if (d) out.datasetUrl = d;
  const c = parseColor(q.get("c"));
  if (c) out.color = c;
  if (q.get("cm")) out.colormap = q.get("cm")!;
  if (q.get("vr")) {
    const [a, b] = q.get("vr")!.split(",");
    out.vrange = [num(a, 0), num(b, 1)];
  }
  if (q.get("z")) out.hideZeros = q.get("z") === "1";
  const f = parseFilter(q.get("fl"));
  if (f) out.filter = f;
  if (q.get("v")) {
    const [x, y, z] = q.get("v")!.split(",");
    out.viewState = { target: [num(x, 0), num(y, 0), 0], zoom: num(z, 0) };
  }
  if (q.get("h")) out.hiddenCategories = parseHidden(q.get("h"));
  if (q.get("img") != null) {
    const v = num(q.get("img"), 1);
    out.imageOpacity = v;
    out.showImages = v > 0;
  }
  if (q.get("l") === "strip" || q.get("l") === "grid") out.layoutMode = q.get("l") as "strip" | "grid";
  if (q.get("s")) out.focus = q.get("s");
  if (q.get("hs")) out.hiddenSamples = q.get("hs")!.split(",").filter(Boolean);
  if (q.get("ps")) out.pointScale = num(q.get("ps"), 1);
  if (q.get("o")) {
    const [field, style, width] = q.get("o")!.split(":");
    if (field) out.outline = { field, style: (["field", "light", "dark"].includes(style) ? style : "light") as "field" | "light" | "dark", width: num(width, 1.5) };
  }
  if (q.get("gf")) out.groupField = q.get("gf");
  if (q.get("poly") === "0") out.showPolygons = false;
  if (q.get("p")) out.platforms = q.get("p")!.split(",").filter(Boolean);
  if (q.get("sv")) {
    const v = q.get("sv")!;
    if (v === "0") out.split = { on: false, side: "left", fraction: 0.38 };
    else {
      const m = /^(l|r):([\d.]+)$/.exec(v);
      if (m) out.split = { on: true, side: m[1] === "l" ? "left" : "right", fraction: Math.min(0.8, Math.max(0.2, num(m[2], 0.38))) };
    }
  }
  return out;
}

export function serialize(s: ViewerState): string {
  const q = new URLSearchParams();
  if (s.datasetUrl) q.set("d", s.datasetUrl);
  if (s.focus) q.set("s", s.focus);
  if (s.color) q.set("c", s.color.kind === "gene" ? `g:${s.color.gene}` : `f:${s.color.field}`);
  if (s.colormap !== DEFAULTS.colormap) q.set("cm", s.colormap);
  if (s.vrange[0] !== 0 || s.vrange[1] !== 1) q.set("vr", `${s.vrange[0].toFixed(3)},${s.vrange[1].toFixed(3)}`);
  if (s.hideZeros) q.set("z", "1");
  if (s.filter) {
    const f = s.filter;
    if (f.kind === "category") q.set("fl", `c:${f.field}:${f.codes.join(".")}`);
    else q.set("fl", `${f.kind === "gene" ? "g:" + f.gene : "f:" + f.field}:${f.range[0].toFixed(3)},${f.range[1].toFixed(3)}`);
  }
  if (s.viewState) q.set("v", `${s.viewState.target[0].toFixed(0)},${s.viewState.target[1].toFixed(0)},${s.viewState.zoom.toFixed(2)}`);
  const h = Object.entries(s.hiddenCategories)
    .filter(([, codes]) => codes.length)
    .map(([f, codes]) => `${f}:${codes.join(".")}`)
    .join(";");
  if (h) q.set("h", h);
  if (!s.showImages) q.set("img", "0");
  else if (s.imageOpacity !== 1) q.set("img", s.imageOpacity.toFixed(2));
  if (s.layoutMode !== DEFAULTS.layoutMode) q.set("l", s.layoutMode);
  if (s.hiddenSamples.length) q.set("hs", s.hiddenSamples.join(","));
  if (s.pointScale !== 1) q.set("ps", s.pointScale.toFixed(2));
  if (s.platforms) q.set("p", s.platforms.join(","));
  if (s.groupField) q.set("gf", s.groupField);
  if (!s.showPolygons) q.set("poly", "0");
  if (s.outline.field) q.set("o", `${s.outline.field}:${s.outline.style}:${s.outline.width}`);
  if (!s.split.on) q.set("sv", "0");
  else if (s.split.side !== "left" || Math.abs(s.split.fraction - 0.38) > 0.005) q.set("sv", `${s.split.side[0]}:${s.split.fraction.toFixed(2)}`);
  return q.toString();
}

export function bindUrl(): () => void {
  let timer: number | null = null;
  let last = "";
  const write = () => {
    timer = null;
    const qs = serialize(store.getState());
    if (qs === last) return;
    last = qs;
    history.replaceState(null, "", `${location.pathname}?${qs}${location.hash}`);
  };
  return store.subscribe((s, prev) => {
    if (s.hover !== prev.hover || s.pending !== prev.pending || s.timings !== prev.timings) {
      // ignore high-frequency, non-URL state unless something else changed too
      const keys = (Object.keys(s) as (keyof ViewerState)[]).filter((k) => s[k] !== prev[k]);
      if (keys.every((k) => k === "hover" || k === "pending" || k === "timings" || k === "categoryCounts" || k === "visibleCount" || k === "filterHistogram")) return;
    }
    const slow = s.viewState !== prev.viewState;
    if (timer) window.clearTimeout(timer);
    timer = window.setTimeout(write, slow ? 250 : 0);
  });
}
