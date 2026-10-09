# `spatialscape convert`

Turn R objects (SpatialExperiment / SingleCellExperiment saved as .rds or .rda) into build inputs.

No R needed: the file is parsed in Python. A spatial object becomes one folder per sample under `OUT` (`adata.h5ad`, the H&E as PNG, SpaceRanger-style scale factors), which `init` and `build` pick up with no image or scale settings; an object without spatialCoords becomes `OUT/<name>.h5ad` with its UMAP in `obsm/X_umap`, ready to be an embedding sample. Needs enough memory to hold the object (roughly what R needs).

## Usage

```bash
spatialscape convert <OBJECTS>... [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `OBJECTS` | path | *required* | R objects: `.rds` or `.rda`/`.RData` files holding a SpatialExperiment or SingleCellExperiment. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | *required* | Folder to write into (created if missing). |
| `--assay` | text | `logcounts` | Assay written as the expression matrix. Counts are fine too; `build` normalizes them. |
| `--cols` | text | — | Comma-separated colData columns to keep as annotations. Default: all. Fewer columns keep files small and the viewer's field list short. |
| `--sample-col` | text | `sample_id` | colData column that defines samples (spatial objects only). |
| `--embedding` | text | — | reducedDims entry to use as the 2-D embedding (objects without spatialCoords). Default: UMAP if present. |
| `--microns-per-pixel` | float | — | Microns per coordinate unit, when known (e.g. SpaceRanger's `microns_per_pixel`; required for Visium HD). Default: derive a Visium spot diameter from the spot spacing. |
| `--object` | text | — | Which object to take from an `.rda` that holds several. |

## Examples

**A Visium SpatialExperiment, keeping four annotations**

```bash
spatialscape convert spe_visium.rds -o data/visium --assay logcounts --cols BayesSpace_domain,sum_umi,sum_gene,expr_chrM_ratio
```

**A Visium HD object whose coordinates are pixels of a known size**

```bash
spatialscape convert spe_hd.rds -o data/hd --microns-per-pixel 0.2525
```

**An snRNA-seq SingleCellExperiment with a UMAP**

```bash
spatialscape convert sce_snrnaseq.rds -o data/sn --cols fine_celltype,broad_celltype,subject
```

## See also

- [`spatialscape inspect`](./inspect)
- [`spatialscape init`](./init)
- [`spatialscape build`](./build)
- Guide: [Preparing your data: from R](/guide/preparing-data#from-r)
