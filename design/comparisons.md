# Comparisons: case/control results in the viewer

Branch `comparisons`. Status: plan, nothing built. Last edited 2026-10-21.

## What this adds, in one paragraph

A dataset can carry the results of differential expression tests that were fit upstream, in R or
Python, together with the replicate-level values behind them. In the viewer a person picks a
contrast, clicks a gene in its results table, sees one dot per mouse or donor for that gene, and sees
the gene on every section at the same time. Clicking a dot focuses that subject's sections. Sections
can be laid out by condition and subject so the groups sit side by side on the one canvas. Gene sets
say how many of their genes a section measures. Nothing statistical is computed in the browser.

## Decisions already taken

- **Import, never compute.** The viewer draws expression from 8-bit storage and has no model. The
  table and the dots come from files the analysis wrote; the panel shows the model description the
  yaml gives. No p-values, means or fold changes are derived in the browser, ever.
- **Replicate to sections is the link that matters.** A replicate is a subject (a mouse, a donor).
  Its sections are found through sample metadata, so a dot can focus the tissue it came from, and
  several sections of one subject are never shown as independent replicates.
- **Group comparison is a layout option**, not a second viewer: rows and columns of the existing
  grid by sample metadata, with captions. No averaged "case tissue".
- **One way in: the dataset yaml**, reading the tables people already have (DESeq2, limma, edgeR,
  Seurat column names recognised). No export format of our own, no companion R package. From a
  notebook, `show()` takes the same tables as data frames.
- **Dots first, box optional.** Small n: the replicates are the evidence.
- **No volcano plot.** The table, sorted and searched, selects genes.
- **Gene sets stay what they are**: blend mode is a live mean of a set, a continuous field is a
  supplied score. The addition is labelling and coverage, not a third mechanism.

## The user-facing model

### 1. Sample metadata and layout by metadata

Every sample may carry free metadata keys. Templates render per glob match or per R-object sample,
and a key can be read from an obs column that is constant within the sample.

```yaml
samples:
  - glob: "sections/*/adata.h5ad"
    platform: visium
    meta: { subject: "{name}", condition: { column: condition }, sex: { column: sex } }
  - path: spe_mice.rds
    platform: visium
    meta: { subject: "{name}", condition: { column: condition } }

layout:
  mode: grid
  rows: subject                      # a meta key, or leave out
  columns: condition                 # a meta key, or a number as today
  levels: { condition: [control, stress] }   # value order; default: first appearance in sample order
  captions: true                     # column captions above the grid, row captions at its left
```

Rules: a sample missing one of the keys goes to a trailing "other" row or column; an empty cell is
left empty (a subject without a section in one condition); `order:` still wins inside a cell when
several samples share one. Strip mode ignores rows and columns. `meta` keys appear in the hover rows
and are available to comparisons as the link.

### 2. The `comparisons:` block

```yaml
comparisons:
  - id: stress_vs_control_d1
    name: Stress vs control in D1 MSNs
    description: "limma-voom on per-mouse pseudobulk, ~ condition + sex. Positive log2FC = higher in stress."
    results: de/stress_vs_control_d1.csv      # one row per gene: gene, effect, p, padj, and a mean when there is one
    pseudobulk: de/pseudobulk_d1.csv          # genes x replicates, first column the gene, one column per replicate id
    replicates: de/mice.csv                   # optional: one row per replicate: id, group, subject, anything else
    groups: [control, stress]                 # plotting order; the contrast is the last against the first
    units: log2 CPM                           # axis label of the dots; whatever the pseudobulk file holds
    population: { field: celltype, value: D1 MSN }   # optional: the cells the test was fit in
    link: subject                             # optional: the sample meta key that holds replicate ids (default subject, then the sample id)
    columns:                                  # optional: only when the recognised names miss
      results: { gene: gene_name, effect: logFC, p: P.Value, padj: adj.P.Val, mean: AveExpr }
      replicates: { id: mouse, group: condition, subject: mouse }
```

Files are CSV, TSV or parquet, paths relative to the yaml. Recognised column names:

