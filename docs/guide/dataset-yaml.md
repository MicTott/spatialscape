# Writing dataset.yaml

A dataset yaml describes one dataset: its samples, the annotations to expose, and a few display defaults.
You rarely write one from scratch: `init` writes it as a menu of the data, and three mechanisms keep it
short even for many samples.

## Start from a menu

```bash
spatialscape init analysis/spe_dlpfc.rds --id dlpfc --name "Human DLPFC"     # an R object
spatialscape init "visium/*/adata.h5ad" --platform visium --id dlpfc         # or AnnData files
```

`init` reads the data once and writes `dlpfc.yaml` where you ran it (`-o` puts it elsewhere). The file is
complete and builds as written, but it is meant to be edited:

```yaml
id: dlpfc
name: Human DLPFC
# default_gene: SNAP25                       # gene shown on open (default: the most variable gene)
default_color: { field: domain }             # annotation shown on open; or { gene: SNAP25 }
# palette: colors.json                       # { "domain": { "L1": "#F0027F", ... } }; a field uses it through palette_key
# thumbnail_sample: vis_Br2743               # section drawn on the gallery card (default: the first)
layout: { mode: grid }                       # or strip; gutter_fraction: 0.1 spaces sections out

fields:                                      # display names; add palette_key, aliases or categories here
  - { id: domain, name: Spatial domain, type: categorical }
  - { id: total_counts, name: Total counts, type: continuous }
  - { id: detected_genes, name: Detected genes, type: continuous }
  - { id: mito_percent, name: Mito %, type: continuous }

samples:
  - path: analysis/spe_dlpfc.rds             # SpatialExperiment, 12 samples: Br2743, Br3942, ... (one sample per sample_id)
    platform: visium                         # or visium_hd, xenium, merfish
    assay: logcounts                         # drawn as expression; also in the object: counts
    # sample_col: sample_id                  # colData column that splits the object into samples
    id: "vis_{name}"                         # {name} = the sample_id value
    name: "{name} (Visium)"
    group: "{name}"
    fields:                                  # field id: column. Delete a line to hide an annotation, uncomment one to add it
      domain: BayesSpace_harmony_09          # 9 levels: L1, L2, L3, WM, ...
      total_counts: sum_umi                  # numeric 512..6.1e4
      detected_genes: sum_gene               # numeric 300..9.8e3
      mito_percent: { column: expr_chrM_ratio, scale: 100 }   # numeric 0.001..0.4 -> shown as percent
      # domain: BayesSpace_harmony_16        # alternative; 16 levels: Sp16D1, Sp16D2, ...
      # subject: subject                     # 3 levels: Br2743, Br3942, Br6423
      # position: position                   # 2 levels: 0, 300
    # not listed: sample_id, in_tissue, array_row, array_col (ids and layout columns)
```

Three things to know about the menu:

- **What gets mapped.** The first column that looks like a spatial domain or cluster becomes `domain`, the
  first that looks like a cell type becomes `celltype`, and the usual QC metrics are matched by name
  (`total_counts`, `detected_genes`, `mito_percent`, with a ratio scaled to percent). Everything else is a
  comment with its type and levels. If nothing looks like a domain or a cell type, every small categorical
  column is mapped under its own id.
- **Deleting a line hides an annotation; uncommenting adds one.** A field id is shared by every sample that
  maps it, so two platforms mapping different columns to `domain` get one legend and one set of colors.
- **`build --dry-run`** shows the expanded sample list and what a build would do, without writing anything.

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
  - path: visium/spe_visium.rds           # an R object: one sample per sample_id, converted by build
    platform: visium
    id: "vis_{name}"
    name: "{name} (Visium)"
    group: "{name}"
  - path: sce_bla.rds                     # an R object without spatialCoords: one embedding sample
    id: sn
    name: snRNA-seq (BLA, 5 donors)
    fields: { celltype: fine_celltype, total_umi: sum }
```

## R objects as samples

A `samples:` entry whose `path` is an `.rds` / `.rda` file is an R object. `build` converts it once, in
Python (no R needed), into a cache next to the bundle (`bundles/.cache/<id>/`), and expands it into one
sample per `sample_col` value (a `SpatialExperiment`) or one embedding sample drawn by its UMAP (an object
without `spatialCoords`). The entry's other keys apply to those samples; `{name}` in templates is the sample
id.

| Key | Default | Meaning |
|---|---|---|
| `assay` | `logcounts` | assay drawn as expression (`counts` works too; `build` log-normalizes it) |
| `sample_col` | `sample_id` | colData column that splits a spatial object into samples |
| `embedding` | UMAP if present | reducedDims entry for objects without spatialCoords |
| `object` | | which object to take from an `.rda` that holds several |
| `microns` | spot spacing (Visium) | `{ microns_per_unit: 0.2525 }` for Visium HD; Xenium and MERFISH objects are taken as microns |

The cache keeps every colData column, so editing `fields:` never reconverts. Re-saving the object or
changing `assay`, `sample_col`, `embedding` or `object` converts again and removes the old copy. The cache
is a sibling of the bundle, so uploading `bundles/<id>` never includes it.

## Globs and templates

A `glob:` entry expands to one sample per matching path, sorted. Inside that entry these placeholders are filled per match:

| Placeholder | Value |
|---|---|
| `{name}` | the folder containing the matched file (`Br2743` for `visium/Br2743/adata.zarr`), or the sample id for an R object |
| `{stem}` | the file name without `.h5ad` / `.zarr` |
| `{dir}` | the containing folder's full path |
| `{i}` | the match index, from 0 |

If `id` is omitted it defaults to a sanitized `{name}`.

## `platforms` and `defaults`

`defaults` is merged into every sample; `platforms.<platform>` is merged into samples of that platform; the sample's own keys win. Dictionaries merge deeply, so a sample can add one field without repeating the others. Mapping `fields` in a platform block instead of on each entry is the usual way to keep several globs of the same platform consistent.

## Automatic discovery

- `fields: auto` exposes every categorical column with 2 to 200 levels and every numeric column whose name looks like a QC metric (count, sum, detected, percent, ratio, area, score, umi, genes, mito, nucleus, transcript, total). Columns such as `sample_id`, barcodes and indices are skipped. The menu that `init` writes is the explicit version of this; `auto` remains valid for yamls written by hand.
- `images: auto` (the default for spatial samples) looks next to the data for `image.ome.zarr` or any `*.ome.zarr`, then a SpaceRanger `spatial/` folder (`tissue_hires_image.png` + `scalefactors_json.json`, which also supplies the micron scale), then a Xenium `morphology_focus*.ome.tif`.
- Fields that samples map without a declaration are declared automatically; the type is inferred from the data and the display name from the column.

Declare a field explicitly when you want a display name, a palette key, aliases (merge labels), an explicit category order, or a fixed range for a continuous field.

## Shared vocabularies across platforms

Two samples that map different obs columns to the **same field id** share one vocabulary: a label gets one code and one color everywhere. That is how a Visium domain column and a Xenium domain column both become "Spatial domain" with consistent colors. Labels only ever append to a vocabulary, so rebuilding one sample never changes the codes of the others.

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
