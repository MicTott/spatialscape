import { describe, expect, it } from "vitest";
import { cardGroups, cardPills, type RegistryEntry } from "../ui/registry";

const card = (id: string, extra: Partial<RegistryEntry> = {}): RegistryEntry => ({ id, name: id, url: id, ...extra });

describe("gallery groups", () => {
  it("is one section without a heading when no card names a group", () => {
    const g = cardGroups([card("a"), card("b")]);
    expect(g).toEqual([{ name: null, items: [card("a"), card("b")] }]);
  });
  it("keeps groups in order of first appearance and puts ungrouped cards last", () => {
    const g = cardGroups([card("a", { group: "Other" }), card("b"), card("c", { group: "Main" }), card("d", { group: "Other" })]);
    expect(g.map((x) => [x.name, x.items.map((d) => d.id)])).toEqual([
      ["Other", ["a", "d"]],
      ["Main", ["c"]],
      [null, ["b"]],
    ]);
  });
  it("has no empty trailing section when every card is grouped", () => {
    expect(cardGroups([card("a", { group: "Main" })]).map((x) => x.name)).toEqual(["Main"]);
  });
});

describe("card pills", () => {
  const label = (p: string) => ({ visium: "Visium", merfish: "MERFISH", other: "Other" })[p] ?? p;
  it("lists platforms by name, then tags, once each", () => {
    expect(cardPills(card("a", { platforms: ["visium"], tags: ["visium", "human cortex"] }), label)).toEqual(["Visium", "human cortex"]);
  });
  it("leaves out the platform `other`, which says nothing", () => {
    expect(cardPills(card("a", { platforms: ["other"], tags: ["CosMx"] }), label)).toEqual(["CosMx"]);
    expect(cardPills(card("a", { platforms: ["other"] }), label)).toEqual([]);
  });
});
