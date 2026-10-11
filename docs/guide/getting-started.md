# Getting started

spatialscape is one Python package: a command-line tool that turns your data into *bundles*
(folders of static files), and the web viewer that streams them, shipped inside the same install.

## Install

```bash
pip install spatialscape
spatialscape --version
```

Python 3.11 or newer. `sscape` is a short alias for every command.

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

## Your own data in three steps

Work inside your project folder: everything a command writes lands next to the yaml it read, and every
output path is printed.

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
