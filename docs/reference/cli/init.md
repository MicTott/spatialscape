# `spatialscape init`

Write a dataset yaml that doubles as a menu of what the data contains.

The yaml gets one `samples:` entry per argument. Inside it, `fields:` already maps the columns that look like spatial domains, cell types and the usual QC metrics (total counts, detected genes, mito percent), and every other column is listed as a comment with its type and levels, so showing one more annotation is uncommenting a line. Optional settings (opening gene, palette, thumbnail, layout) are present as comments. The file builds as written; edit it, then run `build`.

## Usage

```bash
spatialscape init <PATHS>... [OPTIONS]
```

## Arguments

| Argument | Type | Default | Description |
|---|---|---|---|
| `PATHS` | text | *required* | What to describe: R objects (`.rds` / `.rda` holding a SpatialExperiment, SingleCellExperiment or Seurat object), globs of sample files such as `'data/*/adata.h5ad'` (quoted, so the shell does not expand them), and results tables of differential expression tests (`.csv` / `.tsv` / `.parquet`, one row per gene). One `samples:` entry per object or glob, one `comparisons:` entry per table. |

## Options

| Option | Type | Default | Description |
|---|---|---|---|
| `-o`, `--out` | path | — | Where to write the yaml. Default: `<id>.yaml` in the current folder. |
| `--id` | text | — | Dataset id: used in `?d=<id>` and as the bundle folder name. Default: the object's file name, or the folder a glob starts in. |
| `--name` | text | — | Human-readable dataset name. Default: the id, prettified. |
| `--platform` | text | — | Platform of the spatial samples: `visium`, `visium_hd`, `xenium`, `merfish` or `other`. Default: guessed from the columns (`array_row` / `array_col` mean Visium when the grid fits one Visium array or the spots split into capture areas of Visium size, Visium HD when the grid is larger; Xenium's cell metrics mean Xenium), else `visium`; the yaml says which. Objects and files without spatial coordinates become `snrnaseq` embeddings regardless. |
| `--table` | text | — | Table key inside a SpatialData store. |

## Examples

**A SpatialExperiment saved from R (one sample per sample_id)**

```bash
spatialscape init analysis/spe_visium.rds --id dlpfc --name "Human DLPFC"
```

**Xenium donors in sibling folders**

```bash
spatialscape init "xenium/*/adata.zarr" --platform xenium --id amygdala --name "Human amygdala"
```

**A spatial object and the snRNA-seq reference behind its labels, one dataset**

```bash
spatialscape init analysis/spe_visium.rds analysis/sce_snrnaseq.rds --id dlpfc
```

## See also

- [`spatialscape build`](./build)
- [`spatialscape inspect`](./inspect)
- Guide: [Writing dataset.yaml](/guide/dataset-yaml)
