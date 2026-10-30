import type { BinaryAttr } from "../data/cache";
import type { FilterSpec, ViewId, ViewKind, ViewRect } from "../store/store";

export type { ViewId, ViewKind, ViewRect };
export const VIEW_KINDS: ViewKind[] = ["spatial", "embedding"];

export interface SampleLayerInputs {
  pos: BinaryAttr<Float32Array>;
  value?: BinaryAttr<Uint8Array>;
  cat?: BinaryAttr<Uint16Array>;
  filter?: BinaryAttr<Uint8Array>;
  data: { length: number; attributes: Record<string, BinaryAttr<ArrayBufferView>> };
}

/** Layer props shared by every overlay: never pick, never fight the depth buffer, route to one pane. */
export function overlayProps(view: ViewId) {
  return { pickable: false, viewId: view, parameters: { depthWriteEnabled: false, depthCompare: "always" } } as const;
}

export function filterRange(f: FilterSpec): [number, number] {
  return f.kind === "category" ? [0.5, 1] : f.range;
}

export function sameChannel(a: FilterSpec, b: FilterSpec) {
  return a.kind === b.kind && (a.kind === "gene" ? a.gene === (b as any).gene : a.field === (b as any).field);
}

export const fmtValue = (v: number) => (Math.abs(v) >= 1000 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));

/** One CSV line: a field with a comma, quote or line break is quoted, quotes doubled. */
export function csvLine(fields: (string | number)[]): string {
  return fields.map((f) => (/[",\r\n]/.test(String(f)) ? `"${String(f).replace(/"/g, '""')}"` : String(f))).join(",");
}
