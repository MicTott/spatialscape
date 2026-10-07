import { describe, expect, it } from "vitest";
import { readUrl, serialize } from "../url/urlState";
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

describe("point size per view", () => {
  it("round-trips separate spatial and embedding multipliers", () => {
    const s = { ...store.getState(), pointScale: { spatial: 1.5, embedding: 0.5 } } as ViewerState;
    const q = new URLSearchParams(serialize(s));
    expect(q.get("ps")).toBe("1.50");
    expect(q.get("pse")).toBe("0.50");
    const g = globalThis as any;
    const saved = g.window;
    g.window = { location: { search: "?ps=1.5&pse=0.5" } };
    expect(readUrl().pointScale).toEqual({ spatial: 1.5, embedding: 0.5 });
    g.window = { location: { search: "?ps=2" } };
    expect(readUrl().pointScale).toEqual({ spatial: 2, embedding: 1 });
    g.window = saved;
  });
});

describe("scale and debug flags", () => {
  it("serialize only when set and read back", () => {
    const q = new URLSearchParams(serialize({ ...store.getState(), scalePerSample: true, debug: true } as ViewerState));
    expect(q.get("sps")).toBe("1");
    expect(q.get("debug")).toBe("1");
    expect(new URLSearchParams(serialize(store.getState())).has("sps")).toBe(false);
    const g = globalThis as any;
    const saved = g.window;
    g.window = { location: { search: "?sps=1&debug=1" } };
    const r = readUrl();
    expect(r.scalePerSample).toBe(true);
    expect(r.debug).toBe(true);
    g.window = saved;
  });
});
