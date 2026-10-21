import { describe, expect, it } from "vitest";
import type { Manifest, Sample } from "../data/manifest";
import { computePanes, dragFractions, groupFractions, MIN_PANE_FRACTION, PANE_HEADER, paneGroups, paneRects, presentLevels, splitKeys, unassignedSamples } from "../views/panes";

const mk = (id: string, kind: "spatial" | "embedding", meta?: Record<string, string>): Sample => ({
  id,
  name: id,
  platform: kind === "embedding" ? "snrnaseq" : "visium",
  kind,
  meta,
  nObs: 10,
  nGenes: 5,
  bbox: [0, 0, 100, 100],
  toDataset: [1, 0, 0, 0, 1, 0, 0, 0, 1],
  pointRadius: 5,
  expr: { kind: "u8", sharded: true, shardGenes: 512 },
  hasF16: false,
  fields: [],
  images: [],
  idBlock: 65536,
});

const manifest = (samples: Sample[], meta?: Manifest["meta"]): Manifest =>
  ({
    formatVersion: 1,
    id: "t",
    name: "t",
    defaultColor: { kind: "gene", gene: "G" },
    layout: { mode: "grid", gutterFraction: 0.1, order: samples.map((s) => s.id) },
    colormaps: [],
    vocabularies: {},
    fields: [],
    samples,
    meta,
  }) as Manifest;

const emb = { on: true, side: "left" as const, fraction: 0.38 };
const two = manifest(
  [mk("a", "spatial", { condition: "control", mouse: "m1" }), mk("b", "spatial", { condition: "stress", mouse: "m2" }), mk("c", "spatial", { condition: "control", mouse: "m3" }), mk("u", "embedding")],
  [{ id: "condition", name: "Condition", levels: ["control", "stress"] }],
);

describe("panes", () => {
  it("lists the keys that split the sections and their levels in declared order", () => {
    expect(splitKeys(two)).toEqual([
      { id: "condition", name: "Condition", levels: ["control", "stress"] },
      { id: "mouse", name: "mouse", levels: ["m1", "m2", "m3"] },
    ]);
    expect(presentLevels(manifest([mk("a", "spatial", { k: "y" }), mk("b", "spatial", { k: "x" })], [{ id: "k", name: "K", levels: ["x", "y", "z"] }]), "k")).toEqual(["x", "y"]); // z has no section
  });

  it("makes one pane per group plus the embedding pane at its side; none when the key is unknown", () => {
    const panes = computePanes(two, { key: "condition", groups: null, fractions: null }, emb);
    expect(panes.map((p) => [p.id, p.kind, p.group?.value ?? null, p.samples.map((s) => s.id)])).toEqual([
      ["embedding", "embedding", null, ["u"]],
      ["g0", "spatial", "control", ["a", "c"]],
      ["g1", "spatial", "stress", ["b"]],
    ]);
    const right = computePanes(two, { key: "condition", groups: null, fractions: null }, { ...emb, side: "right" });
    expect(right.map((p) => p.id)).toEqual(["g0", "g1", "embedding"]);
    expect(computePanes(two, { key: "nope", groups: null, fractions: null }, emb).map((p) => p.id)).toEqual(["embedding", "spatial"]);
    expect(computePanes(two, null, { ...emb, on: false }).map((p) => p.id)).toEqual(["spatial"]);
  });

  it("shows at most three groups, the chosen ones when they exist, and reports the sections left out", () => {
    const m = manifest(["a", "b", "c", "d", "e"].map((id, i) => mk(id, "spatial", i < 4 ? { site: `s${i}` } : undefined)));
    expect(paneGroups(m, { key: "site", groups: null, fractions: null })).toEqual(["s0", "s1", "s2"]);
    expect(paneGroups(m, { key: "site", groups: ["s3", "s1", "gone"], fractions: null })).toEqual(["s3", "s1"]);
    expect(unassignedSamples(m, { key: "site", groups: null, fractions: null }).map((s) => s.id)).toEqual(["d", "e"]); // s3 not shown, e has no site
    expect(unassignedSamples(m, null)).toEqual([]);
  });

  it("lays panes out side by side with a header strip, or stacked, honouring the fractions", () => {
    const panes = computePanes(two, { key: "condition", groups: null, fractions: null }, emb);
    const split = { key: "condition", groups: null, fractions: null };
    const r = paneRects(panes, 1000, 600, split, emb, false);
    expect(r.embedding).toEqual({ x: 0, y: PANE_HEADER, w: 380, h: 600 - PANE_HEADER });
    expect(r.g0).toEqual({ x: 380, y: PANE_HEADER, w: 310, h: 600 - PANE_HEADER });
    expect(r.g1).toEqual({ x: 690, y: PANE_HEADER, w: 310, h: 600 - PANE_HEADER });
    const dragged = paneRects(panes, 1000, 600, { ...split, fractions: [0.25, 0.75] }, emb, false);
    expect([dragged.g0.w, dragged.g1.w]).toEqual([155, 465]);
    const stacked = paneRects(panes, 500, 900, split, emb, true);
    expect(stacked.embedding).toEqual({ x: 0, y: PANE_HEADER, w: 500, h: 342 - PANE_HEADER });
    expect(stacked.g0.y).toBe(342 + PANE_HEADER);
    expect(stacked.g1.y + stacked.g1.h).toBe(900);
    const single = paneRects(computePanes(two, null, { ...emb, on: false }), 800, 500, null, emb, false);
    expect(single.spatial).toEqual({ x: 0, y: 0, w: 800, h: 500 }); // no header without a split
  });

  it("keeps dragged fractions only while every pane stays wide enough", () => {
    expect(groupFractions(3, null)).toEqual([1 / 3, 1 / 3, 1 / 3]);
    expect(groupFractions(2, [1, 3])).toEqual([0.25, 0.75]);
    expect(groupFractions(2, [0.02, 0.98])).toEqual([0.5, 0.5]);
    const d = dragFractions([0.5, 0.5], 1, 0.7);
    expect(d[0]).toBeCloseTo(0.7);
    expect(d[1]).toBeCloseTo(0.3);
    const clamped = dragFractions([1 / 3, 1 / 3, 1 / 3], 2, 0.99);
    expect(clamped[2]).toBeCloseTo(MIN_PANE_FRACTION);
    expect(clamped[0]).toBeCloseTo(1 / 3); // only the two neighbours move
  });
});
