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
    expect(q.has("sb")).toBe(false);
    expect(q.has("ms")).toBe(false);
  });

  it("round-trips the group split, its cameras and the scale lock", () => {
    const s = {
      ...store.getState(),
      datasetUrl: "http://x/y",
      splitBy: { key: "condition", groups: ["stress", "control"], fractions: [0.4, 0.6] },
      paneCameras: [
        { target: [10.2, 20.7, 0] as [number, number, number], zoom: -1.234 },
        { target: [30, 40, 0] as [number, number, number], zoom: 0.5 },
      ],
      matchScale: false,
    } as ViewerState;
    const qs = serialize(s);
    const q = new URLSearchParams(qs);
    expect(q.get("sb")).toBe("condition");
    expect(q.get("sg")).toBe("stress,control");
    expect(q.get("sf")).toBe("0.400,0.600");
    expect(q.get("pv")).toBe("10,21,-1.23;30,40,0.50");
    expect(q.get("ms")).toBe("0");
    const g = globalThis as any;
    const saved = g.window;
    g.window = { location: { search: `?${qs}` } };
    const back = readUrl();
    expect(back.splitBy).toEqual({ key: "condition", groups: ["stress", "control"], fractions: [0.4, 0.6] });
    expect(back.paneCameras).toEqual([
      { target: [10, 21, 0], zoom: -1.23 },
      { target: [30, 40, 0], zoom: 0.5 },
    ]);
    expect(back.matchScale).toBe(false);
    g.window = { location: { search: "?sb=condition" } };
    const plain = readUrl();
    expect(plain.splitBy).toEqual({ key: "condition", groups: null, fractions: null });
    expect(plain.matchScale).toBeUndefined(); // the default stays on
    g.window = saved;
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

  it("keeps image visibility and opacity apart and quotes feature ids that contain colons", () => {
    const s = { ...store.getState(), datasetUrl: "http://x/y", showImages: false, imageOpacity: 0.6, filter: { kind: "gene", gene: "peak: chr1:100-200", range: [0.1, 1] } } as ViewerState;
    const q = new URLSearchParams(serialize(s));
    expect(q.get("imgs")).toBe("0");
    expect(q.get("img")).toBe("0.60");
    expect(q.get("fl")).toBe("g:peak: chr1:100-200:0.100,1.000");
  });
});
