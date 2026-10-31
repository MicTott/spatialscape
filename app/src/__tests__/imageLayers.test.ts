import { describe, expect, it } from "vitest";
import { Matrix4 } from "@math.gl/core";
import { channelNames, imageLayer, type ImageHandle } from "../layers/imageLayers";
import type { SampleImage } from "../data/manifest";

const img: SampleImage = {
  id: "morphology",
  name: "Morphology",
  path: "morphology.ome.zarr",
  kind: "multichannel",
  pixelSize: 1.7,
  translate: [0, 0],
  size: [4269, 2989],
  channels: [
    { name: "DAPI", color: "#4c8dff", window: [1, 6548] },
    { name: "18S", color: "#ff4fd8", window: [1, 7533] },
  ],
  defaultOpacity: 1,
} as SampleImage;
const handle: ImageHandle = { data: [{ shape: [2, 2989, 4269] }, { shape: [2, 1494, 2134] }], channels: 2, dtype: "Uint16", labels: ["c", "y", "x"] };

describe("image layer props", () => {
  it("keeps the props Viv keys its tiles on when a rebuild changes nothing", () => {
    // every camera frame rebuilds the layers; a new selections array made Viv refetch every visible tile
    const both = ["DAPI", "18S"];
    const a = imageLayer("img-a", img, handle, new Matrix4().translate([5, 0, 0]), 1, true, both, { viewId: "spatial" });
    const b = imageLayer("img-a", img, handle, new Matrix4().translate([5, 0, 0]), 0.5, true, both, { viewId: "spatial" });
    for (const k of ["selections", "contrastLimits", "colors", "channelsVisible", "modelMatrix"] as const) expect(b.props[k]).toBe(a.props[k]);
    expect(b.props.opacity).toBe(0.5);
    const moved = imageLayer("img-a", img, handle, new Matrix4().translate([9, 0, 0]), 1, true, both, { viewId: "spatial" });
    expect(moved.props.modelMatrix).not.toBe(a.props.modelMatrix);
    expect(moved.props.selections).toBe(a.props.selections);
  });

  it("fetches only the drawn channels, in the order chosen, and keeps the layer invisible when none of its channels is drawn", () => {
    const one = imageLayer("img-b", img, handle, new Matrix4(), 1, true, ["18S"]);
    expect(one.props.channelsVisible).toEqual([true]);
    expect(one.props.selections).toEqual([{ c: 1 }]);
    const swapped = imageLayer("img-b", img, handle, new Matrix4(), 1, true, ["18S", "DAPI"]);
    expect(swapped.props.selections).toEqual([{ c: 1 }, { c: 0 }]);
    const none = imageLayer("img-b", img, handle, new Matrix4(), 1, true, ["CD3"]); // a channel this image lacks
    expect(none.props.visible).toBe(false);
    expect(imageLayer("img-b", img, handle, new Matrix4(), 1, false, ["DAPI"]).props.visible).toBe(false);
    expect(channelNames({ ...img, channels: null }, 8)).toEqual(Array.from({ length: 8 }, (_, i) => `channel ${i + 1}`));
  });
});

describe("drawn channels", () => {
  it("are the chosen ones in order, else the dataset's first six minus an old link's hidden ones", async () => {
    const { drawnChannels, MAX_DRAWN } = await import("../layers/imageLayers");
    const names = Array.from({ length: 56 }, (_, i) => (i === 0 ? "DAPI" : `M${i}`));
    expect(drawnChannels(names, null, [])).toEqual(names.slice(0, MAX_DRAWN));
    expect(drawnChannels(names, null, ["M2", "M3"])).toEqual(["DAPI", "M1", "M4", "M5", "M6", "M7"]);
    expect(drawnChannels(names, ["M40", "DAPI", "nope"], [])).toEqual(["M40", "DAPI"]); // order kept, unknown names dropped
    expect(drawnChannels(names, names.slice(10, 20), [])).toHaveLength(MAX_DRAWN);
    expect(drawnChannels(["DAPI", "CD3"], null, [])).toEqual(["DAPI", "CD3"]);
  });
});
