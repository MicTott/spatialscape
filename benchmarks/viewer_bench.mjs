// The viewer table of design/benchmarks.md, measured in a headed Chrome through Playwright.
//
//   node benchmarks/viewer_bench.mjs --app http://127.0.0.1:8790 --data http://127.0.0.1:8790/amygdala --name amygdala \
//        [--section xen_Br9192] [--genes 20] [--out benchmarks/results/viewer-amygdala.json] [--browser chrome|chromium]
//
// Serve the bundles first (`spatialscape serve <folder> --port 8790`): the app and the data come from one origin, with
// no network in between. For each of three states (the grid at the fitted zoom; one section focused; a 1 x 1 mm window
// on that section, with cell shapes, then also with molecules when the bundle has them) the script records what is
// drawn (dots, polygons, molecules from the controller's tally), the requests and bytes it took to reach the state, the
// JS heap, and the frame times over a scripted 10 s pan. Cold load is measured once, from navigation to the first frame
// with cells. A gene switch is timed over N genes, each cold (first request) then cached, as data-ready and
// first-frame-drawn, from the store's own timings. Everything goes into one JSON with the machine, browser and commit.
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

const browser = await chromium.launch({ headless: false, channel: BROWSER === "chrome" ? "chrome" : undefined, args: ["--enable-gpu-rasterization"] });
const context = await browser.newContext({ viewport: { width: 1440, height: 860 }, deviceScaleFactor: 2 });
const page = await context.newPage();
const cdp = await context.newCDPSession(page);
await cdp.send("Network.enable");

// requests and bytes, attributed to the state being reached
const inflight = new Map(); // requestId -> url
let bucket = null;
const newBucket = () => (bucket = { requests: 0, bytes: 0, byStore: {} });
const storeOf = (url) => {
  const m = url.match(/\/samples\/[^/]+\/([^/?]+)/);
  if (!m) return url.includes("manifest.json") || url.includes("genes.json") || url.includes("features.json") ? "dataset" : url.includes("/assets/") || url.endsWith("/") ? "app" : "other";
  const f = m[1];
  if (f === "expr.zarr") return "expression";
  if (f === "rows.zarr") return "rows";
  if (f.endsWith(".ome.zarr")) return "images";
  if (f.startsWith("shapes") || f === "segmentations" || f === "outlines") return "shapes";
  if (f.startsWith("molecules")) return "molecules";
  if (f === "tracks") return "tracks";
  return "cells";
};
cdp.on("Network.requestWillBeSent", (e) => inflight.set(e.requestId, e.request.url));
cdp.on("Network.loadingFinished", (e) => {
  const url = inflight.get(e.requestId); inflight.delete(e.requestId);
  if (!bucket || !url) return;
  bucket.requests += 1; bucket.bytes += e.encodedDataLength;
  const s = storeOf(url); bucket.byStore[s] ??= { requests: 0, bytes: 0 }; bucket.byStore[s].requests += 1; bucket.byStore[s].bytes += e.encodedDataLength;
});
const settle = async () => { await page.evaluate(() => window.__sscape.controller.whenIdle()); await page.waitForTimeout(400); await page.evaluate(() => window.__sscape.controller.whenIdle()); };
const snapshot = async () => page.evaluate(() => {
  const c = window.__sscape.controller; const vs = c.viewStates.spatial;
  const vp = c.deck.getViewports().find((v) => v.id === "spatial");
  return { drawn: window.__sscape.drawn(), zoom: vs?.zoom ?? null, pxPerMicron: vs ? Math.pow(2, vs.zoom) : null, viewportPx: vp ? [vp.width, vp.height] : null, heapBytes: performance.memory?.usedJSHeapSize ?? null };
});
const pan = async () => page.evaluate(async (ms) => {
  const c = window.__sscape.controller; const vs0 = c.viewStates.spatial; const px = 1 / Math.pow(2, vs0.zoom);
  const frames = []; let last = performance.now(); const t0 = last; let i = 0;
  await new Promise((done) => {
    const step = (now) => {
      frames.push(now - last); last = now; i++;
      const a = (now - t0) / 1000; // a slow circle, 4 px per frame
      c.setViewState("spatial", { target: [vs0.target[0] + 240 * px * Math.sin(a), vs0.target[1] + 240 * px * (1 - Math.cos(a)), 0], zoom: vs0.zoom }, true);
      if (now - t0 < ms) requestAnimationFrame(step); else { c.setViewState("spatial", vs0, true); done(); }
    };
    requestAnimationFrame(step);
  });
  frames.shift();
  return frames;
}, PAN_MS);
const panStats = (frames) => ({ ...stats(frames), over16_7ms: frames.filter((f) => f > 16.7).length / frames.length, over33ms: frames.filter((f) => f > 33.4).length / frames.length });

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
const manifest = await page.evaluate(() => window.__sscape.controller.manifest);
const spatial = manifest.samples.filter((s) => s.kind === "spatial");
const section = SECTION ?? spatial.sort((a, b) => b.nObs - a.nObs)[0]?.id;
const sec = manifest.samples.find((s) => s.id === section);
result.dataset = { samples: manifest.samples.length, cells: manifest.samples.reduce((n, s) => n + s.nObs, 0), section, sectionCells: sec?.nObs ?? null, hasMolecules: !!sec?.molecules, hasShapes: !!sec?.shapes };
result.coldLoad = { readyMs, firstFrameWithCellsMs: firstFrameMs, ...bucket };

