# Architecture

```
app/src
  views/ViewerController.ts   imperative deck.gl Deck, views/rects, camera, store subscription, diagnostics (~400 lines)
  views/loader.ts             manifest + sample opening + "which arrays does the current state need"
  views/layers.ts             LayerBuilder: store state -> deck.gl layers (points, images, outlines, polygons, frames, labels)
  views/interaction.ts        pointer + keyboard: hover lookup and tooltip rows, click/dblclick, lasso gestures, shortcuts
  views/selection.ts          lasso polygon -> selected indices, highlight layers, summary, CSV export
  views/stats.ts              category counts, filter histogram, gene-by-annotation table
  views/blend.ts              two-set gene scores (mean of per-gene normalized expression)
  layers/ExpressionScatterLayer.ts  ScatterplotLayer + 4 per-instance bytes (value, value2, category, filter), 1D/2D LUT + palette textures, LOD prefix draw
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

Color modes in the shader: 0 continuous (1D LUT), 1 categorical (palette texture, alpha = visibility), 2 not measured (grey), 3 blend (2D LUT indexed by two gene-set scores; schemes in `layers/lut.ts`).

Registry: `app/public/datasets.json` lists datasets for the landing gallery; `?d=<id>` resolves through it, full URLs bypass it.

Test hooks: `window.__sscape` exposes `ready`, `setGene(gene) -> ms`, `getState()`, `pixelProbe()`, `store`, `controller` (dev and e2e builds).
