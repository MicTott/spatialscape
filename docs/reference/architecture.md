# Architecture

## Principles

Each one traces to a lesson from an earlier viewer:

- **One GL context for all samples** (ABC Atlas slide view, Odon mosaic). Stepping samples moves nothing in memory.
- **Recolor is a one-byte-per-cell upload.** Legend toggles, colormap, range and filter bounds are uniform or 4 KB texture updates. Nothing is refetched.
- **Loaders open once per sample and are cached.** Switching samples or colors never rebuilds them.
- **Decoding runs in a worker.** The main thread receives transferred `ArrayBuffer`s.
- **Rows are shuffled at build time**, so level of detail is a prefix draw count rather than a second attribute.
- **React renders chrome only.** The canvas is driven by store subscriptions.

## App modules

```
app/src
  views/ViewerController.ts   deck.gl Deck, two OrthographicViews, camera, store subscription, diagnostics
  views/loader.ts             manifest + sample opening + the arrays the current state needs
  views/layers.ts             store state → deck.gl layers (points, images, outlines, polygons, frames, labels)
  views/interaction.ts        pointer + keyboard: hover lookup and tooltip rows, click, lasso gestures, shortcuts
  views/selection.ts          lasso polygon → selected indices, highlight layers, summary, CSV
  views/stats.ts              category counts, filter histogram, gene-by-annotation table
  views/blend.ts              two-set gene scores
  layers/ExpressionScatterLayer.ts  ScatterplotLayer + 4 per-instance bytes (value, value2, category, filter),
                                    1D/2D LUT + palette textures, LOD prefix draw
  layers/imageLayers.ts       Viv MultiscaleImageLayer per sample image
  data/worker.ts              zarrita reads (sharded zarr v3 + zstd), KDBush build, polygon decode
  data/cache.ts               main-thread caches keyed by sample: positions, index, obs arrays, gene LRU
  store/store.ts              Zustand store: small descriptors only, never typed arrays
  url/urlState.ts             URLSearchParams ⇄ store
  ui/*                        sidebar panels, legend, gallery, site bar, scale bar
```

## Shader color modes

| mode | meaning | inputs |
|---|---|---|
| 0 | continuous | `instanceValue` → 256-entry LUT |
| 1 | categorical | `instanceCategory` → palette texture, alpha 0 = hidden |
| 2 | not measured | constant grey |
| 3 | blend | `instanceValue`, `instanceValue2` → 32×32 2D LUT |

The filter channel (`instanceFilter`, uniform bounds) applies in every mode; filtered or hidden instances are moved outside clip space.

## Data flow for a gene switch

1. Store `color` changes → controller bumps a generation counter → `Loader.loadChannels()`.
2. For each open sample without the gene cached, the worker reads one Zarr chunk (one range request on sharded stores), decodes zstd, transfers a `Uint8Array`.
3. The main-thread LRU stores it; `LayerBuilder` builds layers whose `data.attributes.getValue` points at the array. Positions keep the same descriptor object, so deck.gl does not re-upload them.
4. deck.gl uploads the new byte attribute and redraws. Cached switches skip step 2 entirely.

## Test hooks

In development and e2e builds, `window.__sscape` exposes `ready`, `setGene(gene) → ms`, `getState()`, `pixelProbe()`, the store and the controller.
