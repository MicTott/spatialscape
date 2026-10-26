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

`init` prints what it took for granted, one block per entry, so nothing is silently assumed:

```
assumed for analysis/spe_dlpfc.rds:
  platform: visium (guessed from array_col, array_row columns)
  coordinates: full-resolution pixels; microns from the spot spacing (100 um) when `build` runs
  expression: assay logcounts (also: counts); counts are log-normalized by build, anything else is taken as already log-normalized
  annotations: domain <- BayesSpace_harmony_09 (9 levels), total_counts <- sum_umi, mito_percent <- expr_chrM_ratio
```

The platform is guessed from the columns: SpaceRanger's `array_row` / `array_col` mean Visium when the grid
fits one Visium array (128 x 224 positions at most) or the spots split into capture areas of Visium size
(stitched donors with a `capture_area` column), and Visium HD when the grid is larger; Xenium's
`transcript_counts` / `cell_area` mean Xenium; with no evidence it is
`visium` and the yaml's `platform:` comment says "the default". `--platform` overrides the guess. A column's
note carries its NA count (`9 levels: L1, L2, ...; 120 NA`), and a single file that holds several sections
(a `sample_id` or `capture_area` column with several values) gets a warning and a commented `subset:` line,
because one entry draws them as one sample.

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
| `overrides` | | settings for single samples, keyed by sample id: `{ Br9902_1: { images: [] }, Br2743: { name: Br2743 (replicate) } }` |

The cache keeps every colData column, so editing `fields:` never reconverts. Re-saving the object or
changing `assay`, `sample_col`, `embedding` or `object` converts again and removes the old copy. The cache
is a sibling of the bundle, so uploading `bundles/<id>` never includes it.

## One file, several samples

A sample may keep only part of a file: `subset: { column: broad_celltype, values: [Excitatory] }`. Three
entries with the same `path` and different subsets turn one snRNA-seq object into three panels, which is how
per-class UMAPs (excitatory, inhibitory, non-neuronal) are shown side by side. `layout: { columns: 3 }` then
fixes the grid so rows and columns mean something (species by cell class, donor by condition). The same
split turns one h5ad that holds several sections into one sample per section; `init` warns when it sees
such a file and writes the first `subset:` line as a comment.

## Globs and templates

A `glob:` entry expands to one sample per matching path, sorted. Inside that entry these placeholders are filled per match:

| Placeholder | Value |
|---|---|
| `{name}` | the folder containing the matched file (`Br2743` for `visium/Br2743/adata.zarr`), or the sample id for an R object |
| `{stem}` | the file name without `.h5ad` / `.zarr` |
| `{dir}` | the containing folder's full path |
| `{i}` | the match index, from 0 |

If `id` is omitted it defaults to a sanitized `{name}`.

One sample of a glob (or of an R object) can differ from the rest through `overrides:`, a map from the
sample's `{name}` (its `{stem}` in flat layouts, or its rendered id) to the keys that change. Dictionaries
such as `fields` merge into the entry's; lists and scalars replace them. A key that names no sample is an
error, so a typo cannot silently do nothing.

```yaml
  - glob: "hd/*/adata.h5ad"
    platform: visium_hd
    id: "hd_{name}"
    overrides:
      Br9902_1: { images: [] }                       # this section's H&E does not match its cells
      Br8667_2: { fields: { note: qc_flag } }        # one more annotation on one section
```

## `platforms` and `defaults`

`defaults` is merged into every sample; `platforms.<platform>` is merged into samples of that platform; the sample's own keys win. Dictionaries merge deeply, so a sample can add one field without repeating the others. Mapping `fields` in a platform block instead of on each entry is the usual way to keep several globs of the same platform consistent.

## Automatic discovery

- `fields: auto` exposes every categorical column with 2 to 200 levels and every numeric column whose name looks like a QC metric (count, sum, detected, percent, ratio, area, score, umi, genes, mito, nucleus, transcript, total). Columns such as `sample_id`, barcodes and indices are skipped. The menu that `init` writes is the explicit version of this; `auto` remains valid for yamls written by hand.
- `images: auto` (the default for spatial samples) looks next to the data for `image.ome.zarr` or any `*.ome.zarr`, then a SpaceRanger `spatial/` folder (`tissue_hires_image.png` + `scalefactors_json.json`, which also supplies the micron scale), then a Xenium morphology focus image (the `morphology_focus/` folder, `morphology_focus.ome.tif`, then `morphology_mip.ome.tif`; read at about 0.85 µm per pixel).
- Fields that samples map without a declaration are declared automatically; the type is inferred from the data and the display name from the column.

Declare a field explicitly when you want a display name, a palette key, aliases (merge labels), an explicit category order, or a fixed range for a continuous field.

## Shared vocabularies across platforms

Two samples that map different obs columns to the **same field id** share one vocabulary: a label gets one code and one color everywhere. That is how a Visium domain column and a Xenium domain column both become "Spatial domain" with consistent colors. Labels only ever append to a vocabulary, so rebuilding one sample never changes the codes of the others.

Colors come from the palette file (`{vocabulary: {label: "#hex"}}`, with `palette_key` naming which block to use, comma-separated for fallbacks), then a fixed qualitative palette, then generated hues.

## Beyond the basics

- [Genome tracks](./tracks) for ATAC and multiome samples.
- [Metadata and comparisons](./comparisons): sample-level keys the viewer splits by, and differential expression results beside the cells.
- Every key, with its type and default, in the [dataset.yaml schema](../reference/dataset-schema).

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
