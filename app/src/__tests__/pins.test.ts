import { beforeEach, describe, expect, it } from "vitest";
import { store } from "../store/store";
import { clearPins, pinSection, pinnedSections, unpinSection } from "../views/pins";
import { SECTION_KEY } from "../views/panes";

describe("pinned sections", () => {
  beforeEach(() => store.getState().set({ splitBy: null, menu: null }));

  it("pins the first section alone, the next one beside it, and keeps the slot order left to right", () => {
    pinSection("a", "left");
    expect(pinnedSections()).toEqual(["a"]);
    pinSection("b", "right");
    expect(store.getState().splitBy).toEqual({ key: SECTION_KEY, groups: ["a", "b"], fractions: null });
    pinSection("c", "left");
    expect(pinnedSections()).toEqual(["c", "a", "b"]);
  });

  it("moves a section already pinned instead of pinning it twice, and replaces the far slot when full", () => {
    pinSection("a", "left");
    pinSection("b", "right");
    pinSection("b", "left");
    expect(pinnedSections()).toEqual(["b", "a"]);
    pinSection("c", "right");
    pinSection("d", "right");
    expect(pinnedSections()).toEqual(["b", "a", "d"]);
  });

  it("unpinning the last section ends the split, and clearing removes every pin", () => {
    pinSection("a", "left");
    pinSection("b", "right");
    unpinSection("a");
    expect(pinnedSections()).toEqual(["b"]);
    unpinSection("b");
    expect(store.getState().splitBy).toBeNull();
    pinSection("a", "right");
    clearPins();
    expect(store.getState().splitBy).toBeNull();
    expect(store.getState().menu).toBeNull();
  });
});
