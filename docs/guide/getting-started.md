# Getting started

spatialscape has two parts:

- **The viewer**, a static web app. The hosted copy at <https://mictott.github.io/spatialscape/> can open any bundle on any host; you never need to deploy it yourself unless you want your own URL or a registry.
- **The CLI**, `spatialscape`, a Python package that converts your data into a *bundle*: a folder of static files the viewer streams.

## Install the CLI

```bash
pip install spatialscape
```

Python 3.11 or newer. `sscape` works as a short alias for every command.

## Try it with synthetic data

```bash
spatialscape synth demo-src                 # two fake sections + an embedding + dataset.yaml
spatialscape build demo-src/dataset.yaml -o bundles/demo
spatialscape serve bundles --port 8787
```

Open <https://mictott.github.io/spatialscape/?d=http://127.0.0.1:8787/demo>. The hosted viewer loads the bundle straight from your machine; nothing is uploaded.

::: tip Why does that work?
The viewer is plain JavaScript running in your browser. It fetches the bundle with ordinary HTTP requests, and `spatialscape serve` answers them with the two headers that matter: CORS and HTTP Range.
:::

## Your own data in four steps

1. **Export** each sample as AnnData (`.h5ad` or `.zarr`) or a SpatialData store. From R, write your `SpatialExperiment` with zellkonverter or anndataR. See [Preparing your data](./preparing-data).
2. **Describe** the dataset in a `dataset.yaml`. `spatialscape init` writes a draft; `spatialscape inspect` shows the columns available in a file. See [Writing dataset.yaml](./dataset-yaml).
3. **Build** with `spatialscape build dataset.yaml -o bundles/<id>`. The build validates itself and renders thumbnails. See [Building and validating](./building).
4. **Host** the bundle folder anywhere static files live, then share `https://<viewer>/?d=https://<data-host>/<id>`. See [Hosting](./hosting).

## Run the viewer locally

Only needed if you want to change the app or run your own copy:

```bash
git clone https://github.com/MicTott/spatialscape && cd spatialscape
npm install
npm run dev          # http://127.0.0.1:5173
```

In development the dev server proxies `/examples` to `spatialscape serve examples --port 8787`, so the committed synthetic bundle opens with `?d=synthetic`.
