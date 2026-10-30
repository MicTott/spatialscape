# Sequencing-based spatial

Visium, Visium HD, Slide-seq, Stereo-seq and the like: barcoded spots, beads or bins on a tissue section,
whole-transcriptome counts, usually an H&E image of the same section. The viewer draws the spots at their true size
on the image, with spatial domains as colours.

## The minimum

A SpaceRanger-style folder, an AnnData file or a `SpatialExperiment` saved from R:

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

A spot drawn too large or too small against the image, or a scale bar that reads wrong, means this value; the
[scale rules](../preparing-data#getting-the-scale-right) list what the build tries, in order.

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
      - { path: spaceranger/Br2743/spatial/tissue_hires_image.png, pixel_size: auto }   # same frame as the spots
      - { path: scans/Br2743.tif, pixel_size: 0.5, translate: [120, -40] }               # a scan: µm per pixel and an offset
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

Build time and bundle size scale with the bin count: an 8 µm-binned 6.5 mm section is about 600k bins and builds in
a minute; 2 µm bins are sixteen times that and are better served segmented into cells first.

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

`platform: other` draws cells at 5 µm unless `point_radius` says otherwise and takes coordinates as microns unless
`microns:` says otherwise; the platform bar labels the sample by its name.

## Next

- [Where your data comes from](../preparing-data) for the R, Python and SpatialData paths and image placement.
- [Using the viewer](../viewer): blends, the filter, lasso.
- [Single-cell and multiome](./single-cell) to put a reference beside the sections with shared colours.