| Role | Names tried, in order |
|---|---|
| gene | `gene`, `gene_name`, `symbol`, `feature`, `gene_id`, an unnamed first column (R row names) |
| effect | `log2FoldChange`, `logFC`, `avg_log2FC`, `log2fc`, `estimate`, `beta`, `coef` |
| p | `pvalue`, `p_value`, `P.Value`, `p_val`, `PValue`, `pval` |
| padj | `padj`, `adj.P.Val`, `FDR`, `p_val_adj`, `q_value`, `qvalue`, `fdr` |
| mean | `baseMean`, `AveExpr`, `logCPM`, `mean` |
| replicate id | `id`, `replicate`, `sample`, `sample_id`, `subject`, `donor`, `mouse`, `animal` |
| group | `group`, `condition`, `treatment`, `genotype`, `diagnosis`, `dx` |
| subject (pairing) | `subject`, `donor`, `mouse`, `animal`, `pair` |

`replicates:` may be left out when the pseudobulk columns are subject ids that the samples' `meta`
already describes: the group then comes from the samples' `meta.condition` (or the key `groups`
names), and the link is automatic. The sheet is needed for comparisons without sections (an
snRNA-seq-only contrast), for paired designs where the pairing id is not a sample key, and for
replicates that have no section at all.

Linking rule, per replicate id: the samples whose `meta.<link>` equals the id, else the sample whose
id equals it, else none. A replicate with no section still plots; its dot just cannot focus anything.

Gene matching: results genes are matched to the bundle's gene union by name, then through an
Ensembl id column when the bundle is symbol-named and the table is id-named. Unmatched genes stay in
the table, marked "not measured", with a count in the panel header. This is the panel-coverage
honesty the Xenium case needs.

### 3. `init`

A `.csv`, `.tsv` or `.parquet` argument is taken as a results table and becomes one `comparisons:`
entry: id and name from the file name (`stress_vs_control` yields `groups: [control, stress]`), the
column mapping as found, `# pseudobulk:` and `# replicates:` lines ready to fill, and the columns the
heuristics did not take listed as comments. The printed "assumed for" block says which column was
taken for what and how many genes the table has, the same way it does for obs columns.

### 4. From a notebook

```python
s = spatialscape.show(adata, sample="mouse", fields={"condition": "condition"})
cells = s.selection()                      # lasso, then the DE test in scanpy, decoupler, limma through rpy2, ...
s.add_comparison("Stress vs control, lassoed region", results=res_df, pseudobulk=pb_df,
                 replicates=meta_df, groups=["control", "stress"], units="log2 CPM",
                 description="pyDESeq2 on per-mouse pseudobulk of the lassoed cells")
s                                          # re-display: the viewer reloads with the comparison in its menu
```

`add_comparison` writes the same bundle files into the session's folder and rewrites its manifest;
the data hash of the object is not touched, so iterating on a test never rebuilds the samples. The
same keyword works at `show()` time with a list of comparisons. From R the call is the same through
reticulate with data frames.

## Bundle format

```
<bundle>/
  manifest.json                        + comparisons[], + layout.rows/columns/levels/captions, + samples[].meta
  comparisons/<id>/
    comparison.json                    id, name, description, groups, units, population, link,
                                       replicates: [{id, group, subject, samples: [sample ids]}],
                                       n: {genes, matched, unmatched}
    results.json                       column arrays: genes[], effect[], p[], padj[], mean[]; rows sorted by padj
                                       then |effect|; unmeasured: [row indices not in the bundle]
    pseudobulk.zarr                    float32 (n_results_genes, n_replicates), zstd, chunks (1024, n_rep),
                                       rows in results order; one range request per gene lookup
    build.json                         fingerprint of the three inputs and the entry's settings
```

Sizes for a 20k-gene table and 40 replicates: results about 0.7 MB, pseudobulk about 3 MB in twenty
chunks, both cached by the browser after the first fetch. Static hosting needs nothing new.

Manifest additions, mirrored in `manifest.py` and `app/src/data/manifest.ts`:

- `Sample.meta: dict[str, str]`
- `Layout.rows`, `Layout.columns` (int or meta key), `Layout.levels`, `Layout.captions`
- `Manifest.comparisons: [{id, name, description, path, groups, units, population, nGenes, nReplicates, nUnmatched}]`

