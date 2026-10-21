import { useEffect, useRef } from "react";
import { store, useViewer } from "../store/store";
import { dragFractions, groupFractions, PANE_HEADER } from "../views/panes";

/** Draggable handles between neighbouring panes. A handle next to the embedding pane resizes it (and carries the
 *  swap button); one between two group panes moves their shared boundary. Double-click equalises. */
export function PaneDividers({ mapRef }: { mapRef: React.RefObject<HTMLDivElement | null> }) {
  const panes = useViewer((s) => s.panes);
  const rects = useViewer((s) => s.viewRects);
  const split = useViewer((s) => s.split);
  const splitBy = useViewer((s) => s.splitBy);
  const drag = useRef<{ k: number; stacked: boolean } | null>(null);

  useEffect(() => {
    const move = (e: PointerEvent) => {
      const d = drag.current;
      const el = mapRef.current;
      if (!d || !el) return;
      const st = store.getState();
      const r = el.getBoundingClientRect();
      const pos = d.stacked ? (e.clientY - r.top) / r.height : (e.clientX - r.left) / r.width;
      const a = st.panes[d.k - 1];
      const b = st.panes[d.k];
      if (!a || !b) return;
      if (a.kind === "embedding" || b.kind === "embedding") {
        const frac = a.kind === "embedding" ? pos : 1 - pos; // the embedding pane sits before or after the boundary
        st.set({ split: { ...st.split, fraction: Math.min(0.8, Math.max(0.2, frac)) } });
        return;
      }
      // boundary between two group panes: a fraction of the group area, which excludes the embedding pane
      const groups = st.panes.filter((p) => p.key);
      const first = st.viewRects[groups[0].id];
      const last = st.viewRects[groups[groups.length - 1].id];
      if (!first || !last || !st.splitBy) return;
      const lo = d.stacked ? first.y - PANE_HEADER : first.x;
      const hi = d.stacked ? last.y + last.h : last.x + last.w;
      const total = d.stacked ? r.height : r.width;
      const at = (pos * total - lo) / Math.max(1, hi - lo);
      const kGroup = groups.findIndex((p) => p.id === b.id);
      if (kGroup < 1) return;
      const cur = groupFractions(groups.length, st.splitBy.fractions);
      st.set({ splitBy: { ...st.splitBy, fractions: dragFractions(cur, kGroup, at) } });
    };
    const up = () => {
      drag.current = null;
      document.body.style.cursor = "";
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [mapRef]);

  if (panes.length < 2) return null;
  const stacked = panes.length > 1 && panes.every((p) => (rects[p.id]?.x ?? 0) === 0);
  const header = splitBy && panes.some((p) => p.key) ? PANE_HEADER : 0;
  return (
    <>
      {panes.slice(1).map((p, i) => {
        const r = rects[p.id];
        const prev = panes[i];
        if (!r) return null;
        const embBoundary = p.kind === "embedding" || prev.kind === "embedding";
        const style = stacked ? { top: r.y - header - 4 } : { left: r.x - 4 };
        const equalise = () => {
          const st = store.getState();
          if (embBoundary) st.set({ split: { ...st.split, fraction: 0.38 } });
          else if (st.splitBy) st.set({ splitBy: { ...st.splitBy, fractions: null } });
        };
        return (
          <div
            key={p.id}
            className={`divider${stacked ? " h" : ""}`}
            style={style}
            title="drag to resize · double-click to equalise"
            onDoubleClick={equalise}
            onPointerDown={(e) => {
              if ((e.target as HTMLElement).closest("button")) return;
              drag.current = { k: i + 1, stacked };
              document.body.style.cursor = stacked ? "row-resize" : "col-resize";
              e.preventDefault();
            }}
          >
            {embBoundary && !stacked && (
              <button className="swap" onClick={() => store.getState().set({ split: { ...split, side: split.side === "left" ? "right" : "left" } })} title="swap sides">
                ⇄
              </button>
            )}
          </div>
        );
      })}
    </>
  );
}
