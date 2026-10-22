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
    const a = imageLayer("img-a", img, handle, new Matrix4().translate([5, 0, 0]), 1, true, new Set(), { viewId: "spatial" });
    const b = imageLayer("img-a", img, handle, new Matrix4().translate([5, 0, 0]), 0.5, true, new Set(), { viewId: "spatial" });
    for (const k of ["selections", "contrastLimits", "colors", "channelsVisible", "modelMatrix"] as const) expect(b.props[k]).toBe(a.props[k]);
    expect(b.props.opacity).toBe(0.5);
    const moved = imageLayer("img-a", img, handle, new Matrix4().translate([9, 0, 0]), 1, true, new Set(), { viewId: "spatial" });
    expect(moved.props.modelMatrix).not.toBe(a.props.modelMatrix);
    expect(moved.props.selections).toBe(a.props.selections);
  });

  it("hides channels by name without changing what is fetched, and keeps the layer invisible when all are hidden", () => {
    const one = imageLayer("img-b", img, handle, new Matrix4(), 1, true, new Set(["DAPI"]));
    expect(one.props.channelsVisible).toEqual([false, true]);
    expect(one.props.selections).toEqual([{ c: 0 }, { c: 1 }]);
    const none = imageLayer("img-b", img, handle, new Matrix4(), 1, true, new Set(["DAPI", "18S"]));
    expect(none.props.visible).toBe(false);
    expect(none.props.selections).toBe(one.props.selections); // same tiles: nothing to refetch when one comes back
    expect(imageLayer("img-b", img, handle, new Matrix4(), 1, false, new Set()).props.visible).toBe(false);
    expect(channelNames({ ...img, channels: null }, 8)).toEqual(["channel 1", "channel 2", "channel 3", "channel 4", "channel 5", "channel 6"]);
  });
});
