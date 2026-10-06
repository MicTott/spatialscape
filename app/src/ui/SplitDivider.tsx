import { useEffect, useRef } from "react";
import { store, useViewer } from "../store/store";

/** Draggable divider between the embedding and spatial views, with a swap button. */
export function SplitDivider({ mapRef }: { mapRef: React.RefObject<HTMLDivElement | null> }) {
  const manifest = useViewer((s) => s.manifest);
  const split = useViewer((s) => s.split);
  const dragging = useRef(false);
  const hasEmbedding = !!manifest?.samples.some((s) => s.kind === "embedding");
  const hasSpatial = !!manifest?.samples.some((s) => s.kind !== "embedding");

  useEffect(() => {
    const move = (e: PointerEvent) => {
      if (!dragging.current || !mapRef.current) return;
      const r = mapRef.current.getBoundingClientRect();
      const x = (e.clientX - r.left) / r.width;
      const frac = split.side === "left" ? x : 1 - x;
      store.getState().set({ split: { ...store.getState().split, fraction: Math.min(0.8, Math.max(0.2, frac)) } });
    };
    const up = () => {
      dragging.current = false;
      document.body.style.cursor = "";
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    return () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
  }, [split.side, mapRef]);

  if (!hasEmbedding || !hasSpatial || !split.on) return null;
  const left = split.side === "left" ? split.fraction : 1 - split.fraction;
  return (
    <div
      className="divider"
      style={{ left: `calc(${(left * 100).toFixed(2)}% - 4px)` }}
      onPointerDown={(e) => {
        dragging.current = true;
        document.body.style.cursor = "col-resize";
        e.preventDefault();
      }}
    >
      <button
        className="swap"
        title="swap sides"
        onPointerDown={(e) => e.stopPropagation()}
        onClick={() => store.getState().set({ split: { ...split, side: split.side === "left" ? "right" : "left" } })}
      >
        ⇄
      </button>
    </div>
  );
}
