# Writing dataset.yaml

`dataset.yaml` describes one dataset: its samples, the annotations to expose, and a few display defaults. Three mechanisms keep it short even for many samples.

## Start from a draft

```bash
spatialscape init "visium/*/adata.h5ad" --platform visium --id my_atlas --name "My atlas" -o dataset.yaml
spatialscape plan dataset.yaml          # expanded sample list, nothing built
```

`init` writes one glob entry per pattern with `fields: auto` and `images: auto`; `plan` shows exactly which samples a build would produce.

## A complete example

```yaml
id: amygdala
name: Human amygdala
description: Visium, Visium HD and Xenium sections with spatial domains and cell types.
default_gene: PENK
default_color: { field: domain }          # or { gene: PENK }
palette: palette.json                     # optional {vocabId: {label: "#hex"}}
layout: { mode: grid }                    # grid | strip
thumbnail_sample: vis_Br8325              # which section the gallery card shows

feature_groups:                           # non-gene features get their own tab
  - { id: rctd, name: Cell type weights (RCTD), pattern: "^RCTD: ", units: weight }

fields:                                   # declare only what needs a name, palette, alias or order
  - { id: domain, name: Spatial domain, type: categorical, palette_key: "visium_domain,xenium_domain", aliases: { AI: IA } }
  - { id: celltype, name: Cell type, type: categorical, palette_key: cell_type }
  - { id: total_counts, name: Total transcripts, type: continuous }

platforms:                                # shared per platform; samples can override
  xenium:
    fields: { domain: Banksy_domains, celltype: first_type, total_counts: total_counts }
    images: []
  visium:
    fields: { domain: BS_k16, total_umi: sum_umi }
    images: auto

samples:
  - glob: xenium/Br*/adata.zarr           # one sample per match
    platform: xenium
    id: "xen_{name}"
    name: "{name} (Xenium)"
    group: "{name}"
  - glob: visium/Br*/adata.zarr
    platform: visium
    id: "vis_{name}"
    name: "{name} (Visium)"
    group: "{name}"
  - id: sn
    name: snRNA-seq (BLA, 5 donors)
    platform: snrnaseq
    kind: embedding
    path: sce.h5ad
    coords: obsm/X_umap
    fields: { celltype: fine_celltype, total_umi: sum }
```

## Globs and templates

A `glob:` entry expands to one sample per matching path, sorted. Inside that entry these placeholders are filled per match:

| Placeholder | Value |
|---|---|
| `{name}` | the folder containing the matched file (`Br2743` for `visium/Br2743/adata.zarr`) |
| `{stem}` | the file name without `.h5ad` / `.zarr` |
| `{dir}` | the containing folder's full path |
| `{i}` | the match index, from 0 |

If `id` is omitted it defaults to a sanitized `{name}`.

## `platforms` and `defaults`

`defaults` is merged into every sample; `platforms.<platform>` is merged into samples of that platform; the sample's own keys win. Dictionaries merge deeply, so a sample can add one field without repeating the others.

## Automatic discovery

- `fields: auto` exposes every categorical column with 2 to 200 levels and every numeric column whose name looks like a QC metric (count, sum, detected, percent, ratio, area, score, umi, genes, mito, nucleus, transcript, total). Columns such as `sample_id`, barcodes and indices are skipped.
- `images: auto` (the default for spatial samples) looks next to the data for `image.ome.zarr` or any `*.ome.zarr`, then a SpaceRanger `spatial/` folder (`tissue_hires_image.png` + `scalefactors_json.json`, which also supplies the micron scale), then a Xenium `morphology_focus*.ome.tif`.
- Fields that samples map without a declaration are declared automatically; the type is inferred from the data and the display name from the column.

Declare a field explicitly when you want a display name, a palette key, aliases (merge labels), an explicit category order, or a fixed range for a continuous field.

## Shared vocabularies across platforms

Two samples that map different obs columns to the **same field id** share one vocabulary: a label gets one code and one color everywhere. That is how a Visium domain column and a Xenium domain column both become "Spatial domain" with consistent colors. Labels only ever append to a vocabulary, so `add-sample` never changes existing codes.

Colors come from the palette file (`{vocabulary: {label: "#hex"}}`, with `palette_key` naming which block to use, comma-separated for fallbacks), then a fixed qualitative palette, then generated hues.

## Reference

Every key is listed with its type and default in the [dataset.yaml schema](../reference/dataset-schema).

## One field, several units

Samples that store the same quantity in different units can still share one field. Give the mapping in long form with a `scale` that multiplies the column:

```yaml
platforms:
  visium:
    fields: { mito_percent: { column: expr_chrM_ratio, scale: 100 } }   # ratio -> percent
  visium_hd:
    fields: { mito_percent: subsets_Mito_percent }                      # already a percent
```

Keeping annotations shared this way is what makes the sidebar short: one *Total counts*, one *Mito %*, one *Cell type* per reference, each listing every sample that carries it.
