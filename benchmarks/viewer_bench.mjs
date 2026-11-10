// The viewer table of design/benchmarks.md, measured in a headed Chrome through Playwright.
//
//   node benchmarks/viewer_bench.mjs --app http://127.0.0.1:8790 --data http://127.0.0.1:8790/amygdala --name amygdala \
//        [--section xen_Br9192] [--genes 20] [--out benchmarks/results/viewer-amygdala.json] [--browser chrome|chromium]
//
// Serve the bundles first (`spatialscape serve <folder> --port 8790`): the app and the data come from one origin, with
// no network in between. States: the grid at the fitted zoom; one section focused; a 1 x 1 mm window on that section
// (cell shapes draw once dense enough); and, when the bundle has molecules, the window halved until the viewer draws
// them (it refuses when more than about a million would be visible). For each state the script records what is drawn
// (dots, polygons, molecules from the controller's tally), the requests and bytes it took to reach the state, the JS
// heap, and the frame times over a scripted 10 s pan. Cold load is measured once, from navigation to the first frame
// with cells. A gene switch is timed over N genes, each cold (first request) then cached, as data-ready and
// first-frame-drawn, from the store's own timings. Requests are Playwright's page events, which include the data
// worker's range requests; bytes are the response body size, or Content-Length for partial responses (HEADs count
// as requests with no bytes). The genome panel reacts to a gene switch on its own clock (locating the gene, a glide,
// a debounce, then the coverage reads), so each switch is followed by a wait for the panel to go idle: its reads
// count toward the switch that caused them. Everything goes
// into one JSON with the machine, browser and commit. A dataset with no tissue sections (an embedding-only atlas) gets
// the overview state and the gene switch only, on the embedding view.
import { chromium } from "playwright";
import { writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
import os from "node:os";

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d; };
const APP = arg("app", "http://127.0.0.1:8790");
const DATA = arg("data");
const NAME = arg("name", "dataset");
const SECTION = arg("section", null);
const NGENES = Number(arg("genes", "20"));
const OUT = arg("out", `benchmarks/results/viewer-${NAME}.json`);
const BROWSER = arg("browser", "chrome");
const PAN_MS = 10_000;
if (!DATA) throw new Error("--data <bundle url> is required");

const q = (xs, p) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.min(s.length - 1, Math.floor(p * s.length))] : null; };
const stats = (xs) => ({ n: xs.length, median: q(xs, 0.5), p95: q(xs, 0.95), max: xs.length ? Math.max(...xs) : null });

const browser = await chromium.launch({ headless: false, channel: BROWSER === "chrome" ? "chrome" : undefined });
const context = await browser.newContext({ viewport: { width: 1440, height: 860 }, deviceScaleFactor: 2 });
const page = await context.newPage();

// requests and bytes, attributed to the state being reached
let bucket = null;
const newBucket = () => (bucket = { requests: 0, bytes: 0, byStore: {} });
const storeOf = (url) => {
  const m = url.match(/\/samples\/[^/]+\/([^/?]+)/);
  if (!m) return /manifest\.json|genes\.json|features\.json|thumbnail/.test(url) ? "dataset" : url.includes("/assets/") || /\/\?|\/$/.test(url) ? "app" : "other";
  const f = m[1];
  if (f === "expr.zarr") return "expression";
  if (f === "rows.zarr") return "rows";
  if (f.endsWith(".ome.zarr")) return "images";
  if (f.startsWith("shapes") || f === "segmentations" || f === "outlines" || f.startsWith("polygons")) return "shapes";
  if (f.startsWith("molecules")) return "molecules";
  if (f === "tracks") return "tracks";
  return "cells";
};
page.on("requestfinished", async (r) => {
  if (!bucket) return;
  const b = bucket;
  const sizes = await r.sizes().catch(() => null);
  const resp = await r.response().catch(() => null);
  const n = r.method() === "HEAD" ? 0 : sizes?.responseBodySize || Number(resp?.headers()["content-length"] ?? 0) || 0; // a HEAD has no body
  const s = storeOf(r.url());
  b.requests += 1; b.bytes += n; b.byStore[s] ??= { requests: 0, bytes: 0 }; b.byStore[s].requests += 1; b.byStore[s].bytes += n;
});
const settle = async () => { await page.evaluate(() => window.__sscape.controller.whenIdle()); await page.waitForTimeout(400); await page.evaluate(() => window.__sscape.controller.whenIdle()); };
const snapshot = async (view) => page.evaluate((view) => {
  const c = window.__sscape.controller; const vs = c.viewStates[view];
  const vp = c.deck.getViewports().find((v) => v.id === view);
  return { view, drawn: window.__sscape.drawn(), zoom: vs?.zoom ?? null, pxPerUnit: vs ? Math.pow(2, vs.zoom) : null, viewportPx: vp ? [vp.width, vp.height] : null, heapBytes: performance.memory?.usedJSHeapSize ?? null };
}, view);
const idleFrames = async (ms = 1000) => page.evaluate(async (ms) => {
  const frames = []; let last = performance.now(); const t0 = last;
  await new Promise((done) => { const step = (now) => { frames.push(now - last); last = now; if (now - t0 < ms) requestAnimationFrame(step); else done(); }; requestAnimationFrame(step); });
  frames.shift(); return frames;
}, ms);
const pan = async (view) => page.evaluate(async ([view, ms]) => {
  const c = window.__sscape.controller; const vs0 = c.viewStates[view]; const px = 1 / Math.pow(2, vs0.zoom);
  const frames = []; let last = performance.now(); const t0 = last;
  await new Promise((done) => {
    const step = (now) => {
      frames.push(now - last); last = now;
      const a = (now - t0) / 1000; // a slow circle of 240 px radius
      c.setViewState(view, { target: [vs0.target[0] + 240 * px * Math.sin(a), vs0.target[1] + 240 * px * (1 - Math.cos(a)), 0], zoom: vs0.zoom }, true);
      if (now - t0 < ms) requestAnimationFrame(step); else { c.setViewState(view, vs0, true); done(); }
    };
    requestAnimationFrame(step);
  });
  frames.shift();
  return frames;
}, [view, PAN_MS]);
const panStats = (frames) => ({ ...stats(frames), over16_7ms: frames.filter((f) => f > 16.7).length / frames.length, over33ms: frames.filter((f) => f > 33.4).length / frames.length });
// A pan is only meaningful with the window frontmost and unthrottled: Chrome drops an occluded window to 30 fps or
// less. The idle baseline (no camera change) is recorded with each pan; a baseline far above the display's period
// found at start marks the pan as throttled, and the state is re-measured once.
let displayFrameMs = null;
const state = async (view) => {
  const s = await snapshot(view); s.reached = bucket;
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.bringToFront();
    const idle = stats(await idleFrames(800));
    s.idleFrameMs = idle.median;
    s.pan = panStats(await pan(view));
    s.pan.throttled = displayFrameMs != null && idle.median > 1.5 * displayFrameMs;
    if (!s.pan.throttled) break;
    console.error(`  window throttled (idle ${idle.median.toFixed(1)} ms per frame against ${displayFrameMs.toFixed(1)} at start): bring the Chrome window to the front; retrying`);
    await page.waitForTimeout(3000);
  }
  await settle(); return s;
};

