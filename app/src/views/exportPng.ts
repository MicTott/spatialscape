/** Composes the current GL frame with a legend and scale bar onto a 2D canvas and triggers a download. */
import { fieldById } from "../data/manifest";
import { colormapLUT } from "../layers/lut";
import { store, type ViewId } from "../store/store";
import { niceScale } from "../ui/ScaleBar";
import type { ViewRect } from "./types";

export function composePNG(gl: HTMLCanvasElement, container: HTMLElement, rects: Partial<Record<ViewId, ViewRect>>) {
  const s = store.getState();
  const m = s.manifest;
  if (!m) return;
  const dpr = gl.width / Math.max(1, container.clientWidth);
  const out = document.createElement("canvas");
  out.width = gl.width;
  out.height = gl.height;
  const ctx = out.getContext("2d")!;
  ctx.fillStyle = "#0e1116";
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(gl, 0, 0);
  const px = (v: number) => v * dpr;
  const font = (size: number, weight = 400) => `${weight} ${px(size)}px Inter, system-ui, sans-serif`;
  const panel = "rgba(22,27,34,0.88)";

  // ---- legend (top-right of the spatial view, else of the canvas)
  const rect = rects.spatial ?? rects.embedding ?? { x: 0, w: container.clientWidth };
  const right = px(rect.x + rect.w) - px(12);
  let title = "";
  let rows: { color: string; label: string; n?: number }[] = [];
  let ramp: { lut: Uint8Array; lo: string; hi: string } | null = null;
  if (s.color?.kind === "field") {
    const f = fieldById(m, s.color.field);
    if (f) {
      title = f.name;
      if (f.type === "categorical") {
        const v = m.vocabularies[f.vocabulary];
        const hid = new Set(s.hiddenCategories[f.id] ?? []);
        const cnt = s.categoryCounts[f.id];
        rows = v.categories
          .map((label, i) => ({ color: v.colors[i], label, n: cnt?.[i], i }))
          .filter((r) => !hid.has(r.i) && (r.n === undefined || r.n > 0))
          .sort((a, b) => (b.n ?? 0) - (a.n ?? 0));
      } else ramp = { lut: colormapLUT(s.colormap), lo: "low", hi: "high" };
    }
  } else if (s.color?.kind === "gene") {
    const grp = s.features?.groups.find((g) => g.features.some((f) => f.id === (s.color as any).gene));
    title = grp?.features.find((f) => f.id === (s.color as any).gene)?.label ?? s.color.gene;
    const lo = s.vrange[0] * s.geneMax;
    const hi = s.vrange[1] * s.geneMax;
    ramp = { lut: colormapLUT(s.colormap), lo: s.scalePerSample ? "0" : lo.toFixed(2), hi: s.scalePerSample ? "max per sample" : hi.toFixed(2) };
  } else if (s.color?.kind === "blend") {
    title = `Blend: A = ${s.color.a.join(", ") || "(empty)"} · B = ${s.color.b.join(", ") || "(empty)"}`;
  }
  const maxRows = 30;
  const shown = rows.slice(0, maxRows);
  const lineH = px(16);
  const pad = px(10);
  ctx.font = font(12, 600);
  let boxW = ctx.measureText(title).width;
  ctx.font = font(11);
  for (const r of shown) boxW = Math.max(boxW, px(18) + ctx.measureText(r.label).width + (r.n != null ? px(8) + ctx.measureText(r.n.toLocaleString()).width : 0));
  if (ramp) boxW = Math.max(boxW, px(160));
  boxW += pad * 2;
  const boxH = pad * 2 + px(18) + (ramp ? px(30) : shown.length * lineH + (rows.length > maxRows ? lineH : 0));
  if (title) {
    const x0 = right - boxW;
    const y0 = px(12);
    ctx.fillStyle = panel;
    roundRect(ctx, x0, y0, boxW, boxH, px(8));
    ctx.fill();
    ctx.fillStyle = "#e6edf3";
    ctx.font = font(12, 600);
    ctx.textBaseline = "top";
    ctx.fillText(title, x0 + pad, y0 + pad);
    let y = y0 + pad + px(20);
    if (ramp) {
      const w = boxW - pad * 2;
      for (let i = 0; i < 256; i++) {
        ctx.fillStyle = `rgb(${ramp.lut[i * 4]},${ramp.lut[i * 4 + 1]},${ramp.lut[i * 4 + 2]})`;
        ctx.fillRect(x0 + pad + (w * i) / 256, y, w / 256 + 1, px(10));
      }
      ctx.fillStyle = "#8b949e";
      ctx.font = font(10);
      ctx.fillText(ramp.lo, x0 + pad, y + px(13));
      const hw = ctx.measureText(ramp.hi).width;
      ctx.fillText(ramp.hi, x0 + boxW - pad - hw, y + px(13));
    } else {
      ctx.font = font(11);
      for (const r of shown) {
        ctx.fillStyle = r.color;
        roundRect(ctx, x0 + pad, y + px(2), px(11), px(11), px(2));
        ctx.fill();
        ctx.fillStyle = "#e6edf3";
        ctx.fillText(r.label, x0 + pad + px(18), y);
        if (r.n != null) {
          ctx.fillStyle = "#8b949e";
          const t = r.n.toLocaleString();
          ctx.fillText(t, x0 + boxW - pad - ctx.measureText(t).width, y);
        }
        y += lineH;
      }
      if (rows.length > maxRows) {
        ctx.fillStyle = "#8b949e";
        ctx.fillText(`+${rows.length - maxRows} more`, x0 + pad + px(18), y);
      }
    }
  }

  // ---- scale bar (bottom-left of the spatial view)
  const sp = s.viewPx.spatial;
  if (sp && rects.spatial) {
    const { um, label } = niceScale(sp);
    const w = px(um * sp);
    const x = px(rects.spatial.x + 16);
    const y = px(container.clientHeight - 22);
    ctx.fillStyle = "#e6edf3";
    ctx.fillRect(x, y, w, px(3));
    ctx.fillRect(x, y - px(6), px(2), px(9));
    ctx.fillRect(x + w - px(2), y - px(6), px(2), px(9));
    ctx.font = font(11, 600);
    ctx.textBaseline = "bottom";
    ctx.fillText(label, x, y - px(8));
  }

  const colorName = s.color?.kind === "gene" ? s.color.gene : s.color?.kind === "field" ? s.color.field : s.color?.kind === "blend" ? "blend" : "view";
  out.toBlob((blob) => {
    if (!blob) return;
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${m.id}-${colorName}.png`.replace(/[^\w.-]+/g, "_");
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  }, "image/png");
}

function roundRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}
