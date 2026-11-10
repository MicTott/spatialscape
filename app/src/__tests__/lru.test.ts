import { describe, expect, it } from "vitest";
import { ByteLRU } from "../data/lru";

const f32 = (n: number) => new Float32Array(n); // 4 bytes a value

describe("ByteLRU", () => {
  it("evicts the least recently used entries once over its byte budget", () => {
    const lru = new ByteLRU<Float32Array>(100);
    lru.set("a", f32(10)); // 40 bytes
    lru.set("b", f32(10)); // 80
    lru.set("c", f32(10)); // 120: a goes
    expect(lru.has("a")).toBe(false);
    expect(lru.has("b")).toBe(true);
    expect(lru.has("c")).toBe(true);
    expect(lru.byteSize).toBe(80);
    expect(lru.size).toBe(2);
  });
  it("a get refreshes recency", () => {
    const lru = new ByteLRU<Float32Array>(100);
    lru.set("a", f32(10));
    lru.set("b", f32(10));
    lru.get("a");
    lru.set("c", f32(10)); // b is now the oldest
    expect(lru.has("a")).toBe(true);
    expect(lru.has("b")).toBe(false);
  });
  it("keeps one entry even when it alone is over budget, and replaces a key's bytes on set", () => {
    const lru = new ByteLRU<Float32Array>(16);
    lru.set("big", f32(100));
    expect(lru.size).toBe(1);
    expect(lru.byteSize).toBe(400);
    lru.set("big", f32(2));
    expect(lru.byteSize).toBe(8);
    lru.delete("big");
    expect(lru.size).toBe(0);
    expect(lru.byteSize).toBe(0);
    expect(lru.get("big")).toBeUndefined();
  });
});
