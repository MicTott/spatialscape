import { Matrix4 } from "@math.gl/core";
import type { LayoutMode, Sample } from "../data/manifest";

export interface Placement {
  sampleId: string;
  /** translation applied after toDataset, in dataset microns */
  offset: [number, number];
  /** world-space bbox [minx, miny, maxx, maxy] after placement */
  worldBbox: [number, number, number, number];
  /** 4x4 column-major model matrix for deck.gl */
  modelMatrix: Matrix4;
  row: number;
  col: number;
}
export interface LayoutResult {
  placements: Map<string, Placement>;
  worldBbox: [number, number, number, number];
  cell: [number, number];
  ncols: number;
  nrows: number;
}

function affine3to4(a: number[]): Matrix4 {
  // a is 3x3 row-major [a b c; d e f; 0 0 1]
  const m = new Matrix4();
  m.setRowMajor(a[0], a[1], 0, a[2], a[3], a[4], 0, a[5], 0, 0, 1, 0, 0, 0, 0, 1);
  return m;
}

/** bbox of a sample after its toDataset affine. */
export function datasetBbox(s: Sample): [number, number, number, number] {
  const m = affine3to4(s.toDataset);
  const [x0, y0, x1, y1] = s.bbox;
  const pts = [
    [x0, y0],
    [x1, y0],
    [x0, y1],
    [x1, y1],
  ].map(([x, y]) => m.transformAsPoint([x, y, 0]));
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

export function computeLayout(
  samples: Sample[],
  order: string[],
  mode: LayoutMode,
  gutterFraction: number,
  viewportAspect: number,
  hidden: ReadonlySet<string> = new Set(),
): LayoutResult {
  const byId = new Map(samples.map((s) => [s.id, s]));
  const ids = order.filter((id) => byId.has(id) && !hidden.has(id));
  for (const s of samples) if (!ids.includes(s.id) && !hidden.has(s.id)) ids.push(s.id);
  const bboxes = new Map(ids.map((id) => [id, datasetBbox(byId.get(id)!)]));
  let maxW = 1;
  let maxH = 1;
  for (const b of bboxes.values()) {
    maxW = Math.max(maxW, b[2] - b[0]);
    maxH = Math.max(maxH, b[3] - b[1]);
  }
  const cellW = maxW * (1 + gutterFraction);
  const cellH = maxH * (1 + gutterFraction);
  const n = Math.max(1, ids.length);
  const ncols = mode === "strip" ? n : Math.max(1, Math.min(n, Math.ceil(Math.sqrt((n * viewportAspect * cellH) / cellW))));
  const nrows = Math.ceil(n / ncols);
  const placements = new Map<string, Placement>();
  ids.forEach((id, i) => {
    const b = bboxes.get(id)!;
    const col = i % ncols;
    const row = Math.floor(i / ncols);
    // center each sample inside its cell
    const ox = col * cellW + (cellW - (b[2] - b[0])) / 2 - b[0];
    const oy = row * cellH + (cellH - (b[3] - b[1])) / 2 - b[1];
    const modelMatrix = new Matrix4().translate([ox, oy, 0]).multiplyRight(affine3to4(byId.get(id)!.toDataset));
    placements.set(id, {
      sampleId: id,
      offset: [ox, oy],
      worldBbox: [b[0] + ox, b[1] + oy, b[2] + ox, b[3] + oy],
      modelMatrix,
      row,
      col,
    });
  });
  return {
    placements,
    worldBbox: [0, 0, ncols * cellW, nrows * cellH],
    cell: [cellW, cellH],
    ncols,
    nrows,
  };
}

/** Orthographic view state that fits a bbox into a viewport (px) with padding fraction. */
export function fitBbox(bbox: [number, number, number, number], width: number, height: number, pad = 0.05) {
  const bw = Math.max(1e-6, bbox[2] - bbox[0]);
  const bh = Math.max(1e-6, bbox[3] - bbox[1]);
  const scale = Math.min((width * (1 - 2 * pad)) / bw, (height * (1 - 2 * pad)) / bh);
  return { target: [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2, 0] as [number, number, number], zoom: Math.log2(scale) };
}
