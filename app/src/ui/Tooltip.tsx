import { useViewer } from "../store/store";

export function Tooltip() {
  const hover = useViewer((s) => s.hover);
  const manifest = useViewer((s) => s.manifest);
  if (!hover || !manifest) return null;
  const smp = manifest.samples.find((x) => x.id === hover.sampleId);
  const style = { left: hover.x + 14, top: hover.y + 14 };
  return (
    <div className="tooltip" style={style}>
      <div className="tt-sample">{smp?.name ?? hover.sampleId}</div>
      {hover.rows?.map((r, i) => (
        <div className="tt-row" key={i}>
          <span className="tt-label">
            {r.swatch && <span className="swatch" style={{ background: r.swatch }} />}
            {r.label}
          </span>
          <b>{r.value}</b>
        </div>
      ))}
      <div className="tt-id">{hover.id ?? "…"}</div>
    </div>
  );
}
