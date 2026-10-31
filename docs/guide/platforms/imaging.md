# Imaging-based spatial

Xenium, MERSCOPE (MERFISH), CosMx, Molecular Cartography and the like: cells segmented from a fluorescence image,
a few hundred to a few thousand genes, and every decoded transcript with a position. The viewer draws the cells as
dots, then as their shapes, with the image underneath and the molecules on top once zoomed in.

## The minimum

An object with cells × genes and coordinates in microns is enough:

```bash
spatialscape init xenium/*/adata.h5ad --id xen        # one sample per folder
spatialscape build xen.yaml && spatialscape serve bundles --open
```

```yaml
samples:
  - glob: xenium/*/adata.h5ad
    platform: xenium                                  # or merfish; other platforms: other
    id: "xen_{name}"
    fields: { celltype: cell_type, total_counts: transcript_counts }
```

Coordinates are taken as microns for `xenium` and `merfish`. A platform that writes pixels (CosMx) needs the scale:
`microns: { microns_per_unit: 0.12028 }`.

## The optional layers

Each is one key on the sample. For a Xenium `outs/` folder `init` writes all of them when it finds the files; for
other platforms it writes the keys as comments with the column names to fill in.

| Layer | Key | Xenium (defaults) | MERSCOPE | CosMx |
|---|---|---|---|---|
| Fluorescence image | `images: auto`, or a path | `morphology_focus/` found on its own, read at 0.85 µm/px | `images/mosaic_DAPI_z3.tif` with `pixel_size` and `translate` from `micron_to_mosaic_pixel_transform.csv` | per-FOV TIFFs; stitch first |
| Cell boundaries | `polygons:` | `cell_boundaries.parquet` (`cell_id`, `vertex_x`, `vertex_y`) | export the geometry to a long table (below) | `*-polygons.csv`: `cellID`, `x_global_px`, `y_global_px` |
| Nuclei, for comparison | `segmentations:` | `nucleus_boundaries.parquet` found next to the cell boundaries | a second long table | – |
| Transcripts | `molecules:` | `transcripts.parquet` (`feature_name`, `x_location`, `y_location`, `qv` ≥ 20, `cell_id`, `overlaps_nucleus`) | `detected_transcripts.csv`: `gene`, `global_x`, `global_y`, `cell_id` (−1 = none) | `*_tx_file.csv`: `target`, `x_global_px`, `y_global_px`, `cell_ID` (0 = none), `CellComp` |

Tables are Parquet, CSV or TSV, gzipped or not. Control features are dropped by name (10x's `NegControl*` and
`Unassigned*`, Vizgen's `Blank-*`, NanoString's `NegPrb*`, `SystemControl*`, `FalseCode*`). The Xenium column
is what we build the amygdala from; the MERSCOPE and CosMx columns follow the formats the vendors document and
have not been built here, so a report of one that works (or does not) is welcome.

### Xenium

```yaml
  - glob: xenium/*/outs/adata.h5ad
    platform: xenium
    id: "xen_{name}"
    polygons: { path: "{dir}/cell_boundaries.parquet" }     # shapes; nuclei are found next to it
    molecules: { path: "{dir}/transcripts.parquet" }        # 170-400 MB per section; delete the line to leave them out
```

`images: auto` (the default) finds the morphology image (`morphology_focus/` in XOA 2 and later,
`morphology_focus.ome.tif` in XOA 1) and the pixel size from `experiment.xenium`. The files are JPEG 2000 and need
`pip install "spatialscape[images]"`; without it the image is skipped with a note. Cell ids must match: the
boundary and transcript files of a *re-segmentation* (Xenium Ranger, Baysor, Proseg) go with the matrix of that
run, not the original, and the build log reports the match rate.

