import { expect, test } from "@playwright/test";

const DATA = "http://127.0.0.1:8787/synthetic";


test("loads the synthetic bundle, switches genes fast, filters without network", async ({ page }) => {
  const requests: string[] = [];
  const errors: string[] = [];
  page.on("request", (r) => {
    if (/\/(expr|obs)\.zarr\//.test(r.url())) requests.push(r.url());
  });
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  await page.goto(`/?d=${encodeURIComponent(DATA)}`);
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  const state = await page.evaluate(() => (window as any).__sscape.getState());
  expect(state.status).toBe("ready");
  expect(Object.values(state.sampleStatus)).toEqual(["ready", "ready", "ready"]);

  // something is drawn (poll: the first frame with layers may land a few ms after ready)
  let probe = { nonBackground: 0, total: 0 };
  for (let i = 0; i < 20 && probe.nonBackground <= 50; i++) {
    probe = await page.evaluate(() => (window as any).__sscape.pixelProbe());
    if (probe.nonBackground <= 50) await page.waitForTimeout(150);
  }
  expect(probe.nonBackground).toBeGreaterThan(50);

  // gene switch: cold then cached
  const cold = await page.evaluate(() => (window as any).__sscape.setGene("G005"));
  // best of three: headless software GL has multi-hundred-ms hiccups while earlier async work drains
  let cached = Infinity;
  for (let i = 0; i < 3; i++) cached = Math.min(cached, await page.evaluate(() => (window as any).__sscape.setGene("G005")));
  expect(cold).toBeLessThan(2500);
  expect(cached).toBeLessThan(100);
  expect((await page.evaluate(() => (window as any).__sscape.getState().color)).gene).toBe("G005");

  // legend toggle makes no network requests
  await page.evaluate(() => (window as any).__sscape.store.getState().setColor({ kind: "field", field: "cluster" }));
  await page.evaluate(() => (window as any).__sscape.controller.whenIdle());
  const before = requests.length;
  await page.evaluate(() => (window as any).__sscape.store.getState().toggleCategory("cluster", 1));
  await page.waitForTimeout(300);
  expect(requests.length).toBe(before);
  expect((await page.evaluate(() => (window as any).__sscape.getState().hiddenCategories)).cluster).toEqual([1]);

  // focus via URL param
  await page.goto(`/?d=${encodeURIComponent(DATA)}&s=sampleB`);
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  expect((await page.evaluate(() => (window as any).__sscape.getState())).focus).toBe("sampleB");
  const vs = await page.evaluate(() => {
    const c = (window as any).__sscape.controller;
    const vp = c.deck.getViewports().find((v: any) => v.id === "spatial");
    const b = c.layouts.spatial.placements.get("sampleB").worldBbox;
    return { target: vp.target ?? vp.position, center: [(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], views: c.deck.getViewports().map((v: any) => v.id).sort() };
  });
  // the synthetic bundle has an embedding sample, so the split view is on by default
  expect(vs.views).toEqual(["embedding", "spatial"]);
  expect(Math.abs(vs.target[0] - vs.center[0])).toBeLessThan(1);
  expect(Math.abs(vs.target[1] - vs.center[1])).toBeLessThan(1);
  expect(errors, errors.join("\n")).toEqual([]);
});
