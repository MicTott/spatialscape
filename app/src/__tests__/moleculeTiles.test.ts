import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { decodeMoleculeTile } from "../data/moleculeTiles";
import { geneColors, pinColor } from "../views/molecules";
import { hexToRGB } from "../layers/lut";
import { GENE_TEX_WIDTH, geneTextureData, geneTextureRows } from "../layers/MoleculeLayer";

const dir = fileURLToPath(new URL("./fixtures/molecules/", import.meta.url));
const frame = new Uint8Array(readFileSync(dir + "tile.bin"));
const expected = JSON.parse(readFileSync(dir + "expected.json", "utf8")) as { origin: [number, number]; grid: number; n: number; gene: number[]; xy: number[][]; flags: number[] };

async function zstdDecode(f: Uint8Array): Promise<Uint8Array> {
  const Zstd = (await import("numcodecs/zstd")).default;
  return Zstd.fromConfig({ id: "zstd", level: 1 } as any).decode(f);
}

describe("molecule tiles written by the Python build", () => {
  it("decode to the same molecules, gene-major with run boundaries", async () => {
    const t = decodeMoleculeTile(await zstdDecode(frame), expected.origin, expected.grid);
    expect(t.n).toBe(expected.n);
    for (let i = 0; i < t.n; i++) {
      expect(t.gene[i]).toBe(expected.gene[i]);
      expect(t.flags[i]).toBe(expected.flags[i]);
      expect(t.positions[i * 2]).toBeCloseTo(expected.xy[i][0], 3);
      expect(t.positions[i * 2 + 1]).toBeCloseTo(expected.xy[i][1], 3);
    }
    for (let r = 0; r < t.runs.length; r++) {
      for (let m = t.runStarts[r]; m < t.runStarts[r + 1]; m++) expect(t.gene[m]).toBe(t.runs[r]);
      if (r) expect(t.runs[r]).toBeGreaterThan(t.runs[r - 1]);
    }
    expect(t.runStarts[t.runs.length]).toBe(t.n);
  });

  it("colours molecules like the view: the gene on screen, a blend's sets, or grey", () => {
    const genes = ["A", "B", "C"];
    const counts = [10, 30, 60];
    const g = geneColors(genes, { color: { kind: "gene", gene: "B" }, colormap: "viridis", geneMin: 0, moleculeGenes: [] });
    expect([...g.colors.subarray(0, 4)]).toEqual([0, 0, 0, 0]); // A hidden
    expect(g.colors[7]).toBe(255); // B drawn
    expect([...g.colors.subarray(4, 7)]).toEqual([250, 231, 33]); // the top of the viridis fit, as bytes
    expect(g.shares(counts)).toBeCloseTo(0.3);
    const b = geneColors(genes, { color: { kind: "blend", scheme: "yb", a: ["A"], b: ["B", "A"] }, colormap: "viridis", geneMin: 0, moleculeGenes: [] });
    expect(b.colors[3]).toBe(255);
    expect(b.colors[7]).toBe(255);
    expect(b.colors[11]).toBe(0);
    expect(b.shares(counts)).toBeCloseTo(0.4);
    const f = geneColors(genes, { color: { kind: "field", field: "cluster" }, colormap: "viridis", geneMin: 0, moleculeGenes: [] });
    expect([...f.colors].filter((_, i) => i % 4 === 3)).toEqual([255, 255, 255]);
    expect(f.shares(counts)).toBe(1);
    // pinned genes draw in their pin colours next to the gene on screen, and count towards the gate
    const p = geneColors(genes, { color: { kind: "gene", gene: "B" }, colormap: "viridis", geneMin: 0, moleculeGenes: ["C", "A"] });
    expect([...p.colors.subarray(8, 11)]).toEqual(hexToRGB(pinColor(0)));
    expect([...p.colors.subarray(0, 3)]).toEqual(hexToRGB(pinColor(1)));
    expect(p.shares(counts)).toBeCloseTo(1);
    const pf = geneColors(genes, { color: { kind: "field", field: "cluster" }, colormap: "viridis", geneMin: 0, moleculeGenes: ["C"] });
    expect([...pf.colors.subarray(8, 11)]).toEqual(hexToRGB(pinColor(0)));
    expect([...pf.colors.subarray(0, 3)]).toEqual([205, 208, 214]);
    // all genes: every gene its own colour, pins and the gene on screen still on top; the seventh pin gets a colour too
    const al = geneColors(genes, { color: { kind: "gene", gene: "B" }, colormap: "viridis", geneMin: 0, moleculeGenes: [], moleculeColors: "all" });
    expect(al.colors[3]).toBe(255);
    expect([...al.colors.subarray(0, 3)]).not.toEqual([...al.colors.subarray(8, 11)]);
    expect([...al.colors.subarray(4, 7)]).toEqual([250, 231, 33]);
    expect(al.shares(counts)).toBe(1);
    expect(pinColor(7)).toMatch(/^#[0-9a-f]{6}$/);
    expect(pinColor(7)).not.toBe(pinColor(8));
    // a chosen colour replaces the pin colour for that gene only
    const chosen = geneColors(["A", "B", "C"], { color: null, colormap: "viridis", geneMin: 0, moleculeGenes: ["B", "C"], moleculePinColors: { C: "#102030" } } as any);
    expect(Array.from(chosen.colors.subarray(8, 11))).toEqual([0x10, 0x20, 0x30]);
    expect(Array.from(chosen.colors.subarray(4, 7))).toEqual(hexToRGB(pinColor(0)));
  });
});

describe("gene colour texture", () => {
  it("lays a whole-transcriptome panel out in rows that fit the GPU", () => {
    const n = 18028;
    const colors = new Uint8Array(n * 4).map((_, i) => i % 251);
    const rows = geneTextureRows(n);
    expect(rows).toBe(Math.ceil(n / GENE_TEX_WIDTH));
    expect(GENE_TEX_WIDTH).toBeLessThanOrEqual(4096); // below every WebGL2 max texture size
    const data = geneTextureData(colors);
    expect(data.length).toBe(GENE_TEX_WIDTH * rows * 4);
    // gene g is texel (g mod width, g div width), the same arithmetic as the shader
    const g = 17_777;
    const texel = ((g % GENE_TEX_WIDTH) + Math.floor(g / GENE_TEX_WIDTH) * GENE_TEX_WIDTH) * 4;
    expect(Array.from(data.subarray(texel, texel + 4))).toEqual(Array.from(colors.subarray(g * 4, g * 4 + 4)));
    expect(geneTextureRows(1)).toBe(1);
    expect(geneTextureData(new Uint8Array([1, 2, 3, 4])).length).toBe(GENE_TEX_WIDTH * 4);
  });
});
