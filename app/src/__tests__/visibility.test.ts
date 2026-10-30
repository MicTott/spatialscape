import { describe, expect, it } from "vitest";
import { csvLine } from "../views/types";
import { cellTest } from "../views/visibility";

describe("what a cell you can see is", () => {
  const cat = Uint16Array.from([0, 1, 2, 1]);
  const filter = Uint8Array.from([0, 100, 200, 255]);
  it("hides nothing when nothing is hidden", () => {
    expect(cellTest({ filter: { state: "none" } })).toBeNull();
    expect(cellTest({ hidden: new Set(), cat, filter: { state: "loading" } })).toBeNull();
  });
  it("applies hidden categories, the filter's byte range and hidden zeros together", () => {
    const t = cellTest({ hidden: new Set([2]), cat, filter: { state: "ok", values: filter, lo: 50, hi: 255, scale: 255 }, zeros: Uint8Array.from([5, 0, 5, 5]) })!;
    expect([0, 1, 2, 3].map(t)).toEqual([false, false, false, true]); // 0: filter; 1: zero; 2: hidden category; 3: shown
  });
  it("shows no cell of a sample that does not measure the filter's channel", () => {
    const t = cellTest({ filter: { state: "unmeasured" } })!;
    expect([0, 1].map(t)).toEqual([false, false]);
  });
});

describe("csv lines", () => {
  it("quotes commas, quotes and line breaks", () => {
    expect(csvLine(["s1", "cell 7", 7])).toBe("s1,cell 7,7");
    expect(csvLine(["a,b", 'say "hi"', "two\nlines"])).toBe('"a,b","say ""hi""","two\nlines"');
  });
});
