<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/brand/banner-dark.svg">
    <img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/brand/banner-light.svg" width="372" alt="spatialscape">
  </picture>
</p>

<p align="center">
  A static, reactive browser for spatial transcriptomics and snRNA-seq.<br>
  Every section of a study on one map, instant at a million cells, hosted as plain files.
</p>

<p align="center">
  <a href="https://mictott.github.io/spatialscape/docs/"><b>Documentation</b></a>
  &nbsp;·&nbsp; <a href="https://mictott.github.io/spatialscape/docs/guide/getting-started">Getting started</a>
  &nbsp;·&nbsp; <a href="https://mictott.github.io/spatialscape/">Live demo</a>
  &nbsp;·&nbsp; <a href="CHANGELOG.md">Changelog</a>
</p>

<p align="center">
  <a href="https://github.com/MicTott/spatialscape/actions/workflows/python.yml"><img src="https://github.com/MicTott/spatialscape/actions/workflows/python.yml/badge.svg" alt="python"></a>
  <a href="https://github.com/MicTott/spatialscape/actions/workflows/app.yml"><img src="https://github.com/MicTott/spatialscape/actions/workflows/app.yml/badge.svg" alt="app"></a>
  <a href="https://mictott.github.io/spatialscape/docs/"><img src="https://github.com/MicTott/spatialscape/actions/workflows/pages.yml/badge.svg" alt="docs"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-3776ab" alt="Python 3.11+">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

## Why spatialscape

The Lieber Institute publishes spatial transcriptomics studies that span many donors, often several platforms, and a paired snRNA-seq reference behind the labels. Putting one online used to mean a choice. A Shiny app needs a server, shows one section at a time and redraws a plot for every gene. A static viewer such as Vitessce needs no server and is fast, but gives each section its own small pane, rebuilds the pane when you switch, and leaves little room for the tissue. We built the amygdala browser both ways before writing this. Neither let a reader do what we do with these studies ourselves: look at every donor at once, under identical settings, and ask the same question of all of them.

spatialscape was built for that one thing, and a few others follow from it:

| | spatialscape | Shiny apps (spatialLIBD, iSEE) | Static multi-pane viewers (Vitessce) |
|---|---|---|---|
| Sections in view | the whole study on one canvas, one legend, one set of settings | one at a time, or a fixed grid of plots | one per pane; switching rebuilds the pane |
| Platforms | Visium, Visium HD, Xenium and snRNA-seq in one dataset, laid out in microns, with one shared vocabulary so a label has the same color everywhere | one object per app | one dataset per view |
| Changing the gene | one HTTP range request per section; a cached switch is a GPU upload, so a million cells recolor in milliseconds | a server-side redraw | a fetch per pane |
| Hosting | static files: GitHub Pages, S3, Cloudflare R2, a lab web server | an R process per visitor | static files |
| Sharing a view | the URL holds the gene, annotation, filters, camera and split, so a link reopens the exact view | screenshots | a view-config JSON |
| Authoring | `init` writes one yaml from your `.rds` or AnnData; `build` applies every edit; `site.yaml` describes the gallery | R code | a Zarr export plus a JSON config per view |

The rest is what a published dataset needs around that: a gallery with real thumbnails, paper links, a navigation bar, outlines of spatial domains over any coloring, lasso statistics, and a build that validates itself.

## Quick start

```bash
pip install spatialscape
spatialscape synth demo-src                      # two fake sections, an embedding and a dataset.yaml
spatialscape build demo-src/dataset.yaml         # -> demo-src/bundles/synthetic
spatialscape serve demo-src/bundles --open       # viewer + data at http://127.0.0.1:8787/
```

## Your own data

Inside your project folder, from a saved R object (`SpatialExperiment` / `SingleCellExperiment` as `.rds` or `.rda`, parsed in Python, no R needed) or from AnnData / SpatialData files:

```bash
spatialscape init analysis/spe_dlpfc.rds --id dlpfc --name "Human DLPFC"   # writes dlpfc.yaml, a menu of the data
# edit dlpfc.yaml: keep the annotations you want, name them, pick colors and the opening gene
spatialscape build dlpfc.yaml                                              # -> bundles/dlpfc; rerun after any edit
spatialscape serve bundles --open
spatialscape site build bundles -o site                                    # viewer + gallery + data, ready to upload
```

`init` maps the columns that look like spatial domains, cell types and QC metrics and lists every other column as a comment, so most edits are deleting or uncommenting a line. `build` is incremental: a rename or a new palette takes seconds, a re-exported file rebuilds that one sample. For a gallery of several datasets with a title, paper links and "coming soon" cards, `spatialscape site init` writes a `site.yaml` and `spatialscape site build site.yaml` builds it.