`FORMAT_VERSION` is unchanged: every addition is optional and older bundles read as before.

## Viewer

### The Compare panel

A panel under the maps, built the way the genome panel is (own height, dragged at its top edge,
remembered per browser), opened by choosing a comparison in a "Compare" select in the side panel's
Color section and closed by choosing none. When the dataset has no comparisons nothing is shown.

Left: the results table.

- Header: the comparison's name; a search box; sort by padj, effect up, effect down, mean; a
  direction filter (all, up, down); the count line, e.g. "14,210 genes, 312 at padj < 0.05, 1,020
  not measured on screen".
- A virtualised list (the gene list already caps and virtualises; same component family): gene,
  effect with sign and a small bar, padj. Clicking a row colours the maps by that gene through the
  existing `setColor`. The row of the current colour gene is highlighted; up and down arrows step
  through the sorted table without leaving the comparison.
- Genes not in the bundle are grey with "not measured" and cannot be selected.

Right: the replicate plot for the current colour gene.

- x: groups in `groups` order; y: the pseudobulk value with the `units` label. One dot per
  replicate, jittered, coloured by group (two muted hues; or the vocabulary colours when the group
  key is also a categorical field). A median line per group; a box on request (toggle in the header,
  remembered). Paired lines between the same subject across groups when `subject` repeats.
- Hover: replicate id, value, linked sections. Click: focus the first linked section; the strip
  highlights all of them. No sections: the dot says so.
- Footer: the table's numbers for this gene (effect, p, padj, mean) and the comparison's
  description, verbatim. When the colour is not a gene of this table the plot area says "pick a gene
  in the table".

State and URL: `comparison: string | null` in the store, `cmp=<id>` in the URL. The gene travels as
`c=g:<gene>` as today, so a copied link reopens the same contrast and gene. Choosing a comparison
with a `population` sets the existing category filter to that population and shows a chip "map
filtered to D1 MSN" with a clear button; it is the normal filter, so the user can change it.

### Layout by metadata

`computeLayout` takes `rows`, `columns`, `levels` from the manifest, places each sample at (row
index, column index), leaves empty cells, and sizes the grid from the number of levels. Captions are
a `TextLayer` in the controller: column labels above the first row, row labels left of the first
column, toggled in Display and on by default when the layout names a key. Strip mode is unchanged.
The sample strip and keyboard stepping follow the new order.

### Gene set coverage

Blend legends and the selection panel say "mean of 12 genes" and, per section on screen, "3 of 12
not measured" when a panel lacks some of them; the hover rows say the same for the blended value.
Supplied scores keep their field names and get "(supplied score)" in the legend title when the
field's `units` or `description` says so, so a mean and a score are never read as the same thing.
Named sets, when wanted, are one more yaml list (`gene_sets: [{id, name, genes: [...]}]`) shown as
presets in the Blend panel; it is in the last milestone and can be cut.

## Build

New module `python/src/spatialscape/comparisons.py`:

- `read_table(path)` by extension; `map_columns(df, role_table, overrides)` with the names above;
  `load_comparison(spec, base)` returning results, pseudobulk and replicates as frames, with
  the checks: every pseudobulk column is a replicate id, every replicate has a group, groups are a
  subset of `groups`, the gene column is unique.
- `link_replicates(replicates, samples, link)` using `Sample.meta`.
- `match_genes(results, union, aliases)` returning the matched index and the unmatched list.
- `write_comparison(out, spec, ...)` writing the four files; `comparison_fingerprint(spec, base)`
  from `_stat` of the three inputs plus the entry's json, and `why_stale` as for samples.

