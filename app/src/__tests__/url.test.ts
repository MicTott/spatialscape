import { describe, expect, it } from "vitest";
import { serialize } from "../url/urlState";
import { store, type ViewerState } from "../store/store";

describe("url state", () => {
  it("serializes non-default state compactly", () => {
    const s = {
      ...store.getState(),
      datasetUrl: "http://x/y",
      color: { kind: "gene", gene: "GAD1" },
      filter: { kind: "field", field: "total_counts", range: [0.25, 1] },
      hiddenCategories: { domain: [1, 3] },
      focus: "s1",
      viewState: { target: [100.4, 200.6, 0] as [number, number, number], zoom: -2.345 },
    } as ViewerState;
    const q = new URLSearchParams(serialize(s));
    expect(q.get("d")).toBe("http://x/y");
    expect(q.get("c")).toBe("g:GAD1");
    expect(q.get("fl")).toBe("f:total_counts:0.250,1.000");
    expect(q.get("h")).toBe("domain:1.3");
    expect(q.get("s")).toBe("s1");
    expect(q.get("v")).toBe("100,201,-2.35");
    expect(q.has("cm")).toBe(false);
  });
});
