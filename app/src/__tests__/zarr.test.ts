/** Reads one gene from the CLI-built synthetic bundle through zarrita (sharded zarr v3 + zstd). */
import { describe, expect, it } from "vitest";
import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import * as zarr from "zarrita";
import { FileSystemStore } from "@zarrita/storage";

const bundle = resolve(__dirname, "../../../examples/synthetic");

describe.skipIf(!existsSync(resolve(bundle, "manifest.json")))("zarrita reads the bundle", () => {
  it("fetches a single gene column and gmax", async () => {
    const store = new FileSystemStore(resolve(bundle, "samples/sampleA/expr.zarr"));
    const root = zarr.root(store);
    const u8 = await zarr.open.v3(root.resolve("u8"), { kind: "array" });
    const manifest = JSON.parse(readFileSync(resolve(bundle, "manifest.json"), "utf8"));
    const s = manifest.samples.find((x: any) => x.id === "sampleA");
    expect(u8.shape).toEqual([s.nGenes, s.nObs]);
    const col = await zarr.get(u8 as zarr.Array<"uint8">, [3, null]);
    expect(col.data.length).toBe(s.nObs);
    expect(Math.max(...(col.data as Uint8Array))).toBe(255); // scaled to per-gene max
    const gmax = await zarr.get((await zarr.open.v3(root.resolve("gmax"), { kind: "array" })) as zarr.Array<"float32">);
    expect(gmax.data.length).toBe(s.nGenes);
  });
});
