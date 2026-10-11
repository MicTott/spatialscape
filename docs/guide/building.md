# Building and validating

```bash
spatialscape build dlpfc.yaml              # -> bundles/dlpfc next to the yaml (or -o <dir>)
```

`build` brings the bundle in line with the yaml and the source files, validates the result and renders
thumbnails. Rerun it after any edit: it does only the work the edit requires. A Xenium donor with 270k
cells and 366 genes takes a few seconds to build, a Visium donor with 36k genes about fifteen, and a
sample that did not change takes none.

## What happens per sample

1. **Read** the AnnData / SpatialData table (R objects were converted first, see below), resolve `fields: auto` and `images: auto`, declare any undeclared fields.
2. **Expression**: detect counts vs log-normalized, drop all-zero genes, compute each gene's maximum, quantize to 8 bits (`round(255 · x / max)`, with any non-zero value kept ≥ 1), and write a gene-major Zarr v3 array sharded into ~128 MB files. Optionally keep a float16 copy (`keep_f16`).
3. **Geometry**: convert coordinates to microns, apply `transform`, shift the origin to the bounding box corner, record the bounding box and a default point radius per platform.
4. **Observations**: shuffle rows once with a fixed seed (the viewer draws a prefix of the shuffled rows at low zoom), write positions, categorical codes against the dataset vocabularies, numeric columns, and the cell ids in blocks.
5. **Polygons** (if configured): match `cell_id` to the object, pack vertices as centroid deltas.
6. **Images**: convert to an OME-Zarr pyramid with the same flip/rotation as the points, record pixel size and offset in microns.
7. **Outlines**: for every categorical field on spatial samples, trace region boundaries (rasterize, majority-smooth over 150 µm, remove features under 300 µm, marching squares, simplify).
8. **Fingerprint**: write `build.json` into the sample folder (what the next build compares against).

Then the dataset-level files: `manifest.json`, `genes.json`, `features.json`, `thumbnail.png`, and `thumbnail.png` per sample.

## What a rebuild does

Every built sample folder carries `build.json`, a fingerprint of what went into it: the resolved sample
settings, the size and modification time of each input file, the declarations of the fields it maps
(type, vocabulary, category order, aliases), the shard settings and the format version. The next `build`
recomputes the fingerprint from the yaml and the files and decides per sample:

| Situation | Action | Reason shown |
|---|---|---|
| not in the bundle yet | build | `new` |
| an input file changed (re-exported h5ad, new image next to it, edited parquet) | build | `source changed` |
| its settings changed (fields mapping, coords, microns, transform, images, polygons, expression, ...) | build | `settings changed` |
| a field it maps was given a different `type`, `vocabulary`, `categories` or `aliases` | build | `field declarations changed` |
| the bundle format or build recipe changed with a new spatialscape version | build | `format changed` |
| none of the above | skip | `unchanged` |

Samples the yaml no longer lists are deleted. Names, group labels, the palette, the opening gene and
annotation, the layout, feature groups and `thumbnail_sample` are not part of the fingerprint: they live
in `manifest.json`, which every `build` rewrites together with `genes.json`, `features.json` and the
thumbnails. That is why renaming or recoloring takes seconds.

- `build --dry-run` prints this table for the current state and writes nothing.
- `build --force` rebuilds every sample.
- R objects listed under `samples:` are converted into `bundles/.cache/<id>/` on the first build and reused afterwards; the cache is replaced when the object or its conversion settings change (see [R objects as samples](./dataset-yaml#r-objects-as-samples)).
- A bundle built before fingerprints existed is rebuilt once in full, then behaves as above.

::: tip Vocabularies stay stable
When some samples are kept, the vocabularies they use are kept too: a rebuilt sample's labels get the
same codes as before and new labels are appended, so colors never shift under samples that did not
change. When every sample is rebuilt, vocabularies start fresh in the declared order.
:::

## Other commands on a bundle

| Task | Command |
|---|---|
| Re-trace outlines with different smoothing | `spatialscape outlines dlpfc.yaml --smooth-um 100 --min-feature-um 200` |
| Re-render thumbnails around another section | set `thumbnail_sample` and `build`, or `spatialscape thumbnails bundles/dlpfc --hero vis_Br8325` |

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
