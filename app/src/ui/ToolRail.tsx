import { store, useViewer } from "../store/store";

/** Compact canvas controls. Tool selection and fitting use the same store and controller as keyboard shortcuts. */
export function ToolRail() {
  const manifest = useViewer((s) => s.manifest);
  const tool = useViewer((s) => s.tool);
  if (!manifest) return null;
  const set = store.getState().set;
  const fit = () => {
    const c = window.__sscape?.controller;
    const focus = store.getState().focus;
    if (!c) return;
    if (focus) c.focusSample(focus, true);
    else c.fitAllPanes(true);
  };
  return (
    <nav className="toolrail" aria-label="Canvas tools">
      <button className={tool === "pan" ? "active" : ""} aria-label="Pan" aria-pressed={tool === "pan"} title="Pan" onClick={() => set({ tool: "pan" })}><svg viewBox="0 0 24 24"><path d="M12 3v18M3 12h18M9 6l3-3 3 3M9 18l3 3 3-3M6 9l-3 3 3 3M18 9l3 3-3 3" /></svg></button>
      <button className={tool === "lasso" ? "active" : ""} aria-label="Lasso select" aria-pressed={tool === "lasso"} title="Lasso select (L)" onClick={() => set({ tool: "lasso" })}><svg viewBox="0 0 24 24"><path d="M9 19c-1 2-3 2-4 1m4-1c-4-1-6-4-5-8C5 7 9 4 14 5s7 5 6 8c-1 4-6 6-11 6zM9 19l2 2" /></svg></button>
      <span className="toolrail-divider" />
      <button aria-label="Fit view" title="Fit view (F)" onClick={fit}><svg viewBox="0 0 24 24"><path d="M9 4H4v5m11-5h5v5M4 15v5h5m11-5v5h-5" /></svg></button>
      <button className="toolrail-help" aria-label="Keyboard shortcuts" title="Keyboard shortcuts (?)" onClick={() => set({ help: !store.getState().help })}><svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M9.5 9a2.5 2.5 0 1 1 3.8 2.1c-1 .6-1.3 1.1-1.3 2.2M12 17h.01" /></svg></button>
    </nav>
  );
}
