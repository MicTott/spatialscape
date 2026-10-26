# Metadata and comparisons

Two things that live on the dataset rather than inside a sample: metadata keys that describe each sample
(condition, subject, batch), and the results of a test fit upstream, linked to the sections through those keys.

## Sample metadata

Samples can carry metadata keys, one value per sample: the condition, the subject, sex, genotype, a batch.
The viewer splits the canvas by any such key (one pane per level, see [the viewer guide](./viewer#panes-comparing-groups-side-by-side)),
the hover shows the values, and comparisons will link replicates to their sections through them.

```yaml
meta:                                          # optional: display names and level order
  - { id: condition, name: Condition, levels: [control, stress] }
  - { id: mouse, name: Mouse }

samples:
  - glob: "sections/*/adata.h5ad"
    platform: visium
    meta: { mouse: "{name}", condition: { column: condition } }
  - path: spe_mice.rds
    platform: visium
    meta: { mouse: "{name}", condition: { column: condition } }
```

A value is a string (templated per glob match or per R-object sample, like `id`), or `{ column: x }` to read
it from an obs column that holds one value for the whole sample, which is how most objects carry a
condition. A column with several values in one sample is an error that names them: split the file with
`subset:` or expose the column as an annotation under `fields:` instead. The dataset-level `meta:` list is
optional; keys used only on samples get their id as display name and their levels in order of first use,
and levels a declaration does not list are appended rather than dropped. A value typed in the yaml applies
on the next `build` without rebuilding the sample; a value read from a column is fixed when the sample is
built. `init` lists the columns that are constant within each sample as a commented `# meta:` line.

## Comparisons: results of a test, next to the sections

A dataset can carry differential expression results that were fit upstream, in R or Python, so the viewer
can put a gene's statistics, the replicate values behind them and the tissue side by side. Nothing
statistical is computed by `build` or the viewer: the tables are read, their columns recognised, their genes
matched to the bundle and their replicates linked to sections through the samples' [metadata](#sample-metadata).

```yaml
comparisons:
  - id: stress_vs_control
    name: Stress vs control in D1 MSNs
    description: "limma-voom on per-mouse pseudobulk, ~ condition + sex. Positive log2FC = higher in stress."
    results: de/stress_vs_control.csv      # one row per gene: gene, effect, p, padj, and a mean when there is one
    pseudobulk: de/pseudobulk_d1.csv       # genes x replicates, first column the gene, one column per replicate id
    replicates: de/mice.csv                # optional: one row per replicate: id, group, subject
    groups: [control, stress]              # plotting and pane order; the contrast is the last against the first
    units: log2 CPM                        # axis label of the replicate values
    population: { field: celltype, value: D1 MSN }   # the cells the test was fit in
    split: condition                       # the meta key whose levels are the groups (found by matching when left out)
    link: mouse                            # the meta key that holds replicate ids (the best-matching key when left out)
```

Files are CSV, TSV or parquet, paths relative to the yaml. Column names are recognised as the common tools
write them, so a DESeq2, limma, edgeR, Seurat `FindMarkers`, pyDESeq2 or scanpy table needs no mapping:

| Role | Names tried, in order |
|---|---|
| gene | `gene`, `genes`, `gene_name`, `symbol`, `feature`, `names`, `gene_id`, an unnamed first column (R row names), or the first column when it holds text and nothing else is named like a gene column |
| effect | `log2FoldChange`, `logFC`, `avg_log2FC`, `logfoldchanges`, `estimate`, `beta`, `coef` |
| p | `pvalue`, `p_value`, `P.Value`, `p_val`, `PValue`, `pvals` |
| padj | `padj`, `adj.P.Val`, `FDR`, `p_val_adj`, `pvals_adj`, `q_value` |
| mean | `baseMean`, `AveExpr`, `logCPM`, `mean` |
| replicate id | `id`, `replicate`, `sample`, `sample_id`, `subject`, `donor`, `mouse`, `animal` |
| group | `group`, `condition`, `treatment`, `genotype`, `diagnosis` |
| subject | `subject`, `donor`, `mouse`, `animal`, `pair` |

When they miss, `columns: { results: { effect: lfc, padj: q }, replicates: { group: arm } }` names them.
When a table has several gene columns (an Ensembl id and a symbol), the one that matches the bundle's genes
best is taken. Genes the sections do not measure stay in the table, marked as not measured.

`replicates:` can be left out when the pseudobulk columns are subject ids the samples' metadata describes:
the group is then what each replicate's sections carry under the split key. The sheet is needed when
replicates have no sections (an snRNA-seq-only contrast), for pairing ids that are not a sample key, and
whenever the grouping cannot be read off the sections. `groups:` can be left out too; it then follows the
order of appearance, and the build log says so. A replicate links to the samples whose `meta.<link>` equals
its id, else to the sample with that id; a replicate with no section still plots.

`init` turns a results table given on the command line into a `comparisons:` entry with the columns it
recognised, the groups from a `<case>_vs_<reference>` file name, and the other keys as comments. A
comparison is rebuilt only when one of its tables, its settings or the samples change; renaming it or
changing its description applies without a rebuild.
