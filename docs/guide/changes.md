# Making changes

Everything the viewer shows comes from two files you own: `dataset.yaml` (one per dataset) and
`site/datasets.json` (the gallery). This page is the map from "I want to change X" to the line to edit and
the command to rerun. Commands that only rewrite metadata take a second; `build` reprocesses the data.

| I want to | Edit | Then run |
|---|---|---|
| Rename the dataset, change its description | `name:` / `description:` in `dataset.yaml` | `spatialscape refresh dataset.yaml -o bundles/<id>` |
| Choose the gene shown on open | `default_gene: SNAP25` | `refresh` |
| Open on an annotation instead | `default_color: { field: domain }` | `refresh` |
| Name an annotation properly ("Spatial domain", not "BS k16 …") | declare it under `fields:` with `name:` | `refresh` |
| Show fewer / other annotations | the `fields:` mapping under `platforms:` (or per sample) | `build` |
| Use my paper's colors | `palette: colors.json` plus `palette_key:` on the field | `refresh` |
| Fix the order of categories | `categories: [L1, L2, …]` on the field | `build` |
| Merge spellings (`AI` and `IA`) | `aliases: { AI: IA }` on the field | `build` |
| Put QC metrics in one unit across platforms | `{ column: expr_chrM_ratio, scale: 100 }` in the mapping | `build` |
| Change which section is the thumbnail | `thumbnail_sample: vis_Br8325` | `spatialscape thumbnails bundles/<id> --hero vis_Br8325` |
| Space the sections out | `layout: { gutter_fraction: 0.3 }` | `refresh` |
| Re-export one sample | fix the file, keep the yaml | `spatialscape add-sample dataset.yaml -o bundles/<id> --sample <sample>` |
| Add a sample to a dataset | add it to `samples:` (or let the glob find it) | `add-sample … --sample <new>` |
| Add a dataset to the site | a new `dataset.yaml`, built into `bundles/<other>` | `spatialscape site build bundles -o site` |
| Add a paper link, tags or a "coming soon" card | `site/datasets.json` | nothing; rerunning `site build` keeps your edits |
| Add a navigation bar above the viewer | a `site:` block in `site/datasets.json` | nothing |

## The same yaml, before and after

`spatialscape init` writes the minimum. This is the amygdala Visium dataset as `init` left it:

```yaml
id: amygdala_visium
name: Human amygdala Visium
platforms:
  visium:
    fields: auto
    images: auto
samples:
  - glob: data/visium/*/adata.h5ad
    platform: visium
    id: vis_{name}
    name: "{name} (Visium)"
    group: "{name}"
```

and after naming things, picking colors and the opening view:

```yaml
id: amygdala_visium
name: Human amygdala Visium
description: Seven donors, BayesSpace domains with manual relabeling, lowres H&E.
default_gene: PENK
default_color: { field: domain }
palette: ../Vitessce_app/build/handoff/palette.json     # { "visium_semisupervised": { "CeA": "#8b2e17", ... } }
thumbnail_sample: vis_Br8325
fields:
  - { id: domain, name: Spatial domain, type: categorical, palette_key: visium_semisupervised, aliases: { AI: IA } }
  - { id: total_counts, name: Total counts, type: continuous }
  - { id: detected_genes, name: Detected genes, type: continuous }
  - { id: mito_percent, name: Mito %, type: continuous }
platforms:
  visium:
    fields: { domain: BS_k16_Semisupervised_wAI, total_counts: sum_umi, detected_genes: sum_gene, mito_percent: { column: expr_chrM_ratio, scale: 100 } }
    images: auto
samples:
  - glob: data/visium/*/adata.h5ad
    platform: visium
    id: vis_{name}
    name: "{name} (Visium)"
    group: "{name}"
```

Because the annotation columns changed, this one needs `build`; afterwards every item in the table above
that says `refresh` is instant.

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

## When to rebuild from scratch

`build` is safe to rerun at any time: it rewrites the bundle from the yaml and the source files. Rerun it
when annotation columns, images, polygons or the expression layer change. `refresh` is for everything
that is only a name, a color, an order or a default.
