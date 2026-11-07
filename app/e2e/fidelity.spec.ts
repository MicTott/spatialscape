/** Fidelity of what the viewer computes: the lasso's membership against an offline point-in-polygon, and the
 *  region test against the same statistics computed in Python from the row store (scipy's Mann-Whitney). The
 *  browser side draws the regions through the store, runs the test, and writes a dump; the Python side
 *  (`python -m spatialscape.fidelity browser-de`) reads the same bundle from disk and reports every disagreement. */
import { expect, test } from "@playwright/test";
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const APP = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const DATA = process.env.E2E_DATA ?? "http://127.0.0.1:8787/synthetic";
const BUNDLE = process.env.E2E_BUNDLE ?? resolve(APP, "../examples/synthetic");
const PYTHON = process.env.E2E_PYTHON ?? resolve(APP, "../python/.venv/bin/python");

/** Two vertical bands of a section in its own micron frame: the left third and the right third. */
function bands(bbox: number[]): { left: [number, number][]; right: [number, number][] } {
  const [x0, y0, x1, y1] = bbox;
  const w = x1 - x0;
  const box = (a: number, b: number): [number, number][] => [
    [a, y0 - 1],
    [b, y0 - 1],
    [b, y1 + 1],
    [a, y1 + 1],
  ];
  return { left: box(x0 - 1, x0 + w / 3), right: box(x1 - w / 3, x1 + 1) };
}

test("regions drawn through the store select the cells an offline point-in-polygon selects, and the test matches scipy", async ({ page }) => {
  test.setTimeout(180_000);
  await page.goto(`/?d=${encodeURIComponent(DATA)}`);
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  const manifest = await page.evaluate(() => (window as any).__sscape.controller.manifest);
  const spatial = manifest.samples.filter((s: any) => s.kind === "spatial");
  expect(spatial.length).toBeGreaterThanOrEqual(2);

  // group A: the left band of every section; group B: the right band of every section
  const groups = [
    { id: "gA", name: "left", color: "#4e79a7", polygons: [] as any[] },
    { id: "gB", name: "right", color: "#f28e2b", polygons: [] as any[] },
  ];
  let seq = 0;
  for (const s of spatial) {
    const { left, right } = bands(s.bbox);
    groups[0].polygons.push({ id: `p${++seq}`, seq, sample: s.id, view: "spatial", local: left });
    groups[1].polygons.push({ id: `p${++seq}`, seq, sample: s.id, view: "spatial", local: right });
  }
  await page.evaluate((g) => (window as any).__sscape.store.getState().setRegions(g), groups);
  await page.evaluate(() => (window as any).__sscape.controller.whenIdle());

  // what the viewer assigned, per bundle row, and the positions it assigned them from
  const field = await page.evaluate(() => (window as any).__sscape.controller.regions.field);
  const assigned = await page.evaluate((field) => {
    const c = (window as any).__sscape.controller;
    const out: Record<string, { codes: number[]; xy: number[] }> = {};
    for (const [id, sd] of c.cache.samples) {
      const codes = sd.cat.get(field);
      if (codes) out[id] = { codes: Array.from(codes), xy: Array.from(sd.xy) };
    }
    return out;
  }, field);
  // the offline rule, on the same coordinates
  const inPoly = (x: number, y: number, poly: [number, number][]) => {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
      const [xi, yi] = poly[i];
      const [xj, yj] = poly[j];
      if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  };
  let members = 0;
  for (const s of spatial) {
    const { codes, xy } = assigned[s.id];
    const { left, right } = bands(s.bbox);
    for (let i = 0; i < codes.length; i++) {
      const expected = inPoly(xy[i * 2], xy[i * 2 + 1], right) ? 1 : inPoly(xy[i * 2], xy[i * 2 + 1], left) ? 0 : groups.length;
      expect(codes[i], `${s.id} cell ${i}`).toBe(expected);
      if (expected < groups.length) members++;
    }
  }
  expect(members).toBeGreaterThan(100);

  // the test, as the panel's button runs it: left against right, no subsampling
  await page.evaluate(() => (window as any).__sscape.regionTest({ mode: "pair", scope: "drawn", cap: 1e9 }));
  await page.waitForFunction(() => (window as any).__sscape.getState().test === null, null, { timeout: 120_000 });
  const note = await page.evaluate(() => (window as any).__sscape.getState().testNote);
  expect(note).toBeNull();
  const dump = await page.evaluate(async () => {
    const h = (window as any).__sscape;
    const m = await h.liveMatrix();
    const stats: Record<string, number[]> = {};
    for (const [k, v] of Object.entries(m.stats)) stats[k] = Array.from(v as Float32Array);
    return { info: m.info, genes: m.genes, levels: m.info.levels, stats, sections: m.sections ?? null };
  });
  expect(dump.levels.length).toBeGreaterThanOrEqual(1);
  const codes: Record<string, number[]> = {};
  for (const [id, v] of Object.entries(assigned)) codes[id] = v.codes;
  const outDir = resolve(APP, "test-results");
  mkdirSync(outDir, { recursive: true });
  const dumpPath = resolve(outDir, "fidelity-regions-test.json");
  writeFileSync(dumpPath, JSON.stringify({ dataset: DATA, mode: "pair", scope: "drawn", groups: groups.map((g) => g.name), field, codes, ...dump }));

  // the reference: Python reads the same bundle from disk and recomputes every statistic
  const r = spawnSync(PYTHON, ["-m", "spatialscape.fidelity", "browser-de", dumpPath, BUNDLE, "--out", resolve(outDir, "fidelity-regions-test.report.json")], { encoding: "utf8" });
  console.log(r.stdout);
  expect(r.stderr).toBe("");
  expect(r.status, r.stdout).toBe(0);
});
