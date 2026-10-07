# CLI commands

All commands are available as `spatialscape <command>` and `sscape <command>`. Run any command with `--help` for the full option list.

## `init`

```bash
spatialscape init <globs...> [--platform xenium] [--id my_dataset] [--name "My dataset"] -o dataset.yaml
```

Writes a starter `dataset.yaml` with one glob entry per pattern, `fields: auto` and `images: auto`.

## `plan`

```bash
spatialscape plan dataset.yaml
```

Prints the expanded sample table (globs, templates, defaults and platform blocks applied) without reading any data.

## `inspect`

```bash
spatialscape inspect <h5ad | zarr | spatialdata.zarr> [--table KEY]
```

Lists obs columns with types and levels, obsm keys, layers, and `uns` keys that look like scale information.

## `build`

```bash
spatialscape build dataset.yaml -o <bundle> [--no-shard] [-q]
```

Builds every sample, writes dataset files, renders thumbnails and validates. `--no-shard` writes one file per gene instead of sharded arrays (for hosts without Range support). Exit code 1 if validation finds problems.

## `add-sample`

```bash
spatialscape add-sample dataset.yaml -o <bundle> --sample <id> [--no-shard] [--allow-vocab-append / --no-allow-vocab-append]
```

Rebuilds one sample into an existing bundle and refreshes the dataset files. Vocabularies only grow; with `--no-allow-vocab-append` a new label is an error.

## `refresh`

```bash
spatialscape refresh dataset.yaml -o <bundle>
```

Rewrites `manifest.json`, `genes.json` and `features.json` from the samples already in the bundle. Use after changing field names, palette, feature groups, layout or thumbnail settings.

## `outlines`

```bash
spatialscape outlines dataset.yaml -o <bundle> [--sample ID]... [--field ID]... [--smooth-um 150] [--min-feature-um 300]
```

Traces categorical boundaries from the bundle's own arrays (no source data needed) and records them in the manifest.

## `thumbnails`

```bash
spatialscape thumbnails <bundle> [--hero SAMPLE_ID] [--no-per-sample]
```

Renders `thumbnail.png` for the dataset (one section colored by the default annotation) and for each sample.

## `validate`

```bash
spatialscape validate <bundle directory | https://host/bundle>
```

Local: schema, array shapes and chunking, codes within vocabularies, id blocks, polygon sizes, image sizes. Remote: manifest fetch with CORS headers and a `Range` request on one expression chunk expecting `206`.

## `serve`

```bash
spatialscape serve <directory> [--port 8787] [--host 127.0.0.1]
```

Development server with CORS, HTTP Range and `Timing-Allow-Origin`. Not for production.

## `synth`

```bash
spatialscape synth <directory> [--cells 2000] [--genes 50]
```

Writes two synthetic sections with images and polygons, plus an embedding and a `dataset.yaml`, for tests and demos.
