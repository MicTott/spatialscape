/**
 * Panes: how the canvas is divided. One pane holds the tissue sections (or one pane per group when the
 * dataset is split by a sample meta key such as condition), plus an optional pane for the embeddings.
 * Pure functions of the manifest and the store state, so the layout can be tested without a GL context.
 */
import type { Manifest, Sample } from "../data/manifest";
import type { GroupSplit, PaneInfo, SplitState, ViewKind, ViewRect } from "../store/store";

export const MAX_GROUP_PANES = 3;
export const PANE_HEADER = 30; // px above each pane for the caption, when the canvas is split by a key
export const STACK_BELOW = 900; // container width (px) under which group panes stack vertically
export const MIN_PANE_FRACTION = 0.12;

export interface Pane {
  id: string; // "spatial" | "embedding" | "g0".."g2"
  kind: ViewKind;
  group: { key: string; value: string } | null;
  samples: Sample[]; // in manifest order; the layout then applies layout.order and the hidden sets
}

/** The levels of a meta key: the declared order first, then values that samples carry, in sample order. */
export function metaLevels(m: Manifest, key: string, samples: Sample[] = m.samples): string[] {
  const out = [...(m.meta?.find((k) => k.id === key)?.levels ?? [])];
  for (const s of samples) {
    const v = s.meta?.[key];
    if (v != null && !out.includes(v)) out.push(v);
  }
  return out;
}

export function metaName(m: Manifest, key: string): string {
  return m.meta?.find((k) => k.id === key)?.name ?? key;
}

/** Meta keys the tissue sections can be split by: two or more levels among the spatial samples. */
export function splitKeys(m: Manifest): { id: string; name: string; levels: string[] }[] {
  const spatial = m.samples.filter((s) => s.kind !== "embedding");
  const ids: string[] = [];
  for (const k of m.meta ?? []) ids.push(k.id);
  for (const s of spatial) for (const k of Object.keys(s.meta ?? {})) if (!ids.includes(k)) ids.push(k);
  return ids
    .map((id) => ({ id, name: metaName(m, id), levels: presentLevels(m, id) }))
    .filter((k) => k.levels.length >= 2);
}

/** Levels of a key that at least one tissue section carries, in level order. */
export function presentLevels(m: Manifest, key: string): string[] {
  const spatial = m.samples.filter((s) => s.kind !== "embedding");
  const have = new Set(spatial.map((s) => s.meta?.[key]).filter((v): v is string => v != null));
  return metaLevels(m, key, spatial).filter((v) => have.has(v));
}

/** The groups shown as panes, in pane order: the chosen ones that still exist, else the first three levels. */
export function paneGroups(m: Manifest, split: GroupSplit): string[] {
  const levels = presentLevels(m, split.key);
  const chosen = (split.groups ?? []).filter((g) => levels.includes(g));
  return (chosen.length ? chosen : levels).slice(0, MAX_GROUP_PANES);
}

/** Tissue sections that carry no value of the split key (or a level not shown): drawn in no pane. */
export function unassignedSamples(m: Manifest, split: GroupSplit | null): Sample[] {
  if (!split) return [];
  const shown = new Set(paneGroups(m, split));
  return m.samples.filter((s) => s.kind !== "embedding" && !shown.has(s.meta?.[split.key] ?? ""));
}

export function computePanes(m: Manifest, split: GroupSplit | null, emb: SplitState): Pane[] {
  const spatial = m.samples.filter((s) => s.kind !== "embedding");
  const embedding = m.samples.filter((s) => s.kind === "embedding");
  const tissue: Pane[] = [];
  const groups = split && presentLevels(m, split.key).length >= 2 ? paneGroups(m, split) : null;
  if (groups) {
    groups.forEach((value, i) => tissue.push({ id: `g${i}`, kind: "spatial", group: { key: split!.key, value }, samples: spatial.filter((s) => s.meta?.[split!.key] === value) }));
  } else if (spatial.length) {
    tissue.push({ id: "spatial", kind: "spatial", group: null, samples: spatial });
  }
  const out = [...tissue];
  if (embedding.length && (emb.on || !tissue.length)) {
    const pane: Pane = { id: "embedding", kind: "embedding", group: null, samples: embedding };
    if (emb.side === "left") out.unshift(pane);
    else out.push(pane);
  }
  return out;
}

