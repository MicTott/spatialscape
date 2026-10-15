# Getting started

spatialscape is one Python package: a command-line tool that turns your data into *bundles*
(folders of static files), and the web viewer that streams them, shipped inside the same install.

## Install

```bash
pip install spatialscape
spatialscape --version
```

Python 3.11 or newer. `sscape` is a short alias for every command.

## Just looking at an object?

In a notebook, `spatialscape.show(adata)` builds the object straight from memory and opens the viewer under the
cell; `s.selection()` hands back the cells you lasso. The same works from R through reticulate and one
`saveRDS`. See [In a notebook: show()](./notebooks). The rest of this page is the path to a dataset you edit,
rebuild and publish.

## Try it in two minutes

```bash
spatialscape synth demo-src                      # two fake sections, an embedding and a dataset.yaml
spatialscape build demo-src/dataset.yaml         # -> demo-src/bundles/synthetic
spatialscape serve demo-src/bundles --open       # viewer + data from one local address
```

`serve` opens a gallery of every bundle in the folder. Click one: double-click a section to focus it,
step through sections with the arrow keys, type a gene, color by an annotation, lasso a region.

::: tip Nothing leaves your machine
The viewer is plain JavaScript served from `127.0.0.1`, and it reads the bundle from the same address.
There is no upload, no account and no server process beyond this one.
:::

## How it fits together

Two kinds of file are yours to edit, everything else is built from them:

```
your data                     you write / edit                    spatialscape builds
─────────────────────────     ─────────────────────────────────   ──────────────────────────────────
spe.rds, sce.rds        ──▶   amygdala.yaml   (one per dataset) ──▶  bundles/amygdala/   the dataset, upload this
*.h5ad, *.zarr          ──▶   dlpfc.yaml                        ──▶  bundles/dlpfc/
                              site.yaml       (optional gallery) ──▶  site/               viewer + gallery + bundles, upload this
```

Inside your project folder that looks like this after the steps below:

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

## Your own data in three steps

Work inside your project folder: everything a command writes lands next to the yaml it read.

1. **Describe.** Point `init` at the data: a saved R object (a `SpatialExperiment` or
   `SingleCellExperiment` as `.rds` / `.rda`) or a glob of AnnData files. It writes `<id>.yaml`, a menu of
   what the data contains: the columns that look like spatial domains, cell types and QC metrics are
   already mapped, every other column is a comment, and so is every optional setting.

   ```bash
   spatialscape init analysis/spe_dlpfc.rds --id dlpfc --name "Human DLPFC"
   ```

2. **Edit, build, look.** Open `dlpfc.yaml`, keep the annotations you want, name them, pick the opening
   gene and a palette. Build, then open the result. Rerun `build` after any edit: only the samples whose
   inputs or settings changed are rebuilt, so names, colors and defaults apply in seconds.

   ```bash
   spatialscape build dlpfc.yaml                  # -> bundles/dlpfc next to the yaml
   spatialscape serve bundles --open
   ```

3. **Publish.** `spatialscape site build bundles -o site` writes a folder to upload to any static host.
   For a gallery with a title, several datasets, paper links or "coming soon" cards, describe it in
   `site.yaml` and build that instead.

   ```bash
   spatialscape site init dlpfc.yaml --title "Our lab's spatial data"
   spatialscape site build site.yaml              # -> site/ next to site.yaml
   ```

[Writing dataset.yaml](./dataset-yaml) explains the menu, [Making changes](./changes) maps every common
edit to the line to change, and [Publish your own site](./publish) covers hosting.

## The hosted viewer

<https://mictott.github.io/spatialscape/> is the same viewer, deployed from this repository. It opens any
bundle on any host with `?d=<url>`, which is handy for sharing data that is already online. Opening a
`127.0.0.1` bundle from it depends on your browser's local-network permissions, so for local work use
`spatialscape serve`.

## Working on the viewer itself

Only needed to change the app:

```bash
git clone https://github.com/MicTott/spatialscape && cd spatialscape
npm install
npm run dev          # http://127.0.0.1:5173, proxies /examples to `spatialscape serve examples --port 8787`
```
