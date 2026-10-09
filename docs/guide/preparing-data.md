# Preparing your data

The CLI reads three input types. Whatever you start from, each **sample** (one tissue section, or one embedding) becomes one entry in `dataset.yaml`.

| Input | Path in `dataset.yaml` | Notes |
|---|---|---|
| AnnData `.h5ad` | `path: sample.h5ad` | Read with `anndata.read_h5ad` |
| AnnData Zarr (v2 or v3) | `path: sample.zarr` | Read with `anndata.read_zarr` |
| SpatialData Zarr | `path: store.zarr`, `table: <key>` | The table is read as AnnData; coordinates come from its `obsm` |

## What the CLI needs from each sample

- **Expression**: `X` or a layer, cells × genes. Counts are detected and converted to log1p CP10k; log-normalized data is used as is (`expression.normalized` overrides the guess).
- **Coordinates**: `obsm/spatial` by default, or any `obsm` key, or two obs columns (`coords: "obs/x,obs/y"`). Units can be pixels or microns; see [scale](#getting-the-scale-right).
- **Annotations**: obs columns, categorical or numeric. `fields: auto` picks sensible ones.
- **Gene names**: `var_names`, or a var column via `gene_column`.
- **Images** (optional): see [images](#images).

## From R

### The short way: one helper, one folder per sample

[`spe_to_spatialscape.R`](https://github.com/MicTott/spatialscape/blob/main/examples/scripts/spe_to_spatialscape.R)
writes each sample of a `SpatialExperiment` as `adata.h5ad` next to a SpaceRanger-style `spatial/` folder
(H&E PNG plus `scalefactors_json.json`), which the CLI recognises without any image or scale settings:

```r
source("https://raw.githubusercontent.com/MicTott/spatialscape/main/examples/scripts/spe_to_spatialscape.R")
spe_to_spatialscape(spe, "exports/visium", assay = "logcounts",
                    cols = c("BS_k16_Semisupervised_wAI", "sum_umi", "sum_gene", "expr_chrM_ratio"))
```

```bash
spatialscape init "exports/visium/*/adata.h5ad" --platform visium --id my_visium -o dataset.yaml
spatialscape build dataset.yaml -o bundles/my_visium
```

`cols` limits `colData` to the annotations you want to show (leave it out to keep everything). Images come
from `imgData()` (hires if present, else lowres); the spot diameter is measured from the spot spacing. The
helper needs zellkonverter, png, RANN and jsonlite.

### By hand: SpatialExperiment / SingleCellExperiment → h5ad

```r
library(zellkonverter)
sce <- as(spe, "SingleCellExperiment")
reducedDim(sce, "spatial") <- spatialCoords(spe)      # becomes obsm/spatial
writeH5AD(sce, "Br2743.h5ad", X_name = "logcounts")
```

`colData` becomes `obs` and `rowData` becomes `var`. Trim `colData` first if it carries dozens of QC columns;
it keeps the file small and `fields: auto` tidy. anndataR works without a Python environment:

```r
anndataR::write_h5ad(anndataR::as_AnnData(sce), "sce.h5ad")
```

### Visium scale factors

Visium coordinates in a `SpatialExperiment` are full-resolution pixels. Pass the scale through one of these:

- a `spatial/scalefactors_json.json` next to the file with `spot_diameter_fullres` (55 µm spots) or `microns_per_pixel`, which `images: auto` also reads, or
- `microns: { spot_diameter_fullres: 89.4 }` in `dataset.yaml`, or
- `uns["spot_nn_spacing_level0_px"]` in the object (centre-to-centre spot spacing in coordinate units, 100 µm); the CLI finds it automatically.

### Images from R

`imgRaster(spe, sample, "hires")` is a raster you can write with `png::writePNG`; put it at
`spatial/tissue_hires_image.png` next to the h5ad with the matching `tissue_hires_scalef` in
`scalefactors_json.json` and the CLI picks it up. Or point `images:` at any OME-Zarr / TIFF / PNG that shares
the coordinate frame, with `pixels_per_unit` set to the image's scale factor.

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
3. Visium samples look for `uns["spot_nn_spacing_level0_px"]`, then SpaceRanger scalefactors under `uns["spatial"]`.
4. Embeddings (`kind: embedding`) are rescaled so their longest side equals `extent` (default 5000).

If none applies, the build stops with a message naming the sample.

## Images

Supported inputs: OME-Zarr directories (NGFF 0.4 or 0.5), TIFF / OME-TIFF, PNG and JPEG. RGB images are H&E-style; multichannel images (DAPI plus markers) get per-channel colors and windows.

Two placements:

- **Same frame as the coordinates** (`pixel_size: auto`). The image's level-0 pixels map onto the coordinate units through `pixels_per_unit` (1.0 when coordinates are already in level-0 pixels of that image; `tissue_hires_scalef` when coordinates are full-resolution pixels and the image is the hires PNG).
- **Explicit** (`pixel_size: <µm per pixel>` plus optional `translate`).

Flips and rotations in `transform:` apply to the points and the image together, so registration survives.

## Cell boundary polygons

Polygons can come from two places:

- **A long-format parquet file** such as Xenium Ranger's `cell_boundaries.parquet`: `polygons: { path: cell_boundaries.parquet }` with `cell_id`, `vertex_x`, `vertex_y` columns (names configurable). The build matches `cell_id` to `obs_names`.
- **An `obsm` array** of shape `(n_obs, n_vertices, 2)` already in the object, as SpatialExperiment exports of Visium HD segmentations often carry: `polygons: { obsm: segmentations }`. An `obsm` key named `segmentations`, `cell_boundaries`, `boundaries` or `polygons` with that shape is picked up automatically when `polygons` is not set.

Vertices must be in the same frame as the coordinates. If the object's coordinates were transposed, mirrored or shifted after segmentation, map the vertices with `affine: [a, b, c, d, e, f]` (`x' = a·x + b·y + c`, `y' = d·x + e·y + f`): a transpose is `[0, 1, 0, 1, 0, 0]`, a mirror across both axes with extents `Xmax`, `Ymax` is `[0, -1, Ymax, -1, 0, Xmax]`. The sample's own `transform:` and micron scaling are applied afterwards, so one setting keeps points, image and polygons together.

The build reports how many cells matched and warns when polygon centroids sit far from their cells, which is the signature of a frame mismatch. A low match rate means the boundary file comes from a different segmentation run than the cells in the object.

## snRNA-seq and other embeddings

Declare the sample with `kind: embedding` and point `coords` at the UMAP (`obsm/X_umap`). It shares genes, annotations and the renderer with the spatial samples and appears in the embedding view beside the tissue. When its cell type labels use the same names as a spatial annotation, map both to the same field id and they share one vocabulary and one set of colors.