// ---- state 1: overview
result.states.overview = { ...(await snapshot()), reached: bucket };
result.states.overview.pan = panStats(await pan());

// ---- state 2: one section focused
newBucket();
await page.evaluate((id) => window.__sscape.store.getState().setFocus(id), section);
await settle();
result.states.section = { ...(await snapshot()), reached: bucket };
result.states.section.pan = panStats(await pan());

// ---- gene switch on the focused section: cold then cached, N genes
const genes = await page.evaluate(async (n) => {
  const s = window.__sscape.store.getState(); const url = s.datasetUrl;
  const all = await (await fetch(`${url}/genes.json`)).json();
  const pick = []; let seed = 12345; // deterministic subset
  const rnd = () => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  while (pick.length < n && all.length) { const g = all[Math.floor(rnd() * all.length)]; if (!pick.includes(g)) pick.push(g); }
  return pick;
}, NGENES);
const cold = { data: [], frame: [], idle: [] }, cached = { data: [], frame: [], idle: [] };
newBucket();
for (const g of genes) {
  for (const acc of [cold, cached]) {
    const idle = await page.evaluate((gene) => window.__sscape.setGene(gene), g);
    const t = await page.evaluate(() => window.__sscape.store.getState().timings);
    acc.idle.push(idle); acc.data.push(t.lastGeneMs); acc.frame.push(t.lastGeneFrameMs);
    await page.waitForTimeout(50);
  }
}
result.geneSwitch = { genes: genes.length, cold: { dataReadyMs: stats(cold.data), firstFrameMs: stats(cold.frame), idleMs: stats(cold.idle) }, cached: { dataReadyMs: stats(cached.data), firstFrameMs: stats(cached.frame), idleMs: stats(cached.idle) }, requests: bucket, perGeneRequests: bucket.requests / (2 * genes.length) };

// ---- state 3: a 1 x 1 mm window on the section (cell shapes draw once dense enough), then with molecules
const zoomTo1mm = async () => page.evaluate((id) => {
  const c = window.__sscape.controller; const p = c.layouts.spatial.placements.get(id); const b = p.worldBbox;
  const vp = c.deck.getViewports().find((v) => v.id === "spatial");
  const zoom = Math.log2(Math.min(vp.width, vp.height) / 1000); // 1000 um across the short side
  c.setViewState("spatial", { target: [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2, 0], zoom }, true);
}, section);
newBucket();
await zoomTo1mm(); await settle(); await page.waitForTimeout(1500); await settle();
result.states.window1mm = { ...(await snapshot()), reached: bucket };
result.states.window1mm.pan = panStats(await pan());
await settle();
if (sec?.molecules) {
  newBucket();
  await page.evaluate(() => window.__sscape.store.getState().set({ molecules: true }));
  await settle(); await page.waitForTimeout(2000); await settle();
  result.states.window1mmMolecules = { ...(await snapshot()), reached: bucket };
  result.states.window1mmMolecules.pan = panStats(await pan());
  await page.evaluate(() => window.__sscape.store.getState().set({ molecules: false }));
}

writeFileSync(OUT, JSON.stringify(result, null, 1));
const r = result;
console.log(`${NAME}: ${r.dataset.cells.toLocaleString()} cells in ${r.dataset.samples} samples; cold load ready ${readyMs?.toFixed(0)} ms, first frame ${firstFrameMs} ms, ${(r.coldLoad.bytes / 1e6).toFixed(1)} MB in ${r.coldLoad.requests} requests`);
for (const [k, s] of Object.entries(r.states)) console.log(`  ${k}: drawn ${s.drawn.points.toLocaleString()} dots, ${s.drawn.shapes.toLocaleString()} shapes, ${s.drawn.molecules.toLocaleString()} molecules; pan median ${s.pan.median?.toFixed(1)} ms, p95 ${s.pan.p95?.toFixed(1)} ms, ${(100 * s.pan.over16_7ms).toFixed(0)}% over 16.7; reached with ${(s.reached.bytes / 1e6).toFixed(1)} MB / ${s.reached.requests} req; heap ${(s.heapBytes / 1e6).toFixed(0)} MB`);
console.log(`  gene switch (${genes.length} genes): cold data ${r.geneSwitch.cold.dataReadyMs.median?.toFixed(0)} ms (p95 ${r.geneSwitch.cold.dataReadyMs.p95?.toFixed(0)}), frame ${r.geneSwitch.cold.firstFrameMs.median?.toFixed(0)} ms; cached data ${r.geneSwitch.cached.dataReadyMs.median?.toFixed(0)} ms, frame ${r.geneSwitch.cached.firstFrameMs.median?.toFixed(0)} ms; ${r.geneSwitch.perGeneRequests.toFixed(2)} requests per switch`);
await browser.close();
