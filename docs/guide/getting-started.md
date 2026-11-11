# Getting started

The spatialscape Python package includes a command-line tool and a browser viewer. The CLI converts
data into *bundles*: folders containing the arrays, images and metadata the viewer reads.

| Task | Workflow |
|---|---|
| View an object and retrieve selected cells in a notebook | `spatialscape.show(adata)` |
| Build a local viewer with an editable configuration | `init` → edit the YAML → `build` → `serve` |
| Publish datasets online | `site build`, then upload the output folder to a static host |

## Install

```bash
pip install spatialscape
spatialscape --version
```

Python 3.11 or newer. `sscape` is a short alias for every command.

::: details The development version
The package carries the built viewer, so an install from the repository needs Node once:

```bash
git clone https://github.com/MicTott/spatialscape && cd spatialscape
npm ci && npm run build && python python/scripts/bundle_app.py   # builds the viewer into the Python package
pip install ./python                                            # or `pip install -e python` to hack on it
```

Without that step `site build` stops with "this install has no packaged viewer" and `serve` serves the bundles without one.
:::

## View an object in a notebook {#goal-1-just-look-at-an-object}

In a notebook, `spatialscape.show(adata)` builds the object straight from memory and opens the viewer under the
cell; `s.selection()` hands back the cells you lasso. The same works from R through reticulate and one
`saveRDS`. See [In a notebook: show()](./notebooks). The rest of this page is the path to a dataset you edit,
rebuild and publish.

## Try a synthetic dataset {#try-the-full-path-in-two-minutes}

```bash
spatialscape synth demo-src                      # two synthetic sections, an embedding and a dataset.yaml
spatialscape build demo-src/dataset.yaml         # -> demo-src/bundles/synthetic
spatialscape serve demo-src/bundles --open       # viewer + data from one local address
```

`serve` opens a gallery of every bundle in the folder. Click one: double-click a section to focus it,
step through sections with the arrow keys, type a gene, color by an annotation, lasso a region.

::: tip Local preview
`serve` runs the viewer and serves the bundle from `127.0.0.1`. It does not upload the bundle.
A copied link points to that local address and requires the server to be running on the computer that opens it.
Publish the site before sharing links with others.
:::

## How it fits together

Edit the dataset configuration and, optionally, a gallery configuration. The CLI builds the output folders from them:

```
your data                     you write / edit                    spatialscape builds
─────────────────────────     ─────────────────────────────────   ──────────────────────────────────
spe.rds, sce.rds        ──▶   dlpfc.yaml      (one per dataset) ──▶  bundles/dlpfc/      the dataset, upload this
*.h5ad, *.zarr          ──▶   mouse_brain.yaml                  ──▶  bundles/mouse_brain/
                              site.yaml       (optional gallery) ──▶  site/               viewer + gallery + bundles, upload this
```

Inside your project folder that looks like this after the steps below (the commands run from `myproject/spatialscape/`):

```
myproject/
  analysis/spe_dlpfc.rds           your object, never modified
  spatialscape/
    dlpfc.yaml                     written by `init`, edited by you: samples, annotations, names, colors
    site.yaml                      written by `site init`, edited by you: title, cards, paper links (optional)
    bundles/
      dlpfc/                       written by `build`: manifest.json, genes.json, samples/<id>/..., thumbnail.png
      .cache/dlpfc/                R objects converted to AnnData; reused by later builds, never uploaded
    site/                          written by `site build`: index.html, assets/, datasets.json, dlpfc/
```

| File or folder | Who writes it | What to do with it |
|---|---|---|
| `<id>.yaml` | `init`, then you | edit it; rerun `build` after every change |
| `site.yaml` | `site init`, then you | edit it; rerun `site build` |
| `bundles/<id>/` | `build` | open with `serve`; upload to a data host ([format](../reference/format)) |
| `bundles/.cache/` | `build` | leave it alone; delete it to reclaim space, the next `build` recreates it |
| `site/` | `site build` | upload to any static host, or `serve site` to preview |

Every command prints the paths it wrote and the next command to run.

## Build a dataset from your data {#goal-2-your-own-data-on-your-machine}

Create a folder for the configuration and build outputs, such as `spatialscape/` in the layout above.
Input data can live elsewhere. Relative paths in the YAML resolve from the configuration file's folder;
`build` writes to `bundles/<id>` beside it unless you specify `-o`.

1. **Create a configuration.** Run `init` on a saved R object (`SpatialExperiment`, `SingleCellExperiment`
   or Seurat, as `.rds` / `.rda`) or a glob of AnnData files. It writes `<id>.yaml` in the current folder,
   with inferred mappings for spatial domains, cell types and QC metrics. Additional columns and optional
   display settings appear as comments. Check the reported platform, coordinate units and expression
   layer, and correct them in the YAML if needed.

   ```bash
   mkdir -p spatialscape && cd spatialscape
   spatialscape init ../analysis/spe_dlpfc.rds --id dlpfc --name "Human DLPFC"     # -> ./dlpfc.yaml
   ```

2. **Review the settings and build.** Open `dlpfc.yaml`, choose the annotations to display, and set their
   names, colors and the initial view. Run `build`, then open the result. The first build reads the inputs
   and writes every sample; saved R objects are converted into a local cache. Later builds reuse unchanged
   samples. Changes to display names, palettes and defaults update the dataset metadata without rebuilding
   the sample arrays. Build time depends on the input size, included layers and hardware.

   ```bash
   spatialscape build dlpfc.yaml                  # -> bundles/dlpfc next to the yaml
   spatialscape serve bundles --open
   ```

::: tip DLPFC example
The spatialLIBD DLPFC `SpatialExperiment` (12 Visium sections, 47,681 spots) is the first example in the
[examples repository](./examples): `visium-human-dlpfc/build.sh` downloads it, runs `init`, builds the committed
YAML and validates the result. Compare the generated and committed configurations to see which settings
the example uses.
:::

[Writing dataset.yaml](./dataset-yaml) explains the configuration and [Making changes](./changes) maps every common
edit to the line to change. Your platform's page ([sequencing-based](./platforms/sequencing),
[imaging-based](./platforms/imaging), [single-cell](./platforms/single-cell)) lists the optional layers (images,
cell shapes, transcripts) and the files each requires.

## Publish a site {#goal-3-publish}

`spatialscape site build bundles -o site` writes a folder with the viewer, a gallery and your bundles, to
upload to any static host. For a gallery with a title, several datasets, paper links or "coming soon"
cards, describe it in `site.yaml` and build that instead.

```bash
spatialscape site init dlpfc.yaml --title "Our lab's spatial data"
spatialscape site build site.yaml              # -> site/ next to site.yaml
spatialscape serve site                        # what a visitor will see
```

[Publish your own site](./publish) has one complete route for GitHub Pages and the object-storage setup
for data too large for it.

## The hosted viewer

<https://mictott.github.io/spatialscape/> is the same viewer, deployed from this repository. It opens any bundle on
any host with `?d=<url>`, which is handy for sharing data that is already online; the public examples are its gallery
at [/examples/](https://mictott.github.io/spatialscape/examples/). Opening a `127.0.0.1` bundle from it depends on
your browser's local-network permissions, so for local work use `spatialscape serve`.

## Working on the viewer itself

Only needed to change the app:

```bash
git clone https://github.com/MicTott/spatialscape && cd spatialscape
npm install
npm run dev          # http://127.0.0.1:5173, proxies /examples to `spatialscape serve examples --port 8787`
```
