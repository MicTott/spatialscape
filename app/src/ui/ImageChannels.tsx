import { useMemo } from "react";
import type { Manifest } from "../data/manifest";
import { store, useViewer } from "../store/store";
import { MAX_DRAWN, datasetChannels, drawnChannels } from "../layers/imageLayers";

export function channelSummary(manifest: Manifest): number {
  const n = datasetChannels(manifest).length;
  return n >= 2 ? n : 0;
}

/** One row per fluorescence channel name across the dataset, like the legend: click to switch it on or off,
 * double-click to show it alone. At most MAX_DRAWN draw at once; past that a row says so instead of switching on.
 * Images with a single channel or RGB get no rows. */
export function ImageChannels() {
  const manifest = useViewer((s) => s.manifest)!;
  const active = useViewer((s) => s.activeChannels);
  const hidden = useViewer((s) => s.hiddenChannels);
  const rows = useMemo(() => datasetChannels(manifest), [manifest]);
  if (rows.length < 2) return null;
  const names = rows.map(([n]) => n);
  const drawn = drawnChannels(names, active, hidden);
  const on = new Set(drawn);
  const full = drawn.length >= MAX_DRAWN;
  const setActive = (list: string[]) => store.getState().set({ activeChannels: list, hiddenChannels: [] });
  const toggle = (name: string) => {
    if (on.has(name)) setActive(drawn.filter((n) => n !== name));
    else if (!full) setActive([...drawn, name]);
  };
  const solo = (name: string) => setActive(drawn.length === 1 && on.has(name) ? names.slice(0, MAX_DRAWN) : [name]);
  return (
    <>
      {rows.length > MAX_DRAWN && (
        <div className="muted small channels-note">
          {drawn.length} of {rows.length} channels on screen, up to {MAX_DRAWN} at a time
        </div>
      )}
      <ul className="cats channels" aria-label="image channels">
        {rows.map(([name, color]) => {
          const blocked = !on.has(name) && full;
          return (
            <li
              key={name}
              className={on.has(name) ? "" : blocked ? "off blocked" : "off"}
              role="button"
              tabIndex={0}
              aria-pressed={on.has(name)}
              aria-disabled={blocked || undefined}
              onClick={() => toggle(name)}
              onKeyDown={(e) => {
                if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  toggle(name);
                }
              }}
              onDoubleClick={(e) => {
                e.preventDefault();
                solo(name);
              }}
              title={blocked ? `${MAX_DRAWN} channels are on; switch one off first · double-click: this one alone` : "click: on / off · double-click: this one alone"}
            >
              <span className="swatch" style={{ background: color }} />
              <span className="cat-name">{name}</span>
            </li>
          );
        })}
      </ul>
    </>
  );
}
