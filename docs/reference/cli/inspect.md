# `spatialscape inspect`

Print what a sample file contains, to help edit the dataset yaml.

Lists every `obs` column with its type and number of levels (with example values for categoricals), the `obsm` keys and their shapes, the layers, and any `uns` keys that look like scale information. `init` writes the same information into a yaml you can edit; `inspect` only prints it.

## Usage

```bash
spatialscape inspect <PATH> [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `PATH` | path | *required* | An `.h5ad` file, an AnnData Zarr store, a SpatialData Zarr store, or an R `.rds` / `.rda` holding a SpatialExperiment / SingleCellExperiment. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `--table` | text | — | Table key inside a SpatialData store (required when the store has more than one). |

## Examples

**A SpatialExperiment saved from R**

```bash
spatialscape inspect analysis/spe_visium.rds
```

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
- Guide: [Where your data comes from](/guide/preparing-data)