/** Width (or height, stacked) shares of the group panes: the dragged fractions when they still fit, else equal. */
export function groupFractions(n: number, fractions: number[] | null): number[] {
  if (fractions && fractions.length === n && fractions.every((f) => f > 0)) {
    const sum = fractions.reduce((a, b) => a + b, 0);
    const norm = fractions.map((f) => f / sum);
    if (norm.every((f) => f >= MIN_PANE_FRACTION - 1e-6)) return norm;
  }
  return new Array(n).fill(1 / Math.max(1, n));
}

/** Pixel rectangles of the panes inside a width x height container. Group panes get a header strip when the
 *  canvas is split; the embedding pane keeps its width fraction and sits at its side. Under `stacked` the panes
 *  are laid out top to bottom instead. The last pane always takes the rounding remainder. */
export function paneRects(panes: Pane[], width: number, height: number, split: GroupSplit | null, emb: SplitState, stacked: boolean): Record<string, ViewRect> {
  const out: Record<string, ViewRect> = {};
  if (!panes.length) return out;
  const header = split && panes.some((p) => p.group) ? PANE_HEADER : 0;
  const embPane = panes.find((p) => p.kind === "embedding");
  const tissue = panes.filter((p) => p.kind !== "embedding");
  const total = stacked ? height : width;
  const embSize = embPane && tissue.length ? Math.round(total * Math.min(0.8, Math.max(0.2, emb.fraction))) : embPane ? total : 0;
  const tissueSize = total - embSize;
  const shares = groupFractions(tissue.length, tissue.some((p) => p.group) ? (split?.fractions ?? null) : null);
  const sizes = new Map<string, number>();
  if (embPane) sizes.set(embPane.id, embSize);
  let used = 0;
  tissue.forEach((p, i) => {
    const px = i === tissue.length - 1 ? tissueSize - used : Math.round(tissueSize * shares[i]);
    sizes.set(p.id, px);
    used += px;
  });
  let cursor = 0;
  for (const p of panes) {
    const size = sizes.get(p.id) ?? 0;
    out[p.id] = stacked ? { x: 0, y: cursor + header, w: width, h: Math.max(1, size - header) } : { x: cursor, y: header, w: Math.max(1, size), h: Math.max(1, height - header) };
    cursor += size;
  }
  return out;
}

/** The point radius multiplier a pane draws with: its own when set, else its kind's base value. */
export function pointScaleFor(scales: Record<string, number>, view: string, kind: ViewKind): number {
  return scales[view] ?? scales[kind] ?? 1;
}

export function paneInfo(panes: Pane[], m: Manifest, hidden: Set<string>): PaneInfo[] {
  return panes.map((p) => ({
    id: p.id,
    kind: p.kind,
    key: p.group?.key ?? null,
    value: p.group?.value ?? null,
    label: p.group ? p.group.value : p.kind === "embedding" ? "snRNA-seq" : "sections",
    count: p.samples.filter((s) => !hidden.has(s.id)).length,
    hidden: p.samples.filter((s) => hidden.has(s.id)).length,
  }));
}

/** New width shares after dragging the boundary between group panes k-1 and k to `at` (a fraction of the
 *  group area): only the two neighbours change, and neither goes under the minimum. */
export function dragFractions(fractions: number[], k: number, at: number): number[] {
  const out = [...fractions];
  const before = out.slice(0, k - 1).reduce((a, b) => a + b, 0);
  const pair = out[k - 1] + out[k];
  const left = Math.min(pair - MIN_PANE_FRACTION, Math.max(MIN_PANE_FRACTION, at - before));
  out[k - 1] = left;
  out[k] = pair - left;
  return out;
}
