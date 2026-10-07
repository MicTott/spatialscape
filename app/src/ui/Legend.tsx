import { fieldById } from "../data/manifest";
import { useEffect, useRef } from "react";
import { BLEND_SCHEMES, BLEND_SIZE, blendLUT, colormapCSS } from "../layers/lut";
import { store, useViewer } from "../store/store";

function BlendLegend({ scheme, a, b }: { scheme: string; a: string[]; b: string[] }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const ctx = cv.getContext("2d")!;
    const img = new ImageData(new Uint8ClampedArray(blendLUT(scheme)), BLEND_SIZE, BLEND_SIZE);
    // flip vertically so B increases upwards
    const tmp = document.createElement("canvas");
    tmp.width = tmp.height = BLEND_SIZE;
    tmp.getContext("2d")!.putImageData(img, 0, 0);
    ctx.save();
    ctx.imageSmoothingEnabled = true;
    ctx.translate(0, cv.height);
    ctx.scale(cv.width / BLEND_SIZE, -cv.height / BLEND_SIZE);
    ctx.drawImage(tmp, 0, 0);
    ctx.restore();
  }, [scheme]);
  const sc = BLEND_SCHEMES[scheme] ?? BLEND_SCHEMES.yb;
  const name = (list: string[]) => (list.length === 0 ? "(empty)" : list.length <= 3 ? list.join(", ") : `${list.slice(0, 2).join(", ")} +${list.length - 2}`);
  return (
    <div className="legend blend-legend">
      <div className="legend-head">
        <span>Blend</span>
        <span className="muted">{sc.name}</span>
      </div>
      <div className="blend-grid">
        <div className="blend-y" title={b.join(", ")}>
          <span className="swatch" style={{ background: sc.b }} /> B: {name(b)}
        </div>
        <canvas ref={ref} width={96} height={96} />
        <div />
        <div className="blend-x" title={a.join(", ")}>
          <span className="swatch" style={{ background: sc.a }} /> A: {name(a)}
        </div>
      </div>
      <div className="muted small">corner colors: neither · A only · B only · both</div>
    </div>
  );
}

export function Legend() {
  const manifest = useViewer((s) => s.manifest);
  const color = useViewer((s) => s.color);
  const hidden = useViewer((s) => s.hiddenCategories);
  const counts = useViewer((s) => s.categoryCounts);
  const colormap = useViewer((s) => s.colormap);
  const vrange = useViewer((s) => s.vrange);
  const geneMax = useViewer((s) => s.geneMax);
  const features = useViewer((s) => s.features);
  const platforms = useViewer((s) => s.platforms);
  const hiddenSamples = useViewer((s) => s.hiddenSamples);
  const scalePerSample = useViewer((s) => s.scalePerSample);
  if (!manifest || !color) return null;
  // samples currently on screen that do not carry the colored field: drawn grey as "not measured"
  const onScreen = manifest.samples.filter((smp) => !hiddenSamples.includes(smp.id) && (smp.kind === "embedding" || !platforms || platforms.includes(smp.platform)));
  const notMeasured = color.kind === "field" ? onScreen.filter((smp) => !smp.fields.includes((color as any).field)).length : 0;

  if (color.kind === "field") {
    const f = fieldById(manifest, color.field);
    if (!f) return null;
    if (f.type === "categorical") {
      const v = manifest.vocabularies[f.vocabulary];
      const hid = new Set(hidden[f.id] ?? []);
      const cnt = counts[f.id];
      // categories with no cells in the loaded samples are dropped; the rest sort by count so the big classes come first
      const order = v.categories.map((_, i) => i).filter((i) => !cnt || cnt[i] > 0 || hid.has(i));
      if (cnt) order.sort((a, b) => cnt[b] - cnt[a]);
      const all = () => store.getState().setHiddenCategories(f.id, []);
      const none = () => store.getState().setHiddenCategories(f.id, v.categories.map((_, i) => i));
      return (
        <div className="legend">
          <div className="legend-head">
            <span>{f.name}</span>
            <span className="legend-actions">
              <button onClick={all}>all</button>
              <button onClick={none}>none</button>
            </span>
          </div>
          <ul className="cats">
            {order.map((i) => {
              const c = v.categories[i];
              return (
              <li
                key={c}
                className={hid.has(i) ? "off" : ""}
                onClick={() => store.getState().toggleCategory(f.id, i)}
                onDoubleClick={(e) => {
                  e.preventDefault();
                  store.getState().setHiddenCategories(f.id, v.categories.map((_, j) => j).filter((j) => j !== i));
                }}
                title="click: toggle · double-click: solo"
              >
                <span className="swatch" style={{ background: v.colors[i] }} />
                <span className="cat-name">{c}</span>
                {cnt && <span className="cat-n">{cnt[i].toLocaleString()}</span>}
              </li>
              );
            })}
          </ul>
          {notMeasured > 0 && <NotMeasured n={notMeasured} />}
        </div>
      );
    }
    return (
      <div className="legend">
        <div className="legend-head">
          <span>{f.name}</span>
        </div>
        <div className="ramp" style={{ background: colormapCSS(colormap) }} />
        <div className="ramp-labels">
          <span>low</span>
          <span>high</span>
        </div>
        {notMeasured > 0 && <NotMeasured n={notMeasured} />}
      </div>
    );
  }
  if (color.kind === "blend") return <BlendLegend scheme={color.scheme} a={color.a} b={color.b} />;
  const lo = vrange[0] * geneMax;
  const hi = vrange[1] * geneMax;
  const group = features?.groups.find((g) => g.features.some((f) => f.id === color.gene));
  const label = group?.features.find((f) => f.id === color.gene)?.label ?? color.gene;
  return (
    <div className="legend">
      <div className="legend-head">
        <span>{label}</span>
        <span className="muted">{group ? (group.units ?? group.name) : "log-normalized"}</span>
      </div>
      <div className="ramp" style={{ background: colormapCSS(colormap) }} />
      <div className="ramp-labels">
        <span>{scalePerSample ? "0" : lo.toFixed(2)}</span>
        <span>{scalePerSample ? "max per sample" : hi.toFixed(2)}</span>
      </div>
    </div>
  );
}

function NotMeasured({ n }: { n: number }) {
  return (
    <div className="muted small notmeasured">
      <span className="swatch" style={{ background: "#5c6470" }} /> grey: not measured in {n} sample{n === 1 ? "" : "s"} on screen
    </div>
  );
}