const result = {
  name: NAME, data: DATA, date: new Date().toISOString(),
  commit: execSync("git rev-parse --short HEAD").toString().trim(),
  machine: { cpu: os.cpus()[0].model, cores: os.cpus().length, memoryGB: Math.round(os.totalmem() / 2 ** 30), platform: `${os.type()} ${os.release()}` },
  browser: `${BROWSER} ${browser.version()}`, viewport: "1440x860 @2x", states: {},
};

// ---- cold load: navigation -> ready -> first frame with cells
newBucket();
const t0 = Date.now();
await page.goto(`${APP}/?d=${encodeURIComponent(DATA)}`);
await page.waitForFunction(() => !!window.__sscape, null, { timeout: 120_000 });
await page.evaluate(() => window.__sscape.ready);
const readyMs = await page.evaluate(() => window.__sscape.readyAtMs);
let probe = { nonBackground: 0 }, firstFrameMs = null;
for (let i = 0; i < 100 && probe.nonBackground <= 50; i++) { probe = await page.evaluate(() => window.__sscape.pixelProbe()); if (probe.nonBackground > 50) firstFrameMs = Date.now() - t0; else await page.waitForTimeout(100); }
await settle();
await page.bringToFront();
displayFrameMs = stats(await idleFrames(1000)).median;
result.displayFrameMs = displayFrameMs;
const manifest = await page.evaluate(() => window.__sscape.controller.manifest);
const spatial = manifest.samples.filter((s) => s.kind === "spatial");
const view = spatial.length ? "spatial" : "embedding";
const section = spatial.length ? (SECTION ?? [...spatial].sort((a, b) => b.nObs - a.nObs)[0].id) : null;
const sec = manifest.samples.find((s) => s.id === section);
result.dataset = { samples: manifest.samples.length, cells: manifest.samples.reduce((n, s) => n + s.nObs, 0), view, section, sectionCells: sec?.nObs ?? null, hasMolecules: !!sec?.molecules, hasShapes: !!sec?.shapes };
result.coldLoad = { readyMs, firstFrameWithCellsMs: firstFrameMs, ...bucket };

// ---- state 1: overview
result.states.overview = await state(view);

// ---- state 2: one section focused
if (section) {
  newBucket();
  await page.evaluate((id) => window.__sscape.store.getState().setFocus(id), section);
  await settle();
  result.states.section = await state(view);
}

