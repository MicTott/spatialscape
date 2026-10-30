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
  // in a real browser a cached switch is ~5-15 ms; headless SwiftShader adds up to ~100 ms of frame time
  expect(cached).toBeLessThan(250);
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

test("polished group controls preserve independent visibility and expansion", async ({ page }) => {
  await page.goto(`/?d=${encodeURIComponent(DATA)}`);
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  const cells = page.locator(".group").filter({ has: page.locator(".group-title", { hasText: "Cells" }) });
  const header = cells.locator(".group-head");
  await expect(header).toHaveAttribute("aria-expanded", "true");
  await page.getByRole("checkbox", { name: "Cells" }).click();
  expect((await page.evaluate(() => (window as any).__sscape.getState())).showCells).toBe(false);
  await expect(header).toHaveAttribute("aria-expanded", "true");
  const showCells = page.getByRole("checkbox", { name: "Cells" });
  await showCells.focus();
  await showCells.press("Space");
  expect((await page.evaluate(() => (window as any).__sscape.getState())).showCells).toBe(true);
  await expect(header).toHaveAttribute("aria-expanded", "true");
  const samples = page.locator(".group").filter({ has: page.locator(".group-title", { hasText: "Samples" }) });
  await samples.locator(".group-head").click();
  await expect(samples.locator(".group-head")).toHaveAttribute("aria-expanded", "true");
  await expect(header).toHaveAttribute("aria-expanded", "true");
});

test("canvas controls and labels support the full-view workflow", async ({ page }) => {
  await page.goto(`/?d=${encodeURIComponent(DATA)}&s=sampleB`);
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  await expect(page.getByRole("button", { name: "Pan and navigate" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Lasso select" }).click();
  await expect(page.getByRole("button", { name: "Lasso select" })).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Pan and navigate" }).click();
  await expect(page.getByRole("button", { name: "Pan and navigate" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".group-title", { hasText: "ROIs" })).toBeVisible();
  await page.getByRole("button", { name: "Gene sets", exact: true }).click();
  await expect(page.evaluate(() => (window as any).__sscape.getState().color)).resolves.toMatchObject({ kind: "blend" });
  await expect(page.locator(".blend-legend")).toContainText("Gene sets");

  await page.getByRole("button", { name: "Recenter all visible data" }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__sscape.getState().focus)).toBeNull();
  await expect.poll(() => page.evaluate(() => {
    const c = (window as any).__sscape.controller;
    return c.panes.every((pane: any) => {
      const vp = c.deck.getViewports().find((v: any) => v.id === pane.id);
      const b = c.layouts[pane.id]?.worldBbox;
      return vp && b && Math.abs(vp.target[0] - (b[0] + b[2]) / 2) < 1 && Math.abs(vp.target[1] - (b[1] + b[3]) / 2) < 1;
    });
  }), { timeout: 5000 }).toBe(true);
});

test("gene controls follow the color scale and scaling survives a shared link", async ({ page }) => {
  await page.goto(`/?d=${encodeURIComponent(DATA)}`);
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  await page.getByRole("button", { name: "Gene", exact: true }).click();
  const scale = page.getByRole("checkbox", { name: "scale each sample to its own max" });
  await expect(scale).not.toBeChecked(); // one shared scale is the default
  const ordered = await page.evaluate(() => {
    const ramp = document.querySelector(".legend .ramp")!;
    const controls = document.querySelector(".color-display-controls")!;
    return !!(ramp.compareDocumentPosition(controls) & Node.DOCUMENT_POSITION_FOLLOWING);
  });
  expect(ordered).toBe(true);
  await scale.check();
  await expect.poll(() => new URL(page.url()).searchParams.get("sps")).toBe("1");
  await page.reload();
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  await expect(page.getByRole("checkbox", { name: "scale each sample to its own max" })).toBeChecked();
});

test("embedding label toggle immediately redraws labels and categories respond to keyboard", async ({ page }) => {
  await page.goto(`/?d=${encodeURIComponent(DATA)}`);
  await page.waitForFunction(() => !!(window as any).__sscape, null, { timeout: 20_000 });
  await page.evaluate(() => (window as any).__sscape.ready);
  const hasLabels = () => page.evaluate(() => (window as any).__sscape.controller.deck.props.layers.flat(Infinity).some((l: any) => l?.id === "cluster-labels-embedding"));
  await expect.poll(hasLabels).toBe(true);
  const labels = page.getByRole("checkbox", { name: /Embedding labels/ });
  await labels.uncheck();
  await expect.poll(hasLabels).toBe(false);
  await labels.check();
  await expect.poll(hasLabels).toBe(true);
  const firstCategory = page.locator(".annotation-legend .cats li").first();
  await expect(firstCategory).toHaveAttribute("aria-pressed", "true");
  await firstCategory.focus();
  await firstCategory.press("Space");
  await expect(firstCategory).toHaveAttribute("aria-pressed", "false");
});
