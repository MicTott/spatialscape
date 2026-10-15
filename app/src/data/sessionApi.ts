/** `spatialscape.show()` serves the viewer from a Python session and answers /_api on the same origin. When that
 *  is where the dataset comes from, lasso selections are posted back so `session.selection()` can read them.
 *  Any other origin (a static site, a CDN) gets no requests at all. */
let probe: Promise<string | null> | null = null;

export function sessionApi(datasetUrl: string | null): Promise<string | null> {
  if (!datasetUrl) return Promise.resolve(null);
  const u = new URL(datasetUrl, location.href);
  if (u.origin !== location.origin || u.protocol === "file:") return Promise.resolve(null);
  if (!probe) {
    probe = fetch(`${u.origin}/_api/ping`)
      .then((r) => (r.ok ? `${u.origin}/_api` : null))
      .catch(() => null);
  }
  return probe;
}

/** The dataset's key on the session server: the last segment of its URL (the bundle folder). */
function datasetKey(datasetUrl: string): string {
  return new URL(datasetUrl, location.href).pathname.replace(/\/+$/, "").split("/").pop() ?? "";
}

let lastPosted = "";

/** Post the selection once per version (the summary is recomputed as arrays arrive; the cells do not change). */
export async function postSelection(datasetUrl: string | null, version: number, samples: Map<string, Uint32Array> | null): Promise<void> {
  const api = await sessionApi(datasetUrl);
  if (!api || !datasetUrl) return;
  const stamp = `${datasetUrl}|${version}|${samples ? "sel" : "none"}`;
  if (stamp === lastPosted) return;
  lastPosted = stamp;
  const body = { dataset: datasetKey(datasetUrl), version, samples: Object.fromEntries([...(samples ?? new Map())].map(([id, idx]) => [id, Array.from(idx)])) };
  await fetch(`${api}/selection`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => undefined);
}
