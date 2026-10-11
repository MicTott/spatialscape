# `spatialscape outlines`

Re-trace annotation boundaries from the arrays already in a bundle.

`build` traces outlines with the default settings. This command redoes them with other sizes: labels are rasterized at half the cell spacing, majority-smoothed, cleaned of small features, traced with marching squares and simplified. Cells labelled `NA` are treated as unknown and filled by their neighbours. Results go to `samples/<id>/outlines/<field>.json` and the manifest; no source data is read.

## Usage

```bash
spatialscape outlines <CONFIG> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `CONFIG` | path | *required* | Path to the dataset yaml. Relative paths inside it resolve against its own folder. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | — | Bundle directory. Default: `bundles/<id>` next to the yaml. |
| `--sample` | text, repeatable | — | Only these sample ids (repeatable). Default: every spatial sample. |
| `--field` | text, repeatable | — | Only these categorical field ids (repeatable). Default: every categorical field the sample carries. |
| `--smooth-um` | float | `150.0` | Side of the majority-vote smoothing window, in microns. Larger values merge small islands into their neighbours. |
| `--min-feature-um` | float | `300.0` | Islands and holes smaller than this (per side, in microns) are removed before tracing. |

## Examples

**All spatial samples, all categorical fields**

```bash
spatialscape outlines dlpfc.yaml
```

**Finer outlines for one Xenium donor**

```bash
spatialscape outlines amygdala.yaml --sample xen_Br9280 --field domain --smooth-um 80 --min-feature-um 150
```

## See also

- [`spatialscape build`](./build)
- Guide: [Using the viewer: outlines](/guide/viewer#outlines)
