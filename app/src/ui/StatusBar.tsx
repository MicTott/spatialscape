import { useViewer } from "../store/store";

export function StatusBar() {
  const status = useViewer((s) => s.status);
  const pending = useViewer((s) => s.pending);
  const timings = useViewer((s) => s.timings);
  const sampleStatus = useViewer((s) => s.sampleStatus);
  const focus = useViewer((s) => s.focus);
  const manifest = useViewer((s) => s.manifest);
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
      {timings.lastGeneMs != null && <span title="time from gene selection to all samples colored">gene switch {timings.lastGeneMs.toFixed(0)} ms</span>}
      <span>{timings.fps} fps</span>
      <span className="grow" />
      <span className="muted">{focusName ? `focus: ${focusName} · Esc = all` : "dbl-click a sample to focus · ←/→ step · f = fit"}</span>
    </div>
  );
}
