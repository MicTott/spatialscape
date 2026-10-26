import { useMemo } from "react";
import type { Manifest } from "../data/manifest";
import { store, useViewer } from "../store/store";
import { channelNames } from "../layers/imageLayers";

export function channelSummary(manifest: Manifest): number {
  const names = new Set<string>();
  for (const smp of manifest.samples)
    for (const img of smp.images) if (img.kind === "multichannel" && img.channels?.length) for (const n of channelNames(img, img.channels.length)) names.add(n);
  return names.size >= 2 ? names.size : 0;
}

/** One row per fluorescence channel name across the dataset, like the legend: click to switch it on or off,
 * double-click to show it alone (again to show them all). Images with a single channel or RGB get no rows. */
export function ImageChannels() {
  const manifest = useViewer((s) => s.manifest)!;
  const hidden = useViewer((s) => s.hiddenChannels);
  const rows = useMemo(() => {
    const seen = new Map<string, string>();
    for (const smp of manifest.samples)
      for (const img of smp.images) {
        if (img.kind !== "multichannel" || !img.channels?.length) continue;
        channelNames(img, img.channels.length).forEach((name, i) => {
          if (!seen.has(name)) seen.set(name, img.channels![i].color ?? "#ffffff");
        });
      }
    return [...seen.entries()];
  }, [manifest]);
  if (rows.length < 2) return null;
  const off = new Set(hidden);
  const setHidden = (names: string[]) => store.getState().set({ hiddenChannels: names });
  const toggle = (name: string) => setHidden(off.has(name) ? hidden.filter((n) => n !== name) : [...hidden, name]);
  const solo = (name: string) => {
    const others = rows.map(([n]) => n).filter((n) => n !== name);
    const alone = !off.has(name) && others.every((n) => off.has(n));
    setHidden(alone ? [] : others);
  };
  return (
    <ul className="cats channels" aria-label="image channels">
      {rows.map(([name, color]) => (
        <li
          key={name}
          className={off.has(name) ? "off" : ""}
          onClick={() => toggle(name)}
          onDoubleClick={(e) => {
            e.preventDefault();
            solo(name);
          }}
          title="click: toggle · double-click: solo"
        >
          <span className="swatch" style={{ background: color }} />
          <span className="cat-name">{name}</span>
        </li>
      ))}
    </ul>
  );
}
