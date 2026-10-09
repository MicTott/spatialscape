# Getting started

spatialscape is one Python package: a command-line tool that turns AnnData / SpatialData into *bundles*
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
spatialscape build demo-src/dataset.yaml -o bundles/demo
spatialscape serve bundles --open                # viewer + data from one local address
```

`serve` opens a gallery of every bundle in the folder. Click one: double-click a section to focus it,
step through sections with the arrow keys, type a gene, color by an annotation, lasso a region.

::: tip Nothing leaves your machine
The viewer is plain JavaScript served from `127.0.0.1`, and it reads the bundle from the same address.
There is no upload, no account and no server process beyond this one.
:::

## Your own data in four steps

1. **Bring the data.** AnnData (`.h5ad` / `.zarr`) and SpatialData stores are read directly. R objects too:
   `spatialscape convert spe.rds -o data/visium` turns a saved `SpatialExperiment` or `SingleCellExperiment`
   into build inputs, images and scale factors included. See [Preparing your data](./preparing-data).
2. **Describe** the dataset in a `dataset.yaml`. `spatialscape init` writes a draft; `spatialscape inspect`
   lists the columns available in a file. See [Writing dataset.yaml](./dataset-yaml).
3. **Build** with `spatialscape build dataset.yaml -o bundles/<id>`. The build validates itself and renders
   thumbnails. See [Building and validating](./building).
4. **Adjust** names, colors, the opening gene and which annotations show, in the yaml; `refresh` applies most of it in a second. See [Making changes](./changes).
5. **Publish** with `spatialscape site build bundles/* -o site` and upload the folder, or host the bundles on
   object storage and share `https://<viewer>/?d=https://<data-host>/<id>`. See [Publish your own site](./publish).

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
