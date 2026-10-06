# Architecture

```
app/src
  views/ViewerController.ts   imperative deck.gl Deck; subscribes to the store; builds layers; hover/focus/keys
  layers/ExpressionScatterLayer.ts  ScatterplotLayer + 3 per-instance bytes (value, category, filter), LUT + palette textures, LOD prefix draw
  layers/imageLayers.ts       Viv MultiscaleImageLayer per sample image, positioned by modelMatrix
  data/worker.ts              zarrita reads (sharded zarr v3 + zstd), KDBush build; transfers ArrayBuffers
  data/cache.ts               main-thread caches keyed by sample: positions, index, obs arrays, gene LRU (192 MB)
  views/layout.ts             grid/strip placement -> per-sample modelMatrix + world bbox
  store/store.ts              Zustand store: small descriptors only (never typed arrays)
  url/urlState.ts             URLSearchParams <-> store (replaceState, debounced view state)
```

Principles, each traceable to a prior-art lesson:

- One GL context for all samples (ABC Atlas slideview, Odon mosaic). Stepping samples never touches data. Two deck.gl views share it: `spatial` (tissue mosaic) and `embedding` (snRNA-seq UMAPs), routed by a `viewId` layer prop and `layerFilter`; the split fraction/side lives in the store (`sv` URL key).
- Recolor = upload 1 byte per cell; legend toggles, colormap, range and filter bounds = uniform or 4 KB texture updates.
- Loaders are opened once per sample and cached; switching samples or colors never rebuilds them (Vitessce #1953/#2564).
- Decoding runs in a worker (Vitessce #1709). Positions are uploaded once (stable descriptor identity).
- Rows are shuffled at build time so LOD is a prefix draw count, not a second attribute.
- React renders chrome only; the canvas is driven by store subscriptions.

Test hooks: `window.__sscape` exposes `ready`, `setGene(gene) -> ms`, `getState()`, `pixelProbe()`, `store`, `controller` (dev and e2e builds).
