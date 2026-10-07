# `spatialscape add-sample`

Rebuild one sample inside an existing bundle.

Reads the sample's entry from `dataset.yaml`, rebuilds only that sample folder, and refreshes `manifest.json`, `genes.json` and `features.json`. Other samples are untouched.

## Usage

```bash
spatialscape add-sample <CONFIG> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `CONFIG` | path | *required* | Path to `dataset.yaml`. Relative paths inside it resolve against its own folder. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | *required* | Bundle directory to write (created if missing). |
| `--sample` | text | *required* | Id of the sample to (re)build, as listed by `plan`. |
| `--no-shard` | flag | `off` | Write one file per gene instead of sharded Zarr. |
| `--allow-vocab-append`, `--no-allow-vocab-append` | flag | `on` | Allow category labels not yet in the dataset vocabulary. They are appended, so existing codes never change; with `--no-allow-vocab-append` a new label is an error. |

## Examples

**Rebuild one donor after fixing its coordinates**

```bash
spatialscape add-sample dataset.yaml -o bundles/amygdala --sample vis_Br2743
```

**Fail instead of silently extending a vocabulary**

```bash
spatialscape add-sample dataset.yaml -o bundles/amygdala --sample xen_new --no-allow-vocab-append
```

## See also

- [`spatialscape build`](./build)
- [`spatialscape refresh`](./refresh)
- Guide: [Building and validating](/guide/building#incremental-workflows)
