/** Viv image layers for OME-Zarr pyramids, positioned in sample space via modelMatrix. */
import { Matrix4 } from "@math.gl/core";
import { loadOmeZarr, MultiscaleImageLayer, ImageLayer } from "@hms-dbmi/viv";
import type { SampleImage } from "../data/manifest";
import { hexToRGB } from "./lut";

export interface ImageHandle {
  data: any[]; // ZarrPixelSource per level
  channels: number;
  dtype: string;
  labels: string[];
}

const loaders = new Map<string, Promise<ImageHandle>>();

export function loadImage(url: string): Promise<ImageHandle> {
  let p = loaders.get(url);
  if (!p) {
    p = loadOmeZarr(url, { type: "multiscales" } as any).then((res: any) => {
      const data = Array.isArray(res.data) ? res.data : [res.data];
      const shape: number[] = data[0].shape;
      const labels: string[] = data[0].labels ?? ["c", "y", "x"];
      const ci = labels.indexOf("c");
      return { data, channels: ci >= 0 ? shape[ci] : 1, dtype: data[0].dtype, labels } as ImageHandle;
    });
    loaders.set(url, p);
  }
  return p;
}

export function imageLayer(
  id: string,
  img: SampleImage,
  handle: ImageHandle,
  sampleMatrix: Matrix4,
  opacity: number,
  visible: boolean,
  extraProps: Record<string, unknown> = {},
) {
  const modelMatrix = new Matrix4(sampleMatrix)
    .translate([img.translate[0], img.translate[1], 0])
    .scale([img.pixelSize, img.pixelSize, 1]);
  const n = handle.channels;
  const isRGB = img.kind === "rgb" && n >= 3;
  const chans = isRGB ? [0, 1, 2] : Array.from({ length: n }, (_, i) => i);
  const maxv = handle.dtype === "Uint8" || handle.dtype === "uint8" ? 255 : 65535;
  // only keys that exist in the source's dimension labels are valid selection keys
  const selections = chans.map((c) => {
    const sel: Record<string, number> = {};
    for (const l of handle.labels) if (l !== "x" && l !== "y") sel[l] = l === "c" ? c : 0;
    return sel;
  });
  const contrastLimits = chans.map((c) => (img.channels?.[c]?.window as [number, number]) ?? [0, maxv]);
  const colors = isRGB
    ? [
        [255, 0, 0],
        [0, 255, 0],
        [0, 0, 255],
      ]
    : chans.map((c) => hexToRGB(img.channels?.[c]?.color ?? "#ffffff"));
  const common = {
    id,
    loader: handle.data,
    selections,
    contrastLimits,
    colors,
    channelsVisible: chans.map(() => true),
    opacity,
    visible,
    modelMatrix,
    pickable: false,
    // images never write depth, so points drawn later are not occluded
    parameters: { depthWriteEnabled: false, depthCompare: "always" },
    ...extraProps,
  } as any;
  return handle.data.length > 1 ? new MultiscaleImageLayer(common) : new ImageLayer(common);
}
