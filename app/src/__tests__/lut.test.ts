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
