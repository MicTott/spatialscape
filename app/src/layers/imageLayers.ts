/** Viv image layers for OME-Zarr pyramids, positioned in sample space via modelMatrix. */
import { Matrix4 } from "@math.gl/core";
import { loadOmeZarr, MultiscaleImageLayer, ImageLayer } from "@hms-dbmi/viv";
import type { Manifest, SampleImage } from "../data/manifest";
import { hexToRGB } from "./lut";

export interface ImageHandle {
  data: any[]; // ZarrPixelSource per level
  channels: number;
  dtype: string;
  labels: string[];
}

const loaders = new Map<string, Promise<ImageHandle>>();
/** Channels drawn at once: Viv blends at most this many in one pass, and additive colours stop being readable past about six. */
export const MAX_DRAWN = 6;

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

/** Props objects reused while their content is the same. Viv keys its tiles on `selections` (and its background
 * image on the props it was built from) and refetches every visible tile when handed a new array, even an equal
 * one; the layers are rebuilt on every camera frame, so fresh arrays used to download the same tiles again and
 * again while zooming (2,820 requests for 44 distinct tiles over two wheel gestures). */
const stableProps = new Map<string, { key: string; value: unknown }>();
function stable<T>(slot: string, key: string, make: () => T): T {
  const hit = stableProps.get(slot);
  if (hit && hit.key === key) return hit.value as T;
  const value = make();
  stableProps.set(slot, { key, value });
  return value;
}

// images never write depth, so points drawn later are not occluded
const IMAGE_PARAMETERS = { depthWriteEnabled: false, depthCompare: "always" };
const RGB_COLORS = [
  [255, 0, 0],
  [0, 255, 0],
  [0, 0, 255],
];

/** The channel names a multichannel image offers, in file order (at most the ones the viewer can draw). */
export function channelNames(img: SampleImage, count: number): string[] {
  return Array.from({ length: count }, (_, i) => img.channels?.[i]?.name ?? `channel ${i + 1}`);
}

/** Every fluorescence channel name across the dataset, in first-seen order, with its colour. */
export function datasetChannels(manifest: Manifest): [string, string][] {
  const seen = new Map<string, string>();
  for (const smp of manifest.samples)
    for (const img of smp.images) {
      if (img.kind !== "multichannel" || !img.channels?.length) continue;
      channelNames(img, img.channels.length).forEach((name, i) => {
        if (!seen.has(name)) seen.set(name, img.channels![i].color ?? "#ffffff");
      });
    }
  return [...seen.entries()];
}

/** The channels on screen, in order: the chosen list, or the dataset's first MAX_DRAWN minus any an older link hid. */
export function drawnChannels(names: string[], activeChannels: string[] | null, hiddenChannels: string[]): string[] {
  if (activeChannels) return activeChannels.filter((n) => names.includes(n)).slice(0, MAX_DRAWN);
  const hidden = new Set(hiddenChannels);
  return names.filter((n) => !hidden.has(n)).slice(0, MAX_DRAWN);
}

export function imageLayer(
  id: string,
  img: SampleImage,
  handle: ImageHandle,
  sampleMatrix: Matrix4,
  opacity: number,
  visible: boolean,
  drawn: readonly string[],
  extraProps: Record<string, unknown> = {},
) {
  const slot = `${id}|${String(extraProps.viewId ?? "")}`;
  const placement = `${Array.from(sampleMatrix as unknown as ArrayLike<number>).join(",")}|${img.translate.join(",")}|${img.pixelSize}`;
  const modelMatrix = stable(`${slot}|matrix`, placement, () =>
    new Matrix4(sampleMatrix).translate([img.translate[0], img.translate[1], 0]).scale([img.pixelSize, img.pixelSize, 1]),
  );
  const n = handle.channels;
  const isRGB = img.kind === "rgb" && n >= 3;
  // the drawn channels this image has, in the order chosen; only those are fetched, so a 56-channel panel costs
  // no more than a 6-channel one, and a channel switched on is fetched then
  const names = channelNames(img, n);
  const chans = isRGB ? [0, 1, 2] : drawn.map((name) => names.indexOf(name)).filter((i) => i >= 0);
  const shown = chans.map(() => true);
  const maxv = handle.dtype === "Uint8" || handle.dtype === "uint8" ? 255 : 65535;
  // only keys that exist in the source's dimension labels are valid selection keys
  const selections = stable(`${slot}|selections`, `${handle.labels.join(",")}|${chans.join(",")}`, () =>
    chans.map((c) => {
      const sel: Record<string, number> = {};
      for (const l of handle.labels) if (l !== "x" && l !== "y") sel[l] = l === "c" ? c : 0;
      return sel;
    }),
  );
  const limits = chans.map((c) => (img.channels?.[c]?.window as [number, number]) ?? [0, maxv]);
  const contrastLimits = stable(`${slot}|limits`, JSON.stringify(limits), () => limits);
  const cols = isRGB ? RGB_COLORS : chans.map((c) => hexToRGB(img.channels?.[c]?.color ?? "#ffffff"));
  const colors = stable(`${slot}|colors`, JSON.stringify(cols), () => cols);
  const channelsVisible = stable(`${slot}|visible`, shown.join(","), () => shown);
  const common = {
    id,
    loader: handle.data,
    selections,
    contrastLimits,
    colors,
    channelsVisible,
    opacity,
    // with every channel hidden the layer stays, invisible, so its tiles are still cached when one comes back
    visible: visible && shown.some(Boolean),
    modelMatrix,
    pickable: false,
    parameters: IMAGE_PARAMETERS,
    ...extraProps,
  } as any;
  // Viv's ImageLayer takes one pixel source, the multiscale layer the whole pyramid (a small image has one level)
  return handle.data.length > 1 ? new MultiscaleImageLayer(common) : new ImageLayer({ ...common, loader: handle.data[0] });
}
