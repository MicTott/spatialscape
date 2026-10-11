# `spatialscape thumbnails`

Re-render `thumbnail.png` for the dataset and for each sample.

One section is drawn from the bundle's own coordinates, colored by the default annotation (or the first categorical field the sample carries). `build` runs this automatically.

## Usage

```bash
spatialscape thumbnails <OUT> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `OUT` | path | *required* | Bundle directory. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--hero` | text | — | Sample shown on the dataset thumbnail. Default: `thumbnail_sample` from the yaml, else the first spatial sample in layout order. |
| `--no-per-sample` | flag | `off` | Skip the per-sample thumbnails. |

## Examples

**Lead with a particular section**

```bash
spatialscape thumbnails bundles/dlpfc --hero vis_Br8325
```

## See also

- [`spatialscape build`](./build)
- Guide: [The gallery: site.yaml](/guide/registry)
