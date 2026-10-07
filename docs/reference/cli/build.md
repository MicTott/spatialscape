# `spatialscape build`

Build a complete bundle from `dataset.yaml`.

For every sample: read the object, resolve automatic fields and images, quantize and shard the expression matrix, convert coordinates to microns, write observation arrays and ids, pack polygons, convert images, and trace annotation outlines. Then write the dataset-level files, render thumbnails and run the same checks as `validate`. Exits with status 1 if validation reports problems.

## Usage

```bash
spatialscape build <CONFIG> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `CONFIG` | path | *required* | Path to `dataset.yaml`. Relative paths inside it resolve against its own folder. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | *required* | Bundle directory to write (created if missing). |
| `--no-shard` | flag | `off` | Write one file per gene instead of sharded Zarr. Larger file counts, but works on hosts without HTTP Range support (e.g. GitHub Pages). |
| `-q`, `--quiet` | flag | `off` | Suppress per-sample progress output. |

## Examples

**Standard build**

```bash
spatialscape build dataset.yaml -o bundles/amygdala
```

**For GitHub Pages or other hosts without Range support**

```bash
spatialscape build dataset.yaml -o site/examples/demo --no-shard
```

## See also

- [`spatialscape validate`](./validate)
- [`spatialscape add-sample`](./add-sample)
- [`spatialscape refresh`](./refresh)
- [`spatialscape serve`](./serve)
- Guide: [Building and validating](/guide/building)
