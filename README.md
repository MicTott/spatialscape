# spatialscape

[![python](https://github.com/mictott/spatialscape/actions/workflows/python.yml/badge.svg)](https://github.com/mictott/spatialscape/actions/workflows/python.yml) [![pages](https://github.com/mictott/spatialscape/actions/workflows/pages.yml/badge.svg)](https://mictott.github.io/spatialscape/) [![PyPI](https://img.shields.io/pypi/v/spatialscape)](https://pypi.org/project/spatialscape/) [![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

A static, highly reactive web browser for spatial transcriptomics (Visium, Visium HD, Xenium, MERFISH) and paired snRNA-seq, built for publishing datasets alongside papers.

- **One big map.** Every sample of a dataset is drawn on one WebGL canvas (deck.gl), laid out as a grid or a strip. Double-click a sample to focus it, step through samples with the arrow keys, and every setting (gene, colormap, range, legend filters, image opacity) applies to all samples at once.
- **Instant gene switching.** Expression is stored one byte per cell per gene, gene-major, in sharded Zarr v3, so one gene for one sample is one HTTP range request. Cached switches are a single GPU buffer upload.
- **Color-by and filter-by are separate.** Color by cell type while filtering to cells above a threshold of a gene or QC metric, with a live histogram and count.
- **Linked snRNA-seq panel.** Embedding samples (UMAP of an snRNA-seq reference) render in a second view beside the tissue, sharing the same GL context, gene, colormap, legend and filters. The split is resizable and can sit left or right.
- **Platform bar and feature groups.** Switch the mosaic between Visium, Visium HD, Xenium or all at once. Non-gene features such as RCTD cell type weights get their own tab instead of polluting the gene search.
- **Hover, lasso, dot plot.** Hover shows every annotation of a cell plus the current gene value. Lasso any region for composition, gene statistics and a CSV of cell IDs. A per-annotation dot plot of the current gene doubles as a category filter. Cell boundary polygons draw when zoomed in.
- **Domain outlines over anything.** Boundaries of any categorical annotation (spatial domains, cell types) are traced at build time and can be drawn as thin light, dark or colored strokes on top of gene or cell-type coloring, so you always know which domain you are looking at.
- **Images under the points.** H&E or fluorescence pyramids (OME-Zarr) rendered with Viv, in the same coordinate frame as the cells.
- **Static hosting.** No server. The app is plain files (GitHub Pages, Cloudflare Pages); the data is plain files (S3, R2, any host with CORS and HTTP Range). Every view state lives in the URL.
- **One command to add data.** `spatialscape build dataset.yaml -o bundle` converts AnnData (h5ad / zarr) or SpatialData into a viewer bundle. R users export their SpatialExperiment / SingleCellExperiment to h5ad first (zellkonverter or anndataR).

## Layout

```
app/      Vite + React 19 + TypeScript viewer (deck.gl 9, Viv, zarrita, Zustand)
python/   `spatialscape` CLI (anndata, zarr v3, pydantic)
examples/ synthetic demo bundle (committed) and dataset.yaml examples
docs/     format.md (bundle on disk), cli.md, hosting.md, architecture.md
```

## Quick start

Data contributors only need the CLI:

```bash
pip install spatialscape
spatialscape inspect my_sample.h5ad
spatialscape build dataset.yaml -o bundles/my_dataset
```

Developers, from a clone:

```bash
# 1. Python CLI (editable)
python3 -m venv python/.venv && python/.venv/bin/pip install -e "python[dev]"

# 2. Build the synthetic demo and serve it (CORS + Range enabled)
python/.venv/bin/spatialscape synth /tmp/synth-src
python/.venv/bin/spatialscape build /tmp/synth-src/dataset.yaml -o examples/synthetic
python/.venv/bin/spatialscape serve examples --port 8787

# 3. Run the app
npm install && npm run dev
# open http://127.0.0.1:5173/?d=http://127.0.0.1:8787/synthetic
```

## Adding a dataset

Write a `dataset.yaml` (see `examples/amygdala.yaml` and `docs/cli.md`), then:

```bash
spatialscape inspect my_sample.h5ad            # lists obs columns, obsm keys, scale hints
spatialscape build dataset.yaml -o bundles/my_dataset
spatialscape validate bundles/my_dataset        # or a URL once uploaded
```

`sscape` is accepted as a short alias everywhere.

Upload the bundle directory to any static host that supports CORS and HTTP Range requests (see `docs/hosting.md`), then open `https://your-app-host/?d=https://your-data-host/my_dataset`.

## Tests

```bash
python/.venv/bin/python -m pytest python/tests      # exporter
npm test                                             # app unit tests (vitest)
npm run e2e                                          # Playwright smoke test against the synthetic bundle
```

## Status

v1 scope: mosaic/strip layout with focus, gene / annotation / feature-group coloring, legend filtering, independent filter channel, hover, H&E/fluorescence images, platform bar, linked embedding split view, URL state. Planned: lasso selection summaries, dot plots, cell polygons at high zoom, multi-frame compare, named waypoints.

Hosted demo (synthetic data): https://mictott.github.io/spatialscape/

MIT license. See `CONTRIBUTING.md` to get involved and `CITATION.cff` to cite.
