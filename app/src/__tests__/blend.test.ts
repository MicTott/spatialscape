import { describe, expect, it } from "vitest";
import { blendScore } from "../views/blend";

describe("blend score", () => {
  it("averages dequantized expression and maps against the shared max", () => {
    // gene A max 4 (u8 255 = 4.0), gene B max 1 (u8 255 = 1.0)
    const a = new Uint8Array([255, 0, 128]);
    const b = new Uint8Array([255, 255, 0]);
    const out = blendScore([a, b], [4, 1], 3, 4);
    // cell0: mean(4, 1) = 2.5 -> 2.5/4*255 = 159 ; cell1: mean(0, 1) = 0.5 -> 32 ; cell2: mean(2.008, 0) = 1.004 -> 64
    expect(Array.from(out)).toEqual([159, 32, 64]);
  });
  it("is empty without genes or a scale", () => {
    expect(Array.from(blendScore([], [], 2, 1))).toEqual([0, 0]);
    expect(Array.from(blendScore([new Uint8Array([255])], [1], 1, 0))).toEqual([0]);
  });
});
