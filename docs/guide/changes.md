# Making changes

Everything the viewer shows comes from files you own: one dataset yaml per dataset and, for a gallery,
`site.yaml`. This page is the map from "I want to change X" to the line to edit and the command to rerun.
There is one command per dataset, `spatialscape build <yaml>`, and it only redoes the work an edit
requires: a rename or a new palette takes seconds, a changed annotation column rebuilds the samples that
carry it, a re-exported file rebuilds that sample.

| I want to | Edit | Then run |
|---|---|---|
| Rename the dataset, change its description | `name:` / `description:` | `build` (seconds) |
| Choose the gene shown on open | `default_gene: SNAP25` | `build` (seconds) |
| Open on an annotation instead | `default_color: { field: domain }` | `build` (seconds) |
| Name an annotation properly ("Layer", not "layer_guess_reordered_short") | `name:` on its entry under `fields:` | `build` (seconds) |
| Compare conditions side by side in the viewer | `meta: { condition: stress }` on each sample (or `{ column: condition }`), optionally `meta:` at the top for names and order | `build` (seconds for typed values; the sample once for a column) |
| Show fewer / other annotations | the `fields:` mapping on the sample entry: delete or uncomment lines | `build` (rebuilds those samples) |
| Use my paper's colors | `palette: colors.json` plus `palette_key:` on the field | `build` (seconds) |
| Fix the order of categories | `categories: [L1, L2, …]` on the field | `build` (rebuilds the samples that carry it) |
| Merge spellings (`AI` and `IA`) | `aliases: { AI: IA }` on the field | `build` (rebuilds the samples that carry it) |
| Put QC metrics in one unit across platforms | `{ column: expr_chrM_ratio, scale: 100 }` in the mapping | `build` |
| Change which section is the thumbnail | `thumbnail_sample: vis_151673` | `build` (seconds) |
| Space the sections out | `layout: { gutter_fraction: 0.3 }` | `build` (seconds) |
| Re-export one sample | fix the file, keep the yaml | `build` (rebuilds that sample) |
| Add a sample | add it to `samples:`, or let the glob find it | `build` (builds the new one) |
| Remove a sample | delete its entry | `build` (deletes its folder) |
| Use another assay from an R object | `assay: counts` on the entry | `build` (converts again, rebuilds) |
| Add a dataset to the gallery | a `config:` line in `site.yaml` | `spatialscape site build site.yaml` |
| Add a paper link, tags or a "coming soon" card | `paper:`, `tags:`, or an `id:` + `name:` card in `site.yaml` | `site build` |
| Add a navigation bar above the viewer | `nav:` in `site.yaml` | `site build` |

Not sure what a build will do? `spatialscape build <yaml> --dry-run` lists every sample with build / skip
and the reason.

## The same yaml, before and after

`spatialscape init` writes the menu. This is the DLPFC example from [Reproduce the examples](./examples) as
`init` left it, comments trimmed:

```yaml
id: visium-human-dlpfc
name: "Human DLPFC, Visium (Maynard et al. 2021)"
default_color: { field: domain }
layout: { mode: grid }
fields:
  - { id: domain, name: Spatial domain, type: categorical }
  - { id: total_counts, name: Total counts, type: continuous }
  - { id: detected_genes, name: Detected genes, type: continuous }
  - { id: mito_percent, name: Mito %, type: continuous }
samples:
  - path: raw/spe_dlpfc.rds                      # SpatialExperiment, 12 samples: 151507, 151508, ... (one sample per sample_id)
    platform: visium
    assay: logcounts
    id: "vis_{name}"
    name: "{name} (Visium)"
    group: "{name}"
    fields:
      domain: layer_guess_reordered_short        # 7 levels: L1, L3, WM, L6, ...; 352 NA
      total_counts: sum_umi
      detected_genes: sum_gene
      mito_percent: { column: expr_chrM_ratio, scale: 100 }
      # domain: Cluster                          # alternative; 9 levels: 1, 2, 3, 4, ...
    # meta: { subject: { column: subject }, position: { column: position }, replicate: { column: replicate } }
```

and after a description, the opening view, the layer order and the donor metadata:

```yaml
id: visium-human-dlpfc
name: Human DLPFC, Visium (Maynard et al. 2021)
description: "Twelve Visium sections of human dorsolateral prefrontal cortex from three donors, with the manual cortical layer annotation and the H&E of each section."
default_gene: SNAP25
default_color: { field: domain }
thumbnail_sample: vis_151673
layout: { mode: grid, columns: 4 }               # four sections per donor, so one row per donor
fields:
  - { id: domain, name: Layer (manual annotation), type: categorical, categories: [L1, L2, L3, L4, L5, L6, WM] }
  - { id: total_counts, name: Total counts, type: continuous }
  - { id: detected_genes, name: Detected genes, type: continuous }
  - { id: mito_percent, name: Mito %, type: continuous }
meta:
  - { id: subject, name: Donor }
  - { id: position, name: Position (µm) }
  - { id: replicate, name: Replicate }
samples:
  - path: raw/spe_dlpfc.rds
    platform: visium
    assay: logcounts
    id: "vis_{name}"
    name: "Section {name}"
    group: "{name}"
    fields:
      domain: layer_guess_reordered_short
      total_counts: sum_umi
      detected_genes: sum_gene
      mito_percent: { column: expr_chrM_ratio, scale: 100 }
    meta: { subject: { column: subject }, position: { column: position }, replicate: { column: replicate } }
```

The `categories` line changes codes and `meta` reads a column, so this edit rebuilds the twelve samples once;
every later edit that the table above marks "seconds" is just that.

## Colors

A palette file is JSON: top-level keys are palette names, each mapping a category label to a hex color.
A field uses it through `palette_key`; several keys can be listed, first match wins. Labels missing from the
palette get an automatic color. Categories are matched by label, so renaming a label in `aliases` also
changes which color it gets.

```json
{ "domain": { "L1": "#F0027F", "L2": "#377EB8", "WM": "#1A1A1A" } }
```

## Two datasets, one vocabulary

When two datasets, or two platforms within one, label the same cell types, give them the same field id and
the same `palette_key`. A `Cell type` field shared by a Xenium section and an snRNA-seq UMAP then uses one
legend and one set of colors, and the viewer greys out samples that do not carry it.

## Starting over

`build --force` rebuilds every sample from the yaml and the source files; deleting the bundle folder does
the same. Neither is needed for ordinary edits.