// ---- gene switch: cold then cached, N genes from the dataset's gene list
const genes = await page.evaluate(async (n) => {
  const url = window.__sscape.store.getState().datasetUrl;
  const all = await (await fetch(`${url}/genes.json`)).json();
  const pick = []; let seed = 12345;
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  while (pick.length < n && pick.length < all.length) { const g = all[Math.floor(rnd() * all.length)]; if (!pick.includes(g)) pick.push(g); }
  return pick;
}, NGENES);
const cold = { data: [], frame: [], idle: [] }, cached = { data: [], frame: [], idle: [] };
// the panel's reads follow the map's idle by a 500 ms glide and a 60 ms debounce: give it that, then wait them out
const hasGenome = await page.evaluate(() => !!window.__sscape.genome);
const switched = async () => {
  await page.waitForTimeout(50);
  if (!hasGenome) return;
  await page.waitForTimeout(700);
  await page.evaluate(() => window.__sscape.genome?.whenIdle());
};
const coldBucket = newBucket();
let cachedBucket = null;
for (const g of genes) {
  bucket = coldBucket;
  let idle = await page.evaluate((gene) => window.__sscape.setGene(gene), g);
  let t = await page.evaluate(() => window.__sscape.store.getState().timings);
  cold.idle.push(idle); cold.data.push(t.lastGeneMs); cold.frame.push(t.lastGeneFrameMs);
  await switched();
  bucket = cachedBucket ??= { requests: 0, bytes: 0, byStore: {} };
  idle = await page.evaluate((gene) => window.__sscape.setGene(gene), g);
  t = await page.evaluate(() => window.__sscape.store.getState().timings);
  cached.idle.push(idle); cached.data.push(t.lastGeneMs); cached.frame.push(t.lastGeneFrameMs);
  await switched();
}
result.geneSwitch = {
  genes: genes.length,
  cold: { dataReadyMs: stats(cold.data), firstFrameMs: stats(cold.frame), idleMs: stats(cold.idle), requests: coldBucket, requestsPerSwitch: coldBucket.requests / genes.length, bytesPerSwitch: coldBucket.bytes / genes.length },
  cached: { dataReadyMs: stats(cached.data), firstFrameMs: stats(cached.frame), idleMs: stats(cached.idle), requests: cachedBucket, requestsPerSwitch: cachedBucket.requests / genes.length },
};

// ---- state 3: a 1 x 1 mm window on the section, then halved until molecules draw
const zoomTo = async (mm) => page.evaluate(([id, mm]) => {
  const c = window.__sscape.controller; const b = c.layouts.spatial.placements.get(id).worldBbox;
  const vp = c.deck.getViewports().find((v) => v.id === "spatial");
  const zoom = Math.log2(Math.min(vp.width, vp.height) / (1000 * mm)); // the window spans the short side
  c.setViewState("spatial", { target: [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 0], zoom }, true);
}, [section, mm]);
if (section) {
  newBucket();
  await zoomTo(1); await settle(); await page.waitForTimeout(1500); await settle();
  result.states.window1mm = { windowMm: 1, ...(await state("spatial")) };
  if (sec?.molecules) {
    newBucket();
    await page.evaluate(() => window.__sscape.store.getState().set({ molecules: true }));
    let mm = 1;
    for (let i = 0; i < 5; i++) {
      await settle(); await page.waitForTimeout(2000); await settle();
      if ((await snapshot("spatial")).drawn.molecules > 0) break;
      mm /= 2; await zoomTo(mm);
    }
    result.states.windowMolecules = { windowMm: mm, ...(await state("spatial")) };
    await page.evaluate(() => window.__sscape.store.getState().set({ molecules: false }));
  }
}

writeFileSync(OUT, JSON.stringify(result, null, 1));
const r = result;
const mb = (b) => (b / 1e6).toFixed(1);
console.log(`${NAME}: ${r.dataset.cells.toLocaleString()} cells in ${r.dataset.samples} samples; display frame ${displayFrameMs.toFixed(1)} ms; cold load ready ${readyMs?.toFixed(0)} ms, first frame ${firstFrameMs} ms, ${mb(r.coldLoad.bytes)} MB in ${r.coldLoad.requests} requests`);
for (const [k, s] of Object.entries(r.states)) console.log(`  ${k}${s.windowMm ? ` (${s.windowMm} mm)` : ""}: drawn ${s.drawn.points.toLocaleString()} dots, ${s.drawn.shapes.toLocaleString()} shapes, ${s.drawn.molecules.toLocaleString()} molecules; pan median ${s.pan.median?.toFixed(1)} ms, p95 ${s.pan.p95?.toFixed(1)} ms, ${(100 * s.pan.over16_7ms).toFixed(0)}% over 16.7${s.pan.throttled ? " THROTTLED" : ""}; reached with ${mb(s.reached.bytes)} MB / ${s.reached.requests} req; heap ${(s.heapBytes / 1e6).toFixed(0)} MB`);
const g = r.geneSwitch;
console.log(`  gene switch (${genes.length} genes): cold data ${g.cold.dataReadyMs.median?.toFixed(0)} ms (p95 ${g.cold.dataReadyMs.p95?.toFixed(0)}), frame ${g.cold.firstFrameMs.median?.toFixed(0)} ms, ${g.cold.requestsPerSwitch.toFixed(1)} requests / ${mb(g.cold.bytesPerSwitch)} MB per switch; cached data ${g.cached.dataReadyMs.median?.toFixed(0)} ms, frame ${g.cached.firstFrameMs.median?.toFixed(0)} ms, ${g.cached.requestsPerSwitch.toFixed(2)} requests`);
await browser.close();
