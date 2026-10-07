# Building and validating

```bash
spatialscape build dataset.yaml -o bundles/my_atlas
```

`build` runs every sample through the same steps, validates the result, and renders thumbnails. A Xenium donor with 270k cells and 366 genes takes a few seconds; a Visium donor with 36k genes takes about fifteen.

## What happens per sample

1. **Read** the AnnData / SpatialData table, resolve `fields: auto` and `images: auto`, declare any undeclared fields.
2. **Expression**: detect counts vs log-normalized, drop all-zero genes, compute each gene's maximum, quantize to 8 bits (`round(255 · x / max)`, with any non-zero value kept ≥ 1), and write a gene-major Zarr v3 array sharded into ~128 MB files. Optionally keep a float16 copy (`keep_f16`).
3. **Geometry**: convert coordinates to microns, apply `transform`, shift the origin to the bounding box corner, record the bounding box and a default point radius per platform.
4. **Observations**: shuffle rows once with a fixed seed (the viewer draws a prefix of the shuffled rows at low zoom), write positions, categorical codes against the dataset vocabularies, numeric columns, and the cell ids in blocks.
5. **Polygons** (if configured): match `cell_id` to the object, pack vertices as centroid deltas.
6. **Images**: convert to an OME-Zarr pyramid with the same flip/rotation as the points, record pixel size and offset in microns.
7. **Outlines**: for every categorical field on spatial samples, trace region boundaries (rasterize, majority-smooth over 150 µm, remove features under 300 µm, marching squares, simplify).

Then the dataset-level files: `manifest.json`, `genes.json`, `features.json`, `thumbnail.png`, and `thumbnail.png` per sample.

## Incremental workflows

| Task | Command |
|---|---|
| Rebuild one sample after fixing its data | `spatialscape add-sample dataset.yaml -o bundle --sample vis_Br2743` |
| Change display names, palette, feature groups or layout only | `spatialscape refresh dataset.yaml -o bundle` |
| Re-trace outlines with different smoothing | `spatialscape outlines dataset.yaml -o bundle --smooth-um 100 --min-feature-um 200` |
| Re-render thumbnails, pick the hero section | `spatialscape thumbnails bundle --hero vis_Br8325` |

`add-sample` refuses to reorder an existing vocabulary; new labels are appended so other samples' codes stay valid. Pass `--allow-vocab-append false` to make any new label an error.

## Validation

`build` ends with the same checks as `spatialscape validate bundle`:

- manifest parses; every referenced vocabulary, field and sample exists
- expression arrays have the right shape and gene-major chunking, and one chunk reads back
- observation arrays, id blocks and polygon files match `nObs`
- categorical codes are below their vocabulary's size
- images open and match their recorded size

Against a URL, `validate` also fetches the manifest and one expression chunk with a `Range` header and reports missing CORS headers or a non-206 response. Run it after every upload.

## Sizes to expect

| Data | Per sample |
|---|---|
| Xenium, 250k cells × 366 genes | 20 to 30 MB |
| Visium, 30k spots × 36k genes | 90 to 100 MB (90% zeros compress well) |
| snRNA-seq, 15k nuclei × 34k genes | about 110 MB |
| Visium lowres H&E OME-Zarr | 1 to 3 MB |
| Outlines, all fields | 0.1 to 1.5 MB |

The first page view of a dataset downloads positions (8 bytes per cell), the default annotation (2 bytes per cell) and one gene (1 byte per cell). Everything else loads on demand.
