# Where your data comes from

Usually nothing needs preparing: point `init` at what you have, then read the `assumed for` block it prints
(platform, coordinate units, the layer drawn) and fix whatever it got wrong in the yaml. The cases that need a
hand (scale, a file that pools several sections, Ensembl ids, images) are on this page. A **sample** is one tissue section or one embedding; files give one sample each, an R object gives one per `sample_id` (or one embedding).

| Input | Entry in the dataset yaml | Notes |
|---|---|---|
| R object: `SpatialExperiment` / `SingleCellExperiment` as `.rds` or `.rda` | `path: spe.rds` | parsed in Python, no R needed; converted once into `bundles/.cache/` ([details](#from-r)) |
| AnnData `.h5ad` | `path: sample.h5ad` | read with `anndata.read_h5ad` |
| AnnData Zarr (v2 or v3) | `path: sample.zarr` | read with `anndata.read_zarr` |
| SpatialData Zarr | `path: store.zarr`, `table: <key>` | the table is read as AnnData; coordinates come from its `obsm` |

Many files of one kind go in as a single `glob:` entry (`glob: visium/*/adata.h5ad`); `init` writes these entries for you.

## What the CLI needs from each sample

- **Expression**: `X` or a layer, cells × genes. Counts are detected and converted to log1p CP10k; log-normalized data is used as is (`expression.normalized` overrides the guess).
- **Coordinates**: `obsm/spatial` by default, or any `obsm` key, or two obs columns (`coords: "obs/x,obs/y"`). Units can be pixels or microns; see [scale](#getting-the-scale-right).
- **Annotations**: obs columns, categorical or numeric. `init` maps the likely ones and lists the rest as comments.
- **Gene names**: `var_names`, or a var column via `gene_column`. An object indexed by Ensembl ids with a `gene_name` or `symbol` column is named by the symbols on its own, so genes match across samples and are what the search box expects.
- **Images** (optional): see [images](#images). Shapes, molecules and nuclei: see [the family pages](#layers-beyond-the-matrix).

## From R

You do not need to export anything from R. Save your object and point the CLI at it:

```bash
spatialscape init analysis/spe_visium.rds --id my_visium      # reads the object once, writes my_visium.yaml
spatialscape build my_visium.yaml                             # converts it (cached), builds every sample
```

The yaml lists the object as one `samples:` entry; `{name}` is the sample id:

```yaml
samples:
  - path: analysis/spe_visium.rds        # one sample per sample_id
    platform: visium
    assay: logcounts                     # also in the object: counts
    id: "vis_{name}"
    name: "{name} (Visium)"
    group: "{name}"
    fields: { domain: BayesSpace_domain, total_counts: sum_umi, detected_genes: sum_gene, mito_percent: { column: expr_chrM_ratio, scale: 100 } }
```

`build` parses the `.rds` (or `.rda`) in Python and writes, for a `SpatialExperiment`, one folder per sample
into `bundles/.cache/<id>/`: `adata.h5ad` (the assay as `X`, every `colData` column as `obs`,
`spatialCoords()` as `obsm/spatial`), the H&E from `imgData()` as `spatial/tissue_<id>_image.png`, and
`spatial/scalefactors_json.json` with the image scale factor plus a spot diameter measured from the spot
spacing. That is the SpaceRanger layout, so no image or scale settings are needed. Later builds reuse the
cache; it is replaced when the object or its conversion settings change.

Most objects carry only SpaceRanger's low-resolution H&E (`lowres`, 600-1200 px wide, about 20 µm per pixel), which looks blocky up close; `build` says so when that is all it found. For detail, give each sample an `images:` entry pointing at `tissue_hires_image.png` or the full-resolution scan, as in [dataset.yaml](./dataset-yaml).

A `SingleCellExperiment` without `spatialCoords` (an snRNA-seq reference) becomes one embedding sample drawn
by its UMAP (`platform: snrnaseq`, `kind: embedding`, `coords: obsm/X_umap`, all set for you).

A **Seurat object** (v3 to v5 assays, split v5 layers joined back together) works the same way. The gene assay
(the default assay, unless that is a peak assay) is drawn as expression: `assay:` names one of its layers, `data`
by default (`logcounts` means `data`), or `counts`. Every other assay becomes a set of features next to the genes,
named with a prefix: a Signac `ChromatinAssay` or any assay whose features are coordinates as `peak: chr1-100-200`,
assays with "activity" in their name as `activity: <gene>`, chromVAR as `motif: <name>`, anything else as
`<assay>: <feature>`. `meta.data` becomes `obs` (plus the active ident as `ident`), and `embedding:` names a
reduction (`wnn.umap`, `umap.rna`, ...; a UMAP is picked when none is given). `spatialscape inspect x.rds` lists
all of this, including the fragment files a `ChromatinAssay` was built from. When those records map cells to
barcodes (an object pooled from several runs), two columns are added to `obs`, `fragment_run` and
`fragment_barcode`, so a `tracks:` block can say `sample_column: fragment_run`, `barcode_column: fragment_barcode`
and list one fragment file per run; `init` writes that block, commented, with the paths as the object recorded
them. Seurat spatial images (`VisiumV1` and friends) are not read yet; export those as a `SpatialExperiment`.

Settings on the entry:

- `assay: counts` works too; `build` log-normalizes counts.
- `microns: { microns_per_unit: 0.2525 }` for Visium HD, where the spot-spacing rule does not apply (SpaceRanger prints `microns_per_pixel` in `scalefactors_json.json`). Xenium and MERFISH objects are taken as microns.
- `sample_col` if samples are not in `sample_id`; `embedding` to pick a reducedDims entry; `object` to pick one object out of an `.rda`.

The object is held in memory while it is read (once by `init`, once by the first `build`), so expect roughly
the memory R needs for it. HDF5-backed assays (`DelayedArray`) are not read; realize them in R first with
`assay(x, "logcounts") <- as(assay(x, "logcounts"), "dgCMatrix")`.

### Writing h5ad yourself instead

If you prefer to control the export, zellkonverter works:

```r
library(zellkonverter)
sce <- as(spe, "SingleCellExperiment")
reducedDim(sce, "spatial") <- spatialCoords(spe)      # becomes obsm/spatial
writeH5AD(sce, "Br2743.h5ad", X_name = "logcounts")
```

Then give the CLI the scale and image yourself: a `spatial/` folder next to the file with
`tissue_hires_image.png` and a `scalefactors_json.json` (`tissue_hires_scalef`, `spot_diameter_fullres` or
`microns_per_pixel`), or `microns: { spot_diameter_fullres: 89.4 }` in `dataset.yaml`, or
`uns["spot_nn_spacing_level0_px"]` in the object.

## From Python

AnnData objects need nothing special:

```python
adata.write_h5ad("sample.h5ad")       # or adata.write_zarr("sample.zarr")
```

For 10x outputs, `scanpy.read_visium` / `squidpy.read.visium` leave `uns["spatial"][lib]["scalefactors"]` in place, and the CLI reads `microns_per_pixel` or `spot_diameter_fullres` from there. Xenium `cells.csv` / `cells.parquet` coordinates are already microns.

## From SpatialData

```yaml
- id: s1
  path: sample.zarr
  table: table            # which table to use
  coords: obsm/spatial
```

Images inside the SpatialData store are not yet discovered automatically; point `images:` at the OME-Zarr inside the store.

## Getting the scale right

Everything in the viewer is laid out in **microns**, so Visium spots are 55 µm wide next to 10 µm Xenium cells, and the scale bar is honest. The rules, in order:

1. `microns:` in `dataset.yaml` wins (`already_microns`, `microns_per_unit`, `spot_diameter_fullres`, `spot_spacing`, `scalefactors_json`).
2. Xenium and MERFISH samples are assumed to be in microns.
3. Visium samples look for `uns["spot_nn_spacing_level0_px"]`, then SpaceRanger scalefactors under `uns["spatial"]`, then a `spatial/scalefactors_json.json` next to the file (also when `images:` is listed or `[]`).
4. Embeddings (`kind: embedding`) are rescaled so their longest side equals `extent` (default 5000).

If none applies, the build stops with a message naming the sample.

## Images

Supported inputs: OME-Zarr directories (NGFF 0.4 or 0.5), TIFF / OME-TIFF, PNG and JPEG. RGB images are H&E-style; multichannel images (DAPI plus markers) get per-channel colors and windows.

Two placements:

- **Same frame as the coordinates** (`pixel_size: auto`). The image's level-0 pixels map onto the coordinate units through `pixels_per_unit` (1.0 when coordinates are already in level-0 pixels of that image; `tissue_hires_scalef` when coordinates are full-resolution pixels and the image is the hires PNG).
- **Explicit** (`pixel_size: <µm per pixel>` plus optional `translate`).

Flips and rotations in `transform:` apply to the points and the image together, so registration survives.

Multichannel images get their channel names from the file's OME metadata, a distinct colour each (blue first,
for the nuclear stain), and a display window fitted to the signal (the 0.5th to 99.9th percentile of non-zero
pixels) unless `channels:` gives one. Without that, a 16-bit fluorescence channel whose signal sits in the low
thousands would be drawn against 0 to 65,535 and look black. The viewer draws the first six channels.

**Xenium morphology** is found on its own next to a Xenium sample (`images: auto`): the 2D focus image
(`morphology_focus/` in XOA 2 and later, with one file per stain, or `morphology_focus.ome.tif` in XOA 1, then
`morphology_mip.ome.tif`), never the 3D `morphology.ome.tif` stack, with the pixel size from `experiment.xenium`.
It is read at about 0.85 µm per pixel, the stored level four times coarser than the scan, where a nucleus is 7 to
12 px across. A machine without the memory for that reads the next coarser level instead and says so. Full
resolution waits for a streaming converter; `max_size:` on an explicit image entry picks another level. These files are JPEG 2000 compressed and
need the optional `imagecodecs` package: `pip install "spatialscape[images]"`. Without it the image is skipped
with a note and the sample builds without it.

`max_size:` bounds what an image costs to read. A pyramidal file is read at the level that gives the largest copy
within it; a larger level, or a file without pyramid levels (10x's CytAssist and Visium HD TIFFs), is reduced
band by band while it is read, so the whole slide is never in memory. A read that would need more than a sixth of
the machine's memory (or of a cgroup or SLURM limit) is refused with the size it would need and the way out: set or
lower `max_size:` on the image.

**OME-Zarr in, OME-Zarr out.** An image that is already an OME-Zarr pyramid, the output of `bioformats2raw`,
a SpatialData image or an earlier bundle's image, is copied into the bundle as it is: no decode, no re-encode,
no limit on its size, and hard links rather than a second copy when the bundle sits on the same disk. Channel
names and colours come from the pyramid's own metadata when the yaml gives none, and display windows are
fitted on a coarse level unless the pyramid carries a narrower one. Such an image is not cropped to the points,
and a setting that moves pixels (`transform.flip` or `rotate`, `transpose`, `flip`, `mask`, `max_size`) switches
back to reading and writing it. For a whole-slide scan of many channels, convert once with `bioformats2raw` and
let every build pass it through.

`max_size:` is also the only knob for how fine a copy the bundle keeps. `pixels_per_unit` describes the source
scan and never changes with the level read: a Xenium-layout image stays at 4.705882 pixels per µm (the 0.2125 µm
scan) whether it is kept at full, half or quarter resolution. Halving `pixels_per_unit` to "read at half
resolution" declares a pixel twice as large as it is, and the image lands at twice its size over the cells.

## Layers beyond the matrix

Cell shapes, molecules, nuclei and embeddings each come from a file the platform writes; which ones, where they
are and what they cost is on the family pages: [sequencing-based](./platforms/sequencing),
[imaging-based](./platforms/imaging), [single-cell](./platforms/single-cell). Boundary and transcript tables are
read as Parquet, CSV or TSV, gzipped or not, with the column names given in the yaml when they are not 10x's.
