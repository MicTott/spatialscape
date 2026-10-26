# Single-cell and multiome

snRNA-seq and scRNA-seq references, snATAC and 10x Multiome: no tissue, an embedding instead. A single-cell sample
is drawn by its UMAP in a pane beside the sections, shares genes, annotations and colours with them, and can carry
genome tracks when it has fragments.

## The minimum

An object with an embedding: a `SingleCellExperiment` or Seurat object saved from R, or an h5ad with `obsm/X_umap`.

```bash
spatialscape init analysis/sce_bla.rds --id sn               # no spatialCoords: one embedding sample
spatialscape build sn.yaml && spatialscape serve bundles --open
```

```yaml
samples:
  - path: analysis/sce_bla.rds
    id: sn_bla
    name: snRNA-seq (BLA, 5 donors)
    fields: { celltype: fine_celltype, total_counts: sum }
```

`init` sets `platform: snrnaseq`, `kind: embedding` and the embedding (`coords: obsm/X_umap` for a file,
`embedding: UMAP` for an R object) when the object has no spatial coordinates. The embedding is rescaled to a fixed
extent, so point size and zoom behave like a section's.

## Beside the sections

The value of a reference is next to the tissue. List it in the same yaml as the sections and map its cell type
column to the **same field id** the sections use:

```yaml
platforms:
  xenium:
    fields: { celltype: first_type }             # RCTD's label on the cells
samples:
  - glob: xenium/*/adata.h5ad
    platform: xenium
    id: "xen_{name}"
  - path: analysis/sce_bla.rds
    id: sn_bla
    fields: { celltype: fine_celltype }          # the same id: one legend, one set of colours
```

A label gets one code and one colour everywhere, so "Pvalb" is the same green in the UMAP and in the tissue, and
hiding it in the legend hides it in both. Labels that differ in spelling are merged with `aliases` on the field.
The embedding pane and the tissue pane split the canvas; hover, lasso and the gene on screen work in both.

### One object, several panels

Per-class embeddings (excitatory, inhibitory, non-neuronal) come from one object listed three times with `subset:`,
and `layout: { columns: 3 }` lines them up:

```yaml
  - { path: sce.rds, id: sn_exc, name: Excitatory,   subset: { column: broad_class, values: [Excitatory] } }
  - { path: sce.rds, id: sn_inh, name: Inhibitory,   subset: { column: broad_class, values: [Inhibitory] } }
  - { path: sce.rds, id: sn_glia, name: Non-neuronal, subset: { column: broad_class, values: [Glia] } }
```

## Seurat objects

A Seurat object (v3 to v5) works like an SCE: the gene assay is drawn as expression (`assay:` picks `data` or
`counts`), every other assay becomes a set of features next to the genes (`peak: chr1-100-200` for a Signac
`ChromatinAssay`, `motif:` for chromVAR, `activity:` for gene activity), `meta.data` is `obs`, and `embedding:`
names a reduction (`wnn.umap`, `umap.rna`). `spatialscape inspect x.rds` lists all of it.

## Genome tracks (ATAC and multiome)

A sample with fragment files carries pseudobulk accessibility tracks per cell type, built once and streamed by the
viewer's genome panel:

```yaml
  - path: analysis/multiome.rds
    id: multiome
    tracks:
      fragments: { S1: runs/S1/atac_fragments.tsv.gz, S2: runs/S2/atac_fragments.tsv.gz }
      sample_column: fragment_run
      barcode_column: fragment_barcode
      by: [celltype]
      genome: hg38
```

`init` writes this block, commented, with the fragment paths the Seurat object recorded. Streaming two 4 GB fragment
files takes about 15 minutes; bigWigs another tool exported (ArchR, Signac) can be copied in instead. The whole of
it, including `ssh://` paths for fragments on a cluster, is in [Genome tracks](../tracks).

## Next

- [Metadata and comparisons](../comparisons) to put a differential expression result beside the cells.
- [Writing dataset.yaml](../dataset-yaml) for R object settings (`assay`, `sample_col`, `embedding`, `object`).
- [Using the viewer](../viewer#panes-comparing-groups-side-by-side) for the embedding pane and splitting by metadata.
