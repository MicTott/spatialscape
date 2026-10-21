# Comparisons: case/control results in the viewer

Branch `comparisons`. Status: M1 to M4 built (sample metadata and panes, comparisons in the bundle, the Compare panel, the notebook hook); the manual pass on real data and Safari remains. Last edited 2026-10-21.

Deviations from the plan, decided while building M1: the *split by* control and *match scale* live in the
top bar next to the lasso and the snRNA-seq control, not in a new Views section, so everything about what is
on the canvas sits in one place; group panes share one grid shape (the largest group's column count) so the
same section index sits in the same place in every pane; on a fresh split the most zoomed-out pane sets the
shared scale so no group is cut off, while a user zoom or a focus leads from the pane it happened in.

## What this adds, in one paragraph

A dataset can say which experimental group each section belongs to, and the viewer can split the
canvas into one pane per group, control on one side and stress on the other, a third pane for a
third group, each pane zoomed and panned on its own while colour, filters and legend stay shared. A
dataset can also carry the results of differential expression tests that were fit upstream, in R or
Python, together with the replicate-level values behind them: a person picks a contrast, the canvas
splits by its groups, they click a gene in the results table, see one dot per mouse or donor for that
gene, and see the gene on every section at the same time. Clicking a dot focuses that subject's
sections. Nothing statistical is computed in the browser.

## Decisions already taken

- **Import, never compute.** The viewer draws expression from 8-bit storage and has no model. The
  table and the dots come from files the analysis wrote; the panel shows the model description the
  yaml gives. No p-values, means or fold changes are derived in the browser, ever.
- **Groups are compared side by side in panes**, one per group, two or three at a time, each with
  its own camera. Not a second viewer: the same canvas, the same layers, the same settings, split
  the way the snRNA-seq embedding already sits beside the tissue today. No averaged "case tissue".
- **Replicate to sections is the link that matters.** A replicate is a subject (a mouse, a donor).
  Its sections are found through sample metadata, so a dot can focus the tissue it came from, and
  several sections of one subject are never shown as independent replicates.
- **One way in: the dataset yaml**, reading the tables people already have (DESeq2, limma, edgeR,
  Seurat column names recognised). No export format of our own, no companion R package. From a
  notebook, `show()` takes the same tables as data frames.
- **Dots first, box optional.** Small n: the replicates are the evidence.
- **No volcano plot.** The table, sorted and searched, selects genes.
- **Modules and gene sets are not part of this branch.**

## The user-facing model

### 1. Sample metadata

Every sample may carry free metadata keys. Templates render per glob match or per R-object sample,
and a key can be read from an obs column that is constant within the sample. A dataset-level block
gives the keys display names and a level order, the way `fields:` does for annotations; it is
optional, and keys used only on samples get their id as name and first appearance as order.

```yaml
meta:
  - { id: condition, name: Condition, levels: [control, stress] }
  - { id: subject, name: Mouse }

samples:
  - glob: "sections/*/adata.h5ad"
    platform: visium
    meta: { subject: "{name}", condition: { column: condition }, sex: { column: sex } }
  - path: spe_mice.rds
    platform: visium
    meta: { subject: "{name}", condition: { column: condition } }
```

`{ column: x }` is read at build time and must hold one value in the sample; several values is an
error naming the column and the values, with `subset:` as the way out. Metadata appears in the hover
rows and in the sample list, is what the viewer splits by, and is how comparisons find a replicate's
sections. `init` proposes `meta:` lines for columns that are constant within a sample (across the
samples of an R object; the single-valued columns of the first file of a glob), as comments.

### 2. The `comparisons:` block

```yaml
comparisons:
  - id: stress_vs_control_d1
    name: Stress vs control in D1 MSNs
    description: "limma-voom on per-mouse pseudobulk, ~ condition + sex. Positive log2FC = higher in stress."
    results: de/stress_vs_control_d1.csv      # one row per gene: gene, effect, p, padj, and a mean when there is one
    pseudobulk: de/pseudobulk_d1.csv          # genes x replicates, first column the gene, one column per replicate id
    replicates: de/mice.csv                   # optional: one row per replicate: id, group, subject, anything else
    groups: [control, stress]                 # plotting and pane order; the contrast is the last against the first
    units: log2 CPM                           # axis label of the dots; whatever the pseudobulk file holds
    population: { field: celltype, value: D1 MSN }   # optional: the cells the test was fit in
    split: condition                          # optional: the meta key whose levels are the groups (default: found by matching)
    link: subject                             # optional: the meta key that holds replicate ids (default subject, then the sample id)
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
already describes: the group then comes from the samples' value of the `split` key, and the link is
automatic. The sheet is needed for comparisons without sections (an snRNA-seq-only contrast), for
paired designs where the pairing id is not a sample key, and for replicates that have no section.

Linking rule, per replicate id: the samples whose `meta.<link>` equals the id, else the sample whose
id equals it, else none. A replicate with no section still plots; its dot just cannot focus anything.

Gene matching: results genes are matched to the bundle's gene union by name, then through an
Ensembl id column when the bundle is symbol-named and the table is id-named. Unmatched genes stay in
the table, marked "not measured", with a count in the panel header, which is what a targeted panel
such as Xenium needs to be honest about.

### 3. `init`

A `.csv`, `.tsv` or `.parquet` argument is taken as a results table and becomes one `comparisons:`
entry: id and name from the file name (`stress_vs_control` yields `groups: [control, stress]`), the
column mapping as found, `# pseudobulk:` and `# replicates:` lines ready to fill, and the columns the
heuristics did not take listed as comments. The printed "assumed for" block says which column was
taken for what and how many genes the table has, the same way it does for obs columns.

### 4. From a notebook

```python
s = spatialscape.show(adata, sample="mouse", meta={"condition": "condition"})
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
  manifest.json                        + meta[] (key declarations), + samples[].meta, + comparisons[]
  comparisons/<id>/
    comparison.json                    id, name, description, groups, units, population, split, link,
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

- `Manifest.meta: [{id, name, levels}]` and `Sample.meta: dict[str, str]`
- `Manifest.comparisons: [{id, name, description, path, groups, units, population, split, nGenes, nReplicates, nUnmatched}]`

`FORMAT_VERSION` is unchanged: every addition is optional and older bundles read as before.

## Viewer

### Split by group: the panes

Today the canvas is one `Deck` with up to two `OrthographicView`s, `spatial` and `embedding`,
each with its own camera, layout and scale bar, layers routed to a view by `viewId`, and a draggable
divider. The change is to make that a list of panes instead of a fixed pair. A pane is a kind
(`spatial` or `embedding`), an optional group (`{key, value}`), and a width fraction. The embedding
pane that exists today is one pane of the list and keeps its URL key and behaviour.

**Entry point.** The side panel gets a *Views* section where the embedding toggle lives now:

```
Views
  Layout       [grid ▾]
  Split by     [none ▾]  → none · Condition · Sex · …   (the dataset's meta keys with 2+ levels)
  [x] match scale across panes
  [ ] snRNA-seq pane
```

Choosing a key splits the canvas into one pane per level in level order, two panes for two levels,
three for three or more. With more than three levels each pane header has a select that swaps the
group it shows, so any three can be compared; the number of panes never exceeds three plus the
optional embedding pane. Choosing none returns to the single canvas with the camera it had.

**Pane anatomy.** A slim header on top of each pane: the group's name as a caption, "6 sections ·
3 mice", and the select when there is a choice. The map below lays the group's sections out with the
same grid or strip layout as the single canvas, in the dataset's sample order. A scale bar sits at
the bottom left of every spatial pane. The active pane, the last one the pointer touched, carries a
two-pixel accent line under its header; keyboard stepping, Escape and the focus work within it.

**Cameras.** Independent per pane: zoom and pan one group, the others stay. *Match scale*, on by
default for group panes, keeps the same microns per pixel in every pane: zooming in one pane re-zooms
the others around their own centres while panning stays free, so two sections at the same scale can
be read side by side without the panes drifting into unrelated zoom levels. One click releases it.
The embedding pane never takes part in scale matching. Double-click a section to focus it inside its
pane; Escape in the active pane returns to that pane's overview; the sample strip at the bottom
groups its thumbnails under the same captions and focuses the right pane on click.

**Dividers.** One draggable handle between each pair of neighbouring panes, with a minimum pane
width; double-click a handle to equalise. Below about 900 px of width the panes stack vertically
with the same headers, so a laptop next to a projector still works.

**Shared state.** Colour, colormap and range, legend and hidden categories, filters, point size,
image opacity, outlines, polygons, the lasso tool and regions are all global, as they already are
across the tissue and embedding views. The legend's on-screen counts cover every pane. Hover and
lasso work in any pane. Sections without a value for the split key are drawn in none of the panes,
and the Views section says so: "3 sections have no condition", with a one-click return to the single
canvas.

**URL.** `sb=condition` for the split key, `sg=control,stress` when the panes show other groups
than the default three or in another order, `sf=0.33,0.33` when the handles were dragged,
`ms=0` when scale matching is off, and the cameras of every pane as `pv=x,y,z;x,y,z;…`. `sv` keeps
describing the embedding pane. A copied link reopens the same panes, groups and cameras.

**Export.** PNG export composes every pane with its header, one legend and one scale bar per pane.

**Cost.** One `Deck`, one GL context, one `OrthographicView` per pane, layers filtered per pane by
`viewId`, the sample arrays shared: splitting, swapping a group or releasing the split moves nothing
in memory and fetches nothing.

**Implementation notes.** `VIEWS` and the `ViewId` union become pane ids; `computeRects` becomes a
pane layout (fractions, stacking); `relayout(pane)` takes the pane's sample subset (`meta[key] ===
value`, all spatial samples when there is no key, embedding samples for the embedding pane);
`viewOf(sampleId)` resolves through the panes; `viewStates`, `viewPx`, `viewRects`, `layouts` and
`activeView` are keyed by pane id; `ScaleBar` renders once per spatial pane; `SplitDivider` becomes
`PaneDividers`; `stepFocus` steps within the active pane; `exportPng` iterates the panes; `urlState`
reads and writes the new keys and keeps `sv`. The selection and region machinery already works per
view and needs only the id type widened.

### The Compare panel

A panel under the maps, built the way the genome panel is (own height, dragged at its top edge,
remembered per browser), opened by choosing a comparison in a *Compare* select in the side panel's
Colour section and closed by choosing none. When the dataset has no comparisons nothing is shown.

Choosing a comparison does three things at once: it splits the canvas by the comparison's groups
(its `split` key, panes in `groups` order) unless the user has pinned a different split, it applies
the population filter when there is one and shows a chip "map filtered to D1 MSN" with a clear button
(it is the normal category filter, so it can be changed), and it opens the panel.

Left: the results table.

- Header: the comparison's name; a search box; sort by padj, effect up, effect down, mean; a
  direction filter (all, up, down); the count line, e.g. "14,210 genes, 312 at padj < 0.05, 1,020
  not measured on screen".
- A virtualised list: gene, effect with sign and a small bar, padj. Clicking a row colours every
  pane by that gene through the existing `setColor`. The row of the current colour gene is
  highlighted; up and down arrows step through the sorted table without leaving the comparison.
- Genes not in the bundle are grey with "not measured" and cannot be selected.

Right: the replicate plot for the current colour gene.

- x: groups in `groups` order, the same order as the panes above; y: the pseudobulk value with the
  `units` label. One dot per replicate, jittered, coloured by group (two muted hues; the categorical
  field's colours when the split key is also a field). A median line per group; a box on request
  (toggle in the header, remembered). Paired lines between the same subject across groups when
  `subject` repeats.
- Hover: replicate id, value, linked sections. Click: focus the first linked section in its pane;
  the strip highlights all of them. No sections: the dot says so.
- Footer: the table's numbers for this gene (effect, p, padj, mean) and the comparison's
  description, verbatim. When the colour is not a gene of this table the plot area says "pick a gene
  in the table".

State and URL: `comparison: string | null` in the store, `cmp=<id>` in the URL. The gene travels as
`c=g:<gene>` as today, so a copied link reopens the same contrast, split and gene.

## Build

New module `python/src/spatialscape/comparisons.py`:

- `read_table(path)` by extension; `map_columns(df, role_table, overrides)` with the names above;
  `load_comparison(spec, base)` returning results, pseudobulk and replicates as frames, with the
  checks: every pseudobulk column is a replicate id, every replicate has a group, groups are a
  subset of `groups`, the gene column is unique.
- `link_replicates(replicates, samples, link)` using `Sample.meta`; `find_split_key(groups, meta)`
  when `split:` is not given (the key whose levels contain every group).
- `match_genes(results, union, aliases)` returning the matched index and the unmatched list.
- `write_comparison(out, spec, ...)` writing the four files; `comparison_fingerprint(spec, base)`
  from `_stat` of the three inputs plus the entry's json, and `why_stale` as for samples.

`build_dataset` runs comparisons after the samples (it needs the gene union and the samples' meta),
rebuilds only those whose fingerprint changed, removes folders of ids the yaml dropped, and lists
all of this in `--dry-run`. The manifest's `comparisons` list is rewritten on every build like the
other dataset files. `validate` checks the json keys, array lengths, the zarr shape and that every
linked sample id exists. `site build` carries the folders along with the rest of the bundle.

Sample `meta` is resolved in `build_sample`: templated strings at expansion time, `{column: x}` by
reading the column. It enters the sample fingerprint like any other setting, so a key from the yaml
rebuilds nothing but the manifest and a key from a column rebuilds that sample once.

`synth` gains `--comparisons`: two groups of fake sections with `meta`, a results table with a few
planted true positives, a pseudobulk matrix consistent with the sections, and a replicate sheet, so
every test and the docs have a complete example without real data.

## Tests

pytest:
- `meta` from templates and from columns, the error for a column with several values, the
  dataset-level declarations and level order, `init` proposing meta lines;
- column heuristics for each tool's output (DESeq2, limma, edgeR, Seurat FindMarkers, pyDESeq2),
  overrides, an unnamed first column, an Ensembl id table against a symbol bundle;
- linking: by meta key, by sample id, replicates without sections, several sections per subject;
  the split key found from the groups; a comparison without a replicate sheet;
- build writes the four files, `validate` passes, the manifest lists the comparison; unmatched genes
  counted; a second build is "unchanged"; editing the results file rebuilds only that comparison;
  dropping the entry removes its folder;
- `init` on a results CSV writes an entry that builds unedited with the synthetic bundle;
- `show().add_comparison` writes into the session folder and the manifest; `s.selection()` still
  works afterwards.

vitest:
- pane layout from a split key: two and three levels, more than three with chosen groups, the
  embedding pane alongside, fractions, vertical stacking, samples without the key left out;
- scale matching: a zoom in one pane sets the others' zoom and keeps their centres;
- URL round trip of `sb`, `sg`, `sf`, `ms`, `pv`, `cmp`, with and without `sv`;
- table sorting and direction filter as pure functions; replicate plot data preparation (jitter is
  deterministic per replicate id, paired lines only when a subject repeats).

Manual pass in the browser: the synthetic experiment; the amygdala Visium donors split by a made-up
condition for the panes at real data size; a real DE table from the group for the panel; Safari; a
narrow window for the stacked layout; PNG export with three panes.

## Docs

- New guide page "Comparing groups": sample metadata, split by group, the Compare panel, the three
  tables and the yaml, the honesty notes (values are the imported ones, colours are 8-bit, a section
  is never a replicate), the notebook round trip.
- Dataset yaml guide: `meta`, the `comparisons` block.
- Reference: schema rows, format page (`comparisons/` files, `meta`), URL page (`sb`, `sg`, `sf`,
  `ms`, `pv`, `cmp`).
- Viewer guide: the Views section, panes, match scale, the Compare panel.
- Notebook guide: `meta=` and `add_comparison`.
- CHANGELOG under Unreleased.

## Milestones

| # | Deliverable | Acceptance |
|---|---|---|
| M1 | `meta` on samples and in the manifest, `init` proposals, `synth --comparisons` sections; panes: Views section, split by key, headers, dividers, stacking, match scale, per-pane focus and stepping, strip captions, URL, PNG export; the embedding pane unchanged in behaviour | the synthetic experiment splits into control and stress with captions; a third level gives three panes; zooming with match scale keeps the other panes' centres; a copied link reopens the panes and cameras; existing bundles and URLs behave exactly as before |
| M2 | `comparisons.py`, build, fingerprint, `validate`, `init` from CSV, manifest | the synthetic tables build to the four files; unmatched genes counted; dry run lists comparison actions; second build unchanged; `init de.csv` entry builds as written |
| M3 | Compare panel: table, replicate plot, auto-split on selection, population chip, focus from a dot, `cmp` in the URL | choosing a comparison splits the canvas and opens the panel; click a gene recolours every pane with no extra fetch when cached; up and down step genes; a dot focuses its section in the right pane; a copied link reopens contrast, split and gene |
| M4 | `add_comparison` and `meta=` in `show()`, docs, changelog | the notebook round trip works from Python and R; docs build with no dead links |

About three weeks of focused work: M1 four to five days, since the pane generalisation touches the
controller, the dividers, the strip, the scale bars, the export and the URL; M2 two days; M3 three
to four days; M4 one to two days; plus the manual pass.

## Out of scope, by decision

- Any statistics in the browser, including recomputing a mean from the 8-bit columns for the plot.
- A volcano plot.
- Gene sets, modules and coverage labels: another branch, when wanted.
- An averaged or pooled "case" versus "control" section.
- More than three group panes at once; aligning rows across panes by subject (paired designs
  before and after) comes later, once the panes are in daily use.
- A results format or an R/Python companion package of our own.

## Open questions

1. *Match scale* on by default for group panes (the plan says yes, one click to release)?
2. When a comparison is chosen, split automatically by its groups (the plan says yes, unless the
   user has pinned a different split in the Views section)?
3. Apply the population filter by default when a comparison has one (the plan says yes, with a
   visible chip and clear button)?
