/** Pin left / pin right: the canvas as two windows. Pinning a section puts it in the left or right window; the
 *  grid of every section keeps the other window until a second section is pinned there. Unpinning gives the
 *  window back to the grid (and, when no pin is left, to the embedding pane). */
import { store } from "../store/store";
import type { Pins } from "../store/store";
import { anyPinned, bothPinned, NO_PINS } from "./panes";

export type Side = "left" | "right";

export function pinnedSections(): string[] {
  return store.getState().pins.filter((p): p is string => !!p);
}

export function isPinned(id: string): boolean {
  return store.getState().pins.includes(id);
}

/** The window the next pin goes to: the left one first, then the right; none when both hold a section. */
export function nextPinSide(pins: Pins): Side | null {
  return !pins[0] ? "left" : !pins[1] ? "right" : null;
}

/** Put a section in a window; a section already in the other window moves. With the pin tool armed, the tool
 *  stays armed while a window is free and returns to pan once both are pinned. */
export function pinSection(id: string, side: Side): void {
  const s = store.getState();
  const pins: Pins = [...s.pins];
  const slot = side === "left" ? 0 : 1;
  if (pins[1 - slot] === id) pins[1 - slot] = null;
  pins[slot] = id;
  s.set({ pins, menu: null, pinHover: null, tool: s.tool === "pin" && !bothPinned(pins) ? "pin" : s.tool === "pin" ? "pan" : s.tool });
}

export function unpinSection(id: string): void {
  const s = store.getState();
  if (!s.pins.includes(id)) return;
  s.set({ pins: s.pins.map((p) => (p === id ? null : p)) as Pins, menu: null });
}

export function clearPins(): void {
  const s = store.getState();
  if (anyPinned(s.pins)) s.set({ pins: NO_PINS, menu: null, tool: s.tool === "pin" ? "pan" : s.tool });
  else if (s.menu) s.set({ menu: null });
}

/** What the pin tool says next to the pointer. */
export function pinHint(pins: Pins, sectionName: string | null): string {
  const side = nextPinSide(pins);
  if (!side) return "both windows hold a pinned section: unpin one first";
  return sectionName ? `pin ${sectionName} on the ${side}` : `click a section to pin it on the ${side}`;
}