`build_dataset` runs comparisons after the samples (it needs the gene union and the samples' meta),
rebuilds only those whose fingerprint changed, removes folders of ids the yaml dropped, and lists
all of this in `--dry-run`. The manifest's `comparisons` list is rewritten on every build like the
other dataset files. `validate` checks the json keys, array lengths, the zarr shape and that every
linked sample id exists. `site build` carries the folders along with the rest of the bundle.

Sample `meta` is resolved in `build_sample`: templated strings at expansion time, `{column: x}` by
reading the column (one value per sample, or an error naming the column and its values). It enters
the sample fingerprint like any other setting, so adding a key rebuilds nothing but the manifest
when the value comes from the yaml and rebuilds the sample when it comes from a column.

`synth` gains `--comparisons`: two groups of fake sections with `meta`, a results table with a few
planted true positives, a pseudobulk matrix consistent with the sections, and a replicate sheet, so
every test and the docs have a complete example without real data.

## Tests

pytest:
- column heuristics for each tool's output (DESeq2, limma, edgeR, Seurat FindMarkers, pyDESeq2),
  overrides, an unnamed first column, an Ensembl id table against a symbol bundle;
- linking: by meta key, by sample id, replicates without sections, several sections per subject;
- a comparison without a replicate sheet;
- build writes the four files, `validate` passes, the manifest lists the comparison; unmatched genes
  counted; a second build is "unchanged"; editing the results file rebuilds only that comparison;
  dropping the entry removes its folder;
- `init` on a results CSV writes an entry that builds unedited with the synthetic bundle;
- `show().add_comparison` writes into the session folder and the manifest; `s.selection()` still
  works afterwards;
- `meta` from templates and from columns, including the error for a column with several values;
- layout `rows`/`columns`/`levels` validated against the yaml (unknown key, unknown level).

vitest:
- `computeLayout` with rows and columns: positions, empty cells, level order, hidden samples,
  strip unchanged;
- URL round trip of `cmp` with and without a gene;
- table sorting and direction filter as pure functions; replicate plot data preparation (jitter is
  deterministic per replicate id, paired lines only when a subject repeats).

Manual pass in the browser on the synthetic comparison and on a real one (the amygdala Visium donors
split by a made-up condition is enough to exercise the layout; a real DE table from the group for
the panel), including Safari.

## Docs

- New guide page "Comparisons: case/control results": the three tables, the yaml, what the panel
  shows and does not, the honesty notes (values are the imported ones, colours are 8-bit, a
  section is never a replicate), the notebook round trip.
- Dataset yaml guide: `meta`, layout `rows`/`columns`/`levels`/`captions`, the `comparisons` block.
- Reference: schema rows, format page (`comparisons/` files, `meta`), URL page (`cmp`).
- Viewer guide: the Compare panel, captions, gene set coverage wording.
- Notebook guide: `add_comparison`.
- CHANGELOG under Unreleased.

## Milestones

| # | Deliverable | Acceptance |
|---|---|---|
| M1 | `meta`, layout `rows`/`columns`/`levels`/`captions`, hover rows, `synth --comparisons` sections | synthetic sections arranged 2 by n with captions; empty cell for a missing section; URL and strip order follow; existing bundles unchanged |
| M2 | `comparisons.py`, build, fingerprint, `validate`, `init` from CSV, manifest | the synthetic tables build to the four files; unmatched genes counted; dry run lists comparison actions; second build unchanged; `init de.csv` entry builds as written |
| M3 | Compare panel: table, replicate plot, focus from a dot, `cmp` in the URL, population chip | click a gene recolours the maps with no extra fetch when cached; up and down step genes; a dot focuses its section; a copied link reopens contrast and gene |
| M4 | `add_comparison` in `show()`, gene set coverage labels, docs, changelog; named `gene_sets` if time allows | the notebook round trip works from Python and R; blend legend states coverage per section; docs build with no dead links |

About two weeks of focused work: M1 one to two days, M2 two days, M3 three to four days, M4 one to
two days, plus the manual pass.

## Out of scope, by decision

- Any statistics in the browser, including recomputing a mean from the 8-bit columns for the plot.
- A volcano plot.
- An averaged or pooled "case" versus "control" section.
- Matching rows by anatomical level or another second key: later, once the simple grid is in use.
- A results format or an R/Python companion package of our own.

## Open questions

1. When a comparison has a `population`, should selecting it apply the filter by default (the plan
   says yes, with a visible chip and clear button)?
2. Group colours: fixed muted pair, or the categorical field's colours when the group key is also a
   field? The plan takes the field's colours when they exist.
3. Should the table offer "export CSV" of the current sort and filter, or is the source file enough?
