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

### SpatialExperiment / SingleCellExperiment → h5ad

```r
library(zellkonverter)
writeH5AD(spe, "Br2743.h5ad", X_name = "logcounts")
```

zellkonverter writes `spatialCoords()` into `obsm/spatial`, `colData` into `obs`, and `rowData` into `var`. If you only want a subset of `colData`, trim it first; it keeps the file small and `fields: auto` tidy.

anndataR works without a Python environment:

```r
anndataR::write_h5ad(anndataR::as_AnnData(sce), "sce.h5ad")
```

### Visium scale factors

Visium coordinates in a `SpatialExperiment` are full-resolution pixels. Pass the scale through one of these:

- `microns: { spot_diameter_fullres: 89.4 }` using `scaleFactors()` / `spot_diameter_fullres` (55 µm spots), or
- `microns: { scalefactors_json: outs/spatial/scalefactors_json.json }`, or
- put `uns["spot_nn_spacing_level0_px"]` (center-to-center spot spacing in coordinate units, 100 µm) in the object; the CLI finds it automatically.

### Images from R

Point `images:` at the SpaceRanger `tissue_hires_image.png` with `pixels_per_unit: <tissue_hires_scalef>`, or at any OME-Zarr / TIFF / PNG that shares the coordinate frame. If the folder has a SpaceRanger `spatial/` directory, `images: auto` handles it.

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

Add `polygons: { path: cell_boundaries.parquet }` with `cell_id`, `vertex_x`, `vertex_y` columns in the same frame as the coordinates. The build matches `cell_id` to `obs_names` and reports how many cells matched; a low match rate means the segmentation does not correspond to the cells in the object.

## snRNA-seq and other embeddings

Declare the sample with `kind: embedding` and point `coords` at the UMAP (`obsm/X_umap`). It shares genes, annotations and the renderer with the spatial samples and appears in the embedding view beside the tissue. When its cell type labels use the same names as a spatial annotation, map both to the same field id and they share one vocabulary and one set of colors.
