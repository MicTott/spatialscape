# `spatialscape outlines`

Trace annotation boundaries from the arrays already in a bundle.

Labels are rasterized at half the cell spacing, majority-smoothed, cleaned of small features, traced with marching squares and simplified. Cells labelled `NA` are treated as unknown and filled by their neighbours. Results go to `samples/<id>/outlines/<field>.json` and the manifest. No source data is needed, so this is cheap to re-run while tuning the two size parameters.

## Usage

```bash
spatialscape outlines <CONFIG> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `CONFIG` | path | *required* | Path to `dataset.yaml`. Relative paths inside it resolve against its own folder. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | *required* | Bundle directory to write (created if missing). |
| `--sample` | text, repeatable | — | Only these sample ids (repeatable). Default: every spatial sample. |
| `--field` | text, repeatable | — | Only these categorical field ids (repeatable). Default: every categorical field the sample carries. |
| `--smooth-um` | float | `150.0` | Side of the majority-vote smoothing window, in microns. Larger values merge small islands into their neighbours. |
| `--min-feature-um` | float | `300.0` | Islands and holes smaller than this (per side, in microns) are removed before tracing. |

## Examples

**All spatial samples, all categorical fields**

```bash
spatialscape outlines dataset.yaml -o bundles/amygdala
```

**Finer outlines for one Xenium donor**

```bash
spatialscape outlines dataset.yaml -o bundles/amygdala --sample xen_Br9280 --field domain --smooth-um 80 --min-feature-um 150
```

## See also

- [`spatialscape build`](./build)
- Guide: [Using the viewer: outlines](/guide/viewer#outlines)
