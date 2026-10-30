import { store, useViewer } from "../store/store";

export function StatusBar() {
  const status = useViewer((s) => s.status);
  const pending = useViewer((s) => s.pending);
  const timings = useViewer((s) => s.timings);
  const sampleStatus = useViewer((s) => s.sampleStatus);
  const focus = useViewer((s) => s.focus);
  const manifest = useViewer((s) => s.manifest);
  const debug = useViewer((s) => s.debug);
  const shapeHint = useViewer((s) => s.shapeHint);
  const moleculeHint = useViewer((s) => s.moleculeHint);
  if (status === "idle") return null;
  const n = Object.keys(sampleStatus).length;
  const ready = Object.values(sampleStatus).filter((x) => x === "ready").length;
  const errs = Object.values(sampleStatus).filter((x) => x === "error").length;
  const focusName = focus ? manifest?.samples.find((s) => s.id === focus)?.name : null;
  return (
    <div className="statusbar">
      <span className={`dot ${status}`} />
      <span>{status === "loading" ? `loading ${ready}/${n} samples` : `${ready}/${n} samples`}</span>
      {errs > 0 && <span className="warn">{errs} failed</span>}
      {pending > 0 && <span className="pending">fetching {pending}…</span>}
      {(shapeHint || moleculeHint) && <span className="muted">{[shapeHint, moleculeHint].filter(Boolean).join(" · ")}</span>}
      {debug && timings.lastGeneMs != null && (
        <span title="gene switch: time until every section's column was here (data), and until the first frame drawn with it (frame)">
          gene switch {timings.lastGeneMs.toFixed(0)} ms data{timings.lastGeneFrameMs != null && ` · ${timings.lastGeneFrameMs.toFixed(0)} ms frame`}
        </span>
      )}
      {debug && <span>{timings.fps} fps</span>}
      <span className="grow" />
      <span className="muted">{focusName ? `focus: ${focusName} · Esc = all` : "dbl-click a sample to focus · ←/→ step · f = fit"}</span>
      <button className="helpbtn" title="keyboard shortcuts (?)" onClick={() => store.getState().set({ help: !store.getState().help })}>
        ?
      </button>
    </div>
  );
}