If the object's coordinates were transposed or mirrored after segmentation (an export through another tool),
set `polygons.affine` once; the molecules and the nuclei inherit it, and `images` take `transpose` / `flip`.
[Troubleshooting](../troubleshooting#warning-polygon-centroids-sit-far-from-their-cells) has the recipe.

### MERSCOPE

```yaml
  - path: region_0/adata.h5ad
    platform: merfish
    id: mer_r0
    polygons: { path: region_0/boundaries_long.parquet, id_column: cell, x_column: x, y_column: y }
    molecules: { path: region_0/detected_transcripts.csv, feature_column: gene, x_column: global_x, y_column: global_y, qv_column: null, cell_column: cell_id, nucleus_column: null }
    images:
      - { path: region_0/images/mosaic_DAPI_z3.tif, kind: multichannel, pixel_size: 0.108, translate: [0, 0] }
```

Vizgen's `cell_boundaries.parquet` holds one WKB geometry per cell, not one row per vertex. Flatten it once:

```python
import geopandas as gpd, pandas as pd
g = gpd.read_parquet("region_0/cell_boundaries.parquet")
rows = [(cid, x, y) for cid, geom in zip(g["EntityID"], g.geometry) for x, y in geom.exterior.coords]
pd.DataFrame(rows, columns=["cell", "x", "y"]).to_parquet("region_0/boundaries_long.parquet")
```

The mosaic's placement comes from `micron_to_mosaic_pixel_transform.csv`: `pixel_size` is 1 over its scale,
`translate` its offset divided by the scale and negated. Coordinates and transcripts are already microns.

### CosMx

```yaml
  - path: slide1/adata.h5ad
    platform: other
    id: cosmx_s1
    microns: { microns_per_unit: 0.12028 }                  # global pixels -> um
    point_radius: 5
    polygons: { path: slide1/slide1-polygons.csv, id_column: cellID, x_column: x_global_px, y_column: y_global_px }
    molecules: { path: slide1/slide1_tx_file.csv.gz, feature_column: target, x_column: x_global_px, y_column: y_global_px, qv_column: null, cell_column: cell_ID, nucleus_column: CellComp }
```

The flat files number cells per FOV (`cell_ID`) while AtoMx exports name them `c_<slide>_<fov>_<cell>`; the
boundary ids must spell the matrix's `obs_names` the same way, and the build log says how many matched. One
`microns:` covers coordinates, boundaries and transcripts, since all three share the global pixel frame.

### CODEX, PhenoCycler, MICS, IMC (multiplexed protein imaging)

Antibody panels of 30 to 100 markers imaged on one section give a many-channel image, a segmentation mask and a
cells × markers intensity table, usually with gated cell types on top. The scverse toolbox
[spatialproteomics](https://sagar87.github.io/spatialproteomics) keeps all of that in one object (an xarray
Dataset saved as Zarr), and spatialscape reads that object directly:

```yaml
defaults:
  platform: codex
  microns: { microns_per_unit: 0.5 }        # the scan's pixel size: coordinates are pixels (PhenoCycler-Fusion 0.5, Keyence 20x 0.377)
  expression: { normalized: raw }           # per-cell intensities summarised by spatialproteomics, kept as they are
  fields: { cell_type: labels, neighborhood: neighborhoods, pd1_positive: PD-1_binarized, degree: degree }
samples:
  - glob: cores/LN_*.zarr                   # one object per core
    id: "{stem}"
    polygons: { labels: "{dir}/{stem}.zarr/_segmentation" }     # the label mask, traced into cell outlines
    images:
      - { id: stains, name: Stains, path: "{dir}/{stem}.zarr/_image_raw", kind: multichannel, pixels_per_unit: 1.0, crop: false }
```

What the reader takes from the object: `_intensity` (cells × channels) as the expression layer, with the channel
names as features; `_obs` as annotations, `_labels` and `_neighborhoods` turned into names through the object's
property tables and their colours kept, every `<marker>_binarized` column as a positive / negative category, the
gating tree's levels (`labels_0`, `labels_1`, ...) as categories too, and the centroids as coordinates. The image
is the `_image_raw` (or `_image`) array, written band by band with the channel names from the object; `_segmentation`
becomes the cell shapes. A label mask from any other pipeline (MCMICRO, Cytokit, QuPath) works the same way as a
TIFF or PNG with `polygons: { labels: mask.tif }`, next to a table of cells read as any other AnnData.

In the viewer the channel list shows every marker; up to six draw at once, chosen by clicking, and only those are
fetched. Colour cells by any marker's intensity from the gene box, or by a gating-tree level from the annotations.

## What each layer costs

| Layer | Build | Bundle | Viewer |
|---|---|---|---|
| Image at 0.85 µm/px | 10–60 s per section, 3 GB of memory | about 200 MB | tiles in view only |
| Cell shapes | 2 s per 250k cells | 10 MB per 250k cells (44 B per cell) | replaces the dots when a cell is 6 px across; at most 40,000 cells per pane |
| Nuclei | as shapes | 7–10 MB per section | dashed over the cells, with a cells / median area table |
| Transcripts | 20–50 s per 50–120 M molecules, 7 B each of memory | 3.5 B per molecule: 170–400 MB per section | about one molecule per screen pixel, a million in a large window |

The whole-section build of a 250k-cell Xenium sample with all four layers takes about two minutes and lands at
roughly 600 MB. Leave out the transcripts and it is a third of that. Every layer is added or removed by editing
the sample's entry and rerunning `build`; only that sample is rebuilt.

## Next

- [Comparing segmentations](../viewer#comparing-segmentations) and [molecules in the viewer](../viewer#molecules).
- [Where your data comes from](../preparing-data) for R objects, SpatialData stores and image placement.
- [Making changes](../changes) maps every edit to the line to change.
