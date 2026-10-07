# `spatialscape inspect`

Print what a sample file contains, to help write `dataset.yaml`.

Lists every `obs` column with its type and number of levels (with example values for categoricals), the `obsm` keys and their shapes, the layers, and any `uns` keys that look like scale information.

## Usage

```bash
spatialscape inspect <PATH> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `PATH` | path | *required* | An `.h5ad` file, an AnnData Zarr store, or a SpatialData Zarr store. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--table` | text | — | Table key inside a SpatialData store (required when the store has more than one). |

## Examples

**An h5ad written from R**

```bash
spatialscape inspect Br2743.h5ad
```

**A SpatialData store with several tables**

```bash
spatialscape inspect store.zarr --table cells
```

## See also

- [`spatialscape init`](./init)
- Guide: [Preparing your data](/guide/preparing-data)
