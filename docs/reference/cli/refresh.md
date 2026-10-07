# `spatialscape refresh`

Rewrite the dataset-level files without rebuilding any sample.

Use after changing field display names, the palette, feature groups, layout order or `thumbnail_sample`. Reads each sample's existing `genes.json` and the current manifest, then rewrites `manifest.json`, `genes.json` and `features.json`.

## Usage

```bash
spatialscape refresh <CONFIG> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `CONFIG` | path | *required* | Path to `dataset.yaml`. Relative paths inside it resolve against its own folder. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | *required* | Bundle directory to write (created if missing). |

## Examples

**After renaming fields or changing the palette**

```bash
spatialscape refresh dataset.yaml -o bundles/amygdala
```

## See also

- [`spatialscape add-sample`](./add-sample)
- [`spatialscape thumbnails`](./thumbnails)
- Guide: [Building and validating](/guide/building#incremental-workflows)
