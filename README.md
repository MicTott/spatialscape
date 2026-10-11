# spatialscape

[![python](https://github.com/mictott/spatialscape/actions/workflows/python.yml/badge.svg)](https://github.com/mictott/spatialscape/actions/workflows/python.yml) [![pages](https://github.com/mictott/spatialscape/actions/workflows/pages.yml/badge.svg)](https://mictott.github.io/spatialscape/) [![PyPI](https://img.shields.io/pypi/v/spatialscape)](https://pypi.org/project/spatialscape/) [![license](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

A static, highly reactive web browser for spatial transcriptomics (Visium, Visium HD, Xenium, MERFISH) and paired snRNA-seq, built for publishing datasets alongside papers.

- **One big map.** Every sample of a dataset is drawn on one WebGL canvas (deck.gl), laid out as a grid or a strip. Double-click a sample to focus it, step through samples with the arrow keys, and every setting (gene, colormap, range, legend filters, image opacity) applies to all samples at once.
- **Instant gene switching.** Expression is stored one byte per cell per gene, gene-major, in sharded Zarr v3, so one gene for one sample is one HTTP range request. Cached switches are a single GPU buffer upload.
- **Color-by and filter-by are separate.** Color by cell type while filtering to cells above a threshold of a gene or QC metric, with a live histogram and count.
- **Linked snRNA-seq panel.** Embedding samples (UMAP of an snRNA-seq reference) render in a second view beside the tissue, sharing the same GL context, gene, colormap, legend and filters. The split is resizable and can sit left or right.
- **Platform bar and feature groups.** Switch the mosaic between Visium, Visium HD, Xenium or all at once. Non-gene features such as RCTD cell type weights get their own tab instead of polluting the gene search.
- **Two-set gene blending.** Color each cell by two gene sets at once (one gene or fifty per set): yellow and blue mixing to green, cyan and magenta to white, or red and green to yellow, with a 2D legend. Scores are the mean log-normalized expression of each set, on one scale across samples.
- **Hover, lasso, dot plot.** Hover shows every annotation of a cell plus the current gene value. Lasso any region for composition, gene statistics and a CSV of cell IDs. A per-annotation dot plot of the current gene doubles as a category filter. Cell boundary polygons draw when zoomed in.
- **Domain outlines over anything.** Boundaries of any categorical annotation (spatial domains, cell types) are traced at build time and can be drawn as thin light, dark or colored strokes on top of gene or cell-type coloring, so you always know which domain you are looking at.
- **Images under the points.** H&E or fluorescence pyramids (OME-Zarr) rendered with Viv, in the same coordinate frame as the cells.
- **Static hosting.** No server. The app is plain files (GitHub Pages, Cloudflare Pages); the data is plain files (S3, R2, any host with CORS and HTTP Range). Every view state lives in the URL.
- **One yaml per dataset, one command to apply it.** `spatialscape init` reads your data (a saved SpatialExperiment / SingleCellExperiment as `.rds` / `.rda`, parsed in Python with images and scale factors, or AnnData / SpatialData files) and writes a yaml that is a menu of what it contains. `spatialscape build <yaml>` turns it into a bundle and, after every edit, redoes only what changed. `spatialscape serve bundles` opens everything locally with the viewer that ships in the package.
- **One yaml for the gallery, when you want one.** `spatialscape site build bundles -o site` writes a folder to upload to any static host; `site.yaml` adds a title, paper links, "coming soon" cards and a navigation bar, and `spatialscape site build site.yaml` builds the listed datasets and the registry from it.

The landing gallery lists datasets with real thumbnails rendered at build time; `?d=<id>` opens one by name, `?d=<url>` opens any bundle. The hosted demo's registry is `app/public/datasets.json`.

`app/public/nexus/` holds a draft landing page for an institute portal ("LIBD Nexus") built around the viewer; it is a static mockup for review, served at `/nexus/index.html`.

**Documentation:** <https://mictott.github.io/spatialscape/docs/> (source in `docs/`, built with VitePress; `npm run docs:dev` to preview).

## Layout

```
app/      Vite + React 19 + TypeScript viewer (deck.gl 9, Viv, zarrita, Zustand)
python/   `spatialscape` CLI (anndata, zarr v3, pydantic)
examples/ synthetic demo bundle (committed) and dataset.yaml examples
docs/     VitePress documentation site (guide + reference)
```

## Quick start

```bash
pip install spatialscape
spatialscape synth demo-src                              # or skip: use your own h5ad / zarr files
spatialscape build demo-src/dataset.yaml -o bundles/demo
spatialscape serve bundles --open                        # viewer + data at http://127.0.0.1:8787/
```

Your own data, from a saved R object or from AnnData / SpatialData files, inside your project folder:

```bash
spatialscape init analysis/spe_visium.rds --id my_dataset   # writes my_dataset.yaml: a menu of the data
# edit my_dataset.yaml: keep the annotations you want, name them, pick colors and the opening gene
spatialscape build my_dataset.yaml                          # -> bundles/my_dataset; rerun after any edit
spatialscape serve bundles --open
spatialscape site build bundles -o site                     # viewer + registry + data, ready to upload
```

For a gallery of several datasets with a title, paper links and "coming soon" cards, `spatialscape site init` writes a `site.yaml` and `spatialscape site build site.yaml` builds it. Upload `site/` to GitHub Pages, Cloudflare Pages or any static host, or keep the bundles on S3 / R2 and set `data_url` in `site.yaml`. The [documentation](https://mictott.github.io/spatialscape/docs/) walks through every step; `sscape` is accepted as a short alias everywhere.

Developers, from a clone:

```bash
python3 -m venv python/.venv && python/.venv/bin/pip install -e "python[dev]"
npm install && npm run dev                               # viewer at http://127.0.0.1:5173
python/.venv/bin/spatialscape serve examples --port 8787 # data (the dev server proxies /examples to it)
npm run build && python/.venv/bin/python python/scripts/bundle_app.py   # refresh the viewer copy inside the package
```

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
