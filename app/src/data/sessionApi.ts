/** `spatialscape.show()` serves the viewer from a Python session whose registry (datasets.json) names an `api`
 *  path. When the dataset comes from that origin, lasso selections and regions are posted there so
 *  `session.selection()` / `session.regions()` can read them. A static site names no api and gets no requests. */
import { loadRegistry } from "../ui/registry";

export async function sessionApi(datasetUrl: string | null): Promise<string | null> {
  if (!datasetUrl) return null;
  const reg = (await loadRegistry().catch(() => null)) as ({ api?: string } & object) | null;
  if (!reg?.api) return null;
  const api = new URL(reg.api, location.href);
  if (api.origin !== new URL(datasetUrl, location.href).origin) return null;
  return api.toString().replace(/\/$/, "");
}

/** The dataset's key on the session server: the last segment of its URL (the bundle folder). */
function datasetKey(datasetUrl: string): string {
  return new URL(datasetUrl, location.href).pathname.replace(/\/+$/, "").split("/").pop() ?? "";
}

let lastPosted = "";
/** One id per page load: the session server keeps the newest version from the same viewer and lets a new viewer start over. */
const viewerId = typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;

/** POST with one retry; false when the server did not take it (the caller may try again later). */
async function post(url: string, body: unknown): Promise<boolean> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (r.ok) return true;
    } catch {
      // network error: retried once below
    }
    await new Promise((res) => setTimeout(res, 400));
  }
  console.warn(`spatialscape: the session did not take ${url}`);
  return false;
}

/** Region membership for a Python session: group names and colours plus per-sample codes (Uint16, base64). */
export interface RegionsDoc {
  version: number;
  groups: { name: string; color: string; polygons: { sample: string; view: string; local: [number, number][] }[] }[];
  codes: Record<string, string>;
}

/** The drawing the session holds for this dataset (what the viewer last posted, or what Python loaded). */
export async function fetchRegions(datasetUrl: string | null): Promise<RegionsDoc | null> {
  const api = await sessionApi(datasetUrl);
  if (!api || !datasetUrl) return null;
  try {
    const r = await fetch(`${api}/regions?d=${encodeURIComponent(datasetKey(datasetUrl))}`);
    return r.ok ? ((await r.json()) as RegionsDoc) : null;
  } catch {
    return null;
  }
}

export async function postRegions(datasetUrl: string | null, version: number, groups: RegionsDoc["groups"], codes: Map<string, Uint16Array>): Promise<void> {
  const api = await sessionApi(datasetUrl);
  if (!api || !datasetUrl) return;
  const enc = (u: Uint16Array) => {
    const bytes = new Uint8Array(u.buffer, u.byteOffset, u.byteLength);
    let s = "";
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  const body = { dataset: datasetKey(datasetUrl), version, viewer: viewerId, groups, codes: Object.fromEntries([...codes].map(([id, u]) => [id, enc(u)])) };
  await post(`${api}/regions`, body);
}

/** Post the selection once per version (the summary is recomputed as arrays arrive; the cells do not change). */
export async function postSelection(datasetUrl: string | null, version: number, samples: Map<string, Uint32Array> | null): Promise<void> {
  const api = await sessionApi(datasetUrl);
  if (!api || !datasetUrl) return;
  const stamp = `${datasetUrl}|${version}|${samples ? "sel" : "none"}`;
  if (stamp === lastPosted) return;
  const body = { dataset: datasetKey(datasetUrl), version, viewer: viewerId, samples: Object.fromEntries([...(samples ?? new Map())].map(([id, idx]) => [id, Array.from(idx)])) };
  if (await post(`${api}/selection`, body)) lastPosted = stamp; // a failed post is not remembered as done: the next summary posts again
}