```
myproject/
  analysis/spe_dlpfc.rds        your object, never modified
  spatialscape/
    dlpfc.yaml                  yours to edit: samples, annotations, names, colors
    site.yaml                   yours to edit: title, cards, paper links (optional)
    bundles/dlpfc/              the built dataset: upload this to a data host
    bundles/.cache/             R objects converted to AnnData; local only
    site/                       the finished website: upload this
```

The [documentation](https://mictott.github.io/spatialscape/docs/) walks through every step:
[how it fits together](https://mictott.github.io/spatialscape/docs/guide/getting-started#how-it-fits-together),
[writing dataset.yaml](https://mictott.github.io/spatialscape/docs/guide/dataset-yaml),
[making changes](https://mictott.github.io/spatialscape/docs/guide/changes),
[publishing a site](https://mictott.github.io/spatialscape/docs/guide/publish) and the
[CLI reference](https://mictott.github.io/spatialscape/docs/reference/cli/).

## What it looks like

<p align="center">
  <a href="https://mictott.github.io/spatialscape/docs/"><img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/screenshots/dacc-layers.png" width="840" alt="Seventeen Visium sections of human dACC on one canvas, H&E under cortical layer labels"></a>
</p>
<p align="center"><sub>Seventeen Visium sections of human dorsal anterior cingulate cortex on one canvas: H&amp;E under PRECAST layer labels, one legend for all of them.</sub></p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/screenshots/gallery.png" width="49%" alt="The landing gallery with thumbnails rendered at build time">
  <img src="https://raw.githubusercontent.com/MicTott/spatialscape/main/docs/public/screenshots/bla-umaps.png" width="49%" alt="snRNA-seq UMAPs of three species sharing one cell type legend">
</p>
<p align="center"><sub>Left: the gallery that <code>site build</code> writes, thumbnails rendered at build time. Right: basolateral amygdala nuclei from three species, one UMAP each, one shared cell type legend.</sub></p>

## What you get

| In the viewer | In the pipeline |
|---|---|
| Color by gene, by two blended gene sets, by any annotation or by cell type weights | Visium, Visium HD, Xenium, MERFISH and snRNA-seq in one dataset, laid out in microns |
| Filter independently of color: a gene threshold, a QC range, a category | H&E and fluorescence images as OME-Zarr pyramids under the points |
| Hover for every annotation; lasso a region for composition, gene statistics and a CSV of cell ids | Spatial-domain outlines traced at build time; cell boundary polygons at high zoom |
| A dot plot of the current gene by annotation that doubles as a filter | Dataset-level vocabularies: one label, one code, one color across samples and platforms |
| A split view with the snRNA-seq embedding, resizable, left or right | Validation of every bundle, locally and over HTTP (CORS and Range checks) |
| Copy a link to the exact view; export a PNG with legend and scale bar | Incremental builds with a per-sample fingerprint; a conversion cache for R objects |

## How it works

`spatialscape build` writes a *bundle*: a folder of static files holding `manifest.json`, the gene lists and, per sample, a gene-major uint8 expression array (sharded Zarr v3), positions in microns, categorical codes, images, outlines and polygons. The viewer (React 19, deck.gl 9, Viv, zarrita) draws every sample in one WebGL context, decodes in a worker and recolors by uploading one byte per cell. Details: [bundle format](https://mictott.github.io/spatialscape/docs/reference/format), [architecture](https://mictott.github.io/spatialscape/docs/reference/architecture).

## Repository

```
app/       the viewer: Vite + React 19 + TypeScript (deck.gl 9, Viv, zarrita, Zustand)
python/    the spatialscape CLI (anndata, zarr v3, pydantic, rds2py); the built viewer ships inside the wheel
docs/      the documentation site (VitePress); the CLI pages are generated from the help text
examples/  dataset yamls for the LIBD amygdala, dACC and cross-species BLA datasets, and the synthetic demo
```

## Development

```bash
git clone https://github.com/MicTott/spatialscape && cd spatialscape
python3 -m venv python/.venv && python/.venv/bin/pip install -e "python[dev]"
npm install
npm run dev                                                   # viewer at http://127.0.0.1:5173
python/.venv/bin/spatialscape serve examples --port 8787      # data; the dev server proxies /examples to it
python/.venv/bin/python -m pytest python/tests && npm test && npm run e2e
```

`npm run build && python/.venv/bin/python python/scripts/bundle_app.py` refreshes the viewer copy inside the package. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Status

Built for the Lieber Institute for Brain Development's spatial transcriptomics and snRNA-seq data releases, and meant for any lab that wants to put a dataset online next to a paper. Planned: multi-frame compare, named waypoints, more LIBD datasets.

MIT license. Cite with [CITATION.cff](CITATION.cff).
