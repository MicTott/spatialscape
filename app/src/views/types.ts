import type { BinaryAttr } from "../data/cache";
import type { FilterSpec, ViewId } from "../store/store";

export const VIEWS: ViewId[] = ["spatial", "embedding"];

export interface SampleLayerInputs {
  pos: BinaryAttr<Float32Array>;
  value?: BinaryAttr<Uint8Array>;
  cat?: BinaryAttr<Uint16Array>;
  filter?: BinaryAttr<Uint8Array>;
  data: { length: number; attributes: Record<string, BinaryAttr<ArrayBufferView>> };
}

export interface ViewRect {
  x: number; // px from the left of the container
  w: number;
}

/** Layer props shared by every overlay: never pick, never fight the depth buffer, route to one view. */
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
