import { beforeEach, describe, expect, it } from "vitest";
import { store } from "../store/store";
import { clearPins, nextPinSide, pinHint, pinSection, pinnedSections, unpinSection } from "../views/pins";

describe("pinned windows", () => {
  beforeEach(() => store.getState().set({ pins: [null, null], menu: null, tool: "pan" }));

  it("the left window first, then the right; a section pinned again moves; the slots are the pane order", () => {
    expect(nextPinSide([null, null])).toBe("left");
    pinSection("a", "left");
    expect(store.getState().pins).toEqual(["a", null]);
    expect(nextPinSide(store.getState().pins)).toBe("right");
    pinSection("b", "right");
    expect(store.getState().pins).toEqual(["a", "b"]);
    expect(nextPinSide(store.getState().pins)).toBeNull();
    pinSection("b", "left");
    expect(store.getState().pins).toEqual(["b", null]);
    pinSection("c", "right");
    pinSection("d", "right");
    expect(pinnedSections()).toEqual(["b", "d"]);
  });

  it("unpinning frees that window; clearing frees both and disarms the pin tool", () => {
    pinSection("a", "left");
    pinSection("b", "right");
    unpinSection("a");
    expect(store.getState().pins).toEqual([null, "b"]);
    store.getState().set({ tool: "pin" });
    clearPins();
    expect(store.getState().pins).toEqual([null, null]);
    expect(store.getState().tool).toBe("pan");
  });

  it("the pin tool stays armed while a window is free and returns to pan once both are pinned", () => {
    store.getState().set({ tool: "pin" });
    pinSection("a", "left");
    expect(store.getState().tool).toBe("pin");
    pinSection("b", "right");
    expect(store.getState().tool).toBe("pan");
  });

  it("says what the next click does", () => {
    expect(pinHint([null, null], null)).toBe("click a section to pin it on the left");
    expect(pinHint(["a", null], "Br6423 (Visium)")).toBe("pin Br6423 (Visium) on the right");
    expect(pinHint(["a", "b"], null)).toMatch(/unpin one first/);
  });
});
