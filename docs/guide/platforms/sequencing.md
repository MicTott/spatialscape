# Sequencing-based spatial

Visium, Visium HD, Slide-seq and Stereo-seq measure expression at spots, beads or bins on a tissue section.
Spatialscape places these observations at their physical scale and can display a registered image beneath
them. Color observations by gene expression or annotations such as spatial domains.

## Required input

A SpaceRanger-style folder, an AnnData file, a `SpatialExperiment` or a Seurat object with Visium slices saved from
R, or a SpatialData store:

```bash
spatialscape init analysis/spe_visium.rds --id vis         # one sample per sample_id
spatialscape build vis.yaml && spatialscape serve bundles --open
```

```yaml
samples:
  - path: analysis/spe_visium.rds
    platform: visium
    assay: logcounts
    id: "vis_{name}"
    fields: { domain: BayesSpace_domain, total_counts: sum_umi }
```

Everything in the viewer is laid out in microns, so the scale of the coordinates has to be known. For Visium it
is inferred from the spot spacing (100 µm) or SpaceRanger's scale factors; for the others you set it once:

| Platform | `platform:` | Coordinates | Set |
|---|---|---|---|
| Visium | `visium` | full-resolution pixels | nothing: the spot spacing or `scalefactors_json.json` gives the scale |
| Visium HD | `visium_hd` | full-resolution pixels | `microns: { microns_per_unit: <microns_per_pixel> }` from `scalefactors_json.json` |
| Slide-seq / Slide-seqV2 | `other` | bead-array pixels | `microns: { microns_per_unit: 0.65 }`, `point_radius: 5` |
| Stereo-seq | `other` | DNB units or bins | `microns: { microns_per_unit: 0.5 }` for DNBs, times the bin size for bins; `point_radius` half the bin |

If the spot size or scale bar is incorrect, check the coordinate scale and image placement. The
[scale rules](../preparing-data#getting-the-scale-right) list how the build resolves the coordinate units.

## The optional layers

| Layer | Key | Where it comes from |
|---|---|---|
| H&E image | `images: auto` (default) | SpaceRanger's `spatial/tissue_hires_image.png` + `scalefactors_json.json`, found next to the data; the H&E inside an R object; or any PNG / TIFF / OME-Zarr with `pixel_size` |
| Spot or bin shapes | `polygons:` | an `obsm` array of shape (n, vertices, 2) is picked up on its own (`segmentations`, `cell_boundaries`, …), as SpatialExperiment exports of HD segmentations carry; else a long table |

### Visium

The H&E is found on its own. An R object usually carries only SpaceRanger's low-resolution image (600–1,200 px,
about 20 µm per pixel), which looks blocky up close; `build` says so when that is all it found. For detail, point
the sample at the hires PNG or the full scan:

```yaml
    images:
      - { path: spaceranger/Br5292/spatial/tissue_hires_image.png, pixel_size: auto }   # same frame as the spots
      - { path: scans/Br5292.tif, pixel_size: 0.5, translate: [120, -40] }               # a scan: µm per pixel and an offset
```

A slide scan shared by two sections is masked to each section's spots automatically. Several capture areas in one
object (a `capture_area` column) build as one sample; `subset:` splits them.

### Visium HD

Bins are drawn as squares at the bin pitch and cells (from a segmentation) as their shapes when the object carries
them. The one thing to set is the pixel size:

```yaml
  - glob: hd/*/adata.h5ad
    platform: visium_hd
    id: "hd_{name}"
    microns: { microns_per_unit: 0.2525 }      # SpaceRanger's microns_per_pixel for this slide
```

Build time and bundle size depend on the number of bins retained. For the same area, 2 µm bins produce
sixteen times as many observations as 8 µm bins. Use coarser bins or a cell segmentation when the finer
resolution is not needed for the analysis.

### Slide-seq and Stereo-seq

No image, beads or DNBs in their own pixel units, and often a single file for the whole puck or chip:

```yaml
  - path: pucks/Puck_200115_08.h5ad
    platform: other
    id: puck_08
    microns: { microns_per_unit: 0.65 }
    point_radius: 5                            # a 10 µm bead
    images: []
```

`platform: other` draws cells at 5 µm unless `point_radius` says otherwise and needs `microns:` (`{ already_microns:
true }` when the coordinates are microns; the build stops and says so without it); the platform bar labels the sample by its name.

## Next

- [Preparing data](../preparing-data) for the R, Python and SpatialData paths and image placement.
- [Using the viewer](../viewer): blends, the filter, lasso.
- [Single-cell and multiome](./single-cell) to put a reference beside the sections with shared colours.
