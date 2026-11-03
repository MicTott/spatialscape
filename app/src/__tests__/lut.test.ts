import { describe, expect, it } from "vitest";
import { categoryPalette, colormapLUT, hexToRGB } from "../layers/lut";

describe("lut", () => {
  it("builds 256-entry colormaps with increasing luminance for greys", () => {
    const g = colormapLUT("greys");
    expect(g.length).toBe(1024);
    expect(g[0]).toBeGreaterThan(g[255 * 4]);
    const v = colormapLUT("viridis");
    expect(v[3]).toBe(255);
    expect(v[0]).toBeLessThan(120); // dark purple start
    expect(v[255 * 4 + 1]).toBeGreaterThan(200); // yellow end
  });
  it("encodes hidden categories as alpha 0", () => {
    const p = categoryPalette(["#ff0000", "#00ff00"], [1]);
    expect([...p]).toEqual([255, 0, 0, 255, 0, 255, 0, 0]);
    expect(hexToRGB("#abc")).toEqual([170, 187, 204]);
  });
});


describe("shared colour scale per sample", () => {
  it("maps each sample's own code range onto the shared range, zero landing in one place for all", async () => {
    const { valueMapping } = await import("../layers/colorModule");
    // two non-negative samples, max 4 and 8, shared max 8: the smaller sample's full code reaches half way
    expect(valueMapping(0, 4, 8, false)).toEqual({ scale: 0.5, offset: 0, center: 0 });
    expect(valueMapping(0, 8, 8, false)).toEqual({ scale: 1, offset: 0, center: 0 });
    // a signed sample (-2..2) beside a non-negative one (0..4) on a shared scale -4..4:
    const signed = valueMapping(-2, 2, 4, true);
    expect(signed.center).toBe(0.5);
    expect(0.5 * signed.scale + signed.offset).toBeCloseTo(0.5, 9); // its zero (code 0.5) sits at the shared midpoint
    expect(1 * signed.scale + signed.offset).toBeCloseTo(0.75, 9); // its max (+2) at three quarters
    const plain = valueMapping(0, 4, 4, true);
    expect(plain.center).toBe(0);
    expect(0 * plain.scale + plain.offset).toBeCloseTo(0.5, 9); // its zero (code 0) also at the shared midpoint
    expect(1 * plain.scale + plain.offset).toBeCloseTo(1, 9); // its max (+4) at the top
    // per-sample scaling (shared max 0): codes pass through
    expect(valueMapping(-2, 2, 0, true)).toEqual({ scale: 1, offset: 0, center: 0.5 });
  });
});
