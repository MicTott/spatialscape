import { describe, expect, it } from "vitest";
import { binFor, chevronPositions, covers, formatLocus, formatSpan, niceStep, packLanes, padGene, parseLocus, tickLabel, ticks, windowFor } from "../genome/model";
import { rasterize } from "../genome/raster";

const sizes = new Map([
  ["chr1", 1000],
  ["chr11", 135_086_622],
]);

describe("loci", () => {
  it("parses browser-style loci, bare chromosome names and single positions", () => {
    expect(parseLocus("chr11:60,405,809-60,512,181", sizes)).toEqual({ chrom: "chr11", start: 60_405_808, end: 60_512_181 });
    expect(parseLocus("11:100-200", sizes)).toEqual({ chrom: "chr11", start: 99, end: 200 });
    expect(parseLocus("chr1", sizes)).toEqual({ chrom: "chr1", start: 0, end: 1000 });
    expect(parseLocus("chr1:500", sizes)).toEqual({ chrom: "chr1", start: 0, end: 1000 }); // ±5 kb, clamped to the chromosome
    expect(parseLocus("chrZ:1-2", sizes)).toBeNull();
    expect(parseLocus("MS4A1", sizes)).toBeNull();
  });
  it("prints 1-based inclusive coordinates and short spans", () => {
    expect(formatLocus({ chrom: "chr11", start: 60_405_808, end: 60_512_181 })).toBe("chr11:60,405,809-60,512,181");
    expect(formatSpan(106_373)).toBe("106 kb");
    expect(formatSpan(1_500_000)).toBe("1.5 Mb");
    expect(formatSpan(850)).toBe("850 bp");
  });
});

describe("axis", () => {
  it("picks 1-2-2.5-5 steps at least 90 px apart", () => {
    expect(niceStep(106_373, 1500)).toBe(10_000);
    expect(niceStep(1000, 1500)).toBe(100);
    expect(niceStep(250_000_000, 1500)).toBe(20_000_000);
  });
  it("labels ticks in the unit of the step", () => {
    expect(tickLabel(60_410_000, 10_000)).toBe("60,410 kb");
    expect(tickLabel(60_412_500, 2_500)).toBe("60,412.5 kb");
    expect(tickLabel(20_000_000, 20_000_000)).toBe("20 Mb");
    expect(tickLabel(1250, 250)).toBe("1,250");
    expect(ticks(95, 321, 100)).toEqual([100, 200, 300]);
  });
});

describe("bins and windows", () => {
  it("doubles the track bin until a bin is at least a pixel wide", () => {
    expect(binFor(70, 25)).toBe(100);
    expect(binFor(10, 25)).toBe(25);
    expect(binFor(90_000, 25)).toBe(102_400);
  });
  it("fetches one span each side, aligned to the bin and inside the chromosome", () => {
    expect(windowFor(1000, 2000, 100, 10_000)).toEqual({ start: 0, end: 3000 });
    expect(windowFor(9000, 9500, 100, 9950)).toEqual({ start: 8500, end: 9950 });
  });
  it("reuses a cache that covers the view at a bin no coarser than twice the wanted one", () => {
    const c = { chrom: "chr1", bin: 100, start: 0, end: 3000 };
    expect(covers(c, "chr1", 1000, 2000, 100)).toBe(true);
    expect(covers(c, "chr1", 1000, 2000, 50)).toBe(true);
    expect(covers(c, "chr1", 1000, 2000, 25)).toBe(false);
    expect(covers(c, "chr1", 2500, 3500, 100)).toBe(false);
    expect(covers(c, "chr2", 1000, 2000, 100)).toBe(false);
  });
  it("rasterizes spans into area-weighted bins, gaps as zero", () => {
    expect([...rasterize([0, 150, 400], [100, 250, 450], [1, 2, 4], 0, 100, 5)]).toEqual([1, 1, 1, 0, 2]);
  });
});

describe("genes", () => {
  const g = (name: string, start: number, end: number) => ({ name, start, end });
  it("packs overlapping genes into lanes and drops what fits nowhere", () => {
    const lanes = packLanes([g("A", 0, 100), g("B", 50, 150), g("C", 120, 200), g("D", 60, 70)], 1, 2, null, 0);
    expect(lanes.map((l) => l.map((x) => x.name))).toEqual([["A", "C"], ["B"]]);
  });
  it("reserves room for centred labels", () => {
    expect(packLanes([g("LONGNAME", 100, 110), g("X", 125, 135)], 1, 3, (n) => n.length * 6, 0)).toHaveLength(2);
    expect(packLanes([g("LONGNAME", 100, 110), g("X", 125, 135)], 1, 3, null, 0)).toHaveLength(1);
  });
  it("places chevrons along the visible introns, none when there is no room", () => {
    const gene = { name: "G", strand: 1, start: 0, end: 1000, exonStarts: [0, 900], exonEnds: [100, 1000] };
    const xs = chevronPositions(gene, 1, 0, 1000, 100);
    expect(xs).toHaveLength(8);
    expect(xs[0]).toBeGreaterThan(100);
    expect(xs[7]).toBeLessThan(900);
    expect(chevronPositions(gene, 0.01, 0, 1000, 100)).toEqual([]);
  });
  it("pads a gene by 1.5 lengths, at least 5 kb", () => {
    expect(padGene(10_000, 12_000, 1e6)).toEqual({ start: 5000, end: 17_000 });
    expect(padGene(100_000, 110_000, 1e6)).toEqual({ start: 85_000, end: 125_000 });
  });
});
