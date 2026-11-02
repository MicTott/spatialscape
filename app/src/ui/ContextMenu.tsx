import { useEffect } from "react";
import { store, useViewer } from "../store/store";
import { clearPins, isPinned, pinSection, pinnedSections, unpinSection } from "../views/pins";

/** The canvas's right-click menu: pin the section under the pointer to the left or right window, unpin it, or
 *  clear every pin. Closes on a click anywhere, Esc, or scrolling. */
export function ContextMenu() {
  const menu = useViewer((s) => s.menu);
  const manifest = useViewer((s) => s.manifest);
  useEffect(() => {
    if (!menu) return;
    const close = (e: Event) => {
      if (e.target instanceof Element && e.target.closest(".ctx-menu")) return; // a click on the menu itself runs its item
      store.getState().set({ menu: null });
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close(e);
    window.addEventListener("pointerdown", close, { capture: true });
    window.addEventListener("wheel", close, { capture: true, passive: true });
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", close, { capture: true });
      window.removeEventListener("wheel", close, { capture: true });
      window.removeEventListener("keydown", onKey);
    };
  }, [menu]);
  if (!menu || !manifest) return null;
  const name = menu.sampleId ? (manifest.samples.find((s) => s.id === menu.sampleId)?.name ?? menu.sampleId) : null;
  const pins = pinnedSections();
  const item = (label: string, run: () => void, muted = false) => (
    <button key={label} className={muted ? "muted" : ""} onClick={run}>
      {label}
    </button>
  );
  const x = Math.min(menu.x, window.innerWidth - 190);
  const y = Math.min(menu.y, window.innerHeight - 150);
  return (
    <div className="ctx-menu" style={{ left: x, top: y }} role="menu" onContextMenu={(e) => e.preventDefault()}>
      {name && <div className="ctx-title">{name}</div>}
      {menu.sampleId && item("Pin left", () => pinSection(menu.sampleId!, "left"))}
      {menu.sampleId && item("Pin right", () => pinSection(menu.sampleId!, "right"))}
      {menu.sampleId && isPinned(menu.sampleId) && item("Unpin", () => unpinSection(menu.sampleId!))}
      {pins.length > 0 && item(pins.length === 1 ? "Clear the pin" : "Clear pins", clearPins, true)}
      {!menu.sampleId && !pins.length && <div className="ctx-title muted">right-click a section to pin it beside the others</div>}
    </div>
  );
}
