# Bundle format (formatVersion 1)

A bundle is a directory of static files. Everything the viewer needs is addressable by URL with plain GET and Range requests.

```
<dataset>/
  manifest.json                 dataset description (schema: python/src/sscape/manifest.py, app/src/data/manifest.ts)
  genes.json                    sorted union of plain gene symbols across samples (autocomplete)
  features.json                 {genes, groups:[{id, name, units, features:[{id, label}]}]} — feature groups (e.g. RCTD weights)
  build-info.json
  samples/<sampleId>/
    genes.json                  gene order of expr rows for this sample
    expr.zarr/                  Zarr v3 group
      u8      uint8   (nGenes, nObs)   chunk (1, nObs), shard (shardGenes, nObs), zstd
      gmax    float32 (nGenes)         dequantize: value = u8 / 255 * gmax[gene]
      f16     float16 (nGenes, nObs)   optional (--f16 / keep_f16), not read by the viewer
    obs.zarr/                   Zarr v3 group
      xy      float32 (nObs, 2)        microns, sample-local frame, y down, origin at bbox min
      order   uint32  (nObs)           source row index of each bundle row (rows are shuffled once, seeded)
      cat/<fieldId>  uint16 (nObs)     codes into manifest.vocabularies[field.vocabulary].categories
      num/<fieldId>  float32 (nObs)
    ids/<block>.json            obs names in blocks of manifest.samples[].idBlock (default 65536)
    <imageId>.ome.zarr/         OME-Zarr (NGFF 0.4, zarr v2), axes c,y,x, 512x512 chunks, relative pyramid scales
    outlines/<fieldId>.json     {bin, paths:[{c: code, p: [[x, y], ...]}]} boundary polylines in µm (sample-local frame)
    polygons.offsets.u32        uint32[nObs+1] vertex start per cell (bundle row order; zero-length = no polygon)
    polygons.i16                int16[(dx, dy) * 10] vertex deltas from the cell centroid, 0.1 µm units
```

## Why this layout

- **Gene-major uint8**: colouring N cells by a gene needs exactly N bytes. One inner chunk per gene means one range request per gene per sample; shards keep the file count small (a 20k-gene sample is ~40 files, not 20k).
- **Shuffled rows**: any prefix of the arrays is a uniform random subsample, so the viewer draws the first k rows at overview zoom (level of detail) without extra data.
- **Dataset-level vocabularies**: categorical codes are shared across samples and platforms, so the same label has the same code and colour everywhere.
- **Images carry their own geometry in the manifest** (`pixelSize` in µm per level-0 pixel, `translate` in µm), independent of NGFF transforms.

## manifest.json

See the pydantic models in `python/src/sscape/manifest.py`; field names are camelCase and mirrored one-to-one in `app/src/data/manifest.ts`. Key entries:

- `defaultColor`: `{kind: "gene", gene}` or `{kind: "field", field}`.
- `layout`: `{mode: "grid" | "strip", gutterFraction, order: [sampleId]}`.
- `vocabularies[id]`: `{categories[], colors[], aliases{}}`. A missing label is the category `"NA"`.
- `fields[]`: `{id, name, type: "categorical", vocabulary}` or `{id, name, type: "continuous", range?, colormap?}`.
- `samples[]`: `{id, name, platform, kind: "spatial" | "embedding", group?, nObs, nGenes, bbox, toDataset (3x3 row-major affine), pointRadius (µm), expr{kind, sharded, shardGenes}, fields[], images[]{id, name, path, kind, pixelSize, translate, size, channels?, defaultOpacity}}`.

An snRNA-seq object is a `kind: "embedding"` sample whose `xy` is a UMAP rescaled to a fixed extent; it shares the renderer, genes and vocabularies with the spatial samples.
