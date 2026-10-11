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
| Name an annotation properly ("Spatial domain", not "BS k16 …") | `name:` on its entry under `fields:` | `build` (seconds) |
| Show fewer / other annotations | the `fields:` mapping on the sample entry: delete or uncomment lines | `build` (rebuilds those samples) |
| Use my paper's colors | `palette: colors.json` plus `palette_key:` on the field | `build` (seconds) |
| Fix the order of categories | `categories: [L1, L2, …]` on the field | `build` (rebuilds the samples that carry it) |
| Merge spellings (`AI` and `IA`) | `aliases: { AI: IA }` on the field | `build` (rebuilds the samples that carry it) |
| Put QC metrics in one unit across platforms | `{ column: expr_chrM_ratio, scale: 100 }` in the mapping | `build` |
| Change which section is the thumbnail | `thumbnail_sample: vis_Br8325` | `build` (seconds) |
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

`spatialscape init` writes the menu. This is the amygdala Visium dataset as `init` left it, comments
trimmed:

```yaml
id: amygdala_visium
name: Human amygdala Visium
default_color: { field: domain }
layout: { mode: grid }
fields:
  - { id: domain, name: Spatial domain, type: categorical }
  - { id: total_counts, name: Total counts, type: continuous }
  - { id: detected_genes, name: Detected genes, type: continuous }
  - { id: mito_percent, name: Mito %, type: continuous }
samples:
  - path: ../Vitessce_app/spe_amy_shinyapp.rds   # SpatialExperiment, 7 samples: Br2743, Br3942, ... (one sample per sample_id)
    platform: visium
    assay: logcounts
    id: "vis_{name}"
    name: "{name} (Visium)"
    group: "{name}"
    fields:
      domain: BS_k16_Semisupervised_wAI          # 16 levels: CeA, MeA, BLA, ...
      total_counts: sum_umi
      detected_genes: sum_gene
      mito_percent: { column: expr_chrM_ratio, scale: 100 }
      # domain: BS_k8                            # alternative; 8 levels
      # subject: subject                         # 7 levels: Br2743, Br3942, ...
```

and after a description, the paper's colors and the opening view:

```yaml
id: amygdala_visium
name: Human amygdala Visium
description: Seven donors, BayesSpace domains with manual relabeling, lowres H&E.
default_gene: PENK
default_color: { field: domain }
palette: ../Vitessce_app/build/handoff/palette.json     # { "visium_semisupervised": { "CeA": "#8b2e17", ... } }
thumbnail_sample: vis_Br8325
layout: { mode: grid }
fields:
  - { id: domain, name: Spatial domain, type: categorical, palette_key: visium_semisupervised, aliases: { AI: IA } }
  - { id: total_counts, name: Total counts, type: continuous }
  - { id: detected_genes, name: Detected genes, type: continuous }
  - { id: mito_percent, name: Mito %, type: continuous }
samples:
  - path: ../Vitessce_app/spe_amy_shinyapp.rds
    platform: visium
    assay: logcounts
    id: "vis_{name}"
    name: "{name} (Visium)"
    group: "{name}"
    fields:
      domain: BS_k16_Semisupervised_wAI
      total_counts: sum_umi
      detected_genes: sum_gene
      mito_percent: { column: expr_chrM_ratio, scale: 100 }
```

The `aliases` line changes codes, so this edit rebuilds the seven samples once; every later edit that the
table above marks "seconds" is just that.

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
