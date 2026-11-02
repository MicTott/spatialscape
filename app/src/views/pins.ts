/** Pin left / pin right: two (or three) sections side by side, each in its own pane. Implemented as the built-in
 *  "section" split, so cameras, point sizes, pane headers, match scale and the URL (`sb=section&sg=a,b`) come for
 *  free. The slot order is the pane order: left first. */
import { store } from "../store/store";
import { MAX_GROUP_PANES, SECTION_KEY } from "./panes";

export function pinnedSections(): string[] {
  const split = store.getState().splitBy;
  return split?.key === SECTION_KEY ? [...(split.groups ?? [])] : [];
}

export function isPinned(id: string): boolean {
  return pinnedSections().includes(id);
}

/** Put a section in the left or right slot; the other slot keeps its section, and a section pinned twice moves. */
export function pinSection(id: string, side: "left" | "right"): void {
  const others = pinnedSections().filter((p) => p !== id);
  const groups = side === "left" ? [id, ...others].slice(0, MAX_GROUP_PANES) : [...others.slice(0, MAX_GROUP_PANES - 1), id];
  store.getState().set({ splitBy: { key: SECTION_KEY, groups, fractions: null }, menu: null });
}

export function unpinSection(id: string): void {
  const pins = pinnedSections().filter((p) => p !== id);
  store.getState().set({ splitBy: pins.length ? { key: SECTION_KEY, groups: pins, fractions: null } : null, menu: null });
}

export function clearPins(): void {
  if (pinnedSections().length) store.getState().set({ splitBy: null, menu: null });
}
